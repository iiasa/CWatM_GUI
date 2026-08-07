"""
Main window for CWatM GUI application.

Orchestrates all components and handles user interactions.
Provides the main interface for loading, parsing, editing,
and managing CWatM configuration files.
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QPlainTextEdit, QStatusBar, QFrame,
    QLineEdit, QApplication, QScrollArea, QToolTip,
    QSizePolicy, QMessageBox, QDialog, QInputDialog, QFileDialog,
    QSplitter, QTextBrowser, QTabWidget, QCheckBox
)
from PySide6.QtCore import Qt, QEvent, QTimer, QSettings, QUrl, QDate
from PySide6.QtGui import QFont, QPixmap, QIcon, QTextCursor, QTextDocument, QImage
import re
import sys
import os

from src.gui.components.config_parser import ConfigParser
from src.gui.managers.date_manager import DateManager
from src.gui.managers.file_manager import FileManager
from src.gui.managers.text_display import TextDisplayManager
from src.gui.utils.progress_clock import ProgressClock
from src.gui.widgets.discharge_sparkline import DischargeSparkline
from src.gui.widgets.options_window import OptionsWindow
from src.gui.utils import display_format
from src.gui.utils import theme
from src.gui.utils.gui_log import get_logger
from src.gui.utils.meta_netcdf import get_meta
from src.gui.widgets.line_number_gutter import LineNumberGutter
from src.gui.widgets.settings_editor import SettingsEditor
from src.gui.components.menu_builder import MenuBuilderMixin
from src.gui.components.run_controller import RunControllerMixin
from src.gui.components.output_box import OutputBoxMixin

# Startup-cost note (report §4.1): basin_viewer (numpy/xarray/rasterio +
# QtWebEngine) and check_data_window (cwatm.run_cwatm -> scipy/pandas/netCDF4)
# are imported LAZILY inside the methods that need them, so the window appears
# after only the PySide6 + stdlib imports. cwatm_gui.py warms the heavy modules
# up in a background thread once the window is shown.

import cwatm.version as version

log = get_logger("main_window")

# Experience level (Beginner -> Advanced -> Expert -> Beginner). Each level
# defines which settings sections may be unfolded; every other section is kept
# folded, non-unfoldable and its header drawn gray. Expert unlocks everything.
_EXPERIENCE_LEVELS = ["Beginner", "Advanced", "Expert"]
_BEGINNER_SECTIONS = {
    "[FILE_PATHS]", "[MASK_OUTLET]", "[TIME-RELATED_CONSTANTS]", "[OUTPUT]",
}
_ADVANCED_SECTIONS = _BEGINNER_SECTIONS | {
    "[OPTIONS]", "[INITITIAL CONDITIONS]", "[METEO]", "[EVAPORATION]",
}
# Sections a given level is allowed to unfold (Expert = all -> None means "no
# restriction").
_LEVEL_ALLOWED = {
    "Beginner": _BEGINNER_SECTIONS,
    "Advanced": _ADVANCED_SECTIONS,
    "Expert": None,
}
# Level button background (RGB; drawn at 50% transparency).
_LEVEL_COLORS = {
    "Beginner": "144, 238, 144",   # light green
    "Advanced": "173, 216, 230",   # light blue
    "Expert":   "180, 180, 180",   # gray
}


class CWatMMainWindow(MenuBuilderMixin, RunControllerMixin,
                      OutputBoxMixin, QMainWindow):
    """Main application window for CWatM GUI.
    
    This class orchestrates all GUI components and manages user interactions
    for the CWatM model configuration and execution interface.
    
    Attributes:
        config_parser: Handles INI file parsing and formatting
        date_manager: Manages date input validation
        file_manager: Handles file I/O operations
        text_display: Manages text display area operations
        progress_clock: Circular progress indicator widget
        cwatm_running: Boolean flag indicating if CWatM is executing
        output_file_path: Path for optional output file logging
    """
    
    def __init__(self):
        """Initialize the main window and all its components.
        
        Sets up the window properties, initializes all manager classes,
        creates the UI layout, and configures initial state.
        """
        super().__init__()

        self.setWindowTitle("Community Water Model by IIASA")
        self.resize(1200, 800)  # Default reasonable size
        # Center window and make responsive to different screen sizes
        self.setMinimumSize(800, 600)  # Minimum size for usability
        # Always open in full (maximized) view
        self.setWindowState(Qt.WindowMaximized)
        # Allow dropping a settings file (.ini/.txt) onto the window to load it
        self.setAcceptDrops(True)
        
        # Set window icon (prefer the small multi-size icon for the taskbar). Resolve an
        # ABSOLUTE path so it works regardless of the current working directory (the old
        # relative "assets/..." only loaded when launched from the gui folder), and
        # handle the frozen exe. Only set it if it loads.
        try:
            if getattr(sys, "frozen", False):
                _bases = [getattr(sys, "_MEIPASS", ""), os.path.dirname(sys.executable)]
            else:
                # this file is <root>/src/gui/components/main_window.py -> <root> is 3 up
                _bases = [os.path.abspath(os.path.join(
                    os.path.dirname(__file__), "..", "..", ".."))]
            _icon = QIcon()
            for _base in _bases:
                for _name in ("cwatm_small.ico", "cwatm.ico"):
                    _p = os.path.join(_base, "assets", _name)
                    if os.path.exists(_p):
                        _cand = QIcon(_p)
                        if not _cand.isNull():
                            _icon = _cand
                            break
                if not _icon.isNull():
                    break
            if not _icon.isNull():
                self.setWindowIcon(_icon)
        except Exception:
            log.debug("window icon not set", exc_info=True)
        
        # Initialize components
        self.config_parser = ConfigParser()
        self.date_manager = DateManager()
        self.file_manager = FileManager(self)
        
        # UI elements
        self.text_area = None
        self.text_display = None
        self.filename_label = None
        self.workdir_label = None
        # Working directory override (File > Change Working Dir). None = derive it
        # from the settings file's own folder, which is the default.
        self._working_dir_override = None
        self.pathout_field = None
        self.maskmap_field = None
        self.run_cwatm_button = None
        self.progress_clock = None
        self.cwatminfo_box = None  # read-only QPlainTextEdit holding the CWatM output
        self.original_content = ""
        self.file_parsed = False
        self._last_was_progress = False  # last line in the box is a '\r' progress update
        # Throttle the output-box updates: CWatM prints once per timestep. Lines are
        # buffered in _pending_output as they arrive and appended to the (read-only)
        # QPlainTextEdit at most every ~150 ms, so appends stay O(1) per line.
        self._pending_output = []  # queued (text, is_error, is_progress) tuples
        self._display_timer = QTimer(self)
        self._display_timer.setInterval(150)
        self._display_timer.timeout.connect(self._flush_cwatminfo_display)
        self._suppress_dirty = False  # ignore dirty signals during programmatic updates
        self._is_dirty = False  # there are unsaved changes to the settings file
        self._clean_content = ""  # editor text at the last load/save (undo dirty check)
        # Debounce timer: auto-apply field changes (dates / PathOut / MaskMap) into the
        # in-memory settings content shortly after the user stops changing them.
        self._field_update_timer = QTimer(self)
        self._field_update_timer.setSingleShot(True)
        self._field_update_timer.setInterval(500)
        self._field_update_timer.timeout.connect(self._apply_field_changes)
        self.cwatm_running = False
        self.cwatm_worker = None
        self._run_start_time = None  # wall-clock start of the current run (elapsed/ETA)
        self._baseline_fields = {}   # field values at last load/save (changed-fields hint)
        # Combined Find & Replace dialog (non-modal, created on demand; Ctrl+F
        # opens it on the Find tab, Ctrl+H on the Replace tab)
        self._find_dialog = None
        self.output_file_path = None  # Path to the output file when checkbox is checked
        self._output_file_handle = None  # file handle kept open for the whole run
        self._output_file_override = None  # custom output-box file set via Configure menu
        self._pathout_warning = ""  # PathOut-missing warning (checked only on load/save)
        self._mask_context = None   # in-memory mask for gauge checks (built on load/save)
        self._mask_context_key = None  # MaskMap value the cached mask was built from
        self._mask_context_built = False  # has a build been ATTEMPTED for that key?
        # Recent settings files (History menu), persisted across sessions
        self._settings = QSettings("IIASA", "CWatM_GUI")
        # Restore the global display-decimals setting (Configure > Show Decimals).
        display_format.set_decimals(
            self._settings.value("display/decimals", 3, type=int))
        # Restore the initial map-transparency setting (Configure > Transparency).
        display_format.set_transparency(
            self._settings.value("display/transparency", 100, type=int))
        # Settings-editor font size in px ('+' / '-' buttons right of Down),
        # persisted across sessions (editor/font_size)
        self._editor_font_size = max(6, min(32,
            self._settings.value("editor/font_size", 13, type=int)))
        # Experience level (Beginner/Advanced/Expert) - restricts which settings
        # sections can be unfolded; persisted across sessions (editor/level)
        lvl = self._settings.value("editor/level", "Expert")
        self._experience_level = lvl if lvl in _EXPERIENCE_LEVELS else "Expert"
        rf = self._settings.value("recent_files", [])
        if isinstance(rf, str):
            rf = [rf]
        # History keeps the 6 most recent settings files
        self._recent_files = (list(rf) if rf else [])[:6]
        
        # Keep reference to basin viewer to prevent garbage collection
        self.basin_viewer = None
        
        self.setup_ui()
        self.setup_status_bar()
        
        # cwatminfo display updates immediately after each print command
        
    def setup_ui(self):
        """Setup the main user interface.
        
        Creates the central widget, main layout, header, and splits
        the interface into left control panel and right display panel.
        """
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)

        # Banner (title + logos) at the very top
        self.create_header(main_layout)

        # Main content in a draggable splitter (left control panel | right editor).
        # Built before the menu bar because the menu references widgets the panels
        # create (the write-output checkbox).
        content_splitter = QSplitter(Qt.Horizontal)
        content_splitter.setChildrenCollapsible(False)  # don't let a pane vanish
        content_splitter.setHandleWidth(6)
        self.content_splitter = content_splitter

        # Left panel with controls
        self.create_left_panel(content_splitter)

        # Right panel with text display
        self.create_right_panel(content_splitter)

        # Menu bar directly below the banner (inserted just under the header)
        self.create_menu_bar(main_layout)

        # Initial split position (responsive); the user can drag the handle to resize.
        screen_width = QApplication.primaryScreen().availableGeometry().width()
        left_w = max(360, int(screen_width * 0.42))
        right_w = max(400, int(screen_width * 0.58))
        content_splitter.setSizes([left_w, right_w])
        content_splitter.setStretchFactor(0, 0)  # keep left panel width on resize
        content_splitter.setStretchFactor(1, 1)  # right editor takes extra space

        main_layout.addWidget(content_splitter, 1)
        
    def create_header(self, parent_layout):
        """Create header with title and logo.
        
        Args:
            parent_layout: The parent layout to add the header to
        """
        # The whole banner lives in a container widget so Configure ▸ Show Header
        # can hide it (setVisible(False)) and everything below moves up.
        banner_widget = QWidget()
        header_layout = QHBoxLayout(banner_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)

        # CWatM icon
        try:
            icon_label = QLabel()
            from src.gui.utils.assets import asset_path
            pixmap = QPixmap(asset_path("cwatm.ico"))
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                icon_label.setPixmap(scaled_pixmap)
            header_layout.addWidget(icon_label)
        except Exception:
            log.debug("banner icon not shown", exc_info=True)
        
        # Title
        title_label = QLabel("CWatM GUI")
        title_label.setAlignment(Qt.AlignLeft)
        # Make title font size responsive
        screen_width = QApplication.primaryScreen().availableGeometry().width()
        title_font_size = max(20, min(33, screen_width // 35))  # Scale with screen width
        title_label.setFont(QFont("Arial", title_font_size, QFont.Bold))
        title_label.setStyleSheet(f"color: {theme.c('accent')};")
        self._banner_title = title_label
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        # Interface description, centred in the middle of the banner
        interface_label = QLabel("The Community Water Model User Interface")
        interface_label.setAlignment(Qt.AlignCenter)
        interface_label.setStyleSheet(f"color: {theme.c('text_muted')};")
        self.interface_label = interface_label
        # No word wrap; instead the font is sized to the current window width and
        # shrinks as the window shrinks (see _update_interface_font / resizeEvent).
        self._update_interface_font()
        header_layout.addWidget(interface_label)

        header_layout.addStretch()

        # IIASA logo
        try:
            iiasa_label = QLabel()
            from src.gui.utils.assets import asset_path
            iiasa_pixmap = QPixmap(asset_path("iiasa-logo.svg"))
            if not iiasa_pixmap.isNull():
                scaled_iiasa = iiasa_pixmap.scaled(180, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                iiasa_label.setPixmap(scaled_iiasa)
                header_layout.addWidget(iiasa_label)
            else:
                iiasa_label.setText("IIASA")
                iiasa_label.setStyleSheet("color: blue; font-weight: bold;")
                header_layout.addWidget(iiasa_label)
        except:
            iiasa_label = QLabel("IIASA")
            iiasa_label.setStyleSheet("color: blue; font-weight: bold;")
            header_layout.addWidget(iiasa_label)

        self._banner_widget = banner_widget
        parent_layout.addWidget(banner_widget)
        # Apply the persisted Show Header state (default ON) at startup.
        try:
            show_header = self._settings.value("display/show_header", True, type=bool)
        except Exception:
            show_header = True
        banner_widget.setVisible(bool(show_header))

    def _update_interface_font(self):
        """Size the banner interface text to the current window width so it shrinks
        as the window shrinks. Smaller than the rest of the header; no word wrap."""
        if getattr(self, "interface_label", None) is None:
            return
        size = max(7, min(13, self.width() // 95))  # scale with window width
        self.interface_label.setFont(QFont("Arial", size))

    def resizeEvent(self, event):
        """Keep the banner interface font and output-box width responsive."""
        super().resizeEvent(event)
        # resizeEvent can fire during __init__ (setWindowState(Maximized) at the top,
        # before the managers/widgets exist), so the helpers here must tolerate a
        # not-yet-built window (they guard with getattr).
        self._update_interface_font()
        self._cap_output_box_width()

    def _cap_output_box_width(self):
        """One shared width for the date row, the output box and the date
        timeline: everything ends at the right edge of the last element of the
        date row (the End Date field, or its 'Pick a date' button when the
        web-style picker is on)."""
        sa = getattr(self, "cwatminfo_box", None)
        dm = getattr(self, "date_manager", None)
        end = getattr(dm, "end_date_edit", None) if dm else None
        if sa is None or end is None:
            return
        right = end.geometry().right()
        btn = getattr(dm, "_cal_buttons", {}).get('end')
        if btn is not None and btn.isVisible():
            right = max(right, btn.geometry().right())
        if right > 150:  # only once the date row has actually been laid out
            # Fixed width (not just a maximum) so the box keeps this width and the
            # trailing stretch in its container pins it to the left instead of centring.
            sa.setFixedWidth(right)
            tl = getattr(dm, "timeline", None)
            if tl is not None:
                tl.setFixedWidth(right)

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
                pass
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

    def create_left_panel(self, parent_layout):
        """Create left control panel with all input controls.
        
        Creates file controls, date fields, path inputs, action buttons,
        and the CWatM execution interface.
        
        Args:
            parent_layout: The parent layout to add the panel to
        """
        # Create outer container with scroll area for smaller screens
        left_container = QWidget()
        # Floor width so the splitter cannot drag the control panel away entirely
        left_container.setMinimumWidth(320)
        left_container_layout = QVBoxLayout(left_container)
        left_container_layout.setContentsMargins(0, -15, 0, 0)  # Shift content up by 15 pixels

        # Create scroll area for the control panel
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        # Scroll horizontally (instead of clipping) when the panel is dragged narrow
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_scroll.setFrameShape(QFrame.NoFrame)  # Remove scroll area border
        
        left_panel = QWidget()
        left_panel.setStyleSheet(self._left_panel_style())
        self._left_panel = left_panel
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(0)  # Minimal vertical spacing between elements
        left_layout.setContentsMargins(8, 0, 8, 8)  # Ultra-minimal margins
        
        # Set minimum width for the scrollable content and responsive sizing (20% wider)
        screen_width = QApplication.primaryScreen().availableGeometry().width()
        min_panel_width = max(360, min(480, int(screen_width // 4 * 1.2)))  # 20% wider: 300-400px → 360-480px
        left_panel.setMinimumWidth(min_panel_width)
        
        # Set size policy to allow expansion but prefer minimum size
        left_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        
        # Small space before the first control group (interface title now lives in
        # the banner header, see create_header)
        left_layout.addSpacing(2)

        # Separator with ultra-minimal spacing
        separator1 = QFrame()
        separator1.setFrameShape(QFrame.HLine)
        separator1.setFrameShadow(QFrame.Sunken)
        separator1.setMaximumHeight(2)  # Ultra-thin separator
        separator1.setContentsMargins(0, 1, 0, 1)  # Ultra-minimal margins
        left_layout.addWidget(separator1)

        # Load file controls
        self.create_file_controls(left_layout)

        # Separator with ultra-minimal spacing
        separator2 = QFrame()
        separator2.setFrameShape(QFrame.HLine)
        separator2.setFrameShadow(QFrame.Sunken)
        separator2.setMaximumHeight(2)  # Ultra-thin separator
        separator2.setContentsMargins(0, 1, 0, 1)  # Ultra-minimal margins
        left_layout.addWidget(separator2)

        # Date controls
        self.date_manager.create_date_widgets(left_layout)
        
        # Connect date change signals to dirty-state marking / auto-apply
        self.date_manager.start_date_edit.dateChanged.connect(self.on_field_changed)
        self.date_manager.spin_date_edit.dateChanged.connect(self.on_field_changed)
        self.date_manager.end_date_edit.dateChanged.connect(self.on_field_changed)
        # The calendar popups dim days outside the meteo-forcing coverage
        self.date_manager.set_forcing_provider(self._forcing_range_for_calendar)
        # Web-style picker (Configure > Web-style date picker), persisted
        self.date_manager.set_web_picker(
            self._settings.value("display/date_picker_web", True, type=bool))
        # Three-handle date timeline (Configure > Date timeline), persisted
        self.date_manager.set_timeline_visible(
            self._settings.value("display/date_timeline", True, type=bool))
        
        # PathOut controls
        self.create_pathout_controls(left_layout)
        
        # MaskMap controls
        self.create_maskmap_controls(left_layout)

        # Gauges controls (under MaskMap)
        self.create_gauges_controls(left_layout)
        
        # Separator with ultra-minimal spacing
        separator3 = QFrame()
        separator3.setFrameShape(QFrame.HLine)
        separator3.setFrameShadow(QFrame.Sunken)
        separator3.setMaximumHeight(2)  # Ultra-thin separator
        separator3.setContentsMargins(0, 1, 0, 1)  # Ultra-minimal margins
        left_layout.addWidget(separator3)

        # Run button
        self.create_run_button(left_layout)
        
        left_layout.addStretch()
        
        # Add the panel to the scroll area
        left_scroll.setWidget(left_panel)
        left_container_layout.addWidget(left_scroll)
        
        parent_layout.addWidget(left_container)
        
    def create_file_controls(self, parent_layout):
        """Create file loading controls"""
        load_layout = QHBoxLayout()
        load_layout.setSpacing(5)  # Minimal horizontal spacing
        load_layout.setContentsMargins(0, 0, 0, 0)  # No vertical margins: keeps the
        # "Working directory:" line tight under the "Loaded:" line

        self.filename_label = QLabel("No file loaded")
        self._filename_state = "none"  # none / loaded / saveas / error
        self.filename_label.setContentsMargins(0, 0, 0, 0)
        load_layout.addWidget(self.filename_label)

        # The settings "Title" value, shown right of "Loaded:" in the same colour
        # and size, so the two read as one line.
        self.title_label = QLabel("")
        load_layout.addWidget(self.title_label)

        # Both parts of the "Loaded:" line 1 pt bigger than the default (kept via
        # QFont so the setStyleSheet calls, which set only colour, do not reset it)
        for _lbl in (self.filename_label, self.title_label):
            _f = _lbl.font()
            if _f.pointSize() > 0:
                _f.setPointSize(_f.pointSize() + 1)
                _lbl.setFont(_f)
        self._apply_filename_state()

        load_layout.addStretch()
        parent_layout.addLayout(load_layout)

        # Second line, under "Loaded: ...": the folder the settings file lives in.
        # Hidden while no file is loaded. 1pt smaller than the Loaded line (kept via
        # QFont so the later setStyleSheet calls, which set only colour, do not
        # reset the size).
        self.workdir_label = QLabel("")
        _wd_font = self.workdir_label.font()
        if _wd_font.pointSize() > 1:
            _wd_font.setPointSize(_wd_font.pointSize() - 1)
            self.workdir_label.setFont(_wd_font)
        self.workdir_label.setContentsMargins(0, 0, 0, 0)
        self.workdir_label.setToolTip("Folder of the loaded settings file")
        self.workdir_label.setVisible(False)
        parent_layout.addWidget(self.workdir_label)

        parent_layout.addSpacing(1)  # Minimal spacing after file controls
        
        
    def create_run_button(self, parent_layout):
        """Create the separator and the RUN CWatM button. (The old Actualize button was
        removed: field changes auto-apply in memory and Save shows the unsaved state.)"""
        # Separator line with ultra-minimal spacing
        separator4 = QFrame()
        separator4.setFrameShape(QFrame.HLine)
        separator4.setFrameShadow(QFrame.Sunken)
        separator4.setMaximumHeight(2)  # Ultra-thin separator
        separator4.setContentsMargins(0, 1, 0, 1)  # Ultra-minimal margins
        parent_layout.addWidget(separator4)
        parent_layout.addSpacing(1)  # Minimal spacing after separator
        
        # RUN CWatM button with progress
        self.create_run_cwatm_button(parent_layout)
        
    def create_run_cwatm_button(self, parent_layout):
        """Create RUN CWatM button and output area with progress clock"""
        # RUN CWatM button
        run_cwatm_layout = QHBoxLayout()
        run_cwatm_layout.setSpacing(5)  # Minimal horizontal spacing
        run_cwatm_layout.setContentsMargins(0, 1, 0, 1)  # Minimal vertical margins
        
        self.run_cwatm_button = QPushButton("RUN CWatM")
        # Compact responsive height so the button takes less vertical room
        screen_height = QApplication.primaryScreen().availableGeometry().height()
        button_height = max(28, min(38, screen_height // 26))
        self.run_cwatm_button.setMinimumHeight(button_height)
        self.run_cwatm_button.setMinimumWidth(100)
        self._run_btn_state = "idle"  # idle / ready (blue) / running (red)
        self.run_cwatm_button.setStyleSheet(self._run_button_idle_style())
        self.run_cwatm_button.clicked.connect(self.run_cwatm)
        run_cwatm_layout.addWidget(self.run_cwatm_button)

        # "Save changes to use them!" hint right of RUN CWatM: shown whenever there
        # are unsaved edits (editor / left-window field / Excel), hidden after a save.
        self.save_hint_label = QLabel("")
        self.save_hint_label.setStyleSheet(
            f"QLabel {{ color: {theme.c('warn_color')}; font-weight: bold; }}")
        run_cwatm_layout.addWidget(self.save_hint_label)

        # Changed-fields hint right of RUN CWatM (blue): which fields differ from the
        # loaded/saved file, i.e. the run will use the new values.
        self.changed_fields_label = QLabel("")
        self.changed_fields_label.setWordWrap(True)
        self.changed_fields_label.setStyleSheet(
            f"QLabel {{ color: {theme.c('hint_color')}; }}")
        run_cwatm_layout.addWidget(self.changed_fields_label, 1)

        # Warning label to the right of RUN CWatM - shows problems (e.g. gauges not in
        # the mask) in red. Empty when everything is fine.
        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet(
            f"QLabel {{ color: {theme.c('warn_color')}; font-weight: bold; }}")
        run_cwatm_layout.addWidget(self.warning_label, 1)

        # ("Write output to cwatm_out.txt" checkbox removed — now controlled by the
        # Settings > "Write output" menu tick box.)

        run_cwatm_layout.addStretch()
        parent_layout.addLayout(run_cwatm_layout)
        parent_layout.addSpacing(1)  # Minimal spacing after run button
        
        # CWatM info area and progress clock layout.
        # Always stack vertically so the progress clock sits *under* the output box.
        screen_width = QApplication.primaryScreen().availableGeometry().width()
        info_progress_layout = QVBoxLayout()
        info_progress_layout.setSpacing(2)  # Ultra-minimal vertical spacing
        info_progress_layout.setContentsMargins(0, 1, 0, 1)  # Ultra-minimal margins
        
        # CWatM info area for DOS screen output - a read-only QPlainTextEdit: appends
        # are O(1) (no full HTML re-render), scrollback is capped by maximumBlockCount,
        # and selection/copy are native.
        self.cwatminfo_box = QPlainTextEdit()
        self.cwatminfo_box.setReadOnly(True)
        self.cwatminfo_box.setPlaceholderText("CWatM output will appear here...")
        self.cwatminfo_box.setMaximumBlockCount(5000)  # scrollback limit (lines)
        self.cwatminfo_box.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        # --- Vertical budget (laptop -> desktop): the run button (h/26, 28-38 px,
        # set in create_run_cwatm_button above), output box (h/5, 100-260 px) and
        # clock row (h/6, 110-220 px) are all sized from the screen height.
        # Everything above the output box (banner, menu, file/date/path/gauge
        # rows, run button) needs ~420-470 px, so on a ~700 px laptop screen the
        # box and clock must shrink for the column to fit without scrolling,
        # while a >=1000 px desktop screen gets the full sizes.
        screen_height = QApplication.primaryScreen().availableGeometry().height()
        min_height = max(100, screen_height // 10)
        max_height = min(260, screen_height // 5)
        self.cwatminfo_box.setMinimumHeight(min_height)
        self.cwatminfo_box.setMaximumHeight(max_height)
        # Output box: modest minimum width; the maximum is capped at the right edge of
        # the End Date field in resizeEvent, so the box ends where the calendar fields end.
        self.cwatminfo_box.setMinimumWidth(350)
        # Make cwatminfo font size responsive
        self._cwatm_font_size = max(9, min(11, screen_height // 80))  # Scale with screen height
        self.cwatminfo_box.setStyleSheet(self._output_box_style())

        # Native selection / Ctrl+C work out of the box; the custom context menu keeps
        # the standard actions and adds "Copy all output", which works even while the
        # run is still updating.
        self.cwatminfo_box.setContextMenuPolicy(Qt.CustomContextMenu)
        self.cwatminfo_box.customContextMenuRequested.connect(self._show_cwatminfo_menu)

        cwatminfo_container = QWidget()
        cwatminfo_container_layout = QHBoxLayout(cwatminfo_container)
        cwatminfo_container_layout.setContentsMargins(0, 0, 0, 0)  # Shift 90px to the left (80+10)
        cwatminfo_container_layout.setSpacing(0)
        cwatminfo_container_layout.addWidget(self.cwatminfo_box)
        cwatminfo_container_layout.addStretch()  # keep the box pinned to the left

        info_progress_layout.addWidget(cwatminfo_container)
        
        # Add extra space before progress clock (reduced by 30 pixels to shift cwatminfo left)
        #info_progress_layout.addSpacing(10)  # Reduced from 30 to 20 pixels (10 more pixels left)
        
        # Progress clock - right side with container for positioning (10px up)
        progress_container = QWidget()
        progress_container_layout = QVBoxLayout(progress_container)
        # Negative top margin pulls the clock close under the output box
        # (the left panel's QWidget margin/padding cascade pushes it down)
        progress_container_layout.setContentsMargins(0, -30, 0, 0)
        progress_container_layout.setSpacing(0)  # No spacing in container
        
        self.progress_clock = ProgressClock()
        self.progress_clock.setValue(0)  # Start at 0%
        # Make progress clock responsive to screen size. The elapsed/remaining
        # run time is drawn INSIDE the clock face (set_time_lines), so the
        # diameter is a bit larger than it was with the external label.
        screen_width = QApplication.primaryScreen().availableGeometry().width()
        # Size by both screen width and height (see the vertical-budget note
        # above): h/6 shrinks the clock to ~120 px on a laptop screen so the
        # whole left column fits; capped at 220 px on big screens.
        clock_size = max(110, min(220, screen_width // 8, screen_height // 6))
        self.progress_clock.setFixedSize(clock_size, clock_size)

        # Clock on the left, live discharge sparkline to its right (same row) so the
        # user watches percentage/time and the discharge trace side by side during a run.
        clock_row = QHBoxLayout()
        clock_row.setContentsMargins(0, 0, 0, 0)
        clock_row.setSpacing(10)
        clock_row.addWidget(self.progress_clock)

        self.discharge_sparkline = DischargeSparkline()
        self.discharge_sparkline.setFixedHeight(max(60, clock_size - 40))
        # 15% wider than before (previously max(220, clock_size + 40)).
        self.discharge_sparkline.setMinimumWidth(int(max(220, clock_size + 40) * 1.15))
        clock_row.addWidget(self.discharge_sparkline)
        clock_row.addStretch()
        progress_container_layout.addLayout(clock_row)

        # Clock left-aligned under the output box
        info_progress_layout.addWidget(progress_container, 0, Qt.AlignLeft)

        info_progress_layout.addStretch()
        parent_layout.addLayout(info_progress_layout)
        parent_layout.addSpacing(1)  # Ultra-minimal spacing at bottom
        
    def create_pathout_controls(self, parent_layout):
        """Create PathOut display controls aligned with date fields"""
        pathout_layout = QHBoxLayout()
        pathout_layout.setSpacing(2)  # Ultra-minimal spacing between label and field
        pathout_layout.setContentsMargins(0, 0, 0, 0)  # No vertical margins
        
        # PathOut label (exact width to align with Start Date field)
        pathout_label = QLabel("PathOut:")
        
        # Create a temporary label with "Start Date:" to measure its size
        temp_label = QLabel("Start Date:")

        # Set PathOut label to same width as "Start Date:" label
        pathout_label.setFixedWidth(90)
        pathout_layout.addWidget(pathout_label)
        pathout_layout.addSpacing(2)  # Ultra-minimal spacing
        

        # PathOut field (editable, same width as MaskMap field)
        self.pathout_field = QLineEdit()
        self.pathout_field.setPlaceholderText("Enter or edit path here...")
        # Use responsive height for input fields
        screen_height = QApplication.primaryScreen().availableGeometry().height()
        input_height = max(24, min(28, screen_height // 28))  # 2px tighter row
        self.pathout_field.setMinimumHeight(input_height)
        self.pathout_field.setMinimumWidth(120)  # Same width as MaskMap field
        self.pathout_field.setStyleSheet(self._field_style())
        self.pathout_field.textChanged.connect(self.on_field_changed)
        pathout_layout.addWidget(self.pathout_field)
        
        # Add stretch to match date field layout
        pathout_layout.addStretch()
        
        parent_layout.addLayout(pathout_layout)
        parent_layout.addSpacing(1)  # Minimal spacing after pathout controls
        
    def create_maskmap_controls(self, parent_layout):
        """Create MaskMap display controls aligned with date fields"""
        maskmap_layout = QHBoxLayout()
        maskmap_layout.setSpacing(2)  # Ultra-minimal spacing between label and field
        maskmap_layout.setContentsMargins(0, 0, 0, 0)  # No vertical margins
        
        # MaskMap label (exact width to align with Start Date field)
        maskmap_label = QLabel("MaskMap:")
        
        # Create a temporary label with "Start Date:" to measure its size
        temp_label = QLabel("Start Date:")
        #temp_size = temp_label.sizeHint()
        
        # Set MaskMap label to same width as "Start Date:" label
        maskmap_label.setFixedWidth(100)
        maskmap_layout.addWidget(maskmap_label)
        
        # Add 30 pixel spacing to shift MaskMap field to the right
        #maskmap_layout.addSpacing(10)
        
        # MaskMap field (editable, same width as PathOut field)
        self.maskmap_field = QLineEdit()
        self.maskmap_field.setPlaceholderText("Enter or edit mask map path here...")
        # Use responsive height for input fields
        screen_height = QApplication.primaryScreen().availableGeometry().height()
        input_height = max(24, min(28, screen_height // 28))  # 2px tighter row
        self.maskmap_field.setMinimumHeight(input_height)
        self.maskmap_field.setMinimumWidth(120)  # Same width as PathOut field
        self.maskmap_field.setStyleSheet(self._field_style())
        self.maskmap_field.textChanged.connect(self.on_field_changed)
        maskmap_layout.addWidget(self.maskmap_field)
        
        # Add stretch to match date field layout
        maskmap_layout.addStretch()

        parent_layout.addLayout(maskmap_layout)
        parent_layout.addSpacing(1)  # Minimal spacing after maskmap controls

    def create_gauges_controls(self, parent_layout):
        """Create Gauges display controls (label + field), aligned like MaskMap."""
        gauges_layout = QHBoxLayout()
        gauges_layout.setSpacing(2)
        gauges_layout.setContentsMargins(0, 0, 0, 0)

        # Gauges label (same fixed width as the MaskMap label for alignment)
        gauges_label = QLabel("Gauges:")
        gauges_label.setFixedWidth(100)
        gauges_layout.addWidget(gauges_label)

        # Gauges field (editable, styled like the MaskMap field), linked to the
        # settings-file "Gauges" entry.
        self.gauges_field = QLineEdit()
        self.gauges_field.setPlaceholderText("Enter or edit gauges here...")
        screen_height = QApplication.primaryScreen().availableGeometry().height()
        input_height = max(24, min(28, screen_height // 28))  # 2px tighter row
        self.gauges_field.setMinimumHeight(input_height)
        self.gauges_field.setMinimumWidth(120)
        self.gauges_field.setStyleSheet(self._field_style())
        self.gauges_field.textChanged.connect(self.on_field_changed)
        gauges_layout.addWidget(self.gauges_field)

        gauges_layout.addStretch()
        parent_layout.addLayout(gauges_layout)
        parent_layout.addSpacing(1)

    def _live_content(self):
        """Settings content with the MaskMap and Gauges entries replaced by the CURRENT
        text-box values, so the gauge-in-mask check reflects what is shown in the boxes
        (which may differ from the saved/parsed settings file)."""
        try:
            content = self.text_display.get_content() or self.original_content
        except Exception:
            content = ""
        if not content:
            try:
                path = self.file_manager.get_current_file_path()
                if path:
                    with open(path, encoding="utf-8", errors="ignore") as _f:
                        content = _f.read()
            except Exception:
                content = ""
        updates = {}
        if getattr(self, "maskmap_field", None) is not None:
            updates['maskmap'] = self.maskmap_field.text().strip()
        if getattr(self, "gauges_field", None) is not None:
            updates['gauges'] = self.gauges_field.text().strip()
        if getattr(self, "pathout_field", None) is not None:
            updates['pathout'] = self.pathout_field.text().strip()
        if updates and content:
            try:
                content = self.config_parser.update_settings(content, updates)
            except Exception:
                log.warning("live-content substitution failed", exc_info=True)
        return content

    def _resolved_pathout_dir(self):
        """Return the PathOut text-box value with placeholders resolved to an existing
        directory (used as the start folder for Analyse > Timeseries), or None."""
        try:
            if getattr(self, "pathout_field", None) is None:
                return None
            if not self.pathout_field.text().strip():
                return None
            from src.gui.widgets.basin_viewer import pathout_exists  # lazy (§4.1)
            _, resolved = pathout_exists(self._live_content())
            if resolved and os.path.isdir(resolved):
                return resolved
        except Exception:
            log.debug("PathOut could not be resolved", exc_info=True)
        return None

    def _rebuild_mask_cache(self, force=False):
        """(Re)build the in-memory mask used for gauge checks. This is potentially
        expensive for a coordinate-based MaskMap (a basin is generated with CWatM),
        so it is only done when a settings file is loaded (force=True) or the MaskMap
        entry has changed since the last build (on save)."""
        content = self._live_content()
        maskmap = self.maskmap_field.text().strip() if getattr(self, "maskmap_field", None) else ""
        # Guard on "a build was attempted for this MaskMap", NOT on "a mask exists":
        # build_mask_context returns None whenever the mask cannot be built (mid-typing
        # a MaskMap value, missing ups.nc, ...), and keying off _mask_context would then
        # never cache that outcome - so the full temp-.ini + `mainwarm -vgm` run repeated
        # on every field edit (report §2.1). A failed build is cached like a successful
        # one; Save / Save As / load pass force=True and retry it.
        if not force and self._mask_context_built and maskmap == self._mask_context_key:
            return  # MaskMap unchanged - keep the cached result (mask or None)
        settings_file = self.file_manager.get_current_file_path()
        from src.gui.widgets.basin_viewer import build_mask_context  # lazy (§4.1)
        self._mask_context = build_mask_context(settings_file, content)
        self._mask_context_key = maskmap
        self._mask_context_built = True
        # Small hint when a MaskMap is defined but its mask could not be built
        # (e.g. coordinate MaskMap without a resolvable ups.nc, or missing mask file),
        # so the gauge check is silently skipped.
        if maskmap and self._mask_context is None:
            self.status_bar.showMessage(
                "Note: could not build the basin mask for the gauge check "
                "(check MaskMap / ups.nc).")

    def _update_warnings(self, check_pathout=True):
        """Colour the Gauges field and show problems in red next to the RUN CWatM
        button. The gauges-in-mask check runs on every call (also after field
        changes); the PathOut-exists check runs only when check_pathout is True
        (i.e. on load and save)."""
        if getattr(self, "gauges_field", None) is None:
            return
        # Always base the check on the CURRENT left-box values: rebuild the mask if the
        # MaskMap box changed since the cached mask was built (cheap when unchanged).
        try:
            self._rebuild_mask_cache()
        except Exception:
            log.warning("mask-cache rebuild failed - gauge check may be stale",
                        exc_info=True)
        try:
            settings_file = self.file_manager.get_current_file_path()
            content = self._live_content()  # use the current text-box values
        except Exception:
            settings_file, content = None, ""

        # --- Gauges inside the mask map (built from the current MaskMap box) ---
        try:
            from src.gui.widgets.basin_viewer import gauges_inside  # lazy (§4.1)
            gres = gauges_inside(self._mask_context, content)
        except Exception:
            gres = None
        gauge_warning = ""
        self._gauges_state = gres  # remembered for a theme re-style (_retheme)
        self._apply_gauges_field_color()
        if gres is False:
            gauge_warning = "Gauge is not inside the basin! Change manually or use Tools/Set Gauge."

        # --- PathOut folder exists (only on load/save) ---
        if check_pathout:
            try:
                from src.gui.widgets.basin_viewer import pathout_exists  # lazy (§4.1)
                pres, _ = pathout_exists(content)
            except Exception:
                pres = None
            self._pathout_warning = (
                "PathOut does not exists! You can use Tools/Create PathOut Folder."
                if pres is False else "")

        # Show / clear the warnings next to the RUN CWatM button
        warnings = [w for w in (gauge_warning, self._pathout_warning) if w]
        if getattr(self, "warning_label", None) is not None:
            self.warning_label.setText("\n".join(warnings))

    def check_settingsfile(self):
        """Settings ▸ Check settingsfile: walk the settings as shown in the editor and
        check every value that can be identified as a filename/path. Lines whose file
        does not exist are marked **red** and **bookmarked** (F2 jumps between them)."""
        import configparser
        import glob as _glob
        try:
            content = self.text_area.toPlainText()
        except Exception:
            return
        if not content.strip():
            self.status_bar.showMessage("Nothing to check - load a settings file first")
            return

        # ConfigParser (no interpolation) for resolving $(section:key) placeholders.
        config = None
        try:
            config = configparser.ConfigParser(interpolation=None, strict=False)
            config.read_string(content)
        except Exception:
            config = None
        from src.gui.widgets.basin_viewer import _resolve_settings_placeholders

        # Relative paths resolve against the working directory (the settings file's
        # folder unless File > Change Working Dir overrode it).
        base_dir = self.working_dir()

        _EXT = (r'\.(nc|nc4|tif|tiff|map|txt|csv|xlsx?|geojson|json|asc|img|bil|'
                r'hdf5?|h5|pcr|ldd|dat|bin)(\*|"|\b|$)')

        def looks_like_path(v):
            v = v.strip().strip('"')
            if not v:
                return False
            if '$(' in v:                         # a settings placeholder -> path ref
                return True
            if re.search(_EXT, v, re.I):          # a known data-file extension
                return True
            if re.match(r'^[A-Za-z]:[\\/]', v) or v.startswith('\\\\'):  # absolute path
                return True
            return False

        def path_exists(p, strict=False):
            """Whether the resolved path exists. ``strict`` (used for keys starting with
            'path', i.e. directory paths) checks existence exactly - no NetCDF
            without-extension / date-suffix glob fallbacks."""
            p = p.strip().strip('"')
            if not p:
                return True
            if not os.path.isabs(p) and base_dir:
                p = os.path.join(base_dir, p)
            try:
                if any(c in p for c in '*?'):
                    return bool(_glob.glob(p))
                if os.path.exists(p):
                    return True
                if strict:
                    return False
                # CWatM often stores NetCDFs without .nc or with a date suffix
                if _glob.glob(p + '*'):
                    return True
                return os.path.exists(p + '.nc')
            except Exception:
                return True   # never flag on a lookup error

        # Interchangeable raster extensions in CWatM: a map named .map/.tif/.nc may
        # actually be on disk under one of the others.
        _ALT_EXTS = ('.nc', '.nc4', '.tif', '.tiff', '.map')

        def wrong_extension_alt(p):
            """If the exact file p is missing but the SAME base name exists with a
            different known raster extension (e.g. .map written, .nc on disk), return
            that existing alternative path; else None. Best-effort, never raises."""
            p = p.strip().strip('"')
            if not p or any(c in p for c in '*?'):
                return None
            if not os.path.isabs(p) and base_dir:
                p = os.path.join(base_dir, p)
            root, ext = os.path.splitext(p)
            if not ext or ext.lower() not in _ALT_EXTS:
                return None
            try:
                for alt in _ALT_EXTS:
                    if alt == ext.lower():
                        continue
                    cand = root + alt
                    if os.path.exists(cand) or _glob.glob(cand + '*'):
                        return cand
            except Exception:
                return None
            return None

        # Fresh run: drop any red/bookmarks from a previous check first.
        self.text_area.clear_checking()

        # Sections whose keys CWatM only reads when their [OPTIONS] switch is on
        # (mirrored from the checkOption(...) guards in cwatm/, read-only - e.g.
        # run_cwatm.py:65 modflow, readmeteo.py glaciers, water_demand.py:423,
        # lakes_reservoirs.py:303, cwatm_dynamic.py:229/255, inflow.py:129,
        # environflow.py:67). A missing FILE in such a section while the option is
        # explicitly off is dimmed, not flagged. Unresolved placeholders and out_*
        # keys stay global: CWatM resolves/collects those for EVERY section at
        # parse time (ExtParser Error 116, configuration.py:272) - option off or not.
        _SECTION_GATED_BY = {
            'GROUNDWATER_MODFLOW': 'modflow_coupling',
            'GLACIER': 'includeGlaciers',
            'WATERDEMAND': 'includeWaterDemand',
            'LAKES_RESERVOIRS': 'includeWaterBodies',
            'RUNOFF_CONCENTRATION': 'includeRunoffConcentration',
            'INFLOW': 'inflow',
            'ENVIRONMENTALFLOW': 'calc_environflow',
            'ROUTING': 'includeRouting',
        }
        # Finer, KEY-level gating: an individual file key CWatM only reads when an
        # [OPTIONS] switch is on (regardless of which section it sits in), mirrored
        # read-only from the returnBool(...)/checkOption(...) guards in cwatm/. Maps
        # the .ini key (lowercase) -> its gating option. All entries here are DIRECT
        # (key active only when the option is on); if a future one is inverted,
        # handle it explicitly. Refs:
        #   initLoad             <- load_initial            (initcondition.py:453-455)
        #   initSave             <- save_initial            (initcondition.py:463-466)
        #   albedoMaps           <- albedo                  (evaporationPot.py:310)
        #   initLoad_pySnowClim  <- load_initial_pySnowClim (snow_frost.py:260-261)
        #   initSave_pySnowClim  <- save_initial_pySnowClim (snow_frost.py:269-271)
        #   smallLakesRes        <- useSmallLakes           (lakes_res_small.py:110-119)
        #   smallwaterBodyDis    <- useSmallLakes           (lakes_res_small.py:137)
        #   EnvironmentalFlowFile<- use_environflow         (environmental_need.py:69-90;
        #                           a separate option from the [OPTIONS] calc_environflow)
        #   irrNonPaddy_fracVegCover <- static_irrigation_map (landcoverType.py:708-709)
        _KEY_GATED_BY = {
            'initload': 'load_initial',
            'initsave': 'save_initial',
            'albedomaps': 'albedo',
            'initload_pysnowclim': 'load_initial_pySnowClim',
            'initsave_pysnowclim': 'save_initial_pySnowClim',
            'smalllakesres': 'useSmallLakes',
            'smallwaterbodydis': 'useSmallLakes',
            'environmentalflowfile': 'use_environflow',
            'irrnonpaddy_fracvegcover': 'static_irrigation_map',
        }
        # Prefix gates: every key starting with the prefix is gated by the option -
        # covers all downscale_wordclim_<var> (prec/tavg/tmin/tmax/...) at once
        # (readmeteo.py:162-179; NOT meteomapssamescale - that only rescales maps).
        _KEY_GATED_BY_PREFIX = {
            'downscale_wordclim': 'usemeteodownscaling',
        }
        # VALUE gates: a file key CWatM reads only when another key's NUMERIC value
        # meets a condition (not a boolean on/off). Mirrors, read-only:
        #   averageBaseflow / averageDischarge  <- swAbstractionFrac < 0
        #     (water_demand.py:719-724: loadmap only inside `if swAbstractionFrac<0`;
        #      with swAbstractionFrac >= 0 a fixed fraction is used and the files are
        #      never read). key (lower) -> (gate key, condition).
        _KEY_GATED_BY_VALUE = {
            'averagebaseflow': ('swAbstractionFrac', 'neg'),
            'averagedischarge': ('swAbstractionFrac', 'neg'),
        }
        disabled = {}                # SECTION (upper) -> gating option name
        # Gating-switch lookup, flattened across ALL sections (key lower -> raw value,
        # later sections win). CWatM reads these switches by key name from its flat
        # dicts - checkOption() from [OPTIONS], but returnBool() from `binding`, and
        # most fine gating switches (load_initial, albedo, useSmallLakes,
        # use_environflow, usemeteodownscaling, ...) live OUTSIDE [OPTIONS]
        # (e.g. [INITITIAL CONDITIONS]/[EVAPORATION]/[LAKES_RESERVOIRS]/[WATERDEMAND]),
        # so scanning only [OPTIONS] would miss them.
        opts = {}
        if config is not None:
            for sec in config.sections():
                try:
                    for k, v in config.items(sec):
                        opts[k.lower()] = v
                except Exception:
                    continue

        def _explicitly_off(opt_name):
            """True only when a gating switch is present and set false/0/no/off.
            A missing switch is treated as active (conservative - never hides a real
            missing-file error), same rule as the section gating."""
            v = (opts.get(opt_name.lower()) or "").strip().lower()
            return v in ('false', '0', 'no', 'off')

        def _value_gate_phrase(key_lower):
            """For a VALUE-gated key, return a short summary phrase when its gate is
            NOT met (so the file is not read), else None. Conservative: an unparseable
            or missing gate value counts as active (flag a real miss)."""
            entry = _KEY_GATED_BY_VALUE.get(key_lower)
            if not entry:
                return None
            gate_key, cond = entry
            raw = (opts.get(gate_key.lower()) or "").strip()
            if cond == 'neg':          # read only when gate value < 0
                try:
                    val = float(raw)
                except (TypeError, ValueError):
                    return None
                if val >= 0:
                    return f"{gate_key} = {raw} >= 0 (read only when < 0)"
            return None

        def _is_modflow_input(key_lower, raw_value):
            """True for a groundwater-MODFLOW input path/file: a PathGroundwaterModflow*
            key itself, or any value routed through a $(PathGroundwaterModflow...)
            placeholder (modflow_basin/topo_modflow/chanRatio/cwatm_modflow_indices/...).
            MODFLOW input is normally preprocessed/optional, so a missing one is soft
            (light orange, no bookmark) rather than a hard red error - but only while
            the GROUNDWATER_MODFLOW section is active (an off section is already dimmed)."""
            if key_lower.startswith('pathgroundwatermodflow'):
                return True
            return 'pathgroundwatermodflow' in (raw_value or '').lower()

        for sec_u, opt in _SECTION_GATED_BY.items():
            if _explicitly_off(opt):
                disabled[sec_u] = opt

        checked = 0
        missing = []
        missing_info = []            # (row, key, value, resolved)
        wrongext_info = []           # (row, key, value, resolved, alt_path)
        bad_placeholders = []        # (row, key, value, [placeholder, ...])
        inactive_info = []           # (row, kind, name, gate); kind = section|key|valuekey|modflow
        options_rows = {}            # [OPTIONS] key (lower) -> its line row
        gated_active_problem = set() # gated SECTION (upper) that is ON and has a red row
        cur_section = ""
        for r, line in enumerate(content.split('\n')):
            s = line.strip()
            if not s or s[0] in '#;':
                continue
            if s[0] == '[':
                cur_section = s.strip('[]').strip()
                continue
            eq = s.find('=')
            if eq <= 0:
                continue
            key = s[:eq].strip()
            value = s[eq + 1:].strip()
            # Remember where each [OPTIONS] switch line sits, so a problem inside an
            # enabled feature's section can be rolled up onto its option line below.
            if cur_section.strip().upper() == 'OPTIONS':
                options_rows[key.lower()] = r
            # Keys starting with 'path' (PathRoot/PathOut/PathMaps/...) are directory
            # paths: always checked, and only for plain existence (strict).
            is_path_key = key[:4].lower() == "path"
            if not is_path_key and not looks_like_path(value):
                continue
            resolved = value
            if config is not None:
                try:
                    resolved = _resolve_settings_placeholders(value, config)
                except Exception:
                    resolved = value
            if not resolved.strip():
                continue
            if '$(' in resolved:
                # Placeholder(s) whose referenced key/section does not exist in the
                # settings file (e.g. $(PathRoot) with no PathRoot entry, or a typo'd
                # $(FILE_PATHS:PathRoot)): a real error - CWatM would fail on it too.
                # Only flaggable when the content parsed (config is not None);
                # otherwise resolution never ran, so skip as before.
                if config is not None:
                    bad = sorted(set(re.findall(r'\$\(([^)]+)\)', resolved)))
                    bad_placeholders.append((r, key, value, bad))
                    # A red row inside an ENABLED gated feature's section rolls up.
                    sec_u = cur_section.upper()
                    if sec_u in _SECTION_GATED_BY and sec_u not in disabled:
                        gated_active_problem.add(sec_u)
                continue
            checked += 1
            if not path_exists(resolved, strict=is_path_key):
                gate = disabled.get(cur_section.upper())
                key_gate = _KEY_GATED_BY.get(key.lower())
                if key_gate is None:
                    kl = key.lower()
                    for _pref, _opt in _KEY_GATED_BY_PREFIX.items():
                        if kl.startswith(_pref):
                            key_gate = _opt
                            break
                alt = None if is_path_key else wrong_extension_alt(resolved)
                vphrase = _value_gate_phrase(key.lower())
                if gate:
                    # Section's option is off - not important: dim, don't flag.
                    inactive_info.append((r, 'section', cur_section, gate))
                elif key_gate and _explicitly_off(key_gate):
                    # This individual key's option is off - not read: dim, don't flag.
                    inactive_info.append((r, 'key', key, key_gate))
                elif vphrase is not None:
                    # Value-gated key whose gate is not met (e.g. averageDischarge with
                    # swAbstractionFrac >= 0): not read - dim, don't flag.
                    inactive_info.append((r, 'valuekey', key, vphrase))
                elif _is_modflow_input(key.lower(), value):
                    # Groundwater-MODFLOW input path/file: preprocessed/optional - dim,
                    # don't flag (separate rule from the section gate).
                    inactive_info.append((
                        r, 'modflow', key,
                        'groundwater MODFLOW input (preprocessed/optional)'))
                elif alt is not None:
                    # The file exists but with a different known raster extension
                    # (likely a wrong-extension typo): orange, NO bookmark.
                    wrongext_info.append((r, key, value, resolved, alt))
                else:
                    missing.append(r)
                    missing_info.append((r, key, value, resolved))
                    # A missing file inside an ENABLED gated feature's section rolls
                    # up onto that feature's [OPTIONS] switch line too.
                    sec_u = cur_section.upper()
                    if sec_u in _SECTION_GATED_BY and sec_u not in disabled:
                        gated_active_problem.add(sec_u)

        # Semantic checks (date ordering, ...) - mark their rows too.
        semantic = self._semantic_settings_problems(content, config, base_dir)
        semantic_rows = [r for r, _ in semantic if r is not None]

        placeholder_rows = [r for r, _k, _v, _b in bad_placeholders]
        # Roll-up: an ENABLED feature whose section has a red row gets its [OPTIONS]
        # switch line marked red + bookmarked too (points the user at the culprit
        # option). Only when the option line actually exists in the file.
        rollup = []                  # (option_row, option_name, section_upper)
        for sec_u in sorted(gated_active_problem):
            opt = _SECTION_GATED_BY.get(sec_u)
            orow = options_rows.get(opt.lower()) if opt else None
            if orow is not None:
                rollup.append((orow, opt, sec_u))
        rollup_rows = [orow for orow, _o, _s in rollup]
        mark_rows = missing + placeholder_rows + semantic_rows + rollup_rows
        self.text_area.set_error_rows(mark_rows)
        # Missing files in disabled sections / behind an off key-option:
        # dimmed orange, NO bookmark.
        self.text_area.set_inactive_rows([r for r, _k, _n, _g in inactive_info])
        # Wrong-extension (file exists under another raster extension):
        # clear orange, NO bookmark.
        self.text_area.set_wrongext_rows([r for r, _k, _v, _res, _alt in wrongext_info])
        if mark_rows:
            self.text_area.bookmark_rows(mark_rows)

        # Summary to the output box. When Configure ▸ 'Write output box' is on (and
        # a run is not already writing the log), mirror this whole summary into the
        # output-box file too - append_to_cwatminfo writes to the open handle.
        _own_output_file = False
        if getattr(self, "_write_output_enabled", False):
            _own_output_file = self._open_output_file_note("Check settingsfile")
        try:
            self._write_check_summary(
                checked, missing_info, inactive_info, wrongext_info,
                bad_placeholders, semantic, rollup)
        finally:
            if _own_output_file:
                self._finalize_output_file()
        skip_note = (f", {len(inactive_info)} dimmed (option off)"
                     if inactive_info else "")
        rollup_note = f", {len(rollup)} enabled option(s) flagged" if rollup else ""
        self.status_bar.showMessage(
            f"Check settingsfile: {len(missing)} missing file(s), "
            f"{len(bad_placeholders)} unresolved placeholder(s), "
            f"{len(semantic)} settings problem(s){skip_note}{rollup_note} "
            "- see the output box")

    def _write_check_summary(self, checked, missing_info, inactive_info,
                             wrongext_info, bad_placeholders, semantic, rollup):
        """Emit the Check settingsfile summary via append_to_cwatminfo (output box +,
        when opened by the caller, the output-box log file)."""
        self.append_to_cwatminfo("==== Check settingsfile ====")
        if not missing_info:
            extra = " (except disabled sections/keys, see below)" if inactive_info else ""
            self.append_to_cwatminfo(
                f"Checked {checked} filename value(s) - all files exist{extra}.")
        else:
            self.append_to_cwatminfo(
                f"{len(missing_info)} of {checked} file value(s) missing "
                "(marked red + bookmarked; F2/Shift+F2 to jump):")
            # Only the problem lines - one compact line each (resolved path appended
            # when it differs from the written value).
            for r, key, value, resolved in missing_info:
                extra = f"   ->  {resolved}" if resolved.strip() != value.strip() else ""
                self.append_to_cwatminfo(
                    f"  line {r + 1}: {key} = {value}{extra}", is_error=True)
        # Missing files whose gating option is off: one quiet note per section/key
        # (the lines are dimmed orange in the editor, not red/bookmarked).
        if inactive_info:
            per = {}
            for _r, kind, name, gate in inactive_info:
                per[(kind, name, gate)] = per.get((kind, name, gate), 0) + 1
            for (kind, name, gate), n in per.items():
                if kind in ('valuekey', 'modflow'):
                    # gate is already a full phrase (e.g. "swAbstractionFrac = 0.8 >= 0 …"
                    # or "groundwater MODFLOW input …").
                    self.append_to_cwatminfo(
                        f"skipped {name} - {gate} "
                        f"({n} missing file value(s) dimmed, not flagged)")
                    continue
                label = f"[{name}]" if kind == 'section' else name
                self.append_to_cwatminfo(
                    f"skipped {label} - {gate} = False "
                    f"({n} missing file value(s) dimmed, not flagged)")
        # Wrong-extension: the file exists under a different raster extension
        # (marked orange, NOT bookmarked - a likely typo, not a hard miss).
        if wrongext_info:
            self.append_to_cwatminfo(
                f"{len(wrongext_info)} wrong extension (file exists as another "
                "type; marked orange, not bookmarked):")
            for r, key, value, resolved, alt in wrongext_info:
                self.append_to_cwatminfo(
                    f"  line {r + 1}: {key} = {value}   ->  exists as "
                    f"{os.path.basename(alt)}")
        # Unresolvable placeholders (marked red + bookmarked, like missing files).
        if bad_placeholders:
            self.append_to_cwatminfo(
                f"{len(bad_placeholders)} unresolved placeholder(s) - the referenced "
                "key does not exist in the settings file:")
            for r, key, value, bad in bad_placeholders:
                names = ', '.join(f'$({b})' for b in bad)
                self.append_to_cwatminfo(
                    f"  line {r + 1}: {key} = {value}   ->  {names} not defined",
                    is_error=True)
        # Semantic problems (marked red + bookmarked, like missing files).
        if semantic:
            self.append_to_cwatminfo(
                f"{len(semantic)} settings problem(s):")
            for r, msg in semantic:
                where = f"line {r + 1}: " if r is not None else ""
                self.append_to_cwatminfo(f"  {where}{msg}", is_error=True)
        elif not missing_info:
            self.append_to_cwatminfo("Date order (StepStart/SpinUp/StepEnd) OK.")
        # Enabled options flagged because their feature's section has a problem.
        if rollup:
            self.append_to_cwatminfo(
                f"{len(rollup)} enabled option(s) flagged - a problem exists in the "
                "section they switch on (marked red + bookmarked):")
            for orow, opt, sec_u in rollup:
                self.append_to_cwatminfo(
                    f"  line {orow + 1}: {opt} = True   ->  see the red line(s) "
                    f"in [{sec_u}]", is_error=True)

    def _semantic_settings_problems(self, content, config=None, base_dir=""):
        """Semantic (not just file-existence) checks on the settings content. Returns a
        list of (row_index_or_None, message) problems:
        - simulation date ordering StepStart ≤ SpinUp ≤ StepEnd (comparing only values
          that are real dates; SpinUp/StepEnd may legitimately be an integer number of
          timesteps);
        - the run window inside the **meteo forcing** NetCDF time coverage (the most
          common "crashes hours into a run" error) - needs ``config``/``base_dir`` to
          resolve and read the forcing files."""
        from datetime import datetime

        def _find(key):
            """(row_index, value) of the first uncommented ``key = value`` line, or
            (None, None)."""
            for i, line in enumerate(content.split('\n')):
                s = line.strip()
                if not s or s[0] in '#;[':
                    continue
                eq = s.find('=')
                if eq <= 0:
                    continue
                if s[:eq].strip().lower() == key.lower():
                    return i, s[eq + 1:].strip()
            return None, None

        def _as_date(v):
            if v is None:
                return None
            for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
                try:
                    return datetime.strptime(v.strip(), fmt)
                except ValueError:
                    continue
            return None

        problems = []
        rs, vs = _find("StepStart")
        rp, vp = _find("SpinUp")
        re_, ve = _find("StepEnd")
        d_start, d_spin, d_end = _as_date(vs), _as_date(vp), _as_date(ve)

        # StepStart must be a date (CWatM requires it)
        if vs is not None and d_start is None:
            problems.append((rs, f"StepStart = {vs} is not a valid date (dd/mm/yyyy)."))
        if d_start and d_spin and d_spin < d_start:
            problems.append(
                (rp, f"SpinUp ({vp}) is before StepStart ({vs}) - spin-up must be "
                 "on/after the start."))
        if d_start and d_end and d_end < d_start:
            problems.append(
                (re_, f"StepEnd ({ve}) is before StepStart ({vs}) - the run would be "
                 "empty."))
        if d_spin and d_end and d_end < d_spin:
            problems.append(
                (re_, f"StepEnd ({ve}) is before SpinUp ({vp}) - no output would be "
                 "written."))

        # Option dependencies: an option switched ON but missing its required keys, OR a
        # required key that is a PATH which does not exist on disk. Either way the
        # **option's own line** is flagged (so a bad dependency is visible on the option
        # too, not only on the path line). The key may be defined in any section (CWatM
        # flattens them); a commented/absent/empty key counts as "not set".
        _OPTION_REQUIRES = {
            "modflow_coupling": ["path_mf6dll", "PathGroundwaterModflow",
                                 "nameModflowModel", "Modflow_resolution"],
        }
        # Required keys checked only for "is it set" (NOT "does the path exist"):
        # the MODFLOW input dir is preprocessed/optional (same separate rule as
        # _is_modflow_input), so a set-but-missing PathGroundwaterModflow must not
        # flag its option red. path_mf6dll (the solver DLL) still must exist.
        _REQUIRE_SET_ONLY = {"pathgroundwatermodflow"}
        from src.gui.widgets.basin_viewer import _resolve_settings_placeholders

        def _looks_path(v):
            return bool(v) and (v.startswith("$(") or "\\" in v or "/" in v
                                or bool(re.match(r"^[A-Za-z]:", v)))

        def _path_missing(v):
            """(missing, resolved) for a path value (placeholders resolved). An
            unresolvable placeholder is treated as present (not flagged)."""
            try:
                resolved = _resolve_settings_placeholders(v, config) if config else v
            except Exception:
                resolved = v
            resolved = (resolved or "").strip().strip('"')
            if not resolved or "$(" in resolved:
                return False, resolved
            p = resolved
            if not os.path.isabs(p) and base_dir:
                p = os.path.join(base_dir, p)
            return (not os.path.exists(p)), resolved

        for opt, required in _OPTION_REQUIRES.items():
            r_opt, v_opt = _find(opt)
            if (v_opt or "").strip().lower() not in ("true", "1", "yes", "on"):
                continue
            issues = []
            for k in required:
                vk = (_find(k)[1] or "").strip()
                if not vk:
                    issues.append(f"{k} (not set)")
                elif _looks_path(vk) and k.lower() not in _REQUIRE_SET_ONLY:
                    miss, resolved = _path_missing(vk)
                    if miss:
                        extra = f" -> {resolved}" if resolved != vk else ""
                        issues.append(f"{k}{extra} (missing)")
            if issues:
                problems.append((r_opt, f"{opt} = True but: {'; '.join(issues)}."))

        # Output keywords: every `out_*` key (outside [OPTIONS]) must follow CWatM's
        # output grammar, mirrored from cwatm/management_modules/ (do not edit there):
        #   configuration.py: `out_*` = output key; `out_*_dir` = output directory;
        #     `out_tss_*` = timeseries; anything else = map;
        #   globals.py: outputTypMap / outputTypTss / outputTypTss2 (the valid types);
        #   output.py appendinfo: maps only match `out_map_<type>` exactly - a bad map
        #     key (e.g. OUT_MAP_AreaSum_MonthTot: AreaSum is TSS-only) is **silently
        #     ignored** by CWatM, so F4 is the only place the user learns about it.
        _TSS_TYPES = ('daily', 'monthtot', 'monthavg', 'monthend', 'annualtot',
                      'annualavg', 'annualend', 'totaltot', 'totalavg')
        _MAP_TYPES = _TSS_TYPES + ('monthmid', 'totalend', 'once', '12month')
        _AGG = ('areasum', 'areaavg')

        def _out_key_problem(key):
            """Error message for an invalid `out_*` key, or None if it is valid."""
            k = key.lower()
            if k.endswith('_dir'):
                return None                      # out_*_dir = output directory, valid
            rest = k[4:]                          # after 'out_'
            if rest.startswith('tss_'):
                parts = rest[4:].split('_')
                if parts[-1] not in _TSS_TYPES:
                    return (f"'{parts[-1]}' is not a valid TSS time step - use one "
                            f"of: {', '.join(_TSS_TYPES)}.")
                if len(parts) == 1:
                    return None                   # out_tss_<type>
                if len(parts) == 2 and parts[0] in _AGG:
                    return None                   # out_tss_<areasum|areaavg>_<type>
                return (f"'{'_'.join(parts[:-1])}' is not a valid TSS aggregation - "
                        "use OUT_TSS_<type> (point value), or "
                        "OUT_TSS_AreaSum_<type> / OUT_TSS_AreaAvg_<type>.")
            if rest.startswith('map_'):
                parts = rest[4:].split('_')
                if parts[0] in _AGG:
                    return (f"'{parts[0]}' is only available for timeseries "
                            "(OUT_TSS_AreaSum_... / OUT_TSS_AreaAvg_...), not for "
                            "maps - CWatM silently ignores this key.")
                if len(parts) == 1 and parts[0] in _MAP_TYPES:
                    return None                   # out_map_<type>
                return (f"'{rest[4:]}' is not a valid map time step - use "
                        f"OUT_MAP_<type> with one of: {', '.join(_MAP_TYPES)}.")
            return ("output keys must be OUT_TSS_..., OUT_MAP_... or OUT_..._Dir - "
                    "CWatM silently ignores this key.")

        # Output values: each comma-separated variable name of a (valid) out_* key is
        # checked against the metaNetcdf.xml catalogue (cached in meta_netcdf.py).
        # Mirrors CWatM's runtime check (output.py checkifvariableexists, Error 132):
        # case-sensitive, `[index]` stripped, the special 'WaterCycle' allowed; a
        # first item of "None" (or empty) means "output disabled" (configuration.py
        # splitout) and is skipped. Best-effort: if the xml is unreadable, or a token
        # is not a plain identifier, nothing is flagged.
        import difflib
        from src.gui.utils.meta_netcdf import all_varnames
        _known = all_varnames()
        _known_lower = {k.lower(): k for k in _known}

        # Multi-dimensional model variables that need an index in an output value
        # (e.g. actualET -> actualET[1]) - mirrored from the allocation lists in
        # cwatm/hydrological_modules/ (read-only, per the hard rule):
        #   landcoverType.py landcoverAll+landcoverVars -> (6, cells)  [_DIM6]
        #   landcoverType.py landcoverVarsSoil + w1/w2/w3 -> (4, cells) [_DIM4]
        #   landcoverType.py soilVars -> (soilLayers=3, 4, cells)       [_DIM3X4]
        #   soil.py soilDepthLayer -> (soilLayers=3, cells)             [_DIM3]
        #   evaporation.py crop lists -> (len(Crops), cells)            [_DIMCROP]
        _DIM6 = frozenset((
            'fracVegCover', 'interceptStor', 'availWaterInfiltration', 'interceptEvap',
            'directRunoff', 'openWaterEvap', 'irrTypeFracOverIrr', 'fractionArea',
            'totAvlWater', 'cropKC', 'cropKC_landCover', 'effSatAt50',
            'effPoreSizeBetaAt50', 'rootZoneWaterStorageMin',
            'rootZoneWaterStorageRange', 'totalPotET', 'potTranspiration',
            'soilWaterStorage', 'infiltration', 'actBareSoilEvap', 'landSurfaceRunoff',
            'actTransTotal', 'gwRecharge', 'gwRecharge2', 'interflow', 'actualET',
            'pot_irrConsumption', 'act_irrConsumption', 'irrDemand', 'topWaterLayer',
            'perc3toGW', 'capRiseFromGW', 'netPercUpper', 'netPerc', 'prefFlow'))
        _DIM4 = frozenset((
            'arnoBeta', 'rootZoneWaterStorageCap', 'rootZoneWaterStorageCap12',
            'perc1to2', 'perc2to3', 'theta1', 'theta2', 'theta3', 'w1', 'w2', 'w3'))
        _DIM3X4 = frozenset(('adjRoot', 'perc', 'capRise', 'rootDepth', 'storCap'))
        _DIM3 = frozenset(('soildepth',))
        _DIMCROP = frozenset((
            'irrM3_Paddy_month_segment', 'irr_Paddy_month', 'irr_crop',
            'irr_crop_month', 'irrM3_crop_month_segment', 'ratio_a_p_nonIrr',
            'ratio_a_p_Irr', 'fracCrops_IrrLandDemand', 'fracCrops_Irr',
            'areaCrops_Irr_segment', 'areaCrops_nonIrr_segment',
            'fracCrops_nonIrrLandDemand', 'fracCrops_nonIrr', 'activatedCrops',
            'monthCounter', 'currentKC', 'totalPotET_month', 'PET_cropIrr_m3',
            'actTransTotal_month_Irr', 'actTransTotal_month_nonIrr', 'currentKY',
            'Yield_Irr', 'Yield_nonIrr', 'actTransTotal_crops_Irr',
            'actTransTotal_crops_nonIrr', 'PotET_crop', 'PotETaverage_crop_segments',
            'totalPotET_month_segment', 'ET_crop_nonIrr', 'ET_crop_Irr',
            'ratio_a_p_nonIrr_daily', 'ratio_a_p_Irr_daily'))
        _HINT6 = "0..5 = forest, grassland, irrPaddy, irrNonPaddy, sealed, water"
        _HINT4 = "0..3 = forest, grassland, irrPaddy, irrNonPaddy"
        _HINT3 = "0..2 = soil layer"

        def _num(s):
            try:
                return int(s.strip())
            except ValueError:
                return None

        def _dim_problem(base, idx):
            """Message when the index/indices of ``base`` don't match its dimension,
            or None. Unknown variables with an index are NOT flagged (other modules
            allocate 2-D vars we don't track)."""
            if base in _DIM6 or base in _DIM4 or base in _DIM3:
                n, hint = ((6, _HINT6) if base in _DIM6 else
                           (4, _HINT4) if base in _DIM4 else (3, _HINT3))
                kind = "per-soil-layer" if base in _DIM3 else "per-land-cover"
                if len(idx) != 1:
                    return (f"'{base}' is a {kind} array - it needs one index, "
                            f"e.g. '{base}[1]' ({hint}).")
                i = _num(idx[0])
                if i is None or not 0 <= i < n:
                    return f"index '[{idx[0]}]' is invalid for '{base}' - use {hint}."
            elif base in _DIM3X4:
                if len(idx) != 2:
                    return (f"'{base}' is a (soil layer x land cover) array - it "
                            f"needs two indices, e.g. '{base}[0][1]'.")
                i0, i1 = _num(idx[0]), _num(idx[1])
                if i0 is None or not 0 <= i0 < 3:
                    return (f"first index '[{idx[0]}]' is invalid for '{base}' "
                            f"({_HINT3}).")
                if i1 is None or not 0 <= i1 < 4:
                    return (f"second index '[{idx[1]}]' is invalid for '{base}' "
                            f"({_HINT4}).")
            elif base in _DIMCROP:
                if len(idx) != 1 or _num(idx[0]) is None or _num(idx[0]) < 0:
                    return (f"'{base}' is a per-crop array - it needs a crop index, "
                            f"e.g. '{base}[0]'.")
            return None

        def _out_value_problems(value):
            """List of messages for unknown output-variable names in ``value``."""
            if not _known:
                return []
            items = [v.strip() for v in value.split(',')]
            if not items or items[0] in ("", "None"):
                return []
            msgs = []
            for it in items:
                m = re.match(r'^([A-Za-z_]\w*)((?:\[[^\]]*\])*)$', it)
                if not m:
                    continue
                base = m.group(1)
                idx = re.findall(r'\[([^\]]*)\]', m.group(2))
                if base == 'WaterCycle':
                    continue
                if base not in _known:
                    hit = _known_lower.get(base.lower()) or (
                        'WaterCycle' if base.lower() == 'watercycle' else None)
                    if hit:
                        msgs.append(f"'{base}' has the wrong case - CWatM is "
                                    f"case-sensitive, use '{hit}'.")
                    else:
                        closest = difflib.get_close_matches(base, _known, n=1)
                        extra = f" (closest: '{closest[0]}')" if closest else ""
                        msgs.append(f"variable '{base}' is not in "
                                    f"cwatm/metaNetcdf.xml{extra}.")
                    continue
                dmsg = _dim_problem(base, idx)
                if dmsg:
                    msgs.append(dmsg)
            return msgs

        section = ""
        for i, line in enumerate(content.split('\n')):
            s = line.strip()
            if not s or s[0] in '#;':
                continue
            if s.startswith('['):
                section = s.strip('[]').strip().upper()
                continue
            eq = s.find('=')
            if eq <= 0:
                continue
            key = s[:eq].strip()
            if section == "OPTIONS" or key.lower()[:4] != "out_":
                continue
            msg = _out_key_problem(key)
            if msg:
                problems.append((i, f"{key}: {msg}"))
            elif not key.lower().endswith('_dir'):
                for vmsg in _out_value_problems(s[eq + 1:].strip()):
                    problems.append((i, f"{key}: {vmsg}"))

        # Forcing coverage: is [StepStart..StepEnd] inside the meteo forcing time axis?
        # Only when StepStart is a real date; StepEnd checked only if it is a date too.
        if d_start is not None:
            rng = self._forcing_time_range(content, config, base_dir)
            if rng is not None:
                key, fkey_row, tmin, tmax = rng
                fmt = lambda d: d.strftime("%d/%m/%Y")
                if d_start < tmin:
                    problems.append(
                        (rs, f"StepStart ({vs}) is before the forcing data starts "
                         f"({fmt(tmin)}, from {key}) - no forcing for the first steps."))
                if d_end is not None and d_end > tmax:
                    problems.append(
                        (re_, f"StepEnd ({ve}) is after the forcing data ends "
                         f"({fmt(tmax)}, from {key}) - the run will fail when it runs "
                         "out of forcing."))
        return problems

    def _forcing_time_range(self, content, config, base_dir):
        """Time coverage of the meteo forcing: (key, key_row, tmin, tmax) for the first
        forcing entry whose NetCDF files can be read, else None. Reads only the first &
        last (name-sorted) file of the glob, so it is cheap even for many yearly files.
        Best-effort - any read error just returns None (never breaks the F4 check)."""
        if config is None:
            return None
        import glob as _glob
        from datetime import datetime
        from src.gui.widgets.basin_viewer import _resolve_settings_placeholders

        def _key(name):
            for i, line in enumerate(content.split('\n')):
                s = line.strip()
                if not s or s[0] in '#;[' or '=' not in s:
                    continue
                k, v = s.split('=', 1)
                if k.strip().lower() == name.lower():
                    return i, v.strip().strip('"')
            return None, None

        def _natkey(path):
            # Numeric-aware key so pr_2.nc sorts before pr_10.nc (a plain lexical
            # sort would put pr_10/pr_12 before pr_2/pr_9 and pick the wrong first/
            # last file, giving a bogus forcing time range for non-zero-padded names).
            return [int(tok) if tok.isdigit() else tok.lower()
                    for tok in re.split(r'(\d+)', path)]

        def _files(value):
            try:
                resolved = _resolve_settings_placeholders(value, config)
            except Exception:
                resolved = value
            resolved = (resolved or "").strip().strip('"')
            if not resolved or '$(' in resolved:
                return []
            if not os.path.isabs(resolved) and base_dir:
                resolved = os.path.join(base_dir, resolved)
            pats = [resolved] if any(c in resolved for c in '*?') \
                else [resolved, resolved + '*', resolved + '.nc']
            for pat in pats:
                fs = sorted((f for f in _glob.glob(pat)
                             if f.lower().endswith('.nc') and os.path.isfile(f)),
                            key=_natkey)
                if fs:
                    return fs
            return []

        def _to_dt(v):
            try:
                import pandas as pd
                return pd.Timestamp(v).to_pydatetime()
            except Exception:
                try:
                    return datetime(int(v.year), int(v.month), int(v.day))
                except Exception:
                    return None

        def _range(path):
            try:
                import xarray as xr
                with xr.open_dataset(path, decode_times=True) as ds:
                    tname = next((d for d in ds.dims if 'time' in str(d).lower()), None)
                    if not tname or tname not in ds.coords:
                        return None, None
                    t = ds[tname].values
                    if len(t) == 0:
                        return None, None
                    return _to_dt(t[0]), _to_dt(t[-1])
            except Exception:
                log.debug("forcing time read failed: %s", path, exc_info=True)
                return None, None

        # Precipitation first (canonical), then temperature / evaporation.
        for name in ("PrecipitationMaps", "TavgMaps", "E0Maps", "ETMaps"):
            row, value = _key(name)
            if not value:
                continue
            files = _files(value)
            if not files:
                continue
            tmin, _ = _range(files[0])
            _, tmax = _range(files[-1]) if len(files) > 1 else (None, tmin)
            if len(files) == 1:
                tmin, tmax = _range(files[0])
            if tmin is not None and tmax is not None and tmin <= tmax:
                return name, row, tmin, tmax
        return None

    def _forcing_range_for_calendar(self):
        """(QDate, QDate) meteo-forcing coverage for the Start/Spin/End calendar
        popups (CWatMCalendar dims days outside it), or None when unknown. Uses the
        same _forcing_time_range as the F4 semantic check; called lazily by the
        DateManager cache the first time a popup opens after a file load."""
        try:
            content = self.text_area.toPlainText()
            if not content.strip():
                return None
            config = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                config.read_string(content)
            except Exception:
                return None
            rng = self._forcing_time_range(content, config, self.working_dir())
            if rng is None:
                return None
            _key, _row, tmin, tmax = rng
            return (QDate(tmin.year, tmin.month, tmin.day),
                    QDate(tmax.year, tmax.month, tmax.day))
        except Exception:
            log.debug("forcing range for calendar failed", exc_info=True)
            return None

    def clear_checking(self):
        """Remove the red marks and the check-owned bookmarks that Check settingsfile
        added (leaves the user's own bookmarks). Reached via the Check settingsfile
        toggle (F4 a second time); see toggle_check_settings."""
        try:
            self.text_area.clear_checking()
        except Exception:
            log.debug("clear_checking failed", exc_info=True)
        self.append_to_cwatminfo("==== Clear checking: removed Check settingsfile marks ====")
        self.status_bar.showMessage("Cleared Check settingsfile marks and bookmarks")

    def _checking_active(self):
        """True when Check settingsfile marks (red / dimmed-orange rows) are currently
        shown in the editor - i.e. there is something for Clear checking to remove."""
        ed = getattr(self, "text_area", None)
        if ed is None:
            return False
        try:
            return bool(getattr(ed, "_error_rows", None)
                        or getattr(ed, "_inactive_rows", None)
                        or getattr(ed, "_wrongext_rows", None))
        except Exception:
            return False

    def _refresh_check_settings_label(self):
        """Flip the single Check/Clear toggle action's label + tooltip to match the
        current state (marks shown -> 'Clear checking', else -> 'Check settingsfile')."""
        act = getattr(self, "check_settings_action", None)
        if act is None:
            return
        try:
            if self._checking_active():
                act.setText("Clear checking")
                act.setToolTip("Remove the red marks and bookmarks set by Check "
                               "settingsfile. Press again (F4) to re-check.")
            else:
                act.setText("Check settingsfile")
                act.setToolTip("Check every filename value in the settings; mark + "
                               "bookmark lines whose file does not exist. Press again "
                               "(F4) to clear the marks.")
        except RuntimeError:
            pass  # the QAction's C++ object was deleted

    def toggle_check_settings(self):
        """Settings ▸ Check settingsfile (F4): a single toggle. When no check marks are
        shown, run the check; when they are, clear them - then relabel the menu item."""
        if self._checking_active():
            self.clear_checking()
        else:
            self.check_settingsfile()
        self._refresh_check_settings_label()

    def open_excel_sheet(self, sheet_name, release_sheet=None):
        """Excel menu: open ``sheet_name`` of the settings Excel_settings_file in an
        editable, colour-preserving table (used by Excel ▸ Crops / Reservoirs).
        ``release_sheet`` adds a "Release" button that opens that companion sheet
        (used by Reservoirs -> Reservoirs_downstream)."""
        import configparser
        try:
            content = self.text_area.toPlainText()
        except Exception:
            content = ""
        if not content.strip():
            self.status_bar.showMessage("Load a settings file first")
            return
        try:
            config = configparser.ConfigParser(interpolation=None, strict=False)
            config.read_string(content)
        except Exception:
            config = None
        if config is None:
            QMessageBox.warning(self, sheet_name, "Could not parse the settings file.")
            return
        from src.gui.widgets.basin_viewer import (
            _find_setting_value, _resolve_settings_placeholders)
        excel = _find_setting_value(config, "Excel_settings_file")
        if not excel:
            QMessageBox.information(
                self, sheet_name,
                "No 'Excel_settings_file' entry found in the settings file.")
            return
        resolved = _resolve_settings_placeholders(excel.strip(), config)
        if "$(" in resolved:
            QMessageBox.warning(
                self, sheet_name, f"Could not resolve the Excel path:\n{excel}")
            return
        if not os.path.isabs(resolved):
            base = self.working_dir()
            if base:
                resolved = os.path.join(base, resolved)
        if not os.path.exists(resolved):
            QMessageBox.warning(
                self, sheet_name, f"The Excel file does not exist:\n{resolved}")
            return
        try:
            from src.gui.widgets.excel_sheet_window import ExcelSheetWindow
            win = ExcelSheetWindow(resolved, sheet_name, self, release_sheet=release_sheet)
            win.exec()
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, sheet_name, f"Could not open the Excel sheet:\n{e}")

    def create_pathout_folder(self):
        """Create the PathOut folder (placeholders resolved) if it does not exist."""
        if not self.file_manager.has_file_loaded():
            self.status_bar.showMessage("No file loaded")
            return
        try:
            content = self.original_content or self.text_display.get_content()
        except Exception:
            content = ""

        from src.gui.widgets.basin_viewer import pathout_exists  # lazy (§4.1)
        exists, resolved = pathout_exists(content)
        if not resolved:
            self.status_bar.showMessage("No PathOut defined in the settings file")
            return
        if exists:
            self.status_bar.showMessage(f"PathOut already exists: {resolved}")
            self._update_warnings()
            return
        try:
            os.makedirs(resolved, exist_ok=True)
            self.status_bar.showMessage(f"Created PathOut folder: {resolved}")
        except Exception as e:
            self.status_bar.showMessage(f"Could not create PathOut folder: {e}")
            print(f"Error creating PathOut folder: {e}", file=sys.stderr)
            return
        # Refresh warnings so the "PathOut does not exists" message clears
        self._update_warnings()

    def set_gauge(self):
        """Set the Gauges field to the cell centre with the largest upstream area
        (ups.nc) that lies inside the mask map."""
        if not self.file_manager.has_file_loaded():
            self.status_bar.showMessage("No file loaded")
            return
        # Make sure the in-memory mask is available
        self._rebuild_mask_cache()
        try:
            content = self.original_content or self.text_display.get_content()
        except Exception:
            content = ""
        settings_file = self.file_manager.get_current_file_path()
        from src.gui.widgets.basin_viewer import find_largest_ups_gauge  # lazy (§4.1)
        result = find_largest_ups_gauge(settings_file, content, self._mask_context)
        if result is None:
            self.status_bar.showMessage(
                "Set Gauge: could not determine a gauge location (check MaskMap / ups.nc)")
            return
        lon, lat = result
        # Format the coordinates to 4 decimal places
        coords = f"{lon:.4f} {lat:.4f}"
        # Setting the field triggers the auto-apply + colour re-check
        self.gauges_field.setText(coords)
        self.status_bar.showMessage(
            f"Gauge set to {coords} (largest upstream area in mask)")

    def add_output_watercycle(self):
        """Append 'OUT_TSS_AreaSum_MonthTot = WaterCycle' as the last line of the settings
        file (in memory, not saved), unless a WaterCycle entry already exists."""
        if not self.file_manager.has_file_loaded():
            self.status_bar.showMessage("No file loaded")
            return
        line_to_add = "OUT_TSS_AreaSum_MonthTot = WaterCycle"
        try:
            content = self.original_content or self.text_display.get_content()
        except Exception:
            content = ""

        # Skip if a WaterCycle value already exists for that key
        for line in content.split('\n'):
            s = line.strip()
            if s.startswith('#') or s.startswith(';') or '=' not in s:
                continue
            key, value = s.split('=', 1)
            if key.strip().lower() == 'out_tss_areasum_monthtot' and \
               'watercycle' in [v.lower() for v in value.split()]:
                self.status_bar.showMessage("WaterCycle output already present")
                return

        # Insert the line under the [OUTPUT] section (in memory only)
        lines = content.split('\n')
        out_start = None
        for i, line in enumerate(lines):
            if line.strip().lower() == '[output]':
                out_start = i
                break

        if out_start is None:
            # No [OUTPUT] section - create one at the end
            updated = content.rstrip('\n') + '\n\n[OUTPUT]\n' + line_to_add + '\n'
        else:
            # Find the end of the [OUTPUT] section (next section header or EOF)
            insert_at = len(lines)
            for j in range(out_start + 1, len(lines)):
                s = lines[j].strip()
                if s.startswith('[') and s.endswith(']'):
                    insert_at = j
                    break
            # Place it right after the last non-blank entry of the section
            while insert_at - 1 > out_start and lines[insert_at - 1].strip() == '':
                insert_at -= 1
            lines.insert(insert_at, line_to_add)
            updated = '\n'.join(lines)

        self.original_content = updated
        self.text_display.set_original_content(updated)
        self.parse_file(content=updated, load=False, expand_all=False)
        self._set_save_dirty(True)
        self.status_bar.showMessage("Added WaterCycle output under [OUTPUT] (not saved)")

    def add_output_variables(self):
        """Tools ▸ Add output variables: open the picker of metaNetcdf.xml [Array]
        output variables that fit the current [OPTIONS]. Clicking one inserts it at the
        editor cursor (only on an OUT_TSS_… / OUT_MAP_… line)."""
        if not self.file_manager.has_file_loaded():
            self.status_bar.showMessage("Load a settings file first")
            return
        try:
            from src.gui.widgets.output_variables_window import open_output_variables
            self._output_variables_window = open_output_variables(self)
        except Exception:
            from src.gui.utils.gui_log import get_logger
            get_logger("main_window").debug("Add output variables failed", exc_info=True)
            self.status_bar.showMessage("Could not open the output-variables picker")

    def _default_output_file(self):
        """Default output-box file: <PathOut>/cwatm_out.txt (placeholders resolved).
        Falls back to the settings-file directory if PathOut cannot be resolved."""
        try:
            content = self.original_content or self.text_display.get_content()
        except Exception:
            content = ""
        from src.gui.widgets.basin_viewer import pathout_exists  # lazy (§4.1)
        _, resolved = pathout_exists(content)
        if resolved:
            return os.path.join(resolved, "cwatm_out.txt")
        file_path = self.file_manager.get_current_file_path()
        if file_path:
            return os.path.join(os.path.dirname(file_path), "cwatm_out.txt")
        return "cwatm_out.txt"

    def _output_file(self):
        """Effective output-box file: the custom one set via Configure, else the
        default (<PathOut>/cwatm_out.txt)."""
        return self._output_file_override or self._default_output_file()

    def _on_write_output_toggled(self, checked):
        """Mirror the 'Write output box' state to a bool (the native checkmark shows
        the toggle state, like Show Header and the other toggles)."""
        self._write_output_enabled = checked

    def _on_run_subprocess_toggled(self, checked):
        """Mirror the 'Run model in separate process' state to a bool (read by
        run_controller.run_cwatm) and persist it."""
        self._run_subprocess_enabled = checked
        self._settings.setValue("run/subprocess", checked)

    def _on_load_previous_toggled(self, checked):
        """Persist the 'Load previous settings at start' state. When on, cwatm_gui.py
        re-opens the last settings file at the next startup."""
        try:
            self._settings.setValue("startup/load_previous", bool(checked))
        except Exception:
            log.debug("persist load_previous failed", exc_info=True)

    def _on_use_modflow_toggled(self, checked):
        """Persist the 'Use Modflow' state and pre-warm flopy in the background when on
        (heavy import kept off the GUI thread). Called at menu build with the persisted
        value, so 'on from the beginning' warms flopy at startup too."""
        try:
            self._settings.setValue("modflow/enabled", bool(checked))
        except Exception:
            log.debug("persist modflow/enabled failed", exc_info=True)
        if checked:
            try:
                from src.gui.utils import modflow
                modflow.warm_flopy()
            except Exception:
                log.debug("flopy pre-warm failed", exc_info=True)

    def _on_bookmark_change_toggled(self, checked):
        """Mirror the 'Bookmark Change' state to the editor and persist it. When on,
        changed lines get auto-bookmarked."""
        try:
            self._settings.setValue("editor/bookmark_change", bool(checked))
        except Exception:
            pass
        try:
            if getattr(self, "text_area", None) is not None:
                self.text_area.set_auto_bookmark_changed(bool(checked))
        except Exception:
            log.debug("set_auto_bookmark_changed failed", exc_info=True)

    def _on_web_picker_toggled(self, checked):
        """Configure > Web-style date picker: switch the Start/Spin/End fields
        between the frameless 📅 popup (on) and the classic drop-down (off)."""
        try:
            self._settings.setValue("display/date_picker_web", bool(checked))
        except Exception:
            pass
        try:
            self.date_manager.set_web_picker(bool(checked))
        except Exception:
            log.debug("web picker toggle failed", exc_info=True)
        # Button visibility changed the date row's width -> re-sync the shared
        # width once the layout has settled
        QTimer.singleShot(0, self._cap_output_box_width)

    def _on_date_timeline_toggled(self, checked):
        """Configure > Date timeline: show/hide the three-handle date timeline."""
        try:
            self._settings.setValue("display/date_timeline", bool(checked))
        except Exception:
            pass
        try:
            self.date_manager.set_timeline_visible(bool(checked))
        except Exception:
            log.debug("date timeline toggle failed", exc_info=True)

    def _on_show_header_toggled(self, checked):
        """Configure > Show Header: show/hide the top banner (CWatM icon + title +
        interface text + IIASA logo). Off = everything below moves up."""
        try:
            self._settings.setValue("display/show_header", bool(checked))
        except Exception:
            pass
        try:
            if getattr(self, "_banner_widget", None) is not None:
                self._banner_widget.setVisible(bool(checked))
        except Exception:
            log.debug("show header toggle failed", exc_info=True)

    def _update_output_tooltip(self):
        """Refresh the 'Write output box' tooltip: what it does, plus the current
        effective output file path (custom or default <PathOut>/cwatm_out.txt)."""
        try:
            path = self._output_file()
        except Exception:
            path = ""
        tip = "Writes input to output box to disk, but can slow down a run"
        tip += f"\nOutput box file: {path}"
        if self._output_file_override:
            tip += "  (custom)"
        try:
            self.write_output_action.setToolTip(tip)
        except RuntimeError:
            log.debug("write-output action already deleted - tooltip not updated")

    def _default_basemap(self):
        """Return the default basemap chosen in Configure ▸ Default openstreet map.
        This is now a Show Basin2 WMS layer name (e.g. "OSM-WMS"); the classic Show
        Basin ignores an unknown key and falls back to its own "standard" tiles."""
        return self._settings.value("basin/default_basemap", "OSM-WMS")

    def _set_default_basemap(self, key):
        """Persist the default OpenStreetMap basemap chosen in the Configure menu."""
        self._settings.setValue("basin/default_basemap", key)
        self.status_bar.showMessage(f"Default OpenStreetMap basemap: {key}")

    def set_show_decimals(self):
        """Configure > Show Decimals: ask for the number of decimals shown throughout
        all displays and persist it. Newly opened displays pick it up immediately."""
        value, ok = QInputDialog.getInt(
            self, "Show Decimals",
            "Number of decimals shown in all displays:",
            display_format.get_decimals(), 0, 12, 1)
        if not ok:
            return
        display_format.set_decimals(value)
        self._settings.setValue("display/decimals", display_format.get_decimals())
        self.status_bar.showMessage(
            f"Displays now show {display_format.get_decimals()} decimals")

    def set_transparency(self):
        """Configure > Transparency: ask for the initial map transparency (0-100) used
        by NetCDF and Show Basin when they open, and persist it."""
        value, ok = QInputDialog.getInt(
            self, "Transparency",
            "Initial map transparency for NetCDF / Show Basin (0-100):\n"
            "0 = OSM hidden (only the data); 100 = OSM fully visible (data 50% on top)",
            display_format.get_transparency(), 0, 100, 1)
        if not ok:
            return
        display_format.set_transparency(value)
        self._settings.setValue("display/transparency", display_format.get_transparency())
        self.status_bar.showMessage(
            f"Initial map transparency set to {display_format.get_transparency()}%")

    def _set_animal(self, name):
        """Configure > Select animal: persist the chosen cameo animal and apply it to
        the live discharge sparkline."""
        self._settings.setValue("display/animal", name)
        spark = getattr(self, "discharge_sparkline", None)
        if spark is not None:
            try:
                spark.set_animal(name)
            except RuntimeError:
                pass
        self.status_bar.showMessage(f"Sparkline animal: {name}")

    def set_output_box_file(self):
        """Let the user pick a custom output-box file (location + name), kept in
        memory. The default shown is <PathOut>/cwatm_out.txt."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Set output box file", self._output_file(),
            "Text files (*.txt);;All files (*)")
        if path:
            self._output_file_override = path
            self.status_bar.showMessage(f"Output box file set to: {path}")

    def open_pathout_folder(self):
        """Tools > Open PathOut Folder: show the resolved PathOut directory in the
        system file browser."""
        path = self._resolved_pathout_dir()
        if not path:
            self.status_bar.showMessage(
                "PathOut does not exist - use Tools/Create PathOut Folder first")
            return
        try:
            os.startfile(path)
        except Exception as e:
            log.warning("could not open PathOut folder", exc_info=True)
            self.status_bar.showMessage(f"Could not open PathOut: {e}")

    # ------------------------------------------------- changed-fields hint (RUN row)
    def _current_field_values(self):
        """Current values of the auto-applied fields (dates / PathOut / MaskMap /
        Gauges), keyed by their display name - for the changed-fields hint."""
        vals = {}
        try:
            start, spin, end = self.date_manager.get_current_dates()
            vals['Start Date'] = start.toString('dd/MM/yyyy') if start else ''
            vals['Spin Date'] = spin.toString('dd/MM/yyyy') if spin else ''
            vals['End Date'] = end.toString('dd/MM/yyyy') if end else ''
        except Exception:
            log.debug("date fields not readable for hint", exc_info=True)
        for label, attr in (('PathOut', 'pathout_field'),
                            ('MaskMap', 'maskmap_field'),
                            ('Gauges', 'gauges_field')):
            field = getattr(self, attr, None)
            if field is not None:
                vals[label] = field.text().strip()
        return vals

    def _capture_field_baseline(self):
        """Remember the current field values as the saved-file state (called on
        load/save via _mark_clean) and clear the changed-fields hint."""
        self._baseline_fields = self._current_field_values()
        self._update_changed_fields_hint()

    def _update_changed_fields_hint(self):
        """Show which fields differ from the loaded/saved file next to RUN CWATM -
        a hint that the run will use the new (unsaved) values."""
        label = getattr(self, 'changed_fields_label', None)
        if label is None:
            return
        if not self._baseline_fields:
            label.setText("")
            return
        current = self._current_field_values()
        changed = [k for k, v in current.items()
                   if self._baseline_fields.get(k, v) != v]
        if changed:
            label.setText("Changed (run uses the new values): " + ", ".join(changed))
        else:
            label.setText("")

    # ------------------------------------------------------- drag & drop of a .ini
    def dragEnterEvent(self, event):
        """Accept a dragged settings file (.ini/.txt)."""
        urls = event.mimeData().urls()
        if urls and urls[0].toLocalFile().lower().endswith(('.ini', '.txt')):
            event.acceptProposedAction()

    def dropEvent(self, event):
        """Load a settings file dropped onto the window."""
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if os.path.isfile(path):
                self.load_recent_file(path)
                event.acceptProposedAction()

    # ------------------------------------------------------------ search & replace
    def replace_text(self):
        """Settings > Replace (Ctrl+H): the combined Find & Replace window,
        Replace tab (see _open_find_dialog)."""
        self._open_find_dialog(1)

    # --------------------------------------------------- metaNetcdf hover tooltips
    def _show_meta_tooltip(self, event):
        """Hovering a CWatM variable name (e.g. 'discharge') in the editor shows its
        long_name / unit / description from cwatm/metaNetcdf.xml."""
        viewport = self.text_area.viewport()
        pos = viewport.mapFromGlobal(event.globalPos())
        cursor = self.text_area.cursorForPosition(pos)
        block_text = cursor.block().text()
        col = cursor.positionInBlock()
        token = None
        for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_]*", block_text):
            if m.start() <= col <= m.end():
                token = m.group()
                break
        meta = get_meta(token) if token else None
        if meta:
            unit, long_name, description = meta
            tip = f"<b>{token}</b>"
            if long_name:
                tip += f"<br>{long_name}"
            if unit:
                tip += f" [{unit}]"
            if description:
                tip += f"<br>{description}"
            QToolTip.showText(event.globalPos(), tip, viewport)
        else:
            QToolTip.hideText()

    def create_right_panel(self, parent_layout):
        """Create right panel with text display"""
        right_panel = QWidget()
        right_panel.setObjectName("rightPanel")
        # Scope the style to this panel only (a bare "QWidget {…}" selector cascades
        # to child widgets - including the editor's scroll bars - and would collapse
        # them via the padding/margin, so use the object-name selector).
        right_panel.setStyleSheet(self._right_panel_style())
        self._right_panel = right_panel
        right_layout = QVBoxLayout(right_panel)
        right_layout.setSpacing(12)
        right_layout.setContentsMargins(15, 15, 15, 15)
        
        # Save controls with modern styling
        save_controls = QHBoxLayout()
        save_controls.setSpacing(3)
        
        # Modern button style template + the light-blue unsaved variant, both
        # built from the active theme (regenerated on a mode switch in _retheme)
        modern_button_style = self._build_modern_button_style()
        self._modern_button_style = modern_button_style
        self._save_dirty_style = self._build_save_dirty_style()

        save_button = QPushButton("Save")
        save_button.setStyleSheet(modern_button_style)
        save_button.clicked.connect(self.save_file)
        save_controls.addWidget(save_button)
        self.save_button = save_button

        save_as_button = QPushButton("Save As")
        save_as_button.setStyleSheet(modern_button_style)
        save_as_button.clicked.connect(self.save_as_file)
        save_controls.addWidget(save_as_button)
        self.save_as_button = save_as_button
        
        compress_all_button = QPushButton("Fold All")
        compress_all_button.setStyleSheet(modern_button_style)
        compress_all_button.clicked.connect(self.compress_all_sections)
        save_controls.addWidget(compress_all_button)
        
        expand_all_button = QPushButton("Unfold All")
        expand_all_button.setStyleSheet(modern_button_style)
        expand_all_button.clicked.connect(self.expand_all_sections)
        save_controls.addWidget(expand_all_button)
        
        top_button = QPushButton("Top")
        top_button.setStyleSheet(modern_button_style)
        top_button.clicked.connect(self.jump_to_top)
        save_controls.addWidget(top_button)

        down_button = QPushButton("Down")
        down_button.setStyleSheet(modern_button_style)
        down_button.clicked.connect(self.jump_to_bottom)
        save_controls.addWidget(down_button)

        font_plus_button = QPushButton("+")
        font_plus_button.setStyleSheet(modern_button_style)
        font_plus_button.setToolTip("Increase font size")
        font_plus_button.clicked.connect(self.increase_editor_font_size)
        save_controls.addWidget(font_plus_button)

        font_minus_button = QPushButton("-")
        font_minus_button.setStyleSheet(modern_button_style)
        font_minus_button.setToolTip("Decrease font size")
        font_minus_button.clicked.connect(self.decrease_editor_font_size)
        save_controls.addWidget(font_minus_button)

        # Experience-level button: Beginner -> Advanced -> Expert -> Beginner.
        # Restricts which settings sections are shown (see cycle_experience_level).
        # Coloured per level (light green/blue/red) so it is styled separately from
        # the plain nav buttons - kept OUT of self._nav_buttons.
        level_button = QPushButton(self._experience_level)
        level_button.setToolTip(
            "The skill of the user determines how much of the settingsfile is presented.\n"
            "Click to cycle: Beginner → Advanced → Expert.")
        level_button.clicked.connect(self.cycle_experience_level)
        save_controls.addWidget(level_button)
        self.level_button = level_button
        self._apply_level_button_style()

        # kept so a theme switch can re-style them (_retheme)
        self._nav_buttons = [save_button, save_as_button, compress_all_button,
                             expand_all_button, top_button, down_button,
                             font_plus_button, font_minus_button]
        
        
        save_controls.addStretch()
        right_layout.addLayout(save_controls)
        
        # Text area: plain-text settings editor (QPlainTextEdit + syntax
        # highlighter + section folding - report §3.2). The document is the
        # settings file at all times; saving is toPlainText().
        self.text_area = SettingsEditor()
        self.text_area.setPlaceholderText("Configuration content will appear here...")
        self.text_area.setReadOnly(False)
        self.text_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.text_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        # Colour Save / Save As blue when the document has unsaved edits
        self.text_area.document().modificationChanged.connect(self._on_doc_modified)
        # Keep the in-memory settings content (self.original_content) in sync with
        # the live document on every edit - the document IS the settings file, so
        # field-apply / gauge / PathOut / Show Basin must use the user's current
        # text (including manual typing), never a stale snapshot.
        self.text_area.textChanged.connect(self._on_editor_text_changed)
        # After an undo/redo, re-sync the left-window fields from the reverted text
        self.text_area.undoRedoPerformed.connect(self._sync_fields_from_editor)
        self.text_area.setStyleSheet(self._editor_style())
        # Editor row: line-number gutter (display lines) + the editor itself
        editor_row = QHBoxLayout()
        editor_row.setSpacing(2)
        self.line_number_gutter = LineNumberGutter(self.text_area)
        editor_row.addWidget(self.line_number_gutter)
        editor_row.addWidget(self.text_area, 1)
        right_layout.addLayout(editor_row)

        # Initialize text display manager
        self.text_display = TextDisplayManager(self.text_area)

        # Enable mouse interaction for links; the widget-level filter also handles
        # the metaNetcdf hover tooltips (QEvent.ToolTip)
        self.text_area.viewport().installEventFilter(self)
        self.text_area.installEventFilter(self)
        self.text_area.setMouseTracking(True)
        
        parent_layout.addWidget(right_panel)
        
    def setup_status_bar(self):
        """Setup status bar"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
    
    def show_documentation(self, doc_name="CWatM_GUI_Documentation.md",
                           window_title="CWatM GUI — Documentation"):
        """Open a bundled Markdown help file in a viewer window (Help menu:
        the Documentation by default, the Features tour via show_features)."""
        base_file = os.path.dirname(os.path.abspath(__file__))          # .../src/gui/components
        gui_root = os.path.abspath(os.path.join(base_file, "..", "..", ".."))  # .../gui
        candidates = [
            os.path.join(gui_root, "documentation", doc_name),
            os.path.join(os.getcwd(), "documentation", doc_name),
        ]
        if getattr(sys, "frozen", False):
            candidates.insert(0, os.path.join(getattr(sys, "_MEIPASS", ""),
                                              "documentation", doc_name))
            candidates.append(os.path.join(os.path.dirname(sys.executable),
                                           "documentation", doc_name))
        doc_path = next((c for c in candidates if os.path.exists(c)), None)
        if not doc_path:
            QMessageBox.warning(self, "Documentation",
                                f"{doc_name} was not found in the documentation folder.")
            return
        try:
            with open(doc_path, encoding="utf-8") as _f:
                md = _f.read()
        except Exception as e:
            QMessageBox.warning(self, "Documentation", f"Could not read documentation:\n{e}")
            return

        class _MarkdownBrowser(QTextBrowser):
            """QTextBrowser that also renders base64 data: images from the Markdown."""
            def loadResource(self, rtype, url):
                s = url.toString()
                if s.startswith("data:"):
                    try:
                        import base64
                        img = QImage()
                        img.loadFromData(base64.b64decode(s.split(",", 1)[1]))
                        return img
                    except Exception:
                        log.debug("documentation image not decoded", exc_info=True)
                        return None
                return super().loadResource(rtype, url)

        dlg = QDialog(self)
        dlg.setWindowTitle(window_title)
        dlg.resize(920, 720)
        layout = QVBoxLayout(dlg)
        browser = _MarkdownBrowser()
        browser.setOpenExternalLinks(True)
        browser.document().setBaseUrl(QUrl.fromLocalFile(os.path.dirname(doc_path) + os.sep))
        browser.setMarkdown(md)
        layout.addWidget(browser)
        dlg.exec()

    def show_features(self):
        """Help ▸ CWatM GUI Features: the user-facing feature & usage tour."""
        self.show_documentation("CWatM_GUI_Features.md", "CWatM GUI — Features")

    def show_faq(self):
        """Help ▸ FAQ: common questions & troubleshooting."""
        self.show_documentation("CWatM_GUI_FAQ.md", "CWatM GUI — FAQ")

    def show_info_dialog(self):
        """Show information dialog about CWatM"""
        dialog = QDialog(self)
        dialog.setWindowTitle("CWatM - Community Water Model")
        dialog.setFixedSize(600, 500)  # Increased size for scrollable content
        dialog.setModal(True)
        
        # Center dialog on parent window
        parent_geometry = self.geometry()
        dialog.move(
            parent_geometry.center().x() - dialog.width() // 2,
            parent_geometry.center().y() - dialog.height() // 2
        )
        
        layout = QVBoxLayout()
        
        # Title label (fixed at top)
        title_label = QLabel("CWatM - Community Water Model")
        title_label.setStyleSheet(f"""
            QLabel {{
                font-family: 'Segoe UI', sans-serif;
                font-weight: 700;
                font-size: 18px;
                color: {theme.c('accent')};
                padding: 15px 0px 10px 0px;
                text-align: center;
            }}
        """)
        title_label.setAlignment(Qt.AlignCenter)
        
        # Scrollable area for content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: 1px solid {theme.c('border')};
                border-radius: 6px;
                background-color: {theme.c('panel_bg')};
            }}
            QScrollBar:vertical {{
                background-color: {theme.c('surface_bg')};
                width: 12px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {theme.c('accent')};
                border-radius: 6px;
                min-height: 20px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {theme.c('menu_sel_bg')};
            }}
        """)
        
        # Content widget inside scroll area
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(15)
        content_layout.setContentsMargins(20, 20, 20, 20)
        
        # Main information text
        info_text = QLabel(
            "CWatM is the in-house hydrological model of IIASA.\n\n"
            "The Community Water Model (CWatM) is designed as a tool for "
            "assessing water security in the context of global change including "
            "environmental flows. It includes an accounting of how future "
            "water demands will evolve in response to socioeconomic change "
            "and how water availability will change in response to climate change.\n\n"
            "CWatM is a spatially distributed model that simulates the water cycle "
            "including surface water, groundwater, and human water use at daily "
            "timestep and at resolutions from 30 arcsec to 30 arcmin."
        )
        info_text.setStyleSheet(f"""
            QLabel {{
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                color: {theme.c('text')};
                line-height: 1.4;
                margin-bottom: 20px;
            }}
        """)
        info_text.setWordWrap(True)
        info_text.setAlignment(Qt.AlignJustify)
        
        # CWatM GUI version (shown above the CWatM model version)
        gui_version_header = QLabel("CWatM GUI version 1.02")
        gui_version_header.setStyleSheet(f"""
            QLabel {{
                font-family: 'Segoe UI', sans-serif;
                font-weight: 700;
                font-size: 14px;
                color: {theme.c('accent')};
                margin-top: 0px;
                margin-bottom: 0px;
            }}
        """)

        # Version header
        version_header = QLabel("CWatM Version")
        version_header.setStyleSheet(f"""
            QLabel {{
                font-family: 'Segoe UI', sans-serif;
                font-weight: 700;
                font-size: 14px;
                color: {theme.c('accent')};
                margin-top: 10px;
                margin-bottom: 10px;
            }}
        """)
        
        # Get version information
        try:
            version_info = version.get_version_info()
            version_text = (
                f"Source code on Github: https://github.com/iiasa/CWatM\n"
                f"Branch: {version_info['git_branch']}\n"
                f"Git Hash: {version_info['git_hash']}\n"
                f"Build on: {version_info['build_timestamp']}"
            )
        except Exception as e:
            version_text = (
                "Source code on Github: https://github.com/iiasa/CWatM\n"
                "Version information unavailable"
            )
        
        version_info_label = QLabel(version_text)
        version_info_label.setStyleSheet(f"""
            QLabel {{
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 11px;
                color: {theme.c('text')};
                background-color: {theme.c('surface_bg')};
                padding: 10px;
                border: 1px solid {theme.c('border')};
                border-radius: 4px;
                line-height: 1.4;
            }}
        """)
        version_info_label.setWordWrap(True)
        version_info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        # Add content to scroll area
        content_layout.addWidget(info_text)
        content_layout.addWidget(gui_version_header)
        content_layout.addWidget(version_header)
        content_layout.addWidget(version_info_label)
        content_layout.addStretch()
        
        scroll_area.setWidget(content_widget)
        
        # Close button (fixed at bottom)
        close_button = QPushButton("Close")
        close_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #0066CC, stop:1 #0055AA);
                border: 2px solid #0066CC;
                border-radius: 6px;
                color: white;
                font-weight: 600;
                font-size: 12px;
                padding: 8px 20px;
                min-width: 80px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #0055AA, stop:1 #004499);
                border-color: #0055AA;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #004499, stop:1 #003388);
                border-color: #004499;
            }
        """)
        close_button.clicked.connect(dialog.accept)
        
        # Add button layout
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(close_button)
        button_layout.addStretch()
        
        # Add all widgets to main layout
        layout.addWidget(title_label)
        layout.addWidget(scroll_area, 1)  # Give scroll area most of the space
        layout.addLayout(button_layout)
        
        dialog.setLayout(layout)
        dialog.exec()
        
    # Event handlers
    def reload_file(self):
        """Reload the current settings file from disk, discarding unsaved changes."""
        if not self.file_manager.has_file_loaded() or not self.file_manager.get_current_file_path():
            self.status_bar.showMessage("No file to reload")
            return

        # Confirm before discarding unsaved changes
        if getattr(self, "_is_dirty", False):
            reply = QMessageBox.question(
                self,
                "Reload file",
                "Discard unsaved changes and reload the file from disk?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        # Drop any pending auto-apply so it cannot re-introduce discarded changes
        self._field_update_timer.stop()
        self.file_parsed = False
        # parse_file(load=True) re-reads the current file path from disk and re-renders
        self.parse_file(load=True, show_status=True)
        self._mark_clean()
        self.status_bar.showMessage(f"Reloaded: {self.file_manager.get_current_file_path()}")

    def reload_after_external_save(self, path=None):
        """Refresh the main editor after the file it has open was written elsewhere
        (currently: saved from the Compare settings window). Reloads from disk so the
        editor shows the saved version. Prompts before discarding unsaved edits in the
        main window; if the user declines, the on-disk change is left un-shown."""
        cur = self.file_manager.get_current_file_path()
        if not cur:
            return
        if getattr(self, "_is_dirty", False):
            reply = QMessageBox.question(
                self,
                "File changed",
                "This settings file was just saved in the Compare settings window.\n\n"
                "Reload it here and discard your unsaved changes in the main window?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                self.status_bar.showMessage(
                    "File changed on disk (Compare settings) - not reloaded, "
                    "unsaved changes kept")
                return
        # Drop any pending auto-apply so it cannot re-introduce old field values.
        self._field_update_timer.stop()
        self.file_parsed = False
        self.parse_file(load=True, show_status=True)
        self._mark_clean()
        self.status_bar.showMessage(f"Reloaded after Compare-settings save: {cur}")

    def _get_settings_title(self, content):
        """Return the 'Title' value from the settings content, or '' if absent."""
        if not content:
            return ""
        for line in content.split('\n'):
            s = line.strip()
            if s.startswith('#') or s.startswith(';') or '=' not in s:
                continue
            key, value = s.split('=', 1)
            if key.strip().lower() == 'title':
                return value.strip()
        return ""

    def _has_excel_settings_file(self, content=None):
        """Whether the settings content defines an 'Excel_settings_file' key with a
        non-empty value (commented-out lines do not count)."""
        if content is None:
            content = self.original_content or ""
        if not content:
            return False
        for line in content.split('\n'):
            s = line.strip()
            if s.startswith('#') or s.startswith(';') or '=' not in s:
                continue
            key, value = s.split('=', 1)
            if key.strip().lower() == 'excel_settings_file':
                return bool(value.strip())
        return False

    def _update_excel_menu_enabled(self, content=None):
        """Grey out the Excel menu's items (Crops / Reservoirs) when the settings
        file has no 'Excel_settings_file' key - there is nothing for them to open.
        The Excel menu itself stays enabled, so it can still be opened to see why."""
        actions = getattr(self, "_excel_actions", None)
        if not actions:
            return
        enabled = self._has_excel_settings_file(content)
        for act in actions:
            try:
                act.setEnabled(enabled)
            except RuntimeError:
                # QAction already deleted on the C++ side - nothing to update.
                log.debug("Excel action gone while updating enabled state",
                          exc_info=True)

    def working_dir(self):
        """The current working directory: the folder of the loaded settings file,
        unless File > Change Working Dir has overridden it.

        This is the base every relative path in the settings file is resolved
        against, and the directory the model child process is started in.
        Returns "" when nothing is loaded and no override is set."""
        override = getattr(self, "_working_dir_override", None)
        if override:
            return override
        try:
            path = self.file_manager.get_current_file_path()
            if path:
                return os.path.dirname(os.path.abspath(path))
        except Exception:
            log.warning("working_dir lookup failed", exc_info=True)
        return ""

    def _update_workdir_label(self, loaded=True):
        """Show 'Working directory: <dir>' under the Loaded line (hidden when no
        file is loaded and no override is set)."""
        if getattr(self, "workdir_label", None) is None:
            return
        folder = self.working_dir() if (
            loaded or getattr(self, "_working_dir_override", None)) else ""
        self.workdir_label.setText(f"Working directory: {folder}" if folder else "")
        self.workdir_label.setVisible(bool(folder))

    def change_working_dir(self):
        """File > Change Working Dir - pick the directory relative paths in the
        settings file resolve against, and that the model runs from.

        Beyond the label and the GUI-side path resolution (working_dir()), this
        also chdir's the GUI process, so the checks that test a relative path with
        a plain os.path.exists (PathOut / basin viewer / Check settingsfile) and an
        in-process run resolve from the same place the model child does."""
        start = self.working_dir() or os.getcwd()
        folder = QFileDialog.getExistingDirectory(
            self, "Change Working Directory", start)
        if not folder:
            return
        folder = os.path.abspath(folder)
        try:
            os.chdir(folder)
        except Exception as e:
            QMessageBox.warning(self, "Change Working Dir",
                                f"Could not change to this directory:\n{folder}\n\n{e}")
            return
        self._working_dir_override = folder
        self._update_workdir_label()
        self.status_bar.showMessage(f"Working directory: {folder}")
        self.append_to_cwatminfo(f"Working directory changed to: {folder}\n")
        # Relative paths now resolve elsewhere - re-check the mask/gauges and PathOut
        self._rebuild_mask_cache(force=True)
        self._update_warnings()

    def load_file(self):
        """Handle file loading (via file dialog)"""
        content, filename = self.file_manager.load_file()
        self._finish_load(content, filename)

    def load_recent_file(self, path):
        """Load a settings file chosen from the History (recent files) menu."""
        if not path or not os.path.exists(path):
            self.status_bar.showMessage(f"File not found: {path}")
            self._recent_files = [p for p in self._recent_files if p != path]
            self._settings.setValue("recent_files", self._recent_files)
            return
        content, filename = self.file_manager.load_file_from_path(path)
        self._finish_load(content, filename)

    def _finish_load(self, content, filename):
        """Shared post-load handling for dialog load and History (recent) load."""
        if content is not None:
            self.text_display.set_plain_content(content)
            self.file_parsed = False  # Reset parsed flag when loading new file
            if filename.startswith("Error:"):
                self.filename_label.setText(filename)
                self._filename_state = "error"
                self._apply_filename_state()
                self.title_label.setText("")
                self._update_workdir_label(loaded=False)
                self._update_excel_menu_enabled("")
                self.status_bar.showMessage(filename)
            else:
                self.filename_label.setText(f"Loaded: {filename}")
                # Settings "Title" value, right of "Loaded:" in the same colour
                self.title_label.setText(self._get_settings_title(content))
                # A newly loaded file defines the working directory afresh - drop any
                # File > Change Working Dir override and chdir there.
                self._working_dir_override = None
                _wd = self.working_dir()
                if _wd:
                    try:
                        os.chdir(_wd)
                    except Exception:
                        log.warning("chdir to settings folder failed", exc_info=True)
                self._update_workdir_label()
                self._update_excel_menu_enabled(content)
                self._filename_state = "loaded"
                self._apply_filename_state()
                self.status_bar.showMessage(f"Loaded: {self.file_manager.get_current_file_path()}")

                # Register in the recent-files (History) list
                self._add_recent_file(self.file_manager.get_current_file_path())

                # Automatically parse the file after loading
                self.parse_file(load = True, show_status=True)

                # Freshly loaded file has no unsaved changes
                self._mark_clean()

                # Build the in-memory mask, then check gauges / PathOut
                self._rebuild_mask_cache(force=True)
                self._update_warnings()

                # RUN CWatM button - saturated blue "ready" state (readable in
                # every theme; run_controller uses the same style after a run)
                self.set_cwatm_button_ready_state()
                

    def parse_file(self, target_line=None, expand_all=True, show_status=False,load=False,content=""):
        """Apply settings content to the editor and the left-panel fields.

        The editor document is plain text (report §3.2): "parsing" now means
        setting the text (preserving folds/scroll/undo where possible via
        set_content_preserving) and refreshing the date/PathOut/MaskMap/Gauges
        boxes. With load=True the content is re-read from the current file."""
        if not self.file_manager.has_file_loaded():
            self.status_bar.showMessage("No file loaded to parse")
            self.text_display.set_plain_content("Please load a configuration file first before parsing.")
            return

        # Programmatic re-render: don't let the resulting text/field changes flip the
        # unsaved-changes (Save button) state.
        self._suppress_dirty = True
        try:
            # Store current scroll position if no target specified
            position_data = self.save_scroll_position() if target_line is None else None

            # Read and parse file
            if load:
                with open(self.file_manager.get_current_file_path(), 'r', encoding='utf-8') as file:
                    content = file.read()

            # Store original content (= last programmatically applied content)
            self.original_content = content
            self.text_display.set_original_content(content)

            # Extract the date / path fields
            date_values, settings_values = self.config_parser.parse_content(content)

            # Put the content into the editor. On load/reload (expand_all) use
            # load_text: it sets the SAVED baseline (so nothing shows as changed),
            # unfolds, clears bookmarks and resets undo. A field auto-apply
            # (expand_all=False) uses set_content_preserving, which keeps folds,
            # scroll and undo history and leaves the edited lines marked changed.
            if expand_all:
                self.text_area.load_text(content)
                # A fresh load recreated all blocks (clearing folds); re-apply the
                # experience-level lock computed from the new file's sections.
                self._apply_experience_level()
            else:
                self.text_area.set_content_preserving(content)

            # Update date fields
            self.date_manager.set_dates_from_config(date_values, self.config_parser)
            
            # Update PathOut field
            if 'pathout' in settings_values:
                self.pathout_field.setText(settings_values['pathout'])
            else:
                self.pathout_field.setText("")
                
            # Update MaskMap field
            if 'maskmap' in settings_values:
                self.maskmap_field.setText(settings_values['maskmap'])
            else:
                self.maskmap_field.setText("")

            # Update Gauges field
            if 'gauges' in settings_values:
                self.gauges_field.setText(settings_values['gauges'])
            else:
                self.gauges_field.setText("")
            
            # Restore position
            if target_line is not None:
                self.text_display.restore_cursor_position(target_line, 0)
            elif position_data:
                self.restore_scroll_position(position_data)
            
            if show_status:
                self.status_bar.showMessage("Configuration file parsed")
            
            # Set parsed flag to True on successful parsing
            self.file_parsed = True
            
        except Exception as e:
            # Print error to stderr so it appears in dark red in cwatminfo
            import sys
            print(f"Error parsing file: {str(e)}", file=sys.stderr)
            self.status_bar.showMessage(f"Error parsing file: {str(e)}")
            self.file_parsed = False
        finally:
            # A fresh programmatic render is not an unsaved user edit
            self.text_area.document().setModified(False)
            self._suppress_dirty = False

    # ------------------------------------------------------------ theme styles
    # Every stylesheet the main window sets is built from the active theme's
    # colour tokens (src/gui/utils/theme.py). Normal = the classic colours.

    def _left_panel_style(self):
        return f"""
            QWidget {{
                background-color: {theme.c('panel_bg')};
                border-radius: 12px;
                margin: 6px 8px 8px 8px;
                margin-top: 1px;
                padding: 5px 8px 8px 8px;
            }}
        """

    def _right_panel_style(self):
        # Scoped to the object name - a bare "QWidget {…}" would cascade into the
        # editor's scroll bars (see create_right_panel).
        return f"""
            QWidget#rightPanel {{
                background-color: {theme.c('panel_bg')};
                border-radius: 12px;
                margin: 8px;
                padding: 15px;
            }}
        """

    def _field_style(self):
        return (f"QLineEdit {{ background-color: {theme.c('field_bg')}; "
                f"color: {theme.c('field_text')}; }}")

    def _output_box_style(self):
        return f"""
            QPlainTextEdit {{
                background-color: {theme.c('out_bg')};
                border: 1px solid {theme.c('out_border')};
                padding: 0px;
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                font-size: {self._cwatm_font_size}px;
                color: {theme.c('out_text')};
            }}
            QScrollBar:vertical {{
                background-color: {theme.c('surface_bg')};
                width: 16px;
                border-radius: 6px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {theme.c('accent')};
                border-radius: 6px;
                min-height: 28px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {theme.c('menu_sel_bg')};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
            QScrollBar:horizontal {{
                background-color: {theme.c('surface_bg')};
                height: 16px;
                border-radius: 6px;
                margin: 2px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {theme.c('accent')};
                border-radius: 6px;
                min-width: 28px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: {theme.c('menu_sel_bg')};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
                background: none;
            }}
        """

    def increase_editor_font_size(self):
        """'+' button: grow the settings-editor font by 1 px (capped)."""
        self._set_editor_font_size(self._editor_font_size + 1)

    def decrease_editor_font_size(self):
        """'-' button: shrink the settings-editor font by 1 px (floored)."""
        self._set_editor_font_size(self._editor_font_size - 1)

    def _set_editor_font_size(self, size):
        self._editor_font_size = max(6, min(32, size))
        self._settings.setValue("editor/font_size", self._editor_font_size)
        self.text_area.setStyleSheet(self._editor_style())
        # The gutter derives its font from the editor's - repaint so the
        # numbers keep lining up with the (re-laid-out) text rows.
        self.line_number_gutter.update()

    # ---------------------------------------------------- experience level
    def cycle_experience_level(self):
        """Level button: Beginner -> Advanced -> Expert -> Beginner."""
        idx = _EXPERIENCE_LEVELS.index(self._experience_level)
        nxt = _EXPERIENCE_LEVELS[(idx + 1) % len(_EXPERIENCE_LEVELS)]
        self.set_experience_level(nxt)

    def set_experience_level(self, level):
        """Set the experience level (from the button or the Configure ▸ Skill of
        User menu) and apply it. Keeps the menu radio group in sync."""
        if level not in _EXPERIENCE_LEVELS or level == self._experience_level:
            # Still re-sync the menu check state (the QActionGroup may have toggled).
            self._sync_level_menu()
            return
        self._experience_level = level
        self._settings.setValue("editor/level", self._experience_level)
        self.level_button.setText(self._experience_level)
        self._apply_level_button_style()
        self._sync_level_menu()
        self._apply_experience_level()

    def _sync_level_menu(self):
        """Tick the matching Configure ▸ Skill of User radio item."""
        actions = getattr(self, "_level_menu_actions", None)
        if not actions:
            return
        for lvl, act in actions.items():
            try:
                act.setChecked(lvl == self._experience_level)
            except RuntimeError:
                pass

    def _apply_experience_level(self):
        """Hide the settings sections the current level may not see: locked
        sections are fully hidden (header + content) and cannot be unfolded.
        Expert shows everything. Recomputed from the editor's current section list
        so it stays correct after loading a different file."""
        allowed = _LEVEL_ALLOWED.get(self._experience_level)
        if allowed is None:   # Expert - no restriction
            locked = set()
        else:
            locked = {s for s in self.text_area.section_names() if s not in allowed}
        self.text_area.set_locked_sections(locked)

    def _level_button_style(self):
        """Stylesheet for the level button: the level's colour at 50% opacity."""
        rgb = _LEVEL_COLORS.get(self._experience_level, "200, 200, 200")
        return f"""
            QPushButton {{
                background-color: rgba({rgb}, 0.5);
                border: 1px solid {theme.c('btn_border')};
                border-radius: 5px;
                color: {theme.c('btn_text')};
                font-weight: 600;
                font-size: 11px;
                padding: 2px 8px;
                min-height: 16px;
            }}
            QPushButton:hover {{ background-color: rgba({rgb}, 0.7);
                                 border-color: {theme.c('btn_hover_border')}; }}
            QPushButton:pressed {{ background-color: rgba({rgb}, 0.85);
                                   border-color: {theme.c('btn_press_border')}; }}
        """

    def _apply_level_button_style(self):
        btn = getattr(self, "level_button", None)
        if btn is not None:
            try:
                btn.setStyleSheet(self._level_button_style())
            except RuntimeError:
                pass

    def _editor_style(self):
        return f"""
            QPlainTextEdit {{
                background-color: {theme.c('editor_bg')};
                border: 2px solid {theme.c('editor_border')};
                border-radius: 12px;
                padding: 16px;
                font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', 'Consolas', monospace;
                font-size: {self._editor_font_size}px;
                line-height: 1.5;
                color: {theme.c('editor_text')};
                selection-background-color: {theme.c('sel_bg')};
                selection-color: {theme.c('sel_text')};
            }}
            QPlainTextEdit:focus {{
                border-color: {theme.c('editor_focus_border')};
            }}
            QScrollBar:vertical {{
                background-color: {theme.c('surface_bg')};
                width: 16px;
                border-radius: 6px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {theme.c('accent')};
                border-radius: 6px;
                min-height: 28px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {theme.c('menu_sel_bg')};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """

    def _run_button_idle_style(self):
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {theme.c('btn_top')}, stop:1 {theme.c('btn_bottom')});
                border: 2px solid {theme.c('btn_border')};
                border-radius: 8px;
                color: {theme.c('btn_text')};
                font-weight: 600;
                font-size: 13px;
                padding: 8px 16px;
                min-height: 32px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {theme.c('btn_hover_top')}, stop:1 {theme.c('btn_hover_bottom')});
                border-color: {theme.c('btn_hover_border')};
            }}
            QPushButton:pressed {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {theme.c('btn_press_top')}, stop:1 {theme.c('btn_press_bottom')});
                border-color: {theme.c('btn_press_border')};
            }}
        """

    def _build_modern_button_style(self):
        return f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {theme.c('btn_top')}, stop:1 {theme.c('btn_bottom')});
                border: 1px solid {theme.c('btn_border')};
                border-radius: 5px;
                color: {theme.c('btn_text')};
                font-weight: 600;
                font-size: 11px;
                padding: 2px 8px;
                min-height: 16px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {theme.c('btn_hover_top')}, stop:1 {theme.c('btn_hover_bottom')});
                border-color: {theme.c('btn_hover_border')};
            }}
            QPushButton:pressed {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {theme.c('btn_press_top')}, stop:1 {theme.c('btn_press_bottom')});
                border-color: {theme.c('btn_press_border')};
            }}
            QPushButton:disabled {{
                background: {theme.c('surface_bg')};
                border: 1px solid {theme.c('border')};
                color: {theme.c('text_gray')};
            }}
        """

    def _build_save_dirty_style(self):
        return f"""
            QPushButton {{
                background-color: {theme.c('dirty_bg')};
                border: 1px solid {theme.c('dirty_border')};
                border-radius: 5px;
                color: {theme.c('btn_text')};
                font-weight: 600;
                font-size: 11px;
                padding: 2px 8px;
                min-height: 16px;
            }}
            QPushButton:hover {{ background-color: {theme.c('dirty_hover')};
                                 border-color: {theme.c('dirty_border')}; }}
            QPushButton:pressed {{ background-color: {theme.c('dirty_press')};
                                   border-color: {theme.c('dirty_border')}; }}
            QPushButton:disabled {{ background-color: {theme.c('surface_bg')};
                                    border: 1px solid {theme.c('border')};
                                    color: {theme.c('text_gray')}; }}
        """

    def _apply_filename_state(self):
        """Re-apply the filename/Title label colours for the remembered state
        (none / loaded / saveas / error) using the active theme."""
        st = getattr(self, "_filename_state", "none")
        colors = {"loaded": theme.c("ok_color"), "saveas": theme.c("link_color"),
                  "error": theme.c("warn_color")}
        # margin/padding 0 overrides the left panel's bare "QWidget {margin/padding}"
        # cascade, keeping "Working directory:" tight under the "Loaded:" line.
        _tight = " margin: 0px; padding: 0px;"
        if st == "none":
            self.filename_label.setStyleSheet(
                f"color: {theme.c('text_gray')}; font-style: italic;" + _tight)
            if getattr(self, "title_label", None) is not None:
                self.title_label.setStyleSheet(_tight)
        else:
            style = f"color: {colors[st]}; font-weight: bold;" + _tight
            self.filename_label.setStyleSheet(style)
            if st != "error" and getattr(self, "title_label", None) is not None:
                self.title_label.setStyleSheet(style)
        # The Working-directory line stays neutral in every state, 2 px under
        # the Loaded line
        if getattr(self, "workdir_label", None) is not None:
            self.workdir_label.setStyleSheet(
                f"color: {theme.c('text_gray')}; "
                "margin: 2px 0px 0px 0px; padding: 0px;")

    def _apply_gauges_field_color(self):
        """Colour the Gauges box text by the remembered gauge-in-mask result
        (True = all inside, False = outside, None = unknown)."""
        gres = getattr(self, "_gauges_state", None)
        color = {True: theme.c("link_color"), False: theme.c("warn_color")}.get(
            gres, theme.c("field_text"))
        self.gauges_field.setStyleSheet(
            f"QLineEdit {{ background-color: {theme.c('field_bg')}; color: {color}; }}")

    def _retheme(self):
        """Re-apply every theme-dependent style after a Configure ▸ Mode switch.
        The app-wide palette/stylesheet is already applied by the caller."""
        try:
            self.menu_bar.setStyleSheet(self._menu_bar_stylesheet())
            self._banner_title.setStyleSheet(f"color: {theme.c('accent')};")
            self.interface_label.setStyleSheet(f"color: {theme.c('text_muted')};")
            self._left_panel.setStyleSheet(self._left_panel_style())
            self._right_panel.setStyleSheet(self._right_panel_style())
            self.date_manager.retheme()
            self.pathout_field.setStyleSheet(self._field_style())
            self.maskmap_field.setStyleSheet(self._field_style())
            self._apply_gauges_field_color()
            self.changed_fields_label.setStyleSheet(
                f"QLabel {{ color: {theme.c('hint_color')}; }}")
            self.warning_label.setStyleSheet(
                f"QLabel {{ color: {theme.c('warn_color')}; font-weight: bold; }}")
            self.save_hint_label.setStyleSheet(
                f"QLabel {{ color: {theme.c('warn_color')}; font-weight: bold; }}")
            self._apply_filename_state()
            # buttons: regenerate the cached styles, re-apply by current state
            self._modern_button_style = self._build_modern_button_style()
            self._save_dirty_style = self._build_save_dirty_style()
            for b in getattr(self, "_nav_buttons", []):
                b.setStyleSheet(self._modern_button_style)
            self._apply_level_button_style()
            self._set_save_dirty(getattr(self, "_is_dirty", False))
            if getattr(self, "_run_btn_state", "idle") == "idle":
                self.run_cwatm_button.setStyleSheet(self._run_button_idle_style())
            # editor, gutter, clock, output box
            self.text_area.setStyleSheet(self._editor_style())
            self.text_area.retheme()
            self.line_number_gutter.update()
            self.progress_clock.update()
            if getattr(self, "discharge_sparkline", None) is not None:
                self.discharge_sparkline.update()
            self.cwatminfo_box.setStyleSheet(self._output_box_style())
        except Exception:
            log.warning("retheme failed", exc_info=True)

    def _set_save_dirty(self, dirty):
        """Colour the Save / Save As buttons blue when there are unsaved changes."""
        self._is_dirty = bool(dirty)
        if getattr(self, "save_button", None) is None:
            return
        style = self._save_dirty_style if dirty else self._modern_button_style
        self.save_button.setStyleSheet(style)
        self.save_as_button.setStyleSheet(style)
        hint = getattr(self, "save_hint_label", None)
        if hint is not None:
            try:
                hint.setText("Save changes to use them!" if dirty else "")
            except RuntimeError:
                pass

    def _on_doc_modified(self, changed):
        """Editor document modification state changed (ignored during programmatic
        re-renders, which set self._suppress_dirty)."""
        if self._suppress_dirty:
            return
        self._set_save_dirty(changed)

    def _on_editor_text_changed(self):
        """Mirror the live editor document into self.original_content on every edit.

        original_content is the authoritative in-memory settings text used by the
        field auto-apply, the gauge/PathOut checks, Show Basin, the Excel menu, etc.
        It is only refreshed on load/save/undo before this hook, so manual typing in
        the editor left it stale - a subsequent field change then rebuilt from the
        pre-typing snapshot and silently discarded the user's edits. Keeping it in
        step with the document keeps every consumer on the current text. (This does
        not touch the Save-dirty / diff baseline, which is self._clean_content.)"""
        try:
            content = self.text_area.toPlainText()
            self.original_content = content
            self.text_display.set_original_content(content)
            # Adding/removing the Excel_settings_file line enables/greys the Excel menu
            self._update_excel_menu_enabled(content)
        except Exception:
            log.debug("editor->original_content sync failed", exc_info=True)

    def _mark_clean(self):
        """Mark the document/state as saved (no unsaved changes)."""
        if getattr(self, "text_area", None) is not None:
            self.text_area.document().setModified(False)
            # Snapshot of the saved/loaded text: undo/redo compares against this
            # to decide whether the Save indicator should be blue (see
            # _sync_fields_from_editor).
            self._clean_content = self.text_area.toPlainText()
            # Current text is now the saved baseline -> clear the light-blue
            # changed-line highlight.
            self.text_area.mark_saved()
        self._set_save_dirty(False)
        # The fields now match the file on disk - reset the changed-fields hint
        self._capture_field_baseline()

    def _sync_fields_from_editor(self):
        """Re-derive the left-window fields (dates, PathOut, MaskMap, Gauges) from
        the editor text after an editor undo/redo, so a field-driven change is
        reverted/re-applied together with the text (the fields would otherwise stay
        stale and re-poison _live_content / the next save). Also refreshes the Save
        indicator, the changed-fields hint and the gauge-in-mask warning."""
        if getattr(self, "text_area", None) is None:
            return
        content = self.text_area.toPlainText()
        self._suppress_dirty = True
        try:
            self.original_content = content
            self.text_display.set_original_content(content)
            date_values, settings_values = self.config_parser.parse_content(content)
            self.date_manager.set_dates_from_config(date_values, self.config_parser)
            if getattr(self, "pathout_field", None) is not None:
                self.pathout_field.setText(settings_values.get('pathout', ""))
            if getattr(self, "maskmap_field", None) is not None:
                self.maskmap_field.setText(settings_values.get('maskmap', ""))
            if getattr(self, "gauges_field", None) is not None:
                self.gauges_field.setText(settings_values.get('gauges', ""))
        except Exception:
            log.warning("field re-sync after undo/redo failed", exc_info=True)
        finally:
            self._suppress_dirty = False
        # Dirty iff the current text differs from the last saved/loaded snapshot
        # (so undoing all the way back to the saved file clears the Save colour).
        self._set_save_dirty(content != getattr(self, "_clean_content", None))
        self._update_changed_fields_hint()
        # Re-check gauge-in-mask against the reverted/re-applied field values
        # (PathOut is only checked on load/save).
        self._update_warnings(check_pathout=False)

    def on_field_changed(self):
        """Handle when dates, pathout, or maskmap fields change"""
        if self._suppress_dirty:
            return  # programmatic update during parse/load, not a user change
        # Mark unsaved changes on the Save / Save As buttons
        self._set_save_dirty(True)
        # Show which fields differ from the saved file next to RUN CWATM
        self._update_changed_fields_hint()
        # Auto-apply the change into the in-memory settings content (debounced)
        self._field_update_timer.start()

    def _apply_field_changes(self):
        """Apply changed Start/Spin/End dates, PathOut and MaskMap into the in-memory
        settings content and refresh the view. Does NOT save to disk (unlike Actualize)."""
        if not self.file_manager.has_file_loaded():
            return
        try:
            start_date, spin_date, end_date = self.date_manager.get_current_dates()
            if not all([start_date, spin_date, end_date]):
                return

            content = self.text_display.get_content()
            current_config_dates = self.config_parser.get_current_date_values(content)
            current_config_settings = self.config_parser.get_current_settings_values(content)
            current_pathout = self.pathout_field.text().strip()
            current_maskmap = self.maskmap_field.text().strip()
            current_gauges = self.gauges_field.text().strip()

            dates_changed = self.date_manager.dates_changed_from_config(current_config_dates)
            settings_changed = (current_config_settings.get('pathout', '') != current_pathout or
                                current_config_settings.get('maskmap', '') != current_maskmap or
                                current_config_settings.get('gauges', '') != current_gauges)
            if not (dates_changed or settings_changed):
                return

            # Build on the LIVE editor text (fetched above), never a stale
            # original_content snapshot - otherwise manual editor edits made since
            # the last load/save would be discarded when a field changes.
            updated_content = content
            if dates_changed:
                updated_content = self.config_parser.update_dates(
                    updated_content, start_date, spin_date, end_date)
            if settings_changed:
                settings_dict = {}
                if current_config_settings.get('pathout', '') != current_pathout:
                    settings_dict['pathout'] = current_pathout
                if current_config_settings.get('maskmap', '') != current_maskmap:
                    settings_dict['maskmap'] = current_maskmap
                if current_config_settings.get('gauges', '') != current_gauges:
                    settings_dict['gauges'] = current_gauges
                updated_content = self.config_parser.update_settings(updated_content, settings_dict)

            # Update the in-memory content and refresh the view WITHOUT saving to disk.
            self.original_content = updated_content
            self.text_display.set_original_content(updated_content)
            self.parse_file(content=updated_content, load=False, expand_all=False)

            # These are unsaved changes
            self._set_save_dirty(True)
            # Re-check gauges-in-mask only (PathOut is checked on load/save)
            self._update_warnings(check_pathout=False)
            self.status_bar.showMessage("Settings updated (not saved)")
        except Exception as e:
            import sys
            print(f"Error applying field changes: {str(e)}", file=sys.stderr)

    def _flush_pending_field_changes(self):
        """If a debounced field update is still pending, apply it now so that Save and
        Run use the latest date / PathOut / MaskMap values."""
        if self._field_update_timer.isActive():
            self._field_update_timer.stop()
            self._apply_field_changes()
    
    def open_output_explorer(self):
        """Analyse menu > Output Explorer: browse PathOut; double-click dispatches each
        result to the matching viewer (lazy import - fast-startup rule)."""
        try:
            from src.gui.widgets.output_explorer import open_output_explorer
            open_output_explorer(parent=self)
        except Exception as e:
            print(f"Error opening Output Explorer: {str(e)}", file=sys.stderr)

    def open_batch_runner(self):
        """RUN CWATM > Batch Run…: run many scenarios from the loaded settings file
        (base .ini + per-row key overrides), up to N in parallel."""
        try:
            from src.gui.widgets.batch_runner_window import open_batch_runner
            open_batch_runner(parent=self)
        except Exception as e:
            print(f"Error opening Batch Run: {str(e)}", file=sys.stderr)

    def open_run_ledger(self):
        """RUN CWATM > Run Ledger: show the log of past runs."""
        try:
            from src.gui.widgets.run_ledger_window import open_run_ledger
            open_run_ledger(parent=self)
        except Exception as e:
            print(f"Error opening Run Ledger: {str(e)}", file=sys.stderr)

    def set_history_folder(self):
        """Configure > Run history folder…: choose where the Run Ledger is stored."""
        from PySide6.QtWidgets import QFileDialog
        from src.gui.utils import run_ledger
        current = run_ledger.history_dir()
        folder = QFileDialog.getExistingDirectory(
            self, "Choose the run-history folder", current)
        if folder:
            run_ledger.set_history_dir(folder)
            self.status_bar.showMessage(f"Run history folder: {folder}")

    def set_history_retention(self):
        """Configure > Run history retention…: how many days of runs to keep."""
        from PySide6.QtWidgets import QInputDialog
        from src.gui.utils import run_ledger
        days, ok = QInputDialog.getInt(
            self, "Run history retention",
            "Keep runs for how many days? (0 = keep forever)",
            run_ledger.retention_days(), 0, 100000)
        if ok:
            run_ledger.set_retention_days(days)
            keep = f"{days} days" if days else "forever"
            self.status_bar.showMessage(f"Run history retention: keep {keep}")

    def open_timeseries_analysis(self):
        """Analyse menu > Timeseries: open a result .csv and plot it with Plotly."""
        try:
            from src.gui.widgets.analysis_timeseries import open_timeseries
            open_timeseries(parent=self)
        except Exception as e:
            print(f"Error opening timeseries analysis: {str(e)}", file=sys.stderr)

    def open_netcdf_analysis(self):
        """Analyse menu > NetCDF: open a .nc file on a folium OSM map (EPSG:4326)."""
        try:
            from src.gui.widgets.analysis_netcdf import open_netcdf
            open_netcdf(parent=self)
        except Exception as e:
            print(f"Error opening NetCDF analysis: {str(e)}", file=sys.stderr)

    def open_watercycle_analysis(self):
        """Analyse menu > Watercycle: open a WaterCycle csv and show a sunburst."""
        try:
            from src.gui.widgets.analysis_watercycle import open_watercycle
            open_watercycle(parent=self)
        except Exception as e:
            print(f"Error opening Watercycle analysis: {str(e)}", file=sys.stderr)

    def open_flowdiagram_analysis(self):
        """Analyse menu > Flow Diagram: open a WaterCycle csv and show a Sankey."""
        try:
            from src.gui.widgets.analysis_flowdiagram import open_flowdiagram
            open_flowdiagram(parent=self)
        except Exception as e:
            print(f"Error opening Flow Diagram analysis: {str(e)}", file=sys.stderr)

    def open_cwatm_ai(self):
        """CWatM AI button: open the Gemini NotebookLM chat window (lazy import so
        notebooklm/httpx never load at startup - fast-startup rule)."""
        try:
            from src.gui.widgets.notebooklm_window import open_cwatm_ai
            open_cwatm_ai(parent=self)
        except Exception as e:
            print(f"Error opening CWatM AI: {str(e)}", file=sys.stderr)
            try:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self, "CWatM AI",
                    "Could not open CWatM AI.\n\n"
                    "The 'notebooklm-py' package may not be installed:\n"
                    "    pip install notebooklm-py[cookies]\n\n" + str(e))
            except Exception:
                pass

    # -------------------------------------------- CWatM AI <-> settings bridge
    def ai_current_settings_line(self):
        """Text of the settings editor's current cursor line (or the selection if
        any), for CWatM AI 'explain this line'. Empty string if no editor."""
        ed = getattr(self, "text_area", None)
        if ed is None:
            return ""
        cur = ed.textCursor()
        if cur.hasSelection():
            return cur.selectedText().replace(' ', '\n').strip()
        return cur.block().text().strip()

    def open_compare_settings(self):
        """Tools ▸ Compare settings: side-by-side diff of the current settings file
        and another one (loaded in the window)."""
        try:
            from src.gui.widgets.compare_settings_window import open_compare_settings
            # Keep a reference so the non-modal window isn't garbage-collected.
            self._compare_settings_window = open_compare_settings(parent=self)
        except Exception as e:
            print(f"Error opening Compare settings: {str(e)}", file=sys.stderr)
            try:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    self, "Compare settings",
                    f"Could not open Compare settings:\n{e}")
            except Exception:
                pass

    def restore_settingsfile(self):
        """Tools ▸ Restore settingsfile: open a CWatM output NetCDF (dis*.nc) and
        show its stored run metadata (excluding the bulky version_* attributes)."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        start_dir = ""
        try:
            start_dir = self._resolved_pathout_dir() or ""
        except Exception:
            start_dir = ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open CWatM output NetCDF", start_dir,
            "Discharge NetCDF (dis*.nc);;NetCDF files (*.nc)")
        if not path:
            return
        try:
            from src.gui.widgets.restore_settings_window import (
                read_netcdf_metadata, RestoreSettingsWindow)
            metadata = read_netcdf_metadata(path)
            win = RestoreSettingsWindow(path, metadata, self)
            win.exec()
        except Exception as e:
            print(f"Error opening Restore settingsfile: {str(e)}", file=sys.stderr)
            try:
                QMessageBox.warning(
                    self, "Restore settingsfile",
                    f"Could not read the NetCDF metadata:\n{e}")
            except Exception:
                pass

    def save_scroll_position(self):
        """Save current scroll position and cursor position"""
        scroll_bar = self.text_area.verticalScrollBar()
        cursor_position = self.text_display.get_current_line()
        return {
            'scroll_value': scroll_bar.value(),
            'cursor_line': cursor_position
        }
    
    def restore_scroll_position(self, position_data):
        """Restore scroll position and cursor position"""
        if position_data:
            # Restore cursor position first
            if 'cursor_line' in position_data:
                self.text_display.restore_cursor_position(None, position_data['cursor_line'])
            
            # Then restore scroll position. Defer to the next event-loop turn so the
            # freshly set text has been laid out (scrollbar maximum is up to date)
            # without re-entering the event loop here.
            if 'scroll_value' in position_data:
                scroll_bar = self.text_area.verticalScrollBar()
                value = position_data['scroll_value']
                QTimer.singleShot(0, lambda sb=scroll_bar, v=value: sb.setValue(v))

    def save_file(self,new=False):
        """Handle file saving. The editor document is plain text at all times
        (report §3.2), so the saved content is simply toPlainText() - folded
        sections are hidden, not removed, and are saved like everything else.
        No re-render is needed, so view, folds and cursor stay untouched."""
        if not self.file_manager.has_file_loaded():
            self.status_bar.showMessage("No file loaded - use Save As instead")
            return

        # Apply any pending (debounced) field changes so the save captures them
        self._flush_pending_field_changes()

        content = self.text_area.toPlainText()

        if new:
            success, filename, message = self.file_manager.save_as_file(content)
        else:
            success, message = self.file_manager.save_file(content)
        if success:
            if new:
                self.filename_label.setText(f"Saved: {filename}")
                # Keep the Title label in the same colour as the filename label
                self.title_label.setText(self._get_settings_title(content))
                # Save As can move the settings file to another folder. Without an
                # explicit override that folder IS the working directory, so follow
                # it with a chdir too - otherwise working_dir() reports the new
                # folder while the process CWD (what the plain os.path.exists checks
                # in basin_viewer resolve against) still points at the old one.
                if not getattr(self, "_working_dir_override", None):
                    _wd = self.working_dir()
                    if _wd:
                        try:
                            os.chdir(_wd)
                        except Exception:
                            log.warning("chdir after Save As failed", exc_info=True)
                self._update_workdir_label()
                self._filename_state = "saveas"
                self._apply_filename_state()
                self.status_bar.showMessage(f"File saved: {self.file_manager.get_current_file_path()}")
                # A "Save As" file becomes the current file - add it to History
                self._add_recent_file(self.file_manager.get_current_file_path())
            else:
                self.status_bar.showMessage("File saved")

            self.original_content = content
            self.text_display.set_original_content(content)
            # Sync the left-panel fields with the SAVED content: the editor text may
            # contain manual edits to the dates / PathOut / MaskMap / Gauges lines,
            # and _live_content() (gauge/PathOut checks) always substitutes the box
            # values - stale boxes would poison the checks against the saved file.
            # (The old pipeline got this via a full re-parse after saving.)
            self._suppress_dirty = True
            try:
                date_values, settings_values = self.config_parser.parse_content(content)
                self.date_manager.set_dates_from_config(date_values, self.config_parser)
                self.pathout_field.setText(settings_values.get('pathout', ""))
                self.maskmap_field.setText(settings_values.get('maskmap', ""))
                self.gauges_field.setText(settings_values.get('gauges', ""))
            except Exception:
                log.warning("field sync after save failed", exc_info=True)
            finally:
                self._suppress_dirty = False
            # Saved: clear the unsaved-changes indicator
            self._mark_clean()
            # After Save / Save As, rebuild the mask and re-check whether the gauge is
            # inside the MaskMap (force so the check is always fresh, like on load).
            self._rebuild_mask_cache(force=True)
            self._update_warnings()
        else:
            self.status_bar.showMessage(message)


    def save_as_file(self):
        """Handle save as"""
        #success, filename, message = self.file_manager.save_as_file(content)
        self.save_file(new=True)


    def compress_all_sections(self):
        """Settings > Fold All: fold every section in the editor (report §3.2 -
        folding only hides blocks, the document text is untouched)."""
        if not self.file_manager.has_file_loaded():
            self.status_bar.showMessage("No file loaded")
            return
        self.text_area.fold_all()

    def expand_all_sections(self, checked=False):
        """Settings > Unfold All: unfold every section in the editor."""
        if not self.file_manager.has_file_loaded():
            self.status_bar.showMessage("No file loaded")
            return
        self.text_area.unfold_all()

    def jump_to_top(self):
        """Jump to the beginning of the file"""
        if not self.file_manager.has_file_loaded():
            self.status_bar.showMessage("No file loaded")
            return
        
        cursor = self.text_area.textCursor()
        cursor.movePosition(QTextCursor.Start)
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()
        self.status_bar.showMessage("Jumped to top of file")
    
    def jump_to_bottom(self):
        """Jump to the bottom of the file"""
        if not self.file_manager.has_file_loaded():
            self.status_bar.showMessage("No file loaded")
            return
        
        cursor = self.text_area.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.text_area.setTextCursor(cursor)
        # The last line may be inside a folded section - unfold it
        self.text_area.reveal_cursor()
        self.text_area.ensureCursorVisible()
        self.status_bar.showMessage("Jumped to bottom of file")
    
    def eventFilter(self, obj, event):
        """Editor viewport events: the metaNetcdf hover tooltips. (Folding is
        handled by the editor itself - double-click a section header - and by
        the line-number gutter's fold markers.)"""
        if (event.type() == QEvent.ToolTip
                and obj in (self.text_area, self.text_area.viewport())):
            try:
                self._show_meta_tooltip(event)
            except Exception:
                log.debug("meta tooltip failed", exc_info=True)
            return True
        return super().eventFilter(obj, event)
    

    
    def close_subsidiary_windows(self):
        """Close any open subsidiary windows (options window and basin viewer)"""
        # Close options window if it exists and is visible
        if hasattr(self, 'options_window') and self.options_window:
            try:
                if self.options_window.isVisible():
                    self.options_window.close()
            except Exception:
                log.debug("options window already closed/destroyed")
                
    def show_basin(self):
        """Tools ▸ Show Basin: the folium (Leaflet) basin viewer in EPSG:4326 - the
        ups.nc/mask overlays drawn in native lon/lat (no rasterio reprojection, crisp)
        over an OSM WMS basemap. (This is the former Show Basin2; the classic native /
        Mercator viewer was removed.)"""
        try:
            config_content = None
            if hasattr(self, 'original_content') and self.original_content:
                config_content = self.original_content
            if not config_content:
                QMessageBox.information(
                    self, "Show Basin",
                    "Please load a settings file first (File ▸ Load .ini, Ctrl+O).")
                self.status_bar.showMessage("Show Basin needs a loaded settings file")
                return
            # Lazy import (§4.1): pulls in numpy/xarray + folium + QtWebEngine
            from src.gui.widgets.basin_viewer2 import show_basin2
            show_basin2(config_content, self.file_manager.get_current_file_path(),
                        parent=self, default_basemap=self._default_basemap())
            self.status_bar.showMessage("Basin closed")
        except Exception as e:
            print(f"Error loading basin: {str(e)}", file=sys.stderr)
            self.status_bar.showMessage(f"Error loading basin: {str(e)}")

    def open_options_window(self):
        """Open the options window for managing boolean configuration options"""
        try:
            # Get current configuration content
            config_content = None
            if hasattr(self, 'text_display') and self.text_display:
                config_content = self.text_display.get_content()
            
            if not config_content:
                print("No configuration content available", file=sys.stderr)
                self.status_bar.showMessage("No configuration loaded")
                return
            
            # Create and show options window
            self.options_window = OptionsWindow(self, config_content)
            if self.options_window.exec():
                # Options were accepted, content has been updated
                self.status_bar.showMessage("Options updated")
                # Clear reference after use
                self.options_window = None
            else:
                # Clear reference if canceled
                self.options_window = None
            
        except Exception as e:
            print(f"Error opening options window: {str(e)}", file=sys.stderr)
            self.status_bar.showMessage(f"Error opening options: {str(e)}")
    
    def open_check_data_window(self):
        """Open the check data window for analyzing configuration data"""
        try:
            # Get current configuration content
            config_content = None
            if hasattr(self, 'text_display') and self.text_display:
                config_content = self.text_display.get_content()
            
            if not config_content:
                print("No configuration content available", file=sys.stderr)
                self.status_bar.showMessage("No configuration loaded")
                return
            
            # Create and show check data window
            # Lazy import (§4.1): check_data_window pulls in cwatm.run_cwatm
            from src.gui.widgets.check_data_window import CheckDataWindow
            self.check_data_window = CheckDataWindow(self, config_content)
            if self.check_data_window.exec():
                # Window was closed normally
                self.status_bar.showMessage("Check Data window closed")
                # Clear reference after use
                self.check_data_window = None
            else:
                # Clear reference if canceled
                self.check_data_window = None
            
        except Exception as e:
            print(f"Error opening check data window: {str(e)}", file=sys.stderr)
            self.status_bar.showMessage(f"Error opening check data: {str(e)}")

    def closeEvent(self, event):
        """Handle application close event"""
        # Prompt to save if there are unsaved changes to the settings file
        if getattr(self, "_is_dirty", False):
            reply = QMessageBox.question(
                self,
                "Unsaved changes",
                "The settings file has unsaved changes.\nSave before exiting?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.Save:
                self.save_file()
                # If the save did not clear the dirty state (e.g. no file path),
                # abort the close so the user does not lose changes.
                if self._is_dirty:
                    self.status_bar.showMessage("Save failed - exit cancelled")
                    event.ignore()
                    return

        if self.cwatm_running and self.cwatm_worker:
            # Stop CWatM execution before closing
            print("Application closing - stopping CWatM execution...", file=sys.stderr)
            self.stop_cwatm_execution()

        # Make sure the run-log file handle is released
        self._close_output_file_handle()

        # Final cleanup of any remaining file operations
        self.cleanup_file_operations()

        # Accept the close event
        event.accept()

