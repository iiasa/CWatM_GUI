"""
Excel workbook viewer/editor for the CWatM GUI (Excel ▸ Crops/Reservoirs).

``ExcelSheetWindow`` opens **the whole** ``.xlsx`` workbook (the settings
``Excel_settings_file``) in an **editable table that reproduces the sheet's cell
colours** (fill + font) with openpyxl. Like in Excel, a **tab bar below the
table** (above the row×column info line) switches between the workbook's sheets
(``Crops``, ``Reservoirs``, ``Reservoirs_downstream``, …). Bottom buttons:
**Load / Reload / Save / Save As / Close**.

Rendering uses a **lazy** ``QTableView`` + ``ExcelSheetModel``
(``QAbstractTableModel``): the view only asks the model for the cells that are
actually visible, so even a 300k+-cell sheet opens instantly and scrolls smoothly
(no per-cell widgets are built up-front). One model is kept **per sheet** (built
on first visit, then cached), so edits on one tab survive switching to another;
Save flushes every model and writes the workbook back through openpyxl, so all
untouched sheets and the styling are preserved.

**Spreadsheet behaviour** (the parts that make it feel like Excel):

* **Formulas** — ``2+3.5``, ``2 + I3``, ``=(A1+B1)/2``, ``=SUM(C2:C10)`` are
  computed over the sheet's cells (``src/gui/utils/cell_formula.py``); the cell
  shows the result, editing it shows the formula again, and it recalculates when
  a referenced cell changes. Saving writes the **computed value**.
* **Clipboard** — Ctrl+C / Ctrl+X / Ctrl+V / Delete over a rectangular selection,
  as tab-separated text, so blocks move in and out of Excel itself.
* **Fill handle** — the small square at the selection's bottom-right corner;
  drag it down/up/right/left to autofill (copy, number series, text+number,
  weekday/month lists — ``src/gui/utils/cell_fill.py``).
* **Text columns** are shown at **half** their content width with **word wrap**;
  resizing a column re-wraps it (the visible rows are re-heighted).
* **Symbol toolbar** — right of the sheet name: copy, cut, paste, delete │ undo,
  redo as plain glyph buttons (no icon files to ship). Each one simply calls what
  its keyboard shortcut calls, and greys out when it cannot be used.
* **Undo / redo** (Ctrl+Z / Ctrl+Y) — a per-sheet command stack covering cell
  edits, pastes, fills **and** whole-column/row inserts and deletes.
* **Unsaved changes are never lost silently** — Reload, Load and closing the
  window ask first when any sheet holds edits (``closeEvent``: Save / Discard /
  Cancel).
"""

import os
import re

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableView,
    QFileDialog, QMessageBox, QAbstractItemView, QTabBar, QMenu, QToolButton,
    QStyleOptionViewItem,
)
from PySide6.QtCore import (
    Qt, QAbstractTableModel, QModelIndex, QRect, QTimer, QItemSelection,
    QItemSelectionModel, QThread, Signal,
)
from PySide6.QtGui import (
    QColor, QBrush, QFont, QIcon, QPainter, QPen, QKeySequence, QGuiApplication,
    QPalette,
)

from src.gui.utils import theme
from src.gui.utils.cell_fill import extend_series
from src.gui.utils.cell_formula import FormulaError, evaluate, is_formula
from src.gui.utils.window_geometry import GeometryMemoryMixin
from src.gui.utils.gui_log import get_logger

log = get_logger("excel_sheet_window")


def _argb_to_qcolor(argb):
    """openpyxl ARGB string ('FF00A87C' or '00A87C') -> QColor, or None if it is not
    a plain rgb colour (theme/indexed colours are left uncoloured)."""
    if not isinstance(argb, str):
        return None
    s = argb.strip()
    if len(s) == 8:
        a, rgb = int(s[0:2], 16), s[2:]
    elif len(s) == 6:
        a, rgb = 255, s
    else:
        return None
    try:
        r, g, b = int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16)
    except ValueError:
        return None
    if a == 0:            # fully transparent fill == "no fill"
        return None
    return QColor(r, g, b)


def _sheet_key(name):
    """A sheet name reduced to letters/digits, lowercase, plural 's' dropped per word:
    ``Reservoir_transfers`` / ``Reservoirs transfer`` -> ``reservoirtransfer``, while
    ``Reservoirs`` -> ``reservoir`` stays distinct from ``reservoirdownstream``. Used
    to look a sheet up in ``ExcelSheetWindow._SHEET_MIN_CHARS``."""
    words = re.split(r"[^A-Za-z0-9]+", name or "")
    return "".join(w.lower().rstrip("s") for w in words if w)


def _column_index(letters):
    """Excel column letter -> 0-based index ('A' -> 0, 'F' -> 5, 'AB' -> 27)."""
    index = 0
    for ch in letters.upper():
        index = index * 26 + (ord(ch) - 64)
    return index - 1


def _parse_cell(text):
    """Turn edited cell text back into a number when it looks like one (blank -> None),
    so the saved xlsx keeps numeric types."""
    t = text.strip()
    if t == "":
        return None
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    return text


class _LineClip:
    """What the **header's** Copy put on the clipboard: a whole column or a whole
    row, and where it came from.

    Only ``Copy column``/``Copy row`` in a header menu creates one — an ordinary
    Ctrl+C over cells never claims to be a line, however the cells were selected.
    That is what lets the header menus refuse to paste a **row** as a column (or
    the other way round) and to paste a line into a **different sheet**.

    ``text`` is the clipboard content at the time of the copy: if the clipboard has
    since changed (the user copied something else, here or in another program) the
    record is stale and is ignored — ``current()`` checks that."""

    _active = None                 # the one live record, application-wide

    def __init__(self, kind, block, source, text):
        self.kind = kind           # 'column' | 'row'
        self.block = block
        self.source = source       # (workbook path, sheet name)
        self.text = text

    @classmethod
    def remember(cls, kind, block, source, text):
        cls._active = cls(kind, block, source, text)

    @classmethod
    def current(cls):
        """The live record, or None when nothing (or something else) is on the
        clipboard now."""
        clip = cls._active
        if clip is None:
            return None
        if QGuiApplication.clipboard().text() != clip.text:
            cls._active = None     # overwritten by another copy -> just a block
            return None
        return clip


def _fmt_value(v):
    """Cell text for a value: floats limited to **max 5 decimals** (trailing zeros
    stripped), everything else verbatim."""
    if isinstance(v, float):
        s = f"{v:.5f}".rstrip("0").rstrip(".")
        return "0" if s in ("", "-", "-0") else s
    return "" if v is None else str(v)


class ExcelSheetModel(QAbstractTableModel):
    """Lazy model over an openpyxl worksheet: values, per-cell fill/font colours and
    editing are served on demand (only for the cells the view actually shows).

    **Undo/redo** is a command stack of three shapes - a block of cells (with the
    text that re-creates them before and after), an inserted band of rows/columns
    (undone by deleting it again) and a deleted band (undone by re-inserting it and
    writing its captured contents back). Cell contents are captured as the *text*
    that re-creates them, so an undo works the same before and after a Save."""

    undoStateChanged = Signal()      # the toolbar's Undo/Redo buttons follow this

    _UNDO_DEPTH = 200                # commands kept
    _UNDO_CELLS = 100000             # biggest deletion whose contents are captured

    def __init__(self, ws, parent=None):
        super().__init__(parent)
        self._ws = ws
        self._nrows = max(ws.max_row, 1)
        self._ncols = max(ws.max_column, 1)
        self._edits = {}          # (row0, col0) -> new text (differs from the cell)
        self._style_cache = {}    # (row0, col0) -> (bg QBrush|None, fg QBrush|None, QFont|None)
        # Live formulas of this session: (row0, col0) -> source text ('=A1+2').
        # They are kept after a save (the save writes their *value*) so they keep
        # recalculating; _calc caches the results until any cell changes.
        self._formulas = {}
        self._calc = {}
        self._calc_stack = set()
        self._text_col_cache = {}
        # Inserted rows/columns change the worksheet itself (not just _edits), so
        # they need their own "there is something to save" flag. Bolding a block is
        # the same case: the cell's font changed, its text did not.
        self._structural = False
        self._styled = False
        # Undo/redo command stacks; _suspend is on while an undo/redo replays a
        # command, so the replay does not record itself.
        self._undo_stack = []
        self._redo_stack = []
        self._suspend = False

    # ---- shape
    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self._nrows

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self._ncols

    # ---- helpers
    def _cell(self, r, c):
        return self._ws.cell(row=r + 1, column=c + 1)

    def _orig_text(self, r, c):
        v = self._cell(r, c).value
        return "" if v is None else str(v)

    def _display_text(self, r, c):
        """Text shown in the cell: a formula's **result**, an edit's text, else the
        stored value (floats limited to max 5 decimals, trailing zeros stripped)."""
        key = (r, c)
        if key in self._formulas:
            return _fmt_value(self._compute(r, c))
        if key in self._edits:
            return self._edits[key]
        return _fmt_value(self._cell(r, c).value)

    # ---- formulas
    def _resolve(self, r, c):
        """Value of a cell as seen by a formula (edits and formulas included)."""
        if not (0 <= r < self._nrows and 0 <= c < self._ncols):
            return None
        key = (r, c)
        if key in self._formulas:
            v = self._compute(r, c)
            if isinstance(v, str) and v.startswith("#"):
                raise FormulaError(v)          # an error propagates to the user
            return v
        if key in self._edits:
            return _parse_cell(self._edits[key])
        return self._cell(r, c).value

    def _resolve_range(self, r0, c0, r1, c1):
        return [self._resolve(r, c)
                for r in range(r0, min(r1, self._nrows - 1) + 1)
                for c in range(c0, min(c1, self._ncols - 1) + 1)]

    def _compute(self, r, c):
        """The value of the formula in (r, c) - cached until any cell changes.
        Errors (and cycles) come back as their ``#…`` marker string."""
        key = (r, c)
        if key in self._calc:
            return self._calc[key]
        if key in self._calc_stack:
            raise FormulaError("#CYCLE")
        self._calc_stack.add(key)
        try:
            val = evaluate(self._formulas[key], self._resolve, self._resolve_range)
        except FormulaError as e:
            val = str(e)
        except RecursionError:
            val = "#CYCLE"
        except Exception:
            log.debug("formula %r failed", self._formulas.get(key), exc_info=True)
            val = "#ERROR"
        finally:
            self._calc_stack.discard(key)
        self._calc[key] = val
        return val

    def formula_at(self, r, c):
        """The formula source of a cell, or None."""
        return self._formulas.get((r, c))

    def _style(self, r, c):
        key = (r, c)
        cached = self._style_cache.get(key)
        if cached is not None:
            return cached
        bg = fg = font = None
        try:
            cell = self._cell(r, c)
            fill = cell.fill
            if fill is not None and fill.patternType == "solid":
                col = _argb_to_qcolor(getattr(fill.fgColor, "rgb", None))
                if col is not None:
                    bg = QBrush(col)
            f = cell.font
            if f is not None:
                fcol = _argb_to_qcolor(getattr(getattr(f, "color", None), "rgb", None))
                if fcol is not None:
                    fg = QBrush(fcol)
                if f.bold or f.italic:
                    font = QFont()
                    font.setBold(bool(f.bold))
                    font.setItalic(bool(f.italic))
        except Exception:
            log.debug("excel cell style failed", exc_info=True)
        val = (bg, fg, font)
        self._style_cache[key] = val
        return val

    # ---- data
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        if role == Qt.DisplayRole:
            return self._display_text(r, c)          # formula result / max 5 decimals
        if role == Qt.EditRole:
            if (r, c) in self._formulas:
                return self._formulas[(r, c)]        # edit the formula, not its value
            if (r, c) in self._edits:
                return self._edits[(r, c)]
            return self._orig_text(r, c)             # full precision while editing
        if role == Qt.ToolTipRole:
            f = self._formulas.get((r, c))
            return f"{f}  =  {self._display_text(r, c)}" if f else None
        if role == Qt.BackgroundRole:
            return self._style(r, c)[0]
        if role == Qt.ForegroundRole:
            return self._style(r, c)[1]
        if role == Qt.FontRole:
            return self._style(r, c)[2]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        # Row 1 (the frozen header row) is editable like every other row - it is
        # sheet data too, and renaming a column is a normal thing to want.
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole or not index.isValid():
            return False
        r, c = index.row(), index.column()
        before = self._capture([(r, c)])
        self._set_text(r, c, "" if value is None else str(value))
        self._record_cells(before)
        self._invalidate()
        return True

    # ---- undo / redo
    def _restore_text(self, r, c):
        """The text that would re-create this cell's current content - a formula's
        source, an edit's text or the stored value. A stored value that *looks* like
        a formula is escaped with ``'`` so restoring it does not turn text into a
        calculation."""
        key = (r, c)
        if key in self._formulas:
            return self._formulas[key]
        text = self._edits[key] if key in self._edits else self._orig_text(r, c)
        return "'" + text if text and is_formula(text) else text

    def _capture(self, cells):
        """{(r, c): restore text} for the given cells - the 'before' of a command."""
        return {(r, c): self._restore_text(r, c) for r, c in cells}

    @staticmethod
    def _rect_cells(r0, c0, r1, c1):
        return [(r, c) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)]

    def _record_cells(self, before):
        """Close a cell command: keep it only if something actually changed."""
        if self._suspend or not before:
            return
        after = {k: self._restore_text(*k) for k in before}
        if after != before:
            self._push({"kind": "cells", "before": before, "after": after})

    def _push(self, command):
        if self._suspend:
            return
        self._undo_stack.append(command)
        del self._undo_stack[:-self._UNDO_DEPTH]
        self._redo_stack.clear()
        self.undoStateChanged.emit()

    def _clear_undo(self):
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.undoStateChanged.emit()

    def can_undo(self):
        return bool(self._undo_stack)

    def can_redo(self):
        return bool(self._redo_stack)

    def _apply_cells(self, mapping):
        for (r, c), text in mapping.items():
            if r < self._nrows and c < self._ncols:
                self._set_text(r, c, text)

    def _replay(self, command, forward):
        kind = command["kind"]
        self._suspend = True
        try:
            if kind == "cells":
                self._apply_cells(command["after" if forward else "before"])
            elif kind == "bold":
                self._apply_bold(command["after" if forward else "before"])
            elif kind == "insert":
                (self._do_insert if forward else self._do_delete)(
                    command["at"], command["count"], command["rows"])
            elif kind == "delete":
                if forward:
                    self._do_delete(command["at"], command["count"], command["rows"])
                else:
                    self._do_insert(command["at"], command["count"], command["rows"])
                    self._apply_cells(command["cells"])
        finally:
            self._suspend = False
        self._invalidate()

    def undo(self):
        if not self._undo_stack:
            return False
        command = self._undo_stack.pop()
        self._replay(command, forward=False)
        self._redo_stack.append(command)
        self.undoStateChanged.emit()
        return True

    def redo(self):
        if not self._redo_stack:
            return False
        command = self._redo_stack.pop()
        self._replay(command, forward=True)
        self._undo_stack.append(command)
        self.undoStateChanged.emit()
        return True

    def _set_text(self, r, c, txt):
        """Store one cell's new text (no signal - the batch callers emit once).

        A leading ``'`` forces text (Excel's escape); otherwise anything
        ``is_formula`` accepts becomes a live formula for this session."""
        key = (r, c)
        if txt.startswith("'"):
            txt = txt[1:]
            self._formulas.pop(key, None)
        elif is_formula(txt):
            self._formulas[key] = txt
            self._edits[key] = txt
            return
        else:
            self._formulas.pop(key, None)
        if txt == self._orig_text(r, c):
            self._edits.pop(key, None)           # reverted -> no longer an edit
        else:
            self._edits[key] = txt

    def _invalidate(self):
        """Drop the formula cache and repaint: any cell can feed a formula, so a
        single edit may change other cells' results."""
        self._calc.clear()
        self._text_col_cache.clear()
        if self._nrows and self._ncols:
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(self._nrows - 1, self._ncols - 1),
                                  [Qt.DisplayRole, Qt.EditRole, Qt.ToolTipRole])

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        from openpyxl.utils import get_column_letter
        return get_column_letter(section + 1) if orientation == Qt.Horizontal \
            else str(section + 1)

    # ---- block operations (clipboard / fill / delete)
    def display_at(self, r, c):
        """The text shown in a cell - what Copy puts on the clipboard."""
        if 0 <= r < self._nrows and 0 <= c < self._ncols:
            return self._display_text(r, c)
        return ""

    def block_text(self, r0, c0, r1, c1):
        """A rectangular block as tab-separated lines (Excel's clipboard format)."""
        return "\n".join(
            "\t".join(self.display_at(r, c) for c in range(c0, c1 + 1))
            for r in range(r0, r1 + 1))

    def ensure_size(self, nrows, ncols):
        """Grow the model (and thereby the sheet) so a paste/fill that runs past the
        last row/column fits. openpyxl extends the worksheet on write."""
        if nrows > self._nrows:
            self.beginInsertRows(QModelIndex(), self._nrows, nrows - 1)
            self._nrows = nrows
            self.endInsertRows()
        if ncols > self._ncols:
            self.beginInsertColumns(QModelIndex(), self._ncols, ncols - 1)
            self._ncols = ncols
            self.endInsertColumns()

    def paste_block(self, row, col, rows):
        """Write ``rows`` (a list of lists of text) with its top-left at (row, col);
        returns the filled rectangle (r0, c0, r1, c1)."""
        if not rows:
            return None
        height, width = len(rows), max(len(r) for r in rows)
        self.ensure_size(row + height, col + width)
        before = self._capture(
            self._rect_cells(row, col, row + height - 1, col + width - 1))
        for dr, cells in enumerate(rows):
            for dc, txt in enumerate(cells):
                self._set_text(row + dr, col + dc, txt)
        self._record_cells(before)
        self._invalidate()
        return row, col, row + height - 1, col + width - 1

    def clear_range(self, r0, c0, r1, c1):
        """Delete key: empty every cell of the block."""
        before = self._capture(self._rect_cells(r0, c0, r1, c1))
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                self._set_text(r, c, "")
        self._record_cells(before)
        self._invalidate()

    def fill_range(self, src, dst, vertical, backwards):
        """Autofill: continue the ``src`` block (r0, c0, r1, c1) over ``dst``.

        Each line **along the fill axis** is extended on its own (a dragged column
        continues its own series), by ``cell_fill.extend_series``; a backwards
        drag extends the reversed source and writes the result outward."""
        sr0, sc0, sr1, sc1 = src
        dr0, dc0, dr1, dc1 = dst
        self.ensure_size(dr1 + 1, dc1 + 1)
        before = self._capture(self._rect_cells(dr0, dc0, dr1, dc1))
        if vertical:
            count = dr1 - dr0 + 1
            for c in range(sc0, sc1 + 1):
                values = [self.display_at(r, c) for r in range(sr0, sr1 + 1)]
                out = extend_series(list(reversed(values)) if backwards else values,
                                    count)
                rows = range(dr1, dr0 - 1, -1) if backwards else range(dr0, dr1 + 1)
                for txt, r in zip(out, rows):
                    self._set_text(r, c, txt)
        else:
            count = dc1 - dc0 + 1
            for r in range(sr0, sr1 + 1):
                values = [self.display_at(r, c) for c in range(sc0, sc1 + 1)]
                out = extend_series(list(reversed(values)) if backwards else values,
                                    count)
                cols = range(dc1, dc0 - 1, -1) if backwards else range(dc0, dc1 + 1)
                for txt, c in zip(out, cols):
                    self._set_text(r, c, txt)
        self._record_cells(before)
        self._invalidate()

    # ---- structure (insert / delete rows and columns)
    @staticmethod
    def _shift_keys(mapping, at, count, rows, remove=False):
        """Re-key ``_edits``/``_formulas`` around an insert or a delete: on an insert
        everything from ``at`` on moves by ``count``, on a delete the removed band is
        dropped and the rest moves back."""
        out = {}
        for (r, c), v in mapping.items():
            pos = r if rows else c
            if remove:
                if at <= pos < at + count:
                    continue                    # this line is gone
                if pos >= at + count:
                    pos -= count
            elif pos >= at:
                pos += count
            out[(pos, c) if rows else (r, pos)] = v
        return out

    def _after_structure_change(self, at, count, rows, remove=False):
        self._edits = self._shift_keys(self._edits, at, count, rows, remove)
        self._formulas = self._shift_keys(self._formulas, at, count, rows, remove)
        self._style_cache.clear()
        self._calc.clear()
        self._text_col_cache.clear()
        self._structural = True

    def _do_insert(self, at, count, rows):
        """Insert a band of empty rows/columns - the raw operation, used both by the
        menu (which records it for undo) and by an undo/redo replay.

        The worksheet is changed straight away (openpyxl ``insert_rows``/
        ``insert_cols``), which is what Save then writes. openpyxl moves cells and
        their styles but does **not** rewrite formulas or merged ranges, and this
        editor's own formulas are not re-pointed either - a formula referring to a
        moved cell keeps its original reference."""
        if count < 1:
            return
        begin = self.beginInsertRows if rows else self.beginInsertColumns
        end = self.endInsertRows if rows else self.endInsertColumns
        begin(QModelIndex(), at, at + count - 1)
        try:
            if rows:
                self._ws.insert_rows(at + 1, count)
                self._nrows += count
            else:
                self._ws.insert_cols(at + 1, count)
                self._ncols += count
        except Exception:
            log.debug("insert %s(%d, %d) failed", "rows" if rows else "cols",
                      at, count, exc_info=True)
        self._after_structure_change(at, count, rows)
        end()

    def _do_delete(self, at, count, rows):
        """Remove a band of rows/columns - the raw operation (see ``_do_insert``)."""
        limit = (self._nrows if rows else self._ncols) - at
        count = min(count, limit)
        if count < 1:
            return
        begin = self.beginRemoveRows if rows else self.beginRemoveColumns
        end = self.endRemoveRows if rows else self.endRemoveColumns
        begin(QModelIndex(), at, at + count - 1)
        try:
            if rows:
                self._ws.delete_rows(at + 1, count)
                self._nrows = max(self._nrows - count, 1)
            else:
                self._ws.delete_cols(at + 1, count)
                self._ncols = max(self._ncols - count, 1)
        except Exception:
            log.debug("delete %s(%d, %d) failed", "rows" if rows else "cols",
                      at, count, exc_info=True)
        self._after_structure_change(at, count, rows, remove=True)
        end()

    def insert_rows(self, at, count=1):
        """Insert ``count`` empty rows above row ``at`` (0-based), undoably."""
        if count < 1:
            return
        self._do_insert(at, count, rows=True)
        self._push({"kind": "insert", "at": at, "count": count, "rows": True})
        self._invalidate()

    def insert_columns(self, at, count=1):
        """Insert ``count`` empty columns left of column ``at`` (0-based), undoably."""
        if count < 1:
            return
        self._do_insert(at, count, rows=False)
        self._push({"kind": "insert", "at": at, "count": count, "rows": False})
        self._invalidate()

    def _capture_band(self, at, count, rows):
        """The contents of a band about to be deleted, so undo can write them back.
        Empty cells are skipped; a band too big to hold is reported as None."""
        r0, r1 = (at, at + count - 1) if rows else (0, self._nrows - 1)
        c0, c1 = (0, self._ncols - 1) if rows else (at, at + count - 1)
        if (r1 - r0 + 1) * (c1 - c0 + 1) > self._UNDO_CELLS:
            return None
        cells = {}
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                text = self._restore_text(r, c)
                if text:
                    cells[(r, c)] = text
        return cells

    # ---- bold
    def is_bold(self, r, c):
        try:
            return bool(self._cell(r, c).font.bold)
        except Exception:
            return False

    def all_bold(self, r0, c0, r1, c1):
        """True when every cell of the block is already bold - that is what makes the
        toolbar's B a toggle (bold it, press again to take it off)."""
        return all(self.is_bold(r, c)
                   for r in range(r0, r1 + 1) for c in range(c0, c1 + 1))

    def _apply_bold(self, cells):
        """{(r, c): bold} -> the workbook's fonts, the style cache and the view."""
        from copy import copy
        rows, cols = [], []
        for (r, c), bold in cells.items():
            try:
                cell = self._cell(r, c)
                font = copy(cell.font)      # openpyxl StyleProxy -> a real Font
                font.bold = bool(bold)
                cell.font = font
            except Exception:
                log.debug("bold (%d, %d) failed", r, c, exc_info=True)
                continue
            self._style_cache.pop((r, c), None)
            rows.append(r)
            cols.append(c)
        if not rows:
            return
        self._styled = True                 # something to save, though no cell text
        self.dataChanged.emit(self.index(min(rows), min(cols)),
                              self.index(max(rows), max(cols)),
                              [Qt.FontRole])

    def set_bold(self, r0, c0, r1, c1, bold):
        """Bold (or un-bold) a block, undoably. Returns False when the block is too
        big to hold an undo for - the caller says so rather than doing it silently."""
        cells = self._rect_cells(r0, c0, r1, c1)
        if len(cells) > self._UNDO_CELLS:
            return False
        before = {key: self.is_bold(*key) for key in cells}
        after = {key: bool(bold) for key in cells}
        self._apply_bold(after)
        if before != after:
            self._push({"kind": "bold", "before": before, "after": after})
        return True

    def delete_is_undoable(self, at, count, rows):
        """Whether deleting this band could be undone: a band bigger than
        ``_UNDO_CELLS`` is too large to hold on to and wipes the undo history
        instead (see ``_delete_band``) - the confirmation says so."""
        span = self._ncols if rows else self._nrows
        return count * span <= self._UNDO_CELLS

    def delete_rows(self, at, count=1):
        """Remove ``count`` rows starting at row ``at`` (0-based), undoably."""
        self._delete_band(at, count, rows=True)

    def delete_columns(self, at, count=1):
        """Remove ``count`` columns starting at column ``at`` (0-based), undoably."""
        self._delete_band(at, count, rows=False)

    def _delete_band(self, at, count, rows):
        limit = (self._nrows if rows else self._ncols) - at
        count = min(count, limit)
        if count < 1:
            return
        cells = self._capture_band(at, count, rows)
        self._do_delete(at, count, rows)
        if cells is None:
            # Too much data to hold for an undo - better to offer no undo at all
            # than one that would silently drop what it cannot put back.
            self._clear_undo()
        else:
            self._push({"kind": "delete", "at": at, "count": count, "rows": rows,
                        "cells": cells})
        self._invalidate()

    def has_content(self, r0, c0, r1, c1, limit=5000):
        """Whether the block holds anything at all - used to ask before a delete
        throws data away. Stops at the first hit, and never scans more than
        ``limit`` rows (a column of a huge sheet must not freeze the menu)."""
        for r in range(r0, min(r1, r0 + limit) + 1):
            for c in range(c0, c1 + 1):
                if self.display_at(r, c).strip():
                    return True
        return False

    def is_text_column(self, col, sample=60):
        """Whether a column holds text rather than numbers - sampled over the first
        ``sample`` **data** rows (row 0 is the sheets' header row, whose long titles
        would make every column look textual). Cached until the next edit."""
        cached = self._text_col_cache.get(col)
        if cached is not None:
            return cached
        text = numeric = 0
        for r in range(1, min(self._nrows, sample + 1)):
            s = self.display_at(r, col).strip()
            if not s:
                continue
            if isinstance(_parse_cell(s), (int, float)):
                numeric += 1
            else:
                text += 1
        result = text > 0 and text >= numeric
        self._text_col_cache[col] = result
        return result

    # ---- edits / save
    def has_edits(self):
        return bool(self._edits) or self._structural or self._styled

    def flush_to_wb(self):
        """Write the changed cells into the worksheet (numbers re-parsed); unchanged
        cells - including \\xa0 spacers - are left untouched so their formatting
        survives. Merged non-anchor cells are skipped.

        A **formula** cell writes its computed **value** (CWatM reads these sheets
        with pandas/openpyxl and would get the formula text, not a number), and
        stays in ``_formulas`` so it keeps recalculating and is written again on the
        next save."""
        for (r, c), txt in list(self._edits.items()):
            if (r, c) in self._formulas:
                continue                      # written below, as its value
            try:
                self._ws.cell(row=r + 1, column=c + 1).value = _parse_cell(txt)
            except Exception:
                log.debug("excel write cell (%d,%d) failed", r, c, exc_info=True)
        for (r, c) in list(self._formulas):
            value = self._compute(r, c)
            try:
                self._ws.cell(row=r + 1, column=c + 1).value = (
                    value if isinstance(value, (int, float)) else str(value))
            except Exception:
                log.debug("excel write formula (%d,%d) failed", r, c, exc_info=True)
        self._edits.clear()
        self._structural = False      # the inserts are already in the worksheet
        self._styled = False          # ... and so are the fonts


class _FrozenStrip(QTableView):
    """The frozen header row above the sheet - and it must **stay** the header row.

    It shows the same model as the body, so on its own it would happily scroll: a
    click, a drag or the mouse wheel over the strip moved it to row 5 and the sheet
    then carried a "header" that was really some data row. Everything that could
    scroll it vertically is therefore refused - the wheel is handed to the body
    instead, so spinning it over the header scrolls the table, as expected.

    Row 1 is **edited here** (double-click / F2 / just type): the body hides it, so the
    strip is the only place it is shown."""

    def __init__(self, body):
        super().__init__()
        self._body = body

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._body.set_active_view(self)       # the header row is where the user is

    def keyPressEvent(self, event):
        """The block shortcuts work on the header row too. They are implemented once,
        in the body view, and act on whichever selection is active - so they are
        simply handed over (unless a cell editor is open, which owns the keys)."""
        if self.state() != QAbstractItemView.EditingState and (
                event.matches(QKeySequence.Copy) or event.matches(QKeySequence.Cut)
                or event.matches(QKeySequence.Paste)
                or event.matches(QKeySequence.Undo)
                or event.matches(QKeySequence.Redo)
                or event.key() in (Qt.Key_Delete, Qt.Key_Backspace)
                or (event.key() == Qt.Key_B
                    and event.modifiers() & Qt.ControlModifier)):
            self._body.keyPressEvent(event)
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        self._body.wheelEvent(event)          # scroll the table, never the header

    def scrollTo(self, index, hint=QAbstractItemView.EnsureVisible):
        """Never vertically - a click or an edit must not scroll row 1 away.
        Sideways it scrolls the **body** (stepping through header cells can reach a
        column that is off screen), and the strip follows through `_sync_hscroll`."""
        body, model = self._body, self._body.model()
        if not index.isValid() or model is None:
            return
        row = body.rowAt(0)                   # a row already on screen: no vertical jump
        if row >= 0:
            body.scrollTo(model.index(row, index.column()), hint)

    def keep_at_top(self, *_):
        bar = self.verticalScrollBar()
        if bar.value() != 0:
            bar.setValue(0)


class _SheetTableView(QTableView):
    """The spreadsheet table: row 0 frozen, clipboard block operations, an Excel
    **fill handle**, and word-wrapped text columns.

    *Frozen row* — a small second ``QTableView`` (``self.frozen``) shares the same
    model and shows **only row 1**, the sheet's header row. It is placed by the
    window in the layout **directly above** this view and carries the **column
    letters** (this view's own horizontal header is hidden), so the strip has its
    own space instead of covering the top of the scroll area — and this view hides
    row 0, so the scrolling pane starts at row 2 and nothing is ever hidden behind
    the strip. Column widths, horizontal scrolling, the row-number gutter width and
    the palette are kept in sync; clicking a letter on the strip selects that column
    **here**, and row 1 is **edited on the strip itself** (double-click / F2 / type) —
    it is the only place that row is shown.

    *Word wrap* — heights are computed for the **visible** rows only
    (``_resize_visible_rows``, re-run on scroll and after a column resize) **over
    the visible columns only** (``_visible_columns``), so wrapping never walks a
    300k-row sheet, and never walks a 1000-column one either.

    *Never measure the whole sheet* — that is the invariant behind both. Qt's
    ``resizeRowToContents``/``sizeHintForRow`` ask the model for **every** column of
    the row, which on a 1021-column sheet is ~8000 ``data()`` calls **per row**; the
    strip was re-synced once per column while a sheet was being laid out, so opening
    ``Reservoirs_downstream`` froze the whole GUI for minutes. Row heights are
    therefore measured with ``_row_height_hint`` over the columns on screen, and the
    strip's syncs are coalesced by ``_frozen_timer``.
    """

    #: The user moved between the table and the header strip - the toolbar's
    #: enabled state follows the selection of whichever is active.
    activeViewChanged = Signal()

    _HANDLE = 7          # side of the fill-handle square, in pixels
    _MAX_CHARS = 120     # widest a column may get: ~120 characters of text
    _MAX_COPY = 200000   # cells a single copy may put on the clipboard
    _MAX_HINT_COLS = 120  # most columns a row-height measurement may look at

    def __init__(self, parent=None):
        super().__init__(parent)
        # The frozen header row. No parent: the window puts it in the layout right
        # above this view, so it occupies its own space (see the class docstring).
        # Where the user is working (see set_active_view): the table until a click
        # or the keyboard lands in the header strip.
        self._active_view = self
        self.frozen = _FrozenStrip(self)
        f = self.frozen
        f.verticalScrollBar().valueChanged.connect(f.keep_at_top)
        # The header row is editable in place (double-click / F2 / just type), so the
        # strip takes focus and a current cell like a normal table - it only refuses
        # to *scroll* (see _FrozenStrip).
        f.setFocusPolicy(Qt.StrongFocus)
        f.setEditTriggers(QAbstractItemView.DoubleClicked
                          | QAbstractItemView.EditKeyPressed
                          | QAbstractItemView.AnyKeyPressed)
        f.setSelectionMode(QAbstractItemView.ExtendedSelection)
        f.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        f.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        f.setFrameShape(QTableView.NoFrame)     # reads as one table with the body
        f.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        f.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        f.setWordWrap(True)
        # Text that does not fit its column is **cut off** (with an ellipsis), never
        # painted across the neighbouring cell: an unbreakable value (an ID, a path,
        # a long word word wrap cannot split) used to spill into the next column and
        # sit on top of its content. Widen the column to see the rest.
        f.setTextElideMode(Qt.ElideRight)

        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setWordWrap(True)                  # text columns wrap (see wrap_columns)
        self.setTextElideMode(Qt.ElideRight)    # never spill into the next column
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.horizontalHeader().hide()          # the letters live on the strip now

        # Fill-handle drag state: the block it started from and the block the
        # pointer currently covers (drawn as a preview until the button is let go).
        self._fill_src = None
        self._fill_dst = None
        self._filling = False

        # Re-wrapping is debounced: a column drag emits sectionResized per pixel.
        self._wrap_timer = QTimer(self)
        self._wrap_timer.setSingleShot(True)
        self._wrap_timer.setInterval(60)
        self._wrap_timer.timeout.connect(self._resize_visible_rows)
        # Rows already fitted to the current columns/widths (see _resize_visible_rows).
        self._fitted_rows = set()
        self._fitted_span = None
        # Syncing the strip is coalesced the same way: laying out a wide sheet emits
        # one sectionResized per column, and each sync re-measures the header row.
        self._frozen_timer = QTimer(self)
        self._frozen_timer.setSingleShot(True)
        self._frozen_timer.setInterval(0)
        self._frozen_timer.timeout.connect(self._apply_frozen_sync)

        self.horizontalHeader().sectionResized.connect(self._on_section_resized)
        self.horizontalScrollBar().valueChanged.connect(self._sync_hscroll)
        # A relayout of the strip recomputes (and shortens) its scroll range again,
        # which would clamp it back off the body's position - re-apply when it does.
        f.horizontalScrollBar().rangeChanged.connect(self._on_strip_range_changed)
        self.horizontalScrollBar().valueChanged.connect(self._on_hscroll)
        # The letters are on the strip: a drag there resizes the body's column, a
        # click selects it here.
        f.horizontalHeader().sectionResized.connect(
            lambda i, _old, new: self.setColumnWidth(i, new))
        f.horizontalHeader().sectionClicked.connect(self._on_letter_clicked)
        # the main vertical header width can grow while scrolling (wider row
        # numbers) -> keep the frozen strip aligned.
        self.verticalScrollBar().valueChanged.connect(self._sync_frozen)
        self.verticalScrollBar().valueChanged.connect(self._schedule_wrap)

        # Right-click menus: cells (copy/paste) and the two headers (insert/paste
        # whole columns and rows). The column menu hangs off the strip's letters.
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_cell_menu)
        for header, handler in ((f.horizontalHeader(), self._on_header_menu_h),
                                (self.verticalHeader(), self._on_header_menu_v)):
            header.setContextMenuPolicy(Qt.CustomContextMenu)
            header.customContextMenuRequested.connect(handler)

        # The palette the selection tint switches away from and back to; captured
        # on first use, when the view has its parent's (themed) palette.
        self._base_palette = None
        # (workbook path, sheet name) of what is on screen - stamped on a line copy
        # so it cannot be pasted into another sheet.
        self._source = (None, None)

    def set_source(self, path, sheet):
        self._source = (path, sheet)

    def setModel(self, model):
        previous = self.model()
        if previous is not None:
            try:
                previous.dataChanged.disconnect(self._on_data_changed)
            except (RuntimeError, TypeError):
                pass
        super().setModel(model)
        self._forget_fitted_rows()
        if model is not None:
            # Edited text can need a taller (or shorter) row: drop the fitted-row
            # cache so the next wrap pass measures them again. One connection at a
            # time - the same model comes back when a sheet tab is revisited.
            model.dataChanged.connect(self._on_data_changed)
        self.frozen.setModel(model)
        self.frozen.setShowGrid(self.showGrid())
        self.frozen.show()
        # Row 1 is shown by the strip only: hiding it here means the scrolling pane
        # starts at row 2 and the strip covers nothing.
        if model is not None and model.rowCount() > 0:
            self.setRowHidden(0, True)
        self._fill_src = self._fill_dst = None
        self._filling = False
        if self.selectionModel() is not None:
            self.selectionModel().selectionChanged.connect(self._on_selection_changed)
        self._sync_frozen()

    def _on_letter_clicked(self, column):
        """A click on a column letter (they live on the strip) selects that column
        in the body; Ctrl adds a column, Shift extends from the last one."""
        # The click landed on the strip, but the selection it makes is the body's -
        # so that is where the toolbar has to look afterwards.
        self.set_active_view(self)
        mods = QGuiApplication.keyboardModifiers()
        if mods & Qt.ControlModifier or mods & Qt.ShiftModifier:
            selected = self.selected_columns()
            if mods & Qt.ShiftModifier and selected:
                lo, hi = min(selected + [column]), max(selected + [column])
                columns = range(lo, hi + 1)
            else:
                columns = set(selected) ^ {column}      # Ctrl toggles
            model = self.model()
            sm = self.selectionModel()
            if model is None or sm is None:
                return
            sm.clearSelection()
            for c in columns:
                sm.select(QItemSelection(model.index(0, c),
                                         model.index(model.rowCount() - 1, c)),
                          QItemSelectionModel.Select)
        else:
            self.selectColumn(column)

    def _on_selection_changed(self, *_):
        self._update_selection_tint()
        self.viewport().update()          # the fill handle moved with the selection

    # ------------------------------------------------- whole row/column tint
    def _full_lines(self, columns):
        """Indices of the fully selected columns (or rows), read from the selection's
        **ranges**.

        ``QItemSelectionModel.selectedColumns()/selectedRows()`` answer the same
        question by walking every line of the sheet, which on a 1021-column sheet
        takes over 3 seconds per call - and this is asked on every selection change
        and by every header menu. A header click (or a drag) always makes ranges that
        span the sheet's full height/width, so the ranges give the same answer for
        every way the GUI creates a line selection. (Only a line stitched together
        from several partial ranges - rows 0-100 and 101-end selected separately -
        counts as a full line for Qt but not here.)"""
        sm, model = self.selectionModel(), self.model()
        if sm is None or model is None:
            return []
        last_row, last_col = model.rowCount() - 1, model.columnCount() - 1
        found = set()
        for rng in sm.selection():
            if columns:
                if rng.top() == 0 and rng.bottom() == last_row:
                    found.update(range(rng.left(), rng.right() + 1))
            elif rng.left() == 0 and rng.right() == last_col:
                found.update(range(rng.top(), rng.bottom() + 1))
        return sorted(found)

    def selected_columns(self):
        """Indices of the **fully** selected columns (a header click)."""
        return self._full_lines(columns=True)

    def selected_rows(self):
        """Indices of the **fully** selected rows."""
        return self._full_lines(columns=False)

    def _update_selection_tint(self):
        """Marked cells are painted **dark gray** (``selection_cell``) rather than the
        platform's accent blue, and a whole marked column/row gets the stronger
        ``selection_line`` shade - so "the entire line is marked" stays unmistakable."""
        if self._base_palette is None:
            self._base_palette = QPalette(self.palette())
        whole = bool(self.selected_columns() or self.selected_rows())
        palette = QPalette(self._base_palette)
        palette.setColor(QPalette.Highlight, QColor(
            theme.c("selection_line" if whole else "selection_cell")))
        palette.setColor(QPalette.HighlightedText, QColor("white"))
        self.setPalette(palette)
        self.frozen.setPalette(palette)

    def sync_frozen_columns(self):
        """Copy the main view's column widths onto the frozen strip (call after the
        main view auto-sizes / sets a default width).

        The strip's own ``sectionResized`` is blocked while the widths are copied:
        it writes the width straight back into this view, which would emit
        ``sectionResized`` here again - once per column, each one re-syncing the
        strip. On a 1000-column sheet that ping-pong was the freeze."""
        if self.model() is None:
            return
        header = self.frozen.horizontalHeader()
        blocked = header.blockSignals(True)
        try:
            header.setDefaultSectionSize(
                self.horizontalHeader().defaultSectionSize())
            for c in range(self.model().columnCount()):
                self.frozen.setColumnWidth(c, self.columnWidth(c))
        finally:
            header.blockSignals(blocked)
        self._sync_frozen()

    def _on_section_resized(self, logical, old, new):
        self.frozen.setColumnWidth(logical, new)
        self._sync_frozen()
        self._forget_fitted_rows()     # a narrower column needs taller rows
        self._schedule_wrap()

    def _sync_hscroll(self, value):
        """Scroll the strip to exactly where the body is.

        The strip carries no vertical scrollbar (the body does), so its viewport is a
        little wider and Qt gives its scrollbar a slightly **smaller** maximum - at
        the right-hand end of a wide sheet the column letters would stop ~16 px short
        of the data they belong to. Its scrollbar is hidden anyway, so widening the
        range costs nothing and keeps the two exactly aligned; a relayout that resets
        the range is caught by the next scroll or strip sync."""
        bar = self.frozen.horizontalScrollBar()
        if bar.maximum() < value:
            bar.setMaximum(value)      # emits rangeChanged, which re-enters here
        bar.setValue(value)            # once more with the range already wide enough

    def _on_strip_range_changed(self, *_):
        self._sync_hscroll(self.horizontalScrollBar().value())

    def _on_hscroll(self, *_):
        """Scrolling sideways only matters to a sheet measured over **part** of its
        columns (see ``_visible_columns``): columns coming into view can need a taller
        header row. A sheet inside ``_MAX_HINT_COLS`` was measured whole, so nothing
        can change there.

        Only the **strip** is re-measured, not the body rows: re-fitting every visible
        row on every sideways scroll costs ~900 delegate measurements per step and is
        felt as lag, while the header row is the one whose long text actually has to
        wrap. Body rows are fitted when they scroll into view and when a column is
        resized."""
        model = self.model()
        if model is None or model.columnCount() <= self._MAX_HINT_COLS:
            return
        self._sync_frozen()

    def _visible_columns(self, view=None):
        """The columns a height measurement may look at, as (first, last).

        A sheet of at most ``_MAX_HINT_COLS`` columns is measured **whole**, exactly
        as ``resizeRowToContents`` did - the common sheet keeps its heights to the
        pixel. Only a wider one is narrowed down to what is on screen, since
        measuring all 1021 columns of every row is what froze the window."""
        view = view or self
        model = view.model()
        if model is None or model.columnCount() == 0:
            return None
        last_col = model.columnCount() - 1
        if model.columnCount() <= self._MAX_HINT_COLS:
            return 0, last_col
        header = view.horizontalHeader()
        first = header.visualIndexAt(0)
        last = header.visualIndexAt(max(view.viewport().width() - 1, 0))
        if first < 0:
            first = 0
        if last < 0:
            last = last_col
        return first, min(last, first + self._MAX_HINT_COLS, last_col)

    def _row_height_hint(self, view, row, span):
        """Height ``row`` needs for the columns in ``span`` - a bounded stand-in for
        ``resizeRowToContents``, which measures **every** column of the sheet.

        It reproduces Qt's own arithmetic for the columns it is given (tallest cell
        hint, plus the grid line, never below what the row header asks for), so for a
        sheet inside ``_MAX_HINT_COLS`` the result is **identical** to
        ``resizeRowToContents``. The two details that make it identical rather than
        approximate: the option carries `WrapText`, and its rect is a **valid**
        rectangle the width of the column - a zero-height rect is not valid, and Qt
        then measures the text unwrapped on one line (too short for a wrapped cell).
        `sizeHintForIndex` is no use here for the same reason: it never wraps."""
        model = view.model()
        header = view.horizontalHeader()
        height = 0
        for c in range(span[0], span[1] + 1):
            if header.isSectionHidden(c):
                continue
            index = model.index(row, c)
            option = QStyleOptionViewItem()
            option.initFrom(view)
            option.features |= QStyleOptionViewItem.WrapText
            option.rect = QRect(0, 0, view.columnWidth(c),
                                max(view.rowHeight(row), 1))
            hint = view.itemDelegateForIndex(index).sizeHint(option, index).height()
            if hint > height:
                height = hint
        if view.showGrid():
            height += 1
        return max(height, view.verticalHeader().sectionSizeHint(row))

    def _sync_frozen(self, *_):
        """Ask for a strip sync. Coalesced through ``_frozen_timer``, so a burst of
        column resizes (laying out a sheet emits one per column) costs **one**
        measurement, not one per column."""
        self._frozen_timer.start()

    def _apply_frozen_sync(self):
        """Keep the strip lined up with the body: same row-number gutter width, and
        exactly as tall as the letters plus the (possibly wrapped) header row."""
        model = self.model()
        if model is None or model.rowCount() == 0:
            return
        self.frozen.verticalHeader().setFixedWidth(self.verticalHeader().width())
        self._sync_hscroll(self.horizontalScrollBar().value())
        span = self._visible_columns(self.frozen)
        if span is not None:             # the header row wraps too
            height = self._row_height_hint(self.frozen, 0, span)
            if height != self.frozen.rowHeight(0):
                self.frozen.setRowHeight(0, height)
        height = (self.frozen.horizontalHeader().height()
                  + self.frozen.rowHeight(0) + 2)
        self.frozen.setFixedHeight(height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_frozen()
        self._schedule_wrap()

    # ------------------------------------------------------------- word wrap
    def _schedule_wrap(self, *_):
        self._wrap_timer.start()

    def visible_rows(self):
        """(first, last) row currently on screen - the only rows word wrap and the
        height computation ever touch."""
        model = self.model()
        if model is None or model.rowCount() == 0:
            return None
        top = self.rowAt(0)
        bottom = self.rowAt(max(self.viewport().height() - 1, 0))
        if top < 0:
            top = 0
        if bottom < 0:
            bottom = model.rowCount() - 1
        return top, min(bottom, model.rowCount() - 1)

    def _resize_visible_rows(self):
        """Give the rows on screen the height their wrapped text needs. Bounded by
        the viewport in **both** directions - the rows on screen, measured over the
        columns on screen - so this stays cheap however big the sheet is (a
        1000-column sheet made the per-row ``resizeRowToContents`` cost ~8000 model
        reads, which is what made the window freeze)."""
        if not self.wordWrap():
            return
        span = self.visible_rows()
        columns = self._visible_columns()
        if span is None or columns is None:
            return
        if columns != self._fitted_span:      # other columns decide the heights now
            self._fitted_rows.clear()
            self._fitted_span = columns
        top, bottom = span
        for r in range(top, min(bottom + 1, top + 300)):
            if r in self._fitted_rows:
                # Already measured against these columns and these widths - scrolling
                # back and forth must not re-measure the same rows for ever.
                continue
            try:
                height = self._row_height_hint(self, r, columns)
                self._fitted_rows.add(r)
                if height != self.rowHeight(r):
                    # Only when it really changed: every setRowHeight relays out and
                    # repaints the view.
                    self.setRowHeight(r, height)
            except Exception:
                break
        self._sync_frozen()          # the header row may need another line too

    def _on_data_changed(self, *_):
        self._forget_fitted_rows()
        self._schedule_wrap()

    def _forget_fitted_rows(self):
        """Row heights have to be worked out again (new model, changed column widths,
        inserted/deleted lines)."""
        self._fitted_rows.clear()
        self._fitted_span = None

    def header_width_hints(self):
        """What each column needs for its **header** (row 1) text.

        ``resizeColumnsToContents`` on the body cannot see row 1 - the body hides it,
        the strip is where it is shown - so a column was sized to its *data* only and
        a longer header ran past it into the next column."""
        model = self.model()
        if model is None:
            return {}
        return {c: self.frozen.sizeHintForColumn(c)
                for c in range(model.columnCount())}

    def fit_header_widths(self, hints=None):
        """Widen every column that is narrower than its header text needs."""
        hints = self.header_width_hints() if hints is None else hints
        for c, width in hints.items():
            if width > self.columnWidth(c):
                self.setColumnWidth(c, width)

    def cap_column_widths(self):
        """No column may be wider than about ``_MAX_CHARS`` characters - one very
        long cell would otherwise blow a column up to several screens. The text
        simply wraps into more lines instead."""
        limit = self.fontMetrics().averageCharWidth() * self._MAX_CHARS + 12
        model = self.model()
        if model is None:
            return
        for c in range(model.columnCount()):
            if self.columnWidth(c) > limit:
                self.setColumnWidth(c, limit)

    def wrap_columns(self, text_columns):
        """Halve the width of the given (text) columns and let them wrap; numeric
        columns keep the width their content asked for. A column is never halved
        below what its **header** needs, so halving cannot re-create the cut-off
        header the auto-size just fixed."""
        hints = self.header_width_hints()
        for c in text_columns:
            width = self.columnWidth(c)
            if width > 140:
                floor = max(70, min(hints.get(c, 0), width))
                self.setColumnWidth(c, max(floor, width // 2))
        self._resize_visible_rows()

    # ------------------------------------------------------- selected block
    def set_active_view(self, view):
        """Remember where the user is working - the strip (header row) or the table.

        This is deliberately **not** ``hasFocus()`` read at the moment of the action:
        pressing a toolbar button can move the focus first, so B pressed right after
        marking header cells found the strip unfocused and bolted the *table's* old
        selection instead - or did nothing when the table had none. The active view is
        recorded when the focus arrives, and a toolbar button never takes it."""
        if view is not self._active_view:
            self._active_view = view
            self.activeViewChanged.emit()

    def _selection_source(self):
        """Whose selection the clipboard, Delete and Bold act on: the **strip** when
        the user is working in the header row, otherwise this table."""
        view = self._active_view
        return view if view is not None else self

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.set_active_view(self)

    def selected_block(self):
        """The bounding rectangle (r0, c0, r1, c1) of the selection, or None.

        Measured from the selection's **ranges**, never from ``selectedIndexes()``:
        the index list is one object per selected cell, so a Select All on a
        1000-column sheet built 375 000 of them - and ``paintEvent`` asks for this
        block on every repaint, which left the window unusable after Ctrl+A."""
        sm = self._selection_source().selectionModel()
        ranges = sm.selection() if sm is not None else None
        if not ranges:
            return None
        r0 = min(rng.top() for rng in ranges)
        c0 = min(rng.left() for rng in ranges)
        r1 = max(rng.bottom() for rng in ranges)
        c1 = max(rng.right() for rng in ranges)
        return r0, c0, r1, c1

    def _select_block(self, r0, c0, r1, c1):
        model = self.model()
        if model is None:
            return
        sel = QItemSelection(model.index(r0, c0), model.index(r1, c1))
        self.selectionModel().select(
            sel, QItemSelectionModel.ClearAndSelect)

    # ---------------------------------------------------------- fill handle
    def _handle_rect(self):
        """The little square at the selection's bottom-right corner (None when
        nothing is selected or it is scrolled out of view)."""
        block = self.selected_block()
        if block is None or self._filling:
            return None
        r0, c0, r1, c1 = block
        rect = self.visualRect(self.model().index(r1, c1))
        if not rect.isValid() or rect.isNull():
            return None
        s = self._HANDLE
        return QRect(rect.right() - s // 2, rect.bottom() - s // 2, s, s)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.model() is None:
            return
        painter = QPainter(self.viewport())
        try:
            if self._filling and self._fill_dst is not None:
                r0, c0, r1, c1 = self._fill_dst
                a = self.visualRect(self.model().index(r0, c0))
                b = self.visualRect(self.model().index(r1, c1))
                pen = QPen(QColor(theme.c("accent")))
                pen.setStyle(Qt.DashLine)
                pen.setWidth(2)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(a.united(b).adjusted(0, 0, -1, -1))
            else:
                rect = self._handle_rect()
                if rect is not None:
                    painter.setPen(QPen(QColor("white"), 1))
                    painter.setBrush(QBrush(QColor(theme.c("accent"))))
                    painter.drawRect(rect)
        except Exception:
            log.debug("fill handle paint failed", exc_info=True)
        finally:
            painter.end()

    def mousePressEvent(self, event):
        rect = self._handle_rect()
        if (rect is not None and event.button() == Qt.LeftButton
                and rect.adjusted(-2, -2, 2, 2).contains(event.position().toPoint())):
            self._fill_src = self.selected_block()
            self._fill_dst = self._fill_src
            self._filling = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if not self._filling:
            rect = self._handle_rect()
            if rect is not None and rect.adjusted(-2, -2, 2, 2).contains(pos):
                self.setCursor(Qt.CrossCursor)      # Excel's fill-handle cursor
            else:
                self.unsetCursor()
            super().mouseMoveEvent(event)
            return
        self._fill_autoscroll(pos)
        cell = self._cell_at(pos)
        if cell is not None:
            self._fill_dst = self._fill_target(*cell)
            self.viewport().update()
        event.accept()

    def _cell_at(self, pos):
        """(row, col) under ``pos``, the point clamped into the viewport so a drag
        past the edge still targets the last visible cell."""
        x = min(max(pos.x(), 0), max(self.viewport().width() - 1, 0))
        y = min(max(pos.y(), 0), max(self.viewport().height() - 1, 0))
        row, col = self.rowAt(y), self.columnAt(x)
        if row < 0 or col < 0:
            return None
        return row, col

    def _fill_autoscroll(self, pos):
        """Scroll while the pointer is held past an edge, so a fill can reach
        beyond the rows currently on screen."""
        margin = 16
        v, h = self.verticalScrollBar(), self.horizontalScrollBar()
        if pos.y() > self.viewport().height() - margin:
            v.setValue(v.value() + v.singleStep())
        elif pos.y() < margin:
            v.setValue(v.value() - v.singleStep())
        if pos.x() > self.viewport().width() - margin:
            h.setValue(h.value() + h.singleStep())
        elif pos.x() < margin:
            h.setValue(h.value() - h.singleStep())

    def _fill_target(self, row, col):
        """The block the pointer is asking to fill: the source grown along the
        **dominant** axis only (like Excel, a drag is either vertical or
        horizontal)."""
        r0, c0, r1, c1 = self._fill_src
        down, up = row - r1, r0 - row
        right, left = col - c1, c0 - col
        vert = max(down, up)
        horz = max(right, left)
        if vert <= 0 and horz <= 0:
            return self._fill_src
        if vert >= horz:
            return (min(r0, row), c0, max(r1, row), c1)
        return (r0, min(c0, col), r1, max(c1, col))

    def mouseReleaseEvent(self, event):
        if not self._filling:
            super().mouseReleaseEvent(event)
            return
        src, dst = self._fill_src, self._fill_dst
        self._filling = False
        self._fill_src = self._fill_dst = None
        event.accept()
        if src and dst and dst != src:
            self._apply_fill(src, dst)
        self.viewport().update()

    def _apply_fill(self, src, dst):
        """Turn the dragged rectangle into the target strip and hand it to the
        model (which extends each line's series)."""
        model = self.model()
        if model is None or not hasattr(model, "fill_range"):
            return
        sr0, sc0, sr1, sc1 = src
        dr0, dc0, dr1, dc1 = dst
        vertical = (dr0 < sr0) or (dr1 > sr1)
        if vertical:
            backwards = dr0 < sr0
            target = (dr0, sc0, sr0 - 1, sc1) if backwards \
                else (sr1 + 1, sc0, dr1, sc1)
        else:
            backwards = dc0 < sc0
            target = (sr0, dc0, sr1, sc0 - 1) if backwards \
                else (sr0, sc1 + 1, sr1, dc1)
        if target[0] > target[2] or target[1] > target[3]:
            return
        model.fill_range(src, target, vertical, backwards)
        self._select_block(min(src[0], target[0]), min(src[1], target[1]),
                           max(src[2], target[2]), max(src[3], target[3]))
        self._schedule_wrap()

    # ------------------------------------------------------------ clipboard
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Undo):
            self.undo()
            return
        if event.matches(QKeySequence.Redo) or (
                event.key() == Qt.Key_Y and event.modifiers() & Qt.ControlModifier):
            self.redo()
            return
        if event.matches(QKeySequence.Copy):
            self.copy_selection()
            return
        if event.matches(QKeySequence.Cut):
            self.copy_selection(cut=True)
            return
        if event.matches(QKeySequence.Paste):
            self.paste_clipboard()
            return
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) \
                and self.state() != QAbstractItemView.EditingState:
            self.clear_selection()
            return
        if event.key() == Qt.Key_B and event.modifiers() & Qt.ControlModifier \
                and self.state() != QAbstractItemView.EditingState:
            self.toggle_bold()
            return
        super().keyPressEvent(event)

    def undo(self):
        model = self.model()
        if model is not None and hasattr(model, "undo") and model.undo():
            self._after_structure()

    def redo(self):
        model = self.model()
        if model is not None and hasattr(model, "redo") and model.redo():
            self._after_structure()

    def copy_selection(self, cut=False):
        """Put the selected block on the clipboard as tab-separated text (the
        format Excel itself reads and writes)."""
        block = self.selected_block()
        model = self.model()
        if block is None or model is None or not hasattr(model, "block_text"):
            return
        QGuiApplication.clipboard().setText(model.block_text(*block))
        if cut:
            model.clear_range(*block)
            self._schedule_wrap()

    def paste_clipboard(self):
        """Paste tab-separated clipboard text with its top-left at the current
        cell, growing the sheet if it runs past the last row/column."""
        model = self.model()
        if model is None or not hasattr(model, "paste_block"):
            return
        rows = self.clipboard_block()
        if not rows:
            return
        index = self.currentIndex()
        block = self.selected_block()
        row, col = (index.row(), index.column()) if index.isValid() \
            else (block[:2] if block else (0, 0))
        filled = model.paste_block(row, col, rows)
        if filled:
            self._select_block(*filled)
            self._schedule_wrap()

    def clear_selection(self):
        block = self.selected_block()
        model = self.model()
        if block is not None and model is not None and hasattr(model, "clear_range"):
            model.clear_range(*block)
            self._schedule_wrap()

    def toggle_bold(self):
        """Toolbar **B** / Ctrl+B: bold the marked cells, or take the bold off again
        when they are all bold already (like Excel's B). Saved with the workbook."""
        block = self.selected_block()
        model = self.model()
        if block is None or model is None or not hasattr(model, "set_bold"):
            return
        if not model.set_bold(*block, not model.all_bold(*block)):
            QMessageBox.information(
                self, "Bold",
                "That is too many cells to bold in one go.\n"
                "Mark a smaller block and try again.")

    @staticmethod
    def parse_block(text):
        """Tab-separated text as a block of cells (list of rows), or None."""
        if not text:
            return None
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if lines and lines[-1] == "":
            lines.pop()                       # a trailing newline is not a row
        return [line.split("\t") for line in lines] if lines else None

    @classmethod
    def clipboard_block(cls):
        """The clipboard parsed as a block of cells, or None."""
        return cls.parse_block(QGuiApplication.clipboard().text())

    # --------------------------------------------------------- context menus
    def _on_cell_menu(self, pos):
        """Right-click on the cells: the clipboard actions for the selected cell(s)."""
        if self.model() is None or self.selectionModel() is None:
            return
        index = self.indexAt(pos)
        if index.isValid() and not self.selectionModel().isSelected(index):
            self.setCurrentIndex(index)          # right-click outside -> select it
        block = self.selected_block()
        if block is None:
            return
        r0, c0, r1, c1 = block
        cells = (r1 - r0 + 1) * (c1 - c0 + 1)
        what = "cell" if cells == 1 else f"{cells} cells"
        menu = QMenu(self)
        menu.addAction(f"Copy {what}", self.copy_selection)
        menu.addAction(f"Cut {what}", lambda: self.copy_selection(cut=True))
        paste = menu.addAction("Paste", self.paste_clipboard)
        paste.setEnabled(self.clipboard_block() is not None)
        menu.addSeparator()
        menu.addAction(f"Delete contents of {what}", self.clear_selection)
        menu.exec(self.viewport().mapToGlobal(pos))

    def _on_header_menu_h(self, pos):
        self._header_menu(self.horizontalHeader(), pos, columns=True)

    def _on_header_menu_v(self, pos):
        self._header_menu(self.verticalHeader(), pos, columns=False)

    def _header_menu(self, header, pos, columns):
        """Right-click on a column/row header: copy, insert, paste and delete whole
        columns/rows.

        The paste entries are only live for a clipboard that **fits**: a line copied
        from a header carries its orientation and its sheet (``_LineClip``), so a
        copied *row* is never offered as a column to paste, and a line from another
        sheet is refused - both stay visible but disabled, with the reason in the
        tooltip, rather than silently doing the wrong thing."""
        model = self.model()
        if model is None or not hasattr(model, "insert_columns"):
            return
        section = header.logicalIndexAt(pos)
        if section < 0:
            return
        selected = self.selected_columns() if columns else self.selected_rows()
        if section not in selected:
            (self.selectColumn if columns else self.selectRow)(section)
            selected = [section]
        count = len(selected)
        first, last = min(selected), max(selected)

        kind = "column" if columns else "row"
        nouns = kind if count == 1 else f"{count} {kind}s"
        before, after = ("left", "right") if columns else ("above", "below")

        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        menu.addAction(f"Copy {nouns}", lambda: self.copy_lines(columns))
        menu.addSeparator()
        menu.addAction(f"Insert empty {nouns} {before}",
                       lambda: self._insert(first, count, columns))
        menu.addAction(f"Insert empty {nouns} {after}",
                       lambda: self._insert(last + 1, count, columns))

        block = self.clipboard_block()
        if block:
            n = len(block[0]) if columns else len(block)
            span = kind if n == 1 else f"{n} {kind}s"
            reason = self._paste_line_block(kind)
            menu.addSeparator()
            # Plain Paste first: write the clipboard **into** the clicked line(s),
            # overwriting them - the two below make room instead.
            actions = [menu.addAction(
                f"Paste into this {kind}" if count == 1 else f"Paste into {nouns}",
                lambda: self._paste_into(first, block, columns))]
            for where, at in ((before, first), (after, last + 1)):
                actions.append(menu.addAction(
                    f"Paste {span} {where}",
                    lambda at=at: self._paste_lines(at, block, columns)))
            if reason:
                for act in actions:
                    act.setEnabled(False)
                    act.setToolTip(reason)
        menu.addSeparator()
        menu.addAction(f"Delete {nouns}", lambda: self._delete_lines(columns))
        menu.exec(header.mapToGlobal(pos))

    def _paste_line_block(self, kind):
        """Why the clipboard must not be pasted as ``kind`` lines here - '' when it
        may. A plain block of cells (no ``_LineClip``) is always allowed: it never
        claimed to be a column or a row."""
        clip = _LineClip.current()
        if clip is None:
            return ""
        if clip.kind != kind:
            return (f"The clipboard holds a {clip.kind}, not a {kind} - "
                    f"paste it from the {clip.kind} header instead")
        if clip.source != self._source:
            sheet = clip.source[1] or "another workbook"
            return (f"That {kind} was copied from '{sheet}' - a {kind} can only be "
                    f"pasted back into the sheet it came from")
        return ""

    def copy_lines(self, columns):
        """Header 'Copy column(s)/row(s)': the whole lines onto the clipboard, tagged
        as a line of **this** sheet. This is the only way to copy a full column/row -
        Ctrl+C over cells copies just the cells."""
        model = self.model()
        selected = self.selected_columns() if columns else self.selected_rows()
        if model is None or not selected:
            return
        first, last = min(selected), max(selected)
        if columns:
            block = (0, first, model.rowCount() - 1, last)
        else:
            block = (first, 0, last, model.columnCount() - 1)
        cells = (block[2] - block[0] + 1) * (block[3] - block[1] + 1)
        if cells > self._MAX_COPY:
            QMessageBox.information(
                self, "Copy",
                f"That is {cells:,} cells - too much for one copy.\n"
                "Select the cells you need and copy those instead.")
            return
        text = model.block_text(*block)
        QGuiApplication.clipboard().setText(text)
        _LineClip.remember("column" if columns else "row",
                           self.parse_block(text), self._source, text)

    def _delete_lines(self, columns):
        """Header 'Delete column(s)/row(s)'. Asks first when there is data to lose,
        saying whether Ctrl+Z can bring it back (a band too big to hold clears the
        undo history instead - then Reload is the only way back)."""
        model = self.model()
        selected = self.selected_columns() if columns else self.selected_rows()
        if model is None or not selected:
            return
        first, count = min(selected), len(selected)
        kind = "column" if columns else "row"
        nouns = kind if count == 1 else f"{count} {kind}s"
        block = (0, first, model.rowCount() - 1, first + count - 1) if columns \
            else (first, 0, first + count - 1, model.columnCount() - 1)
        if model.has_content(*block):
            note = "You can undo this with Ctrl+Z." \
                if model.delete_is_undoable(first, count, not columns) \
                else ("That is too much data to keep for an undo, so this clears "
                      "the undo history (Reload discards all changes).")
            if QMessageBox.question(
                    self, f"Delete {kind}",
                    f"Delete {nouns} including the data in them?\n" + note) \
                    != QMessageBox.Yes:
                return
        if columns:
            model.delete_columns(first, count)
        else:
            model.delete_rows(first, count)
        self._after_structure()

    def _insert(self, at, count, columns):
        model = self.model()
        if columns:
            model.insert_columns(at, count)
            self.selectColumn(at)
        else:
            model.insert_rows(at, count)
            self.selectRow(at)
        self._after_structure()

    def _paste_into(self, at, block, columns):
        """Header 'Paste into this column/row': write the clipboard **over** the
        clicked line, from the top (a column) or from the left (a row) - nothing is
        inserted, so the sheet keeps its shape."""
        model = self.model()
        filled = model.paste_block(0, at, block) if columns \
            else model.paste_block(at, 0, block)
        if filled:
            self._select_block(*filled)
        self._after_structure()

    def _paste_lines(self, at, block, columns):
        """Insert as many empty columns/rows as the clipboard block is wide/tall and
        drop it in, so nothing existing is overwritten."""
        model = self.model()
        width = max(len(r) for r in block)
        height = len(block)
        if columns:
            model.insert_columns(at, width)
            filled = model.paste_block(0, at, block)
        else:
            model.insert_rows(at, height)
            filled = model.paste_block(at, 0, block)
        if filled:
            self._select_block(*filled)
        self._after_structure()

    def _after_structure(self):
        """Columns/rows moved: their widths and the wrapping have to be redone."""
        self.sync_frozen_columns()
        self._forget_fitted_rows()
        self._schedule_wrap()
        self.viewport().update()


class _WorkbookLoader(QThread):
    """Reads a workbook with openpyxl **off the GUI thread**.

    Nothing Qt is touched in ``run`` - openpyxl hands back plain Python objects, and
    the finished workbook travels to the window through a queued signal. Reading a
    ~1 MB workbook costs ~1.5 s from a local disk but tens of seconds when the file
    sits cold on a slow network share, and doing that in the constructor is what made
    Windows grey the whole application out with "not responding"."""

    done = Signal(object, str)          # (workbook | None, error text)

    # A running QThread must stay referenced and must not be destroyed with the
    # window (closing during a load would otherwise take the interpreter down), so
    # loaders hold themselves here until they finish.
    _running = set()

    def __init__(self, path):
        super().__init__()             # deliberately parentless - see above
        self.path = path
        _WorkbookLoader._running.add(self)
        self.finished.connect(lambda: _WorkbookLoader._running.discard(self))

    def run(self):
        try:
            from openpyxl import load_workbook
            wb = load_workbook(self.path)          # keep styles (colours + save)
        except Exception as e:
            log.debug("workbook load failed: %s", self.path, exc_info=True)
            self.done.emit(None, str(e))
            return
        self.done.emit(wb, "")


class ExcelSheetWindow(GeometryMemoryMixin, QDialog):
    """Editable, colour-preserving view of a whole workbook (lazy QTableView +
    an Excel-like sheet tab bar below the table)."""

    _WIDE_COL = 90       # column width on a sheet too wide to auto-size (> 60 columns)

    # Columns that need more room than their own content asks for, per sheet:
    # {sheet key (see _sheet_key): {column letter: minimum width in characters}}.
    # The auto-size fits what is *in* a cell, which is not always what makes the
    # sheet readable - the reservoir IDs in Reservoir_transfers (400001, ...) must be
    # readable in full, and the description column of Reservoirs must not be squeezed
    # to the point where its text is cut off. Add a line here for any other sheet.
    _SHEET_MIN_CHARS = {
        "reservoir": {"E": 30},
        "reservoirtransfer": {"F": 12, "G": 12},
    }

    def __init__(self, path, sheet_name=None, parent=None):
        super().__init__(parent)
        self.path = path
        self._loader = None            # the running _WorkbookLoader, if any
        self._load_callback = None     # what to call when that load is done
        self._busy = False             # True while the workbook is being read
        # Sheet to select when the window opens (None -> the workbook's first).
        self._initial_sheet = sheet_name
        self.sheet_name = sheet_name or ""
        self._wb = None
        self._ws = None
        self.model = None
        # One model per sheet, built on first visit and kept afterwards so edits
        # on a tab survive switching away from it.
        self._models = {}

        self.setWindowTitle(f"Excel — {os.path.basename(path)}")
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.WindowMinMaxButtonsHint
                            | Qt.WindowCloseButtonHint)
        if not self._init_geometry_memory("excel_workbook"):
            self.resize(900, 600)
        try:
            icon = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(__file__)))), 'assets', 'cwatm.ico')
            if os.path.exists(icon):
                self.setWindowIcon(QIcon(icon))
        except Exception:
            pass

        self._build_ui()
        self._load()

    # ------------------------------------------------------------------- UI
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        # Header row: only the symbol toolbar, hard left. The sheet's name is on its
        # tab below the table (and in the window title), so it is not repeated here.
        head = QHBoxLayout()
        head.setSpacing(6)
        lay.addLayout(head)          # the buttons are added once self.table exists

        self.table = _SheetTableView()
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed)
        # Lazy: only visible cells are queried. Sample few rows when auto-sizing so a
        # huge sheet does not scan every row.
        self.table.horizontalHeader().setResizeContentsPrecision(40)
        self.table.setToolTip(
            "Type a formula:  2+3.5   2 + I3   =(A1+B1)/2   =SUM(C2:C10)\n"
            "Ctrl+C / Ctrl+X / Ctrl+V copy, cut and paste whole blocks; Delete "
            "clears them (right-click for the same menu).\nDrag the small square "
            "at the selection's corner to autofill (copy, series, lists).\n"
            "Right-click a column or row header to insert or paste columns/rows.\n"
            "Ctrl+B bolds the marked cells; Ctrl+Z / Ctrl+Y undo and redo.")
        # The frozen header row lives directly above the table (it carries the
        # column letters); the table itself hides row 1 - see _SheetTableView. Own
        # sub-layout with no spacing, so the two read as one table.
        table_box = QVBoxLayout()
        table_box.setContentsMargins(0, 0, 0, 0)
        table_box.setSpacing(0)
        table_box.addWidget(self.table.frozen)
        table_box.addWidget(self.table, 1)
        self._build_toolbar(head)    # needs self.table for its connections
        head.addStretch()            # ... so the symbols end up hard left
        lay.addLayout(table_box, 1)

        # Sheet tabs, Excel-style: directly **below** the table and **above** the
        # "N rows x M columns" info line. RoundedSouth makes them hang off the
        # table above them the way Excel's sheet tabs do.
        self.tabs = QTabBar()
        self.tabs.setShape(QTabBar.RoundedSouth)
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.ElideNone)
        self.tabs.setStyleSheet(
            "QTabBar { font-family:'Segoe UI',sans-serif; font-size:12px; }"
            "QTabBar::tab { padding:4px 14px; margin-right:2px;"
            f" color:{theme.c('text')}; background:{theme.c('surface_bg')};"
            f" border:1px solid {theme.c('border')}; border-top:none;"
            "  border-bottom-left-radius:5px; border-bottom-right-radius:5px; }"
            f"QTabBar::tab:selected {{ background:{theme.c('panel_bg')};"
            f" color:{theme.c('accent')}; font-weight:600;"
            f" border-bottom:2px solid {theme.c('accent')}; }}"
            f"QTabBar::tab:hover {{ background:{theme.c('panel_bg')}; }}")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        lay.addWidget(self.tabs)

        self.info_label = QLabel("")
        self.info_label.setStyleSheet(
            f"font-size:12px; color:{theme.c('text_muted')};")
        lay.addWidget(self.info_label)

        _btn = """
            QPushButton { font-family:'Segoe UI',sans-serif; font-size:12px;
                font-weight:500; color:white; border:none; border-radius:6px;
                padding:6px 16px; min-height:26px;
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #5dade2, stop:1 #3498db); }
            QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #85c1e9, stop:1 #5dade2); }
            QPushButton:disabled { background:#d3d3d3; color:#a9a9a9; }
        """
        _gray = _btn.replace("#5dade2", "#808080").replace("#3498db", "#606060") \
                    .replace("#85c1e9", "#a0a0a0")

        row = QHBoxLayout()
        row.setSpacing(10)
        # "Load": open ANOTHER workbook in this same editor, showing the same sheet
        # (Crops / Reservoirs) - so a different xlsx than the settings
        # Excel_settings_file can be inspected without changing the settings.
        self.load_button = QPushButton("Load")
        self.load_button.setStyleSheet(_btn)
        self.load_button.setToolTip("load another Excel file")
        self.load_button.clicked.connect(self._load_other)
        row.addWidget(self.load_button)

        self.reload_button = QPushButton("Reload")
        self.reload_button.setStyleSheet(_btn)
        self.reload_button.setToolTip("Discard edits and reload the workbook from disk")
        self.reload_button.clicked.connect(self._reload)
        row.addWidget(self.reload_button)

        self.save_button = QPushButton("Save")
        self.save_button.setStyleSheet(_btn)
        self.save_button.setToolTip("Write the edits back to the Excel file")
        self.save_button.clicked.connect(self._save)
        row.addWidget(self.save_button)

        self.save_as_button = QPushButton("Save As")
        self.save_as_button.setStyleSheet(_btn)
        self.save_as_button.clicked.connect(self._save_as)
        row.addWidget(self.save_as_button)

        row.addStretch()
        self.close_button = QPushButton("Close")
        self.close_button.setStyleSheet(_gray)
        self.close_button.clicked.connect(self.close)
        row.addWidget(self.close_button)
        lay.addLayout(row)

    # -------------------------------------------------------------- toolbar
    def _build_toolbar(self, row):
        """The symbol toolbar (right of the sheet name): copy, cut, paste, delete,
        undo, redo. Plain glyph buttons - no icon files to ship - each doing exactly
        what its keyboard shortcut does, so there is only one implementation."""
        style = (
            "QToolButton { font-size:15px; border:1px solid transparent;"
            f" border-radius:5px; padding:2px 7px; color:{theme.c('text')}; }}"
            f"QToolButton:hover {{ background:{theme.c('surface_bg')};"
            f" border-color:{theme.c('border')}; }}"
            f"QToolButton:pressed {{ background:{theme.c('border')}; }}"
            f"QToolButton:disabled {{ color:{theme.c('text_gray')}; }}")
        self._tool_buttons = {}
        buttons = [
            ("copy", "⧉", "Copy the selected cells (Ctrl+C)"),
            ("cut", "✂", "Cut the selected cells (Ctrl+X)"),
            ("paste", "📋", "Paste at the current cell (Ctrl+V)"),
            ("delete", "🗑", "Clear the selected cells (Delete)"),
            (None, None, None),                      # separator
            ("bold", "B", "Bold the marked cells - press again to un-bold (Ctrl+B)"),
            (None, None, None),
            ("undo", "↶", "Undo the last change (Ctrl+Z)"),
            ("redo", "↷", "Redo (Ctrl+Y)"),
        ]
        for key, glyph, tip in buttons:
            if key is None:
                line = QLabel("│")
                line.setStyleSheet(f"color:{theme.c('border')};")
                row.addWidget(line)
                continue
            button = QToolButton()
            button.setText(glyph)
            button.setToolTip(tip)
            button.setAutoRaise(True)
            button.setStyleSheet(style)
            # Never take the focus: the button must act on the cells the user just
            # marked (in the table or in the header strip), not move the focus away
            # from them first - see _SheetTableView.set_active_view.
            button.setFocusPolicy(Qt.NoFocus)
            row.addWidget(button)
            self._tool_buttons[key] = button
        t = self.table
        self._tool_buttons["copy"].clicked.connect(t.copy_selection)
        self._tool_buttons["cut"].clicked.connect(lambda: t.copy_selection(cut=True))
        self._tool_buttons["paste"].clicked.connect(t.paste_clipboard)
        self._tool_buttons["delete"].clicked.connect(t.clear_selection)
        self._tool_buttons["bold"].clicked.connect(t.toggle_bold)
        self._tool_buttons["bold"].setStyleSheet(
            style + "QToolButton { font-weight:900; }")
        self._tool_buttons["undo"].clicked.connect(t.undo)
        self._tool_buttons["redo"].clicked.connect(t.redo)
        QGuiApplication.clipboard().dataChanged.connect(self._update_toolbar)
        # Moving between the table and the header strip changes whose selection the
        # buttons act on, so it changes what they may do.
        t.activeViewChanged.connect(self._update_toolbar)

    def _update_toolbar(self, *_):
        """Grey out what cannot be done right now (no selection / empty clipboard /
        nothing to undo)."""
        buttons = getattr(self, "_tool_buttons", None)
        if not buttons:
            return
        try:
            has_selection = self.table.selected_block() is not None
            for key in ("copy", "cut", "delete", "bold"):
                buttons[key].setEnabled(has_selection)
            buttons["paste"].setEnabled(
                self.table.clipboard_block() is not None)
            model = self.model
            buttons["undo"].setEnabled(model is not None and model.can_undo())
            buttons["redo"].setEnabled(model is not None and model.can_redo())
        except RuntimeError:
            pass                       # the window is closing

    # ----------------------------------------------------------------- load
    def _load(self, on_done=None):
        """Load self.path in the background, then (re)build the sheet tabs and show
        one sheet. The window stays responsive while the file is read (that can take
        tens of seconds from a network share); ``on_done(ok)`` is called afterwards -
        the Load button uses it to fall back to the previously shown workbook."""
        if self._loader is not None:
            return                    # a load is already running
        self._set_busy(True)
        self._load_callback = on_done
        loader = _WorkbookLoader(self.path)
        self._loader = loader
        # Connected to a **bound method of this window**, never to a bare lambda: a
        # lambda has no receiver object, so Qt makes the connection *direct* and the
        # slot would run in the loader thread and touch widgets from there. With a
        # QObject receiver living in the GUI thread the connection is queued, which
        # is the whole point of loading in a thread.
        loader.done.connect(self._on_loaded)
        loader.start()

    def _set_busy(self, busy):
        """While the workbook is being read: say so, and disable everything that
        would act on a workbook that is not there yet."""
        self._busy = busy
        if busy:
            self.info_label.setText(f"Loading {os.path.basename(self.path)} …")
            QGuiApplication.setOverrideCursor(Qt.BusyCursor)
        else:
            QGuiApplication.restoreOverrideCursor()
        for widget in (self.load_button, self.reload_button, self.save_button,
                       self.save_as_button, self.tabs, self.table,
                       self.table.frozen):
            widget.setEnabled(not busy)

    def _on_loaded(self, wb, error):
        """The loader came back (queued onto the GUI thread)."""
        self._loader = None
        on_done, self._load_callback = self._load_callback, None
        self._set_busy(False)
        if wb is None or not wb.sheetnames:
            QMessageBox.warning(
                self, "Excel", f"Could not open the Excel file:\n{error}"
                if wb is None else "The workbook has no sheets.")
            self.info_label.setText(self.path)
            if on_done is not None:
                on_done(False)
            return
        self._show_workbook(wb)
        if on_done is not None:
            on_done(True)

    def _show_workbook(self, wb):
        self._wb = wb
        self._models = {}                          # models belong to the old workbook
        # Keep the sheet the user was on if the new workbook also has it; else the
        # sheet asked for at construction; else simply the first one.
        wanted = self.sheet_name or self._initial_sheet
        if wanted not in wb.sheetnames:
            wanted = self._initial_sheet if self._initial_sheet in wb.sheetnames \
                else wb.sheetnames[0]
        self._rebuild_tabs(wanted)
        return True

    def _rebuild_tabs(self, current):
        """Fill the tab bar with the workbook's sheet names and show ``current``."""
        bar = self.tabs
        bar.blockSignals(True)
        while bar.count():
            bar.removeTab(0)
        for name in self._wb.sheetnames:
            bar.addTab(name)
        index = self._wb.sheetnames.index(current)
        bar.setCurrentIndex(index)
        bar.blockSignals(False)
        self._show_sheet(current)

    def _on_tab_changed(self, index):
        # The tab *text* can carry an edit marker ("Crops *"), so the sheet is
        # looked up by position, never by label.
        if self._wb is None or not (0 <= index < len(self._wb.sheetnames)):
            return
        self._show_sheet(self._wb.sheetnames[index])

    def _show_sheet(self, name):
        """Put ``name`` into the table, building its model on first visit."""
        if self._wb is None or name not in self._wb.sheetnames:
            return
        self.sheet_name = name
        self._ws = self._wb[name]
        model = self._models.get(name)
        if model is None:
            model = ExcelSheetModel(self._ws, self)
            model.dataChanged.connect(self._refresh_tab_labels)
            model.undoStateChanged.connect(self._update_toolbar)
            self._models[name] = model
        self.model = model
        self.table.setModel(model)
        # Stamp what is on screen, so a column/row copied from a header cannot be
        # pasted into a different sheet (or a different workbook).
        self.table.set_source(self.path, name)
        nrows, ncols = model.rowCount(), model.columnCount()
        # Column widths live on the view, so re-size on every sheet switch (still
        # cheap thanks to the resize precision). Only for a modest sheet; wide
        # sheets keep a sensible default width.
        if ncols <= 60:
            self.table.resizeColumnsToContents()
            # ... and to the **header** row as well, which the line above cannot see
            # (the body hides row 1). Without this a long header ran into the next
            # column - the column-E-over-column-F overlap on the Reservoirs sheet.
            self.table.fit_header_widths()
            self.table.cap_column_widths()     # never wider than ~100 characters
            # A text column gets **half** the width its content asked for and wraps
            # instead (long descriptions would otherwise push the numbers off
            # screen); re-widening it re-wraps, see _SheetTableView.
            self.table.wrap_columns(
                [c for c in range(ncols) if model.is_text_column(c)])
        else:
            # Column widths live on the **view**, so a wide sheet would otherwise
            # inherit whatever the previously shown sheet's columns were (setting the
            # default size does not touch a section that was already sized) - the
            # first columns then had one width and the rest another. Every column is
            # therefore given the width explicitly, signals blocked so the 1000
            # resizes do not each re-sync the strip; sync_frozen_columns below does
            # it once.
            header = self.table.horizontalHeader()
            blocked = header.blockSignals(True)
            try:
                header.setDefaultSectionSize(self._WIDE_COL)
                for c in range(ncols):
                    self.table.setColumnWidth(c, self._WIDE_COL)
                # A wide sheet is a data matrix, but its first columns name the rows
                # (Reservoirs_downstream: the station in B, its river in C), so B and
                # C get 70 % more room than the rest.
                for c in (1, 2):
                    if c < ncols:
                        self.table.setColumnWidth(c, int(self._WIDE_COL * 1.7))
            finally:
                header.blockSignals(blocked)
            self.table._forget_fitted_rows()
        self._apply_sheet_minimums(name, ncols)
        self.table.sync_frozen_columns()      # keep the frozen first row aligned
        self.info_label.setText(f"{nrows} rows × {ncols} columns   |   {self.path}")
        # Both selections drive the toolbar: the header row is marked on the strip,
        # everything else in the table (see _SheetTableView._selection_source).
        for view in (self.table, self.table.frozen):
            if view.selectionModel() is not None:
                view.selectionModel().selectionChanged.connect(self._update_toolbar)
        self._update_toolbar()

    def _apply_sheet_minimums(self, name, ncols):
        """Give the columns listed in ``_SHEET_MIN_CHARS`` for this sheet at least the
        width they need to be readable - what a column *contains* is not always what
        makes it legible (a reservoir ID cut to '4000…' is useless). Never narrows a
        column that is already wider."""
        wanted = self._SHEET_MIN_CHARS.get(_sheet_key(name))
        if not wanted:
            return
        char = self.table.fontMetrics().averageCharWidth() or 7
        changed = False
        for letter, chars in wanted.items():
            c = _column_index(letter)
            width = chars * char + 12          # + the cell's left/right padding
            if 0 <= c < ncols and self.table.columnWidth(c) < width:
                self.table.setColumnWidth(c, width)
                changed = True
        if changed:
            self.table._forget_fitted_rows()

    def _refresh_tab_labels(self, *_):
        """Mark the tabs of sheets holding unsaved edits with a trailing '*'."""
        if self._wb is None:
            return
        for i, name in enumerate(self._wb.sheetnames):
            if i >= self.tabs.count():
                break
            model = self._models.get(name)
            edited = model is not None and model.has_edits()
            self.tabs.setTabText(i, f"{name} *" if edited else name)

    # ----------------------------------------------------------------- save
    def _has_edits(self):
        return any(m.has_edits() for m in self._models.values())

    def _write(self, path):
        if self._wb is None:
            return False
        for model in self._models.values():       # every visited sheet, not just this one
            model.flush_to_wb()
        self._refresh_tab_labels()
        try:
            self._wb.save(path)
            return True
        except PermissionError:
            QMessageBox.warning(
                self, "Save",
                "Could not save - the file is open in Excel (or read-only).\n"
                "Close it there and try again.")
        except Exception as e:
            QMessageBox.warning(self, "Save", f"Could not save the file:\n{e}")
        return False

    def _save(self):
        if self._write(self.path):
            self.info_label.setText(f"Saved: {self.path}")

    def _save_as(self):
        start = os.path.splitext(self.path)[0] + "_edited.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Excel as", start, "Excel files (*.xlsx)")
        if not path:
            return
        if self._write(path):
            self.path = path
            self.setWindowTitle(f"Excel — {os.path.basename(path)}")
            self.info_label.setText(f"Saved: {path}")

    def _load_other(self):
        """Load button: pick another .xlsx and show ITS sheets in this window. The
        settings file is untouched - Save then writes to the newly loaded workbook,
        which is why unsaved edits are confirmed away first."""
        if self._has_edits():
            if QMessageBox.question(
                    self, "Load",
                    "Discard your edits and load another Excel file?") \
                    != QMessageBox.Yes:
                return
        start = os.path.dirname(self.path) if self.path else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load an Excel file", start,
            "Excel files (*.xlsx);;All files (*)")
        if not path:
            return
        previous = self.path
        self.path = path

        def loaded(ok):
            if ok:
                self.setWindowTitle(f"Excel — {os.path.basename(path)}")
            elif previous and previous != path:
                # Unreadable file: go back to what was on screen, so the window never
                # ends up showing one workbook while self.path (what Save writes to)
                # points at another.
                self.path = previous
                self._load()
                self.setWindowTitle(f"Excel — {os.path.basename(previous)}")

        self._load(loaded)

    def _reload(self):
        if self._has_edits():
            if QMessageBox.question(
                    self, "Reload",
                    "Discard your edits and reload the workbook from disk?") \
                    != QMessageBox.Yes:
                return
        self._load()

    # ---------------------------------------------------------------- close
    def closeEvent(self, event):
        """Never lose edits silently: ask before closing a workbook with changes on
        any sheet (Save writes them all, Discard throws them away)."""
        if self._loader is not None:
            # Closed while the workbook is still being read: drop the result (this
            # window is going away) and let the thread finish on its own - it holds
            # itself alive, so nothing is destroyed under it.
            try:
                self._loader.done.disconnect(self._on_loaded)
            except (RuntimeError, TypeError):
                pass
            self._loader = None
            self._load_callback = None
            self._set_busy(False)
        if not self._has_edits():
            event.accept()
            return
        sheets = sorted(name for name, model in self._models.items()
                        if model.has_edits())
        answer = QMessageBox.question(
            self, "Close",
            "There are unsaved changes in: " + ", ".join(sheets) +
            ".\n\nSave them before closing?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save)
        if answer == QMessageBox.Cancel:
            event.ignore()
            return
        if answer == QMessageBox.Save and not self._write(self.path):
            event.ignore()             # the save failed - stay open, keep the edits
            return
        event.accept()
