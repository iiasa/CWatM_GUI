"""Settings-file tabs for the main window.

Several settings files can be open at once, one per **tab** in the bar that sits
below the button row and above the editor. Each tab owns its own
``SettingsEditor`` + ``LineNumberGutter`` page inside a ``QStackedWidget``, so a
tab keeps its own undo stack, bookmarks, folds, changed-line highlights and
Check-settingsfile marks without any of that having to be swapped in and out of
a single widget.

**The active tab is the application state.** Rather than teach every feature
about tabs, switching one re-points the attributes the whole main window already
works through - ``text_area``, ``line_number_gutter``, ``text_display``,
``file_manager.current_file_path``, ``original_content``, ``_clean_content``,
``_is_dirty``, ``_filename_state``, ``_working_dir_override``, the mask cache -
and then refreshes the shared left panel exactly the way a load does. Everything
that reads ``file_manager.get_current_file_path()`` (RUN CWATM, Compare
settings, the Excel editor, Check Data, Show Basin, Output Explorer) therefore
follows the active tab with no change of its own.

Per tab: file path, content, undo/bookmarks/folds, dirty flag, labels, working
directory, gauge/mask cache, field baseline.
Global, and therefore fanned out to *every* tab when they change: the colour
theme, the editor font + size, the skill level's locked sections and
Bookmark-Change.
"""

import difflib
import os
import re

from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QTabBar,
                               QStackedWidget, QMenu, QMessageBox, QToolButton)
from PySide6.QtCore import Qt

from src.gui.managers.text_display import TextDisplayManager
from src.gui.utils import theme
from src.gui.utils.gui_log import get_logger
from src.gui.widgets.line_number_gutter import LineNumberGutter
from src.gui.widgets.settings_editor import SettingsEditor

log = get_logger("tab_manager")

UNTITLED = "untitled"


class HoverCloseTabBar(QTabBar):
    """A tab bar whose close button appears only on the tab under the mouse.

    ``setTabsClosable(True)`` alone puts an ✕ on *every* tab permanently, which is
    noisy for a bar that usually holds one or two files. The buttons are created
    as usual (so the tab widths never jump) but hidden, and only the hovered one
    is shown."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabsClosable(True)
        self.setMouseTracking(True)
        self._hovered = -1

    # Buttons are (re)created by Qt whenever the tab set changes.
    def tabInserted(self, index):
        super().tabInserted(index)
        self._update_close_buttons()

    def tabRemoved(self, index):
        super().tabRemoved(index)
        self._update_close_buttons()

    def mouseMoveEvent(self, event):
        try:
            pos = event.position().toPoint()
        except AttributeError:      # Qt5-style event
            pos = event.pos()
        index = self.tabAt(pos)
        if index != self._hovered:
            self._hovered = index
            self._update_close_buttons()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hovered != -1:
            self._hovered = -1
            self._update_close_buttons()
        super().leaveEvent(event)

    def _update_close_buttons(self):
        for i in range(self.count()):
            for side in (QTabBar.RightSide, QTabBar.LeftSide):
                button = self.tabButton(i, side)
                if button is not None:
                    button.setVisible(i == self._hovered)


def same_file(a, b):
    """Whether two paths mean the same file (absolute, case-insensitive on
    Windows). Used to keep one settings file out of two tabs."""
    if not a or not b:
        return False
    try:
        return (os.path.normcase(os.path.abspath(a))
                == os.path.normcase(os.path.abspath(b)))
    except Exception:
        return False


def diff_line_rows(a_lines, b_lines):
    """The 0-based rows that differ between two line lists, per side.

    Used by Settings ▸ Compare Tab (F8). Unlike the Compare settings window this
    inserts **no filler**: the rows are marked in the real documents, so they have
    to stay the documents' own line numbers."""
    a_rows, b_rows = set(), set()
    sm = difflib.SequenceMatcher(a=a_lines, b=b_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        a_rows.update(range(i1, i2))
        b_rows.update(range(j1, j2))
    return sorted(a_rows), sorted(b_rows)


def next_copy_path(path):
    """The file name *Copy Tab* writes next to `path`.

    ``settings.ini`` -> ``settings_2.ini``, ``settings_2.ini`` ->
    ``settings_3.ini``; a name that is already taken is skipped, so copying
    twice never overwrites the first copy.
    """
    folder, name = os.path.split(os.path.abspath(path))
    stem, ext = os.path.splitext(name)
    m = re.match(r"^(.*)_(\d+)$", stem)
    if m:
        base, n = m.group(1), int(m.group(2)) + 1
    else:
        base, n = stem, 2
    while True:
        candidate = os.path.join(folder, f"{base}_{n}{ext}")
        if not os.path.exists(candidate):
            return candidate
        n += 1


class SettingsTab:
    """One open settings file: its editor page plus the main-window state that
    belongs to it rather than to the window (see the module docstring)."""

    def __init__(self, page, editor, gutter, display):
        self.page = page
        self.editor = editor
        self.gutter = gutter
        self.display = display
        # --- state mirrored to/from the main window on every tab switch
        self.file_path = None
        self.original_content = ""
        self.clean_content = ""
        self.is_dirty = False
        self.file_parsed = False
        self.filename_state = "none"
        self.filename_text = "No file loaded"
        self.title_text = ""
        self.working_dir_override = None
        self.baseline_fields = {}
        self.pathout_warning = ""
        self.mask_context = None
        self.mask_context_key = None
        self.mask_context_built = False
        # Scroll this tab together with the one BEFORE it (tab menu ▸ Link
        # scrolling). Meaningless on the first tab, which has no predecessor.
        self.link_scroll = False

    def label(self):
        """Tab caption: the file name (or 'untitled'), '*' while unsaved."""
        name = os.path.basename(self.file_path) if self.file_path else UNTITLED
        return f"*{name}" if self.is_dirty else name


class SettingsTabsMixin:
    """Tab bar, editor stack and everything that switches between them."""

    # ------------------------------------------------------------- building
    def _create_editor_page(self):
        """One tab's page: the line-number gutter + a SettingsEditor, wired up
        exactly like the single editor was before tabs existed.

        Every new tab starts from the *current* global settings (theme, font,
        Bookmark-Change) - the level's locked sections are applied when content
        arrives, by parse_file -> _apply_experience_level."""
        editor = SettingsEditor()
        editor.setPlaceholderText("Configuration content will appear here...")
        editor.setReadOnly(False)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        editor.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # Colour Save / Save As blue when the document has unsaved edits
        editor.document().modificationChanged.connect(self._on_doc_modified)
        # Keep the in-memory settings content (self.original_content) in sync with
        # the live document on every edit - the document IS the settings file, so
        # field-apply / gauge / PathOut / Show Basin must use the user's current
        # text (including manual typing), never a stale snapshot.
        editor.textChanged.connect(self._on_editor_text_changed)
        # After an undo/redo, re-sync the left-window fields from the reverted text
        editor.undoRedoPerformed.connect(self._sync_fields_from_editor)
        editor.setStyleSheet(self._editor_style())
        try:
            editor.set_auto_bookmark_changed(
                bool(self._settings.value("editor/bookmark_change", False, type=bool)))
        except Exception:
            log.debug("bookmark-change state not applied to new tab", exc_info=True)

        page = QWidget()
        row = QHBoxLayout(page)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        gutter = LineNumberGutter(editor)
        row.addWidget(gutter)
        row.addWidget(editor, 1)

        # Enable mouse interaction for links; the widget-level filter also handles
        # the metaNetcdf hover tooltips (QEvent.ToolTip). eventFilter tests against
        # self.text_area, i.e. only the ACTIVE tab's editor answers.
        editor.viewport().installEventFilter(self)
        editor.installEventFilter(self)
        editor.setMouseTracking(True)

        tab = SettingsTab(page, editor, gutter, TextDisplayManager(editor))
        # Tab menu ▸ Link scrolling: mirror the scroll position and the folded
        # sections onto the linked tab(s)
        editor.verticalScrollBar().valueChanged.connect(
            lambda value, t=tab: self._on_editor_scrolled(t, value))
        editor.foldingChanged.connect(lambda t=tab: self._on_editor_folding(t))
        return tab

    def build_settings_tabs(self, layout):
        """Create the tab bar + editor stack and the first (empty) tab, and add
        both to `layout` (the right panel, below the button row)."""
        self.settings_tab_bar = HoverCloseTabBar()
        self.settings_tab_bar.setExpanding(False)
        self.settings_tab_bar.setDrawBase(False)
        self.settings_tab_bar.setMovable(True)
        self.settings_tab_bar.setUsesScrollButtons(True)
        self.settings_tab_bar.setContextMenuPolicy(Qt.CustomContextMenu)
        self.settings_tab_bar.customContextMenuRequested.connect(
            self._on_tab_context_menu)
        self.settings_tab_bar.currentChanged.connect(self._on_tab_changed)
        # A moved tab must keep its page/state: reorder self._tabs with it.
        self.settings_tab_bar.tabMoved.connect(self._on_tab_moved)
        # The ✕ that appears on the hovered tab closes it, like Delete Tab
        self.settings_tab_bar.tabCloseRequested.connect(self.close_settings_tab)
        # The tab bar and the small '+' tab that opens another empty tab share one
        # row, so the '+' always sits just right of the last tab (a QTabBar has no
        # corner widget of its own).
        self._tabs_row = QWidget()
        row = QHBoxLayout(self._tabs_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        row.addWidget(self.settings_tab_bar, 0, Qt.AlignBottom)
        self.add_tab_plus = QToolButton()
        self.add_tab_plus.setText("+")
        self.add_tab_plus.setToolTip("Open another, empty tab - load or drop a "
                                     "settings file into it")
        self.add_tab_plus.setFocusPolicy(Qt.NoFocus)
        self.add_tab_plus.setCursor(Qt.PointingHandCursor)
        self.add_tab_plus.setFixedWidth(26)
        self.add_tab_plus.clicked.connect(lambda: self.add_settings_tab(activate=True))
        row.addWidget(self.add_tab_plus, 0, Qt.AlignBottom)
        row.addStretch(1)
        self._style_tab_chrome()
        layout.addWidget(self._tabs_row)

        self.settings_stack = QStackedWidget()
        layout.addWidget(self.settings_stack, 1)

        self.add_settings_tab(activate=True, persist=False)
        # Re-style now that a tab exists: the '+' takes its height from a real tab
        self._style_tab_chrome()
        self.update_tabs_visible()

    # ------------------------------------------------------------ visibility
    def tabs_enabled(self):
        """Whether the tab bar is shown: Preferences ▸ Editor & Dates ▸ **Use Tabs**
        (default on) *and* the **Expert** skill level - tabs are an expert tool, and
        Beginner/Advanced keep the single-file window they know."""
        try:
            wanted = bool(self._settings.value("editor/use_tabs", True, type=bool))
        except Exception:
            wanted = True
        return wanted and getattr(self, "_experience_level", "Expert") == "Expert"

    def update_tabs_visible(self):
        """Show or hide the tab row (bar + '+' tab) for the current setting.

        Only the *chrome* is hidden - tabs that are already open keep their content
        and the active one stays in the editor, so switching the option off and on
        never loses work."""
        row = getattr(self, "_tabs_row", None)
        if row is not None:
            try:
                row.setVisible(self.tabs_enabled())
            except RuntimeError:
                log.debug("tab row gone while updating visibility", exc_info=True)

    def _style_tab_chrome(self):
        """(Re-)style the tab bar and the '+' tab from the active theme - called
        when they are built and again on every Mode switch (_retheme)."""
        try:
            self.settings_tab_bar.setStyleSheet(self._tab_bar_style())
            self.add_tab_plus.setStyleSheet(self._plus_tab_style())
            # Match the '+' to the height of a real tab, so the two line up.
            height = self.settings_tab_bar.sizeHint().height()
            if height > 0:
                self.add_tab_plus.setFixedHeight(max(20, height - 2))
        except (AttributeError, RuntimeError):
            log.debug("tab chrome styling skipped", exc_info=True)

    def _plus_tab_style(self):
        """The small '+' tab right of the last tab (theme tokens, tab-like).

        The size is in **pt** on purpose - a pixel font-size on a QToolButton leaves
        its QFont with pointSize() == -1, which is what makes Qt print
        "QFont::setPointSize: Point size <= 0 (-1)" to the console."""
        return f"""
            QToolButton {{
                background: {theme.c('surface_bg')};
                color: {theme.c('text_gray')};
                border: 1px solid {theme.c('border')};
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 11pt;
                font-weight: 700;
                padding-bottom: 2px;
            }}
            QToolButton:hover {{
                color: {theme.c('accent')};
                border-color: {theme.c('btn_hover_border')};
            }}
            QToolButton:pressed {{ background: {theme.c('editor_bg')}; }}
        """

    def _tab_bar_style(self):
        """Theme-token styling for the tab bar (never a hardcoded colour)."""
        return f"""
            QTabBar {{ background: transparent; }}
            QTabBar::tab {{
                background: {theme.c('surface_bg')};
                color: {theme.c('text')};
                border: 1px solid {theme.c('border')};
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                padding: 4px 12px;
                margin-right: 2px;
                font-size: 12px;
            }}
            QTabBar::tab:selected {{
                background: {theme.c('editor_bg')};
                color: {theme.c('accent')};
                font-weight: 600;
                border-color: {theme.c('editor_focus_border')};
            }}
            QTabBar::tab:hover {{ border-color: {theme.c('btn_hover_border')}; }}
        """

    # --------------------------------------------------------------- access
    def current_tab(self):
        """The active SettingsTab, or None before the tabs are built."""
        tabs = getattr(self, "_tabs", None)
        idx = getattr(self, "_active_tab_index", -1)
        if not tabs or not (0 <= idx < len(tabs)):
            return None
        return tabs[idx]

    def all_editors(self):
        """Every tab's editor - used by the theme / font / level fan-out."""
        return [t.editor for t in getattr(self, "_tabs", [])]

    # ------------------------------------------------------- add / activate
    def add_settings_tab(self, activate=True, persist=True):
        """Append a new empty tab (the `+` tab right of the last one)."""
        tab = self._create_editor_page()
        self._tabs.append(tab)
        self.settings_stack.addWidget(tab.page)
        blocked = self.settings_tab_bar.blockSignals(True)
        index = self.settings_tab_bar.addTab(tab.label())
        self.settings_tab_bar.setTabToolTip(index, "No file loaded")
        self.settings_tab_bar.blockSignals(blocked)
        if activate or self._active_tab_index < 0:
            self.switch_to_tab(index)
        if persist:
            self._persist_open_tabs()
        return index

    def switch_to_tab(self, index):
        """Make tab `index` the active one (stores the outgoing tab first)."""
        if not (0 <= index < len(self._tabs)) or self._switching_tabs:
            return
        self._switching_tabs = True
        try:
            self._store_active_tab()
            self._activate_tab(index)
        finally:
            self._switching_tabs = False
        blocked = self.settings_tab_bar.blockSignals(True)
        self.settings_tab_bar.setCurrentIndex(index)
        self.settings_tab_bar.blockSignals(blocked)

    def _on_tab_changed(self, index):
        """The user clicked another tab."""
        self.switch_to_tab(index)
        self._persist_open_tabs()

    def _on_tab_moved(self, frm, to):
        """Keep self._tabs (and the active index) in step with a dragged tab."""
        try:
            tab = self._tabs.pop(frm)
            self._tabs.insert(to, tab)
            self._active_tab_index = self.settings_tab_bar.currentIndex()
            self._normalize_links()
            self._persist_open_tabs()
        except Exception:
            log.warning("tab move bookkeeping failed", exc_info=True)

    def _store_active_tab(self):
        """Copy the main window's per-file state into the tab leaving focus.

        Any debounced field change is flushed first, so the tab's content is the
        authoritative text and the fields can simply be re-derived from it when
        the tab is entered again."""
        tab = self.current_tab()
        if tab is None:
            return
        try:
            self._flush_pending_field_changes()
        except Exception:
            log.debug("flushing field changes before tab switch failed", exc_info=True)
        tab.file_path = self.file_manager.get_current_file_path()
        tab.original_content = self.original_content
        tab.clean_content = getattr(self, "_clean_content", "")
        tab.is_dirty = bool(getattr(self, "_is_dirty", False))
        tab.file_parsed = bool(getattr(self, "file_parsed", False))
        tab.filename_state = getattr(self, "_filename_state", "none")
        tab.filename_text = self.filename_label.text() if self.filename_label else ""
        tab.title_text = self.title_label.text() if getattr(self, "title_label", None) else ""
        tab.working_dir_override = getattr(self, "_working_dir_override", None)
        tab.baseline_fields = dict(getattr(self, "_baseline_fields", {}) or {})
        tab.pathout_warning = getattr(self, "_pathout_warning", "")
        tab.mask_context = getattr(self, "_mask_context", None)
        tab.mask_context_key = getattr(self, "_mask_context_key", None)
        tab.mask_context_built = getattr(self, "_mask_context_built", False)

    def _activate_tab(self, index):
        """Point the main window at tab `index` and refresh everything shared."""
        tab = self._tabs[index]
        self._active_tab_index = index
        # --- the widgets the whole window works through
        self.text_area = tab.editor
        self.line_number_gutter = tab.gutter
        self.text_display = tab.display
        self.settings_stack.setCurrentWidget(tab.page)
        # --- the per-file state
        self.file_manager.current_file_path = tab.file_path
        self.original_content = tab.original_content
        self._clean_content = tab.clean_content
        self.file_parsed = tab.file_parsed
        self._filename_state = tab.filename_state
        self._working_dir_override = tab.working_dir_override
        self._baseline_fields = dict(tab.baseline_fields or {})
        self._pathout_warning = tab.pathout_warning
        self._mask_context = tab.mask_context
        self._mask_context_key = tab.mask_context_key
        self._mask_context_built = tab.mask_context_built

        # --- the shared left panel, refreshed the way a load does it
        self._suppress_dirty = True
        try:
            if getattr(self, "filename_label", None) is not None:
                self.filename_label.setText(tab.filename_text)
                self._apply_filename_state()
            if getattr(self, "title_label", None) is not None:
                self.title_label.setText(tab.title_text)
            # Relative paths in the settings file resolve against the working
            # directory, and so does the model child - follow the tab there.
            wd = self.working_dir()
            if wd and os.path.isdir(wd):
                try:
                    os.chdir(wd)
                except Exception:
                    log.warning("chdir on tab switch failed", exc_info=True)
            self._update_workdir_label(loaded=bool(tab.file_path))
            self._update_excel_menu_enabled(tab.original_content)
            # Dates / PathOut / MaskMap / Gauges come from this tab's content;
            # stale boxes would otherwise poison _live_content() and the next save.
            self._fill_fields_from_content(tab.original_content)
        except Exception:
            log.warning("tab activation refresh failed", exc_info=True)
        finally:
            self._suppress_dirty = False

        self._set_save_dirty(tab.is_dirty)
        self._update_changed_fields_hint()
        try:
            self._update_warnings(check_pathout=bool(tab.file_path))
        except Exception:
            log.warning("warnings refresh on tab switch failed", exc_info=True)
        try:
            self._refresh_check_settings_label()
        except Exception:
            log.debug("check-label refresh on tab switch failed", exc_info=True)
        if tab.file_path:
            self.set_cwatm_button_ready_state()
        # A run locks Save (it uses the file on disk) - keep it locked across a switch
        if getattr(self, "cwatm_running", False):
            try:
                self._set_tools_enabled(False)
            except Exception:
                log.debug("save lock not re-applied on tab switch", exc_info=True)
        self.line_number_gutter.update()

    def _fill_fields_from_content(self, content):
        """Refill the Date / PathOut / MaskMap / Gauges boxes from `content`
        (the caller sets _suppress_dirty). No-op while the left panel does not
        exist yet - the first tab is built during create_right_panel."""
        if getattr(self, "pathout_field", None) is None:
            return
        date_values, settings_values = self.config_parser.parse_content(content or "")
        self.date_manager.set_dates_from_config(date_values, self.config_parser)
        self.pathout_field.setText(settings_values.get('pathout', ""))
        self.maskmap_field.setText(settings_values.get('maskmap', ""))
        self.gauges_field.setText(settings_values.get('gauges', ""))

    # ------------------------------------------------------------- labels
    def refresh_tab_label(self, tab=None):
        """Re-caption a tab from its file name + dirty state."""
        tab = tab or self.current_tab()
        if tab is None:
            return
        try:
            index = self._tabs.index(tab)
        except ValueError:
            return
        try:
            self.settings_tab_bar.setTabText(index, tab.label())
            self.settings_tab_bar.setTabToolTip(index, tab.file_path or "No file loaded")
        except RuntimeError:
            log.debug("refresh_tab_label: ignored", exc_info=True)

    def note_active_tab_file(self):
        """The active tab's file path / dirty flag changed (load, save, save as):
        take them from the window, re-caption the tab and remember the set."""
        tab = self.current_tab()
        if tab is None:
            return
        tab.file_path = self.file_manager.get_current_file_path()
        tab.is_dirty = bool(getattr(self, "_is_dirty", False))
        self.refresh_tab_label(tab)
        self._persist_open_tabs()

    # ------------------------------------------------- one file, one tab
    def tab_index_with_file(self, path, exclude=None):
        """Index of the tab already holding `path` (skipping `exclude`), or -1."""
        for index, tab in enumerate(getattr(self, "_tabs", [])):
            if exclude is not None and index == exclude:
                continue
            if same_file(tab.file_path, path):
                return index
        return -1

    def guard_duplicate_file(self, path, action="Load", quiet=False, switch=True):
        """May `path` be opened in / saved from the active tab? True = go ahead.

        **The same settings file must never sit in two tabs.** Both tabs would
        hold their own copy of the text, both would edit it independently, and
        the second Save would silently throw the first one's work away - and the
        gauge/mask checks, Check settingsfile and a run would each work off a
        different version of one file on disk.

        Loading brings the tab that already has the file to the front
        (`switch=True`); Save As only refuses - switching away from the tab the
        user is saving would be the bigger surprise."""
        index = self.tab_index_with_file(path, exclude=self._active_tab_index)
        if index < 0:
            return True
        name = os.path.basename(path)
        if switch:
            self.switch_to_tab(index)
        try:
            self.status_bar.showMessage(f"{name} is already open in another tab")
        except Exception:
            log.debug("guard_duplicate_file: ignored", exc_info=True)
        if not quiet:
            tail = ("The same settings file cannot be open twice - switched to "
                    "that tab instead." if switch else
                    "The same settings file cannot be open twice - choose a "
                    "different name, or close that tab first.")
            QMessageBox.information(self, f"{action} settings file",
                                    f"{name} is already open in another tab.\n\n{tail}")
        return False

    # ---------------------------------------------------- linked scrolling
    def _linked_group(self, index):
        """Every tab index that scrolls together with `index`.

        The flag lives on the *later* tab of each pair ("linked to the previous
        one"), so a run of ticked tabs forms one chain: ticking tab 2 and tab 3
        links 1-2-3."""
        tabs = self._tabs
        group = [index]
        i = index
        while i > 0 and tabs[i].link_scroll:
            i -= 1
            group.append(i)
        i = index
        while i + 1 < len(tabs) and tabs[i + 1].link_scroll:
            i += 1
            group.append(i)
        return group

    def _on_editor_scrolled(self, tab, value):
        """Mirror a linked tab's vertical scroll onto its partners.

        Only one tab is visible at a time, so the point is what you see when you
        switch: a linked pair sits at the same line, which is how two settings
        files are read against each other. The value is the scrollbar's line
        position, clamped to each partner's own maximum (files differ in length)."""
        if getattr(self, "_scroll_sync", False):
            return
        try:
            index = self._tabs.index(tab)
        except ValueError:
            return
        group = self._linked_group(index)
        if len(group) < 2:
            return
        self._scroll_sync = True
        try:
            for i in group:
                if i == index:
                    continue
                bar = self._tabs[i].editor.verticalScrollBar()
                bar.setValue(max(0, min(value, bar.maximum())))
        except RuntimeError:
            log.debug("linked scroll partner gone", exc_info=True)
        finally:
            self._scroll_sync = False

    def _on_editor_folding(self, tab):
        """Mirror the folded sections onto the linked tab(s).

        Linked tabs are read against each other, so folding `[OPTIONS]` away in one
        must fold it away in the other - otherwise the two are no longer at the same
        place the moment a section collapses. Programmatic churn is skipped: a file
        load and a tab switch both emit foldingChanged, and neither is the user
        folding something (a load would otherwise unfold the partner)."""
        if (getattr(self, "_fold_sync", False)
                or getattr(self, "_switching_tabs", False)
                or getattr(self, "_suppress_dirty", False)):
            return
        try:
            index = self._tabs.index(tab)
        except ValueError:
            return
        group = self._linked_group(index)
        if len(group) < 2:
            return
        self._fold_sync = True
        try:
            folded = tab.editor.folded_sections()
            for i in group:
                if i != index:
                    self._tabs[i].editor.apply_folds(folded)
        except RuntimeError:
            log.debug("linked fold partner gone", exc_info=True)
        finally:
            self._fold_sync = False

    def _normalize_links(self):
        """The first tab can never be linked - it has no predecessor. Called after
        a close or a drag, which both renumber the tabs."""
        if self._tabs:
            self._tabs[0].link_scroll = False

    def set_tab_link_scroll(self, index, enabled):
        """Tab menu ▸ Link scrolling: tie tab `index` to the tab before it (or
        untie it), and bring the partner to this tab's scroll position **and folded
        sections** right away."""
        if not (0 < index < len(self._tabs)):
            return
        tab = self._tabs[index]
        tab.link_scroll = bool(enabled)
        if tab.link_scroll:
            try:
                self._on_editor_folding(tab)
                self._on_editor_scrolled(tab, tab.editor.verticalScrollBar().value())
            except RuntimeError:
                log.debug("initial link sync failed", exc_info=True)
        try:
            name = os.path.basename(self._tabs[index - 1].file_path or "") or UNTITLED
            self.status_bar.showMessage(
                f"Scrolling {'linked to' if tab.link_scroll else 'unlinked from'} {name}")
        except Exception:
            log.debug("set_tab_link_scroll: ignored", exc_info=True)

    # --------------------------------------------------- compare partner
    def compare_partner_index(self):
        """Index of the tab the active one is compared against: the tab immediately
        **left** of it, or - when the active tab is already the first - the one
        immediately **right**. -1 when there is no second tab. Shared by
        Settings ▸ Compare Tab (F8) and the Compare settings window's preload."""
        tabs = getattr(self, "_tabs", [])
        index = getattr(self, "_active_tab_index", -1)
        if len(tabs) < 2 or not (0 <= index < len(tabs)):
            return -1
        return index - 1 if index > 0 else index + 1

    def toggle_compare_tab(self):
        """Settings ▸ Compare Tab (F8): colour every line that differs from the
        neighbouring tab light green - in **both** tabs, so switching between them
        shows the same differences from either side. Pressing it again (F8) removes
        the colouring. Nothing is changed in either file; this is a view."""
        if self.compare_marks_shown():
            self.clear_compare_tab()
            return
        other = self.compare_partner_index()
        if other < 0:
            self.status_bar.showMessage(
                "Compare Tab needs a second tab to compare with")
            return
        tab, partner = self.current_tab(), self._tabs[other]
        try:
            a_lines = tab.editor.toPlainText().split("\n")
            b_lines = partner.editor.toPlainText().split("\n")
        except RuntimeError:
            log.debug("compare tab editor gone", exc_info=True)
            return
        a_rows, b_rows = diff_line_rows(a_lines, b_lines)
        tab.editor.set_compare_rows(a_rows)
        partner.editor.set_compare_rows(b_rows)
        name = os.path.basename(partner.file_path) if partner.file_path else UNTITLED
        if a_rows or b_rows:
            self.status_bar.showMessage(
                f"Compare Tab: {len(a_rows)} line(s) differ from {name} "
                f"({len(b_rows)} there) - F8 clears the colouring")
        else:
            self.status_bar.showMessage(f"Compare Tab: identical to {name}")

    def compare_marks_shown(self):
        """Whether any tab currently shows Compare Tab colouring (F8 = a toggle)."""
        for tab in getattr(self, "_tabs", []):
            try:
                if tab.editor.has_compare_rows():
                    return True
            except RuntimeError:
                continue
        return False

    def clear_compare_tab(self):
        """Remove the Compare Tab colouring from every tab."""
        for tab in getattr(self, "_tabs", []):
            try:
                if tab.editor.has_compare_rows():
                    tab.editor.set_compare_rows(())
            except RuntimeError:
                continue
        self.status_bar.showMessage("Compare Tab colouring cleared")

    def compare_partner_source(self):
        """`(content, path, name)` of the tab **Compare settings** starts its right
        pane on, or None when there is nothing sensible to preload.

        With more than one tab open, comparing the active file against its
        neighbour is what one actually wants: the tab immediately **left** of the
        active one, or - when the active tab is already the first - the one
        immediately **right** of it. A single tab, or a neighbour with no content
        yet, leaves the right pane empty and its Load button as the way in."""
        index = self.compare_partner_index()
        if index < 0:
            return None
        other = self._tabs[index]
        content = other.original_content or ""
        try:
            # A background tab's text lives in its own editor; original_content is
            # only refreshed on every switch, so prefer the document itself.
            text = other.editor.toPlainText()
            if text.strip():
                content = text
        except RuntimeError:
            log.debug("compare partner editor gone", exc_info=True)
        if not content.strip():
            return None
        name = os.path.basename(other.file_path) if other.file_path else UNTITLED
        return content, other.file_path, name

    # ------------------------------------------------------- context menu
    def _on_tab_context_menu(self, pos):
        """Right-click on a tab: Delete Tab / Copy Tab / Run CWatM / Link scrolling."""
        index = self.settings_tab_bar.tabAt(pos)
        if index < 0:
            index = self.settings_tab_bar.currentIndex()
        if not (0 <= index < len(self._tabs)):
            return
        tab = self._tabs[index]
        menu = QMenu(self)
        menu.setToolTipsVisible(True)

        act_del = menu.addAction("Delete Tab")
        act_del.setToolTip("Close this tab (asks about unsaved changes)")
        act_copy = menu.addAction("Copy Tab")
        if tab.file_path:
            act_copy.setToolTip(
                "Write this tab's content to "
                f"{os.path.basename(next_copy_path(tab.file_path))} in the same "
                "folder and open it in a new tab")
        else:
            act_copy.setEnabled(False)
            act_copy.setToolTip("This tab has no settings file yet - nothing to copy")
        menu.addSeparator()
        # Run this tab's settings file - in its own Windowed Run CWatM window, so it
        # is independent of the main run and of what the other tabs are doing.
        act_run = menu.addAction("Run CWatM")
        if tab.file_path:
            act_run.setToolTip(
                "Run this tab's settings file in a separate window "
                f"({os.path.basename(tab.file_path)}, as saved on disk)")
        else:
            act_run.setEnabled(False)
            act_run.setToolTip("This tab has no settings file yet - nothing to run")
        menu.addSeparator()
        act_link = menu.addAction("Link scrolling")
        act_link.setCheckable(True)
        act_link.setChecked(bool(tab.link_scroll))
        if index == 0:
            act_link.setEnabled(False)
            act_link.setToolTip("The first tab has no previous tab to link to")
        else:
            previous = self._tabs[index - 1]
            prev_name = (os.path.basename(previous.file_path) if previous.file_path
                         else UNTITLED)
            act_link.setToolTip(
                f"Scroll this tab together with {prev_name}: scrolling one moves "
                "the other to the same place, so switching between them keeps you "
                "at the same lines")

        chosen = menu.exec(self.settings_tab_bar.mapToGlobal(pos))
        if chosen is act_del:
            self.close_settings_tab(index)
        elif chosen is act_copy:
            self.copy_settings_tab(index)
        elif chosen is act_run:
            self.open_hidden_run(tab.file_path)
        elif chosen is act_link:
            self.set_tab_link_scroll(index, act_link.isChecked())

    def close_settings_tab(self, index):
        """Delete Tab: ask about unsaved changes, then drop the tab.

        The last remaining tab is emptied instead of removed - the window always
        has exactly one active editor."""
        if not (0 <= index < len(self._tabs)):
            return False
        if not self._confirm_tab_saved(index, "Close this tab"):
            return False
        if len(self._tabs) == 1:
            self._reset_tab_to_empty(index)
            self._persist_open_tabs()
            return True
        # Park the active tab's live state in its own object first: closing a tab
        # ends with _activate_tab(), which restores the window from that object -
        # without this, closing a *background* tab would revert the tab the user
        # is working in to its state at the last switch.
        self._store_active_tab()
        active_tab = self.current_tab()
        tab = self._tabs.pop(index)
        blocked = self.settings_tab_bar.blockSignals(True)
        self.settings_tab_bar.removeTab(index)
        self.settings_tab_bar.blockSignals(blocked)
        self.settings_stack.removeWidget(tab.page)
        tab.page.deleteLater()
        self._normalize_links()
        if active_tab is tab or active_tab not in self._tabs:
            new_index = min(index, len(self._tabs) - 1)
        else:
            new_index = self._tabs.index(active_tab)
        self._active_tab_index = -1
        self._switching_tabs = True
        try:
            self._activate_tab(new_index)
        finally:
            self._switching_tabs = False
        blocked = self.settings_tab_bar.blockSignals(True)
        self.settings_tab_bar.setCurrentIndex(new_index)
        self.settings_tab_bar.blockSignals(blocked)
        self._persist_open_tabs()
        return True

    def _reset_tab_to_empty(self, index):
        """Turn a tab back into a fresh, empty one (used when the last tab is
        deleted - see close_settings_tab)."""
        tab = self._tabs[index]
        was_active = (index == self._active_tab_index)
        tab.editor.load_text("")
        tab.file_path = None
        tab.original_content = ""
        tab.clean_content = ""
        tab.is_dirty = False
        tab.file_parsed = False
        tab.filename_state = "none"
        tab.filename_text = "No file loaded"
        tab.title_text = ""
        tab.working_dir_override = None
        tab.baseline_fields = {}
        tab.pathout_warning = ""
        tab.mask_context = None
        tab.mask_context_key = None
        tab.mask_context_built = False
        tab.link_scroll = False
        self.refresh_tab_label(tab)
        if was_active:
            self._switching_tabs = True
            try:
                self._activate_tab(index)
            finally:
                self._switching_tabs = False

    def copy_settings_tab(self, index):
        """Copy Tab: write this tab's *current* content (including unsaved
        edits) to the next free `<name>_<n>.ini` next to it and open that copy
        in a new tab right of the source."""
        if not (0 <= index < len(self._tabs)):
            return
        tab = self._tabs[index]
        if not tab.file_path:
            QMessageBox.information(self, "Copy Tab",
                                    "This tab has no settings file yet - save it first.")
            return
        content = (tab.editor.toPlainText() if tab is self.current_tab()
                   else tab.original_content)
        target = next_copy_path(tab.file_path)
        try:
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(content)
        except Exception as e:
            QMessageBox.warning(self, "Copy Tab",
                                f"Could not write the copy:\n{target}\n\n{e}")
            return
        self.add_settings_tab(activate=True, persist=False)
        # The new tab is the last one; move it next to the tab it was copied from
        new_index = len(self._tabs) - 1
        wanted = index + 1
        if wanted < new_index:
            self.settings_tab_bar.moveTab(new_index, wanted)   # tabMoved reorders _tabs
        self.load_recent_file(target)
        self.status_bar.showMessage(f"Tab copied to {target}")

    # ------------------------------------------------- unsaved-changes prompts
    def _confirm_tab_saved(self, index, question):
        """Ask Save / Discard / Cancel for a dirty tab. True = go ahead."""
        tab = self._tabs[index]
        if not tab.is_dirty and not (index == self._active_tab_index
                                     and getattr(self, "_is_dirty", False)):
            return True
        name = os.path.basename(tab.file_path) if tab.file_path else UNTITLED
        reply = QMessageBox.question(
            self, "Unsaved changes",
            f"{name} has unsaved changes.\n{question} anyway?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save)
        if reply == QMessageBox.Cancel:
            return False
        if reply == QMessageBox.Save:
            # save_file() always works on the ACTIVE tab
            if index != self._active_tab_index:
                self.switch_to_tab(index)
            self.save_file()
            if getattr(self, "_is_dirty", False):
                self.status_bar.showMessage(f"Save failed - {name} kept open")
                return False
        return True

    def confirm_all_tabs_saved(self):
        """closeEvent: walk every dirty tab, prompting per file. False = cancel
        the exit."""
        for index in range(len(getattr(self, "_tabs", []))):
            if not self._confirm_tab_saved(index, "Exit"):
                return False
        return True

    # ------------------------------------------------------------ persistence
    def _persist_open_tabs(self):
        """Remember the open files + the active one, for 'Load previous settings
        at start' (which reopens all of them)."""
        try:
            paths = [t.file_path for t in self._tabs if t.file_path]
            active = 0
            cur = self.current_tab()
            if cur is not None and cur.file_path in paths:
                active = paths.index(cur.file_path)
            self._settings.setValue("tabs/files", paths)
            self._settings.setValue("tabs/active", active)
        except Exception:
            log.debug("persisting open tabs failed", exc_info=True)

    def saved_tab_files(self):
        """(paths, active_index) remembered from the last session."""
        try:
            paths = self._settings.value("tabs/files", []) or []
            if isinstance(paths, str):
                paths = [paths]
            paths = [p for p in paths if p and os.path.isfile(p)]
            active = int(self._settings.value("tabs/active", 0) or 0)
        except Exception:
            log.debug("reading remembered tabs failed", exc_info=True)
            return [], 0
        return paths, max(0, min(active, len(paths) - 1)) if paths else 0

    def open_files_in_tabs(self, paths, active=0):
        """Open every path in its own tab (the first one in the current, empty
        tab) and activate `active`. Used at startup by 'Load previous settings
        at start' - a single file simply lands in the first tab.

        With tabs switched off (or below Expert) only the file that was active
        last time is opened - restoring tabs the user cannot see would be a
        surprise."""
        if not self.tabs_enabled() and paths:
            paths = [paths[max(0, min(active, len(paths) - 1))]]
            active = 0
        # One file, one tab - a remembered list that names the same file twice
        # (an older session, a moved file) must not open it twice.
        unique = []
        for path in paths:
            if not any(same_file(path, seen) for seen in unique):
                unique.append(path)
        if active < len(paths):
            wanted = paths[active]
            active = next((i for i, p in enumerate(unique) if same_file(p, wanted)), 0)
        paths = unique
        opened = 0
        for path in paths:
            if not path or not os.path.isfile(path):
                continue
            if opened:
                self.add_settings_tab(activate=True, persist=False)
            self.load_recent_file(path)
            opened += 1
        if opened:
            self.switch_to_tab(max(0, min(active, opened - 1)))
        self._persist_open_tabs()
        return opened
