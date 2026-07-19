"""
Hidden Run CWatM window (RUN CWATM > Hidden Run CWatM).

A small, self-contained window that runs CWatM on a settings file in its **own OS
process**, completely independent of the main window and of every other Hidden Run
window - so you can start several runs in parallel while the main GUI stays fully
interactive.

Each window:
  - opens pre-loaded with a settings file (the one currently loaded in the main
    window, i.e. an .ini in that file's directory) - a "Load" button lets you pick a
    different .ini;
  - shows the settings-file path in bold green;
  - has a "Run CWatM" button (toggles to "Stop CWatM" while running);
  - streams the run into its own read-only output box (per-timestep discharge line
    overwrites in place via '\\r', errors in dark red - like the main output box).

The run reuses the subprocess worker (``CWatMProcessWorker``) with an ``output_sink``
so the model output lands in THIS window's box instead of the main one. The worker
runs the model in a separate process (real Stop = kill, crash isolation), which is
exactly what lets several of these run side by side without interfering.
"""

import os

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QFileDialog, QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QTextCursor, QTextCharFormat

from src.gui.utils import theme
from src.gui.utils.gui_log import get_logger
from src.gui.utils.cwatm_process_worker import CWatMProcessWorker

log = get_logger("hidden_run_window")


class HiddenRunWindow(QDialog):
    """A non-modal window that runs CWatM on one settings file in its own process."""

    def __init__(self, main_window, settings_path=None):
        super().__init__(main_window)
        self._main = main_window
        self._worker = None
        self._running = False
        self._last_was_progress = False
        # Pre-load: the given path, else the settings file currently loaded in the
        # main window (an .ini in that file's directory).
        self._settings_path = settings_path or self._current_main_settings()

        self.setWindowTitle("Hidden Run CWatM")
        # Non-modal so the main GUI (and other Hidden Run windows) stay interactive.
        self.setModal(False)
        # Delete on close so a closed window frees its resources (and its parent's
        # reference list entry via the destroyed signal); closeEvent still runs first
        # to kill an in-flight run.
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        self.resize(720, 460)
        try:
            icon_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
                    __file__)))), 'assets', 'cwatm.ico')
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            log.debug("hidden-run icon failed", exc_info=True)

        self._build_ui()
        self._refresh_settings_label()

    # ------------------------------------------------------------------ helpers
    def _current_main_settings(self):
        try:
            return self._main.file_manager.get_current_file_path() or ""
        except Exception:
            return ""

    def _settings_dir(self):
        """Directory of the current settings file (for the Load dialog start dir)."""
        if self._settings_path and os.path.isfile(self._settings_path):
            return os.path.dirname(self._settings_path)
        cur = self._current_main_settings()
        return os.path.dirname(cur) if cur else ""

    # ----------------------------------------------------------------------- UI
    def _build_ui(self):
        self.setStyleSheet(f"QDialog {{ background-color: {theme.c('window_bg')}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Row: "Settings:" caption + the file path in bold green + Load button
        top = QHBoxLayout()
        top.setSpacing(8)
        caption = QLabel("Settings:")
        caption.setStyleSheet(
            f"font-family: 'Segoe UI', sans-serif; color: {theme.c('text')};")
        self.settings_label = QLabel("")
        self.settings_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.settings_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.load_button = QPushButton("Load")
        self.load_button.setToolTip("Choose a different settings (.ini) file to run")
        self.load_button.clicked.connect(self._on_load)
        top.addWidget(caption)
        top.addWidget(self.settings_label, 1)
        top.addWidget(self.load_button)
        layout.addLayout(top)

        # Output box (read-only, monospace, themed like the main output box)
        self.output_box = QPlainTextEdit()
        self.output_box.setReadOnly(True)
        self.output_box.setMaximumBlockCount(5000)
        self.output_box.setStyleSheet(f"""
            QPlainTextEdit {{
                background-color: {theme.c('out_bg')};
                border: 1px solid {theme.c('out_border')};
                padding: 0px;
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                font-size: 12px;
                color: {theme.c('out_text')};
            }}
        """)
        layout.addWidget(self.output_box, 1)

        # Bottom row: Run/Stop (left) + Close (right)
        self.run_button = QPushButton("Run CWatM")
        self.run_button.setStyleSheet(self._run_button_style(running=False))
        self.run_button.clicked.connect(self._toggle_run)

        close_button = QPushButton("Close")
        close_button.setStyleSheet(
            "QPushButton { font-family: 'Segoe UI', sans-serif; font-size: 12px; "
            "padding: 6px 16px; min-height: 26px; }")
        close_button.clicked.connect(self.close)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.run_button)
        btn_row.addStretch()
        btn_row.addWidget(close_button)
        layout.addLayout(btn_row)

    @staticmethod
    def _run_button_style(running):
        # Blue = Run (idle), red = Stop (running) - same look as the main RUN button.
        base = "#c0392b" if running else "#2980b9"
        hover = "#e74c3c" if running else "#3498db"
        return (f"QPushButton {{ font-family: 'Segoe UI', sans-serif; font-size: 12px; "
                f"font-weight: 600; color: white; border: none; border-radius: 6px; "
                f"padding: 6px 18px; min-height: 26px; background: {base}; }}"
                f"QPushButton:hover {{ background: {hover}; }}"
                f"QPushButton:disabled {{ background: #d3d3d3; color: #a9a9a9; }}")

    def _refresh_settings_label(self):
        """Show the settings-file path in bold green (grey hint if none loaded)."""
        if self._settings_path:
            self.settings_label.setText(self._settings_path)
            self.settings_label.setStyleSheet(
                "font-family: 'Segoe UI', sans-serif; font-size: 12px; "
                "font-weight: 700; color: #1a9a3c;")   # bold green
            self.run_button.setEnabled(True)
            self.setWindowTitle(
                f"Hidden Run CWatM - {os.path.basename(self._settings_path)}")
        else:
            self.settings_label.setText("(no settings file - press Load)")
            self.settings_label.setStyleSheet(
                f"font-family: 'Segoe UI', sans-serif; font-size: 12px; "
                f"font-style: italic; color: {theme.c('text_muted')};")
            self.run_button.setEnabled(False)

    # --------------------------------------------------------------- load / run
    def _on_load(self):
        if self._running:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Open settings file", self._settings_dir(),
            "Settings files (*.ini *.txt);;All files (*)")
        if not path:
            return
        self._settings_path = path
        self._refresh_settings_label()

    def _toggle_run(self):
        if self._running:
            self._stop_run()
        else:
            self._start_run()

    def _start_run(self):
        if not self._settings_path or not os.path.isfile(self._settings_path):
            self._append_output("Settings file not found - press Load to choose one.\n",
                                True)
            return
        self._running = True
        self._last_was_progress = False
        self.run_button.setText("Stop CWatM")
        self.run_button.setStyleSheet(self._run_button_style(running=True))
        self.load_button.setEnabled(False)
        self._append_output(
            "\n=== Running: %s ===\n" % self._settings_path, False)

        self._worker = CWatMProcessWorker(
            self._settings_path, self, output_sink=self._append_output)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _stop_run(self):
        if self._worker is not None:
            try:
                self._worker.stop()
            except Exception:
                log.debug("hidden-run stop failed", exc_info=True)
        self._append_output("\n=== Stopped by user ===\n", True)
        self._reset_after_run()

    def _on_finished(self, success, last_dis):
        if success:
            tail = "" if last_dis is None else " (last discharge: %s)" % last_dis
            self._append_output("\n=== CWatM finished successfully%s ===\n" % tail, False)
        else:
            self._append_output("\n=== CWatM finished with errors ===\n", True)
        self._reset_after_run()

    def _on_error(self, message):
        self._append_output("\n=== Error: %s ===\n" % message, True)
        self._reset_after_run()

    def _reset_after_run(self):
        self._running = False
        self.run_button.setText("Run CWatM")
        self.run_button.setStyleSheet(self._run_button_style(running=False))
        self.load_button.setEnabled(True)
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    # -------------------------------------------------------------- output box
    def _append_output(self, text, is_error=False):
        """Append run output. A '\\r'-led piece overwrites the previous progress line
        in place (per-timestep discharge), mirroring the main output box; errors are
        drawn in dark red. Called on the GUI thread by the worker's output_sink."""
        stripped = text.strip()
        if not stripped:
            return
        is_progress = text.lstrip(" \t").startswith("\r")

        box = self.output_box
        scroll = box.verticalScrollBar()
        at_bottom = scroll.value() >= scroll.maximum() - 10

        fmt = QTextCharFormat()
        fmt.setForeground(theme.qcolor("out_error" if is_error else "out_text"))
        cursor = QTextCursor(box.document())
        cursor.beginEditBlock()
        try:
            cursor.movePosition(QTextCursor.End)
            if is_progress and self._last_was_progress:
                cursor.movePosition(QTextCursor.StartOfBlock, QTextCursor.KeepAnchor)
                cursor.removeSelectedText()
            elif box.document().characterCount() > 1:
                cursor.insertBlock()
            cursor.insertText(stripped, fmt)
            self._last_was_progress = is_progress
        finally:
            cursor.endEditBlock()

        if at_bottom:
            scroll.setValue(scroll.maximum())

    # --------------------------------------------------------------- lifecycle
    def closeEvent(self, event):
        """Kill this window's run (if any) so a closed window never leaves an orphan
        model process running."""
        if self._worker is not None:
            try:
                self._worker.stop()
            except Exception:
                log.debug("hidden-run close stop failed", exc_info=True)
            self._worker = None
        super().closeEvent(event)
