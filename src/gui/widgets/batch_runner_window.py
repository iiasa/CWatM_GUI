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
import csv
import glob
import json
import time
import hashlib
import itertools
from collections import deque

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QMessageBox, QPlainTextEdit, QCheckBox, QDialogButtonBox, QMenu,
    QFileDialog, QApplication, QStyledItemDelegate, QInputDialog,
)
from PySide6.QtCore import Qt, QSettings, QTimer, QRect
from PySide6.QtGui import QIcon, QColor, QPainter, QTextCursor

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


class _ProgressDelegate(QStyledItemDelegate):
    """Paints the Progress column as a **bar**. The cell text stays ``NN%`` - it is what
    the CSV export and every read of the table use - the bar is only how it is drawn, so
    twenty rows can be taken in at a glance instead of read one by one."""

    def paint(self, painter, option, index):
        text = str(index.data() or "").strip()
        match = re.match(r"(\d+)\s*%$", text)
        if match is None:
            super().paint(painter, option, index)
            return
        pct = max(0, min(100, int(match.group(1))))
        rect = option.rect.adjusted(4, 4, -4, -4)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        groove = QColor(theme.c("surface_bg"))
        painter.setPen(QColor(theme.c("border")))
        painter.setBrush(groove)
        painter.drawRoundedRect(rect, 3, 3)
        if pct:
            fill = QRect(rect)
            fill.setWidth(max(2, int(rect.width() * pct / 100.0)))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme.c("accent")))
            painter.drawRoundedRect(fill, 3, 3)
        painter.setPen(QColor(theme.c("text")))
        painter.drawText(option.rect, Qt.AlignCenter, text)
        painter.restore()


class _ScenarioLog:
    """One scenario's run output: the tail in memory (for *Show log*) and the whole
    stream in ``<PathOut>/cwatm_out.txt``.

    Without this every scenario writes through the global ``sys.stdout`` into the
    **main window's** output box - with several running in parallel their lines
    interleave into one unreadable stream, and a failure leaves nothing to read
    afterwards. Each worker gets its own sink instead (``CWatMProcessWorker``'s
    ``output_sink``), so the batch does not touch the main box at all."""

    _MAX_LINES = 3000        # tail kept in memory
    _FLUSH_EVERY = 50        # lines between flushes (a network share hates per-line)

    def __init__(self, path, title):
        self.path = path                 # None when the scenario has no PathOut
        self.title = title
        self.lines = deque(maxlen=self._MAX_LINES)
        self.errors = deque(maxlen=40)   # stderr lines, for the failure tooltip
        self._fh = None
        self._cur = ""
        self._pending = 0
        self._broken = False             # the file could not be written - stop trying

    def sink(self):
        """The ``output_sink(text, is_error)`` callable for CWatMProcessWorker."""
        return self.append

    def append(self, text, is_error=False):
        parts = str(text).split("\n")
        for i, part in enumerate(parts):
            if "\r" in part:
                # The per-timestep progress line overwrites itself in place.
                self._cur = part.rsplit("\r", 1)[1]
            else:
                self._cur += part
            if i < len(parts) - 1:
                self._flush_line(is_error)

    def _flush_line(self, is_error):
        line = self._cur
        self._cur = ""
        if not line:
            return
        self.lines.append(line)
        if is_error:
            self.errors.append(line)
        self._write(line)

    def _write(self, line):
        if not self.path or self._broken:
            return
        try:
            if self._fh is None:
                self._fh = open(self.path, "a", encoding="utf-8", errors="replace")
                self._fh.write("\n" + "=" * 70 + "\n")
                self._fh.write(time.strftime("%Y-%m-%d %H:%M:%S") +
                               f"   batch scenario: {self.title}\n")
                self._fh.write("-" * 70 + "\n")
            self._fh.write(line + "\n")
            self._pending += 1
            if self._pending >= self._FLUSH_EVERY:
                self._fh.flush()
                self._pending = 0
        except Exception:
            log.debug("scenario log write failed: %s", self.path, exc_info=True)
            self._broken = True

    def close(self):
        if self._cur:
            self._flush_line(False)
        if self._fh is not None:
            try:
                self._fh.write("\n")
                self._fh.close()
            except Exception:
                log.debug("close: ignored", exc_info=True)
            self._fh = None

    def text(self):
        return "\n".join(self.lines)

    def error_text(self, limit=6):
        return "\n".join(list(self.errors)[-limit:])


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
        log.debug("open_batch_runner: ignored", exc_info=True)
    return win


class BatchRunnerWindow(GeometryMemoryMixin, QDialog):
    """Table of scenarios (base .ini + per-row overrides); runs up to N in parallel."""

    _FIXED = ["Scenario", "PathOut"]                    # leading columns
    _TRAILING = ["Progress", "Duration", "Status"]      # trailing columns
    #: Trailing column names a CSV import ignores (they are results, not inputs).
    _INFO_COLS = {"progress", "duration", "status", "lastdischarge"}
    #: A PathOut holding one of these has results in it already (see "skip finished").
    _RESULT_SUFFIXES = (".nc", ".tss", ".csv")

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
        self._logs = {}                     # row -> _ScenarioLog (kept after the run)
        self._log_windows = []              # open "Show log" dialogs
        self._batch_id = ""                 # id shared by one batch's ledger entries
        self._pct = {}                      # row -> last progress %, for the batch ETA
        self._last_dis = {}                 # row -> last discharge (result summary)
        self._durations = []                # seconds per finished scenario (ETA basis)
        self._batch_started = None
        # Ticks the elapsed times and the "7/20 done · ~1 h left" line while running.
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._update_times)

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
            log.debug("_set_window_icon: ignored", exc_info=True)

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
        self._progress_delegate = _ProgressDelegate(self.table)
        self._progress_delegate_col = None
        self._refresh_headers()
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        # Right-click a scenario: run just it, re-run the failed ones, open its output
        # folder, read its log, or see what it actually changes in the settings file.
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_row_menu)
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
        self.import_button = QPushButton("Import CSV")
        self.import_button.setToolTip(
            "Read scenarios from a CSV: columns Scenario, PathOut, then one column "
            "per override key (build them in Excel and paste them here)")
        self.import_button.clicked.connect(self._import_csv)
        self.export_button = QPushButton("Export CSV")
        self.export_button.setToolTip(
            "Write the scenario table to a CSV - including each row's duration, "
            "status and last discharge, so it doubles as the batch's result summary")
        self.export_button.clicked.connect(self._export_csv)
        self.compare_button = QPushButton("Compare results")
        self.compare_button.setToolTip(
            "Overlay the same result file of every finished scenario in one "
            "Timeseries plot")
        self.compare_button.clicked.connect(self._compare_results)
        edit_row.addWidget(self.add_row_button)
        edit_row.addWidget(self.dup_row_button)
        edit_row.addWidget(self.del_row_button)
        edit_row.addWidget(self.clear_button)
        edit_row.addStretch()
        edit_row.addWidget(self.import_button)
        edit_row.addWidget(self.export_button)
        edit_row.addWidget(self.compare_button)
        edit_row.addWidget(self.sweep_button)
        edit_row.addWidget(self.add_key_button)
        layout.addLayout(edit_row)

        # Run controls
        run_row = QHBoxLayout()
        run_row.setSpacing(8)
        run_row.addWidget(QLabel("Parallel runs:"))
        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, 16)
        # Half the cores (at most 4) is a safe default: a CWatM run is CPU- and
        # IO-hungry, and 16 of them will thrash most machines. _preflight warns when
        # the value is raised beyond that.
        self.parallel_spin.setValue(self._default_parallel())
        self.parallel_spin.setToolTip(
            "How many scenarios run at the same time.\n"
            f"This machine has {os.cpu_count() or '?'} logical cores - going much "
            "beyond half of them usually makes the whole batch slower.")
        run_row.addWidget(self.parallel_spin)
        self.stop_on_fail = QCheckBox("Stop on first failure")
        self.stop_on_fail.setToolTip(
            "When a scenario fails, do not start the queued ones.\n"
            "Scenarios already running are left to finish.")
        run_row.addWidget(self.stop_on_fail)
        self.skip_finished = QCheckBox("Skip finished")
        self.skip_finished.setToolTip(
            "Resume an interrupted batch: scenarios whose PathOut already holds "
            "results (.nc / .tss / .csv) are not run again.\n"
            "'Run this scenario' from the row menu always runs, whatever is there.")
        run_row.addWidget(self.skip_finished)
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

    @staticmethod
    def _default_parallel():
        return max(1, min(4, (os.cpu_count() or 2) // 2))

    def _edit_buttons(self):
        """The row/column editing buttons (disabled while a batch is running)."""
        return (self.add_row_button, self.dup_row_button, self.del_row_button,
                self.clear_button, self.sweep_button, self.add_key_button,
                self.import_button)

    def _refresh_headers(self):
        headers = self._FIXED + self._key_cols + self._TRAILING
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        # The Progress column moves when an override column is added, so the bar
        # delegate has to move with it.
        delegate = getattr(self, "_progress_delegate", None)
        if delegate is not None:
            previous = getattr(self, "_progress_delegate_col", None)
            if previous is not None and previous != self._progress_col():
                self.table.setItemDelegateForColumn(previous, None)
            self._progress_delegate_col = self._progress_col()
            self.table.setItemDelegateForColumn(self._progress_delegate_col, delegate)

    # column index helpers
    def _progress_col(self):
        return len(self._FIXED) + len(self._key_cols)

    def _duration_col(self):
        return self._progress_col() + 1

    def _status_col(self):
        return self._progress_col() + 2

    # ------------------------------------------------------------ times / ETA
    @staticmethod
    def _fmt_dur(seconds):
        """h:mm:ss (or m:ss below an hour) - a batch runs for hours, so the elapsed
        time has to be readable at a glance."""
        try:
            seconds = int(max(0, round(seconds)))
        except (TypeError, ValueError):
            return ""
        h, rest = divmod(seconds, 3600)
        m, s = divmod(rest, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def _eta_seconds(self):
        """Rough time left: the mean of the scenarios that have finished, times what is
        still to do (queued rows + the unfinished part of the running ones), divided by
        how many run at once. None until the first one finishes - guessing before that
        would be worse than saying nothing."""
        if not self._durations:
            return None
        mean = sum(self._durations) / len(self._durations)
        outstanding = float(len(self._queue))
        for row in self._active:
            outstanding += max(0.0, 1.0 - self._pct.get(row, 0) / 100.0)
        if outstanding <= 0:
            return 0
        return mean * outstanding / max(1, self.parallel_spin.value())

    def _counts(self):
        """(done, failed, not_run) over the whole table - `not_run` are the rows that
        were skipped as already finished or cancelled by stop-on-first-failure, which
        belong in neither of the other two."""
        done = failed = not_run = 0
        for row in range(self.table.rowCount()):
            status = self._cell_text(row, self._status_col())
            if status.startswith("done"):
                done += 1
            elif status.startswith(self._FAILED_STATES):
                failed += 1
            elif status.startswith(("skipped", "cancelled")):
                not_run += 1
        return done, failed, not_run

    def _update_times(self):
        """The 1 s tick: elapsed time per running scenario + the batch line."""
        now = time.time()
        for row, info in list(self._active.items()):
            self._set_cell(row, self._duration_col(),
                           self._fmt_dur(now - info["started"]), editable=False)
        self._update_batch_line()

    def _update_batch_line(self):
        total = self.table.rowCount()
        done, failed, not_run = self._counts()
        if not self._running:
            return
        parts = [f"{done + failed + not_run}/{total} finished"]
        if failed:
            parts.append(f"{failed} failed")
        if not_run:
            parts.append(f"{not_run} skipped")
        if self._active:
            parts.append(f"{len(self._active)} running")
        if self._queue:
            parts.append(f"{len(self._queue)} queued")
        eta = self._eta_seconds()
        if eta:
            parts.append(f"~{self._fmt_dur(eta)} left")
        self.sub_label.setText(" · ".join(parts))

    def _finish_batch_line(self):
        """The summary that stays on screen when the batch is over."""
        done, failed, not_run = self._counts()
        elapsed = (self._fmt_dur(time.time() - self._batch_started)
                   if self._batch_started else "")
        text = f"Batch finished: {done} done"
        if failed:
            text += f", {failed} failed"
        if not_run:
            text += f", {not_run} skipped"
        if elapsed:
            text += f" in {elapsed}"
        self.sub_label.setText(text)
        try:    # flash the taskbar entry - a batch is long enough to walk away from
            QApplication.alert(self, 0)
        except Exception:
            log.debug("_finish_batch_line: ignored", exc_info=True)

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
            # NB: a plain (non-f) string must close the rule with ONE brace - the
            # doubled one is only an escape *inside* an f-string. With "}}" here Qt
            # failed to parse the whole sheet ("Could not parse stylesheet") and the
            # table stayed unthemed.
            "font-family: 'Segoe UI', sans-serif; font-size: 12px; }"
            f"QHeaderView::section {{ background-color: {theme.c('menubar_bg')}; "
            f"color: {theme.c('text')}; border: 0px; "
            f"border-bottom: 1px solid {theme.c('border')}; padding: 4px 8px; "
            "font-weight: 600; }")

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
    def _set_cell(self, row, col, text, editable=True, tooltip=None):
        item = QTableWidgetItem(str(text))
        if not editable:
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        if tooltip:
            item.setToolTip(tooltip)
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
        self._set_cell(row, self._duration_col(), "", editable=False)
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

    def _safe_name(self, row):
        name = self._cell_text(row, 0) or f"scenario_{row + 1}"
        return re.sub(r"[^\w\-.]+", "_", name).strip("_") or f"scenario_{row + 1}"

    def _temp_glob(self, row):
        """Every temp .ini this **row** has ever written (the name part may have
        changed since), so an old one cannot be left behind after a rename."""
        base = os.path.splitext(os.path.basename(self._base_path))[0]
        return glob.glob(os.path.join(
            self._base_dir, f"{base}.batch{row + 1:03d}_*.ini"))

    def _write_scenario_ini(self, row, content):
        """Write this row's settings file. The name carries the **row number**, so two
        scenarios that sanitise to the same name (``run 1`` / ``run_1``) cannot end up
        writing - and deleting - the same file while both are running."""
        base = os.path.splitext(os.path.basename(self._base_path))[0]
        path = os.path.join(
            self._base_dir, f"{base}.batch{row + 1:03d}_{self._safe_name(row)}.ini")
        for old in self._temp_glob(row):        # a rename left an older one behind
            if os.path.normcase(old) != os.path.normcase(path):
                try:
                    os.remove(old)
                except Exception:
                    log.debug("_write_scenario_ini: ignored", exc_info=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    @staticmethod
    def _drop_temp(path):
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except Exception:
            log.debug("could not remove temp ini: %s", path, exc_info=True)

    # ------------------------------------------------------------- pre-flight
    def _base_keys(self):
        """The keys the base settings file actually defines (lower-cased)."""
        keys = set()
        for line in self._base_content.split("\n"):
            s = line.strip()
            if not s or s[0] in "#;[" or "=" not in s:
                continue
            keys.add(s.split("=", 1)[0].strip().lower())
        return keys

    def _resolved_pathout(self, content, fallback=""):
        """This scenario's PathOut with placeholders expanded (best effort)."""
        try:
            from src.gui.widgets.basin_viewer import pathout_exists
            _exists, resolved = pathout_exists(content)
            if resolved:
                return resolved
        except Exception:
            log.debug("PathOut resolution failed", exc_info=True)
        return fallback

    @staticmethod
    def _writable_dir(path):
        """Can this directory be created/written? Walks up to the nearest existing
        ancestor - the folder itself usually does not exist yet."""
        probe = os.path.abspath(path)
        while probe and not os.path.isdir(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                return False
            probe = parent
        return os.access(probe, os.W_OK)

    def _preflight(self, rows):
        """Check the scenarios **before** anything runs; True = go ahead.

        A batch is expensive, and its worst failures are silent: two rows sharing a
        PathOut quietly mix their results, a row without one writes into the base
        PathOut together with everybody else, and an override key that is not in the
        base file is simply *appended* as a new key - a typo then runs the unchanged
        scenario to completion. All of that is cheap to catch here."""
        errors, warnings = [], []
        seen_names, seen_out = {}, {}
        cores = os.cpu_count() or 2
        parallel = self.parallel_spin.value()
        if parallel > max(1, cores // 2) and len(rows) > 1:
            warnings.append(
                f"{parallel} scenarios in parallel on {cores} logical cores - CWatM is "
                f"CPU- and disk-hungry, so beyond about {max(1, cores // 2)} the whole "
                f"batch usually gets slower, not faster")
        base_keys = self._base_keys()
        unknown = [k for k in self._key_cols if k.lower() not in base_keys]
        for key in unknown:
            warnings.append(
                f"key '{key}' is not in the base settings file - it will be added as a "
                f"new key at the end (a typo would run the base value unchanged)")
        for row in rows:
            label = f"row {row + 1} ({self._cell_text(row, 0) or 'unnamed'})"
            name = self._safe_name(row).lower()
            if name in seen_names:
                warnings.append(f"{label}: same scenario name as row {seen_names[name]}"
                                f" - both appear alike in the Run Ledger")
            else:
                seen_names[name] = row + 1
            pathout = self._cell_text(row, 1)
            if not pathout:
                errors.append(f"{label}: no PathOut - it would write into the base "
                              f"PathOut, together with every other scenario")
                continue
            try:
                content = self._scenario_content(row)
            except Exception as e:
                errors.append(f"{label}: cannot build the settings file ({e})")
                continue
            resolved = self._resolved_pathout(content, pathout)
            key = os.path.normcase(os.path.abspath(resolved))
            if key in seen_out:
                errors.append(f"{label}: same PathOut as row {seen_out[key]} "
                              f"- the two runs would overwrite each other's results")
            else:
                seen_out[key] = row + 1
            if not self._writable_dir(resolved):
                errors.append(f"{label}: PathOut cannot be created or written: {resolved}")
            elif os.path.isdir(resolved) and os.listdir(resolved):
                warnings.append(f"{label}: PathOut is not empty - existing results "
                                f"there will be mixed with the new ones ({resolved})")
        return self._confirm_problems(errors, warnings)

    def _confirm_problems(self, errors, warnings):
        """Show what the pre-flight found. Errors block the batch; warnings ask."""
        def block(title, items):
            shown = items[:20]
            more = len(items) - len(shown)
            text = "\n".join(f"• {m}" for m in shown)
            if more > 0:
                text += f"\n• … and {more} more"
            return f"{title}\n\n{text}"

        if errors:
            QMessageBox.critical(
                self, "Batch Run",
                block(f"{len(errors)} problem(s) would spoil this batch:", errors) +
                "\n\nNothing was started.")
            return False
        if warnings:
            return QMessageBox.question(
                self, "Batch Run",
                block(f"{len(warnings)} thing(s) worth a look:", warnings) +
                "\n\nRun anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes
        return True

    def _run_all(self):
        if self._running or self.table.rowCount() == 0:
            return
        rows = list(range(self.table.rowCount()))
        if not self._preflight(rows):
            return
        self._run_rows(rows)

    def _run_rows(self, rows, force=False):
        """Queue these rows and start pumping (used by Run all, by the row menu's
        *Run this scenario* and by *Re-run failed*).

        ``force`` skips the "Skip finished" filter - asking for **this** scenario
        explicitly means it should run whatever is already in its PathOut."""
        rows = [r for r in rows if r not in self._active and r not in self._queue]
        if not force and self.skip_finished.isChecked():
            keep = []
            for row in rows:
                if self._has_results(self._row_pathout(row)):
                    self._set_cell(row, self._status_col(), "skipped (has results)",
                                   editable=False,
                                   tooltip="'Skip finished' is ticked and this "
                                           "PathOut already holds output files.")
                else:
                    keep.append(row)
            rows = keep                  # the count shows up in the batch line
        if not rows:
            return
        self._queue.extend(rows)
        if not self._running:
            self._running = True
            self._batch_started = time.time()
            # One id for this batch, carried into every scenario's journal entry so
            # the Journal of Runs can fold them into a single row.
            self._batch_id = "%s-%d" % (
                time.strftime("%Y%m%d_%H%M%S"), int(time.time() * 1000) % 1000)
            self._durations = []
            self.run_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            for b in self._edit_buttons():
                b.setEnabled(False)
            self._tick.start()
        for row in rows:
            self._pct[row] = 0
            self._set_cell(row, self._progress_col(), "0%", editable=False)
            self._set_cell(row, self._duration_col(), "", editable=False)
            self._set_cell(row, self._status_col(), "queued", editable=False)
        self._pump()

    def _pump(self):
        """Start queued scenarios until N are running; finish the batch when idle."""
        limit = self.parallel_spin.value()
        while self._queue and len(self._active) < limit:
            row = self._queue.pop(0)
            self._start_row(row)
        if not self._queue and not self._active and self._running:
            self._tick.stop()
            self._finish_batch_line()
            self._running = False
            self.run_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            for b in self._edit_buttons():
                b.setEnabled(True)
        else:
            self._update_batch_line()

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
        resolved = self._resolved_pathout(content, self._cell_text(row, 1))
        if resolved:
            try:
                os.makedirs(resolved, exist_ok=True)
            except Exception as e:
                self._set_cell(row, self._status_col(),
                               f"error: cannot create PathOut ({e})", editable=False)
                self._drop_temp(temp)
                return
        # This scenario's own log: <PathOut>/cwatm_out.txt plus the tail in memory.
        # Without the sink the output would go to the *main* window's box, where
        # parallel scenarios interleave into one unreadable stream.
        scenario_log = _ScenarioLog(
            os.path.join(resolved, "cwatm_out.txt") if resolved else None,
            self._cell_text(row, 0) or f"scenario_{row + 1}")
        self._logs[row] = scenario_log
        # Run from the base settings file's folder (where the scenario .ini is
        # written too), so relative paths resolve against it - not against the main
        # window's working dir, and not against the exe/source root.
        worker = CWatMProcessWorker(temp, self._mw,
                                    output_sink=scenario_log.sink(),
                                    working_dir=self._base_dir or None)
        self._active[row] = dict(worker=worker, temp=temp, started=time.time(),
                                 pathout=resolved, name=self._cell_text(row, 0),
                                 content=content, log=scenario_log.path)
        worker.progress.connect(lambda p, r=row: self._on_progress(r, p))
        worker.finished.connect(lambda ok, dis, r=row: self._on_finished(r, ok, dis))
        worker.error.connect(lambda msg, r=row: self._on_error(r, msg))
        self._set_cell(row, self._status_col(), "running", editable=False)
        worker.start()

    def _on_progress(self, row, pct):
        self._pct[row] = int(pct)
        self._set_cell(row, self._progress_col(), f"{int(pct)}%", editable=False)

    def _freeze_duration(self, row, info):
        """Stop the clock for this row and feed the batch ETA."""
        if not info or not info.get("started"):
            return
        seconds = time.time() - info["started"]
        self._durations.append(seconds)
        self._set_cell(row, self._duration_col(), self._fmt_dur(seconds),
                       editable=False)

    def _cancel_queued(self, reason="cancelled"):
        """Stop-on-first-failure: do not start what has not started yet. Scenarios
        already running are left alone - killing them would throw away hours."""
        for row in self._queue:
            self._set_cell(row, self._status_col(), reason, editable=False,
                           tooltip="A scenario failed and 'Stop on first failure' "
                                   "was ticked.")
        self._queue = []

    def _close_log(self, row):
        scenario_log = self._logs.get(row)
        if scenario_log is not None:
            scenario_log.close()
        return scenario_log

    def _failure_tooltip(self, row, extra=""):
        """What actually went wrong: the run's own error lines (the status cell can
        only ever show a fragment) plus where the full log is."""
        scenario_log = self._logs.get(row)
        parts = [extra] if extra else []
        if scenario_log is not None:
            err = scenario_log.error_text()
            if err:
                parts.append(err)
            if scenario_log.path:
                parts.append(f"Full log: {scenario_log.path}")
        parts.append("Right-click the row for 'Show log'.")
        return "\n".join(p for p in parts if p)

    def _on_finished(self, row, ok, last_dis):
        info = self._active.pop(row, None)
        scenario_log = self._close_log(row)
        if info is not None:
            self._log_scenario(info, ok, last_dis)
            self._freeze_duration(row, info)
            self._set_cell(row, self._progress_col(), "100%" if ok else
                           self._cell_text(row, self._progress_col()), editable=False)
            if ok:
                dis = ""
                try:
                    dis = f" ({display_format.fmt(last_dis)})" if last_dis is not None else ""
                    self._last_dis[row] = float(last_dis)
                except (TypeError, ValueError):
                    dis = ""
                tip = (f"Log: {scenario_log.path}"
                       if scenario_log is not None and scenario_log.path else "")
                self._set_cell(row, self._status_col(), f"done{dis}",
                               editable=False, tooltip=tip)
                # The temp .ini has done its job (it is rebuilt from the table on every
                # run, so nothing is lost); a failed one is kept for inspection.
                self._drop_temp(info["temp"])
            else:
                self._set_cell(row, self._status_col(), "failed", editable=False,
                               tooltip=self._failure_tooltip(row))
                if self.stop_on_fail.isChecked():
                    self._cancel_queued()
        self._pump()

    def _on_error(self, row, msg):
        info = self._active.pop(row, None)
        self._close_log(row)
        if info is not None:
            self._log_scenario(info, False, None)
            self._freeze_duration(row, info)
            self._set_cell(row, self._status_col(), f"error: {msg[:60]}",
                           editable=False, tooltip=self._failure_tooltip(row, msg))
            if self.stop_on_fail.isChecked():
                self._cancel_queued()
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
                content=info.get("content"),
                log_path=info.get("log"), batch_id=self._batch_id))
        except Exception:
            log.debug("batch ledger logging failed", exc_info=True)

    def _stop_all(self):
        self._queue = []
        for row, info in list(self._active.items()):
            try:
                info["worker"].stop()
            except Exception:
                log.debug("_stop_all: ignored", exc_info=True)
            self._close_log(row)
            # A stopped scenario is part of the history too, and its temp .ini has no
            # reason to survive (both used to be dropped silently).
            self._log_scenario(info, False, None)
            self._freeze_duration(row, info)
            self._drop_temp(info.get("temp"))
            self._set_cell(row, self._status_col(), "stopped", editable=False)
        self._active.clear()
        self._tick.stop()
        if self._running:
            self._finish_batch_line()
        self._running = False
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        for b in self._edit_buttons():
            b.setEnabled(True)

    # ------------------------------------------------------------------- CSV
    def _export_csv(self):
        """Write the table to a CSV — the scenarios **and** their outcome, so the same
        file is both a reproducible batch definition and its result summary."""
        start = os.path.join(
            self._base_dir,
            os.path.splitext(os.path.basename(self._base_path))[0] + "_scenarios.csv")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export scenarios", start, "CSV files (*.csv);;All files (*)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh)
                writer.writerow(["Scenario", "PathOut"] + list(self._key_cols)
                                + ["Duration", "Status", "LastDischarge"])
                for row in range(self.table.rowCount()):
                    dis = self._last_dis.get(row)
                    writer.writerow(
                        [self._cell_text(row, 0), self._cell_text(row, 1)]
                        + [self._cell_text(row, 2 + i)
                           for i in range(len(self._key_cols))]
                        + [self._cell_text(row, self._duration_col()),
                           self._cell_text(row, self._status_col()),
                           "" if dis is None else repr(dis)])
        except Exception as e:
            QMessageBox.warning(self, "Export scenarios", f"Could not write:\n{e}")
            return
        self.sub_label.setText(f"Exported {self.table.rowCount()} scenarios → {path}")

    def _row_pathout(self, row):
        """This row's PathOut, placeholders expanded (best effort, never raises)."""
        try:
            return self._resolved_pathout(self._scenario_content(row),
                                          self._cell_text(row, 1))
        except Exception:
            return self._cell_text(row, 1)

    def _has_results(self, path):
        """Does this PathOut already hold model output? (The scenario's own
        ``cwatm_out.txt`` is a .txt, so the log alone never counts as a result.)"""
        if not path or not os.path.isdir(path):
            return False
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if entry.is_file() and entry.name.lower().endswith(
                            self._RESULT_SUFFIXES):
                        return True
        except OSError:
            return False
        return False

    def _compare_results(self):
        """Overlay one result file of every scenario that has output in a single
        Timeseries plot - the reason a sweep is run in the first place."""
        found = {}                       # csv name -> [(scenario, full path)]
        for row in range(self.table.rowCount()):
            out = self._row_pathout(row)
            if not out or not os.path.isdir(out):
                continue
            name = self._cell_text(row, 0) or f"scenario_{row + 1}"
            try:
                with os.scandir(out) as it:
                    for entry in it:
                        if entry.is_file() and entry.name.lower().endswith(".csv"):
                            found.setdefault(entry.name, []).append(
                                (name, entry.path))
            except OSError:
                continue
        usable = {n: v for n, v in found.items() if len(v) > 1}
        if not usable:
            QMessageBox.information(
                self, "Compare results",
                "No result .csv was found in two or more scenario output folders yet.\n\n"
                "Run the batch first - and note that only time series (.csv) can be "
                "overlaid, not maps (.nc).")
            return
        if len(usable) == 1:
            chosen = next(iter(usable))
        else:
            names = sorted(usable, key=lambda n: (-len(usable[n]), n.lower()))
            chosen, ok = QInputDialog.getItem(
                self, "Compare results",
                "Which result file should be compared across the scenarios?",
                [f"{n}   ({len(usable[n])} scenarios)" for n in names], 0, False)
            if not ok or not chosen:
                return
            chosen = chosen.split("   (")[0]
        entries = usable[chosen]
        try:
            from src.gui.widgets.analysis_timeseries import open_comparison
            open_comparison(self._mw or self, [p for _n, p in entries],
                            [n for n, _p in entries])
        except Exception as e:
            log.debug("compare results failed", exc_info=True)
            QMessageBox.warning(self, "Compare results",
                                f"Could not open the comparison:\n{e}")

    def _import_csv(self):
        """Read scenarios from a CSV (the columns Export writes, or one made in Excel).
        Every column that is not Scenario/PathOut and not a result column becomes an
        override key."""
        if self._running:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import scenarios", self._base_dir,
            "CSV files (*.csv);;All files (*)")
        if not path:
            return
        try:
            with open(path, newline="", encoding="utf-8-sig") as fh:
                rows = [r for r in csv.reader(fh) if any(c.strip() for c in r)]
        except Exception as e:
            QMessageBox.warning(self, "Import scenarios", f"Could not read:\n{e}")
            return
        if len(rows) < 2:
            QMessageBox.warning(
                self, "Import scenarios",
                "The file needs a header row (Scenario, PathOut, <keys>…) and at "
                "least one scenario.")
            return
        header = [h.strip() for h in rows[0]]
        lower = [h.lower() for h in header]
        try:
            name_i = lower.index("scenario")
            out_i = lower.index("pathout")
        except ValueError:
            QMessageBox.warning(
                self, "Import scenarios",
                "The header must contain a 'Scenario' and a 'PathOut' column.\n\n"
                f"Found: {', '.join(header) or '(nothing)'}")
            return
        keys = [(i, h) for i, h in enumerate(header)
                if i not in (name_i, out_i) and h and h.lower() not in self._INFO_COLS]
        self.table.setRowCount(0)
        self._key_cols = [h for _i, h in keys]
        self._refresh_headers()
        for raw in rows[1:]:
            cell = lambda i: raw[i].strip() if i < len(raw) else ""   # noqa: E731
            self._add_row(name=cell(name_i), pathout=cell(out_i),
                          overrides={h: cell(i) for i, h in keys})
        self.sub_label.setText(
            f"Imported {self.table.rowCount()} scenarios from {os.path.basename(path)}"
            + (f" · override keys: {', '.join(self._key_cols)}" if self._key_cols else ""))

    # -------------------------------------------------------------- row menu
    _FAILED_STATES = ("failed", "error", "stopped")

    def _failed_rows(self):
        return [r for r in range(self.table.rowCount())
                if self._cell_text(r, self._status_col()).startswith(self._FAILED_STATES)]

    def _on_row_menu(self, pos):
        """Right-click on a scenario: everything that applies to **that one** row."""
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        self.table.selectRow(row)
        name = self._cell_text(row, 0) or f"scenario_{row + 1}"
        menu = QMenu(self)
        menu.setToolTipsVisible(True)

        run_one = menu.addAction(f"Run '{name}'")
        run_one.setToolTip("Run this scenario alone - or add it to a batch already running")
        run_one.setEnabled(row not in self._active and row not in self._queue)
        failed = self._failed_rows()
        rerun = menu.addAction(f"Re-run failed ({len(failed)})")
        rerun.setToolTip("Run every scenario that failed, errored or was stopped")
        rerun.setEnabled(bool(failed))
        menu.addSeparator()

        scenario_log = self._logs.get(row)
        show_log = menu.addAction("Show log")
        show_log.setEnabled(scenario_log is not None and bool(scenario_log.lines))
        show_log.setToolTip("This scenario's run output"
                            if scenario_log is not None else "It has not run yet")
        open_out = menu.addAction("Open output folder")
        show_ini = menu.addAction("Show settings (diff vs base)")
        show_ini.setToolTip("What this scenario changes in the base settings file")

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is run_one:
            self._run_single(row)
        elif chosen is rerun:
            self._rerun_failed()
        elif chosen is show_log:
            self._show_log(row)
        elif chosen is open_out:
            self._open_pathout(row)
        elif chosen is show_ini:
            self._show_scenario_settings(row)

    def _run_single(self, row):
        if self._preflight([row]):
            self._run_rows([row], force=True)

    def _rerun_failed(self):
        rows = self._failed_rows()
        if rows and self._preflight(rows):
            self._run_rows(rows)

    def _open_pathout(self, row):
        try:
            resolved = self._resolved_pathout(self._scenario_content(row),
                                              self._cell_text(row, 1))
        except Exception:
            resolved = self._cell_text(row, 1)
        if not resolved or not os.path.isdir(resolved):
            QMessageBox.information(
                self, "Open output folder",
                f"This scenario has no output folder (yet):\n{resolved or '-'}")
            return
        from src.gui.utils.open_path import open_path
        if not open_path(resolved):
            QMessageBox.warning(self, "Open output folder",
                                f"Could not open:\n{resolved}")

    def _show_log(self, row):
        """The scenario's output in a plain, non-modal window (the log file itself may
        be on a slow share, and a finished run's tail is already in memory)."""
        scenario_log = self._logs.get(row)
        if scenario_log is None:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Log — {self._cell_text(row, 0) or 'scenario'}")
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.resize(820, 520)
        v = QVBoxLayout(dlg)
        head = QLabel(scenario_log.path or "(no PathOut - kept in memory only)")
        head.setStyleSheet(f"color: {theme.c('text_muted')}; font-size: 11px;")
        head.setWordWrap(True)
        v.addWidget(head)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {theme.c('out_bg')}; "
            f"color: {theme.c('out_text')}; border: 1px solid {theme.c('out_border')}; "
            "font-family: Consolas, monospace; font-size: 11px; }")
        view.setPlainText(scenario_log.text())
        view.moveCursor(QTextCursor.MoveOperation.End)
        v.addWidget(view, 1)
        row_box = QHBoxLayout()
        row_box.addStretch()
        if scenario_log.path and os.path.isfile(scenario_log.path):
            open_btn = QPushButton("Open log file")
            open_btn.setStyleSheet(self._button_style())
            open_btn.clicked.connect(
                lambda: __import__("src.gui.utils.open_path", fromlist=["open_path"])
                .open_path(scenario_log.path))
            row_box.addWidget(open_btn)
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(self._button_style())
        close_btn.clicked.connect(dlg.close)
        row_box.addWidget(close_btn)
        v.addLayout(row_box)
        dlg.setStyleSheet(f"QDialog {{ background-color: {theme.c('window_bg')}; }}")
        self._log_windows.append(dlg)
        dlg.destroyed.connect(
            lambda *_: self._log_windows.remove(dlg) if dlg in self._log_windows else None)
        dlg.show()

    def _show_scenario_settings(self, row):
        """The scenario's settings file next to the base one, in the Compare window -
        so what a row really changes is visible before (or after) it runs."""
        try:
            content = self._scenario_content(row)
        except Exception as e:
            QMessageBox.warning(self, "Show settings",
                                f"Could not build this scenario:\n{e}")
            return
        try:
            from src.gui.widgets.compare_settings_window import CompareSettingsWindow
            win = CompareSettingsWindow(self._mw or self)
            win.load_contents(
                self._base_content, os.path.basename(self._base_path) or "base",
                content, f"{self._cell_text(row, 0) or 'scenario'} (generated)")
            win.show()
            win.raise_()
            win.activateWindow()
        except Exception as e:
            log.debug("compare of scenario failed", exc_info=True)
            QMessageBox.warning(self, "Show settings",
                                f"Could not open the comparison:\n{e}")

    def _clear_all(self):
        """Clear all scenarios and override columns and start fresh (one empty row)."""
        if self._running:
            return
        self.table.setRowCount(0)
        self._key_cols = []
        self._refresh_headers()
        self.parallel_spin.setValue(self._default_parallel())
        self._add_row()

    # -------------------------------------------------------------- persistence
    def _cfg_key(self):
        """The QSettings key for **this base settings file**.

        One global key meant that opening another project showed the previous
        project's scenarios - with its PathOuts, ready to run. The path is hashed so
        the key stays short and legal."""
        try:
            ident = os.path.normcase(os.path.abspath(self._base_path))
        except Exception:
            ident = self._base_path or ""
        digest = hashlib.md5(ident.encode("utf-8", "replace")).hexdigest()[:12]
        return f"batch_runner/config_{digest}"

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
                   "stop_on_fail": self.stop_on_fail.isChecked(),
                   "skip_finished": self.skip_finished.isChecked(),
                   "base": self._base_path,
                   "rows": rows}
            QSettings("IIASA", "CWatM_GUI").setValue(
                self._cfg_key(), json.dumps(cfg))
        except Exception:
            log.debug("batch config save failed", exc_info=True)

    def _restore_config(self):
        """Restore the scenario table from the last session; return True if anything was
        restored, else False (so the caller adds a default row)."""
        try:
            settings = QSettings("IIASA", "CWatM_GUI")
            raw = settings.value(self._cfg_key(), "")
            if not raw:
                # Table saved before the per-file keys existed: adopt it once, for the
                # file that is open now, then let it be saved under the new key.
                legacy = settings.value("batch_runner/config", "")
                if legacy:
                    raw = legacy
                    settings.remove("batch_runner/config")
            if not raw:
                return False
            cfg = json.loads(raw)
            rows = cfg.get("rows") or []
            if not rows:
                return False
            self._key_cols = list(cfg.get("keys") or [])
            self._refresh_headers()
            self.parallel_spin.setValue(
                int(cfg.get("parallel", self._default_parallel())))
            self.stop_on_fail.setChecked(bool(cfg.get("stop_on_fail", False)))
            self.skip_finished.setChecked(bool(cfg.get("skip_finished", False)))
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
        for scenario_log in self._logs.values():
            scenario_log.close()
        self._save_config()
        super().closeEvent(event)
