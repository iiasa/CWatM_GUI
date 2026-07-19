"""
Output explorer (Analyse ▸ Output Explorer) for the CWatM GUI.

A dockable-style browser of the resolved PathOut directory: a tree of the produced
result files where a double-click dispatches each file to the right existing viewer,
so "run → analyse" is one click instead of a file dialog per analysis:

    *.nc                        -> NetCDF map window
    *WaterCycle*/*watercycle*.csv -> Watercycle sunburst window
    other  *.csv                -> Timeseries window
    *.html                      -> opened in the system browser
    anything else               -> opened with the OS default application

Non-modal so it can stay open while the user opens several results; the viewer it
launches is the existing (modal) analysis window. Themed at construction like the
other secondary windows; geometry remembered via QSettings key ``output_explorer``.
"""

import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeView, QFileDialog, QMessageBox, QFileSystemModel,
)
from PySide6.QtCore import Qt, QDir
from PySide6.QtGui import QIcon

from src.gui.utils.window_geometry import GeometryMemoryMixin
from src.gui.utils import theme
from src.gui.utils.gui_log import get_logger

log = get_logger("output_explorer")

# File types the tree shows (directories are always shown).
_NAME_FILTERS = ["*.nc", "*.csv", "*.html", "*.txt", "*.tif", "*.map"]


def open_output_explorer(parent=None):
    """Open the Output Explorer rooted at the main window's resolved PathOut."""
    root = ""
    try:
        if parent is not None and hasattr(parent, "_resolved_pathout_dir"):
            root = parent._resolved_pathout_dir() or ""
    except Exception:
        root = ""
    if not root:
        # Fall back to the settings-file directory so the window is still useful.
        try:
            fm = getattr(parent, "file_manager", None)
            p = fm.get_current_file_path() if fm is not None else ""
            if p:
                root = os.path.dirname(p)
        except Exception:
            root = ""
    if not root or not os.path.isdir(root):
        QMessageBox.information(
            parent, "Output Explorer",
            "PathOut does not exist yet.\n\nRun the model (or use "
            "Tools ▸ Create PathOut Folder) first, then reopen the Output Explorer.")
        return
    win = OutputExplorerWindow(root, parent)
    win.show()
    win.raise_()
    win.activateWindow()
    # Keep a reference on the parent so the non-modal window is not garbage-collected.
    try:
        if not hasattr(parent, "_output_explorer_windows"):
            parent._output_explorer_windows = []
        parent._output_explorer_windows.append(win)
        win.destroyed.connect(
            lambda *_: parent._output_explorer_windows.remove(win)
            if win in parent._output_explorer_windows else None)
    except Exception:
        pass
    return win


class OutputExplorerWindow(GeometryMemoryMixin, QDialog):
    """Tree view of the PathOut directory; double-click opens the right viewer."""

    def __init__(self, root_dir, parent=None):
        super().__init__(parent)
        self._root = root_dir
        self.setWindowTitle("\U0001F4C1 Output Explorer")
        # Non-modal so several results can be inspected while it stays open.
        self.setModal(False)
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        if not self._init_geometry_memory("output_explorer"):
            self.resize(560, 620)
        self._set_window_icon()

        self._build_ui()
        self._apply_theme()
        self._set_root(root_dir)

    def _set_window_icon(self):
        try:
            base = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(__file__))))
            icon_path = os.path.join(base, "assets", "cwatm.ico")
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass

    # --------------------------------------------------------------------- UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.header_label = QLabel("Output Explorer")
        self.header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.header_label)

        self.path_label = QLabel(self._root)
        self.path_label.setAlignment(Qt.AlignCenter)
        self.path_label.setWordWrap(True)
        layout.addWidget(self.path_label)

        self.model = QFileSystemModel(self)
        self.model.setNameFilters(_NAME_FILTERS)
        self.model.setNameFilterDisables(False)  # hide non-matching files, keep dirs
        self.model.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.AscendingOrder)
        # Show name / size / modified; hide the "type" column (index 2) to save width.
        self.tree.setColumnHidden(2, True)
        self.tree.setColumnWidth(0, 300)
        self.tree.doubleClicked.connect(self._on_double_clicked)
        layout.addWidget(self.tree, 1)

        self.hint_label = QLabel(
            "Double-click a result to open it: .nc → map, .csv → timeseries, "
            "WaterCycle .csv → sunburst.")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        # Bottom actions
        self.open_button = QPushButton("Open")
        self.open_button.setToolTip("Open the selected file in the matching viewer")
        self.open_button.clicked.connect(self._open_selected)
        self.folder_button = QPushButton("Change folder…")
        self.folder_button.setToolTip("Browse another output directory")
        self.folder_button.clicked.connect(self._change_folder)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setToolTip("Re-read the directory (pick up new run output)")
        self.refresh_button.clicked.connect(self._refresh)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addWidget(self.open_button)
        btn_row.addStretch()
        btn_row.addWidget(self.refresh_button)
        btn_row.addWidget(self.folder_button)
        btn_row.addWidget(self.close_button)
        layout.addLayout(btn_row)

    def _apply_theme(self):
        self.setStyleSheet(f"QDialog {{ background-color: {theme.c('window_bg')}; }}")
        self.header_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 14px; font-weight: 600; "
            f"color: {theme.c('text')}; padding: 4px;")
        for lbl in (self.path_label, self.hint_label):
            lbl.setStyleSheet(
                "font-family: 'Segoe UI', sans-serif; font-size: 11px; "
                f"color: {theme.c('text_muted')}; padding: 2px 8px;")
        self.tree.setStyleSheet(
            f"QTreeView {{ background-color: {theme.c('out_bg')}; "
            f"color: {theme.c('out_text')}; border: 1px solid {theme.c('out_border')}; "
            f"border-radius: 8px; font-family: 'Segoe UI', sans-serif; font-size: 12px; }}"
            f"QHeaderView::section {{ background-color: {theme.c('menubar_bg')}; "
            f"color: {theme.c('text')}; border: 0px; "
            f"border-bottom: 1px solid {theme.c('border')}; padding: 4px 8px; "
            "font-weight: 600; }}")
        style = self._button_style()
        for b in (self.open_button, self.folder_button,
                  self.refresh_button, self.close_button):
            b.setStyleSheet(style)

    @staticmethod
    def _button_style():
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
        """

    # ----------------------------------------------------------------- actions
    def _set_root(self, root_dir):
        self._root = root_dir
        self.path_label.setText(root_dir)
        idx = self.model.setRootPath(root_dir)
        self.tree.setRootIndex(idx)

    def _refresh(self):
        # QFileSystemModel watches the directory, but force a re-root so a folder that
        # did not exist when the window opened (or new files) show up immediately.
        self._set_root(self._root)

    def _change_folder(self):
        d = QFileDialog.getExistingDirectory(
            self, "Choose an output directory", self._root)
        if d:
            self._set_root(d)

    def _open_selected(self):
        idx = self.tree.currentIndex()
        if idx.isValid():
            self._dispatch(self.model.filePath(idx))

    def _on_double_clicked(self, index):
        if not index.isValid():
            return
        path = self.model.filePath(index)
        if os.path.isdir(path):
            return  # let the tree expand/collapse directories itself
        self._dispatch(path)

    # ---------------------------------------------------------------- dispatch
    def _dispatch(self, path):
        """Open ``path`` in the viewer that matches its type."""
        if not path or not os.path.isfile(path):
            return
        name = os.path.basename(path)
        lower = name.lower()
        parent = self.parent()
        try:
            if lower.endswith(".nc"):
                self._open_netcdf(path, parent)
            elif lower.endswith(".csv"):
                if "watercycle" in lower:
                    self._open_watercycle(path, parent)
                else:
                    self._open_timeseries(path, parent)
            else:
                os.startfile(path)  # .html / .txt / anything else -> OS default
        except Exception as e:
            log.warning("output explorer dispatch failed", exc_info=True)
            QMessageBox.warning(
                self, "Output Explorer", f"Could not open the file:\n{e}")

    def _open_timeseries(self, path, parent):
        from src.gui.widgets.analysis_timeseries import TimeseriesWindow
        TimeseriesWindow(path, parent or self).exec()

    def _open_netcdf(self, path, parent):
        from src.gui.widgets.analysis_netcdf import NetcdfWindow
        NetcdfWindow(path, parent or self).exec()

    def _open_watercycle(self, path, parent):
        from src.gui.widgets.analysis_watercycle import WatercycleWindow
        WatercycleWindow(path, parent or self).exec()
