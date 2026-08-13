"""Settings > Find (Ctrl+F) / Replace (Ctrl+H) - the combined Find & Replace window.

One non-modal dialog with a shared "Find:" box above a Find / Replace tab pair, and its
own status bar for match counts. F3 / Shift+F3 keep working while it is open, and
"Replace all in selection" follows the editor's selection state.

Mixed into `CWatMMainWindow`; searches the **active tab's** editor through
`self.text_area`, so it follows a tab switch without knowing tabs exist.
"""

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget,
)
from PySide6.QtGui import QTextCursor, QTextDocument

from src.gui.utils.gui_log import get_logger

log = get_logger("find_replace")


class FindReplaceMixin:
    """The Find & Replace window of `CWatMMainWindow` (see the module docstring)."""

    def find_text(self):
        """Settings > Find (Ctrl+F): the combined Find & Replace window, Find tab."""
        self._open_find_dialog(0)

    def _open_find_dialog(self, tab):
        """Open (or raise) the combined, non-modal Find & Replace window on tab
        0 = Find (Find Next / Count / Close) or 1 = Replace (Find next / Replace /
        Replace all / Close). One shared "Find:" box above the tabs and one shared
        status bar below them; F3 / Shift+F3 keep working while it is open."""
        if getattr(self, "text_area", None) is None:
            return
        if self._find_dialog is not None:
            dlg = self._find_dialog
            dlg._tabs.setCurrentIndex(tab)
            if tab == 1:
                # Entering the Replace tab with a selection auto-ticks
                # "Replace all in selection" (currentChanged does not fire
                # when the tab was already active).
                dlg._sync_sel_check(auto_tick=True)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            dlg._edit.setFocus()
            dlg._edit.selectAll()
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Find & Replace")
        lay = QVBoxLayout(dlg)

        # Shared search box above the tabs (both tabs search the same text).
        top = QHBoxLayout()
        top.addWidget(QLabel("Find:"))
        find_edit = QLineEdit(getattr(self, "_last_search", ""))
        find_edit.selectAll()
        top.addWidget(find_edit, 1)
        lay.addLayout(top)

        tabs = QTabWidget()
        lay.addWidget(tabs)

        # --- Find tab: Find Next / Count / Close
        find_tab = QWidget()
        fgrid = QGridLayout(find_tab)
        next_btn = QPushButton("Find Next")
        count_btn = QPushButton("Count")
        count_btn.setToolTip("Count the matches in the whole file")
        close_btn = QPushButton("Close")
        fgrid.addWidget(next_btn, 0, 0)
        fgrid.addWidget(count_btn, 0, 1)
        fgrid.addWidget(close_btn, 0, 2)
        tabs.addTab(find_tab, "Find")

        # --- Replace tab: the former Replace window (minus its own Find box)
        rep_tab = QWidget()
        rgrid = QGridLayout(rep_tab)
        rgrid.addWidget(QLabel("Replace with:"), 0, 0)
        replace_edit = QLineEdit()
        rgrid.addWidget(replace_edit, 0, 1, 1, 3)
        rfind_btn = QPushButton("Find next")
        replace_btn = QPushButton("Replace")
        all_btn = QPushButton("Replace all")
        rclose_btn = QPushButton("Close")
        rgrid.addWidget(rfind_btn, 1, 0)
        rgrid.addWidget(replace_btn, 1, 1)
        rgrid.addWidget(all_btn, 1, 2)
        rgrid.addWidget(rclose_btn, 1, 3)
        # Only checkable while the editor has a selection; auto-ticked when the
        # Replace tab is entered with a selection already made.
        sel_check = QCheckBox("Replace all in selection")
        sel_check.setToolTip(
            "Replace all only inside the current editor selection")
        rgrid.addWidget(sel_check, 2, 0, 1, 4)
        tabs.addTab(rep_tab, "Replace")

        # The window's own status bar (match counts, "not found", replace results).
        status = QLabel("")
        status.setFrameStyle(QFrame.StyledPanel | QFrame.Sunken)
        lay.addWidget(status)
        dlg._tabs = tabs
        dlg._edit = find_edit
        dlg._status = status

        # Keep _last_search in sync while typing, so the F3/Shift+F3 menu
        # shortcuts search for what the box shows.
        find_edit.textChanged.connect(
            lambda text: setattr(self, "_last_search", text))

        def _find_next():
            text = find_edit.text()
            if not text:
                return
            status.setText("" if self._find_in_editor(text)
                           else f"'{text}' not found")

        def _count():
            text = find_edit.text()
            if not text:
                return
            # Same case-insensitivity as the editor's find(); non-overlapping.
            n = self.text_area.toPlainText().lower().count(text.lower())
            status.setText(f"{n} match(es) in the file")

        def _replace_one():
            text = find_edit.text()
            if not text:
                return
            cursor = self.text_area.textCursor()
            if cursor.hasSelection() and cursor.selectedText().lower() == text.lower():
                cursor.insertText(replace_edit.text())
            _find_next()

        def _replace_all():
            text = find_edit.text()
            if not text:
                return
            count = 0
            rep = replace_edit.text()
            if sel_check.isChecked():
                # Replace only inside the current editor selection. Walk the
                # document with QTextDocument.find (same default case-
                # insensitivity as the widget's find) and shift the selection
                # end by each replacement's length difference.
                doc = self.text_area.document()
                cursor = self.text_area.textCursor()
                end = cursor.selectionEnd()
                found = doc.find(text, cursor.selectionStart())
                while not found.isNull() and found.selectionEnd() <= end:
                    end += len(rep) - (found.selectionEnd()
                                       - found.selectionStart())
                    found.insertText(rep)
                    count += 1
                    found = doc.find(text, found.position())
                self.text_area.reveal_cursor()
                status.setText(f"Replaced {count} occurrence(s) in the selection")
                return
            cursor = self.text_area.textCursor()
            cursor.movePosition(QTextCursor.Start)
            self.text_area.setTextCursor(cursor)
            while self.text_area.find(text):
                found = self.text_area.textCursor()
                found.insertText(rep)
                count += 1
            # The last replacement may sit in a folded section - unfold it
            self.text_area.reveal_cursor()
            status.setText(f"Replaced {count} occurrence(s)")

        next_btn.clicked.connect(_find_next)
        count_btn.clicked.connect(_count)
        rfind_btn.clicked.connect(_find_next)
        replace_btn.clicked.connect(_replace_one)
        all_btn.clicked.connect(_replace_all)
        for b in (close_btn, rclose_btn):
            b.clicked.connect(dlg.close)
        find_edit.returnPressed.connect(_find_next)
        replace_edit.returnPressed.connect(_replace_one)

        # --- "Replace all in selection" enable/tick rules:
        # no selection -> unchecked and disabled; a selection made while the
        # window is open -> enabled (user toggles); entering the Replace tab
        # with a selection already made -> enabled AND auto-ticked.
        def _sync_sel_check(auto_tick=False):
            has = self.text_area.textCursor().hasSelection()
            sel_check.setEnabled(has)
            if not has:
                sel_check.setChecked(False)
            elif auto_tick:
                sel_check.setChecked(True)

        def _on_selection_changed():
            _sync_sel_check(auto_tick=False)

        def _on_tab_changed(index):
            if index == 1:
                _sync_sel_check(auto_tick=True)

        self.text_area.selectionChanged.connect(_on_selection_changed)
        tabs.currentChanged.connect(_on_tab_changed)
        dlg._sync_sel_check = _sync_sel_check
        # The menu shortcuts are window-scoped -> mirror them on the dialog so
        # F3 / Shift+F3 also work while the Find window itself has focus.
        from PySide6.QtGui import QShortcut, QKeySequence
        QShortcut(QKeySequence("F3"), dlg, activated=self.find_next)
        QShortcut(QKeySequence("Shift+F3"), dlg, activated=self.find_previous)

        tabs.setCurrentIndex(tab)
        _sync_sel_check(auto_tick=(tab == 1))   # initial checkbox state

        def _on_closed(*_):
            # Stop tracking the editor selection for this (closed) window.
            try:
                self.text_area.selectionChanged.disconnect(_on_selection_changed)
            except Exception:
                log.debug("_on_closed: ignored", exc_info=True)
            self._find_dialog = None

        self._find_dialog = dlg
        dlg.finished.connect(_on_closed)
        dlg.setModal(False)  # keep the editor reachable while searching
        dlg.show()
        # Shift 200 px left of the default (parent-centred) position so the
        # window covers less of the editor text it is searching.
        dlg.move(dlg.x() - 200, dlg.y())
        find_edit.setFocus()

    def find_next(self):
        """Find the next occurrence of the last searched text (opens Find if none)."""
        text = getattr(self, "_last_search", "")
        if text:
            if not self._find_in_editor(text) and self._find_dialog is not None:
                self._find_dialog._status.setText(f"'{text}' not found")
        else:
            self.find_text()

    def find_previous(self):
        """Find the previous occurrence of the last searched text (backwards, wraps)."""
        text = getattr(self, "_last_search", "")
        if text:
            if not self._find_in_editor(text, backward=True) \
                    and self._find_dialog is not None:
                self._find_dialog._status.setText(f"'{text}' not found")
        else:
            self.find_text()

    def _find_in_editor(self, text, backward=False):
        """Search from the cursor (forward, or backward with ``backward=True``);
        wrap around if not found. Returns bool. A match inside a folded section
        unfolds that section (reveal_cursor)."""
        flags = QTextDocument.FindFlag.FindBackward if backward \
            else QTextDocument.FindFlags()
        if self.text_area.find(text, flags):
            self.text_area.reveal_cursor()
            return True
        # Wrap around: jump to the far end and search again
        cursor = self.text_area.textCursor()
        cursor.movePosition(QTextCursor.End if backward else QTextCursor.Start)
        self.text_area.setTextCursor(cursor)
        if self.text_area.find(text, flags):
            self.text_area.reveal_cursor()
            return True
        return False

    def replace_text(self):
        """Settings > Replace (Ctrl+H): the combined Find & Replace window,
        Replace tab (see _open_find_dialog)."""
        self._open_find_dialog(1)
