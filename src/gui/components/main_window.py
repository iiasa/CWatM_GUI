"""
Main window for CWatM GUI application.

Orchestrates all components and handles user interactions.
Provides the main interface for loading, parsing, editing,
and managing CWatM configuration files.
"""

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QStatusBar, QFrame,
    QLineEdit, QProgressBar, QApplication, QScrollArea, QCheckBox,
    QSizePolicy, QMenuBar, QMessageBox, QDialog, QMenu, QInputDialog, QFileDialog
)
from PySide6.QtCore import Qt, QEvent, QTimer, QThread, Signal
from PySide6.QtGui import (
    QFont, QPixmap, QIcon, QMouseEvent, QTextCursor,
    QPainter, QPen, QColor
)
import math
import threading
import sys
import gc
import os
import time
import re

from src.gui.components.config_parser import ConfigParser
from src.gui.managers.date_manager import DateManager
from src.gui.managers.file_manager import FileManager
from src.gui.managers.text_display import TextDisplayManager
from src.gui.utils.progress_clock import ProgressClock
from src.gui.widgets.options_window import OptionsWindow
from src.gui.widgets.check_data_window import CheckDataWindow
from src.gui.utils.cwatm_worker import CWatMWorker
from src.gui.widgets.basin_viewer import (
    BasinViewer, build_mask_context, gauges_inside, pathout_exists,
    find_largest_ups_gauge
)

import cwatm.run_cwatm as run_cwatm
import cwatm.version as version


class CWatMMainWindow(QMainWindow):
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
        screen = QApplication.primaryScreen().availableGeometry()
        self.setMinimumSize(800, 600)  # Minimum size for usability
        # Start maximized only on larger screens
        if screen.width() >= 1400 and screen.height() >= 900:
            self.setWindowState(Qt.WindowMaximized)
        else:
            # Center window on smaller screens
            x = (screen.width() - self.width()) // 2
            y = (screen.height() - self.height()) // 2
            self.move(x, y)
        
        # Set window icon (prefer the small multi-size icon for the taskbar; only if it
        # loads, so a missing file does not override the app icon set in cwatm_gui.py)
        try:
            _icon = QIcon("assets/cwatm_small.ico")
            if _icon.isNull():
                _icon = QIcon("assets/cwatm.ico")
            if not _icon.isNull():
                self.setWindowIcon(_icon)
        except Exception:
            pass  # Icon file not found, continue without icon
        
        # Initialize components
        self.config_parser = ConfigParser()
        self.date_manager = DateManager()
        self.file_manager = FileManager(self)
        
        # UI elements
        self.text_area = None
        self.text_display = None
        self.filename_label = None
        self.pathout_field = None
        self.maskmap_field = None
        self.run_cwatm_button = None
        self.progress_clock = None
        self.cwatminfo_label = None
        self.actualize_button = None
        self.collapsed_sections = set()
        self.original_content = ""
        self.file_parsed = False
        self.cwatm_output_buffer = []
        self._last_was_progress = False  # last output line was a '\r' progress update
        self._suppress_dirty = False  # ignore dirty signals during programmatic updates
        self._is_dirty = False  # there are unsaved changes to the settings file
        # Debounce timer: auto-apply field changes (dates / PathOut / MaskMap) into the
        # in-memory settings content shortly after the user stops changing them.
        self._field_update_timer = QTimer(self)
        self._field_update_timer.setSingleShot(True)
        self._field_update_timer.setInterval(500)
        self._field_update_timer.timeout.connect(self._apply_field_changes)
        self.temp_content_storage = {}  # Store content before compression
        self.cwatm_running = False
        self.cwatm_worker = None
        self.compress_expand_scroll_position = None
        self.manual_changes_buffer = ""  # Store manual changes made to text
        self.output_file_path = None  # Path to the output file when checkbox is checked
        self._output_file_override = None  # custom output-box file set via Configure menu
        self._pathout_warning = ""  # PathOut-missing warning (checked only on load/save)
        self._mask_context = None   # in-memory mask for gauge checks (built on load/save)
        self._mask_context_key = None  # MaskMap value the cached mask was built from
        
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

        # Main content layout (left and right panels). Built before the menu bar
        # because the menu references widgets the panels create (the write-output
        # checkbox).
        content_layout = QHBoxLayout()

        # Left panel with controls
        self.create_left_panel(content_layout)

        # Right panel with text display
        self.create_right_panel(content_layout)

        # Menu bar directly below the banner (inserted just under the header)
        self.create_menu_bar(main_layout)

        # Set responsive sizing for panels based on screen size (right panel 20% smaller)
        screen_width = QApplication.primaryScreen().availableGeometry().width()
        if screen_width < 1024:  # Smaller screens
            # On small screens, give more space to left panel, right panel 20% smaller
            content_layout.setStretch(0, 6)  # Left panel gets 6 parts 
            content_layout.setStretch(1, 6)  # Right panel gets 6 parts (was 7, reduced by ~20%)
        else:
            # On larger screens, right panel 20% smaller than before
            content_layout.setStretch(0, 4)  # Left panel gets 4 parts (increased to compensate)
            content_layout.setStretch(1, 4)  # Right panel gets 4 parts (was 5, reduced by 20%)
        
        main_layout.addLayout(content_layout)
        
    def create_header(self, parent_layout):
        """Create header with title and logo.
        
        Args:
            parent_layout: The parent layout to add the header to
        """
        header_layout = QHBoxLayout()
        
        # CWatM icon
        try:
            icon_label = QLabel()
            pixmap = QPixmap("assets/cwatm.ico")
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(50, 50, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                icon_label.setPixmap(scaled_pixmap)
            header_layout.addWidget(icon_label)
        except:
            pass
        
        # Title
        title_label = QLabel("CWatM GUI")
        title_label.setAlignment(Qt.AlignLeft)
        # Make title font size responsive
        screen_width = QApplication.primaryScreen().availableGeometry().width()
        title_font_size = max(20, min(33, screen_width // 35))  # Scale with screen width
        title_label.setFont(QFont("Arial", title_font_size, QFont.Bold))
        title_label.setStyleSheet("color: #0066CC;")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        # Interface description, centred in the middle of the banner
        interface_label = QLabel("The Community Water Model User Interface")
        interface_label.setAlignment(Qt.AlignCenter)
        interface_label.setStyleSheet("color: #333333;")
        self.interface_label = interface_label
        # No word wrap; instead the font is sized to the current window width and
        # shrinks as the window shrinks (see _update_interface_font / resizeEvent).
        self._update_interface_font()
        header_layout.addWidget(interface_label)

        header_layout.addStretch()

        # IIASA logo
        try:
            iiasa_label = QLabel()
            iiasa_pixmap = QPixmap("assets/iiasa-logo.svg")
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
        
        parent_layout.addLayout(header_layout)

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
        self._update_interface_font()
        self._cap_output_box_width()

    def _cap_output_box_width(self):
        """Cap the output box width at the right edge of the End Date field, so the
        box ends where the calendar fields end."""
        sa = getattr(self, "scroll_area", None)
        end = getattr(self.date_manager, "end_date_edit", None) if self.date_manager else None
        if sa is None or end is None:
            return
        right = end.geometry().right()
        if right > 150:  # only once the date row has actually been laid out
            # Fixed width (not just a maximum) so the box keeps this width and the
            # trailing stretch in its container pins it to the left instead of centring.
            sa.setFixedWidth(right)

    def find_text(self):
        """Prompt for a search string and find it in the settings (.ini) editor."""
        if getattr(self, "text_area", None) is None:
            return
        text, ok = QInputDialog.getText(self, "Find", "Find text:")
        if ok and text:
            self._last_search = text
            self._find_in_editor(text)

    def find_next(self):
        """Find the next occurrence of the last searched text (re-runs Find if none)."""
        text = getattr(self, "_last_search", "")
        if text:
            self._find_in_editor(text)
        else:
            self.find_text()

    def _find_in_editor(self, text):
        """Search forward from the cursor; wrap to the top if not found. Returns bool."""
        if self.text_area.find(text):
            return True
        # Wrap around: jump to the top and search again
        cursor = self.text_area.textCursor()
        cursor.movePosition(QTextCursor.Start)
        self.text_area.setTextCursor(cursor)
        return self.text_area.find(text)

    def create_left_panel(self, parent_layout):
        """Create left control panel with all input controls.
        
        Creates file controls, date fields, path inputs, action buttons,
        and the CWatM execution interface.
        
        Args:
            parent_layout: The parent layout to add the panel to
        """
        # Create outer container with scroll area for smaller screens
        left_container = QWidget()
        left_container_layout = QVBoxLayout(left_container)
        left_container_layout.setContentsMargins(0, -15, 0, 0)  # Shift content up by 15 pixels
        
        # Create scroll area for the control panel
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_scroll.setFrameShape(QFrame.NoFrame)  # Remove scroll area border
        
        left_panel = QWidget()
        left_panel.setStyleSheet("""
            QWidget {
                background-color: #ffffff;
                border-radius: 12px;
                margin: 6px 8px 8px 8px;
                margin-top: 1px;
                padding: 5px 8px 8px 8px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.08);
            }
        """)
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
        left_layout.addSpacing(5)

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
        
        # Connect date change signals to actualize button coloring
        self.date_manager.start_date_edit.dateChanged.connect(self.on_field_changed)
        self.date_manager.spin_date_edit.dateChanged.connect(self.on_field_changed)
        self.date_manager.end_date_edit.dateChanged.connect(self.on_field_changed)
        
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
        
        parent_layout.addWidget(left_container, 1)
        
    def create_file_controls(self, parent_layout):
        """Create file loading controls"""
        load_layout = QHBoxLayout()
        load_layout.setSpacing(5)  # Minimal horizontal spacing
        load_layout.setContentsMargins(0, 2, 0, 2)  # Minimal vertical margins
        
        load_button = QPushButton("Load Text")
        # Make button heights responsive to screen size
        screen_height = QApplication.primaryScreen().availableGeometry().height()
        button_height = max(35, min(50, screen_height // 20))  # Between 35-50px based on screen height
        load_button.setMinimumHeight(button_height)
        load_button.setMinimumWidth(120)  # Slightly smaller minimum width
        load_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #ffffff, stop:1 #f1f3f4);
                border: 2px solid #e1e5e9;
                border-radius: 8px;
                color: #2c3e50;
                font-weight: 600;
                font-size: 13px;
                padding: 8px 16px;
                min-height: 32px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                border-color: #74b9ff;
                box-shadow: 0 2px 8px rgba(116, 185, 255, 0.2);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #e9ecef, stop:1 #dee2e6);
                border-color: #0984e3;
            }
        """)
        load_button.clicked.connect(self.load_file)
        load_button.setVisible(False)  # "Load Text" removed from UI; use File > Load .ini

        self.filename_label = QLabel("No file loaded")
        self.filename_label.setStyleSheet("color: gray; font-style: italic;")
        # 2pt larger font, kept via QFont so the later setStyleSheet calls (which set
        # only colour/weight) do not reset the size.
        _fl_font = self.filename_label.font()
        if _fl_font.pointSize() > 0:
            _fl_font.setPointSize(_fl_font.pointSize() + 2)
            self.filename_label.setFont(_fl_font)
        load_layout.addWidget(self.filename_label)

        load_layout.addStretch()
        parent_layout.addLayout(load_layout)
        parent_layout.addSpacing(1)  # Minimal spacing after file controls
        
        
    def create_run_button(self, parent_layout):
        """Create actualize and run buttons"""
        # Actualize button
        actualize_layout = QHBoxLayout()
        actualize_layout.setSpacing(3)  # Ultra-minimal horizontal spacing
        actualize_layout.setContentsMargins(0, 1, 0, 1)  # Ultra-minimal vertical margins
        
        self.actualize_button = QPushButton("Actualize")
        # Use same responsive height as other buttons
        screen_height = QApplication.primaryScreen().availableGeometry().height()
        button_height = max(35, min(50, screen_height // 20))
        self.actualize_button.setMinimumHeight(button_height)
        self.actualize_button.setMinimumWidth(120)
        self.actualize_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #ffffff, stop:1 #f1f3f4);
                border: 2px solid #e1e5e9;
                border-radius: 8px;
                color: #2c3e50;
                font-weight: 600;
                font-size: 13px;
                padding: 8px 16px;
                min-height: 32px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                border-color: #74b9ff;
                box-shadow: 0 2px 8px rgba(116, 185, 255, 0.2);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #e9ecef, stop:1 #dee2e6);
                border-color: #0984e3;
            }
        """)
        self.actualize_button.clicked.connect(self.run_configuration)
        self.actualize_button.setVisible(False)  # use RUN CWATM > Actualize instead
        
        
        actualize_layout.addStretch()
        
        parent_layout.addLayout(actualize_layout)
        parent_layout.addSpacing(2)  # Minimal spacing after actualize button
        
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
        run_cwatm_layout.setContentsMargins(0, 2, 0, 2)  # Minimal vertical margins
        
        self.run_cwatm_button = QPushButton("RUN CWatM")
        # Use same responsive height as other buttons
        screen_height = QApplication.primaryScreen().availableGeometry().height()
        button_height = max(35, min(50, screen_height // 20))
        self.run_cwatm_button.setMinimumHeight(button_height)
        self.run_cwatm_button.setMinimumWidth(120)
        self.run_cwatm_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #ffffff, stop:1 #f1f3f4);
                border: 2px solid #e1e5e9;
                border-radius: 8px;
                color: #2c3e50;
                font-weight: 600;
                font-size: 13px;
                padding: 8px 16px;
                min-height: 32px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                border-color: #74b9ff;
                box-shadow: 0 2px 8px rgba(116, 185, 255, 0.2);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #e9ecef, stop:1 #dee2e6);
                border-color: #0984e3;
            }
        """)
        self.run_cwatm_button.clicked.connect(self.run_cwatm)
        run_cwatm_layout.addWidget(self.run_cwatm_button)

        # Warning label to the right of RUN CWatM - shows problems (e.g. gauges not in
        # the mask) in red. Empty when everything is fine.
        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet("QLabel { color: red; font-weight: bold; }")
        run_cwatm_layout.addWidget(self.warning_label, 1)

        # ("Write output to cwatm_out.txt" checkbox removed — now controlled by the
        # Settings > "Write output" menu tick box.)

        # Check Data button (hidden; available via the Tools > Check Data menu)
        self.check_data_button = QPushButton("Check Data")
        self.check_data_button.setMinimumHeight(button_height)
        self.check_data_button.setMinimumWidth(120)
        self.check_data_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #ffffff, stop:1 #f1f3f4);
                border: 2px solid #e1e5e9;
                border-radius: 8px;
                color: #2c3e50;
                font-weight: 600;
                font-size: 13px;
                padding: 8px 16px;
                min-height: 32px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                border-color: #74b9ff;
                box-shadow: 0 2px 8px rgba(116, 185, 255, 0.2);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #e9ecef, stop:1 #dee2e6);
                border-color: #0984e3;
            }
        """)
        self.check_data_button.clicked.connect(self.open_check_data_window)
        self.check_data_button.setVisible(False)  # use Tools > Check Data instead
        
        run_cwatm_layout.addStretch()
        parent_layout.addLayout(run_cwatm_layout)
        parent_layout.addSpacing(2)  # Minimal spacing after run button
        
        # CWatM info area and progress clock layout.
        # Always stack vertically so the progress clock sits *under* the output box.
        screen_width = QApplication.primaryScreen().availableGeometry().width()
        info_progress_layout = QVBoxLayout()
        info_progress_layout.setSpacing(3)  # Ultra-minimal vertical spacing
        info_progress_layout.setContentsMargins(0, 1, 0, 1)  # Ultra-minimal margins
        
        # CWatM info area for DOS screen output (scrollable) - left side
        self.scroll_area = QScrollArea()
        # Make height responsive to screen size (30px taller)
        screen_height = QApplication.primaryScreen().availableGeometry().height()
        min_height = int(max(150, screen_height // 8 + 30) * 1.5)  # 50% more height
        max_height = int(min(330, screen_height // 4 + 30) * 1.5)  # 50% more height
        self.scroll_area.setMinimumHeight(min_height)
        self.scroll_area.setMaximumHeight(max_height)
        # Output box: modest minimum width; the maximum is capped at the right edge of
        # the End Date field in resizeEvent, so the box ends where the calendar fields end.
        self.scroll_area.setMinimumWidth(350)
        # Remove maximum width constraint for flexibility
        self.scroll_area.setSizePolicy(self.scroll_area.sizePolicy().horizontalPolicy(), self.scroll_area.sizePolicy().verticalPolicy())
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        self.cwatminfo_label = QLabel("CWatM output will appear here...")
        self.cwatminfo_label.setWordWrap(True)
        self.cwatminfo_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)  # Aligned to the left
        self.cwatminfo_label.setTextFormat(Qt.RichText)  # Enable rich text formatting
        # Make cwatminfo font size responsive
        screen_height = QApplication.primaryScreen().availableGeometry().height()
        cwatm_font_size = max(9, min(11, screen_height // 80))  # Scale with screen height
        self.cwatminfo_label.setStyleSheet(f"""
            QLabel {{
                background-color: #f5f5f5;
                border: 1px solid #cccccc;
                padding: 0px;
                font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
                font-size: {cwatm_font_size}px;
                color: #333333;
            }}
        """)

        # Let the user select and copy the CWatM output text. Selection enables the
        # native Ctrl+C / right-click "Copy"; the custom context menu adds a
        # "Copy all output" action that works even while the run is still updating
        # (each update resets any active selection).
        self.cwatminfo_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.cwatminfo_label.setCursor(Qt.IBeamCursor)
        self.cwatminfo_label.setContextMenuPolicy(Qt.CustomContextMenu)
        self.cwatminfo_label.customContextMenuRequested.connect(self._show_cwatminfo_menu)

        self.scroll_area.setWidget(self.cwatminfo_label)
        cwatminfo_container = QWidget()
        cwatminfo_container_layout = QHBoxLayout(cwatminfo_container)
        cwatminfo_container_layout.setContentsMargins(0, 0, 0, 0)  # Shift 90px to the left (80+10)
        cwatminfo_container_layout.setSpacing(0)
        cwatminfo_container_layout.addWidget(self.scroll_area)
        cwatminfo_container_layout.addStretch()  # keep the box pinned to the left

        info_progress_layout.addWidget(cwatminfo_container)
        
        # Add extra space before progress clock (reduced by 30 pixels to shift cwatminfo left)
        #info_progress_layout.addSpacing(10)  # Reduced from 30 to 20 pixels (10 more pixels left)
        
        # Progress clock - right side with container for positioning (10px up)
        progress_container = QWidget()
        progress_container_layout = QVBoxLayout(progress_container)
        progress_container_layout.setContentsMargins(0, 0, 0, 0)  # Shift 10px up (negative top margin, compensate bottom)
        progress_container_layout.setSpacing(0)  # No spacing in container
        
        self.progress_clock = ProgressClock()
        self.progress_clock.setValue(0)  # Start at 0%
        # Make progress clock responsive to screen size
        screen_width = QApplication.primaryScreen().availableGeometry().width()
        clock_size = max(120, min(192, screen_width // 8))  # Between 120-192px based on screen width
        self.progress_clock.setFixedSize(clock_size, clock_size)
        
        progress_container_layout.addWidget(self.progress_clock)
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
        input_height = max(30, min(35, screen_height // 25))
        self.pathout_field.setMinimumHeight(input_height)
        self.pathout_field.setMinimumWidth(120)  # Same width as MaskMap field
        self.pathout_field.setStyleSheet("QLineEdit { background-color: #f5f5f5; }")  # Light gray background
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
        input_height = max(30, min(35, screen_height // 25))
        self.maskmap_field.setMinimumHeight(input_height)
        self.maskmap_field.setMinimumWidth(120)  # Same width as PathOut field
        self.maskmap_field.setStyleSheet("QLineEdit { background-color: #f5f5f5; }")  # Light gray background
        self.maskmap_field.textChanged.connect(self.on_field_changed)
        maskmap_layout.addWidget(self.maskmap_field)
        
        # Add minimal spacing before the Show Mask button
        maskmap_layout.addSpacing(5)  # Reduced spacing
        
        # Show Basin button
        self.show_basin_button = QPushButton("Show Basin")
        # Use consistent button sizing
        screen_height = QApplication.primaryScreen().availableGeometry().height()
        button_height = max(35, min(50, screen_height // 20))
        self.show_basin_button.setMinimumHeight(button_height)
        self.show_basin_button.setMinimumWidth(100)  # Slightly smaller for this button
        self.show_basin_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #ffffff, stop:1 #f1f3f4);
                border: 2px solid #e1e5e9;
                border-radius: 8px;
                color: #2c3e50;
                font-weight: 600;
                font-size: 13px;
                padding: 8px 16px;
                min-height: 32px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                border-color: #74b9ff;
                box-shadow: 0 2px 8px rgba(116, 185, 255, 0.2);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #e9ecef, stop:1 #dee2e6);
                border-color: #0984e3;
            }
        """)
        self.show_basin_button.clicked.connect(self.show_basin)
        self.show_basin_button.setVisible(False)  # use Tools > Show Basin instead
        
        # Add spacing between Show Basin and Options buttons
        maskmap_layout.addSpacing(5)
        
        # Options button (now on same line as Show Basin button)
        self.options_button = QPushButton("Options")
        # Use consistent button sizing
        self.options_button.setMinimumHeight(button_height)
        self.options_button.setMinimumWidth(120)
        self.options_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #ffffff, stop:1 #f1f3f4);
                border: 2px solid #e1e5e9;
                border-radius: 8px;
                color: #2c3e50;
                font-weight: 600;
                font-size: 13px;
                padding: 8px 16px;
                min-height: 32px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                border-color: #74b9ff;
                box-shadow: 0 2px 8px rgba(116, 185, 255, 0.2);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #e9ecef, stop:1 #dee2e6);
                border-color: #0984e3;
            }
        """)
        self.options_button.clicked.connect(self.open_options_window)
        self.options_button.setVisible(False)  # use Tools > Change Options instead
        
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
        input_height = max(30, min(35, screen_height // 25))
        self.gauges_field.setMinimumHeight(input_height)
        self.gauges_field.setMinimumWidth(120)
        self.gauges_field.setStyleSheet("QLineEdit { background-color: #f5f5f5; }")
        self.gauges_field.textChanged.connect(self.on_field_changed)
        gauges_layout.addWidget(self.gauges_field)

        gauges_layout.addStretch()
        parent_layout.addLayout(gauges_layout)
        parent_layout.addSpacing(1)

    def _rebuild_mask_cache(self, force=False):
        """(Re)build the in-memory mask used for gauge checks. This is potentially
        expensive for a coordinate-based MaskMap (a basin is generated with CWatM),
        so it is only done when a settings file is loaded (force=True) or the MaskMap
        entry has changed since the last build (on save)."""
        try:
            content = self.original_content or self.text_display.get_content()
        except Exception:
            content = ""
        maskmap = self.maskmap_field.text().strip() if getattr(self, "maskmap_field", None) else ""
        if not force and self._mask_context is not None and maskmap == self._mask_context_key:
            return  # MaskMap unchanged - keep the cached mask
        settings_file = self.file_manager.get_current_file_path()
        self._mask_context = build_mask_context(settings_file, content)
        self._mask_context_key = maskmap
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
        try:
            settings_file = self.file_manager.get_current_file_path()
            content = self.original_content or self.text_display.get_content()
        except Exception:
            settings_file, content = None, ""

        # --- Gauges inside the mask map (uses the cached in-memory mask) ---
        try:
            gres = gauges_inside(self._mask_context, content)
        except Exception:
            gres = None
        base = "QLineEdit { background-color: #f5f5f5;"
        gauge_warning = ""
        if gres is True:
            self.gauges_field.setStyleSheet(base + " color: blue; }")
        elif gres is False:
            self.gauges_field.setStyleSheet(base + " color: red; }")
            gauge_warning = "Gauge is not inside the basin! Change manually or use Tools/Set Gauge."
        else:
            self.gauges_field.setStyleSheet(base + " }")

        # --- PathOut folder exists (only on load/save) ---
        if check_pathout:
            try:
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

    def create_pathout_folder(self):
        """Create the PathOut folder (placeholders resolved) if it does not exist."""
        if not self.file_manager.has_file_loaded():
            self.status_bar.showMessage("No file loaded")
            return
        try:
            content = self.original_content or self.text_display.get_content()
        except Exception:
            content = ""

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
        """Append 'OUT_TSS_AreaSum_Daily = WaterCycle' as the last line of the settings
        file (in memory, not saved), unless a WaterCycle entry already exists."""
        if not self.file_manager.has_file_loaded():
            self.status_bar.showMessage("No file loaded")
            return
        line_to_add = "OUT_TSS_AreaSum_Daily = WaterCycle"
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
            if key.strip().lower() == 'out_tss_areasum_daily' and \
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

    def _default_output_file(self):
        """Default output-box file: <PathOut>/cwatm_out.txt (placeholders resolved).
        Falls back to the settings-file directory if PathOut cannot be resolved."""
        try:
            content = self.original_content or self.text_display.get_content()
        except Exception:
            content = ""
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

    def _update_output_tooltip(self):
        """Set the 'Write output' menu item tooltip to the current effective output
        file path (custom or default <PathOut>/cwatm_out.txt)."""
        try:
            path = self._output_file()
        except Exception:
            path = ""
        tip = f"Output box file: {path}"
        if self._output_file_override:
            tip += "  (custom)"
        self.write_output_action.setToolTip(tip)

    def set_output_box_file(self):
        """Let the user pick a custom output-box file (location + name), kept in
        memory. The default shown is <PathOut>/cwatm_out.txt."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Set output box file", self._output_file(),
            "Text files (*.txt);;All files (*)")
        if path:
            self._output_file_override = path
            self.status_bar.showMessage(f"Output box file set to: {path}")
        
    def create_right_panel(self, parent_layout):
        """Create right panel with text display"""
        right_panel = QWidget()
        right_panel.setStyleSheet("""
            QWidget {
                background-color: #ffffff;
                border-radius: 12px;
                margin: 8px;
                padding: 15px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.08);
            }
        """)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setSpacing(12)
        right_layout.setContentsMargins(15, 15, 15, 15)
        
        # Save controls with modern styling
        save_controls = QHBoxLayout()
        save_controls.setSpacing(8)
        
        # Modern button style template
        modern_button_style = """
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #ffffff, stop:1 #f1f3f4);
                border: 2px solid #e1e5e9;
                border-radius: 8px;
                color: #2c3e50;
                font-weight: 600;
                font-size: 13px;
                padding: 8px 16px;
                min-height: 32px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                border-color: #74b9ff;
                box-shadow: 0 2px 8px rgba(116, 185, 255, 0.2);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #e9ecef, stop:1 #dee2e6);
                border-color: #0984e3;
            }
        """
        
        # Style applied to Save / Save As when there are unsaved changes (blue)
        self._modern_button_style = modern_button_style
        self._save_dirty_style = """
            QPushButton {
                background-color: #add8e6;
                border: 2px solid #87ceeb;
                border-radius: 8px;
                color: #2c3e50;
                font-weight: 600;
                font-size: 13px;
                padding: 8px 16px;
                min-height: 32px;
            }
            QPushButton:hover { background-color: #87ceeb; border-color: #6bb6ff; }
            QPushButton:pressed { background-color: #6bb6ff; border-color: #4fa8e8; }
        """

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
        
        
        save_controls.addStretch()
        right_layout.addLayout(save_controls)
        
        # Text area with modern styling
        self.text_area = QTextEdit()
        self.text_area.setPlaceholderText("Configuration content will appear here...")
        self.text_area.setReadOnly(False)
        # Colour Save / Save As blue when the document has unsaved edits
        self.text_area.document().modificationChanged.connect(self._on_doc_modified)
        self.text_area.setStyleSheet("""
            QTextEdit {
                background-color: #ffffff;
                border: 2px solid #e1e5e9;
                border-radius: 12px;
                padding: 16px;
                font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', 'Consolas', monospace;
                font-size: 13px;
                line-height: 1.5;
                color: #2c3e50;
                selection-background-color: #74b9ff;
                selection-color: white;
                box-shadow: 0 4px 12px rgba(0,0,0,0.05);
            }
            QTextEdit:focus {
                border-color: #74b9ff;
                box-shadow: 0 0 0 3px rgba(116, 185, 255, 0.1);
            }
            QScrollBar:vertical {
                background-color: #f8f9fa;
                width: 12px;
                border-radius: 6px;
                margin: 2px;
            }
            QScrollBar::handle:vertical {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #74b9ff, stop:1 #0984e3);
                border-radius: 6px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #81c3ff, stop:1 #0d7bd6);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
            }
            QScrollBar:horizontal {
                background-color: #f8f9fa;
                height: 12px;
                border-radius: 6px;
                margin: 2px;
            }
            QScrollBar::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #74b9ff, stop:1 #0984e3);
                border-radius: 6px;
                min-width: 30px;
            }
            QScrollBar::handle:horizontal:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #81c3ff, stop:1 #0d7bd6);
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                border: none;
                background: none;
            }
        """)
        right_layout.addWidget(self.text_area)
        
        # Initialize text display manager
        self.text_display = TextDisplayManager(self.text_area)
        
        # Enable mouse interaction for links
        self.text_area.viewport().installEventFilter(self)
        self.text_area.setMouseTracking(True)
        
        parent_layout.addWidget(right_panel, 1)
        
    def setup_status_bar(self):
        """Setup status bar"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
    
    def create_menu_bar(self, parent_layout):
        """Create menu bar with Info menu, placed below the banner.

        Built as a QMenuBar *widget* added to the layout (rather than the native
        QMainWindow menu bar, which is always pinned to the very top of the window).
        """
        menu_bar = QMenuBar()
        menu_bar.setNativeMenuBar(False)  # keep it in the layout (incl. macOS)

        # File menu (left of Info) — same actions as the Load/Save/Save As buttons.
        # Wrapped in lambdas so the QAction.triggered "checked" bool is not passed
        # as an argument (save_file takes an optional 'new' flag).
        file_menu = menu_bar.addMenu("File")
        load_action = file_menu.addAction("Load .ini")
        load_action.setShortcut("Ctrl+O")
        load_action.triggered.connect(lambda: self.load_file())
        reload_action = file_menu.addAction("Reload")
        reload_action.setShortcut("Ctrl+L")
        reload_action.triggered.connect(lambda: self.reload_file())
        save_action = file_menu.addAction("Save .ini")
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(lambda: self.save_file())
        save_as_action = file_menu.addAction("Save As")
        save_as_action.setShortcut("Ctrl+Alt+S")
        save_as_action.triggered.connect(lambda: self.save_as_file())
        file_menu.addSeparator()
        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(lambda: self.close())

        # Settings menu (right of File) — same actions as the editor toolbar buttons
        settings_menu = menu_bar.addMenu("Settings")
        compress_action = settings_menu.addAction("Fold All")
        compress_action.setShortcut("Alt+0")
        compress_action.triggered.connect(lambda: self.compress_all_sections())
        expand_action = settings_menu.addAction("Unfold All")
        expand_action.setShortcut("Alt+Shift+0")
        # Pass False so it actually unfolds (the no-arg default notexpand=True does not)
        expand_action.triggered.connect(lambda: self.expand_all_sections(False))
        top_action = settings_menu.addAction("Top")
        top_action.setShortcut("Alt+T")
        top_action.triggered.connect(lambda: self.jump_to_top())
        down_action = settings_menu.addAction("Down")
        down_action.setShortcut("Alt+D")
        down_action.triggered.connect(lambda: self.jump_to_bottom())
        settings_menu.addSeparator()
        find_action = settings_menu.addAction("Find")
        find_action.setShortcut("F5")
        find_action.triggered.connect(lambda: self.find_text())
        find_next_action = settings_menu.addAction("Find next")
        find_next_action.setShortcut("Ctrl+F")
        find_next_action.triggered.connect(lambda: self.find_next())
        settings_menu.addSeparator()
        undo_action = settings_menu.addAction("Undo")
        undo_action.setShortcut("Ctrl+Z")
        undo_action.triggered.connect(lambda: self.text_area.undo())
        redo_action = settings_menu.addAction("Redo")
        redo_action.setShortcut("Ctrl+Y")
        redo_action.triggered.connect(lambda: self.text_area.redo())

        # Tools menu (right of File) — same actions as the side buttons
        tools_menu = menu_bar.addMenu("Tools")
        tools_menu.setToolTipsVisible(True)
        options_action = tools_menu.addAction("Change Options")
        options_action.setToolTip("Display a popup with the settingsfile [Options]")
        options_action.triggered.connect(lambda: self.open_options_window())
        basin_action = tools_menu.addAction("Show Basin")
        basin_action.triggered.connect(lambda: self.show_basin())
        set_gauge_action = tools_menu.addAction("Set Gauge")
        set_gauge_action.setToolTip("Find the point with the largest upstream area in Mask Map")
        set_gauge_action.triggered.connect(lambda: self.set_gauge())
        tools_menu.addSeparator()
        watercycle_action = tools_menu.addAction("Add output Watercycle")
        watercycle_action.setToolTip("Adds an additional output for creating watercycles")
        watercycle_action.triggered.connect(lambda: self.add_output_watercycle())
        check_action = tools_menu.addAction("Check Data")
        check_action.triggered.connect(lambda: self.open_check_data_window())
        tools_menu.addSeparator()
        create_pathout_action = tools_menu.addAction("Create PathOut Folder")
        create_pathout_action.triggered.connect(lambda: self.create_pathout_folder())

        # RUN CWATM menu (right of Tools). Actualize was removed: field changes are
        # auto-applied to the content, and Save/Run flush any pending change first.
        run_menu = menu_bar.addMenu("RUN CWATM")
        run_action = run_menu.addAction("Run CWATM")
        run_action.setShortcut("Ctrl+R")
        run_action.triggered.connect(lambda: self.run_cwatm())

        # Configure menu (right of RUN CWATM). "Write output to cwatm_out.txt" is a
        # checkable tick box; run_cwatm reads self.write_output_action.isChecked().
        configure_menu = menu_bar.addMenu("Configure")
        configure_menu.setToolTipsVisible(True)  # show action tooltips in the menu
        set_output_action = configure_menu.addAction("Set output box file")
        set_output_action.triggered.connect(lambda: self.set_output_box_file())
        self.write_output_action = configure_menu.addAction("Write output box")
        self.write_output_action.setCheckable(True)
        self.write_output_action.setChecked(False)
        # Refresh the tooltip with the current effective output path when opened
        configure_menu.aboutToShow.connect(self._update_output_tooltip)

        # Create Info menu and place it on the right side
        info_menu = menu_bar.addMenu("Info")

        # Add action for showing info dialog
        info_action = info_menu.addAction("About CWatM")
        info_action.triggered.connect(self.show_info_dialog)

        # Style the menu bar to align Info to the right
        menu_bar.setStyleSheet("""
            QMenuBar {
                background-color: #f8f9fa;
                border-bottom: 1px solid #e1e5e9;
                padding: 4px;
            }
            QMenuBar::item {
                background-color: transparent;
                padding: 4px 8px;
                border-radius: 3px;
            }
            QMenuBar::item:selected {
                background-color: #0066CC;
                color: white;
            }
        """)

        # Insert just below the banner (index 0 = header) regardless of when this
        # is called relative to the content layout.
        parent_layout.insertWidget(1, menu_bar)

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
        title_label.setStyleSheet("""
            QLabel {
                font-family: 'Segoe UI', sans-serif;
                font-weight: 700;
                font-size: 18px;
                color: #0066CC;
                padding: 15px 0px 10px 0px;
                text-align: center;
            }
        """)
        title_label.setAlignment(Qt.AlignCenter)
        
        # Scrollable area for content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: 1px solid #e1e5e9;
                border-radius: 6px;
                background-color: white;
            }
            QScrollBar:vertical {
                background-color: #f8f9fa;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #0066CC;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #0055AA;
            }
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
        info_text.setStyleSheet("""
            QLabel {
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                color: #2c3e50;
                line-height: 1.4;
                margin-bottom: 20px;
            }
        """)
        info_text.setWordWrap(True)
        info_text.setAlignment(Qt.AlignJustify)
        
        # Version header
        version_header = QLabel("CWatM Version")
        version_header.setStyleSheet("""
            QLabel {
                font-family: 'Segoe UI', sans-serif;
                font-weight: 700;
                font-size: 14px;
                color: #0066CC;
                margin-top: 10px;
                margin-bottom: 10px;
            }
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
        version_info_label.setStyleSheet("""
            QLabel {
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 11px;
                color: #2c3e50;
                background-color: #f8f9fa;
                padding: 10px;
                border: 1px solid #e1e5e9;
                border-radius: 4px;
                line-height: 1.4;
            }
        """)
        version_info_label.setWordWrap(True)
        version_info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        
        # Add content to scroll area
        content_layout.addWidget(info_text)
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
        self.collapsed_sections.clear()
        # parse_file(load=True) re-reads the current file path from disk and re-renders
        self.parse_file(load=True, show_status=True)
        self._mark_clean()
        self.status_bar.showMessage(f"Reloaded: {self.file_manager.get_current_file_path()}")

    def load_file(self):
        """Handle file loading"""
        content, filename = self.file_manager.load_file()
        
        if content is not None:
            self.text_display.set_plain_content(content)
            self.file_parsed = False  # Reset parsed flag when loading new file
            if filename.startswith("Error:"):
                self.filename_label.setText(filename)
                self.filename_label.setStyleSheet("color: red; font-weight: bold;")
                self.status_bar.showMessage(filename)
            else:
                self.filename_label.setText(f"Loaded: {filename}")
                self.filename_label.setStyleSheet("color: green; font-weight: bold;")
                self.status_bar.showMessage(f"Loaded: {self.file_manager.get_current_file_path()}")
                
                # Automatically parse the file after loading
                self.parse_file(load = True, show_status=True)

                # Freshly loaded file has no unsaved changes
                self._mark_clean()

                # Build the in-memory mask, then check gauges / PathOut
                self._rebuild_mask_cache(force=True)
                self._update_warnings()

                # Color buttons after successful file load
                # Options button - #add8e6 color
                self.options_button.setStyleSheet("""
                    QPushButton {
                        background-color: #add8e6;
                        border: 2px solid #87ceeb;
                        border-radius: 8px;
                        color: #2c3e50;
                        font-weight: 600;
                        font-size: 13px;
                        padding: 8px 16px;
                        min-height: 32px;
                    }
                    QPushButton:hover {
                        background-color: #87ceeb;
                        border-color: #6bb6ff;
                    }
                    QPushButton:pressed {
                        background-color: #6bb6ff;
                        border-color: #4fa8e8;
                    }
                """)
                
                # Show Basin button - light blue color after successful load
                self.set_show_basin_button_active(True)
                
                # Check Data button - same light blue color as Show Basin
                self.check_data_button.setStyleSheet("""
                    QPushButton {
                        background-color: #add8e6;
                        border: 2px solid #87ceeb;
                        border-radius: 8px;
                        color: #2c3e50;
                        font-weight: 600;
                        font-size: 13px;
                        padding: 8px 16px;
                        min-height: 32px;
                    }
                    QPushButton:hover {
                        background-color: #87ceeb;
                        border-color: #6bb6ff;
                        box-shadow: 0 2px 8px rgba(116, 185, 255, 0.2);
                    }
                    QPushButton:pressed {
                        background-color: #6bb6ff;
                        border-color: #4fa8e8;
                    }
                """)
                
                # RUN CWatM button - same blue as title
                self.run_cwatm_button.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                            stop:0 #2980b9, stop:1 #3498db);
                        border: 2px solid #3498db;
                        border-radius: 8px;
                        color: white;
                        font-weight: 600;
                        font-size: 13px;
                        padding: 8px 16px;
                        min-height: 32px;
                        box-shadow: 0 2px 8px rgba(52, 152, 219, 0.3);
                    }
                    QPushButton:hover {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                            stop:0 #3498db, stop:1 #5dade2);
                        border-color: #5dade2;
                        box-shadow: 0 4px 12px rgba(52, 152, 219, 0.4);
                    }
                    QPushButton:pressed {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                            stop:0 #2471a3, stop:1 #2980b9);
                        border-color: #2471a3;
                        box-shadow: 0 1px 4px rgba(52, 152, 219, 0.3);
                    }
                """)
                
                # Reset actualize button to default modern styling (same as Save buttons)
                self.actualize_button.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                            stop:0 #ffffff, stop:1 #f1f3f4);
                        border: 2px solid #e1e5e9;
                        border-radius: 8px;
                        color: #2c3e50;
                        font-weight: 600;
                        font-size: 13px;
                        padding: 8px 16px;
                        min-height: 32px;
                    }
                    QPushButton:hover {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                            stop:0 #f8f9fa, stop:1 #e9ecef);
                        border-color: #74b9ff;
                        box-shadow: 0 2px 8px rgba(116, 185, 255, 0.2);
                    }
                    QPushButton:pressed {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                            stop:0 #e9ecef, stop:1 #dee2e6);
                        border-color: #0984e3;
                    }
                """)
        
    def parse_file(self, target_line=None, expand_all=True, show_status=False,load=False,content=""):
        """Handle file parsing"""
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


                
            # Store original content for compress functionality
            self.original_content = content
            
            # Set original content in text display manager
            self.text_display.set_original_content(content)
            
            # Expand everything at the beginning of parsing only if expand_all is True
            if expand_all:
                self.collapsed_sections.clear()
            
            # Parse and format content with expand/collapse functionality
            date_values, settings_values = self.config_parser.parse_content(content)
            
            # Create expandable/collapsible view (all sections expanded by default)
            formatted_lines = []
            lines = content.split('\n')
            current_section = None
            section_content = []
            
            for line in lines:
                line_stripped = line.strip()
                
                if line_stripped.startswith('[') and line_stripped.endswith(']'):
                    # Process previous section if exists
                    if current_section:
                        self._add_section_to_view(formatted_lines, current_section, section_content)
                    
                    # Start new section
                    current_section = line_stripped
                    section_content = []
                else:
                    # Add line to current section content
                    if current_section:
                        section_content.append(line)
                    else:
                        # Lines before any section
                        formatted_lines.append(self._format_line(line))
            
            # Add last section
            if current_section:
                self._add_section_to_view(formatted_lines, current_section, section_content)
            
            # Display formatted content
            self.text_display.display_formatted_content(formatted_lines)
            
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
                collapsed_count = len(self.collapsed_sections)
                if collapsed_count > 0:
                    self.status_bar.showMessage(f"Configuration file parsed - {collapsed_count}")
                else:
                    self.status_bar.showMessage("Configuration file parsed")
            
            # Set parsed flag to True on successful parsing
            self.file_parsed = True
            
            # Reset Actualize button to default modern styling after parsing
            self.actualize_button.setStyleSheet("""
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 #ffffff, stop:1 #f1f3f4);
                    border: 2px solid #e1e5e9;
                    border-radius: 8px;
                    color: #2c3e50;
                    font-weight: 600;
                    font-size: 13px;
                    padding: 8px 16px;
                    min-height: 32px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 #f8f9fa, stop:1 #e9ecef);
                    border-color: #74b9ff;
                    box-shadow: 0 2px 8px rgba(116, 185, 255, 0.2);
                }
                QPushButton:pressed {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 #e9ecef, stop:1 #dee2e6);
                    border-color: #0984e3;
                }
            """)
            
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

    def _set_save_dirty(self, dirty):
        """Colour the Save / Save As buttons blue when there are unsaved changes."""
        self._is_dirty = bool(dirty)
        if getattr(self, "save_button", None) is None:
            return
        style = self._save_dirty_style if dirty else self._modern_button_style
        self.save_button.setStyleSheet(style)
        self.save_as_button.setStyleSheet(style)

    def _on_doc_modified(self, changed):
        """Editor document modification state changed (ignored during programmatic
        re-renders, which set self._suppress_dirty)."""
        if self._suppress_dirty:
            return
        self._set_save_dirty(changed)

    def _mark_clean(self):
        """Mark the document/state as saved (no unsaved changes)."""
        if getattr(self, "text_area", None) is not None:
            self.text_area.document().setModified(False)
        self._set_save_dirty(False)

    def on_field_changed(self):
        """Handle when dates, pathout, or maskmap fields change"""
        if self._suppress_dirty:
            return  # programmatic update during parse/load, not a user change
        # Mark unsaved changes on the Save / Save As buttons
        self._set_save_dirty(True)
        # Auto-apply the change into the in-memory settings content (debounced)
        self._field_update_timer.start()
        if hasattr(self, 'actualize_button') and self.actualize_button:
            # Color actualize button with #add8e6 when fields change
            self.actualize_button.setStyleSheet("""
                QPushButton {
                    background-color: #add8e6;
                    border: 2px solid #87ceeb;
                    border-radius: 8px;
                    color: #2c3e50;
                    font-weight: 600;
                    font-size: 13px;
                    padding: 8px 16px;
                    min-height: 32px;
                }
                QPushButton:hover {
                    background-color: #87ceeb;
                    border-color: #6bb6ff;
                }
                QPushButton:pressed {
                    background-color: #6bb6ff;
                    border-color: #4fa8e8;
                }
            """)
    
    def run_configuration(self):
        """Handle configuration run"""
        # Close open windows
        self.close_subsidiary_windows()
        
        if not self.file_manager.has_file_loaded():
            self.status_bar.showMessage("No file loaded - please load a configuration file first")
            return
            
        try:
            # Get current dates
            start_date, spin_date, end_date = self.date_manager.get_current_dates()
            if not all([start_date, spin_date, end_date]):
                self.status_bar.showMessage("Error getting date values")
                return
                
            # Check if dates have changed
            content = self.text_display.get_content()
            current_config_dates = self.config_parser.get_current_date_values(content)
            
            # Check if settings have changed
            current_config_settings = self.config_parser.get_current_settings_values(content)
            current_pathout = self.pathout_field.text().strip()
            current_maskmap = self.maskmap_field.text().strip()
            current_gauges = self.gauges_field.text().strip()

            dates_changed = self.date_manager.dates_changed_from_config(current_config_dates)
            settings_changed = (current_config_settings.get('pathout', '') != current_pathout or
                              current_config_settings.get('maskmap', '') != current_maskmap or
                              current_config_settings.get('gauges', '') != current_gauges)
            
            if dates_changed or settings_changed:
                # Expand everything before saving
                self.collapsed_sections.clear()
                
                # Start with original content (without [-]/[+] indicators)
                updated_content = self.original_content
                
                # Update dates if they changed
                if dates_changed:
                    updated_content = self.config_parser.update_dates(updated_content, start_date, spin_date, end_date)
                
                # Update settings if they changed  
                if settings_changed:
                    settings_dict = {}
                    if current_config_settings.get('pathout', '') != current_pathout:
                        settings_dict['pathout'] = current_pathout
                    if current_config_settings.get('maskmap', '') != current_maskmap:
                        settings_dict['maskmap'] = current_maskmap
                    if current_config_settings.get('gauges', '') != current_gauges:
                        settings_dict['gauges'] = current_gauges
                    updated_content = self.config_parser.update_settings(updated_content, settings_dict)
                
                # Save file with clean content
                success, message = self.file_manager.save_file(updated_content)
                if not success:
                    self.status_bar.showMessage(message)
                    return
                
                # Find StepStart line and parse from 10 lines before it
                stepstart_line = self.config_parser.find_parameter_line(updated_content, "stepstart")
                target_line = max(0, stepstart_line - 10) if stepstart_line >= 0 else 0
                
                # Re-parse with target position
                self.parse_file(target_line,load = True)
                
                # Build status message
                messages = []
                if dates_changed:
                    messages.append(f"StepStart={start_date.toString('dd/MM/yyyy')}, SpinUp={spin_date.toString('dd/MM/yyyy')}, StepEnd={end_date.toString('dd/MM/yyyy')}")
                if settings_changed:
                    settings_msgs = []
                    if current_config_settings.get('pathout', '') != current_pathout:
                        settings_msgs.append(f"PathOut={current_pathout}")
                    if current_config_settings.get('maskmap', '') != current_maskmap:
                        settings_msgs.append(f"MaskMap={current_maskmap}")
                    messages.append(", ".join(settings_msgs))
                
                self.status_bar.showMessage(f"Configuration updated and saved: {'; '.join(messages)}")
                
                # Reset actualize button to default modern styling after successful use
                self.actualize_button.setStyleSheet("""
                    QPushButton {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                            stop:0 #ffffff, stop:1 #f1f3f4);
                        border: 2px solid #e1e5e9;
                        border-radius: 8px;
                        color: #2c3e50;
                        font-weight: 600;
                        font-size: 13px;
                        padding: 8px 16px;
                        min-height: 32px;
                    }
                    QPushButton:hover {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                            stop:0 #f8f9fa, stop:1 #e9ecef);
                        border-color: #74b9ff;
                        box-shadow: 0 2px 8px rgba(116, 185, 255, 0.2);
                    }
                    QPushButton:pressed {
                        background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                            stop:0 #e9ecef, stop:1 #dee2e6);
                        border-color: #0984e3;
                    }
                """)
            else:
                self.status_bar.showMessage("No changes detected - file not modified")
                
        except Exception as e:
            # Print error to stderr so it appears in dark red in cwatminfo
            import sys
            print(f"Error updating configuration: {str(e)}", file=sys.stderr)
            self.status_bar.showMessage(f"Error updating configuration: {str(e)}")

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

            updated_content = self.original_content
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
    
    def run_cwatm(self):
        """Handle CWatM button click - run or stop CWatM model"""
        if self.cwatm_running:
            # If CWatM is running, stop it
            self.stop_cwatm_execution()
            return
            
        # Close open windows before starting CWatM
        self.close_subsidiary_windows()
            
        # If not running, start CWatM
        if not self.file_manager.has_file_loaded():
            self.status_bar.showMessage("No settings file loaded")
            return

        # Apply any pending (debounced) field changes before running
        self._flush_pending_field_changes()

        # Get current file path and name
        file_path = self.file_manager.get_current_file_path()
        
        if not file_path:
            self.status_bar.showMessage("No settings file information available")
            print("No settings file available for CWatM execution")
            return
            
        # Clear previous output first
        self.cwatm_output_buffer.clear()
        self.cwatminfo_label.setText("CWatM output will appear here...")
        
        # Setup output file if the Configure > "Write output" menu item is ticked.
        # Location is the custom file (Configure > Set output box file) or the default
        # <PathOut>/cwatm_out.txt.
        if self.write_output_action.isChecked():
            self.output_file_path = self._output_file()
            # Make sure the target folder exists
            try:
                os.makedirs(os.path.dirname(self.output_file_path), exist_ok=True)
            except Exception:
                pass
            # Append a header block to the output file (do not overwrite previous runs
            # and do not show these lines in the output box).
            try:
                with open(self.output_file_path, 'a', encoding='utf-8') as f:
                    f.write("=================================\n")
                    f.write(time.strftime('%Y-%m-%d %H:%M:%S') + "\n")
                    f.write("---------------------------------\n")
                print(f"Writing output to file: {self.output_file_path}")
            except Exception as e:
                print(f"Error creating output file: {e}")
                self.output_file_path = None
        else:
            self.output_file_path = None
        
        # Reset progress clock to 0
        self.progress_clock.setValue(0)
        QApplication.processEvents()
        
        
        print(f"Starting CWatM with settings file: {file_path}")
        self.status_bar.showMessage(f"Settings file: {file_path} - Starting run")
        
        # Set running state
        self.cwatm_running = True
        self.set_cwatm_button_running_state()
        
        # Disable Show Basin button during CWatM execution
        self.show_basin_button.setEnabled(False)
        
        QApplication.processEvents()
        
        # Create and start worker thread
        self.cwatm_worker = CWatMWorker(file_path, ['-lg'], self)
        self.cwatm_worker.finished.connect(self.on_cwatm_finished)
        self.cwatm_worker.error.connect(self.on_cwatm_error)
        self.cwatm_worker.progress.connect(self.on_cwatm_progress)
        self.cwatm_worker.start()
    
    def on_cwatm_progress(self, value):
        """Handle CWatM execution progress updates"""
        self.progress_clock.setValue(value)
        QApplication.processEvents()
    
    def show_basin(self):
        """Show basin visualization window"""
        try:
            if self.file_manager.current_file_path:
                from src.gui.widgets.basin_viewer import BasinViewer
                basin_viewer = BasinViewer(self.file_manager.current_file_content)
                basin_viewer.show_basin(self.file_manager.current_file_path, parent=self)
            else:
                print("No configuration file loaded", file=sys.stderr)
        except Exception as e:
            print(f"Error opening basin viewer: {str(e)}", file=sys.stderr)
    
    def open_check_data_window(self):
        """Open check data validation window"""
        try:
            if self.file_manager.current_file_path:
                from src.gui.widgets.check_data_window import CheckDataWindow
                check_window = CheckDataWindow(parent=self, config_content=self.file_manager.current_file_content)
                check_window.exec()
            else:
                print("No configuration file loaded", file=sys.stderr)
        except Exception as e:
            print(f"Error opening check data window: {str(e)}", file=sys.stderr)
    
    def _finalize_output_file(self):
        """Append a trailing blank line to the output-box file after a run's content.
        Not shown in the output box."""
        if self.output_file_path:
            try:
                with open(self.output_file_path, 'a', encoding='utf-8') as f:
                    f.write("\n")
            except Exception:
                pass

    def on_cwatm_finished(self, success, last_dis):
        """Handle CWatM execution completion"""
        if success:
            # Format last discharge to 2 decimal places
            try:
                last_dis_formatted = f"{float(last_dis):.2f}" if last_dis is not None else "N/A"
            except (ValueError, TypeError):
                last_dis_formatted = str(last_dis) if last_dis is not None else "N/A"

            print(f"CWatM completed successfully.")
            self.status_bar.showMessage(f"CWatM success: {success}  last discharge: {last_dis_formatted}")
        else:
            print("CWatM execution failed")
            self.status_bar.showMessage("CWatM execution failed")

        # Trailing blank line in the output file after the run's content
        self._finalize_output_file()

        # Reset state but keep progress clock value
        self.cwatm_running = False
        self.cwatm_worker = None
        # Don't reset progress clock - keep final completion percentage
        self.set_cwatm_button_ready_state()
        
        # Re-enable Show Basin button after CWatM execution completes
        self.show_basin_button.setEnabled(True)
    
    def on_cwatm_error(self, error_message):
        """Handle CWatM execution error"""
        print(f"CWatM execution error: {error_message}", file=sys.stderr)
        self.status_bar.showMessage(f"CWatM execution error: {error_message}")

        # Trailing blank line in the output file after the run's content
        self._finalize_output_file()

        # Clean up file operations after error
        self.cleanup_file_operations()
        
        # Reset state but keep progress clock value
        self.cwatm_running = False
        self.cwatm_worker = None
        # Don't reset progress clock - keep progress where error occurred
        self.set_cwatm_button_ready_state()
        
        # Re-enable Show Basin button after CWatM error
        self.show_basin_button.setEnabled(True)
    
    def set_cwatm_button_running_state(self):
        """Set RUN CWatM button to running state (light red)"""
        self.run_cwatm_button.setText("STOP CWatM")
        self.run_cwatm_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #e74c3c, stop:1 #c0392b);
                border: 2px solid #c0392b;
                border-radius: 8px;
                color: white;
                font-weight: 600;
                font-size: 13px;
                padding: 8px 16px;
                min-height: 32px;
                box-shadow: 0 2px 8px rgba(231, 76, 60, 0.3);
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #ec7063, stop:1 #a93226);
                border-color: #a93226;
                box-shadow: 0 4px 12px rgba(231, 76, 60, 0.4);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #c0392b, stop:1 #922b21);
                border-color: #922b21;
                box-shadow: 0 1px 4px rgba(231, 76, 60, 0.3);
            }
        """)
        
    def set_cwatm_button_ready_state(self):
        """Set RUN CWatM button to ready state (blue)"""
        self.run_cwatm_button.setText("RUN CWatM")
        self.run_cwatm_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #2980b9, stop:1 #3498db);
                border: 2px solid #3498db;
                border-radius: 8px;
                color: white;
                font-weight: 600;
                font-size: 13px;
                padding: 8px 16px;
                min-height: 32px;
                box-shadow: 0 2px 8px rgba(52, 152, 219, 0.3);
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #3498db, stop:1 #5dade2);
                border-color: #5dade2;
                box-shadow: 0 4px 12px rgba(52, 152, 219, 0.4);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #2471a3, stop:1 #2980b9);
                border-color: #2471a3;
                box-shadow: 0 1px 4px rgba(52, 152, 219, 0.3);
            }
            QPushButton:disabled {
                background: #bdc3c7;
                color: #7f8c8d;
                border: 2px solid #95a5a6;
                box-shadow: none;
            }
        """)
        
    def stop_cwatm_execution(self):
        """Stop CWatM execution and clean up file operations"""
        if self.cwatm_running and self.cwatm_worker:
            try:
                # Request worker thread to stop
                self.cwatm_worker.stop()
                print("CWatM execution stop requested by user", file=sys.stderr)
                self.status_bar.showMessage("Stopping CWatM execution...")
                
                # Clean up file operations immediately
                self.cleanup_file_operations()
                
                # Disconnect signals to prevent issues during termination
                try:
                    self.cwatm_worker.finished.disconnect()
                    self.cwatm_worker.error.disconnect() 
                    self.cwatm_worker.progress.disconnect()
                except Exception:
                    pass  # Ignore if already disconnected
                
                # Wait a longer time for graceful stop
                if self.cwatm_worker.wait(5000):  # Wait up to 5 seconds
                    print("CWatM execution stopped gracefully", file=sys.stderr)
                else:
                    # Force terminate if not stopped gracefully
                    print("Forcing CWatM thread termination...", file=sys.stderr)
                    self.cwatm_worker.terminate()
                    
                    # Wait for termination to complete
                    if self.cwatm_worker.wait(2000):  # Wait 2 more seconds after terminate
                        print("CWatM execution terminated", file=sys.stderr)
                    else:
                        print("CWatM thread termination timed out", file=sys.stderr)
                    
                    # Additional cleanup after force termination
                    self.cleanup_file_operations()
                    
                self.status_bar.showMessage("CWatM execution stopped by user")
            except Exception as e:
                print(f"Error stopping CWatM: {str(e)}", file=sys.stderr)
                self.status_bar.showMessage(f"Error stopping CWatM: {str(e)}")
        
        # Reset state but keep progress clock value
        self.cwatm_running = False
        
        # Clear the worker reference safely
        if self.cwatm_worker:
            self.cwatm_worker.deleteLater()
            self.cwatm_worker = None
            
        # Don't reset progress clock - keep progress where execution was stopped
        self.set_cwatm_button_ready_state()
        
        # Re-enable Show Basin button after CWatM execution is stopped
        self.show_basin_button.setEnabled(True)

    
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
            
            # Then restore scroll position
            if 'scroll_value' in position_data:
                scroll_bar = self.text_area.verticalScrollBar()
                QApplication.processEvents()  # Ensure text is rendered
                scroll_bar.setValue(position_data['scroll_value'])

    def cleanup_file_operations(self):
        """Clean up all open file operations including netCDF files"""
        try:
            print("Cleaning up file operations...", file=sys.stderr)
            
            # 1. Close all netCDF files
            self._cleanup_netcdf_files()
            
            # 2. Close any other file handles
            self._cleanup_general_files()
            
            # 3. Force garbage collection to clean up unreferenced objects
            gc.collect()
            
            print("File cleanup completed", file=sys.stderr)
            
        except Exception as e:
            print(f"Error during file cleanup: {str(e)}", file=sys.stderr)
    
    def _cleanup_netcdf_files(self):
        """Specifically clean up netCDF4 files"""
        try:
            import netCDF4
            
            # Get all netCDF4 Dataset objects and close them
            for obj in gc.get_objects():
                if isinstance(obj, netCDF4.Dataset):
                    try:
                        if not obj._isopen:
                            continue
                        obj.close()
                    except Exception as e:
                        print(f"Error closing netCDF file: {str(e)}", file=sys.stderr)
                        
        except ImportError:
            # netCDF4 not available
            pass
        except Exception as e:
            print(f"Error in netCDF cleanup: {str(e)}", file=sys.stderr)
    
    def _cleanup_general_files(self):
        """Clean up general file handles"""
        try:
            import io
            
            # Close any open file objects
            for obj in gc.get_objects():
                if isinstance(obj, (io.IOBase, io.TextIOBase, io.BufferedIOBase, io.RawIOBase)):
                    try:
                        if not obj.closed:
                            obj.close()
                    except Exception as e:
                        print(f"Error closing file handle: {str(e)}", file=sys.stderr)
                        
        except Exception as e:
            print(f"Error in general file cleanup: {str(e)}", file=sys.stderr)
    

        except Exception as e:
            print(f"Error storing temporary content: {str(e)}", file=sys.stderr)

    def generate_clean_settings_content(self, current_content):
        """Generate clean settings file content without [-]/[+] indicators"""
        try:
            # Get the current content from text display manager
            # current_content = self.text_display.get_content()

            # Process the content line by line to remove [-]/[+] indicators
            lines = current_content.split('\n')
            clean_lines = []

            for line in lines:
                # Skip empty lines that are just whitespace
                if not line.strip():
                    clean_lines.append(line)
                    continue

                # Check if line contains [-] or [+] indicators
                stripped = line.strip()
                if stripped.startswith('[-]') or stripped.startswith('[+]'):
                    # Extract the section name (everything after the indicator)
                    # Find the actual section bracket [SectionName]
                    bracket_start = line.find('[', line.find('[') + 1)  # Find second [
                    if bracket_start > 0:
                        # Extract just the section name part
                        section_part = line[bracket_start:]
                        clean_lines.append(section_part)
                    else:
                        # Fallback: remove [-] or [+] prefix
                        clean_line = line.replace('[-]', '').replace('[+]', '').strip()
                        clean_lines.append(clean_line)
                else:
                    # Regular line, keep as is
                    clean_lines.append(line)

            # Join lines back together
            clean_content = '\n'.join(clean_lines)

            # Remove any extra blank lines that might have been created
            clean_content = '\n'.join(line for line in clean_content.split('\n') if line.strip() or not line)

            return clean_content

        except Exception as e:
            print(f"Error generating clean settings content: {str(e)}", file=sys.stderr)
            # Fallback to original content
            return self.original_content


    def load_temp_content_for_sections(self, sections_to_update):
        """Load content from temporary file for specific sections only"""
        try:
            if 'content' not in self.temp_content_storage:
                return None

            # temp content is stored content off all expanded
            temp_content1 = self.temp_content_storage['content']
            # current is from screen (with compressed sections]
            current_content1 = self.text_display.text_area.toPlainText()

            temp_content = self.generate_clean_settings_content(temp_content1)
            current_content = self.generate_clean_settings_content(current_content1)

            # Parse both contents into sections
            temp_sections = self.parse_content_into_sections(temp_content)
            current_sections = self.parse_content_into_sections(current_content)
            
            # Update only the requested sections from temp content
            for section_name in sections_to_update:
                if section_name in temp_sections:
                    current_sections[section_name] = temp_sections[section_name]
            
            # Reconstruct the content
            return self.reconstruct_content_from_sections(current_sections)
            
        except Exception as e:
            print(f"Error loading temporary content: {str(e)}", file=sys.stderr)
            return None
    
    def parse_content_into_sections(self, content):
        """Parse content into sections dictionary"""
        sections = {}
        lines = content.split('\n')
        current_section = None
        current_section_lines = []
        
        for line in lines:
            line_stripped = line.strip()
            if line_stripped.startswith('[') and line_stripped.endswith(']'):
                # Save previous section
                if current_section:
                    sections[current_section] = current_section_lines[:]
                # Start new section
                current_section = line_stripped
                current_section_lines = [line]
            else:
                if current_section:
                    current_section_lines.append(line)
                else:
                    # Lines before first section
                    if 'header' not in sections:
                        sections['header'] = []
                    sections['header'].append(line)
        
        # Save last section
        if current_section:
            sections[current_section] = current_section_lines
            
        return sections
    
    def reconstruct_content_from_sections(self, sections):
        """Reconstruct content from sections dictionary"""
        lines = []
        
        # Add header lines first
        if 'header' in sections:
            lines.extend(sections['header'])
        
        # Add all sections except header
        for section_name, section_lines in sections.items():
            if section_name != 'header':
                lines.extend(section_lines)
                
        return '\n'.join(lines)


    def save_file(self,new=False):
        """Handle file saving"""
        if not self.file_manager.has_file_loaded():
            self.status_bar.showMessage("No file loaded - use Save As instead")
            return

        # Apply any pending (debounced) field changes so the save captures them
        self._flush_pending_field_changes()

        # Store current scroll and cursor position before saving
        position_data = self.save_scroll_position()

        # expand all first
        #self.parse_file(show_status=False, expand_all=True)
        # Expand everything at the beginning of parsing only if expand_all is True
        save_collapse = self.collapsed_sections.copy()
        sections_to_update = list(self.collapsed_sections)
        #self.collapsed_sections.clear()
        # Load content from temporary file for collapsed sections only
        if sections_to_update:
            content = self.load_temp_content_for_sections(sections_to_update)
            #if content:
                #self.original_content = content
                #self.text_display.set_original_content(updated_content)
        else:
            content = self.text_display.text_area.toPlainText()
            # Generate clean settings file content without [-]/[+] indicators
            content = self.generate_clean_settings_content(content)

        if new:
            success, filename, message = self.file_manager.save_as_file(content)
        else:
            success, message = self.file_manager.save_file(content)
        # Update original content after successful save and re-parse
        if success:
            if new:
                self.filename_label.setText(f"Saved: {filename}")
                self.filename_label.setStyleSheet("color: blue; font-weight: bold;")
                self.status_bar.showMessage(f"File saved: {self.file_manager.get_current_file_path()}")
            else:
                self.status_bar.showMessage("File saved")

            self.original_content = content
            self.text_display.set_original_content(content)
            # Re-parse the file to restore formatting with the saved changes
            self.parse_file(expand_all=False,load=True)
            # Saved: clear the unsaved-changes indicator
            self._mark_clean()
            # Rebuild the mask only if MaskMap changed, then re-check gauges / PathOut
            self._rebuild_mask_cache()
            self._update_warnings()
            # Restore scroll and cursor position after parsing
            self.collapsed_sections = save_collapse
            self.compress_sections(all=False, compress_sections=self.collapsed_sections)
            self.restore_scroll_position(position_data)
        else:
            self.status_bar.showMessage(message)


    def save_as_file(self):
        """Handle save as"""
        #success, filename, message = self.file_manager.save_as_file(content)
        self.save_file(new=True)


    def compress_sections(self,all=True,compress_sections=[]):
        """Collapse sections in the file"""

        content = self.expand_all_sections(notexpand=True)
        #content = self.text_display.text_area.toPlainText()
        content = self.generate_clean_settings_content(content)
        #self.temp_content_storage['content'] = content

        # Find all section names in the original content
        if all:
            section_names = []
            for line in content.split('\n'):
                line_stripped = line.strip()
                if line_stripped.startswith('[') and line_stripped.endswith(']'):
                    section_names.append(line_stripped)

            # Add all sections to collapsed set
            self.collapsed_sections = set(section_names)
        else:
            self.collapsed_sections = compress_sections

        # Re-parse to update the view without expanding all
        self.parse_file(expand_all=False, load=False, content=content)


    def compress_all_sections(self):
        """Collapse all sections in the file"""
        if not self.file_manager.has_file_loaded():
            self.status_bar.showMessage("No file loaded")
            return

        # Remember scroll position for expand all
        #self.compress_expand_scroll_position = self.save_scroll_position()
        self.compress_sections(all=True)

    def expand_all_sections(self,notexpand=True):
        """Expand all sections in the file"""
        if not self.file_manager.has_file_loaded():
            self.status_bar.showMessage("No file loaded")
            return
        
        # Get list of sections that were collapsed
        content = self.text_display.text_area.toPlainText()
        self.collapsed_sections = set()
        for line in content.split('\n'):
            line_stripped = line.strip()
            if line_stripped.startswith('[+]'):
                self.collapsed_sections.add(line_stripped[4:])

        sections_to_update = list(self.collapsed_sections)

        # Load content from temporary file for collapsed sections only
        if sections_to_update:
            content = self.load_temp_content_for_sections(sections_to_update)
            if content:
                self.original_content = content
                self.text_display.set_original_content(content)
        else:
            content = self.text_display.text_area.toPlainText()
            content = self.generate_clean_settings_content(content)

        # Clear all collapsed sections
        if not(notexpand):
            self.collapsed_sections.clear()

        # store all content in a dict
        self.temp_content_storage['content'] = content
        # Re-parse to update the view and expand all
        self.parse_file(expand_all=not(notexpand),load=False,content=content)

        return content

        
        # Restore scroll position from when compress all was used
        #if self.compress_expand_scroll_position:
        #    self.restore_scroll_position(self.compress_expand_scroll_position)
    
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
        self.text_area.ensureCursorVisible()
        self.status_bar.showMessage("Jumped to bottom of file")
    
    def eventFilter(self, obj, event):
        """Handle mouse events for expand/collapse functionality"""
        if obj == self.text_area.viewport() and event.type() == QEvent.MouseButtonPress:
            if event.button() == Qt.LeftButton:
                # Get cursor position
                cursor = self.text_area.cursorForPosition(event.pos())
                cursor.select(QTextCursor.LineUnderCursor)
                line_text = cursor.selectedText()
                
                # Check if line contains expand/collapse controls
                if '[-]' in line_text:
                    # Extract section name - look for [SectionName] pattern
                    bracket_start = line_text.find('[', 3)  # Skip the [-] part
                    if bracket_start > 0:
                        bracket_end = line_text.find(']', bracket_start)
                        if bracket_end > bracket_start:
                            section_name = line_text[bracket_start:bracket_end + 1]

                            self.collapsed_sections.add(section_name)
                            self.compress_sections(all=False,compress_sections=self.collapsed_sections)

                            #self._refresh_view_preserving_collapsed_state()
                            # Restore position after collapsing
                            #self.restore_scroll_position(position_data)
                            return True
                        
                elif '[+]' in line_text:
                    # Extract section name - look for [SectionName] pattern
                    bracket_start = line_text.find('[', 3)  # Skip the [+] part
                    if bracket_start > 0:
                        bracket_end = line_text.find(']', bracket_start)
                        if bracket_end > bracket_start:
                            section_name = line_text[bracket_start:bracket_end + 1]
                            # Store position before expanding
                            position_data = self.save_scroll_position()

                            self.collapsed_sections.discard(section_name)
                            self.compress_sections(all=False, compress_sections=self.collapsed_sections)

                            # Restore position after expanding
                            self.restore_scroll_position(position_data)
                            return True
        
        return super().eventFilter(obj, event)
    

    
    def close_subsidiary_windows(self):
        """Close any open subsidiary windows (options window and basin viewer)"""
        # Close options window if it exists and is visible
        if hasattr(self, 'options_window') and self.options_window:
            try:
                if self.options_window.isVisible():
                    self.options_window.close()
            except:
                pass  # Window may already be closed or destroyed
                
        # Close basin viewer if it exists and is visible
        if hasattr(self, 'basin_viewer') and self.basin_viewer:
            try:
                if hasattr(self.basin_viewer, 'basin_window') and self.basin_viewer.basin_window:
                    if self.basin_viewer.basin_window.isVisible():
                        self.basin_viewer.basin_window.close()
            except:
                pass  # Window may already be closed or destroyed
    
    def set_show_basin_button_active(self, active: bool = True):
        """Set Show Basin button to light blue (active) or normal styling."""
        if active:
            # Light blue active style
            light_blue_style = """
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 #add8e6, stop:1 #87ceeb);
                    border: 2px solid #74b9ff;
                    border-radius: 8px;
                    color: black;
                    font-weight: 600;
                    font-size: 13px;
                    padding: 8px 16px;
                    min-height: 32px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 #e0f6ff, stop:1 #add8e6);
                    border-color: #0984e3;
                    box-shadow: 0 2px 8px rgba(173, 216, 230, 0.4);
                }
                QPushButton:pressed {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 #87ceeb, stop:1 #5dade2);
                    border-color: #0984e3;
                }
            """
            self.show_basin_button.setStyleSheet(light_blue_style)
        else:
            # Reset to normal style
            normal_style = """
                QPushButton {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 #ffffff, stop:1 #f1f3f4);
                    border: 2px solid #e1e5e9;
                    border-radius: 8px;
                    color: #2c3e50;
                    font-weight: 600;
                    font-size: 13px;
                    padding: 8px 16px;
                    min-height: 32px;
                }
                QPushButton:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 #f8f9fa, stop:1 #e9ecef);
                    border-color: #74b9ff;
                    box-shadow: 0 2px 8px rgba(116, 185, 255, 0.2);
                }
                QPushButton:pressed {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 #e9ecef, stop:1 #dee2e6);
                    border-color: #0984e3;
                }
            """
            self.show_basin_button.setStyleSheet(normal_style)
    
    def show_basin(self):
        """Load basin data using xarray from ldd path in [TOPOP] section"""
        try:
            # Get current configuration content for placeholder resolution
            config_content = None
            if hasattr(self, 'original_content') and self.original_content:
                config_content = self.original_content
            
            if not config_content:
                self.status_bar.showMessage("No configuration content available for basin loading")
                return
            
            # Create basin viewer with config content and load data
            # Keep reference to prevent garbage collection
            self.basin_viewer = BasinViewer(config_content)
            self.basin_viewer.show_basin(self.file_manager.get_current_file_path())
            self.status_bar.showMessage("Basin data loaded from ldd path")
        except Exception as e:
            print(f"Error loading basin: {str(e)}", file=sys.stderr)
            self.status_bar.showMessage(f"Error loading basin: {str(e)}")
    
    def open_options_window(self):
        """Open the options window for managing boolean configuration options"""

        section_names = ['[OPTIONS]','[FILE_PATHS]','[MASK_OUTLET]','[TIME-RELATED_CONSTANTS]']
        for name in section_names:
            self.collapsed_sections.discard(name)

        self.compress_sections(all=False, compress_sections=self.collapsed_sections)


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

        # Final cleanup of any remaining file operations
        self.cleanup_file_operations()

        # Accept the close event
        event.accept()
    
    def _add_section_to_view(self, formatted_lines, section_name, section_content):
        """Add a section with expand/collapse functionality"""
        is_collapsed = section_name in self.collapsed_sections
        
        if is_collapsed:
            # Show collapsed section with [+] to expand
            header_line = f'<span style="color: blue; cursor: pointer;">[+]</span> <span style="font-weight: bold;">{section_name}</span>'
            formatted_lines.append(header_line)
        else:
            # Show expanded section with [-] to collapse
            header_line = f'<span style="color: blue; cursor: pointer;">[-]</span> <span style="font-weight: bold;">{section_name}</span>'
            formatted_lines.append(header_line)
            
            # Add section content
            for line in section_content:
                formatted_lines.append(self._format_line(line))
    
    def _format_line(self, line):
        """Format a content line with appropriate styling"""
        line_stripped = line.strip()
        
        if '=' in line and not line_stripped.startswith('#') and not line_stripped.startswith(';'):
            # Key-value pairs
            key, value = line.split('=', 1)
            value_clean = value.strip()
            
            if value_clean.lower() == 'true':
                return f'<span style="color: black;">{key}= <span style="color: blue;">{value_clean}</span></span>'
            elif value_clean.lower() == 'false':
                return f'<span style="color: black;">{key}= <span style="color: red;">{value_clean}</span></span>'
            else:
                return f'<span style="color: black;">{key}= {value.strip()}</span>'
        elif line_stripped.startswith('#'):
            # Comments - only these should be dark gray
            preserved_line = line.replace(' ', '&nbsp;').replace('\t', '&nbsp;&nbsp;&nbsp;&nbsp;')
            return f'<span style="color: darkgray;">{preserved_line}</span>'
        else:
            # Other lines - explicitly set to black to prevent color bleeding
            return f'<span style="color: black;">{line}</span>'
    
    def _show_cwatminfo_menu(self, pos):
        """Right-click menu for the CWatM output: copy selection or all output."""
        menu = QMenu(self.cwatminfo_label)
        copy_sel = menu.addAction("Copy")
        copy_sel.setEnabled(self.cwatminfo_label.hasSelectedText())
        copy_sel.triggered.connect(
            lambda: QApplication.clipboard().setText(self.cwatminfo_label.selectedText())
        )
        copy_all = menu.addAction("Copy all output")
        copy_all.triggered.connect(self.copy_cwatminfo_to_clipboard)
        menu.exec(self.cwatminfo_label.mapToGlobal(pos))

    def copy_cwatminfo_to_clipboard(self):
        """Copy the full CWatM output buffer to the clipboard as plain text."""
        plain_lines = [re.sub(r'<[^>]+>', '', line) for line in self.cwatm_output_buffer]
        QApplication.clipboard().setText('\n'.join(plain_lines))

    def append_to_cwatminfo(self, text, is_error=False):
        """Append text to cwatminfo output buffer and update display immediately"""
        if text.strip():  # Only add non-empty text
            # CWatM prints per-timestep progress (date + discharge) with a leading
            # carriage return and end='' (see output.py), so a console overwrites a
            # single line in place. Mirror that: a '\r' line replaces the previous
            # progress line instead of accumulating a new line each timestep.
            is_progress = text.lstrip(' \t').startswith('\r')

            # Filter out "Worker:" messages
            text_stripped = text.strip()
            if text_stripped.startswith("Worker:"):
                return  # Skip this message

            # Write to file if output file is configured
            if self.output_file_path:
                try:
                    with open(self.output_file_path, 'a', encoding='utf-8') as f:
                        f.write(text_stripped + '\n')
                        f.flush()  # Ensure immediate write
                except Exception as e:
                    print(f"Error writing to output file: {e}")
                    self.output_file_path = None  # Disable file writing if there's an error

            # Format text with color if it's an error
            if is_error:
                formatted_text = f'<span style="color: darkred;">{text_stripped}</span>'
            else:
                formatted_text = text_stripped

            # Overwrite the previous progress line in place; otherwise append.
            if is_progress and self._last_was_progress and self.cwatm_output_buffer:
                self.cwatm_output_buffer[-1] = formatted_text
            else:
                self.cwatm_output_buffer.append(formatted_text)
            self._last_was_progress = is_progress

            # Keep only last 100 lines to prevent memory issues
            if len(self.cwatm_output_buffer) > 100:
                self.cwatm_output_buffer = self.cwatm_output_buffer[-100:]

            # Update display immediately after each print
            self.update_cwatminfo_display()
    
    def update_cwatminfo_display(self):
        """Regular update of cwatminfo display"""
        if self.cwatm_output_buffer:
            # Join all output lines with HTML line breaks
            display_text = '<br>'.join(self.cwatm_output_buffer)
            
            # Store current scroll position before updating
            scroll_bar = self.scroll_area.verticalScrollBar()
            was_at_bottom = scroll_bar.value() >= scroll_bar.maximum() - 10  # Allow for small rounding errors
            
            # Update the text using HTML formatting
            self.cwatminfo_label.setText(f'<html><body>{display_text}</body></html>')
            
            # Adjust label size to fit content
            self.cwatminfo_label.adjustSize()
            
            # Auto-scroll to bottom only if we were already at/near the bottom
            # This keeps the current view stable if user is reading earlier entries
            if was_at_bottom:
                # Schedule scroll to bottom after the widget updates
                QApplication.processEvents()
                scroll_bar.setValue(scroll_bar.maximum())