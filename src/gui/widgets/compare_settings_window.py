"""Tools ▸ Compare settings - show the differences between two settings files
side by side, with alignment padding, synchronized scrolling and diff navigation.

Two panes, each a `SettingsEditor` (+ line-number gutter) with the same top button
row as the main settings window (Save / Save As / Fold All / Unfold All / Top /
Down; the left pane also has **Next Diff / Previous Diff**, the right pane a **Load**
button). The **left** pane is preloaded with the settings file currently open in the
main window (live editor text). The **right** pane starts empty; **Load** opens a
`*.ini`.

Once both panes hold content the two files are **aligned**: light-gray filler lines
are inserted on whichever side is shorter so equal lines sit on the same row on both
sides. Lines that differ are marked **red**, filler lines **light-gray**. The two
editors **scroll together**, and **Next/Previous Diff** jump between difference blocks.

A menu bar (**File / History / Settings**) mirrors the main window's actions but
applies them to the **active** side (whichever editor last had focus).

Styled like the other secondary windows: `GeometryMemoryMixin` + `QDialog`, every
colour a `theme.c(token)`, cwatm.ico, geometry key `compare_settings`.
"""

import os
import difflib

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget,
    QFileDialog, QMessageBox, QMenuBar, QInputDialog,
)
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QIcon, QTextCursor

from src.gui.utils import theme
from src.gui.utils.window_geometry import GeometryMemoryMixin
from src.gui.utils.gui_log import get_logger
from src.gui.widgets.settings_editor import SettingsEditor
from src.gui.widgets.line_number_gutter import LineNumberGutter

log = get_logger("compare_settings_window")

# Fixed height of each pane's button bar, so both editors start at the same Y even
# though the left pane has the taller blue diff buttons.
_BTN_BAR_HEIGHT = 34


def open_compare_settings(parent=None):
    """Open the Compare settings window, preloading the main window's content."""
    win = CompareSettingsWindow(parent)
    win.show()
    win.raise_()
    win.activateWindow()
    return win


def open_compare_files(parent, left_path, right_path):
    """Open the Compare settings window on two specific settings files (used by the
    Run Ledger's Compare settings). Falls back to preloaded content on a read error."""
    win = CompareSettingsWindow(parent)
    win.load_files(left_path, right_path)
    win.show()
    win.raise_()
    win.activateWindow()
    return win


def align_and_diff(a_lines, b_lines):
    """Align two line lists for a side-by-side diff.

    Returns a dict with equal-length ``left`` / ``right`` display line lists (gray
    filler '' inserted on the shorter side of each change), the 0-based **display**
    rows that differ / are filler per side, and the sorted list of diff-block start
    rows (for Next/Previous Diff)."""
    left, right = [], []
    ldiff, rdiff, lfill, rfill = set(), set(), set(), set()
    blocks = []
    sm = difflib.SequenceMatcher(a=a_lines, b=b_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                left.append(a_lines[i1 + k])
                right.append(b_lines[j1 + k])
            continue
        block_start = len(left)
        la, rb = a_lines[i1:i2], b_lines[j1:j2]
        for k in range(max(len(la), len(rb))):
            row = len(left)
            if k < len(la):
                left.append(la[k]); ldiff.add(row)
            else:
                left.append(""); lfill.add(row)
            if k < len(rb):
                right.append(rb[k]); rdiff.add(row)
            else:
                right.append(""); rfill.add(row)
        blocks.append(block_start)
    return {
        "left": "\n".join(left), "right": "\n".join(right),
        "ldiff": ldiff, "rdiff": rdiff, "lfill": lfill, "rfill": rfill,
        "blocks": sorted(blocks),
    }


class _ComparePane(QWidget):
    """One side of the compare window: a button row + gutter + settings editor."""

    def __init__(self, with_load=False, with_diffnav=False, with_topdown=True,
                 with_fold=True, show_vscroll=True, lead_spacing=0,
                 diffnav_flush_right=False, on_changed=None, on_focus=None,
                 on_fold_all=None, on_unfold_all=None, on_saved=None, parent=None):
        super().__init__(parent)
        self._on_changed = on_changed          # re-diff callback (Load / Save)
        self._on_focus = on_focus              # active-side callback
        self._on_saved = on_saved              # notify after a successful write(path)
        self.file_path = None
        self.filler_rows = set()               # display rows that are gray padding

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # File-name header: bold, dark green.
        self.header = QLabel("(no file)")
        self.header.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 12px; font-weight: bold; "
            "color: #0a7a2f; padding: 2px;")
        layout.addWidget(self.header)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(3)
        style = self._button_style()
        if lead_spacing:
            btn_row.addSpacing(lead_spacing)   # shift the whole row right
        if with_load:
            self.load_button = QPushButton("Load")
            self.load_button.setToolTip("Open a settings file (*.ini) to compare")
            self.load_button.setStyleSheet(style)
            self.load_button.clicked.connect(self._on_load)
            btn_row.addWidget(self.load_button)
        buttons = [("Save", self._on_save), ("Save As", self._on_save_as)]
        # Fold All / Unfold All only on the left pane - it folds/unfolds BOTH sides
        # (the fold state is synchronized), so the right pane omits them.
        if with_fold:
            buttons += [("Fold All", on_fold_all or self.fold_all),
                        ("Unfold All", on_unfold_all or self.unfold_all)]
        # Top / Down only on the left pane - the scrollbars are synchronized, so the
        # right pane would just duplicate them.
        if with_topdown:
            buttons += [("Top", self.top), ("Down", self.down)]
        for label, slot in buttons:
            b = QPushButton(label)
            b.setStyleSheet(style)
            b.clicked.connect(slot)
            btn_row.addWidget(b)

        def _make_diff_buttons():
            diff_style = self._diff_button_style()
            self.next_diff_button = QPushButton("Next Diff F6")
            self.next_diff_button.setToolTip("Show next difference   F6")
            self.next_diff_button.setShortcut("F6")
            self.next_diff_button.setStyleSheet(diff_style)
            btn_row.addWidget(self.next_diff_button)
            self.prev_diff_button = QPushButton("Prev Diff Sh+F6")
            self.prev_diff_button.setToolTip("Show previous difference   Shift+F6")
            self.prev_diff_button.setShortcut("Shift+F6")
            self.prev_diff_button.setStyleSheet(diff_style)
            btn_row.addWidget(self.prev_diff_button)

        if with_diffnav and diffnav_flush_right:
            # Flush against the right edge of the (left) pane = the centre of the
            # window, between the left pane's Down and the right pane's Load.
            btn_row.addStretch()
            _make_diff_buttons()
        elif with_diffnav:
            btn_row.addSpacing(12)
            _make_diff_buttons()
            btn_row.addStretch()
        else:
            btn_row.addStretch()
        # Wrap the button row in a FIXED-height bar (the same on both panes) so the
        # editors below start at the same vertical position - otherwise the taller
        # blue diff buttons on the left pane push its editor lower than the right's.
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_bar = QWidget()
        btn_bar.setLayout(btn_row)
        btn_bar.setFixedHeight(_BTN_BAR_HEIGHT)
        layout.addWidget(btn_bar)

        self.editor = SettingsEditor()
        self.editor.setLineWrapMode(SettingsEditor.NoWrap)
        self.editor.setStyleSheet(self._editor_style())
        # Only the right pane shows a vertical scrollbar (on the very right of the
        # window); the scrollbars are synced so it drives both. The left pane hides
        # its own to leave a single scrollbar, like the main window's right part.
        self.editor.setVerticalScrollBarPolicy(
            Qt.ScrollBarAsNeeded if show_vscroll else Qt.ScrollBarAlwaysOff)
        self.editor.installEventFilter(self)
        self.gutter = LineNumberGutter(self.editor)
        editor_row = QHBoxLayout()
        editor_row.setSpacing(2)
        editor_row.addWidget(self.gutter)
        editor_row.addWidget(self.editor, 1)
        layout.addLayout(editor_row)

    # ---------------------------------------------------------------- focus
    def eventFilter(self, obj, event):
        if obj is self.editor and event.type() == QEvent.FocusIn and self._on_focus:
            self._on_focus(self)
        return super().eventFilter(obj, event)

    # ---------------------------------------------------------------- content
    def set_source(self, text, path=None, name=None):
        """Set this pane's *real* (unaligned) content and file path."""
        self.filler_rows = set()
        self.editor.load_text(text or "")
        self.file_path = path
        self.header.setText(name or (os.path.basename(path) if path else "(no file)"))

    def show_aligned(self, aligned_text, diff_rows, filler_rows):
        """Replace the editor with the aligned display and mark diff/filler rows."""
        self.filler_rows = set(filler_rows)
        self.editor.load_text(aligned_text)
        self.editor.set_diff_rows(diff_rows)       # orange = differences
        self.editor.set_filler_rows(filler_rows)

    def real_text(self):
        """Current editor text with the tracked (empty) filler rows removed - the
        real settings content, robust to edits of the real lines."""
        lines = self.editor.toPlainText().split("\n")
        out = []
        for i, ln in enumerate(lines):
            if i in self.filler_rows and ln == "":
                continue
            out.append(ln)
        return "\n".join(out)

    def has_content(self):
        return bool(self.real_text().strip())

    # ---------------------------------------------------------------- actions
    def _on_load(self):
        start_dir = os.path.dirname(self.file_path) if self.file_path else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load settings file to compare", start_dir,
            "Settings files (*.ini);;All files (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Compare settings", f"Could not read the file:\n{e}")
            return
        self.set_source(content, path)
        if self._on_changed:
            self._on_changed()

    def _on_save(self):
        if not self.file_path:
            self._on_save_as()
            return
        if self._write(self.file_path):
            if self._on_changed:
                self._on_changed()
            if self._on_saved:
                self._on_saved(self.file_path)

    def _on_save_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save settings file as", self.file_path or "",
            "Settings files (*.ini);;All files (*)")
        if not path:
            return
        if self._write(path):
            self.file_path = path
            self.header.setText(os.path.basename(path))
            if self._on_changed:
                self._on_changed()
            if self._on_saved:
                self._on_saved(path)

    def _write(self, path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.real_text())   # never write the gray filler lines
            return True
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Compare settings", f"Could not write the file:\n{e}")
            return False

    def fold_all(self):
        self.editor.fold_all()

    def unfold_all(self):
        self.editor.unfold_all()

    def top(self):
        cur = self.editor.textCursor()
        cur.movePosition(QTextCursor.Start)
        self.editor.setTextCursor(cur)
        self.editor.ensureCursorVisible()

    def down(self):
        cur = self.editor.textCursor()
        cur.movePosition(QTextCursor.End)
        self.editor.setTextCursor(cur)
        self.editor.reveal_cursor()
        self.editor.ensureCursorVisible()

    # ------------------------------------------------------------------ styles
    @staticmethod
    def _button_style():
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {theme.c('btn_top')}, stop:1 {theme.c('btn_bottom')});
                border: 1px solid {theme.c('btn_border')}; border-radius: 5px;
                color: {theme.c('btn_text')}; font-weight: 600; font-size: 11px;
                padding: 2px 8px; min-height: 16px;
            }}
            QPushButton:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {theme.c('btn_hover_top')}, stop:1 {theme.c('btn_hover_bottom')});
                border-color: {theme.c('btn_hover_border')}; }}
        """

    @staticmethod
    def _diff_button_style():
        """Bigger, blue buttons for Next/Previous Diff (stand out from the grey row)."""
        return """
            QPushButton {
                font-family: 'Segoe UI', sans-serif; font-size: 12px; font-weight: 600;
                color: white; border: none; border-radius: 6px;
                padding: 4px 14px; min-height: 24px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #5dade2, stop:1 #3498db);
            }
            QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #85c1e9, stop:1 #5dade2); }
        """

    @staticmethod
    def _editor_style():
        # Wide 16px vertical scrollbar, same as the main window's right part.
        return f"""
            QPlainTextEdit {{
                background-color: {theme.c('editor_bg')};
                border: 2px solid {theme.c('editor_border')};
                border-radius: 10px; padding: 10px;
                font-family: 'Consolas', 'Monaco', monospace; font-size: 13px;
                color: {theme.c('editor_text')};
                selection-background-color: {theme.c('sel_bg')};
                selection-color: {theme.c('sel_text')};
            }}
            QScrollBar:vertical {{
                background-color: {theme.c('surface_bg')};
                width: 16px; border-radius: 6px; margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {theme.c('accent')};
                border-radius: 6px; min-height: 28px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {theme.c('menu_sel_bg')};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
        """


class CompareSettingsWindow(GeometryMemoryMixin, QDialog):
    """Side-by-side settings-file diff viewer with alignment, sync scroll and nav."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._main = parent
        self._diff_blocks = []       # sorted display-row starts of each diff block
        self._changed_rows = set()   # every non-equal display row
        self._syncing = False        # scrollbar-sync reentrancy guard
        self._folding_sync = False   # fold-sync reentrancy guard
        self._find_term = ""
        self.setWindowTitle("⇔ Compare settings")
        self.setModal(False)
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        if not self._init_geometry_memory("compare_settings"):
            self.resize(1300, 820)
        self._set_window_icon()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._build_menubar(layout)

        panes = QHBoxLayout()
        panes.setSpacing(10)
        # Left pane hides its vertical scrollbar; the single scrollbar sits on the
        # very right (right pane) and drives both via the sync.
        # Left pane: Fold All/Unfold All (folding BOTH sides), Top/Down, and the diff
        # buttons flush-right = the centre of the window (between Down and Load).
        self.left = _ComparePane(with_load=False, with_diffnav=True, with_topdown=True,
                                 with_fold=True, show_vscroll=False,
                                 diffnav_flush_right=True,
                                 on_changed=self._recompare, on_focus=self._set_active,
                                 on_fold_all=self._fold_all_both,
                                 on_unfold_all=self._unfold_all_both,
                                 on_saved=self._on_pane_saved)
        # Right pane: no Fold/Unfold, no Top/Down (driven from the left / synced) - has
        # Load. lead_spacing shifts Load/Save/Save As further to the right of centre.
        self.right = _ComparePane(with_load=True, with_diffnav=False, with_topdown=False,
                                  with_fold=False, show_vscroll=True, lead_spacing=60,
                                  on_changed=self._recompare, on_focus=self._set_active,
                                  on_saved=self._on_pane_saved)
        panes.addWidget(self.left, 1)
        panes.addWidget(self.right, 1)
        layout.addLayout(panes, 1)
        self._active = self.left

        # Next / Previous Diff (left pane buttons, centred at the divider)
        self.left.next_diff_button.clicked.connect(lambda: self._goto_diff(+1))
        self.left.prev_diff_button.clicked.connect(lambda: self._goto_diff(-1))

        # Synchronize the two vertical + horizontal scrollbars.
        self._link_scrollbars(self.left.editor, self.right.editor)
        # Synchronize section folding: folding/unfolding a section on either side
        # mirrors to the other.
        self.left.editor.foldingChanged.connect(
            lambda: self._sync_folds(self.left.editor, self.right.editor))
        self.right.editor.foldingChanged.connect(
            lambda: self._sync_folds(self.right.editor, self.left.editor))

        bottom = QHBoxLayout()
        self.summary = QLabel("")
        self.summary.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 12px; "
            f"color: {theme.c('text_muted')};")
        bottom.addWidget(self.summary)
        bottom.addStretch()
        self.close_button = QPushButton("Close")
        self.close_button.setStyleSheet(self._blue_button_style())
        self.close_button.clicked.connect(self.close)
        bottom.addWidget(self.close_button)
        layout.addLayout(bottom)

        self.setStyleSheet(f"QDialog {{ background-color: {theme.c('window_bg')}; }}")
        self._preload_left()

    # -------------------------------------------------------------- menu bar
    def _build_menubar(self, layout):
        mbar = QMenuBar(self)
        mbar.setStyleSheet(
            f"QMenuBar {{ background-color: {theme.c('menubar_bg')}; "
            f"color: {theme.c('text')}; }}"
            f"QMenuBar::item:selected {{ background-color: {theme.c('menu_sel_bg')}; }}")

        def _add(menu, text, slot, shortcut=None, tip=None):
            act = menu.addAction(text, slot)
            if shortcut:
                act.setShortcut(shortcut)
            if tip:
                act.setToolTip(tip)
            return act

        # File - operates on the active side; same shortcuts as the main window.
        file_menu = mbar.addMenu("File")
        _add(file_menu, "Load .ini", self._m_load, "Ctrl+O")
        _add(file_menu, "Reload", self._m_reload, "Ctrl+L")
        _add(file_menu, "Save .ini", self._m_save, "Ctrl+S")
        _add(file_menu, "Save As", self._m_save_as, "Ctrl+Alt+S")
        file_menu.addSeparator()
        file_menu.addAction("Close", self.close)

        self.history_menu = mbar.addMenu("History")
        self.history_menu.setToolTipsVisible(True)
        self.history_menu.aboutToShow.connect(self._populate_history)

        # Settings - same actions/shortcuts as the main window's Settings menu. F5 is
        # free for Find now that diff-nav uses F6 / Shift+F6. Fold All / Unfold All
        # fold BOTH sides.
        settings_menu = mbar.addMenu("Settings")
        _add(settings_menu, "Fold All", self._fold_all_both, "Alt+0")
        _add(settings_menu, "Unfold All", self._unfold_all_both, "Alt+Shift+0")
        _add(settings_menu, "Top", lambda: self._active.top(), "Alt+T")
        _add(settings_menu, "Down", lambda: self._active.down(), "Alt+D")
        settings_menu.addSeparator()
        _add(settings_menu, "Find", self._m_find, "F5")
        _add(settings_menu, "Find next", self._m_find_next, "Ctrl+F")
        settings_menu.addSeparator()
        # Bookmarks on the active side - same shortcuts as the main window.
        _add(settings_menu, "Toggle Bookmark",
             lambda: self._active.editor.toggle_bookmark(), "Ctrl+F2")
        _add(settings_menu, "Next Bookmark",
             lambda: self._active.editor.goto_next_bookmark(True), "F2")
        _add(settings_menu, "Previous Bookmark",
             lambda: self._active.editor.goto_next_bookmark(False), "Shift+F2")
        _add(settings_menu, "Clear all Bookmarks",
             lambda: self._active.editor.clear_bookmarks(), "Ctrl+Shift+F2")
        settings_menu.addSeparator()
        settings_menu.addAction("Next Diff", lambda: self._goto_diff(+1))
        settings_menu.addAction("Previous Diff", lambda: self._goto_diff(-1))
        self._menus = [file_menu, self.history_menu, settings_menu]  # GC guard
        layout.setMenuBar(mbar)

    def _set_active(self, pane):
        self._active = pane

    # File-menu handlers operate on the ACTIVE side.
    def _m_load(self):
        # Left pane has no Load button but the menu can still load into it.
        self._active._on_load()

    def _m_reload(self):
        p = self._active
        if not p.file_path or not os.path.exists(p.file_path):
            self.summary.setText("Active side has no file on disk to reload.")
            return
        try:
            with open(p.file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Compare settings", f"Could not reload:\n{e}")
            return
        p.set_source(content, p.file_path)
        self._recompare()

    def _m_save(self):
        self._active._on_save()

    def _m_save_as(self):
        self._active._on_save_as()

    def _populate_history(self):
        self.history_menu.clear()
        recent = list(getattr(self._main, "_recent_files", []) or [])
        if not recent:
            act = self.history_menu.addAction("(no recent files)")
            act.setEnabled(False)
            return
        for path in recent:
            act = self.history_menu.addAction(os.path.basename(path))
            act.setToolTip(path)
            act.triggered.connect(lambda _c=False, p=path: self._open_recent(p))

    def _open_recent(self, path):
        if not os.path.exists(path):
            self.summary.setText(f"File not found: {path}")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Compare settings", f"Could not open:\n{e}")
            return
        self._active.set_source(content, path)   # into the active side
        self._recompare()

    def _m_find(self):
        term, ok = QInputDialog.getText(self, "Find", "Find text:", text=self._find_term)
        if ok and term:
            self._find_term = term
            self._m_find_next()

    def _m_find_next(self):
        if not self._find_term:
            self._m_find()
            return
        ed = self._active.editor
        if not ed.find(self._find_term):
            cur = ed.textCursor()
            cur.movePosition(QTextCursor.Start)
            ed.setTextCursor(cur)
            ed.find(self._find_term)   # wrap around

    # -------------------------------------------------------------- scroll sync
    def _link_scrollbars(self, ed_a, ed_b):
        av, bv = ed_a.verticalScrollBar(), ed_b.verticalScrollBar()
        ah, bh = ed_a.horizontalScrollBar(), ed_b.horizontalScrollBar()
        av.valueChanged.connect(lambda v: self._mirror(bv, v))
        bv.valueChanged.connect(lambda v: self._mirror(av, v))
        ah.valueChanged.connect(lambda v: self._mirror(bh, v))
        bh.valueChanged.connect(lambda v: self._mirror(ah, v))

    def _mirror(self, bar, value):
        if self._syncing:
            return
        self._syncing = True
        try:
            bar.setValue(value)
        finally:
            self._syncing = False

    # -------------------------------------------------------------- fold sync
    def _sync_folds(self, source, target):
        """Mirror the folded sections from ``source`` to ``target`` (guarded)."""
        if self._folding_sync:
            return
        self._folding_sync = True
        try:
            target.apply_folds(source.folded_sections())
        finally:
            self._folding_sync = False

    def _fold_all_both(self):
        self._folding_sync = True
        try:
            self.left.editor.fold_all()
            self.right.editor.fold_all()
        finally:
            self._folding_sync = False

    def _unfold_all_both(self):
        self._folding_sync = True
        try:
            self.left.editor.unfold_all()
            self.right.editor.unfold_all()
        finally:
            self._folding_sync = False

    # -------------------------------------------------------------- diff nav
    def _goto_diff(self, direction):
        if not self._diff_blocks:
            self.summary.setText("No differences to navigate.")
            return
        row = self.left.editor.textCursor().blockNumber()
        if direction > 0:
            nxt = next((b for b in self._diff_blocks if b > row), self._diff_blocks[0])
        else:
            prev = [b for b in self._diff_blocks if b < row]
            nxt = prev[-1] if prev else self._diff_blocks[-1]
        self._scroll_both_to(nxt)
        self._highlight_current_block(nxt)

    def _highlight_current_block(self, start):
        """Mark the jumped-to difference block darker orange on both editors."""
        rows = set()
        r = start
        while r in self._changed_rows:
            rows.add(r)
            r += 1
        if not rows:
            rows = {start}
        self.left.editor.set_current_diff_rows(rows)
        self.right.editor.set_current_diff_rows(rows)

    def _scroll_both_to(self, row):
        for ed in (self.left.editor, self.right.editor):
            doc = ed.document()
            block = doc.findBlockByNumber(min(row, doc.blockCount() - 1))
            cur = ed.textCursor()
            cur.setPosition(block.position())
            ed.setTextCursor(cur)
            ed.centerCursor()

    # -------------------------------------------------------------- compare
    def _preload_left(self):
        mw = self._main
        try:
            if mw is not None and getattr(mw, "text_area", None) is not None:
                content = mw.text_area.toPlainText()
                path, name = None, "(current settings)"
                try:
                    path = mw.file_manager.get_current_file_path()
                    if path:
                        name = os.path.basename(path)
                except Exception:
                    path = None
                if content.strip():
                    self.left.set_source(content, path, name)
                    return
        except Exception:
            log.debug("preload left failed", exc_info=True)
        self.left.set_source("", None, "(no settings loaded)")

    def _on_pane_saved(self, path):
        """A pane just saved to ``path``. If that file is the one open in the main
        settings window, refresh the main window so it shows the saved version
        (otherwise the main editor keeps showing the pre-save content)."""
        mw = self._main
        if mw is None or not path:
            return
        try:
            cur = mw.file_manager.get_current_file_path()
        except Exception:
            cur = None
        if not cur:
            return
        try:
            same = (os.path.normcase(os.path.abspath(cur))
                    == os.path.normcase(os.path.abspath(path)))
        except Exception:
            same = (cur == path)
        if not same:
            return
        try:
            mw.reload_after_external_save(path)
        except Exception:
            log.debug("main-window refresh after compare save failed", exc_info=True)

    def load_files(self, left_path, right_path):
        """Load two specific settings files into the two panes and diff them (Run
        Ledger ▸ Compare settings). A file that cannot be read loads as empty."""
        for pane, path in ((self.left, left_path), (self.right, right_path)):
            content, name = "", (os.path.basename(path) if path else "(missing)")
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception:
                log.debug("compare load failed: %s", path, exc_info=True)
                name += " (not found)"
            pane.set_source(content, path, name)
        self._recompare()

    def _recompare(self):
        """Re-align both sides, push the aligned display, mark diffs/filler."""
        if not (self.left.has_content() and self.right.has_content()):
            # Show raw (unaligned) content; clear any marks.
            for pane in (self.left, self.right):
                pane.filler_rows = set()
                pane.editor.set_diff_rows(set())
                pane.editor.set_filler_rows(set())
                pane.editor.set_current_diff_rows(set())
            self._diff_blocks = []
            self._changed_rows = set()
            self.summary.setText(
                "Load a settings file on the right to compare."
                if self.left.has_content() else "")
            return
        a = self.left.real_text().split("\n")
        b = self.right.real_text().split("\n")
        res = align_and_diff(a, b)
        self._syncing = True   # avoid scroll feedback while both are repopulated
        try:
            self.left.show_aligned(res["left"], res["ldiff"], res["lfill"])
            self.right.show_aligned(res["right"], res["rdiff"], res["rfill"])
        finally:
            self._syncing = False
        self._diff_blocks = res["blocks"]
        # Every non-equal display row (for computing a jumped-to block's extent).
        self._changed_rows = res["ldiff"] | res["rdiff"] | res["lfill"] | res["rfill"]
        ld, rd = len(res["ldiff"]), len(res["rdiff"])
        if not self._diff_blocks:
            self.summary.setText("The two files are identical.")
        else:
            self.summary.setText(
                f"{len(self._diff_blocks)} difference block(s): "
                f"{ld} changed line(s) left, {rd} right "
                f"(gray = alignment padding). Use Next/Previous Diff.")

    # -------------------------------------------------------------- misc
    def _set_window_icon(self):
        try:
            root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(__file__))))
            icon_path = os.path.join(root, "assets", "cwatm.ico")
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass

    @staticmethod
    def _blue_button_style():
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
