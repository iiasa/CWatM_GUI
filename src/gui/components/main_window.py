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

from src.gui import __version__ as GUI_VERSION
from src.gui.components.config_parser import ConfigParser
from src.gui.managers.date_manager import DateManager
from src.gui.managers.file_manager import FileManager
from src.gui.utils.progress_clock import ProgressClock
from src.gui.widgets.discharge_sparkline import DischargeSparkline
from src.gui.widgets.options_window import OptionsWindow
from src.gui.utils import display_format
from src.gui.utils import theme
from src.gui.utils.gui_log import get_logger
from src.gui.utils.meta_netcdf import get_meta
from src.gui.utils.window_geometry import scaled_default_size
# The settings editor + its gutter and TextDisplayManager are created per TAB,
# in src/gui/components/tab_manager.py - that is where they are imported.
from src.gui.components.menu_builder import MenuBuilderMixin
from src.gui.components.run_controller import RunControllerMixin
from src.gui.components.output_box import OutputBoxMixin
from src.gui.components.tab_manager import SettingsTabsMixin
from src.gui.components.settings_check import SettingsCheckMixin
from src.gui.components.find_replace import FindReplaceMixin
from src.gui.components.main_window_styles import MainWindowStyleMixin

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


class CWatMMainWindow(MenuBuilderMixin, RunControllerMixin,
                      OutputBoxMixin, SettingsTabsMixin,
                      SettingsCheckMixin, FindReplaceMixin, MainWindowStyleMixin,
                      QMainWindow):
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
        # Always open in full (maximized) view - unless CWATM_GUI_NO_MAXIMIZE is set.
        # On a **remote X display** (Xming, X2Go, VNC) a maximized window means a
        # backing store the size of the whole desktop on the X server, which can
        # exhaust it: the window then simply disappears (BadAlloc / a dropped
        # connection). Starting windowed is the way out on such a display.
        if not os.environ.get("CWATM_GUI_NO_MAXIMIZE"):
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
        # Settings-file tabs (src/gui/components/tab_manager.py). text_area /
        # text_display / line_number_gutter always point at the ACTIVE tab.
        self._tabs = []
        self._active_tab_index = -1
        self._switching_tabs = False
        self._scroll_sync = False   # reentrancy guard for tab-linked scrolling
        self._fold_sync = False     # ... and for the tab-linked section folding
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
        # Settings-editor font size in px ('Font+' / 'Font-' buttons right of Down,
        # and Preferences > Display > Font size), persisted (editor/font_size)
        self._editor_font_size = max(6, min(32,
            self._settings.value("editor/font_size", 13, type=int)))
        # Settings-editor font family (Preferences > Display > Font), persisted
        # (editor/font_family). Empty = the built-in monospace fallback chain of
        # _editor_style(), i.e. the look before this setting existed.
        self._editor_font_family = (self._settings.value("editor/font_family", "")
                                    or "").strip()
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

        # CWatM icon (dark-theme variant swapped in by _retheme)
        try:
            icon_label = QLabel()
            self._banner_icon_label = icon_label
            self._set_banner_icon_pixmap()
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

        # IIASA logo (dark-theme variant swapped in by _retheme)
        try:
            iiasa_label = QLabel()
            self._banner_iiasa_label = iiasa_label
            self._set_banner_iiasa_pixmap()
            header_layout.addWidget(iiasa_label)
        except:
            iiasa_label = QLabel("IIASA")
            iiasa_label.setStyleSheet("color: blue; font-weight: bold;")
            self._banner_iiasa_label = iiasa_label
            header_layout.addWidget(iiasa_label)

        self._banner_widget = banner_widget
        parent_layout.addWidget(banner_widget)
        # Apply the persisted Show Header state (default ON) at startup.
        try:
            show_header = self._settings.value("display/show_header", True, type=bool)
        except Exception:
            show_header = True
        banner_widget.setVisible(bool(show_header))

    def _set_banner_icon_pixmap(self):
        """(Re)load the banner's CWatM icon for the active theme - a light-on-dark
        variant for Dark Mode / Mikhail (theme.is_dark()), the normal icon otherwise.
        Called from create_header and re-run by _retheme on a Mode switch."""
        label = getattr(self, "_banner_icon_label", None)
        if label is None:
            return
        from src.gui.utils.assets import asset_path
        name = "cwatm_dark.png" if theme.is_dark() else "cwatm.ico"
        pixmap = QPixmap(asset_path(name))
        if not pixmap.isNull():
            label.setPixmap(pixmap.scaled(50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    @staticmethod
    def _svg_pixmap(path, box_w, box_h):
        """Rasterize an SVG straight to a pixmap that fits ``box_w x box_h``
        (aspect preserved), sharp at that exact size.

        ``QPixmap(svg_path)`` alone rasterizes at the SVG's tiny intrinsic
        size (its declared width/height attribute - ~225x65 for the IIASA
        logo) and a later ``.scaled()`` call is then just a blurry bilinear
        resize of that small bitmap. ``QIcon``'s SVG icon engine renders
        through ``QSvgRenderer`` at whatever pixmap size is actually
        requested, so asking it for the already aspect-fitted size below
        gives a crisp result with no separate blur step."""
        from PySide6.QtSvg import QSvgRenderer
        renderer = QSvgRenderer(path)
        if not renderer.isValid():
            return QPixmap()
        natural = renderer.defaultSize()
        nat_w = natural.width() or box_w
        nat_h = natural.height() or box_h
        ratio = min(box_w / nat_w, box_h / nat_h)
        fit_w = max(1, round(nat_w * ratio))
        fit_h = max(1, round(nat_h * ratio))
        return QIcon(path).pixmap(fit_w, fit_h)

    def _set_banner_iiasa_pixmap(self):
        """(Re)load the banner's IIASA logo for the active theme - a white vector
        variant for Dark Mode / Mikhail (theme.is_dark()), the normal logo
        otherwise. Rendered via _svg_pixmap so it stays sharp at banner size.
        Called from create_header and re-run by _retheme on a Mode switch."""
        label = getattr(self, "_banner_iiasa_label", None)
        if label is None:
            return
        from src.gui.utils.assets import asset_path
        name = "iiasa-logo-dark.svg" if theme.is_dark() else "iiasa-logo.svg"
        pixmap = self._svg_pixmap(asset_path(name), 180, 90)
        if not pixmap.isNull():
            label.setPixmap(pixmap)
        else:
            label.setText("IIASA")
            label.setStyleSheet("color: blue; font-weight: bold;")

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
            gauge_warning = ("Gauge is not inside the basin! Change manually or use "
                             "Tools/Set max Gauge.")

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


    def open_excel_workbook(self):
        """Excel ▸ Crops/Reservoirs: open the settings Excel_settings_file in an
        editable, colour-preserving table; every sheet of the workbook (Crops,
        Reservoirs, Reservoirs_downstream, ...) is a tab below the table."""
        import configparser
        title = "Excel"               # title of this action's message boxes
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
            QMessageBox.warning(self, title, "Could not parse the settings file.")
            return
        from src.gui.widgets.basin_viewer import (
            _find_setting_value, _resolve_settings_placeholders)
        excel = _find_setting_value(config, "Excel_settings_file")
        if not excel:
            QMessageBox.information(
                self, title,
                "No 'Excel_settings_file' entry found in the settings file.")
            return
        resolved = _resolve_settings_placeholders(excel.strip(), config)
        if "$(" in resolved:
            QMessageBox.warning(
                self, title, f"Could not resolve the Excel path:\n{excel}")
            return
        if not os.path.isabs(resolved):
            base = self.working_dir()
            if base:
                resolved = os.path.join(base, resolved)
        if not os.path.exists(resolved):
            QMessageBox.warning(
                self, title, f"The Excel file does not exist:\n{resolved}")
            return
        try:
            from src.gui.widgets.excel_sheet_window import ExcelSheetWindow
            win = ExcelSheetWindow(resolved, parent=self)
            win.exec()
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, title, f"Could not open the Excel file:\n{e}")

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
                "Set max Gauge: could not determine a gauge location "
                "(check MaskMap / ups.nc)")
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
        # Jump the editor to the end of the file first (same as Settings ▸ Down):
        # [OUTPUT] is the last section, so the OUT_… lines a picked variable goes on
        # are on screen - and the cursor, which a left-click inserts at, is already
        # down there instead of wherever it was left.
        self.jump_to_bottom()
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

    def _on_use_tabs_toggled(self, checked):
        """Preferences ▸ Editor & Dates ▸ Use Tabs: persist the choice and show or
        hide the tab bar (Expert only - see tabs_enabled)."""
        try:
            self._settings.setValue("editor/use_tabs", bool(checked))
        except Exception:
            log.debug("persist editor/use_tabs failed", exc_info=True)
        self.update_tabs_visible()

    def _on_bookmark_change_toggled(self, checked):
        """Mirror the 'Bookmark Change' state to every tab's editor and persist it.
        When on, changed lines get auto-bookmarked."""
        try:
            self._settings.setValue("editor/bookmark_change", bool(checked))
        except Exception:
            log.debug("_on_bookmark_change_toggled: ignored", exc_info=True)
        editors = self.all_editors() or (
            [self.text_area] if getattr(self, "text_area", None) is not None else [])
        for editor in editors:
            try:
                editor.set_auto_bookmark_changed(bool(checked))
            except Exception:
                log.debug("set_auto_bookmark_changed failed", exc_info=True)

    def _on_web_picker_toggled(self, checked):
        """Configure > Web-style date picker: switch the Start/Spin/End fields
        between the frameless 📅 popup (on) and the classic drop-down (off)."""
        try:
            self._settings.setValue("display/date_picker_web", bool(checked))
        except Exception:
            log.debug("_on_web_picker_toggled: ignored", exc_info=True)
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
            log.debug("_on_date_timeline_toggled: ignored", exc_info=True)
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
            log.debug("_on_show_header_toggled: ignored", exc_info=True)
        try:
            if getattr(self, "_banner_widget", None) is not None:
                self._banner_widget.setVisible(bool(checked))
        except Exception:
            log.debug("show header toggle failed", exc_info=True)

    def _on_tooltip_reverse_toggled(self, checked):
        """Preferences ▸ Display ▸ Tooltip reverse: show tooltips with the text and
        background colours **swapped** (light on dark instead of the platform's dark
        on light).

        Applied as an application-wide ``QToolTip`` rule, so every window - including
        the ones already open - follows at once. The colours are theme tokens, so
        `_retheme` re-applies this after a Mode switch."""
        try:
            self._settings.setValue("display/tooltip_reverse", bool(checked))
        except Exception:
            log.debug("_on_tooltip_reverse_toggled: ignored", exc_info=True)
        self._apply_tooltip_style(bool(checked))

    #: The platform's own tooltip palette, captured before the first reverse so
    #: switching back restores exactly what Qt had.
    _tooltip_palette = None

    def _apply_tooltip_style(self, reverse=None):
        """(Re)apply the QToolTip rule for the current Mode. ``reverse=None`` reads
        the stored setting - used by `_retheme`."""
        from PySide6.QtWidgets import QApplication
        if reverse is None:
            try:
                reverse = self._settings.value(
                    "display/tooltip_reverse", False, type=bool)
            except Exception:
                reverse = False
        from PySide6.QtWidgets import QToolTip
        from PySide6.QtGui import QPalette, QColor
        app = QApplication.instance()
        if app is None:
            return
        sheet = app.styleSheet() or ""
        # Drop a previous QToolTip block of ours, then add the new one (if any).
        sheet = re.sub(r"\s*/\* cwatm-tooltip \*/.*?\}", "", sheet, flags=re.S).strip()
        # Reversed = the plain opposite of the platform's tooltip: **white on black**
        # on a light Mode, black on white on a dark one. Theme tokens (slate on
        # off-white) would not read as "reversed" at all.
        fg, bg = ("black", "white") if theme.is_dark() else ("white", "black")
        if reverse:
            sheet = (sheet + "\n/* cwatm-tooltip */ QToolTip { "
                     f"color: {fg}; background-color: {bg}; "
                     f"border: 1px solid {fg}; padding: 3px; }}").strip()
        try:
            app.setStyleSheet(sheet)
        except Exception:
            log.debug("tooltip style failed", exc_info=True)
        # Belt and braces: the stylesheet alone is not enough. A tooltip **is** a
        # QLabel, so any `QLabel { … }` rule reaching the widget it belongs to paints
        # it too - which is how the Options window's badge coloured its own tooltip.
        # QToolTip's palette is not affected by that, so set it as well.
        try:
            if self._tooltip_palette is None:
                self._tooltip_palette = QPalette(QToolTip.palette())
            palette = QPalette(self._tooltip_palette)
            if reverse:
                palette.setColor(QPalette.ToolTipBase, QColor(bg))
                palette.setColor(QPalette.ToolTipText, QColor(fg))
                palette.setColor(QPalette.Window, QColor(bg))
                palette.setColor(QPalette.WindowText, QColor(fg))
            QToolTip.setPalette(palette)
        except Exception:
            log.debug("tooltip palette failed", exc_info=True)

    def open_preferences(self):
        """Configure ▸ Preferences… (Ctrl+,) and the ⋮ button in the menu bar's
        right corner: the categorised window holding every GUI setting.

        Modal, and built fresh each time so it picks up the active theme. It edits
        a buffered copy and pushes the changed settings back through the handlers
        below on Apply/OK (see src/gui/widgets/preferences_window.py)."""
        try:
            from src.gui.widgets.preferences_window import open_preferences
            open_preferences(self)
        except Exception as e:
            log.warning("opening Preferences failed", exc_info=True)
            print(f"Error opening Preferences: {str(e)}", file=sys.stderr)

    def _default_basemap(self):
        """Return the default basemap chosen in Configure ▸ Default openstreet map.
        This is now a Show Basin2 WMS layer name (e.g. "OSM-WMS"); the classic Show
        Basin ignores an unknown key and falls back to its own "standard" tiles."""
        return self._settings.value("basin/default_basemap", "OSM-WMS")

    def _set_default_basemap(self, key):
        """Persist the default OpenStreetMap basemap chosen in the Configure menu."""
        self._settings.setValue("basin/default_basemap", key)
        self.status_bar.showMessage(f"Default OpenStreetMap basemap: {key}")

    def _set_animal(self, name):
        """Configure > Select animal: persist the chosen cameo animal and apply it to
        the live discharge sparkline."""
        self._settings.setValue("display/animal", name)
        spark = getattr(self, "discharge_sparkline", None)
        if spark is not None:
            try:
                spark.set_animal(name)
            except RuntimeError:
                log.debug("_set_animal: ignored", exc_info=True)
        self.status_bar.showMessage(f"Sparkline animal: {name}")

    def open_pathout_folder(self):
        """Tools > Open PathOut Folder: show the resolved PathOut directory in the
        system file browser."""
        path = self._resolved_pathout_dir()
        if not path:
            self.status_bar.showMessage(
                "PathOut does not exist - use Tools/Create PathOut Folder first")
            return
        from src.gui.utils.open_path import open_path
        if not open_path(path):
            log.warning("could not open PathOut folder: %s", path)
            self.status_bar.showMessage(f"Could not open PathOut: {path}")

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

        font_plus_button = QPushButton("Font+")
        font_plus_button.setStyleSheet(modern_button_style)
        font_plus_button.setToolTip("Increase the settings-editor font size\n"
                                    "(Preferences ▸ Display ▸ Font size)")
        font_plus_button.clicked.connect(self.increase_editor_font_size)
        save_controls.addWidget(font_plus_button)

        font_minus_button = QPushButton("Font-")
        font_minus_button.setStyleSheet(modern_button_style)
        font_minus_button.setToolTip("Decrease the settings-editor font size\n"
                                     "(Preferences ▸ Display ▸ Font size)")
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

        # (A new tab is opened from the tab bar's right-click menu - 'Add empty
        # Tab' - so there is no Add Tab button in this row.)

        # kept so a theme switch can re-style them (_retheme)
        self._nav_buttons = [save_button, save_as_button, compress_all_button,
                             expand_all_button, top_button, down_button,
                             font_plus_button, font_minus_button]
        
        
        save_controls.addStretch()
        right_layout.addLayout(save_controls)
        
        # Settings-file tabs: the tab bar sits directly below the button row, the
        # editors live in a QStackedWidget below it - one plain-text SettingsEditor
        # + line-number gutter per tab (report §3.2; the document is the settings
        # file at all times, saving is toPlainText()). text_area / text_display /
        # line_number_gutter always point at the ACTIVE tab - see tab_manager.py.
        self.build_settings_tabs(right_layout)

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
        dlg.resize(*scaled_default_size(dlg, 920, 720))
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
        gui_version_header = QLabel(f"CWatM GUI version {GUI_VERSION}")
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
        """Grey out Tools > Excel Crops/Reservoirs when the settings file has no
        'Excel_settings_file' key - there is nothing for it to open. The rest of the
        Tools menu is untouched, so the item can still be seen (and its tooltip read)."""
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
        """File ▸ Load .ini: pick a settings file and load it into the active tab.

        The dialog only supplies the path - the load itself goes through
        load_recent_file like every other one (History, drag & drop, startup), so
        the duplicate-tab guard and the recent-files bookkeeping cannot be
        bypassed by this route."""
        path = self.file_manager.choose_load_path()
        if path:
            self.load_recent_file(path)

    def load_recent_file(self, path):
        """Load a settings file into the ACTIVE tab (History menu, drag & drop,
        the Load dialog, the startup restore). Refuses - and switches to the tab
        that has it - when the file is already open in another tab."""
        if not path or not os.path.exists(path):
            self.status_bar.showMessage(f"File not found: {path}")
            self._recent_files = [p for p in self._recent_files if p != path]
            self._settings.setValue("recent_files", self._recent_files)
            return
        if not self.guard_duplicate_file(path, action="Load"):
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

                # The file belongs to the active tab - re-caption it and remember
                # the open set for "Load previous settings at start"
                self.note_active_tab_file()

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


    def increase_editor_font_size(self):
        """'Font+' button: grow the settings-editor font by 1 px (capped)."""
        self._set_editor_font_size(self._editor_font_size + 1)

    def decrease_editor_font_size(self):
        """'Font-' button: shrink the settings-editor font by 1 px (floored)."""
        self._set_editor_font_size(self._editor_font_size - 1)

    def _set_editor_font_size(self, size):
        """The one place the editor font size changes - the Font+/Font- buttons and
        Preferences ▸ Display ▸ Font size both come through here, so the two can
        never drift apart."""
        self._editor_font_size = max(6, min(32, size))
        self._settings.setValue("editor/font_size", self._editor_font_size)
        # The font is a global setting - apply it to every tab's editor. The
        # gutter derives its font from the editor's, so repaint it too and the
        # numbers keep lining up with the (re-laid-out) text rows.
        self._restyle_all_editors()

    def editor_font_family(self):
        """The font family the settings editor is *rendered* with.

        The persisted choice when there is one, otherwise the family the built-in
        fallback chain actually resolved to on this machine (Consolas on Windows) -
        so Preferences shows what the user sees rather than an empty box."""
        if self._editor_font_family:
            return self._editor_font_family
        try:
            return self.text_area.fontInfo().family()
        except Exception:
            return "Consolas"

    def set_editor_font_family(self, family):
        """Preferences ▸ Display ▸ Font: set the settings-editor font family.

        An empty value restores the built-in fallback chain of _editor_style()."""
        self._editor_font_family = (family or "").strip()
        self._settings.setValue("editor/font_family", self._editor_font_family)
        self._restyle_all_editors()

    def _restyle_all_editors(self):
        """Re-apply the editor stylesheet (font family/size, theme) to every tab."""
        for tab in getattr(self, "_tabs", []):
            try:
                tab.editor.setStyleSheet(self._editor_style())
                tab.gutter.update()
            except RuntimeError:
                log.debug("editor gone while restyling", exc_info=True)

    # ---------------------------------------------------- experience level
    def cycle_experience_level(self):
        """Level button: Beginner -> Advanced -> Expert -> Beginner."""
        idx = _EXPERIENCE_LEVELS.index(self._experience_level)
        nxt = _EXPERIENCE_LEVELS[(idx + 1) % len(_EXPERIENCE_LEVELS)]
        self.set_experience_level(nxt)

    def set_experience_level(self, level):
        """Set the experience level (from the level button or Preferences ▸ Editor &
        Dates ▸ Skill of user) and apply it. Keeps a menu radio group in sync if one
        exists."""
        if level not in _EXPERIENCE_LEVELS or level == self._experience_level:
            self._sync_level_menu()
            return
        self._experience_level = level
        self._settings.setValue("editor/level", self._experience_level)
        self.level_button.setText(self._experience_level)
        self._apply_level_button_style()
        self._sync_level_menu()
        self._apply_experience_level()
        self._apply_menu_level()      # Beginner also hides the advanced menu entries
        self.update_tabs_visible()    # the settings-file tabs are Expert-only

    def _sync_level_menu(self):
        """Tick the matching Skill-of-user radio item. The level lives in the
        Preferences window (a combo box, read fresh on open), so there is no menu
        to sync any more - a no-op unless `_level_menu_actions` is populated again."""
        actions = getattr(self, "_level_menu_actions", None)
        if not actions:
            return
        for lvl, act in actions.items():
            try:
                act.setChecked(lvl == self._experience_level)
            except RuntimeError:
                log.debug("_sync_level_menu: ignored", exc_info=True)

    def _apply_experience_level(self):
        """Hide the settings sections the current level may not see: locked
        sections are fully hidden (header + content) and cannot be unfolded.
        Expert shows everything. Recomputed from the editor's current section list
        so it stays correct after loading a different file."""
        allowed = _LEVEL_ALLOWED.get(self._experience_level)
        # The level is a global setting: every tab hides the sections it may not
        # see, each computed from that tab's own section list.
        editors = self.all_editors() or (
            [self.text_area] if getattr(self, "text_area", None) is not None else [])
        for editor in editors:
            try:
                if allowed is None:   # Expert - no restriction
                    locked = set()
                else:
                    locked = {s for s in editor.section_names() if s not in allowed}
                editor.set_locked_sections(locked)
            except RuntimeError:
                log.debug("editor gone while applying the level", exc_info=True)


    def _retheme(self):
        """Re-apply every theme-dependent style after a Configure ▸ Mode switch.
        The app-wide palette/stylesheet is already applied by the caller."""
        try:
            # The reversed-tooltip rule is built from theme tokens and lives on the
            # application stylesheet the switch just replaced - put it back first.
            self._apply_tooltip_style()
            self.menu_bar.setStyleSheet(self._menu_bar_stylesheet())
            self._banner_title.setStyleSheet(f"color: {theme.c('accent')};")
            self.interface_label.setStyleSheet(f"color: {theme.c('text_muted')};")
            self._set_banner_icon_pixmap()
            self._set_banner_iiasa_pixmap()
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
            # editors + gutters of EVERY tab, clock, output box
            self._style_tab_chrome()          # tab bar + the '+' tab
            for _tab in getattr(self, "_tabs", []):
                _tab.editor.setStyleSheet(self._editor_style())
                _tab.editor.retheme()
                _tab.gutter.update()
            self.progress_clock.update()
            if getattr(self, "discharge_sparkline", None) is not None:
                self.discharge_sparkline.update()
            self.cwatminfo_box.setStyleSheet(self._output_box_style())
        except Exception:
            log.warning("retheme failed", exc_info=True)

    def _set_save_dirty(self, dirty):
        """Colour the Save / Save As buttons blue when there are unsaved changes.

        The dirty flag belongs to the ACTIVE tab, so its caption gets the '*'."""
        self._is_dirty = bool(dirty)
        tab = self.current_tab()
        if tab is not None and tab.is_dirty != self._is_dirty:
            tab.is_dirty = self._is_dirty
            self.refresh_tab_label(tab)
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
                log.debug("_set_save_dirty: ignored", exc_info=True)

    def _on_doc_modified(self, changed):
        """Editor document modification state changed (ignored during programmatic
        re-renders, which set self._suppress_dirty).

        Every tab's document is connected here, so a signal from a background tab
        (e.g. while its content is being reset) must not touch the window state -
        the dirty flag belongs to the tab the user is looking at."""
        if self._suppress_dirty or not self._is_active_editor_signal(document=True):
            return
        self._set_save_dirty(changed)

    def _is_active_editor_signal(self, document=False):
        """True when the signal being handled came from the ACTIVE tab's editor
        (or its document). Signals from other tabs are ignored - see the tabs
        note in tab_manager.py."""
        editor = getattr(self, "text_area", None)
        if editor is None:
            return False
        sender = self.sender()
        if sender is None:          # called directly, not from a signal
            return True
        return sender is (editor.document() if document else editor)

    def _on_editor_text_changed(self):
        """Mirror the live editor document into self.original_content on every edit.

        original_content is the authoritative in-memory settings text used by the
        field auto-apply, the gauge/PathOut checks, Show Basin, the Excel menu, etc.
        It is only refreshed on load/save/undo before this hook, so manual typing in
        the editor left it stale - a subsequent field change then rebuilt from the
        pre-typing snapshot and silently discarded the user's edits. Keeping it in
        step with the document keeps every consumer on the current text. (This does
        not touch the Save-dirty / diff baseline, which is self._clean_content.)

        Only the ACTIVE tab's editor drives this - a background tab keeps its text
        in its own SettingsTab (tab_manager.py)."""
        if not self._is_active_editor_signal():
            return
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
        """RUN CWATM > Journal of Runs: show the log of past runs."""
        try:
            from src.gui.widgets.run_ledger_window import open_run_ledger
            open_run_ledger(parent=self)
        except Exception as e:
            print(f"Error opening Journal of Runs: {str(e)}", file=sys.stderr)

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
                log.debug("open_cwatm_ai: ignored", exc_info=True)

    # -------------------------------------------- CWatM AI <-> settings bridge
    def ai_current_settings_line(self):
        """Text of the settings editor's current cursor line (or the selection if
        any), for CWatM AI 'explain this line'. Empty string if no editor."""
        ed = getattr(self, "text_area", None)
        if ed is None:
            return ""
        cur = ed.textCursor()
        if cur.hasSelection():
            # QTextCursor.selectedText() joins lines with U+2029 (PARAGRAPH SEPARATOR),
            # not a newline. Written as an escape so the source holds no literal
            # separator: str.splitlines() breaks on one and the tokenizer does not,
            # which puts every line-based tool one line out of step from here on.
            return cur.selectedText().replace('\u2029', '\n').strip()
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
                log.debug("open_compare_settings: ignored", exc_info=True)

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
                read_netcdf_attrs, RestoreSettingsWindow)
            # Every global attribute in ONE open - the window filters the bulky ones
            # out of its table and serves its buttons from the same read (these files
            # usually sit on a network share, where each open is the slow part).
            metadata = read_netcdf_attrs(path)
            win = RestoreSettingsWindow(path, metadata, self)
            win.exec()
        except Exception as e:
            print(f"Error opening Restore settingsfile: {str(e)}", file=sys.stderr)
            try:
                QMessageBox.warning(
                    self, "Restore settingsfile",
                    f"Could not read the NetCDF metadata:\n{e}")
            except Exception:
                log.debug("restore_settingsfile: ignored", exc_info=True)

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
            # Ask for the path first: saving onto a file another tab has open would
            # put one settings file in two tabs (see guard_duplicate_file).
            target = self.file_manager.choose_save_path()
            if not target:
                self.status_bar.showMessage("Save cancelled")
                return
            if not self.guard_duplicate_file(target, action="Save as", switch=False):
                return
            success, filename, message = self.file_manager.save_as_file(content, target)
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
            # Save As gives the active tab a new file - re-caption it (and drop the '*')
            self.note_active_tab_file()
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
            
            # Non-modal (since 1.05): the settings editor stays readable while the
            # switches are being changed - each tick is applied to the content at
            # once anyway, so there is nothing to accept or cancel. The reference is
            # kept so the window is not garbage-collected, and dropped on close.
            self.options_window = OptionsWindow(self, config_content)
            self.options_window.destroyed.connect(
                lambda *_: setattr(self, "options_window", None))
            self.options_window.show()
            self.options_window.raise_()
            self.options_window.activateWindow()

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
            
            # Already open (it is non-modal now): raise it instead of stacking a
            # second copy - and never replace one while its check is running.
            existing = getattr(self, "check_data_window", None)
            if existing is not None:
                try:
                    if existing.isVisible():
                        existing.raise_()
                        existing.activateWindow()
                        return
                except RuntimeError:
                    log.debug("open_check_data_window: ignored", exc_info=True)  # deleted C++ object - fall through

            # Create and show check data window.
            # Lazy import (§4.1): check_data_window pulls in cwatm.run_cwatm
            from src.gui.widgets.check_data_window import CheckDataWindow
            # NOT modal / not exec(): the check itself runs in a worker thread, and a
            # modal dialog would keep the GUI blocked anyway - which is exactly what
            # threading it was meant to fix. Kept referenced so it is not GC'd.
            self.check_data_window = CheckDataWindow(self, config_content)
            self.check_data_window.show()
            self.check_data_window.raise_()
            self.check_data_window.activateWindow()
            self.status_bar.showMessage("Check Data window opened")
            
        except Exception as e:
            print(f"Error opening check data window: {str(e)}", file=sys.stderr)
            self.status_bar.showMessage(f"Error opening check data: {str(e)}")

    def closeEvent(self, event):
        """Handle application close event"""
        # Prompt to save every tab that has unsaved changes (one prompt per file,
        # naming it; Cancel or a failed save aborts the exit) - tab_manager.py
        if not self.confirm_all_tabs_saved():
            event.ignore()
            return

        # Hidden Run windows are children of this one: closing here kills their model
        # processes too, so say so rather than ending someone's multi-hour run silently.
        hidden = []
        for win in list(getattr(self, "_hidden_run_windows", []) or []):
            try:
                if getattr(win, "_running", False):
                    hidden.append(win)
            except RuntimeError:
                continue
        if hidden:
            if QMessageBox.question(
                    self, "Windowed runs in progress",
                    f"{len(hidden)} Windowed Run window(s) are still running "
                    "CWatM.\n\n"
                    "Closing the GUI stops them. Close anyway?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No) != QMessageBox.Yes:
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

