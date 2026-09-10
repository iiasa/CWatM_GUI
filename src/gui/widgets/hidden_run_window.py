"""
Windowed Run CWatM window (RUN CWATM > Windowed Run CWatM; the module, its geometry
key and the journal's `kind="hidden"` keep the older "hidden run" name).

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
import time

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
    QFileDialog, QSizePolicy, QProgressBar, QMessageBox, QApplication,
    QInputDialog,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QIcon, QTextCursor, QTextCharFormat, QShortcut, QKeySequence,
)

from src.gui.utils import theme
from src.gui.utils import run_ledger
from src.gui.utils.gui_log import get_logger
from src.gui.utils.window_geometry import GeometryMemoryMixin, scaled_default_size
from src.gui.utils.cwatm_process_worker import CWatMProcessWorker

log = get_logger("hidden_run_window")


def _fmt_dur(seconds):
    """h:mm:ss, or m:ss below an hour."""
    try:
        seconds = int(max(0, round(seconds)))
    except (TypeError, ValueError):
        return ""
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _read_key(content, key):
    """First uncommented ``key = value`` in a settings file, or ""."""
    for line in (content or "").split("\n"):
        s = line.strip()
        if not s or s[0] in "#;[" or "=" not in s:
            continue
        k, v = s.split("=", 1)
        if k.strip().lower() == key.lower():
            return v.strip()
    return ""


class HiddenRunWindow(GeometryMemoryMixin, QDialog):
    """A non-modal window that runs CWatM on one settings file in its own process."""

    def __init__(self, main_window, settings_path=None):
        super().__init__(main_window)
        self._main = main_window
        self._worker = None
        self._running = False
        self._last_was_progress = False
        self._started = None          # time.time() when the run started
        self._pct = 0                 # last progress % (drives the ETA)
        self._content = ""            # settings content the run uses (ledger snapshot)
        self._pathout = ""            # resolved PathOut (ledger + folder creation)
        self._title = ""              # settings Title (window title + ledger)
        self._find_text = ""          # last "Find in output" search (Ctrl+F / F3)
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._update_times)
        # Pre-load: the given path, else the settings file currently loaded in the
        # main window (an .ini in that file's directory).
        self._settings_path = settings_path or self._current_main_settings()

        self.setWindowTitle("Windowed Run CWatM")
        # Non-modal so the main GUI (and other Hidden Run windows) stay interactive.
        self.setModal(False)
        # Delete on close so a closed window frees its resources (and its parent's
        # reference list entry via the destroyed signal); closeEvent still runs first
        # to kill an in-flight run.
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        # Remembered size/position, like every other secondary window - then
        # **cascaded** by the number of Hidden Run windows already open, so several
        # do not land exactly on top of each other (they share one geometry key).
        if not self._init_geometry_memory("hidden_run"):
            self.resize(*scaled_default_size(self, 720, 460))
        try:
            others = [w for w in getattr(main_window, "_hidden_run_windows", [])
                      if w is not self]
            if others:
                step = 28 * len(others)
                self.move(self.x() + step, self.y() + step)
        except Exception:
            log.debug("hidden-run cascade failed", exc_info=True)
        try:
            icon_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
                    __file__)))), 'assets', 'cwatm.ico')
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            log.debug("hidden-run icon failed", exc_info=True)

        self.setAcceptDrops(True)     # drop an .ini onto the window
        self._build_ui()
        self._refresh_settings_label()
        QShortcut(QKeySequence.Find, self, activated=self._find_prompt)
        QShortcut(QKeySequence(Qt.Key_F3), self, activated=self._find_next)

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

        # Row: "Settings:" caption + the file path in bold green + Use current / Load
        top = QHBoxLayout()
        top.setSpacing(8)
        caption = QLabel("Settings:")
        caption.setStyleSheet(
            f"font-family: 'Segoe UI', sans-serif; color: {theme.c('text')};")
        self.settings_label = QLabel("")
        self.settings_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.settings_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.current_button = QPushButton("Use current")
        self.current_button.setToolTip(
            "Take the settings file currently loaded in the main window.\n"
            "(This window keeps the file it was opened with until you say so.)")
        self.current_button.clicked.connect(self._on_use_current)
        self.load_button = QPushButton("Load")
        self.load_button.setToolTip(
            "Choose a different settings (.ini) file to run - or drag one onto this "
            "window")
        self.load_button.clicked.connect(self._on_load)
        top.addWidget(caption)
        top.addWidget(self.settings_label, 1)
        top.addWidget(self.current_button)
        top.addWidget(self.load_button)
        layout.addLayout(top)

        # Row: what this run will actually produce - the settings Title and the
        # resolved PathOut. With several Hidden Run windows open, the Title is what
        # tells them apart, and the PathOut is where the results will be.
        info = QHBoxLayout()
        info.setSpacing(8)
        self.info_label = QLabel("")
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.info_label.setStyleSheet(
            f"font-family: 'Segoe UI', sans-serif; font-size: 11px; "
            f"color: {theme.c('text_muted')};")
        self.pathout_button = QPushButton("Open PathOut")
        self.pathout_button.setToolTip("Open this run's output folder")
        self.pathout_button.clicked.connect(self._on_open_pathout)
        info.addWidget(self.info_label, 1)
        info.addWidget(self.pathout_button)
        layout.addLayout(info)

        # Output box (read-only, monospace, themed like the main output box)
        self.output_box = QPlainTextEdit()
        self.output_box.setReadOnly(True)
        self.output_box.setMaximumBlockCount(5000)
        # Copy all / save / clear / find, on top of the standard read-only menu.
        self.output_box.setContextMenuPolicy(Qt.CustomContextMenu)
        self.output_box.customContextMenuRequested.connect(self._on_output_menu)
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

        # Progress row: the worker already emits `progress` per timestep - without
        # this the one run you walk away from was the only one with no idea how far
        # it had got.
        progress_row = QHBoxLayout()
        progress_row.setSpacing(8)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(18)
        self.progress_bar.setStyleSheet(
            f"QProgressBar {{ border: 1px solid {theme.c('border')}; "
            f"border-radius: 5px; background-color: {theme.c('surface_bg')}; "
            f"color: {theme.c('text')}; text-align: center; font-size: 11px; }}"
            f"QProgressBar::chunk {{ background-color: {theme.c('accent')}; "
            "border-radius: 4px; }")
        self.time_label = QLabel("")
        self.time_label.setStyleSheet(
            f"font-family: 'Segoe UI', sans-serif; font-size: 11px; "
            f"color: {theme.c('text_muted')};")
        progress_row.addWidget(self.progress_bar, 1)
        progress_row.addWidget(self.time_label)
        layout.addLayout(progress_row)

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

    def _read_settings_facts(self):
        """Title and resolved PathOut of the selected settings file, for the header.
        Best effort and cheap - the authoritative read happens in ``_preflight`` right
        before the run, in case the file changed meanwhile."""
        self._title, self._pathout, self._content = "", "", ""
        path = self._settings_path
        if not path or not os.path.isfile(path):
            return
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                self._content = fh.read()
        except Exception:
            log.debug("hidden-run header read failed", exc_info=True)
            return
        self._title = _read_key(self._content, "Title")
        try:
            from src.gui.widgets.basin_viewer import pathout_exists
            _exists, resolved = pathout_exists(self._content)
            self._pathout = resolved or ""
        except Exception:
            log.debug("hidden-run PathOut resolution failed", exc_info=True)

    def _refresh_settings_label(self):
        """Show the settings-file path in bold green (grey hint if none loaded), plus
        the run's Title and output folder underneath."""
        if self._settings_path:
            self.settings_label.setText(self._settings_path)
            self.settings_label.setStyleSheet(
                "font-family: 'Segoe UI', sans-serif; font-size: 12px; "
                f"font-weight: 700; color: {theme.c('ok_color')};")
            self.run_button.setEnabled(True)
            self._read_settings_facts()
            name = self._title or os.path.basename(self._settings_path)
            self.setWindowTitle(f"Windowed Run CWatM - {name}")
            parts = []
            if self._title:
                parts.append(f"Title: {self._title}")
            parts.append(f"PathOut: {self._pathout or '(not resolved)'}")
            self.info_label.setText("   ·   ".join(parts))
            self.pathout_button.setEnabled(bool(self._pathout))
        else:
            self.settings_label.setText("(no settings file - press Load, or drop one here)")
            self.settings_label.setStyleSheet(
                f"font-family: 'Segoe UI', sans-serif; font-size: 12px; "
                f"font-style: italic; color: {theme.c('text_muted')};")
            self.run_button.setEnabled(False)
            self.info_label.setText("")
            self.pathout_button.setEnabled(False)
        try:
            self.current_button.setEnabled(
                not self._running and bool(self._current_main_settings()))
        except RuntimeError:
            log.debug("_refresh_settings_label: ignored", exc_info=True)

    def _on_open_pathout(self):
        from src.gui.utils.open_path import open_path
        if not self._pathout or not os.path.isdir(self._pathout):
            self._append_output(
                "The output folder does not exist yet: %s\n" % (self._pathout or "-"),
                True)
            return
        if not open_path(self._pathout):
            self._append_output("Could not open %s\n" % self._pathout, True)

    def _on_use_current(self):
        """Take the file the main window has loaded **now** - this window otherwise
        keeps the one it was opened with."""
        if self._running:
            return
        path = self._current_main_settings()
        if not path:
            self._append_output("The main window has no settings file loaded.\n", True)
            return
        self._settings_path = path
        self._refresh_settings_label()

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

    def _preflight(self):
        """Read the settings file and make sure the run can even begin: the file has
        to be readable and its **PathOut** has to exist or be creatable. CWatM does
        not create that folder, so without this the run starts and dies minutes
        later - the same check the Batch runner does per scenario.

        Returns True when the run may start; writes the reason into the output box
        otherwise."""
        path = self._settings_path
        if not path or not os.path.isfile(path):
            self._append_output(
                "Settings file not found - press Load to choose one.\n", True)
            return False
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                self._content = fh.read()
        except Exception as e:
            self._append_output(f"Could not read the settings file: {e}\n", True)
            return False
        self._title = _read_key(self._content, "Title") or os.path.basename(path)
        self._pathout = ""
        try:
            from src.gui.widgets.basin_viewer import pathout_exists
            _exists, resolved = pathout_exists(self._content)
            self._pathout = resolved or ""
        except Exception:
            log.debug("hidden-run PathOut resolution failed", exc_info=True)
        if self._pathout:
            try:
                os.makedirs(self._pathout, exist_ok=True)
            except Exception as e:
                self._append_output(
                    f"PathOut cannot be created ({e}):\n  {self._pathout}\n", True)
                return False
        return True

    def _start_run(self):
        if not self._preflight():
            return
        self._running = True
        self._last_was_progress = False
        self._started = time.time()
        self._pct = 0
        self.progress_bar.setValue(0)
        self.time_label.setText("elapsed 0:00")
        self._tick.start()
        self.run_button.setText("Stop CWatM")
        self.run_button.setStyleSheet(self._run_button_style(running=True))
        self.load_button.setEnabled(False)
        self.current_button.setEnabled(False)
        self._append_output(
            "\n=== Running: %s ===\n" % self._settings_path, False)

        # Independent of the main window (incl. its File > Change Working Dir):
        # relative paths in THIS settings file resolve against ITS own folder.
        self._worker = CWatMProcessWorker(
            self._settings_path, self, output_sink=self._append_output,
            working_dir=self._settings_dir() or None)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    # ------------------------------------------------------------ progress/time
    def _on_progress(self, pct):
        self._pct = max(0, min(100, int(pct)))
        self.progress_bar.setValue(self._pct)

    def _update_times(self):
        """Elapsed, and - once there is enough progress to extrapolate from - the
        estimated time left (the same linear estimate the main window's clock uses)."""
        if not self._running or not self._started:
            return
        elapsed = time.time() - self._started
        text = f"elapsed {_fmt_dur(elapsed)}"
        if self._pct >= 3:
            remaining = elapsed / (self._pct / 100.0) - elapsed
            text += f" · remaining ~{_fmt_dur(remaining)}"
        self.time_label.setText(text)

    def _freeze_times(self, label):
        self._tick.stop()
        if self._started:
            self.time_label.setText(f"{label} {_fmt_dur(time.time() - self._started)}")

    def _log_run(self, success, last_dis=None):
        """Record the run in the **Run Ledger**, like a main or a batch run - a hidden
        run used to leave no trace in the history at all."""
        try:
            value = None
            if last_dis is not None:
                try:
                    value = float(last_dis)
                except (TypeError, ValueError):
                    value = None
            run_ledger.add_entry(run_ledger.make_entry(
                self._settings_path, self._title, self._pathout, self._started,
                success, value, kind="hidden", content=self._content))
        except Exception:
            log.debug("hidden-run ledger logging failed", exc_info=True)

    @staticmethod
    def _notify():
        """Flash the taskbar entry - a hidden run is exactly the one nobody watches."""
        try:
            QApplication.alert(QApplication.activeWindow(), 0)
        except Exception:
            log.debug("_notify: ignored", exc_info=True)

    def _stop_run(self):
        if self._worker is not None:
            try:
                self._worker.stop()
            except Exception:
                log.debug("hidden-run stop failed", exc_info=True)
        self._append_output("\n=== Stopped by user ===\n", True)
        self._freeze_times("stopped after")
        self._log_run(False)
        self._reset_after_run()

    def _on_finished(self, success, last_dis):
        if success:
            tail = "" if last_dis is None else " (last discharge: %s)" % last_dis
            self._append_output("\n=== CWatM finished successfully%s ===\n" % tail, False)
            self.progress_bar.setValue(100)
        else:
            self._append_output("\n=== CWatM finished with errors ===\n", True)
        self._freeze_times("run time" if success else "failed after")
        self._log_run(success, last_dis)
        self._reset_after_run()
        self._notify()

    def _on_error(self, message):
        self._append_output("\n=== Error: %s ===\n" % message, True)
        self._freeze_times("failed after")
        self._log_run(False)
        self._reset_after_run()
        self._notify()

    def _reset_after_run(self):
        self._running = False
        self.run_button.setText("Run CWatM")
        self.run_button.setStyleSheet(self._run_button_style(running=False))
        self.load_button.setEnabled(True)
        self.current_button.setEnabled(bool(self._current_main_settings()))
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

    # -------------------------------------------------- output menu / find / drop
    def _on_output_menu(self, pos):
        """The read-only box's standard menu plus what a run log actually needs:
        take it all, keep it, clear it, search it."""
        menu = self.output_box.createStandardContextMenu()
        menu.addSeparator()
        copy_all = menu.addAction("Copy all output")
        save_as = menu.addAction("Save output as…")
        find = menu.addAction("Find…\tCtrl+F")
        menu.addSeparator()
        clear = menu.addAction("Clear output")
        chosen = menu.exec(self.output_box.mapToGlobal(pos))
        if chosen is copy_all:
            QApplication.clipboard().setText(self.output_box.toPlainText())
        elif chosen is save_as:
            self._save_output()
        elif chosen is find:
            self._find_prompt()
        elif chosen is clear:
            self.output_box.clear()
            self._last_was_progress = False

    def _save_output(self):
        start = os.path.join(
            self._settings_dir() or "",
            (self._title or os.path.splitext(os.path.basename(
                self._settings_path or "hidden_run"))[0]) + "_output.txt")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save output", start, "Text files (*.txt);;All files (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", errors="replace") as fh:
                fh.write(self.output_box.toPlainText())
        except Exception as e:
            self._append_output(f"Could not save the output: {e}\n", True)

    def _find_prompt(self):
        text, ok = QInputDialog.getText(self, "Find in output", "Find:",
                                        text=self._find_text)
        if not ok or not text:
            return
        self._find_text = text
        self._find_next()

    def _find_next(self):
        """Find the next occurrence, wrapping around (F3). Silent when there is
        nothing to look for; says so once when the text is not in the box."""
        if not self._find_text:
            self._find_prompt()
            return
        if self.output_box.find(self._find_text):
            return
        cursor = self.output_box.textCursor()
        cursor.movePosition(QTextCursor.Start)
        self.output_box.setTextCursor(cursor)
        if not self.output_box.find(self._find_text):
            self._append_output("Not found: %s\n" % self._find_text, True)

    # An .ini can be dropped straight onto the window (like the main window).
    def dragEnterEvent(self, event):
        if self._running:
            return
        for url in event.mimeData().urls():
            if url.isLocalFile() and url.toLocalFile().lower().endswith((".ini", ".txt")):
                event.acceptProposedAction()
                return

    def dropEvent(self, event):
        if self._running:
            return
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith((".ini", ".txt")) and os.path.isfile(path):
                self._settings_path = path
                self._refresh_settings_label()
                event.acceptProposedAction()
                return

    # --------------------------------------------------------------- lifecycle
    def closeEvent(self, event):
        """Kill this window's run (if any) so a closed window never leaves an orphan
        model process running - but **ask first**: closing used to end a run that may
        have been going for hours, without a word."""
        if self._running:
            name = os.path.basename(self._settings_path or "this settings file")
            elapsed = _fmt_dur(time.time() - self._started) if self._started else ""
            if QMessageBox.question(
                    self, "Windowed Run",
                    f"CWatM is still running on {name}"
                    + (f" ({elapsed} so far)" if elapsed else "") + ".\n\n"
                    "Stop it and close this window?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No) != QMessageBox.Yes:
                event.ignore()
                return
            self._stop_run()
        if self._worker is not None:
            try:
                self._worker.stop()
            except Exception:
                log.debug("hidden-run close stop failed", exc_info=True)
            self._worker = None
        self._tick.stop()
        super().closeEvent(event)      # the geometry mixin saves size/position
