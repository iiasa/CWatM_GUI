"""Tools ▸ Restore settingsfile - show the global metadata of a CWatM output
NetCDF (``dis*.nc``).

CWatM stamps its discharge/ET output files with global attributes describing the
run (settings file, versioning, institution, title, …). This window opens such a
file and lists those attributes in a two-column table, with a **summary card** on
top carrying the four facts everybody actually looks for (title, creation time,
CWatM version, settings file).

The three **bulky, multi-line** attributes are not listed in the table
(``version_settingsfile``, ``version_inputfiles``, ``version_modules``) so it stays
readable - each has its own viewer instead:

* ``version_settingsfile`` -> **Preview settingsfile** (read-only ``SettingsEditor``,
  from which it can be saved, loaded into the editor unsaved, or diffed) and
  **Restore settingsfile** (write + load), plus **Compare with current**.
* ``version_inputfiles``   -> **Show Inputfiles**, which also *checks* each recorded
  file: is it still there, and is it still the same version (recorded date vs the
  file's current time stamps)?

All attributes are read in **one** ``Dataset`` open (these files often live on a
network share, where each open costs real time).

Menu-driven (``RestoreSettingsWindow._build_menubar``): **File** (Export as CSV),
**Action** (Preview settingsfile / Compare with current / Show Inputfiles) and
**Restore** (Restore settingsfile). There is no Close button - the window closes via
its title-bar X or Alt+F4. "Show in Journal" (button and backing function alike) was
removed outright rather than moved into a menu.

Styled like the other secondary windows: ``GeometryMemoryMixin`` + ``QDialog``,
every colour a ``theme.c(token)``, cwatm.ico, geometry key ``restore_settings``.
"""

import csv
import datetime
import os
import re
from configparser import ConfigParser

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox,
    QFileDialog, QMenu, QMenuBar, QApplication, QFrame,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut, QColor

from src.gui.utils import theme
from src.gui.utils.window_geometry import GeometryMemoryMixin, scaled_default_size
from src.gui.utils.gui_log import get_logger

log = get_logger("restore_settings_window")

# Bulky, multi-line attributes that are not shown in the table (each has its own
# viewer - see the module docstring).
_HIDDEN_ATTRS = {"version_settingsfile", "version_inputfiles", "version_modules"}

# The date format CWatM writes into version_inputfiles
# (cwatm/management_modules/data_handling.py: ``date1.strftime('%d/%m/%Y %H:%M')``).
_DATE_FMT = "%d/%m/%Y %H:%M"

# Value endings that make a settings entry a data file (used to find the folders a
# recorded input file may live in).
_DATA_EXTS = (".nc", ".nc4", ".tif", ".tiff", ".map", ".txt", ".csv", ".xlsx",
              ".xls", ".tss", ".zip")


# --------------------------------------------------------------- netCDF reading
def read_netcdf_attrs(nc_path):
    """**Every** global attribute of ``nc_path`` as an ordered [(name, value)] list.

    One ``Dataset`` open for the whole window - the buttons then work off this list
    instead of re-opening the file (which on a network share is the slow part)."""
    from netCDF4 import Dataset
    ds = Dataset(nc_path)
    try:
        return [(name, ds.getncattr(name)) for name in ds.ncattrs()]
    finally:
        ds.close()


def read_netcdf_metadata(nc_path):
    """The attributes shown in the table: everything except the bulky ones."""
    return [(n, v) for n, v in read_netcdf_attrs(nc_path) if n not in _HIDDEN_ATTRS]


def read_netcdf_attr(nc_path, name):
    """Return the value of a single global attribute (str) or None if absent."""
    from netCDF4 import Dataset
    ds = Dataset(nc_path)
    try:
        if name in ds.ncattrs():
            return str(ds.getncattr(name))
        return None
    finally:
        ds.close()


def parse_input_files(value):
    """Parse a ``version_inputfiles`` string (entries separated by ';', each
    '<filename> <DD/MM/YYYY HH:MM>') into an ordered [(name, date)] list, dropping
    exact duplicates."""
    rows, seen = [], set()
    for part in str(value or "").split(";"):
        entry = part.strip()
        if not entry:
            continue
        m = re.match(r"^(.*?)\s+(\d{1,2}[/\\]\d{1,2}[/\\]\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?)\s*$",
                     entry)
        if m:
            name, date = m.group(1).strip(), m.group(2).strip().replace("\\", "/")
        else:
            name, date = entry, ""
        key = (name, date)
        if key in seen:
            continue
        seen.add(key)
        rows.append((name, date))
    return rows


# ------------------------------------------------- input-file existence / version
def _resolve_placeholders(value, config):
    """Resolve ``$(section:key)`` / ``$(key)`` against the rest of the settings file;
    an unresolvable placeholder is left as it is.

    Deliberately a local copy of ``basin_viewer._resolve_settings_placeholders``:
    importing that module drags in numpy/xarray/rasterio, and this check runs in a
    worker thread where that cost is both pointless and invisible (fast-startup rule)."""
    for _ in range(10):
        placeholders = re.findall(r"\$\(([^)]+)\)", value)
        if not placeholders:
            break
        replaced_any = False
        for ph in placeholders:
            parts = ph.split(":")
            repl = None
            if len(parts) >= 2 and config.has_section(parts[0]) \
                    and config.has_option(parts[0], parts[1]):
                repl = config.get(parts[0], parts[1])
            elif len(parts) == 1:
                for section in config.sections():
                    for key, val in config.items(section):
                        if key.lower() == parts[0].lower():
                            repl = val
                            break
                    if repl is not None:
                        break
            if repl is not None:
                value = value.replace(f"$({ph})", repl)
                replaced_any = True
        if not replaced_any:
            break
    return value


def candidate_dirs(settings_content, base_dir):
    """The folders a settings file points at (every ``Path*`` value and the folder of
    every file value, placeholders resolved). That is where the recorded input files
    are looked for - CWatM stores only their **base name**
    (``data_handling.py: os.path.basename(filename)``), so a plain ``os.path.exists``
    on the recorded entry can never work."""
    dirs, seen = [], set()
    cfg = ConfigParser(interpolation=None, strict=False)
    try:
        cfg.read_string(settings_content or "")
    except Exception:
        log.debug("input-file check: settings content unparseable", exc_info=True)
        return dirs
    def add(path):
        path = os.path.normpath(path)
        key = path.lower()
        if key in seen:
            return
        seen.add(key)
        if os.path.isdir(path):
            dirs.append(path)

    for section in cfg.sections():
        for _key, raw in cfg.items(section):
            value = re.split(r"[#;]", str(raw or ""), 1)[0].strip()
            if not value or len(value) > 400:
                continue
            looks_like_path = ("/" in value or "\\" in value
                               or value.lower().endswith(_DATA_EXTS))
            if not looks_like_path:
                continue
            value = _resolve_placeholders(value, cfg)
            if "$(" in value:                     # unresolvable - nothing to look at
                continue
            if not os.path.isabs(value):
                value = os.path.join(base_dir or "", value)
            if os.path.isdir(value):
                add(value)
            else:
                parent = os.path.dirname(value)
                if parent:
                    add(parent)
    return dirs


def _dir_index(dirs, cap=300000):
    """basename(lower) -> full path for every file in ``dirs`` (one listing each)."""
    index = {}
    for folder in dirs:
        try:
            with os.scandir(folder) as it:
                for entry in it:
                    try:
                        if not entry.is_file():
                            continue
                    except OSError:
                        continue
                    index.setdefault(entry.name.lower(), entry.path)
                    if len(index) >= cap:
                        return index
        except Exception:
            continue
    return index


def check_input_files(rows, settings_content, base_dir):
    """For each recorded (name, date): is the file still there, and is it still the
    version the run used?

    Returns a list of dicts ``{name, date, status, detail, path}`` with status
    ``ok`` (found, time stamp matches) / ``changed`` (found, different time stamp) /
    ``found`` (no date recorded) / ``missing`` / ``?`` (nowhere to look)."""
    index = _dir_index(candidate_dirs(settings_content, base_dir)) \
        if settings_content else {}
    why = ("no settings file stored - nowhere to look" if not settings_content
           else "none of the folders in the settings file could be read")
    out = []
    for name, date in rows:
        row = {"name": name, "date": date, "status": "?", "detail": "", "path": ""}
        if not index:
            row["detail"] = why
            out.append(row)
            continue
        path = index.get(os.path.basename(str(name)).lower())
        if not path:
            row["status"] = "missing"
            row["detail"] = "not in any folder of the settings file"
            out.append(row)
            continue
        row["path"] = path
        stamps = {}
        try:
            st = os.stat(path)
            for label, ts in (("modified", st.st_mtime), ("created", st.st_ctime)):
                stamps[label] = datetime.datetime.fromtimestamp(ts).strftime(_DATE_FMT)
        except Exception:
            log.debug("stat failed: %s", path, exc_info=True)
        if not date:
            row["status"] = "found"
        elif date in stamps.values():
            row["status"] = "ok"
        else:
            row["status"] = "changed"
            row["detail"] = "now " + (stamps.get("modified") or stamps.get("created")
                                      or "?")
        out.append(row)
    return out


class _InputCheckWorker(QThread):
    """Runs :func:`check_input_files` off the GUI thread - the folder listings can
    take seconds on a network share."""

    done = Signal(object)          # list of dicts, or None on failure

    def __init__(self, rows, settings_content, base_dir):
        super().__init__()
        self._rows = rows
        self._content = settings_content
        self._base = base_dir

    def run(self):
        try:
            result = check_input_files(self._rows, self._content, self._base)
        except Exception:
            log.warning("input-file check failed", exc_info=True)
            result = None
        self.done.emit(result)


# ------------------------------------------------------------- table copy/export
def _selected_rows_text(table, only_current=False):
    """The marked cells as tab-separated lines (whole rows unless ``only_current``)."""
    if only_current:
        item = table.currentItem()
        return item.text() if item is not None else ""
    rows = sorted({idx.row() for idx in table.selectedIndexes()})
    if not rows:
        return ""
    lines = []
    for row in rows:
        cells = []
        for col in range(table.columnCount()):
            if table.isColumnHidden(col):
                continue
            item = table.item(row, col)
            cells.append(item.text() if item is not None else "")
        lines.append("\t".join(cells))
    return "\n".join(lines)


def _export_table_csv(table, parent, suggested):
    """Write every **visible** row of ``table`` to a user-chosen .csv."""
    path, _ = QFileDialog.getSaveFileName(parent, "Export as CSV", suggested,
                                          "CSV files (*.csv);;All files (*)")
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow([table.horizontalHeaderItem(c).text()
                             for c in range(table.columnCount())
                             if not table.isColumnHidden(c)])
            for row in range(table.rowCount()):
                if table.isRowHidden(row):
                    continue
                writer.writerow([(table.item(row, c).text()
                                  if table.item(row, c) is not None else "")
                                 for c in range(table.columnCount())
                                 if not table.isColumnHidden(c)])
    except Exception as e:  # noqa: BLE001
        QMessageBox.warning(parent, "Export as CSV", f"Could not write the file:\n{e}")
        return
    QMessageBox.information(parent, "Export as CSV", f"Written to\n{path}")


def install_table_tools(table, parent, csv_name):
    """Ctrl+C, a right-click menu (copy value / copy row(s) / export) and Export CSV
    on a read-only table - without them a value cannot be got out of the window at
    all."""
    def copy_rows():
        text = _selected_rows_text(table)
        if text:
            QApplication.clipboard().setText(text)

    def copy_value():
        text = _selected_rows_text(table, only_current=True)
        if text:
            QApplication.clipboard().setText(text)

    def menu(pos):
        m = QMenu(table)
        act_val = m.addAction("Copy value")
        act_row = m.addAction("Copy row(s)\tCtrl+C")
        m.addSeparator()
        act_csv = m.addAction("Export as CSV…")
        chosen = m.exec(table.viewport().mapToGlobal(pos))
        if chosen is act_val:
            copy_value()
        elif chosen is act_row:
            copy_rows()
        elif chosen is act_csv:
            _export_table_csv(table, parent, csv_name)

    table.setContextMenuPolicy(Qt.CustomContextMenu)
    table.customContextMenuRequested.connect(menu)
    shortcut = QShortcut(QKeySequence.Copy, table)
    shortcut.setContext(Qt.WidgetWithChildrenShortcut)
    shortcut.activated.connect(copy_rows)
    return copy_rows


# ------------------------------------------------------------------ shared style
def _table_style():
    return (f"QTableWidget {{ background-color: {theme.c('out_bg')}; "
            f"color: {theme.c('out_text')}; border: 1px solid {theme.c('out_border')}; "
            f"border-radius: 8px; gridline-color: {theme.c('border')}; "
            f"alternate-background-color: {theme.c('surface_bg')}; "
            "font-family: 'Segoe UI', sans-serif; font-size: 12px; }"
            f"QHeaderView::section {{ background-color: {theme.c('menubar_bg')}; "
            f"color: {theme.c('text')}; border: 0px; "
            f"border-bottom: 1px solid {theme.c('border')}; padding: 4px 8px; "
            "font-weight: 600; }")


def _button_style():
    """Blue gradient buttons, matching the NetCDF / Watercycle windows."""
    return """
        QPushButton {
            font-family: 'Segoe UI', sans-serif; font-size: 12px; font-weight: 500;
            color: white; border: none; border-radius: 6px;
            padding: 5px 14px; min-height: 22px;
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #5dade2, stop:1 #3498db);
        }
        QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #85c1e9, stop:1 #5dade2); }
        QPushButton:disabled { background: #d3d3d3; color: #a9a9a9; }
    """


def _format_value(value):
    """Readable single string for a netCDF attribute (which may be an array)."""
    try:
        import numpy as np
        if isinstance(value, np.ndarray):
            value = ", ".join(str(v) for v in value.tolist())
    except Exception:
        log.debug("_format_value: ignored", exc_info=True)
    return str(value)


class RestoreSettingsWindow(GeometryMemoryMixin, QDialog):
    """Show the global metadata of a CWatM output NetCDF file."""

    def __init__(self, nc_path, metadata, parent=None):
        super().__init__(parent)
        self.nc_path = nc_path
        # ``metadata`` may hold every attribute (the current call site) or already be
        # the filtered list (older callers) - keep both working.
        self._attrs = dict(metadata or {})
        self._metadata = [(n, v) for n, v in (metadata or [])
                          if n not in _HIDDEN_ATTRS]
        self._preview_window = None

        self.setWindowTitle(f"\U0001F5C2 Restore settingsfile: {os.path.basename(nc_path)}")
        self.setModal(True)
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        if not self._init_geometry_memory("restore_settings"):
            self.resize(*scaled_default_size(self, 820, 620))
        self._set_window_icon()

        self._build_ui()
        self._apply_theme()
        self._fill_summary()
        self._fill_table()
        self._update_actions()

    # ------------------------------------------------------------------ helpers
    def _attr(self, name):
        """A stored attribute as text ('' when absent)."""
        value = self._attrs.get(name)
        return "" if value is None else _format_value(value).strip()

    def _stored_settings(self):
        """The settings file this run used, or '' when the NetCDF has none."""
        return self._attr("version_settingsfile")

    def _set_window_icon(self):
        try:
            root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(__file__))))
            icon_path = os.path.join(root, "assets", "cwatm.ico")
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            log.debug("_set_window_icon: ignored", exc_info=True)

    # ---------------------------------------------------------------------- UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self._build_menubar(layout)

        self.header_label = QLabel("NetCDF metadata")
        self.header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.header_label)

        self.sub_label = QLabel(self.nc_path)
        self.sub_label.setAlignment(Qt.AlignCenter)
        self.sub_label.setWordWrap(True)
        layout.addWidget(self.sub_label)

        # Summary card: the four facts everybody looks for, without hunting the
        # alphabetical attribute list.
        self.summary_frame = QFrame()
        self.summary_grid = QGridLayout(self.summary_frame)
        self.summary_grid.setContentsMargins(10, 8, 10, 8)
        self.summary_grid.setHorizontalSpacing(10)
        self.summary_grid.setVerticalSpacing(3)
        self.summary_grid.setColumnStretch(1, 1)
        layout.addWidget(self.summary_frame)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Attribute", "Value"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setWordWrap(True)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        install_table_tools(
            self.table, self,
            os.path.join(os.path.dirname(os.path.abspath(self.nc_path)),
                         os.path.splitext(os.path.basename(self.nc_path))[0]
                         + "_metadata.csv"))
        layout.addWidget(self.table, 1)

    def _build_menubar(self, layout):
        """File (Export as CSV), Action (Preview settingsfile / Compare with current /
        Show Inputfiles) and Restore (Restore settingsfile) - the whole former button
        row became menus; tooltips moved from the buttons to the QActions, including
        the dynamic "this file cannot do X" ones (kept live in _update_actions). Show
        in Journal (button + its backing _on_show_in_journal/_journal_entry) was
        deleted outright, not moved to a menu. There is no Close button - the window
        closes via its title-bar X or Alt+F4."""
        mbar = QMenuBar(self)
        mbar.setStyleSheet(
            f"QMenuBar {{ background-color: {theme.c('menubar_bg')}; "
            f"color: {theme.c('text')}; }}"
            f"QMenuBar::item:selected {{ background-color: {theme.c('menu_sel_bg')}; }}")

        file_menu = mbar.addMenu("File")
        self.export_action = file_menu.addAction(
            "Export as CSV", lambda: _export_table_csv(
                self.table, self,
                os.path.join(os.path.dirname(os.path.abspath(self.nc_path)),
                             os.path.splitext(os.path.basename(self.nc_path))[0]
                             + "_metadata.csv")))
        self.export_action.setToolTip("Write this metadata table to a .csv file")

        action_menu = mbar.addMenu("Action")
        self.preview_action = action_menu.addAction(
            "Preview settingsfile", self._on_preview)
        self.compare_action = action_menu.addAction(
            "Compare with current", self._on_compare)
        self.inputfiles_action = action_menu.addAction(
            "Show Inputfiles", self._on_show_inputfiles)

        restore_menu = mbar.addMenu("Restore")
        self.restore_action = restore_menu.addAction(
            "Restore settingsfile", self._on_restore)

        self._menus = [file_menu, action_menu, restore_menu]  # GC guard
        layout.setMenuBar(mbar)

    def _apply_theme(self):
        self.setStyleSheet(f"QDialog {{ background-color: {theme.c('window_bg')}; }}")
        self.header_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 14px; font-weight: 600; "
            f"color: {theme.c('text')}; padding: 4px;")
        self.sub_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 11px; "
            f"color: {theme.c('text_muted')}; padding: 2px 8px;")
        self.summary_frame.setStyleSheet(
            f"QFrame {{ background-color: {theme.c('surface_bg')}; "
            f"border: 1px solid {theme.c('border')}; border-radius: 8px; }}")
        self.table.setStyleSheet(_table_style())

    # ------------------------------------------------------------ summary card
    def _summary_rows(self):
        """[(label, value)] for the card - only the entries the file actually has."""
        created = self._attr("history")
        if created.lower().startswith("created"):
            created = created[7:].strip()
        version = self._attr("Source_Software") or self._attr("Version")
        rows = [
            ("Title", self._attr("title")),
            ("Created", created),
            ("CWatM", version),
            ("Settings file", self._attr("settingsfile")),
            ("Output folder", os.path.dirname(os.path.abspath(self.nc_path))),
        ]
        return [(label, value) for label, value in rows if value]

    def _fill_summary(self):
        label_css = ("font-family: 'Segoe UI', sans-serif; font-size: 11px; "
                     f"color: {theme.c('text_muted')}; border: 0px;")
        value_css = ("font-family: 'Segoe UI', sans-serif; font-size: 12px; "
                     f"color: {theme.c('text')}; border: 0px;")
        for row, (name, value) in enumerate(self._summary_rows()):
            key = QLabel(name + ":")
            key.setStyleSheet(label_css)
            key.setAlignment(Qt.AlignRight | Qt.AlignTop)
            val = QLabel(value)
            val.setStyleSheet(value_css)
            val.setWordWrap(True)
            val.setToolTip(value)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.summary_grid.addWidget(key, row, 0)
            self.summary_grid.addWidget(val, row, 1)
        self.summary_frame.setVisible(self.summary_grid.count() > 0)

    def _fill_table(self):
        self.table.setRowCount(len(self._metadata))
        for row, (name, value) in enumerate(self._metadata):
            key_item = QTableWidgetItem(str(name))
            key_item.setToolTip(str(name))
            val_text = _format_value(value)
            val_item = QTableWidgetItem(val_text)
            val_item.setToolTip(val_text)
            self.table.setItem(row, 0, key_item)
            self.table.setItem(row, 1, val_item)
        self.table.resizeRowsToContents()

    def _update_actions(self):
        """Grey out what this file cannot do, with the reason in the tooltip - better
        than telling the user only after they clicked."""
        has_settings = bool(self._stored_settings().strip())
        for action, tip in (
                (self.preview_action,
                 "Show the settings file stored in this NetCDF, read-only"),
                (self.compare_action,
                 "Diff the stored settings file against the one loaded now "
                 "(closes this window)"),
                (self.restore_action,
                 "Save the settings file stored in this NetCDF (version_settingsfile) "
                 "to a new file and load it")):
            action.setEnabled(has_settings)
            action.setToolTip(tip if has_settings else
                              "This NetCDF has no stored settings file "
                              "(no 'version_settingsfile' attribute)")
        has_inputs = bool(self._attr("version_inputfiles").strip())
        self.inputfiles_action.setEnabled(has_inputs)
        self.inputfiles_action.setToolTip(
            "List the input files (name + date) recorded in version_inputfiles, and "
            "check whether they are still there and unchanged" if has_inputs else
            "This NetCDF has no input-file list (no 'version_inputfiles' attribute)")

    # ------------------------------------------------------------- main window
    def _main_window(self):
        """Walk up to the main window (exposes load_recent_file / _is_dirty)."""
        w = self.parent()
        while w is not None and not hasattr(w, "load_recent_file"):
            w = w.parent() if hasattr(w, "parent") else None
        return w

    def _current_settings_text(self):
        """The settings content the main window shows right now (live box values
        substituted), or '' when nothing is loaded."""
        mw = self._main_window()
        if mw is None:
            return ""
        for getter in ("_live_content",):
            try:
                text = getattr(mw, getter)()
                if text:
                    return text
            except Exception:
                log.debug("live content failed", exc_info=True)
        try:
            return mw.text_area.toPlainText()
        except Exception:
            return ""

    # ------------------------------------------------- preview / compare / load
    def _on_preview(self):
        content = self._stored_settings()
        if not content.strip():
            return
        win = SettingsPreviewWindow(self.nc_path, content, self)
        self._preview_window = win
        win.exec()

    def _on_compare(self):
        """Diff the stored settings against the loaded one.

        Compare settings is a window of its own, so this dialog (modal) steps aside
        first - otherwise the diff would open behind a blocked window."""
        content = self._stored_settings()
        if not content.strip():
            return
        mw = self._main_window()
        if mw is None:
            QMessageBox.information(self, "Compare with current",
                                    "No settings file is loaded to compare against.")
            return
        current = self._current_settings_text()
        if not current.strip():
            QMessageBox.information(self, "Compare with current",
                                    "No settings file is loaded to compare against.")
            return
        try:
            cur_name = os.path.basename(
                mw.file_manager.get_current_file_path() or "") or "current settings"
        except Exception:
            cur_name = "current settings"
        if self._preview_window is not None:
            try:
                self._preview_window.reject()
            except Exception:
                log.debug("_on_compare: ignored", exc_info=True)
        self.accept()               # let the non-modal diff window take over
        try:
            from src.gui.widgets.compare_settings_window import CompareSettingsWindow
            win = CompareSettingsWindow(mw)
            win.load_contents(current, cur_name,
                              content, f"stored in {os.path.basename(self.nc_path)}")
            win.show()
            win.raise_()
            if not hasattr(mw, "_compare_windows"):
                mw._compare_windows = []
            mw._compare_windows.append(win)
        except Exception as e:  # noqa: BLE001
            log.warning("compare with current failed", exc_info=True)
            QMessageBox.warning(mw, "Compare with current",
                                f"Could not open Compare settings:\n{e}")

    def load_into_editor(self, content):
        """Put the stored settings into the editor **without writing a file**.

        One undo step (``set_content_preserving``), so Ctrl+Z brings the current file
        back; the Save buttons turn blue because the editor now differs from the file
        on disk."""
        mw = self._main_window()
        if mw is None:
            QMessageBox.information(self, "Load into editor",
                                    "The main settings window was not found.")
            return False
        try:
            path = mw.file_manager.get_current_file_path()
        except Exception:
            path = ""
        if not path:
            QMessageBox.information(
                self, "Load into editor",
                "No settings file is loaded - use 'Restore settingsfile' to write the "
                "stored settings to a new file instead.")
            return False
        answer = QMessageBox.question(
            self, "Load into editor",
            "Replace the content of\n\n"
            f"{path}\n\n"
            "with the settings stored in this NetCDF?\n\n"
            "Nothing is written to disk - the editor is left with unsaved changes "
            "(Ctrl+Z takes it back).",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return False
        try:
            if hasattr(mw, "text_display"):
                mw.text_display.set_original_content(content)
            editor = getattr(mw, "text_area", None)
            if editor is not None and hasattr(editor, "set_content_preserving"):
                editor.set_content_preserving(content)
            else:
                raise RuntimeError("no settings editor")
            if hasattr(mw, "on_field_changed"):
                mw.on_field_changed()
        except Exception as e:  # noqa: BLE001
            log.warning("load into editor failed", exc_info=True)
            QMessageBox.warning(self, "Load into editor",
                                f"Could not load the settings:\n{e}")
            return False
        return True

    # ----------------------------------------------------- restore settingsfile
    def _suggested_name(self):
        """``<title>_<run date>.ini`` next to the NetCDF - restoring three runs into
        one folder used to give three collisions on ``restored_settings.ini``."""
        title = re.sub(r"[^A-Za-z0-9._-]+", "_", self._attr("title")).strip("_")
        stamp = ""
        created = self._attr("history")
        m = re.search(r"\w{3} (\w{3})\s+(\d{1,2}) \d{2}:\d{2}:\d{2} (\d{4})", created)
        if m:
            try:
                stamp = datetime.datetime.strptime(
                    f"{m.group(1)} {m.group(2)} {m.group(3)}", "%b %d %Y"
                ).strftime("%Y-%m-%d")
            except Exception:
                stamp = ""
        base = "_".join(p for p in (title or "restored_settings", stamp) if p)
        return base + ".ini"

    def _restore_dir(self):
        start_dir = os.path.dirname(os.path.abspath(self.nc_path))
        mw = self._main_window()
        try:
            if mw is not None and hasattr(mw, "_resolved_pathout_dir"):
                start_dir = mw._resolved_pathout_dir() or start_dir
        except Exception:
            log.debug("_restore_dir: ignored", exc_info=True)
        return start_dir

    def _confirm_unsaved(self):
        """Warn when the loaded settings file has unsaved edits. False = abort."""
        mw = self._main_window()
        if mw is None or not getattr(mw, "_is_dirty", False):
            return True
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Restore settingsfile")
        box.setText("Current settingsfile is not saved. Save it or loose content.")
        save_btn = box.addButton("Save current first", QMessageBox.AcceptRole)
        cont_btn = box.addButton("Continue (lose changes)", QMessageBox.DestructiveRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save_btn:
            try:
                mw.save_file()
            except Exception:
                log.debug("save_file failed", exc_info=True)
            if getattr(mw, "_is_dirty", False):
                QMessageBox.information(
                    self, "Restore settingsfile",
                    "The current file was not saved - restore cancelled.")
                return False
            return True
        return clicked is cont_btn

    def _on_restore(self):
        """Save version_settingsfile to a new .ini and load it in the main window.
        Warns first if the currently loaded settings file has unsaved changes."""
        content = self._stored_settings()
        if not content.strip():
            QMessageBox.information(
                self, "Restore settingsfile",
                "This NetCDF file has no stored settings file "
                "(no 'version_settingsfile' attribute).")
            return
        if not self._confirm_unsaved():
            return

        suggested = os.path.join(self._restore_dir(), self._suggested_name())
        path, _ = QFileDialog.getSaveFileName(
            self, "Save restored settings file", suggested,
            "Settings files (*.ini);;All files (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Restore settingsfile",
                                f"Could not write the file:\n{e}")
            return

        # Load the restored file into the main settings window.
        mw = self._main_window()
        if mw is not None:
            try:
                mw.load_recent_file(path)
            except Exception as e:  # noqa: BLE001
                log.warning("load restored file failed", exc_info=True)
                QMessageBox.warning(
                    self, "Restore settingsfile",
                    f"Saved to {path}, but could not load it:\n{e}")
                return
        if self._preview_window is not None:
            try:
                self._preview_window.accept()
            except Exception:
                log.debug("_on_restore: ignored", exc_info=True)
        self.accept()   # close so the restored file is visible in the main window

    # --------------------------------------------------------- show input files
    def _on_show_inputfiles(self):
        rows = parse_input_files(self._attr("version_inputfiles"))
        if not rows:
            QMessageBox.information(
                self, "Show Inputfiles",
                "This NetCDF file has no input-file list "
                "(no 'version_inputfiles' attribute).")
            return
        InputFilesWindow(self.nc_path, rows, self._stored_settings(),
                         self._settings_dir(), self).exec()

    def _settings_dir(self):
        """The folder the run's settings file lived in - relative paths inside the
        stored settings resolve against it."""
        stamped = self._attr("settingsfile")     # "<path>: <ctime>"
        path = stamped.split(": ", 1)[0].strip() if stamped else ""
        if path and os.path.isabs(path):
            return os.path.dirname(path)
        return os.path.dirname(os.path.abspath(self.nc_path))

class SettingsPreviewWindow(GeometryMemoryMixin, QDialog):
    """Read-only view of the settings file stored in a NetCDF.

    The point of the window: **look before you restore**. Until it existed the only
    way to see the stored settings was to write them somewhere and load them, i.e.
    replace the file you were working on.
    """

    def __init__(self, nc_path, content, parent=None):
        super().__init__(parent)
        self._content = content or ""
        self._owner = parent
        self.setWindowTitle(
            f"\U0001F4C4 Stored settingsfile: {os.path.basename(nc_path)}")
        self.setModal(True)
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        if not self._init_geometry_memory("restore_preview"):
            self.resize(*scaled_default_size(self, 900, 700))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        lines = self._content.count("\n") + 1 if self._content else 0
        header = QLabel(f"version_settingsfile  ·  {lines} lines  ·  read-only")
        header.setAlignment(Qt.AlignCenter)
        header.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 12px; font-weight: 600; "
            f"color: {theme.c('text')}; padding: 2px;")
        layout.addWidget(header)

        from src.gui.widgets.settings_editor import SettingsEditor
        from src.gui.widgets.compare_settings_window import _ComparePane
        self.editor = SettingsEditor()
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(SettingsEditor.NoWrap)
        self.editor.setStyleSheet(_ComparePane._editor_style())
        self.editor.load_text(self._content)
        layout.addWidget(self.editor, 1)

        self.save_button = QPushButton("Save as…")
        self.save_button.setToolTip("Write these settings to a file (does not load it)")
        self.save_button.clicked.connect(self._on_save_as)
        self.load_button = QPushButton("Load into editor (unsaved)")
        self.load_button.setToolTip(
            "Put these settings into the main editor without writing anything to "
            "disk - one Ctrl+Z takes it back")
        self.load_button.clicked.connect(self._on_load)
        self.compare_button = QPushButton("Compare with current")
        self.compare_button.setToolTip(
            "Diff these settings against the one loaded now (closes this window)")
        self.compare_button.clicked.connect(self._on_compare)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        row = QHBoxLayout()
        row.setSpacing(8)
        for b in (self.save_button, self.load_button, self.compare_button):
            row.addWidget(b)
        row.addStretch()
        row.addWidget(self.close_button)
        layout.addLayout(row)

        style = _button_style()
        for b in (self.save_button, self.load_button, self.compare_button,
                  self.close_button):
            b.setStyleSheet(style)
        self.setStyleSheet(f"QDialog {{ background-color: {theme.c('window_bg')}; }}")

    def _on_save_as(self):
        owner = self._owner
        start = owner._restore_dir() if hasattr(owner, "_restore_dir") else ""
        name = owner._suggested_name() if hasattr(owner, "_suggested_name") \
            else "restored_settings.ini"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save stored settings file", os.path.join(start, name),
            "Settings files (*.ini);;All files (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._content)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Save as", f"Could not write the file:\n{e}")
            return
        QMessageBox.information(self, "Save as", f"Written to\n{path}")

    def _on_load(self):
        owner = self._owner
        if not hasattr(owner, "load_into_editor"):
            return
        if owner.load_into_editor(self._content):
            self.accept()
            try:
                owner.accept()
            except Exception:
                log.debug("_on_load: ignored", exc_info=True)

    def _on_compare(self):
        owner = self._owner
        if hasattr(owner, "_on_compare"):
            owner._on_compare()          # closes this window and the metadata window


class InputFilesWindow(GeometryMemoryMixin, QDialog):
    """The input files a run used (from ``version_inputfiles``) - with a check of
    whether each is still on disk and still the same version."""

    _COLS = ["File", "Date at run time", "Status", "Found at"]

    def __init__(self, nc_path, rows, settings_content="", base_dir="", parent=None):
        super().__init__(parent)
        self._rows = rows
        self._settings = settings_content or ""
        self._base_dir = base_dir or ""
        self._worker = None
        self.setWindowTitle(
            f"\U0001F4C4 Input files: {os.path.basename(nc_path)}")
        self.setModal(True)
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        if not self._init_geometry_memory("restore_inputfiles"):
            self.resize(*scaled_default_size(self, 900, 620))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.header_label = QLabel(
            f"Input files ({len(rows)})   ·   double-click a file to open it")
        self.header_label.setAlignment(Qt.AlignCenter)
        self.header_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 14px; font-weight: 600; "
            f"color: {theme.c('text')}; padding: 4px;")
        layout.addWidget(self.header_label)

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 11px; "
            f"color: {theme.c('text_muted')}; padding: 0px 8px;")
        layout.addWidget(self.status_label)

        self.table = QTableWidget(len(rows), len(self._COLS))
        self.table.setHorizontalHeaderLabels(self._COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self._on_double_clicked)
        for r, (name, date) in enumerate(rows):
            n_item = QTableWidgetItem(name)
            n_item.setToolTip(name)
            self.table.setItem(r, 0, n_item)
            self.table.setItem(r, 1, QTableWidgetItem(date))
            self.table.setItem(r, 2, QTableWidgetItem(""))
            self.table.setItem(r, 3, QTableWidgetItem(""))
        self.table.setStyleSheet(_table_style())
        install_table_tools(
            self.table, self,
            os.path.join(os.path.dirname(os.path.abspath(nc_path)),
                         os.path.splitext(os.path.basename(nc_path))[0]
                         + "_inputfiles.csv"))
        layout.addWidget(self.table, 1)

        self.recheck_button = QPushButton("Re-check files")
        self.recheck_button.setToolTip(
            "Look for each recorded file again and compare its time stamp with the "
            "one the run recorded")
        self.recheck_button.clicked.connect(self._start_check)
        self.export_button = QPushButton("Export as CSV")
        self.export_button.clicked.connect(
            lambda: _export_table_csv(
                self.table, self,
                os.path.join(os.path.dirname(os.path.abspath(nc_path)),
                             os.path.splitext(os.path.basename(nc_path))[0]
                             + "_inputfiles.csv")))
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.recheck_button)
        row.addWidget(self.export_button)
        row.addStretch()
        row.addWidget(self.close_button)
        layout.addLayout(row)

        style = _button_style()
        for b in (self.recheck_button, self.export_button, self.close_button):
            b.setStyleSheet(style)
        self.setStyleSheet(f"QDialog {{ background-color: {theme.c('window_bg')}; }}")

        self._start_check()

    # ----------------------------------------------------------- the file check
    def _start_check(self):
        """Check in a QThread - listing the input folders can take seconds on a
        network share, and the window must stay usable meanwhile."""
        if self._worker is not None and self._worker.isRunning():
            return
        if not self._settings.strip():
            self.status_label.setText(
                "no settings file stored in this NetCDF - cannot check where these "
                "files live")
            self.recheck_button.setEnabled(False)
            return
        self.recheck_button.setEnabled(False)
        self.status_label.setText("checking the recorded files …")
        self._worker = _InputCheckWorker(self._rows, self._settings, self._base_dir)
        self._worker.done.connect(self._on_checked)     # bound method -> queued
        self._worker.start()

    def _on_checked(self, result):
        self.recheck_button.setEnabled(True)
        self._worker = None
        if not result:
            self.status_label.setText("the file check failed - see gui.log")
            return
        counts = {"missing": 0, "changed": 0}
        for row, info in enumerate(result):
            if row >= self.table.rowCount():
                break
            status = info.get("status", "?")
            counts[status] = counts.get(status, 0) + 1
            text = status
            if info.get("detail"):
                text = f"{status} ({info['detail']})"
            item = QTableWidgetItem(text)
            item.setToolTip(info.get("detail") or status)
            if status == "missing":
                item.setBackground(QColor(theme.c("error_line")))
            elif status == "changed":
                item.setBackground(QColor(theme.c("wrongext_line")))
            self.table.setItem(row, 2, item)
            found = QTableWidgetItem(info.get("path", ""))
            found.setToolTip(info.get("path", ""))
            self.table.setItem(row, 3, found)
            # The resolved path also on the name cell, so a double-click anywhere in
            # the row can open the file.
            name_item = self.table.item(row, 0)
            if name_item is not None:
                name_item.setData(Qt.UserRole, info.get("path", ""))
        parts = [f"{len(result)} files"]
        if counts.get("missing"):
            parts.append(f"{counts['missing']} missing")
        if counts.get("changed"):
            parts.append(f"{counts['changed']} changed since the run")
        # "?" = the file could not even be looked for. Without this the summary
        # claimed "all still there and unchanged" for a check that checked nothing.
        if counts.get("?"):
            parts.append(f"{counts['?']} could not be checked")
        if not any(counts.get(k) for k in ("missing", "changed", "?")):
            parts.append("all still there and unchanged")
        self.status_label.setText("  ·  ".join(parts))

    # -------------------------------------------------------- open an input file
    def _on_double_clicked(self, index):
        """Double-click a row -> open that input file in the NetCDF viewer (the same
        one as Analyse ▸ NetCDF); anything that is not a NetCDF goes to the desktop's
        handler."""
        if not index.isValid():
            return
        row = index.row()
        item = self.table.item(row, 0)
        path = (item.data(Qt.UserRole) or "") if item is not None else ""
        name = item.text() if item is not None else ""
        if not path:
            status = self.table.item(row, 2)
            status_text = status.text() if status is not None else ""
            if status_text.startswith("missing"):
                QMessageBox.information(
                    self, "Open input file",
                    f"'{name}' was not found in any folder of the settings file - "
                    "there is nothing to open.")
            else:
                QMessageBox.information(
                    self, "Open input file",
                    "The files have not been located yet - press 'Re-check files' "
                    "first.")
            return
        if not os.path.isfile(path):
            QMessageBox.information(self, "Open input file",
                                    f"The file is no longer there:\n{path}")
            return
        try:
            if path.lower().endswith((".nc", ".nc4")):
                from src.gui.widgets.analysis_netcdf import NetcdfWindow
                win = NetcdfWindow(path, self)
                # Without WA_DeleteOnClose every viewer opened from this list would
                # stay alive (frames, caches, a QWebEngine page each) until the window
                # closes - the same rule as the Output Explorer.
                win.setAttribute(Qt.WA_DeleteOnClose)
                win.exec()
            else:
                from src.gui.utils.open_path import open_path
                if not open_path(path):
                    raise RuntimeError("no application is registered for this file")
        except Exception as e:  # noqa: BLE001
            log.warning("opening an input file failed", exc_info=True)
            QMessageBox.warning(self, "Open input file",
                                f"Could not open the file:\n{e}")

    def closeEvent(self, event):
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.wait(3000)
        super().closeEvent(event)
