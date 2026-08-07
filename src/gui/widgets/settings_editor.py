"""
Plain-text settings editor (GUI_Improvement_Report §3.2).

QPlainTextEdit + QSyntaxHighlighter replaces the old HTML-in-QTextEdit pipeline:
the document IS the settings file at all times - saving is ``toPlainText()``,
there is no clean/reconstruct step and no ``[-]``/``[+]`` indicator text that
could leak into the saved file. Dirty tracking is the document's native
``modificationChanged``.

Folding hides a section's blocks (``QTextBlock.setVisible(False)``) without
removing them from the document, so folded sections are still saved, copied and
searched. Fold state is a set of section names (``folded_sections()`` /
``apply_folds()``); the line-number gutter draws the ▾/▸ markers and toggles a
section on click, and double-clicking a ``[SECTION]`` header line in the editor
toggles it too.
"""

import difflib

from PySide6.QtWidgets import QPlainTextEdit, QTextEdit
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import (
    QSyntaxHighlighter, QTextCharFormat, QColor, QFont, QTextCursor, QKeySequence,
    QTextBlockUserData, QTextFormat,
)

from src.gui.utils.gui_log import get_logger
from src.gui.utils import theme

log = get_logger("settings_editor")

# Whole-line background for lines changed since the last save/load (not yet saved).
# These module constants are the NORMAL-theme values (kept for tests/back-compat);
# the actual colours are read from the active theme (theme.qcolor) at paint time.
CHANGED_LINE_COLOR = QColor("#dcecff")
# Whole-line background for lines whose keyword (the part before '=') appears more
# than once in the file - CWatM flattens all sections into one binding dict, so a
# duplicate key means one value silently overrides the other. Drawn over the
# changed-line blue (a line can be both changed and a duplicate; red wins).
DUPLICATE_LINE_COLOR = QColor("#ff8f8f")   # stronger than the Check-settingsfile red


class _BlockMarks(QTextBlockUserData):
    """Per-line marks stored on a QTextBlock (moves with the block as text above
    it is inserted/deleted). Currently just the bookmark flag - the 'changed
    since save' highlight is derived by diffing against the saved baseline, so it
    needs no per-block storage."""

    def __init__(self):
        super().__init__()
        self.bookmark = False
        # True when this bookmark was added by Settings ▸ Check settingsfile (so Clear
        # checking can remove exactly those, leaving the user's own bookmarks).
        self.check = False


def is_section_header(text):
    """True if the line is an INI section header like ``[OPTIONS]``."""
    s = text.strip()
    return len(s) > 2 and s.startswith('[') and s.endswith(']')


class IniHighlighter(QSyntaxHighlighter):
    """Colours the settings file like the old HTML formatting did: section
    headers bold, ``#`` comments dark gray, True blue / False red values."""

    def __init__(self, document):
        super().__init__(document)
        self._build_formats()

    def _build_formats(self):
        """(Re)create the char formats from the active theme's colours."""
        self._section = QTextCharFormat()
        self._section.setFontWeight(QFont.Bold)
        self._comment = QTextCharFormat()
        self._comment.setForeground(theme.qcolor("ini_comment"))
        self._true = QTextCharFormat()
        self._true.setForeground(theme.qcolor("ini_true"))
        self._false = QTextCharFormat()
        self._false.setForeground(theme.qcolor("ini_false"))

    def retheme(self):
        """Refresh the format colours from the (changed) theme and re-highlight."""
        self._build_formats()
        self.rehighlight()

    def highlightBlock(self, text):
        stripped = text.strip()
        if stripped.startswith('#') or stripped.startswith(';'):
            self.setFormat(0, len(text), self._comment)
            return
        if is_section_header(text):
            self.setFormat(0, len(text), self._section)
            return
        eq = text.find('=')
        if eq > 0:
            value = text[eq + 1:]
            vs = value.strip().lower()
            if vs in ('true', 'false'):
                start = eq + 1 + (len(value) - len(value.lstrip()))
                self.setFormat(start, len(value.strip()),
                               self._true if vs == 'true' else self._false)


class SettingsEditor(QPlainTextEdit):
    """The settings (.ini) editor: plain-text document + section folding."""

    foldingChanged = Signal()  # fold state changed (gutter repaints)
    undoRedoPerformed = Signal()  # an undo or redo just ran (fields must re-sync)
    bookmarksChanged = Signal()  # bookmark set changed (gutter repaints)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._folded = set()   # section names currently folded
        # Section names locked by the experience level (Beginner/Advanced): fully
        # hidden (header + content) and non-unfoldable. Expert = empty set.
        self._locked_sections = set()
        self._highlighter = IniHighlighter(self.document())
        # Baseline text at the last load/save; lines differing from it are drawn
        # with a light-blue background (changed but not yet saved).
        self._saved_text = ""
        # Recompute the changed-line highlight a touch after edits (debounced so
        # fast typing does not re-diff on every keystroke).
        self._change_timer = QTimer(self)
        self._change_timer.setSingleShot(True)
        self._change_timer.setInterval(120)
        self._change_timer.timeout.connect(self._recompute_change_highlights)
        self.textChanged.connect(self._change_timer.start)
        # Configure ▸ Bookmark Change: when on, a changed line is auto-bookmarked
        # (unless a bookmark already sits 1-2 lines above/below).
        self._auto_bookmark_changed = False
        # Rows flagged red by Settings ▸ Check settingsfile (missing-file values).
        self._error_rows = set()
        # Rows dimmed orange by Check settingsfile: missing files in a section whose
        # gating [OPTIONS] switch is off (not important, no bookmark).
        self._inactive_rows = set()
        # Rows drawn a clear orange by Check settingsfile: the named file does not
        # exist with the written extension, but the same base name DOES exist with a
        # different known raster extension (e.g. .map written, .nc on disk). A likely
        # wrong-extension typo, not a hard miss -> orange, NO bookmark.
        self._wrongext_rows = set()
        # Rows drawn light-gray as alignment filler (Compare settings padding).
        self._filler_rows = set()
        # Rows drawn orange as a difference (Compare settings).
        self._diff_rows = set()
        # Row(s) of the currently jumped-to difference (darker orange).
        self._current_diff_rows = set()
        # Block number of the most recent edit (Settings ▸ Goto last change, F3).
        self._last_change_block = -1
        self.document().contentsChange.connect(self._on_contents_change)

    # -------------------------------------------------------------- bookmarks
    def _block_marks(self, block, create=False):
        """Return the _BlockMarks for a block (creating one if asked)."""
        data = block.userData()
        if isinstance(data, _BlockMarks):
            return data
        if not create:
            return None
        data = _BlockMarks()
        block.setUserData(data)
        return data

    def is_bookmarked(self, block):
        data = self._block_marks(block)
        return bool(data and data.bookmark)

    def toggle_bookmark(self):
        """Toggle a bookmark on the line the cursor is in."""
        self.toggle_bookmark_block(self.textCursor().block())

    def toggle_bookmark_block(self, block):
        """Toggle a bookmark on ``block`` (used by the menu action via
        toggle_bookmark and by clicking the line's number in the gutter)."""
        if block is None or not block.isValid():
            return
        data = self._block_marks(block, create=True)
        data.bookmark = not data.bookmark
        self.bookmarksChanged.emit()

    def bookmark_rows(self, rows):
        """Bookmark each given row for a Check settingsfile result. A bookmark this
        call newly adds is tagged **check-owned** so ``clear_checking`` can remove
        exactly those (a line the user had already bookmarked stays theirs)."""
        doc = self.document()
        changed = False
        for r in rows:
            block = doc.findBlockByNumber(int(r))
            if block.isValid():
                data = self._block_marks(block, create=True)
                if not data.bookmark:
                    data.bookmark = True
                    data.check = True
                    changed = True
        if changed:
            self.bookmarksChanged.emit()

    def set_error_rows(self, rows):
        """Mark these row numbers with a red 'missing file' background and repaint
        (Settings ▸ Check settingsfile). Pass an empty set to clear."""
        self._error_rows = set(int(r) for r in rows)
        self._recompute_change_highlights()

    def set_inactive_rows(self, rows):
        """Mark these row numbers with a very dimmed orange background (Check
        settingsfile: missing file in a section whose [OPTIONS] switch is off -
        not important). Pass an empty set to clear."""
        self._inactive_rows = set(int(r) for r in rows)
        self._recompute_change_highlights()

    def set_wrongext_rows(self, rows):
        """Mark these row numbers with a clear orange background (Check settingsfile:
        the file exists but with a different extension than written). No bookmark.
        Pass an empty set to clear."""
        self._wrongext_rows = set(int(r) for r in rows)
        self._recompute_change_highlights()

    def set_filler_rows(self, rows):
        """Mark these row numbers with a light-gray background (Compare settings
        alignment filler). Pass an empty set to clear."""
        self._filler_rows = set(int(r) for r in rows)
        self._recompute_change_highlights()

    def set_diff_rows(self, rows):
        """Mark these row numbers with an orange background (Compare settings
        differing lines). Pass an empty set to clear."""
        self._diff_rows = set(int(r) for r in rows)
        self._recompute_change_highlights()

    def set_current_diff_rows(self, rows):
        """Mark these row numbers with a **darker** orange background (the Compare
        settings difference you just jumped to). Pass an empty set to clear."""
        self._current_diff_rows = set(int(r) for r in rows)
        self._recompute_change_highlights()

    def clear_checking(self):
        """Settings ▸ Clear checking: remove the red missing-file marks and the bookmarks
        that Check settingsfile added (the user's own bookmarks are left untouched)."""
        self._error_rows = set()
        self._inactive_rows = set()
        self._wrongext_rows = set()
        doc = self.document()
        block = doc.begin()
        changed = False
        while block.isValid():
            data = self._block_marks(block)
            if data and getattr(data, "check", False):
                if data.bookmark:
                    data.bookmark = False
                    changed = True
                data.check = False
            block = block.next()
        self._recompute_change_highlights()   # repaint without the red
        if changed:
            self.bookmarksChanged.emit()

    def clear_bookmarks(self):
        """Remove every bookmark."""
        doc = self.document()
        block = doc.begin()
        changed = False
        while block.isValid():
            data = self._block_marks(block)
            if data and data.bookmark:
                data.bookmark = False
                changed = True
            block = block.next()
        if changed:
            self.bookmarksChanged.emit()

    def _bookmarked_block_numbers(self):
        nums = []
        doc = self.document()
        block = doc.begin()
        while block.isValid():
            if self.is_bookmarked(block):
                nums.append(block.blockNumber())
            block = block.next()
        return nums

    def goto_next_bookmark(self, forward=True):
        """Move the cursor to the next/previous bookmarked line (wrapping). Unfolds
        the target's section if it is hidden. No-op if there are no bookmarks."""
        nums = self._bookmarked_block_numbers()
        if not nums:
            return False
        current = self.textCursor().blockNumber()
        if forward:
            target = next((n for n in nums if n > current), nums[0])
        else:
            target = next((n for n in reversed(nums) if n < current), nums[-1])
        block = self.document().findBlockByNumber(target)
        if not block.isValid():
            return False
        cursor = self.textCursor()
        cursor.setPosition(block.position())
        self.setTextCursor(cursor)
        self.reveal_cursor()
        self.centerCursor()
        return True

    def set_auto_bookmark_changed(self, on):
        """Configure ▸ Bookmark Change: when ``on``, changed lines are
        auto-bookmarked. Turning it on bookmarks the lines already changed."""
        self._auto_bookmark_changed = bool(on)
        if self._auto_bookmark_changed:
            self._recompute_change_highlights()

    def _auto_bookmark_changed_rows(self, changed_rows):
        """Bookmark every changed row, but skip a row if a bookmark already sits on
        any line 1 or 2 rows above/below it (keeps bookmarks spaced out). Bookmarks
        added earlier in the pass count, so adjacent changed lines get a single mark."""
        doc = self.document()
        added = False
        for row in sorted(changed_rows):
            block = doc.findBlockByNumber(row)
            if not block.isValid() or self.is_bookmarked(block):
                continue
            near = False
            for d in (-2, -1, 1, 2):
                nb = doc.findBlockByNumber(row + d)
                if nb.isValid() and self.is_bookmarked(nb):
                    near = True
                    break
            if near:
                continue
            self._block_marks(block, create=True).bookmark = True
            added = True
        if added:
            self.bookmarksChanged.emit()

    def _on_contents_change(self, position, removed, added):
        """Remember where the last edit happened (Goto last change / F3)."""
        try:
            self._last_change_block = self.document().findBlock(position).blockNumber()
        except Exception:
            pass

    def goto_last_change(self):
        """Move the cursor to the most recently edited line (unfold if hidden).
        Falls back to the bottom-most line that differs from the saved baseline."""
        target = self._last_change_block
        doc = self.document()
        if target < 0 or not doc.findBlockByNumber(target).isValid():
            new_lines = self.toPlainText().split('\n')
            old_lines = self._saved_text.split('\n')
            sm = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
            rows = [j2 - 1 for tag, _i1, _i2, j1, j2 in sm.get_opcodes()
                    if tag in ('replace', 'insert')]
            if not rows:
                return False
            target = max(rows)
        block = doc.findBlockByNumber(target)
        if not block.isValid():
            return False
        cursor = self.textCursor()
        cursor.setPosition(block.position())
        self.setTextCursor(cursor)
        self.reveal_cursor()
        self.centerCursor()
        return True

    # ------------------------------------------------ changed-line highlight
    @staticmethod
    def _duplicate_key_rows(lines):
        """Row numbers of every ``key = value`` line whose key (case-insensitive)
        appears more than once. Matches CWatM's parsing (configuration.py):
        ``out_*`` keys are stored PER SECTION (``outDir[sec]`` / ``outTss[sec_opt]``),
        so those only count as duplicates within the same section; every other key
        goes into the flat ``binding`` dict, so a repeat ANYWHERE in the file
        silently overrides the earlier value and is flagged. Comments, section
        headers and lines without '=' are ignored."""
        rows_by_key = {}
        section = ""
        for row, line in enumerate(lines):
            s = line.strip()
            if not s or s.startswith('#') or s.startswith(';'):
                continue
            if is_section_header(s):
                section = s.lower()
                continue
            eq = s.find('=')
            if eq <= 0:
                continue
            key = s[:eq].strip().lower()
            if not key:
                continue
            if key.startswith('out_'):
                key = section + '|' + key   # per-section, like outDir/outTss/outMap
            rows_by_key.setdefault(key, []).append(row)
        dup_rows = set()
        for rows in rows_by_key.values():
            if len(rows) > 1:
                dup_rows.update(rows)
        return dup_rows

    def _recompute_change_highlights(self):
        """Paint full-width line backgrounds via extra selections:
        - light blue on every line that differs from the saved baseline (added or
          modified; cleared when the text matches the baseline again, i.e. right
          after a save/load);
        - light red on every line whose keyword appears more than once in the
          file (duplicate keys silently override each other in CWatM). Red is
          painted after blue, so it wins when a line is both."""
        try:
            new_lines = self.toPlainText().split('\n')
            old_lines = self._saved_text.split('\n')
            changed_rows = set()
            sm = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
            for tag, _i1, _i2, j1, j2 in sm.get_opcodes():
                if tag in ('replace', 'insert'):
                    changed_rows.update(range(j1, j2))
            dup_rows = self._duplicate_key_rows(new_lines)

            selections = []
            doc = self.document()

            def _add(rows, color):
                """Append extra selections painting `rows` with `color`.

                Contiguous rows are merged into ONE selection spanning the whole run:
                FullWidthSelection paints every line the cursor covers edge-to-edge,
                so a multi-block cursor renders the same as the per-row selections it
                replaces, while Qt re-scans a far shorter extra-selection list on every
                viewport paint. Matters most in Compare settings, where diff+filler rows
                can cover most of both panes - hundreds of selections collapse to tens
                (report §4.3).

                Merging happens WITHIN a category only: the documented colour priority
                (changed < error < duplicate < diff < filler < current-diff) relies on
                later categories being appended after earlier ones.
                """
                if not rows:
                    return
                fmt = QTextCharFormat()
                fmt.setBackground(color)
                fmt.setProperty(QTextFormat.FullWidthSelection, True)
                sorted_rows = sorted(rows)
                runs = []                      # [(first_row, last_row), ...]
                start = prev = sorted_rows[0]
                for row in sorted_rows[1:]:
                    if row == prev + 1:
                        prev = row
                        continue
                    runs.append((start, prev))
                    start = prev = row
                runs.append((start, prev))
                for first, last in runs:
                    b0 = doc.findBlockByNumber(first)
                    if not b0.isValid():
                        continue
                    b1 = doc.findBlockByNumber(last)
                    if not b1.isValid():
                        b1 = b0
                    sel = QTextEdit.ExtraSelection()
                    sel.format = fmt
                    cur = QTextCursor(b0)
                    if b1.blockNumber() > b0.blockNumber():
                        # extend to the end of the last block in the run
                        cur.setPosition(b1.position() + b1.length() - 1,
                                        QTextCursor.KeepAnchor)
                    else:
                        cur.clearSelection()
                    sel.cursor = cur
                    selections.append(sel)

            # Priority (later wins): changed (blue) < inactive-section missing file
            # (very dimmed orange, not important) < missing-file (light red) <
            # duplicate key (STRONG red). A duplicate key is the most serious, so it is
            # drawn last and its stronger red stands out from the check-settingsfile red.
            _add((changed_rows - dup_rows) - self._error_rows - self._inactive_rows
                 - self._wrongext_rows,
                 theme.qcolor("changed_line"))
            _add((self._inactive_rows - dup_rows) - self._error_rows
                 - self._wrongext_rows,
                 theme.qcolor("inactive_line"))
            # Wrong-extension (clear orange): above dimmed inactive, below missing red.
            _add((self._wrongext_rows - dup_rows) - self._error_rows,
                 theme.qcolor("wrongext_line"))
            _add(self._error_rows - dup_rows, theme.qcolor("error_line"))
            _add(dup_rows, theme.qcolor("duplicate_line"))
            # Compare settings: differing lines orange, alignment filler light-gray
            # (disjoint rows), drawn last so the compare colours win in that window;
            # the currently jumped-to difference is a darker orange on top of both.
            _add(self._diff_rows, theme.qcolor("diff_line"))
            _add(self._filler_rows, theme.qcolor("filler_line"))
            _add(self._current_diff_rows, theme.qcolor("current_diff_line"))
            self.setExtraSelections(selections)
            if self._auto_bookmark_changed and changed_rows:
                self._auto_bookmark_changed_rows(changed_rows)
        except Exception:
            log.debug("changed-line highlight failed", exc_info=True)

    def load_text(self, text):
        """Set the document to ``text`` as the SAVED baseline (used on file
        load/reload): clears folds, bookmarks and the changed-line highlight, and
        resets the undo stack (setPlainText) so you cannot undo past a load."""
        self._folded.clear()
        self._error_rows = set()   # a fresh file clears any Check-settingsfile flags
        self._inactive_rows = set()  # and the dimmed inactive-section marks
        self._wrongext_rows = set()  # and the wrong-extension orange marks
        self._filler_rows = set()  # and any Compare-settings alignment filler
        self._diff_rows = set()    # and any Compare-settings diff marks
        self._current_diff_rows = set()
        self._saved_text = text
        self.setPlainText(text)   # recreates blocks -> bookmarks/marks cleared
        self._last_change_block = -1   # a fresh load is not a "change" to jump to
        self._recompute_change_highlights()
        # Note: the experience-level lock is re-applied by the main window after a
        # load (it recomputes the locked set from the freshly loaded sections).
        self.foldingChanged.emit()
        self.bookmarksChanged.emit()

    def mark_saved(self):
        """Make the current text the saved baseline (called after Save), so the
        changed-line highlight clears. Bookmarks are kept."""
        self._saved_text = self.toPlainText()
        self._recompute_change_highlights()

    def retheme(self):
        """Re-apply all theme-dependent colours (syntax highlighting and the
        changed/duplicate line backgrounds) after a mode switch."""
        self._highlighter.retheme()
        self._recompute_change_highlights()

    # ------------------------------------------------------------- undo / redo
    # Field auto-apply / add-watercycle / Options toggles edit the document (via
    # set_content_preserving) as undoable steps, so undo/redo revert them - but
    # the left-window field WIDGETS are derived from the text and must be
    # re-synced afterwards. Routing every undo/redo through these overrides (and
    # emitting undoRedoPerformed) lets the main window do that for BOTH triggers:
    # the Settings-menu actions (which call self.undo()/redo()) and the editor's
    # own Ctrl+Z/Ctrl+Y (handled in keyPressEvent below, since QPlainTextEdit's
    # built-in key handling bypasses the public slots).
    def undo(self):
        super().undo()
        self.reveal_cursor()
        self.undoRedoPerformed.emit()

    def redo(self):
        super().redo()
        self.reveal_cursor()
        self.undoRedoPerformed.emit()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Undo):
            self.undo()
            event.accept()
            return
        if event.matches(QKeySequence.Redo):
            self.redo()
            event.accept()
            return
        super().keyPressEvent(event)

    # ---------------------------------------------------------------- folding
    def _section_spans(self):
        """[(name, header_block_no, last_block_no)] for every section, where the
        span covers the section's content up to (not including) the next header."""
        spans = []
        doc = self.document()
        block = doc.begin()
        current = None  # (name, header_no)
        last_no = -1
        while block.isValid():
            if is_section_header(block.text()):
                if current is not None:
                    spans.append((current[0], current[1], block.blockNumber() - 1))
                current = (block.text().strip(), block.blockNumber())
            last_no = block.blockNumber()
            block = block.next()
        if current is not None:
            spans.append((current[0], current[1], last_no))
        return spans

    def section_names(self):
        """All section names in document order."""
        return [name for name, _s, _e in self._section_spans()]

    def folded_sections(self):
        """Set of currently folded section names (pruned to existing sections)."""
        existing = set(self.section_names())
        self._folded &= existing
        return set(self._folded)

    def is_folded(self, name):
        return name in self._folded

    def is_locked(self, name):
        """True if ``name`` is locked by the experience level (fully hidden)."""
        return name in self._locked_sections

    def set_locked_sections(self, names):
        """Set the sections locked by the experience level: locked sections are
        **fully hidden** - both the ``[SECTION]`` header line and all its content
        blocks are made invisible (still saved/searched, just not shown). Unlocked
        sections are restored to visible, honouring the user's own fold state
        (a user-folded section keeps its header visible + content hidden). Passing
        an empty set (Expert) shows everything. Locked blocks are never counted as
        'folded' - ``_folded`` stays the user's own fold set."""
        self._locked_sections = set(names) & set(self.section_names())
        doc = self.document()
        changed = False
        for sec, start, end in self._section_spans():
            if sec in self._locked_sections:
                # Hide the whole section (header + content).
                for n in range(start, end + 1):
                    blk = doc.findBlockByNumber(n)
                    if blk.isValid() and blk.isVisible():
                        blk.setVisible(False)
                        changed = True
            else:
                # Unlocked: header always visible; content visible unless the user
                # folded this section normally.
                folded = sec in self._folded
                for n in range(start, end + 1):
                    blk = doc.findBlockByNumber(n)
                    if not blk.isValid():
                        continue
                    want = True if n == start else (not folded)
                    if blk.isVisible() != want:
                        blk.setVisible(want)
                        changed = True
        if changed:
            self._folds_updated()
        else:
            self.foldingChanged.emit()

    def toggle_section(self, name):
        # A locked section is hidden entirely - never let it be toggled open.
        if name in self._locked_sections:
            return
        self._set_folded(name, name not in self._folded)

    def fold_all(self):
        self.apply_folds(set(self.section_names()))

    def unfold_all(self):
        # Unfold every (non-locked) section; locked sections stay fully hidden.
        self.apply_folds(set())

    def apply_folds(self, names):
        """Make exactly ``names`` the folded sections (others unfolded).
        Experience-level **locked** sections are skipped entirely - they stay
        fully hidden (managed by ``set_locked_sections``) and are never counted
        as 'folded'."""
        names = set(names) - self._locked_sections
        doc = self.document()
        changed = False
        for sec, start, end in self._section_spans():
            if sec in self._locked_sections:
                continue  # fully hidden, not part of the fold set
            fold = sec in names
            for n in range(start + 1, end + 1):
                blk = doc.findBlockByNumber(n)
                if blk.isValid() and blk.isVisible() == fold:
                    blk.setVisible(not fold)
                    changed = True
        self._folded = names & set(self.section_names())
        if changed:
            self._folds_updated()

    def _set_folded(self, name, fold):
        doc = self.document()
        changed = False
        for sec, start, end in self._section_spans():
            if sec != name:
                continue
            for n in range(start + 1, end + 1):
                blk = doc.findBlockByNumber(n)
                if blk.isValid() and blk.isVisible() == fold:
                    blk.setVisible(not fold)
                    changed = True
        if fold:
            self._folded.add(name)
        else:
            self._folded.discard(name)
        if changed:
            self._folds_updated()

    def _folds_updated(self):
        """Force the layout/scrollbar to account for the changed block visibility,
        and move the cursor out of a now-hidden block."""
        cursor = self.textCursor()
        if not cursor.block().isVisible():
            block = cursor.block()
            while block.isValid() and not block.isVisible():
                block = block.previous()
            if block.isValid():
                cursor.setPosition(block.position())
                self.setTextCursor(cursor)
        doc = self.document()
        doc.markContentsDirty(0, doc.characterCount())
        # QPlainTextEdit caches the document size - nudge it to recompute so the
        # scrollbar range matches the visible blocks.
        layout = doc.documentLayout()
        try:
            layout.documentSizeChanged.emit(layout.documentSize())
        except Exception:
            log.debug("documentSizeChanged nudge failed", exc_info=True)
        self.viewport().update()
        self.foldingChanged.emit()

    def reveal_cursor(self):
        """If the cursor sits in a folded (hidden) block, unfold its section."""
        block = self.textCursor().block()
        if block.isVisible():
            return
        no = block.blockNumber()
        for sec, start, end in self._section_spans():
            # Never unfold a locked section (experience level keeps it hidden).
            if start < no <= end and sec in self._folded \
                    and sec not in self._locked_sections:
                self._set_folded(sec, False)
        self.ensureCursorVisible()

    def toggle_block_section(self, block):
        """Toggle the fold of the section whose HEADER is ``block`` (used by the
        gutter's fold-marker click). No-op for non-header blocks."""
        if block.isValid() and is_section_header(block.text()):
            self.toggle_section(block.text().strip())

    def mouseDoubleClickEvent(self, event):
        """Double-clicking a section header line toggles its fold (single click
        still just places the cursor, so headers stay editable)."""
        cursor = self.cursorForPosition(event.pos())
        if is_section_header(cursor.block().text()):
            self.toggle_block_section(cursor.block())
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------- content replacing
    def set_content_preserving(self, text):
        """Replace the document content while preserving scroll position, folding
        and - crucially - the **undo history**, so a programmatic change (a
        field auto-apply, add-watercycle, an Options toggle) is a single
        undoable step rather than something that wipes the stack.

        Both branches edit through a single ``beginEditBlock`` so undo reverts
        the whole change at once. The same-line-count branch touches only the
        lines that differ (cheap, keeps the cursor near the edit); the
        different-line-count branch replaces the whole document in place (still
        one undo step - never ``setPlainText``, which would clear the stack)."""
        old = self.toPlainText()
        if old == text:
            return
        old_lines = old.split('\n')
        new_lines = text.split('\n')
        if len(old_lines) == len(new_lines):
            doc = self.document()
            cursor = QTextCursor(doc)
            cursor.beginEditBlock()
            try:
                for i, (o, n) in enumerate(zip(old_lines, new_lines)):
                    if o == n:
                        continue
                    block = doc.findBlockByNumber(i)
                    cursor.setPosition(block.position())
                    cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                    cursor.insertText(n)
            finally:
                cursor.endEditBlock()
            return
        # Different line count: replace the whole document in ONE undoable edit
        # (select-all + insert), then restore folds / scroll / cursor.
        folds = self.folded_sections()
        scroll = self.verticalScrollBar().value()
        line = self.textCursor().blockNumber()
        cursor = self.textCursor()
        cursor.beginEditBlock()
        cursor.select(QTextCursor.Document)
        cursor.insertText(text)
        cursor.endEditBlock()
        self.apply_folds(folds)
        # The whole document was re-inserted (all blocks visible again) - re-hide
        # the experience-level locked sections.
        if self._locked_sections:
            self.set_locked_sections(self._locked_sections)
        block = self.document().findBlockByNumber(min(line, self.blockCount() - 1))
        cursor = self.textCursor()
        cursor.setPosition(block.position())
        self.setTextCursor(cursor)
        QTimer.singleShot(0, lambda sb=self.verticalScrollBar(), v=scroll: sb.setValue(v))
