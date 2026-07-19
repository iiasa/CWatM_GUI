"""
Batch / scenario runner (RUN CWATM ▸ Batch Run…) for the CWatM GUI.

Runs many CWatM scenarios derived from **one base settings file** (the file loaded in
the main window). Each **table row** is a scenario: a name, its own **PathOut**, and a
few **key = value overrides**; the GUI writes a temporary ``.ini`` per row (base content
with those keys replaced) next to the base file - so placeholders / relative paths
resolve identically - and runs it in its **own OS process** (`CWatMProcessWorker`, the
same subprocess worker as the main run). **Up to N run in parallel** (a spin box,
default 1); a per-row **Progress / Status** column tracks each. Every finished scenario
is recorded in the **Run Ledger**.

Non-modal so the main GUI stays usable; several scenarios run independently. Themed at
construction; geometry key ``batch_runner``.
"""

import os
import re
import json
import time
import itertools

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QPlainTextEdit, QCheckBox, QDialogButtonBox,
)
from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QIcon

from src.gui.utils.window_geometry import GeometryMemoryMixin
from src.gui.utils import theme
from src.gui.utils import run_ledger
from src.gui.utils import display_format
from src.gui.utils.cwatm_process_worker import CWatMProcessWorker
from src.gui.utils.gui_log import get_logger

log = get_logger("batch_runner")


def set_settings_key(content, key, value):
    """Return ``content`` with the first uncommented ``key = ...`` line's value replaced
    by ``value`` (indentation and key spelling preserved); appended at the end if the key
    is absent. Matches how CWatM parses a flat settings key."""
    out = []
    done = False
    for line in content.split("\n"):
        s = line.strip()
        if not done and s and s[0] not in "#;[":
            eq = s.find("=")
            if eq > 0 and s[:eq].strip().lower() == key.lower():
                indent = line[:len(line) - len(line.lstrip())]
                out.append(f"{indent}{s[:eq].strip()} = {value}")
                done = True
                continue
        out.append(line)
    if not done:
        out.append(f"{key} = {value}")
    return "\n".join(out)


def open_batch_runner(parent=None):
    """Open the Batch runner for the settings file loaded in the main window."""
    base_path = ""
    base_content = ""
    try:
        fm = getattr(parent, "file_manager", None)
        base_path = fm.get_current_file_path() if fm is not None else ""
        base_content = parent.text_area.toPlainText() if parent is not None else ""
    except Exception:
        base_path, base_content = "", ""
    if not base_path or not base_content.strip():
        QMessageBox.information(
            parent, "Batch Run",
            "Load a settings file first - it is the base for the batch scenarios.")
        return
    win = BatchRunnerWindow(base_path, base_content, parent)
    win.show()
    win.raise_()
    win.activateWindow()
    try:
        if not hasattr(parent, "_batch_runner_windows"):
            parent._batch_runner_windows = []
        parent._batch_runner_windows.append(win)
        win.destroyed.connect(
            lambda *_: parent._batch_runner_windows.remove(win)
            if win in parent._batch_runner_windows else None)
    except Exception:
        pass
    return win


class BatchRunnerWindow(GeometryMemoryMixin, QDialog):
    """Table of scenarios (base .ini + per-row overrides); runs up to N in parallel."""

    _FIXED = ["Scenario", "PathOut"]        # leading columns
    _TRAILING = ["Progress", "Status"]      # trailing columns

    def __init__(self, base_path, base_content, parent=None):
        super().__init__(parent)
        self._mw = parent
        self._base_path = base_path
        self._base_content = base_content
        self._base_dir = os.path.dirname(base_path)
        self._base_title = self._read_key(base_content, "Title") or "CWatM"
        self._base_pathout = self._read_key(base_content, "PathOut") or ""
        self._key_cols = []                 # override key names (middle columns)
        self._active = {}                   # row -> dict(worker, temp, started, pathout, name)
        self._queue = []
        self._running = False

        self.setWindowTitle("\U0001F5C2 Batch Run")
        self.setModal(False)
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        if not self._init_geometry_memory("batch_runner"):
            self.resize(900, 520)
        self._set_window_icon()

        self._build_ui()
        self._apply_theme()
        # Restore the scenario table from the previous session; else one fresh row.
        if not self._restore_config():
            self._add_row()

    def _set_window_icon(self):
        try:
            base = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(__file__))))
            icon_path = os.path.join(base, "assets", "cwatm.ico")
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass

    @staticmethod
    def _read_key(content, key):
        for line in content.split("\n"):
            s = line.strip()
            if not s or s[0] in "#;[" or "=" not in s:
                continue
            k, v = s.split("=", 1)
            if k.strip().lower() == key.lower():
                return v.strip()
        return ""

    # --------------------------------------------------------------------- UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.header_label = QLabel("Batch Run")
        self.header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.header_label)
        self.sub_label = QLabel(f"Base: {os.path.basename(self._base_path)}  ·  "
                                "each row → a temporary .ini run in its own process")
        self.sub_label.setAlignment(Qt.AlignCenter)
        self.sub_label.setWordWrap(True)
        layout.addWidget(self.sub_label)

        self.table = QTableWidget(0, len(self._FIXED) + len(self._TRAILING))
        self._refresh_headers()
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)     # PathOut
        layout.addWidget(self.table, 1)

        # Row-editing controls
        edit_row = QHBoxLayout()
        edit_row.setSpacing(8)
        self.add_row_button = QPushButton("Add scenario")
        self.add_row_button.clicked.connect(self._add_row)
        self.dup_row_button = QPushButton("Duplicate")
        self.dup_row_button.clicked.connect(self._duplicate_row)
        self.del_row_button = QPushButton("Remove")
        self.del_row_button.clicked.connect(self._remove_row)
        self.clear_button = QPushButton("Clear")
        self.clear_button.setToolTip(
            "Clear all scenarios and override columns and start fresh")
        self.clear_button.clicked.connect(self._clear_all)
        self.add_key_button = QPushButton("Add key column")
        self.add_key_button.setToolTip(
            "Add the settings key on the editor's cursor line as an override column")
        self.add_key_button.clicked.connect(self._add_key_column)
        self.sweep_button = QPushButton("Sweep…")
        self.sweep_button.setToolTip(
            "Auto-generate scenario rows from a value list or range for one or more keys "
            "(the full grid for several keys)")
        self.sweep_button.clicked.connect(self._open_sweep)
        edit_row.addWidget(self.add_row_button)
        edit_row.addWidget(self.dup_row_button)
        edit_row.addWidget(self.del_row_button)
        edit_row.addWidget(self.clear_button)
        edit_row.addStretch()
        edit_row.addWidget(self.sweep_button)
        edit_row.addWidget(self.add_key_button)
        layout.addLayout(edit_row)

        # Run controls
        run_row = QHBoxLayout()
        run_row.setSpacing(8)
        run_row.addWidget(QLabel("Parallel runs:"))
        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, 16)
        self.parallel_spin.setValue(1)
        self.parallel_spin.setToolTip("How many scenarios run at the same time")
        run_row.addWidget(self.parallel_spin)
        run_row.addStretch()
        self.run_button = QPushButton("▶ Run all")
        self.run_button.setStyleSheet(self._run_style(False))
        self.run_button.clicked.connect(self._run_all)
        self.stop_button = QPushButton("■ Stop all")
        self.stop_button.setStyleSheet(self._run_style(True))
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop_all)
        self.close_button = QPushButton("Close")
        self.close_button.setStyleSheet(self._button_style())
        self.close_button.clicked.connect(self.close)
        run_row.addWidget(self.run_button)
        run_row.addWidget(self.stop_button)
        run_row.addWidget(self.close_button)
        layout.addLayout(run_row)

        for b in self._edit_buttons():
            b.setStyleSheet(self._button_style())

    def _edit_buttons(self):
        """The row/column editing buttons (disabled while a batch is running)."""
        return (self.add_row_button, self.dup_row_button, self.del_row_button,
                self.clear_button, self.sweep_button, self.add_key_button)

    def _refresh_headers(self):
        headers = self._FIXED + self._key_cols + self._TRAILING
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)

    # column index helpers
    def _progress_col(self):
        return len(self._FIXED) + len(self._key_cols)

    def _status_col(self):
        return self._progress_col() + 1

    def _apply_theme(self):
        self.setStyleSheet(f"QDialog {{ background-color: {theme.c('window_bg')}; }}")
        self.header_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 14px; font-weight: 600; "
            f"color: {theme.c('text')}; padding: 4px;")
        self.sub_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 11px; "
            f"color: {theme.c('text_muted')}; padding: 2px 8px;")
        self.table.setStyleSheet(
            f"QTableWidget {{ background-color: {theme.c('out_bg')}; "
            f"color: {theme.c('out_text')}; border: 1px solid {theme.c('out_border')}; "
            f"border-radius: 8px; gridline-color: {theme.c('border')}; "
            f"alternate-background-color: {theme.c('surface_bg')}; "
            "font-family: 'Segoe UI', sans-serif; font-size: 12px; }}"
            f"QHeaderView::section {{ background-color: {theme.c('menubar_bg')}; "
            f"color: {theme.c('text')}; border: 0px; "
            f"border-bottom: 1px solid {theme.c('border')}; padding: 4px 8px; "
            "font-weight: 600; }}")

    @staticmethod
    def _button_style():
        return """
            QPushButton {
                font-family: 'Segoe UI', sans-serif; font-size: 12px; font-weight: 500;
                color: white; border: none; border-radius: 6px;
                padding: 5px 14px; min-height: 22px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #5dade2, stop:1 #3498db); }
            QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #85c1e9, stop:1 #5dade2); }
            QPushButton:disabled { background: #bdc3c7; color: #ecf0f1; }
        """

    @staticmethod
    def _run_style(stop):
        c0, c1 = ("#e74c3c", "#c0392b") if stop else ("#2980b9", "#3498db")
        return f"""
            QPushButton {{
                font-family: 'Segoe UI', sans-serif; font-size: 12px; font-weight: 600;
                color: white; border: none; border-radius: 6px;
                padding: 5px 16px; min-height: 22px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {c0}, stop:1 {c1}); }}
            QPushButton:disabled {{ background: #bdc3c7; color: #ecf0f1; }}
        """

    # --------------------------------------------------------------- rows / keys
    def _set_cell(self, row, col, text, editable=True):
        item = QTableWidgetItem(str(text))
        if not editable:
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(row, col, item)

    def _cell_text(self, row, col):
        it = self.table.item(row, col)
        return it.text().strip() if it is not None else ""

    def _add_row(self, name=None, pathout=None, overrides=None):
        if self._running:
            return
        row = self.table.rowCount()
        self.table.insertRow(row)
        n = row + 1
        name = name or f"scenario_{n}"
        # Default PathOut: base PathOut with a per-scenario suffix so runs don't collide.
        if pathout is None:
            pathout = f"{self._base_pathout}_{name}" if self._base_pathout else ""
        self._set_cell(row, 0, name)
        self._set_cell(row, 1, pathout)
        for i, key in enumerate(self._key_cols):
            val = (overrides or {}).get(key, "")
            self._set_cell(row, 2 + i, val)
        self._set_cell(row, self._progress_col(), "0%", editable=False)
        self._set_cell(row, self._status_col(), "idle", editable=False)

    def _duplicate_row(self):
        row = self.table.currentRow()
        if row < 0:
            return
        overrides = {k: self._cell_text(row, 2 + i)
                     for i, k in enumerate(self._key_cols)}
        base_name = self._cell_text(row, 0) or "scenario"
        self._add_row(name=f"{base_name}_copy",
                      pathout=self._cell_text(row, 1) + "_copy",
                      overrides=overrides)

    def _remove_row(self):
        if self._running:
            return
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _key_at_main_cursor(self):
        """The settings key on the main editor's current cursor line, or "" if that line
        is a comment/section/blank or has no ``key = value``."""
        mw = self._mw
        try:
            line = mw.text_area.textCursor().block().text()
        except Exception:
            return ""
        s = line.strip()
        if not s or s[0] in "#;[" or "=" not in s:
            return ""
        return s.split("=", 1)[0].strip()

    def _add_key_column(self):
        """Add an override column for the key on the settings-editor **cursor line**
        (no dialog)."""
        if self._running:
            return
        key = self._key_at_main_cursor()
        if not key:
            QMessageBox.information(
                self, "Add key column",
                "Put the cursor on a 'key = value' line in the settings editor, "
                "then press Add key column.")
            return
        if key in self._key_cols:
            self.sub_label.setText(f"'{key}' is already an override column.")
            return
        col = self._progress_col()          # insert before Progress/Status
        self.table.insertColumn(col)
        self._key_cols.append(key)
        self._refresh_headers()
        # New cells for existing rows are empty/editable; ensure items exist.
        for row in range(self.table.rowCount()):
            if self.table.item(row, col) is None:
                self._set_cell(row, col, "")

    # --------------------------------------------------------------- sweep
    @staticmethod
    def _parse_values(spec):
        """Parse a values spec into a list of value strings: a list (``3.5, 4, 4.5``) or
        a numeric range ``min:max:step`` (``3.5:4.5:0.5`` → 3.5, 4, 4.5; step optional
        → 5 steps)."""
        spec = (spec or "").strip()
        if not spec:
            return []
        if ":" in spec and "," not in spec:
            parts = [p.strip() for p in spec.split(":")]
            try:
                nums = [float(p) for p in parts]
            except ValueError:
                nums = None
            if nums and len(nums) in (2, 3):
                lo, hi = nums[0], nums[1]
                step = nums[2] if len(nums) == 3 else (hi - lo) / 4.0
                out = []
                if step == 0:
                    out = [lo]
                else:
                    n = int(round((hi - lo) / step)) + 1
                    for i in range(max(1, n)):
                        v = lo + i * step
                        if (step > 0 and v <= hi + 1e-9) or (step < 0 and v >= hi - 1e-9):
                            out.append(v)
                return ["%g" % v for v in out]
        return [t for t in re.split(r"[,\s]+", spec) if t]

    def _open_sweep(self):
        """Dialog to auto-generate scenario rows from value lists/ranges (one line per
        key; several keys → the full grid)."""
        if self._running:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Parameter sweep")
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(
            "One key per line — <key>: <values>\n"
            "values = a list (3.5, 4.0, 4.5) or a range min:max:step (3.5:4.5:0.5).\n"
            "Several keys make the full grid (every combination)."))
        edit = QPlainTextEdit()
        k = self._key_at_main_cursor()
        edit.setPlainText(f"{k}: " if k else "")
        edit.setMinimumSize(420, 110)
        v.addWidget(edit)
        replace = QCheckBox("Replace the current scenarios")
        replace.setChecked(True)
        v.addWidget(replace)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        self._apply_sweep(edit.toPlainText(), replace.isChecked())

    def _apply_sweep(self, text, replace):
        specs = []                       # [(key, [value strings])]
        for line in (text or "").split("\n"):
            line = line.strip()
            if not line:
                continue
            m = re.split(r"[:=]", line, 1)
            if len(m) < 2:
                continue
            key = m[0].strip()
            vals = self._parse_values(m[1])
            if key and vals:
                specs.append((key, vals))
        if not specs:
            QMessageBox.information(
                self, "Parameter sweep",
                "Enter at least one line like  SnowMeltCoef: 3.5, 4.0, 4.5")
            return
        total = 1
        for _k, vals in specs:
            total *= len(vals)
        if total > 200 and QMessageBox.question(
                self, "Parameter sweep",
                f"This creates {total} scenarios. Continue?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        # Replace = a clean table (drop old rows AND old override columns).
        if replace:
            self.table.setRowCount(0)
            self._key_cols = []
            self._refresh_headers()
        # Make sure every swept key has an override column.
        for key, _vals in specs:
            if key not in self._key_cols:
                col = self._progress_col()
                self.table.insertColumn(col)
                self._key_cols.append(key)
                self._refresh_headers()
                for row in range(self.table.rowCount()):
                    if self.table.item(row, col) is None:
                        self._set_cell(row, col, "")
        keys = [k for k, _ in specs]
        valuelists = [vals for _, vals in specs]
        for combo in itertools.product(*valuelists):
            name = "_".join(f"{k}{val}" for k, val in zip(keys, combo))
            safe = re.sub(r"[^\w\-.]+", "_", name).strip("_") or "scenario"
            pathout = f"{self._base_pathout}_{safe}" if self._base_pathout else ""
            overrides = {k: val for k, val in zip(keys, combo)}
            self._add_row(name=safe, pathout=pathout, overrides=overrides)

    # ------------------------------------------------------------------- run
    def _scenario_content(self, row):
        """Base content with this row's overrides + PathOut applied."""
        content = self._base_content
        for i, key in enumerate(self._key_cols):
            val = self._cell_text(row, 2 + i)
            if val:
                content = set_settings_key(content, key, val)
        pathout = self._cell_text(row, 1)
        if pathout:
            content = set_settings_key(content, "PathOut", pathout)
        return content

    def _write_scenario_ini(self, row, content):
        name = self._cell_text(row, 0) or f"scenario_{row + 1}"
        safe = re.sub(r"[^\w\-.]+", "_", name).strip("_") or f"scenario_{row + 1}"
        base = os.path.splitext(os.path.basename(self._base_path))[0]
        path = os.path.join(self._base_dir, f"{base}.batch_{safe}.ini")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def _run_all(self):
        if self._running:
            return
        if self.table.rowCount() == 0:
            return
        self._queue = list(range(self.table.rowCount()))
        self._running = True
        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        for b in self._edit_buttons():
            b.setEnabled(False)
        for row in range(self.table.rowCount()):
            self._set_cell(row, self._progress_col(), "0%", editable=False)
            self._set_cell(row, self._status_col(), "queued", editable=False)
        self._pump()

    def _pump(self):
        """Start queued scenarios until N are running; finish the batch when idle."""
        limit = self.parallel_spin.value()
        while self._queue and len(self._active) < limit:
            row = self._queue.pop(0)
            self._start_row(row)
        if not self._queue and not self._active and self._running:
            self._running = False
            self.run_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            for b in self._edit_buttons():
                b.setEnabled(True)

    def _start_row(self, row):
        try:
            content = self._scenario_content(row)
            temp = self._write_scenario_ini(row, content)
        except Exception as e:
            self._set_cell(row, self._status_col(), f"error: {e}", editable=False)
            return
        # Resolve this scenario's PathOut (placeholders expanded) for the ledger, and
        # create the output folder if it does not exist yet - CWatM does not create it
        # and would otherwise fail (e.g. out_emo-1v3_scenario_3).
        pathout = self._cell_text(row, 1)
        resolved = pathout
        try:
            from src.gui.widgets.basin_viewer import pathout_exists
            _ex, res = pathout_exists(content)
            if res:
                resolved = res
        except Exception:
            pass
        if resolved:
            try:
                os.makedirs(resolved, exist_ok=True)
            except Exception as e:
                self._set_cell(row, self._status_col(),
                               f"error: cannot create PathOut ({e})", editable=False)
                return
        worker = CWatMProcessWorker(temp, self._mw)
        self._active[row] = dict(worker=worker, temp=temp, started=time.time(),
                                 pathout=resolved, name=self._cell_text(row, 0),
                                 content=content)
        worker.progress.connect(lambda p, r=row: self._on_progress(r, p))
        worker.finished.connect(lambda ok, dis, r=row: self._on_finished(r, ok, dis))
        worker.error.connect(lambda msg, r=row: self._on_error(r, msg))
        self._set_cell(row, self._status_col(), "running", editable=False)
        worker.start()

    def _on_progress(self, row, pct):
        self._set_cell(row, self._progress_col(), f"{int(pct)}%", editable=False)

    def _on_finished(self, row, ok, last_dis):
        info = self._active.pop(row, None)
        if info is not None:
            self._log_scenario(info, ok, last_dis)
            self._set_cell(row, self._progress_col(), "100%" if ok else
                           self._cell_text(row, self._progress_col()), editable=False)
            if ok:
                dis = ""
                try:
                    dis = f" ({display_format.fmt(last_dis)})" if last_dis is not None else ""
                except (TypeError, ValueError):
                    dis = ""
                self._set_cell(row, self._status_col(), f"done{dis}", editable=False)
                # Clean up the temporary .ini on success (kept on failure for debugging).
                try:
                    os.remove(info["temp"])
                except Exception:
                    pass
            else:
                self._set_cell(row, self._status_col(), "failed", editable=False)
        self._pump()

    def _on_error(self, row, msg):
        info = self._active.pop(row, None)
        if info is not None:
            self._log_scenario(info, False, None)
            self._set_cell(row, self._status_col(),
                           f"error: {msg[:60]}", editable=False)
        self._pump()

    def _log_scenario(self, info, ok, last_dis):
        try:
            last = None
            if last_dis is not None:
                try:
                    last = float(last_dis)
                except (TypeError, ValueError):
                    last = None
            title = f"{self._base_title} [{info.get('name', '')}]"
            run_ledger.add_entry(run_ledger.make_entry(
                self._base_path, title, info.get("pathout", ""),
                info.get("started"), ok, last, kind="batch",
                content=info.get("content")))
        except Exception:
            log.debug("batch ledger logging failed", exc_info=True)

    def _stop_all(self):
        self._queue = []
        for row, info in list(self._active.items()):
            try:
                info["worker"].stop()
            except Exception:
                pass
            self._set_cell(row, self._status_col(), "stopped", editable=False)
        self._active.clear()
        self._running = False
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        for b in self._edit_buttons():
            b.setEnabled(True)

    def _clear_all(self):
        """Clear all scenarios and override columns and start fresh (one empty row)."""
        if self._running:
            return
        self.table.setRowCount(0)
        self._key_cols = []
        self._refresh_headers()
        self.parallel_spin.setValue(1)
        self._add_row()

    # -------------------------------------------------------------- persistence
    def _save_config(self):
        """Persist the current scenario table so the next open restores it."""
        try:
            rows = []
            for r in range(self.table.rowCount()):
                rows.append({
                    "name": self._cell_text(r, 0),
                    "pathout": self._cell_text(r, 1),
                    "overrides": {k: self._cell_text(r, 2 + i)
                                  for i, k in enumerate(self._key_cols)},
                })
            cfg = {"keys": list(self._key_cols),
                   "parallel": self.parallel_spin.value(),
                   "rows": rows}
            QSettings("IIASA", "CWatM_GUI").setValue(
                "batch_runner/config", json.dumps(cfg))
        except Exception:
            log.debug("batch config save failed", exc_info=True)

    def _restore_config(self):
        """Restore the scenario table from the last session; return True if anything was
        restored, else False (so the caller adds a default row)."""
        try:
            raw = QSettings("IIASA", "CWatM_GUI").value("batch_runner/config", "")
            if not raw:
                return False
            cfg = json.loads(raw)
            rows = cfg.get("rows") or []
            if not rows:
                return False
            self._key_cols = list(cfg.get("keys") or [])
            self._refresh_headers()
            self.parallel_spin.setValue(int(cfg.get("parallel", 1)))
            for rd in rows:
                self._add_row(name=rd.get("name"), pathout=rd.get("pathout"),
                              overrides=rd.get("overrides") or {})
            return True
        except Exception:
            log.debug("batch config restore failed", exc_info=True)
            return False

    def closeEvent(self, event):
        # Stop any in-flight scenario processes so none is orphaned.
        if self._active:
            self._stop_all()
        self._save_config()
        super().closeEvent(event)
