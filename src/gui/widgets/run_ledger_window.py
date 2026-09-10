"""
Journal of Runs window (RUN CWATM ▸ Journal of Runs) for the CWatM GUI.

(The feature used to be called the *Run Ledger* and lived in the Tools menu; the
storage module is still ``src/gui/utils/run_ledger.py`` and the on-disk file is still
``run_ledger.json`` - only the name shown to the user changed.)

A table of past model runs recorded by ``src/gui/utils/run_ledger.py`` (one row per
completed run: time, Title, settings file, PathOut, duration, success, last
discharge). Each row is actionable through a menu bar - File (Open results / Load
settings / Refresh / Export CSV), Action (Show log / Re-run / Compare settings /
Compare results - the four selection-dependent ones, enabled only when the marked
rows make them meaningful) and Clean (Delete entry / Clear Journal); Close is the
one button left (see ``_build_ui`` / ``_build_menubar``). The same actions are also
on the table's right-click menu.

Non-modal; themed at construction like the other secondary windows; geometry key
``run_ledger``.
"""

import csv
import os
import time

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox,
    QLineEdit, QCheckBox, QPlainTextEdit, QInputDialog, QMenu, QMenuBar, QFileDialog,
    QApplication,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QBrush, QColor, QTextCursor


class _SortItem(QTableWidgetItem):
    """A cell that sorts by a **key** instead of its text - so `2m 05s` sorts after
    `45s`, `12.5` numerically, and the timestamp by its real value."""

    def __init__(self, text, key=None):
        super().__init__(str(text))
        self.sort_key = text if key is None else key

    def __lt__(self, other):
        mine = getattr(self, "sort_key", self.text())
        theirs = getattr(other, "sort_key", other.text())
        try:
            return mine < theirs
        except TypeError:
            return str(mine) < str(theirs)

from src.gui.utils.window_geometry import GeometryMemoryMixin, scaled_default_size
from src.gui.utils import theme
from src.gui.utils import run_ledger
from src.gui.utils import display_format
from src.gui.utils.gui_log import get_logger

log = get_logger("run_ledger_window")


def open_run_ledger(parent=None):
    """Open the Journal of Runs window (kept alive on the parent so it is not GC'd)."""
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
        log.debug("open_run_ledger: ignored", exc_info=True)
    return win


class RunLedgerWindow(GeometryMemoryMixin, QDialog):
    """Table of past runs; open each run's results or reload its settings."""

    _COLS = ["When", "Title", "PathOut", "Duration", "OK", "Last dis", "Settings",
             "Note"]
    _NOTE_COL = 7

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("\U0001F4D2 Journal of Runs")
        self.setModal(False)
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        if not self._init_geometry_memory("run_ledger"):
            self.resize(*scaled_default_size(self, 940, 520))
        self._set_window_icon()
        self._entries = []          # what the table currently shows (row -> entry)
        self._all = []              # every stored entry, newest first
        self._filling = False       # True while _reload fills the table
        # Live rows (runs in progress) are refreshed on a timer while the window is
        # open, so a run finishing shows up without pressing Refresh.
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(2000)
        self._live_timer.timeout.connect(self._reload)
        self._build_ui()
        self._apply_theme()
        self._reload()
        self._live_timer.start()

    def _set_window_icon(self):
        try:
            base = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(__file__))))
            icon_path = os.path.join(base, "assets", "cwatm.ico")
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            log.debug("_set_window_icon: ignored", exc_info=True)

    # --------------------------------------------------------------------- UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self._build_menubar(layout)

        self.header_label = QLabel("Journal of Runs")
        self.header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.header_label)

        self.sub_label = QLabel("")
        self.sub_label.setAlignment(Qt.AlignCenter)
        self.sub_label.setWordWrap(True)
        layout.addWidget(self.sub_label)

        # Filter + grouping: with a 60-day history and a batch writing one row per
        # scenario, scrolling is not a way to find a run.
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText(
            "Filter — Title, PathOut, settings file, kind (batch/hidden), date …")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.group_check = QCheckBox("Group batches")
        self.group_check.setToolTip(
            "Show the scenarios of one Batch Run as a single row\n"
            "(untick to list every scenario)")
        self.group_check.setChecked(True)
        self.group_check.toggled.connect(self._reload)
        filter_row.addWidget(self.filter_edit, 1)
        filter_row.addWidget(self.group_check)
        layout.addLayout(filter_row)

        self.table = QTableWidget(0, len(self._COLS))
        self.table.setHorizontalHeaderLabels(self._COLS)
        self.table.verticalHeader().setVisible(False)
        # Only the Note column is editable (the per-item flags decide; the view has to
        # allow editing at all for that to work).
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked
                                   | QAbstractItemView.EditKeyPressed)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_row_menu)
        # Extended selection so two rows can be marked (Ctrl/Shift+click) for Compare.
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)      # click a header to sort
        self.table.doubleClicked.connect(lambda *_: self._open_results())
        self.table.itemSelectionChanged.connect(self._update_compare_enabled)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)   # PathOut
        hh.setSectionResizeMode(6, QHeaderView.Stretch)   # Settings
        layout.addWidget(self.table, 1)

        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()
        btn_row.addWidget(self.close_button)
        layout.addLayout(btn_row)

    def _build_menubar(self, layout):
        """File (Open results / Load settings / Refresh / Export CSV), Action (Show
        log / Re-run / Compare settings / Compare results) and Clean (Delete entry /
        Clear Journal) - the row of per-run buttons became menus; Close stays a
        button (see _build_ui)."""
        mbar = QMenuBar(self)
        mbar.setStyleSheet(
            f"QMenuBar {{ background-color: {theme.c('menubar_bg')}; "
            f"color: {theme.c('text')}; }}"
            f"QMenuBar::item:selected {{ background-color: {theme.c('menu_sel_bg')}; }}")

        file_menu = mbar.addMenu("File")
        self.open_action = file_menu.addAction("Open results", self._open_results)
        self.open_action.setToolTip("Open this run's PathOut in the Output Explorer")
        self.load_action = file_menu.addAction("Load settings", self._load_settings)
        self.load_action.setToolTip(
            "Reload this run's settings file into the main window")
        self.refresh_action = file_menu.addAction("Refresh", self._reload)
        self.export_action = file_menu.addAction("Export CSV", self._export_csv)
        self.export_action.setToolTip(
            "Write the rows shown (the filter applies) to a CSV file")

        action_menu = mbar.addMenu("Action")
        self.log_action = action_menu.addAction("Show log", self._show_log)
        self.log_action.setToolTip(
            "The run's output log - the journal records that a run failed, this "
            "says why")
        self.log_action.setEnabled(False)
        self.rerun_action = action_menu.addAction("Re-run", self._rerun)
        self.rerun_action.setToolTip(
            "Run this run's settings again in a Windowed Run window")
        self.rerun_action.setEnabled(False)
        self.compare_action = action_menu.addAction(
            "Compare settings", self._compare_settings)
        self.compare_action.setToolTip(
            "Mark two runs (Ctrl/Shift+click) to diff their settings files")
        self.compare_action.setEnabled(False)
        self.compare_results_action = action_menu.addAction(
            "Compare results", self._compare_results)
        self.compare_results_action.setToolTip(
            "Mark two or more runs to overlay the same result file in one "
            "Timeseries plot")
        self.compare_results_action.setEnabled(False)

        clean_menu = mbar.addMenu("Clean")
        self.delete_action = clean_menu.addAction("Delete entry", self._delete_selected)
        self.delete_action.setToolTip("Remove the marked runs from the journal")
        self.delete_action.setEnabled(False)
        self.clear_action = clean_menu.addAction("Clear Journal", self._clear)
        self.clear_action.setToolTip("Delete all recorded runs")

        self._menus = [file_menu, action_menu, clean_menu]  # GC guard
        layout.setMenuBar(mbar)

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
            # NOTE: these two closers are in *plain* strings - a doubled `}}` is only
            # an escape inside an f-string; written here it made Qt drop the whole
            # sheet ("Could not parse stylesheet"), so the table stayed unthemed.
            "font-family: 'Segoe UI', sans-serif; font-size: 12px; }"
            f"QHeaderView::section {{ background-color: {theme.c('menubar_bg')}; "
            f"color: {theme.c('text')}; border: 0px; "
            f"border-bottom: 1px solid {theme.c('border')}; padding: 4px 8px; "
            "font-weight: 600; }")
        self.close_button.setStyleSheet(self._button_style())
        self.filter_edit.setStyleSheet(
            f"QLineEdit {{ background-color: {theme.c('field_bg')}; "
            f"color: {theme.c('field_text')}; border: 1px solid "
            f"{theme.c('field_border')}; border-radius: 5px; padding: 4px 8px; "
            "font-size: 12px; }")
        self.group_check.setStyleSheet(f"color: {theme.c('text')}; font-size: 12px;")

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

    # ------------------------------------------------------------- live runs
    def _live_entries(self):
        """Pseudo-entries for what is running **right now** - the main run, every
        Hidden Run window and every scenario of a Batch Run. The journal is otherwise
        purely retrospective, so there was no single place showing the current state."""
        live = []
        mw = self.parent()
        if mw is None:
            return live
        now = time.time()
        try:
            if getattr(mw, "cwatm_running", False):
                ctx = getattr(mw, "_run_ledger_ctx", None) or {}
                live.append({
                    "ts": ctx.get("started_at") or now, "live": True,
                    "kind": "run", "title": ctx.get("title", "") or "(main run)",
                    "pathout": ctx.get("pathout", ""),
                    "settings": ctx.get("settings", ""),
                    "duration_s": now - (ctx.get("started_at") or now),
                })
        except Exception:
            log.debug("live main run failed", exc_info=True)
        for win in list(getattr(mw, "_hidden_run_windows", []) or []):
            try:
                if getattr(win, "_running", False):
                    live.append({
                        "ts": win._started or now, "live": True, "kind": "hidden",
                        "title": win._title or "(hidden run)",
                        "pathout": win._pathout or "",
                        "settings": win._settings_path or "",
                        "duration_s": now - (win._started or now),
                    })
            except (RuntimeError, AttributeError):
                continue
        for win in list(getattr(mw, "_batch_runner_windows", []) or []):
            try:
                for row, info in list(win._active.items()):
                    live.append({
                        "ts": info.get("started") or now, "live": True,
                        "kind": "batch", "settings": win._base_path,
                        "title": f"{win._base_title} [{info.get('name', '')}]",
                        "pathout": info.get("pathout", ""),
                        "duration_s": now - (info.get("started") or now),
                    })
            except (RuntimeError, AttributeError):
                continue
        return live

    def _grouped(self, entries):
        """Fold the scenarios of one Batch Run (same ``batch_id``) into a single row.
        Entries without a batch id - every run before this feature, and every main or
        hidden run - are left exactly as they are."""
        out, seen = [], {}
        for e in entries:
            bid = e.get("batch_id")
            if not bid or e.get("live"):
                out.append(e)
                continue
            group = seen.get(bid)
            if group is None:
                group = dict(e)
                group["members"] = [e]
                group["_ok"] = 1 if e.get("success") else 0
                seen[bid] = group
                out.append(group)
            else:
                group["members"].append(e)
                group["_ok"] += 1 if e.get("success") else 0
                group["ts"] = max(group.get("ts", 0), e.get("ts", 0))
                group["duration_s"] = (group.get("duration_s") or 0) + (
                    e.get("duration_s") or 0)
                group["last_dis"] = None
        for group in out:
            members = group.get("members")
            if members and len(members) > 1:
                base = (group.get("title") or "").split(" [")[0]
                group["title"] = f"{base} — batch of {len(members)}"
                group["pathout"] = os.path.dirname(group.get("pathout", "")) or \
                    group.get("pathout", "")
                group["success"] = group["_ok"] == len(members)
                group["group_ok"] = f"{group['_ok']}/{len(members)}"
        return out

    def _reload(self):
        """Rebuild the table: live runs first, then the stored history."""
        stored = sorted(run_ledger.load_entries(),
                        key=lambda e: e.get("ts", 0), reverse=True)
        self._all = stored
        rows = self._live_entries()
        rows.sort(key=lambda e: e.get("ts", 0), reverse=True)
        rows += self._grouped(stored) if self.group_check.isChecked() else stored
        self._entries = rows
        self._filling = True                    # itemChanged fires while filling
        self.table.setSortingEnabled(False)     # filling a sorted table shuffles it
        self.table.setRowCount(len(rows))
        live_brush = QBrush(QColor(theme.c("changed_line")))
        gone_brush = QBrush(QColor(theme.c("text_gray")))
        exists = {}                             # path -> bool, one stat per path
        for row, e in enumerate(rows):
            live = bool(e.get("live"))
            ts = e.get("ts", 0)
            when = ("running…" if live
                    else time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)))
            last = e.get("last_dis")
            try:
                last_txt = display_format.fmt(last) if last is not None else ""
            except (TypeError, ValueError):
                last_txt = str(last) if last is not None else ""
            if live:
                ok = "running"
            elif e.get("group_ok"):
                ok = e["group_ok"]
            else:
                ok = "yes" if e.get("success") else "no"
            kind = e.get("kind", "run")
            if kind and kind != "run" and not e.get("group_ok"):
                ok = f"{ok} ({kind})"
            elif e.get("group_ok"):
                ok = f"{ok} (batch)"
            duration = e.get("duration_s")
            values = [
                (when, ts), (e.get("title", ""), None), (e.get("pathout", ""), None),
                (self._fmt_dur(duration), float(duration or 0)),
                (ok, None), (last_txt, last if isinstance(last, (int, float)) else None),
                (e.get("settings", ""), None), (e.get("note", ""), None),
            ]
            grouped = bool(e.get("members") and len(e["members"]) > 1)
            for col, (text, key) in enumerate(values):
                item = _SortItem(text, key)
                if col == 0:
                    # Which entry this row shows - the row index itself stops being
                    # the answer as soon as the user sorts by a column.
                    item.setData(Qt.UserRole, row)
                if col in (3, 4, 5):
                    item.setTextAlignment(Qt.AlignCenter)
                if col == self._NOTE_COL and not live and not grouped:
                    item.setFlags(item.flags() | Qt.ItemIsEditable)
                    item.setToolTip("Double-click to write a note for this run")
                else:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    if col == self._NOTE_COL and grouped:
                        item.setToolTip("Untick “Group batches” to note one scenario")
                if live:
                    item.setBackground(live_brush)
                # A run whose output folder or settings file has been deleted since:
                # greyed out, so dead rows are visible instead of only discovered by
                # clicking. One stat per distinct path, not per row.
                elif col in (2, 6) and text:
                    if text not in exists:
                        exists[text] = (os.path.isdir(text) if col == 2
                                        else os.path.isfile(text))
                    if not exists[text]:
                        item.setForeground(gone_brush)
                        item.setToolTip("This path does not exist any more")
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        self._filling = False
        self._apply_filter()
        folder = run_ledger.history_dir()
        days = run_ledger.retention_days()
        keep = f"keep {days} days" if days else "keep forever"
        running = sum(1 for e in rows if e.get("live"))
        note = f"{len(stored)} run(s)"
        if running:
            note += f"  ·  {running} running now"
        self.sub_label.setText(f"{note}  ·  {folder}  ·  {keep}")

    def _apply_filter(self):
        """Hide the rows that do not contain the filter text (any column)."""
        needle = self.filter_edit.text().strip().lower()
        shown = 0
        for row in range(self.table.rowCount()):
            if not needle:
                self.table.setRowHidden(row, False)
                shown += 1
                continue
            hit = False
            for col in range(self.table.columnCount()):
                item = self.table.item(row, col)
                if item is not None and needle in item.text().lower():
                    hit = True
                    break
            self.table.setRowHidden(row, not hit)
            shown += 1 if hit else 0
        if needle:
            self.filter_edit.setToolTip(f"{shown} of {self.table.rowCount()} rows match")

    def _entry_at(self, row):
        """The entry a **table row** shows (via the index stashed in column 0, so it
        survives sorting)."""
        item = self.table.item(row, 0)
        if item is None:
            return None
        idx = item.data(Qt.UserRole)
        if isinstance(idx, int) and 0 <= idx < len(self._entries):
            return self._entries[idx]
        return None

    def _selected_entry(self):
        return self._entry_at(self.table.currentRow())

    def select_run(self, ts=None, pathout=None):
        """Select (and scroll to) the row of one run - used by Restore settingsfile ▸
        Show in Journal to point at the run that wrote a NetCDF. Returns True when a
        row matched; a batch row matches any of its scenarios."""
        target = os.path.normcase(os.path.abspath(pathout)) if pathout else ""
        for row in range(self.table.rowCount()):
            entry = self._entry_at(row)
            if entry is None:
                continue
            hit = ts is not None and entry.get("ts") == ts
            if not hit and target:
                own = entry.get("pathout") or ""
                hit = bool(own) and os.path.normcase(os.path.abspath(own)) == target
            if not hit and target:
                # A folded batch row stands for several scenarios.
                for member in entry.get("members") or ():
                    own = member.get("pathout") or ""
                    if own and os.path.normcase(os.path.abspath(own)) == target:
                        hit = True
                        break
            if hit:
                self.table.setRowHidden(row, False)
                self.table.selectRow(row)
                self.table.scrollToItem(self.table.item(row, 0),
                                        QAbstractItemView.PositionAtCenter)
                self.table.setFocus()
                return True
        return False

    def _selected_entries(self):
        """The marked runs, in table order."""
        rows = sorted({idx.row() for idx in
                       self.table.selectionModel().selectedRows()})
        return [e for e in (self._entry_at(r) for r in rows) if e is not None]

    def _update_compare_enabled(self):
        """Compare settings needs exactly two runs; Compare results two or more."""
        marked = self._selected_entries()
        self.compare_action.setEnabled(len(marked) == 2)
        self.compare_results_action.setEnabled(len(marked) >= 2)
        one = len(marked) == 1
        self.rerun_action.setEnabled(one and not marked[0].get("live"))
        self.log_action.setEnabled(one and bool(self._log_path(marked[0])))
        self.delete_action.setEnabled(
            bool(marked) and not any(e.get("live") for e in marked))

    def _compare_settings(self):
        """Diff the settings files of the two marked runs in the Compare window."""
        marked = self._selected_entries()
        if len(marked) != 2:
            return
        # Prefer the run-time snapshot (what actually ran) over the on-disk path.
        ea, eb = marked[0], marked[1]
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

    # -------------------------------------------------- notes / export / menu
    def _on_item_changed(self, item):
        """A note was edited - store it in the journal file."""
        if self._filling or item.column() != self._NOTE_COL:
            return
        entry = self._entry_at(item.row())
        if not entry or entry.get("live"):
            return
        note = item.text().strip()
        if run_ledger.set_note(entry, note):
            entry["note"] = note
            self.sub_label.setText(
                f"Note saved for “{entry.get('title', '')}”." if note
                else f"Note removed from “{entry.get('title', '')}”.")

    def _export_csv(self):
        """Write the rows currently **shown** (so the filter narrows the export) to a
        CSV - for a report, or a lab notebook."""
        start = os.path.join(run_ledger.history_dir(), "journal_of_runs.csv")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export the journal", start, "CSV files (*.csv);;All files (*)")
        if not path:
            return
        rows = [r for r in range(self.table.rowCount())
                if not self.table.isRowHidden(r)]
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh)
                writer.writerow(self._COLS + ["Kind", "Log"])
                for r in rows:
                    entry = self._entry_at(r) or {}
                    writer.writerow(
                        [self.table.item(r, c).text() if self.table.item(r, c) else ""
                         for c in range(len(self._COLS))]
                        + [entry.get("kind", ""), self._log_path(entry)])
        except Exception as ex:
            QMessageBox.warning(self, "Export", f"Could not write:\n{ex}")
            return
        self.sub_label.setText(f"{len(rows)} run(s) exported → {path}")

    def _on_row_menu(self, pos):
        """Right-click a run: everything that applies to it, including the two things
        that have no button - opening its folder in the file manager and copying a
        path (retyping one out of the table was the only way before)."""
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        entry = self._entry_at(row)
        if entry is None:
            return
        pathout = entry.get("pathout", "")
        settings = entry.get("settings", "")
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        act_results = menu.addAction("Open results (Output Explorer)")
        act_results.setEnabled(bool(pathout) and os.path.isdir(pathout))
        act_folder = menu.addAction("Open output folder")
        act_folder.setToolTip("Open PathOut in the file manager")
        act_folder.setEnabled(bool(pathout) and os.path.isdir(pathout))
        act_log = menu.addAction("Show log")
        act_log.setEnabled(bool(self._log_path(entry)))
        menu.addSeparator()
        act_copy_out = menu.addAction("Copy PathOut")
        act_copy_out.setEnabled(bool(pathout))
        act_copy_set = menu.addAction("Copy settings path")
        act_copy_set.setEnabled(bool(settings))
        menu.addSeparator()
        act_load = menu.addAction("Load settings")
        act_load.setEnabled(bool(settings) and not entry.get("live"))
        act_rerun = menu.addAction("Re-run")
        act_rerun.setEnabled(not entry.get("live"))
        act_delete = menu.addAction("Delete from the journal")
        act_delete.setEnabled(not entry.get("live"))

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        self.table.selectRow(row)
        if chosen is act_results:
            self._open_results()
        elif chosen is act_folder:
            self._open_folder(pathout)
        elif chosen is act_log:
            self._show_log()
        elif chosen is act_copy_out:
            self._copy_text(pathout, "PathOut")
        elif chosen is act_copy_set:
            self._copy_text(settings, "Settings path")
        elif chosen is act_load:
            self._load_settings()
        elif chosen is act_rerun:
            self._rerun()
        elif chosen is act_delete:
            self._delete_selected()

    def _open_folder(self, pathout):
        from src.gui.utils.open_path import open_path
        if not pathout or not os.path.isdir(pathout):
            QMessageBox.information(self, "Open output folder",
                                    "This run's PathOut does not exist any more:\n"
                                    + (pathout or "(none)"))
            return
        if not open_path(pathout):
            QMessageBox.warning(self, "Open output folder",
                                f"Could not open:\n{pathout}")

    def _copy_text(self, text, what):
        if not text:
            return
        QApplication.clipboard().setText(text)
        self.sub_label.setText(f"{what} copied: {text}")

    # ------------------------------------------------------------- log / delete
    @staticmethod
    def _log_path(entry):
        """This run's output log: the path recorded with the run, else the standard
        ``<PathOut>/cwatm_out.txt`` when one is actually there."""
        if not entry:
            return ""
        recorded = entry.get("log") or ""
        if recorded and os.path.isfile(recorded):
            return recorded
        pathout = entry.get("pathout") or ""
        candidate = os.path.join(pathout, "cwatm_out.txt") if pathout else ""
        return candidate if candidate and os.path.isfile(candidate) else ""

    def _show_log(self):
        """Show the run's log - the journal records *that* a run failed, this is the
        only place that says *why*. Only the tail is read: a long run's log is big."""
        entry = self._selected_entry()
        path = self._log_path(entry)
        if not path:
            QMessageBox.information(
                self, "Show log",
                "No log file was recorded for this run, and there is no "
                "cwatm_out.txt in its output folder.\n\n"
                "Main runs write one when Preferences ▸ Output ▸ Write output box is "
                "ticked; batch scenarios always do.")
            return
        limit = 2 * 1024 * 1024
        try:
            size = os.path.getsize(path)
            with open(path, encoding="utf-8", errors="replace") as fh:
                if size > limit:
                    fh.seek(size - limit)
                    text = "… (showing the last 2 MB) …\n" + fh.read()
                else:
                    text = fh.read()
        except Exception as ex:
            QMessageBox.warning(self, "Show log", f"Could not read the log:\n{ex}")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Log — {entry.get('title', '') or os.path.basename(path)}")
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.resize(*scaled_default_size(dlg, 900, 560))
        v = QVBoxLayout(dlg)
        head = QLabel(path)
        head.setStyleSheet(f"color: {theme.c('text_muted')}; font-size: 11px;")
        head.setWordWrap(True)
        v.addWidget(head)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {theme.c('out_bg')}; "
            f"color: {theme.c('out_text')}; border: 1px solid {theme.c('out_border')}; "
            "font-family: Consolas, monospace; font-size: 11px; }")
        view.setPlainText(text)
        view.moveCursor(QTextCursor.MoveOperation.End)
        v.addWidget(view, 1)
        row = QHBoxLayout()
        row.addStretch()
        close = QPushButton("Close")
        close.setStyleSheet(self._button_style())
        close.clicked.connect(dlg.close)
        row.addWidget(close)
        v.addLayout(row)
        dlg.setStyleSheet(f"QDialog {{ background-color: {theme.c('window_bg')}; }}")
        dlg.show()

    def _delete_selected(self):
        """Remove the marked runs (and their settings snapshots) from the journal.
        Until now it was all or nothing - Clear wiped everything."""
        marked = [e for e in self._selected_entries() if not e.get("live")]
        if not marked:
            return
        # A grouped batch row stands for all its scenarios.
        victims = []
        for e in marked:
            victims.extend(e.get("members") or [e])
        if QMessageBox.question(
                self, "Delete runs",
                f"Remove {len(victims)} run(s) from the journal?\n\n"
                "The output folders and settings files are NOT touched - only the "
                "journal entries and their settings snapshots.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        removed = run_ledger.remove_entries(victims)
        self._reload()
        self.sub_label.setText(f"{removed} run(s) removed from the journal")

    def _rerun(self):
        """Run this run's settings again, in a **Hidden Run** window - the journal
        knows exactly what ran, so repeating it should not be a manual load-then-run.
        Falls back to the run-time snapshot when the settings file is gone."""
        entry = self._selected_entry()
        if not entry or entry.get("live"):
            return
        path = entry.get("settings", "")
        note = ""
        if not path or not os.path.isfile(path):
            snap = entry.get("snapshot")
            if snap and os.path.isfile(snap):
                path, note = snap, ("\n\nThe original settings file is gone; the "
                                    "snapshot taken when the run started is used.")
            else:
                QMessageBox.information(
                    self, "Re-run",
                    "Neither this run's settings file nor its snapshot exists any "
                    "more.")
                return
        if QMessageBox.question(
                self, "Re-run",
                f"Run this settings file again in a Windowed Run window?\n\n"
                f"{path}{note}",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) != QMessageBox.Yes:
            return
        try:
            from src.gui.widgets.hidden_run_window import HiddenRunWindow
            mw = self.parent()
            if not hasattr(mw, "_hidden_run_windows"):
                mw._hidden_run_windows = []
            win = HiddenRunWindow(mw, path)
            win.destroyed.connect(
                lambda *_: mw._hidden_run_windows.remove(win)
                if win in mw._hidden_run_windows else None)
            mw._hidden_run_windows.append(win)
            win.show()
            win.raise_()
            win.activateWindow()
            win._start_run()
        except Exception as ex:
            log.warning("re-run failed", exc_info=True)
            QMessageBox.warning(self, "Re-run", f"Could not start the run:\n{ex}")

    def _compare_results(self):
        """Overlay the same result file of the marked runs in one Timeseries plot -
        Compare settings answers 'what differed in the set-up', this one answers
        'what differed in the results'."""
        marked = self._selected_entries()
        if len(marked) < 2:
            return
        found = {}
        for e in marked:
            out = e.get("pathout") or ""
            if not out or not os.path.isdir(out):
                continue
            label = e.get("title") or os.path.basename(out)
            try:
                with os.scandir(out) as it:
                    for f in it:
                        if f.is_file() and f.name.lower().endswith(".csv"):
                            found.setdefault(f.name, []).append((label, f.path))
            except OSError:
                continue
        usable = {n: v for n, v in found.items() if len(v) > 1}
        if not usable:
            QMessageBox.information(
                self, "Compare results",
                "No result .csv is present in two or more of the marked runs' output "
                "folders (only time series can be overlaid, not maps).")
            return
        if len(usable) == 1:
            chosen = next(iter(usable))
        else:
            names = sorted(usable, key=lambda n: (-len(usable[n]), n.lower()))
            picked, ok = QInputDialog.getItem(
                self, "Compare results", "Which result file?",
                [f"{n}   ({len(usable[n])} runs)" for n in names], 0, False)
            if not ok or not picked:
                return
            chosen = picked.split("   (")[0]
        entries = usable[chosen]
        try:
            from src.gui.widgets.analysis_timeseries import open_comparison
            open_comparison(self.parent() or self, [p for _l, p in entries],
                            [l for l, _p in entries])
        except Exception as ex:
            log.warning("compare results failed", exc_info=True)
            QMessageBox.warning(self, "Compare results", f"Could not compare:\n{ex}")

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
            from src.gui.utils.open_path import open_path
            if not open_path(pathout):
                QMessageBox.warning(self, "Open results",
                                    f"Could not open:\n{pathout}")

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
                self, "Clear journal", "Delete all recorded runs?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        run_ledger.clear()
        self._reload()

    def closeEvent(self, event):
        self._live_timer.stop()      # no ticks into a window that is going away
        super().closeEvent(event)    # the geometry mixin saves size/position
