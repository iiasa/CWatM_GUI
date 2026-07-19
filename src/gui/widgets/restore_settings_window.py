"""Tools ▸ Restore settingsfile - show the global metadata of a CWatM output
NetCDF (``dis*.nc``).

CWatM stamps its discharge/ET output files with global attributes describing the
run (settings file, versioning, institution, title, …). This window opens such a
file and lists those attributes in a two-column table.

The three **bulky, multi-line** attributes are intentionally hidden
(``version_settingsfile``, ``version_inputfiles``, ``version_modules``) so the
table stays readable; the concise run metadata is what is shown.

Styled like the other secondary windows: ``GeometryMemoryMixin`` + ``QDialog``,
every colour a ``theme.c(token)``, cwatm.ico, geometry key ``restore_settings``.
"""

import os
import re

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox, QFileDialog,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from src.gui.utils import theme
from src.gui.utils.window_geometry import GeometryMemoryMixin
from src.gui.utils.gui_log import get_logger

log = get_logger("restore_settings_window")

# Bulky, multi-line attributes that are not shown (per request).
_HIDDEN_ATTRS = {"version_settingsfile", "version_inputfiles", "version_modules"}


def read_netcdf_metadata(nc_path):
    """Return the global attributes of ``nc_path`` as an ordered [(name, value)]
    list, dropping the bulky hidden ones. Raises on read failure."""
    from netCDF4 import Dataset
    ds = Dataset(nc_path)
    try:
        items = []
        for name in ds.ncattrs():
            if name in _HIDDEN_ATTRS:
                continue
            items.append((name, ds.getncattr(name)))
        return items
    finally:
        ds.close()


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
        m = re.match(r"^(.*?)\s+(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?)\s*$",
                     entry)
        if m:
            name, date = m.group(1).strip(), m.group(2).strip()
        else:
            name, date = entry, ""
        key = (name, date)
        if key in seen:
            continue
        seen.add(key)
        rows.append((name, date))
    return rows


class RestoreSettingsWindow(GeometryMemoryMixin, QDialog):
    """Show the global metadata of a CWatM output NetCDF file."""

    def __init__(self, nc_path, metadata, parent=None):
        super().__init__(parent)
        self.nc_path = nc_path
        self._metadata = metadata

        self.setWindowTitle(f"\U0001F5C2 Restore settingsfile: {os.path.basename(nc_path)}")
        self.setModal(True)
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        if not self._init_geometry_memory("restore_settings"):
            self.resize(760, 520)
        self._set_window_icon()

        self._build_ui()
        self._apply_theme()
        self._fill_table()

    def _set_window_icon(self):
        try:
            root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(__file__))))
            icon_path = os.path.join(root, "assets", "cwatm.ico")
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.header_label = QLabel("NetCDF metadata")
        self.header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.header_label)

        self.sub_label = QLabel(self.nc_path)
        self.sub_label.setAlignment(Qt.AlignCenter)
        self.sub_label.setWordWrap(True)
        layout.addWidget(self.sub_label)

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
        layout.addWidget(self.table, 1)

        # Bottom-left actions: restore the stored settings file / show input files.
        self.restore_button = QPushButton("Restore settingsfile")
        self.restore_button.setToolTip(
            "Save the settings file stored in this NetCDF (version_settingsfile) to a "
            "new file and load it")
        self.restore_button.clicked.connect(self._on_restore)
        self.inputfiles_button = QPushButton("Show Inputfiles")
        self.inputfiles_button.setToolTip(
            "List the input files (name + date) recorded in version_inputfiles")
        self.inputfiles_button.clicked.connect(self._on_show_inputfiles)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addWidget(self.restore_button)
        btn_row.addWidget(self.inputfiles_button)
        btn_row.addStretch()
        btn_row.addWidget(self.close_button)
        layout.addLayout(btn_row)

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
        style = self._button_style()
        for b in (self.restore_button, self.inputfiles_button, self.close_button):
            b.setStyleSheet(style)

    @staticmethod
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

    def _fill_table(self):
        self.table.setRowCount(len(self._metadata))
        for row, (name, value) in enumerate(self._metadata):
            key_item = QTableWidgetItem(str(name))
            key_item.setToolTip(str(name))
            val_text = self._format_value(value)
            val_item = QTableWidgetItem(val_text)
            val_item.setToolTip(val_text)
            self.table.setItem(row, 0, key_item)
            self.table.setItem(row, 1, val_item)
        self.table.resizeRowsToContents()

    @staticmethod
    def _format_value(value):
        """Readable single string for a netCDF attribute (which may be an array)."""
        try:
            import numpy as np
            if isinstance(value, np.ndarray):
                value = ", ".join(str(v) for v in value.tolist())
        except Exception:
            pass
        return str(value)

    # ------------------------------------------------------------- main window
    def _main_window(self):
        """Walk up to the main window (exposes load_recent_file / _is_dirty)."""
        w = self.parent()
        while w is not None and not hasattr(w, "load_recent_file"):
            w = w.parent() if hasattr(w, "parent") else None
        return w

    # ----------------------------------------------------- restore settingsfile
    def _on_restore(self):
        """Save version_settingsfile to a new .ini and load it in the main window.
        Warns first if the currently loaded settings file has unsaved changes."""
        try:
            content = read_netcdf_attr(self.nc_path, "version_settingsfile")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Restore settingsfile",
                                f"Could not read the stored settings file:\n{e}")
            return
        if not content or not content.strip():
            QMessageBox.information(
                self, "Restore settingsfile",
                "This NetCDF file has no stored settings file "
                "(no 'version_settingsfile' attribute).")
            return

        mw = self._main_window()
        # Warn if the current settings file has unsaved edits (Save buttons blue).
        if mw is not None and getattr(mw, "_is_dirty", False):
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
                    return
            elif clicked is not cont_btn:
                return  # Cancel / closed

        # Suggest a filename/dir next to the NetCDF (or the resolved PathOut).
        start_dir = os.path.dirname(os.path.abspath(self.nc_path))
        try:
            if mw is not None and hasattr(mw, "_resolved_pathout_dir"):
                start_dir = mw._resolved_pathout_dir() or start_dir
        except Exception:
            pass
        suggested = os.path.join(start_dir, "restored_settings.ini")
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
        if mw is not None:
            try:
                mw.load_recent_file(path)
            except Exception as e:  # noqa: BLE001
                log.warning("load restored file failed", exc_info=True)
                QMessageBox.warning(
                    self, "Restore settingsfile",
                    f"Saved to {path}, but could not load it:\n{e}")
                return
        self.accept()   # close so the restored file is visible in the main window

    # --------------------------------------------------------- show input files
    def _on_show_inputfiles(self):
        try:
            value = read_netcdf_attr(self.nc_path, "version_inputfiles")
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Show Inputfiles",
                                f"Could not read the input-file list:\n{e}")
            return
        rows = parse_input_files(value) if value else []
        if not rows:
            QMessageBox.information(
                self, "Show Inputfiles",
                "This NetCDF file has no input-file list "
                "(no 'version_inputfiles' attribute).")
            return
        InputFilesWindow(self.nc_path, rows, self).exec()


class InputFilesWindow(GeometryMemoryMixin, QDialog):
    """A 2-column table (file name / date) from a NetCDF's version_inputfiles."""

    def __init__(self, nc_path, rows, parent=None):
        super().__init__(parent)
        self._rows = rows
        self.setWindowTitle(
            f"\U0001F4C4 Input files: {os.path.basename(nc_path)}")
        self.setModal(True)
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        if not self._init_geometry_memory("restore_inputfiles"):
            self.resize(620, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.header_label = QLabel(f"Input files ({len(rows)})")
        self.header_label.setAlignment(Qt.AlignCenter)
        self.header_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 14px; font-weight: 600; "
            f"color: {theme.c('text')}; padding: 4px;")
        layout.addWidget(self.header_label)

        self.table = QTableWidget(len(rows), 2)
        self.table.setHorizontalHeaderLabels(["File", "Date"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        for r, (name, date) in enumerate(rows):
            n_item = QTableWidgetItem(name)
            n_item.setToolTip(name)
            self.table.setItem(r, 0, n_item)
            self.table.setItem(r, 1, QTableWidgetItem(date))
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
        layout.addWidget(self.table, 1)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        self.close_button.setStyleSheet(RestoreSettingsWindow._button_style())
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.close_button)
        layout.addLayout(row)
        self.setStyleSheet(f"QDialog {{ background-color: {theme.c('window_bg')}; }}")
