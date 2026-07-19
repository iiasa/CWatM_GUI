"""
Run Ledger window (RUN CWATM ▸ Run Ledger) for the CWatM GUI.

A table of past model runs recorded by ``src/gui/utils/run_ledger.py`` (one row per
completed run: time, Title, settings file, PathOut, duration, success, last
discharge). Each row is actionable:
- **Open results** - open the run's PathOut in the Output Explorer (or the file
  browser) to inspect its output;
- **Load settings** - reload the run's settings file into the main window (if it
  still exists).

Non-modal; themed at construction like the other secondary windows; geometry key
``run_ledger``.
"""

import os
import time

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from src.gui.utils.window_geometry import GeometryMemoryMixin
from src.gui.utils import theme
from src.gui.utils import run_ledger
from src.gui.utils import display_format
from src.gui.utils.gui_log import get_logger

log = get_logger("run_ledger_window")


def open_run_ledger(parent=None):
    """Open the Run Ledger window (kept alive on the parent so it is not GC'd)."""
    win = RunLedgerWindow(parent)
    win.show()
    win.raise_()
    win.activateWindow()
    try:
        if not hasattr(parent, "_run_ledger_windows"):
            parent._run_ledger_windows = []
        parent._run_ledger_windows.append(win)
        win.destroyed.connect(
            lambda *_: parent._run_ledger_windows.remove(win)
            if win in parent._run_ledger_windows else None)
    except Exception:
        pass
    return win


class RunLedgerWindow(GeometryMemoryMixin, QDialog):
    """Table of past runs; open each run's results or reload its settings."""

    _COLS = ["When", "Title", "PathOut", "Duration", "OK", "Last dis", "Settings"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("\U0001F4D2 Run Ledger")
        self.setModal(False)
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        if not self._init_geometry_memory("run_ledger"):
            self.resize(940, 520)
        self._set_window_icon()
        self._entries = []          # newest-first, aligned with table rows
        self._build_ui()
        self._apply_theme()
        self._reload()

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

        self.header_label = QLabel("Run Ledger")
        self.header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.header_label)

        self.sub_label = QLabel("")
        self.sub_label.setAlignment(Qt.AlignCenter)
        self.sub_label.setWordWrap(True)
        layout.addWidget(self.sub_label)

        self.table = QTableWidget(0, len(self._COLS))
        self.table.setHorizontalHeaderLabels(self._COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        # Extended selection so two rows can be marked (Ctrl/Shift+click) for Compare.
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.doubleClicked.connect(lambda *_: self._open_results())
        self.table.itemSelectionChanged.connect(self._update_compare_enabled)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)   # PathOut
        hh.setSectionResizeMode(6, QHeaderView.Stretch)   # Settings
        layout.addWidget(self.table, 1)

        self.open_button = QPushButton("Open results")
        self.open_button.setToolTip("Open this run's PathOut in the Output Explorer")
        self.open_button.clicked.connect(self._open_results)
        self.load_button = QPushButton("Load settings")
        self.load_button.setToolTip("Reload this run's settings file into the main window")
        self.load_button.clicked.connect(self._load_settings)
        self.compare_button = QPushButton("Compare settings")
        self.compare_button.setToolTip(
            "Mark two runs (Ctrl/Shift+click) to diff their settings files")
        self.compare_button.setEnabled(False)
        self.compare_button.clicked.connect(self._compare_settings)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self._reload)
        self.clear_button = QPushButton("Clear ledger")
        self.clear_button.setToolTip("Delete all recorded runs")
        self.clear_button.clicked.connect(self._clear)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addWidget(self.open_button)
        btn_row.addWidget(self.load_button)
        btn_row.addWidget(self.compare_button)
        btn_row.addStretch()
        btn_row.addWidget(self.refresh_button)
        btn_row.addWidget(self.clear_button)
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
        for b in (self.open_button, self.load_button, self.compare_button,
                  self.refresh_button, self.clear_button, self.close_button):
            b.setStyleSheet(style)

    @staticmethod
    def _button_style():
        # Blue when enabled, gray when disabled (drives the Compare-settings button:
        # gray until exactly two runs are marked, then blue).
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
            QPushButton:disabled { background: #bdc3c7; color: #ecf0f1; }
        """

    # ----------------------------------------------------------------- data
    @staticmethod
    def _fmt_dur(seconds):
        try:
            seconds = int(float(seconds))
        except (TypeError, ValueError):
            return ""
        if seconds < 60:
            return f"{seconds}s"
        m, s = divmod(seconds, 60)
        if m < 60:
            return f"{m}m {s:02d}s"
        h, m = divmod(m, 60)
        return f"{h}h {m:02d}m"

    def _reload(self):
        entries = run_ledger.load_entries()
        entries = sorted(entries, key=lambda e: e.get("ts", 0), reverse=True)
        self._entries = entries
        self.table.setRowCount(len(entries))
        for row, e in enumerate(entries):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(e.get("ts", 0)))
            last = e.get("last_dis")
            try:
                last_txt = display_format.fmt(last) if last is not None else ""
            except (TypeError, ValueError):
                last_txt = str(last) if last is not None else ""
            ok = "yes" if e.get("success") else "no"
            kind = e.get("kind", "run")
            if kind and kind != "run":
                ok = f"{ok} ({kind})"
            values = [
                when, e.get("title", ""), e.get("pathout", ""),
                self._fmt_dur(e.get("duration_s")), ok, last_txt,
                e.get("settings", ""),
            ]
            for col, v in enumerate(values):
                item = QTableWidgetItem(str(v))
                if col in (3, 4, 5):
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, item)
        folder = run_ledger.history_dir()
        days = run_ledger.retention_days()
        keep = f"keep {days} days" if days else "keep forever"
        self.sub_label.setText(f"{len(entries)} run(s)  ·  {folder}  ·  {keep}")

    def _selected_entry(self):
        row = self.table.currentRow()
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def _selected_rows(self):
        """Sorted, distinct indices of the marked rows."""
        return sorted({idx.row() for idx in
                       self.table.selectionModel().selectedRows()})

    def _update_compare_enabled(self):
        """Compare settings is blue only when exactly two runs are marked."""
        self.compare_button.setEnabled(len(self._selected_rows()) == 2)

    def _compare_settings(self):
        """Diff the settings files of the two marked runs in the Compare window."""
        rows = self._selected_rows()
        if len(rows) != 2:
            return
        # Prefer the run-time snapshot (what actually ran) over the on-disk path.
        ea, eb = self._entries[rows[0]], self._entries[rows[1]]
        a = ea.get("snapshot") or ea.get("settings", "")
        b = eb.get("snapshot") or eb.get("settings", "")
        if not a or not b:
            QMessageBox.information(
                self, "Compare settings",
                "One of the marked runs has no settings file recorded.")
            return
        try:
            from src.gui.widgets.compare_settings_window import open_compare_files
            open_compare_files(self.parent() or self, a, b)
        except Exception as ex:
            log.warning("compare settings failed", exc_info=True)
            QMessageBox.warning(self, "Compare settings", f"Could not compare:\n{ex}")

    def _open_results(self):
        e = self._selected_entry()
        if not e:
            return
        pathout = e.get("pathout", "")
        if not pathout or not os.path.isdir(pathout):
            QMessageBox.information(
                self, "Open results",
                "This run's PathOut does not exist any more:\n" + (pathout or "(none)"))
            return
        # Prefer the Output Explorer rooted at this run's PathOut; fall back to the
        # system file browser.
        try:
            from src.gui.widgets.output_explorer import OutputExplorerWindow
            win = OutputExplorerWindow(pathout, self.parent() or self)
            win.show()
            win.raise_()
        except Exception:
            log.debug("output explorer open failed; using file browser", exc_info=True)
            try:
                os.startfile(pathout)
            except Exception as ex:
                QMessageBox.warning(self, "Open results", f"Could not open:\n{ex}")

    def _load_settings(self):
        e = self._selected_entry()
        if not e:
            return
        path = e.get("settings", "")
        if not path or not os.path.exists(path):
            QMessageBox.information(
                self, "Load settings",
                "This run's settings file does not exist any more:\n" + (path or "(none)"))
            return
        mw = self.parent()
        try:
            if mw is not None and hasattr(mw, "load_recent_file"):
                mw.load_recent_file(path)
            elif mw is not None and hasattr(mw, "file_manager"):
                mw.file_manager.load_file(path)
            else:
                raise RuntimeError("no main window to load into")
        except Exception as ex:
            QMessageBox.warning(self, "Load settings", f"Could not load:\n{ex}")

    def _clear(self):
        if QMessageBox.question(
                self, "Clear ledger", "Delete all recorded runs?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        run_ledger.clear()
        self._reload()
