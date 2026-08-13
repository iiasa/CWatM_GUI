"""Tools ▸ Check Data - run CWatM's data analysis (the ``-c`` flag) over the loaded
settings file and show the result table.

CWatM opens every input map the settings file references, reports its shape, valid
cells, min/mean/max and - when a discharge NetCDF is given - whether the dates match.
The window shows that CSV as a table, colours the trouble rows, and can filter, sort,
copy and export it.

Three things this window must keep doing right:

* **The check runs in a worker thread** (``_CheckWorker``). It reads every input file,
  which on a network share is minutes; running it in the GUI thread (as it used to)
  froze the whole application with no progress and no output. The window is therefore
  **not modal** either - a modal dialog would block the GUI just the same.
* **Its output is shown here**, in the log pane below the table (``_LogTee`` mirrors
  ``sys.stdout``/``sys.stderr`` while the check runs). Everything used to be printed
  into the main window's output box *behind* a modal dialog, so a failure was
  invisible.
* **A double-click on a result row jumps to that key** in the settings editor: column
  "Name" of CWatM's check table is the settings key (``checks.py``), so the table and
  the file can be tied together.
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QLineEdit, QFileDialog, QSplitter,
                             QWidget, QFrame, QPlainTextEdit, QTableWidget,
                             QTableWidgetItem, QHeaderView, QApplication,
                             QMessageBox)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QColor, QIcon, QTextCursor
import os
import re
import sys
import threading
import time

from src.gui.utils import theme
from src.gui.utils.gui_log import get_logger

log = get_logger("check_data_window")

# cwatm.run_cwatm (-> scipy/pandas/netCDF4) and netCDF4 are imported lazily in
# the methods that use them (report §4.1) so importing this module stays cheap.

# Columns of CWatM's check table whose "False" means trouble
# (cwatm/management_modules/checks.py builds the header).
_TROUBLE_COLUMNS = ("valid", "same date")

# Checks whose window was closed before they finished: kept referenced so Python
# never collects a *running* QThread (see CheckDataWindow.closeEvent).
_ORPHANED_WORKERS = []


class _LogTee:
    """A stdout/stderr stand-in that passes everything through to the original
    stream **and** to a callback (the window's log pane).

    The check prints through plain ``print()``, so this is the only way to show its
    output in the window without touching cwatm code."""

    def __init__(self, original, emit, is_error=False, owner_thread=None):
        self._original = original
        self._emit = emit
        self._is_error = is_error
        # Only what the check itself prints is mirrored here: sys.stdout is global,
        # so without this the log pane would also collect whatever the GUI thread
        # printed while the check happened to be running.
        self._owner_thread = owner_thread

    def write(self, text):
        try:
            if self._original is not None:
                self._original.write(text)
        except Exception:
            log.debug("write: ignored", exc_info=True)
        try:
            if text and (self._owner_thread is None
                         or threading.get_ident() == self._owner_thread):
                self._emit(text, self._is_error)
        except Exception:
            log.debug("write: ignored", exc_info=True)
        return len(text or "")

    def flush(self):
        try:
            if self._original is not None:
                self._original.flush()
        except Exception:
            log.debug("flush: ignored", exc_info=True)

    def __getattr__(self, name):
        return getattr(self._original, name)


class _CheckWorker(QThread):
    """Runs ``run_cwatm.main(settings, ['-c', …])`` off the GUI thread.

    There is no Stop: CWatM's check has no cooperative break point, and a QThread
    cannot be killed safely. The window stays usable while it runs, and the model
    run itself (which *is* stoppable) uses a separate process instead."""

    output = Signal(str, bool)          # text, is_error
    done = Signal(bool, object, str)    # success, checkinfo, error text

    def __init__(self, settings_file, netcdf_file=None):
        super().__init__()
        self._settings = settings_file
        self._netcdf = netcdf_file

    def run(self):
        checkinfo, success, error = None, False, ""
        me = threading.get_ident()
        streams = (sys.stdout, sys.stderr)
        sys.stdout = _LogTee(streams[0], self.output.emit, False, me)
        sys.stderr = _LogTee(streams[1], self.output.emit, True, me)
        try:
            args = ['-c']
            if self._netcdf:
                args.append(self._netcdf)
            import cwatm.run_cwatm as run_cwatm      # lazy (§4.1)
            success, checkinfo = run_cwatm.main(self._settings, args)
        except SystemExit as e:
            error = f"CWatM exited early (code {e.code})"
        except BaseException as e:                   # noqa: BLE001
            import traceback
            error = f"{e}\n{traceback.format_exc()}"
        finally:
            sys.stdout, sys.stderr = streams
        self.done.emit(bool(success), checkinfo, error)


class _CheckItem(QTableWidgetItem):
    """Table cell that sorts numerically when both cells hold numbers."""

    def __lt__(self, other):
        try:
            return float(self.text().strip()) < float(other.text().strip())
        except (TypeError, ValueError):
            return self.text().strip().lower() < other.text().strip().lower()


def _cell_true_bg():
    """Result-table cell background for OK/True cells (light blue; theme-aware)."""
    return QColor("#d9eff9") if not theme.is_dark() else theme.qcolor("changed_line")


def _cell_false_bg():
    """Result-table cell background for trouble/False cells (light red; theme-aware)."""
    return QColor("#FFB6C1") if not theme.is_dark() else theme.qcolor("duplicate_line")


def _modern_btn(font_size=12, radius=6, padding="8px 16px", extra_base="",
                with_disabled=False):
    """The window's standard button QSS built from the active theme (Normal =
    the classic white-gradient look)."""
    disabled = ""
    if with_disabled:
        disabled = f"""
            QPushButton:disabled {{
                background: {theme.c('surface_bg')};
                border-color: {theme.c('border')};
                color: {theme.c('text_gray')};
            }}"""
    return f"""
        QPushButton {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {theme.c('btn_top')}, stop:1 {theme.c('btn_bottom')});
            border: 2px solid {theme.c('btn_border')};
            border-radius: {radius}px;
            color: {theme.c('btn_text')};
            font-weight: 600;
            font-size: {font_size}px;
            padding: {padding};
            {extra_base}
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
        }}{disabled}
    """


class CheckDataWindow(QDialog):
    """Window for checking CWatM data and comparing outputs"""
    
    def __init__(self, parent=None, config_content=None):
        super().__init__(parent)
        self.config_content = config_content
        self.parent_window = parent
        # Default next to the run's own results, resolved: the old default was the
        # relative "check_cwatm1.csv", written into the current working directory -
        # for an installed build a folder the user may not be able to write to.
        self.output_file_path = self._default_output_path()
        self.netcdf_file_path = ""
        self.original_headers = []
        self.original_data = []
        self._worker = None
        self._started_at = None

        self.setWindowTitle("Check Data")
        # Not modal - see the module docstring: the check runs in a thread so the GUI
        # stays usable, which a modal dialog would undo.
        self.setModal(False)
        self.resize(1050, 700)
        
        # Set window flags for min/max/close buttons but no taskbar icon
        self.setWindowFlags(Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        
        # Set CWatM icon
        try:
            icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), 'assets', 'cwatm.ico')
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception as e:
            print(f"Warning: Could not load CWatM icon: {e}", file=sys.stderr)
        
        # Position window on the left side of the screen
        self.move(150, 100)

        self.init_ui()
        self._check_maskmap_supported()

    # ------------------------------------------------------------------ helpers
    def _settings_text(self):
        """The settings content as it is **now** (live boxes substituted when the
        main window offers that), else what the window was opened with."""
        mw = self.parent_window
        for getter in ("_live_content",):
            try:
                text = getattr(mw, getter)()
                if text:
                    return text
            except Exception:
                log.debug("live content unavailable", exc_info=True)
        return self.config_content or ""

    def _setting_value(self, key):
        """Raw value of a settings key (first hit, comment stripped), or ''."""
        want = key.lower()
        for line in self._settings_text().split('\n'):
            s = line.strip()
            if not s or s[0] in '#;[':
                continue
            eq = s.find('=')
            if eq > 0 and s[:eq].strip().lower() == want:
                return re.split(r'[#;]', s[eq + 1:], 1)[0].strip()
        return ""

    def _default_output_path(self):
        """``<PathOut>/check_cwatm1.csv`` when PathOut can be resolved."""
        try:
            folder = self.parent_window._resolved_pathout_dir()
            if folder:
                return os.path.join(folder, "check_cwatm1.csv")
        except Exception:
            log.debug("PathOut for the check output not resolvable", exc_info=True)
        return os.path.abspath("check_cwatm1.csv")

    @staticmethod
    def _is_coordinate_value(value):
        """True when a MaskMap value is a 'lon lat' pair rather than a map file -
        same rule as basin_viewer._parse_coord_pairs."""
        tokens = [t for t in re.split(r'[\s,]+', (value or '').strip()) if t]
        if len(tokens) < 2:
            return False
        try:
            [float(t) for t in tokens]
        except ValueError:
            return False
        return True

    def _check_maskmap_supported(self):
        """CWatM's check mode needs a MaskMap **map**; with coordinates it fails deep
        inside with a confusing error. The window said so in red text but still let
        you press the button - now the button says why it is disabled."""
        value = self._setting_value("MaskMap")
        blocked = self._is_coordinate_value(value)
        self.run_check_button.setEnabled(not blocked)
        self.run_check_button.setToolTip(
            f"MaskMap is a coordinate ({value}) - Check Data needs a MaskMap map file"
            if blocked else "Run CWatM in check mode (-c) over the loaded settings file")
        if blocked:
            self._log(f"Check Data is disabled: MaskMap = {value} is a coordinate, "
                      "not a map file.", True)
        return not blocked

    def init_ui(self):
        """Initialize the user interface"""
        main_layout = QHBoxLayout()
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Create left panel
        self.create_left_panel(main_layout)
        
        # Create right panel
        self.create_right_panel(main_layout)
        
        self.setLayout(main_layout)
        
    def create_left_panel(self, parent_layout):
        """Create the left panel with data checking functionality"""
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setSpacing(15)
        left_layout.setContentsMargins(10, 10, 10, 10)
        
        # Title label with modern styling
        title_label = QLabel("Check Data")
        if theme.is_dark():
            _title_color, _title_border = theme.c('accent'), theme.c('border')
        else:  # classic blue gradient title + underline
            _title_color = ("qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                            "stop:0 #2980b9, stop:1 #3498db)")
            _title_border = ("qlineargradient(x1:0, y1:0, x2:1, y2:0, "
                             "stop:0 #74b9ff, stop:1 #0984e3)")
        title_label.setStyleSheet(f"""
            QLabel {{
                font-family: 'Segoe UI', sans-serif;
                font-weight: 700;
                font-size: 24px;
                color: {_title_color};
                padding: 15px 0px 20px 0px;
                border-bottom: 3px solid {_title_border};
                margin-bottom: 20px;
            }}
        """)
        left_layout.addWidget(title_label)
        
        # Description text
        description_text = QLabel(
            "With this window you can check the data of the settings file<br>"
            "It will run CWatM but only analyse the data in the settings file<br><br>"
            "<b style='color:#c0392b;'>Works only if you use a MaskMap map, "
            "not coordinates!</b>"
        )
        description_text.setTextFormat(Qt.RichText)
        description_text.setStyleSheet(f"""
            QLabel {{
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                color: {theme.c('text')};
                padding: 10px 0px;
                line-height: 1.4;
            }}
        """)
        left_layout.addWidget(description_text)
        
        # Output file section
        output_section_layout = QHBoxLayout()
        

        self.output_browse_button = QPushButton("Save result file as .csv")
        self.output_browse_button.setStyleSheet(
            _modern_btn(extra_base="min-width: 80px;"))
        self.output_browse_button.clicked.connect(self.browse_output_file)
        
        # Create filename display label
        self.output_filename_label = QLabel(self.output_file_path)
        self.output_filename_label.setStyleSheet(f"""
            QLabel {{
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
                color: {theme.c('text_gray')};
                padding: 2px 5px;
                background-color: {theme.c('surface_bg')};
                border: 1px solid {theme.c('border')};
                border-radius: 3px;
                margin-top: 5px;
            }}
        """)
        
        # Top row with label and browse button
        output_section_layout.addWidget(self.output_browse_button)
        output_section_layout.addStretch()
        
        left_layout.addLayout(output_section_layout)
        
        # Add filename label below on separate row
        left_layout.addWidget(self.output_filename_label)
        
        # Separator
        separator1 = QFrame()
        separator1.setFrameShape(QFrame.HLine)
        separator1.setFrameShadow(QFrame.Sunken)
        separator1.setStyleSheet(f"QFrame {{ color: {theme.c('border')}; }}")
        left_layout.addWidget(separator1)
        
        # Comparison section description
        comparison_text = QLabel(
            "It can also be used to check against an existing output\n"
            "output must be a discharge... netcdf file\n"
        )
        comparison_text.setStyleSheet(f"""
            QLabel {{
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                color: {theme.c('text')};
                padding: 10px 0px;
                line-height: 1.4;
            }}
        """)
        left_layout.addWidget(comparison_text)
        
        # NetCDF file selection
        netcdf_section_layout = QVBoxLayout()


        self.browse_button = QPushButton("Select discharge NetCDF file")
        self.browse_button.setStyleSheet(
            _modern_btn(extra_base="min-width: 80px; margin-top: -10px;"))
        self.browse_button.clicked.connect(self.browse_netcdf_file)
        
        # Create NetCDF filename display label
        self.netcdf_filename_label = QLabel("No file selected")
        self.netcdf_filename_label.setStyleSheet(f"""
            QLabel {{
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
                color: {theme.c('text_gray')};
                padding: 2px 5px;
                background-color: {theme.c('surface_bg')};
                border: 1px solid {theme.c('border')};
                border-radius: 3px;
                margin-top: -5px;
            }}
        """)
        
        netcdf_section_layout.addWidget(self.browse_button)
        netcdf_section_layout.addWidget(self.netcdf_filename_label)
        
        # Restore settings button
        self.restore_settings_button = QPushButton("Restore settings from discharge map")
        self.restore_settings_button.setStyleSheet(
            _modern_btn(extra_base="min-width: 80px; margin-top: 5px;",
                        with_disabled=True))
        self.restore_settings_button.clicked.connect(self.restore_settings_from_discharge)
        self.restore_settings_button.setEnabled(False)  # Initially disabled
        netcdf_section_layout.addWidget(self.restore_settings_button)
        
        left_layout.addLayout(netcdf_section_layout)
        
        # Add stretch to push everything to top
        left_layout.addStretch()
        
        # Bottom buttons
        button_layout = QHBoxLayout()
        
        self.run_check_button = QPushButton("Run Check")
        self.run_check_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #2980b9, stop:1 #3498db);
                border: 2px solid #2980b9;
                border-radius: 8px;
                color: white;
                font-weight: 600;
                font-size: 13px;
                padding: 10px 20px;
                min-width: 100px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #3498db, stop:1 #74b9ff);
                border-color: #74b9ff;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #2980b9, stop:1 #1e6ba8);
                border-color: #1e6ba8;
            }
        """)
        self.run_check_button.clicked.connect(self.run_check)
        
        self.close_button = QPushButton("Close")
        self.close_button.setStyleSheet(
            _modern_btn(font_size=13, radius=8, padding="10px 20px",
                        extra_base="min-width: 100px;"))
        self.close_button.clicked.connect(self.close)
        
        button_layout.addWidget(self.run_check_button)
        button_layout.addStretch()
        button_layout.addWidget(self.close_button)
        
        left_layout.addLayout(button_layout)
        
        left_panel.setLayout(left_layout)
        parent_layout.addWidget(left_panel, 3)  # Left panel weight 3
        
    def create_right_panel(self, parent_layout):
        """Create the right panel for displaying check results table"""
        right_panel = QWidget()
        right_layout = QVBoxLayout()
        right_layout.setSpacing(15)
        right_layout.setContentsMargins(10, 10, 10, 10)
        
        # Results table label and select trouble button
        label_button_layout = QHBoxLayout()
        label_button_layout.setSpacing(10)
        
        results_label = QLabel("Check Results Table")
        results_label.setStyleSheet(f"""
            QLabel {{
                font-family: 'Segoe UI', sans-serif;
                font-weight: 600;
                font-size: 16px;
                color: {theme.c('text')};
                padding: 15px 0px 20px 0px;
                border-bottom: 2px solid {theme.c('border')};
                margin-bottom: 20px;
            }}
        """)
        
        self.select_trouble_button = QPushButton("Select trouble")
        self.select_trouble_button.setStyleSheet(
            _modern_btn(font_size=11, padding="4px 12px",
                        extra_base="min-width: 80px; max-height: 21px;",
                        with_disabled=True))
        self.select_trouble_button.clicked.connect(self.filter_trouble_rows)
        self.select_trouble_button.setEnabled(False)  # Initially disabled
        
        self.copy_table_button = QPushButton("Copy Table")
        self.copy_table_button.setStyleSheet(
            _modern_btn(font_size=11, padding="4px 12px",
                        extra_base="min-width: 80px; max-height: 21px;",
                        with_disabled=True))
        self.copy_table_button.clicked.connect(self.copy_table_to_clipboard)
        self.copy_table_button.setEnabled(False)  # Initially disabled

        self.export_button = QPushButton("Export CSV")
        self.export_button.setToolTip("Write the rows shown here to a .csv file")
        self.export_button.setStyleSheet(
            _modern_btn(font_size=11, padding="4px 12px",
                        extra_base="min-width: 80px; max-height: 21px;",
                        with_disabled=True))
        self.export_button.clicked.connect(self.export_table_csv)
        self.export_button.setEnabled(False)

        label_button_layout.addWidget(results_label)
        label_button_layout.addWidget(self.select_trouble_button)
        label_button_layout.addWidget(self.copy_table_button)
        label_button_layout.addWidget(self.export_button)
        label_button_layout.addStretch()  # Push buttons to the right of label

        right_layout.addLayout(label_button_layout)

        # Filter box + the summary of the last check ("312 rows · 7 not valid").
        summary_row = QHBoxLayout()
        summary_row.setSpacing(10)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter rows…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setFixedWidth(220)
        self.filter_edit.setStyleSheet(
            f"QLineEdit {{ background: {theme.c('field_bg')}; "
            f"color: {theme.c('field_text')}; "
            f"border: 1px solid {theme.c('field_border')}; border-radius: 5px; "
            "padding: 3px 6px; font-size: 11px; }")
        self.filter_edit.textChanged.connect(self._apply_row_filter)
        self.summary_label = QLabel("no check run yet")
        self.summary_label.setStyleSheet(
            f"font-family: 'Segoe UI', sans-serif; font-size: 11px; "
            f"color: {theme.c('text_gray')};")
        summary_row.addWidget(self.filter_edit)
        summary_row.addWidget(self.summary_label, 1)
        right_layout.addLayout(summary_row)

        # Results table widget 
        self.results_table = QTableWidget()

        self.results_table.setStyleSheet(f"""
            QTableWidget {{
                border: 2px solid {theme.c('border')};
                border-radius: 8px;
                gridline-color: {theme.c('border')};
                selection-background-color: {theme.c('sel_bg')};
                selection-color: {theme.c('sel_text')};
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10px;
            }}

            QTableWidget::item:selected {{
                color: {theme.c('sel_text')};
            }}
            QHeaderView::section {{
                background-color: {theme.c('surface_bg')};
                border: 1px solid {theme.c('border')};
                padding: 8px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 11px;
                font-weight: 600;
                color: {theme.c('text')};
            }}
        """)
        
        # Set table properties
        self.results_table.setSortingEnabled(False)
        self.results_table.setAlternatingRowColors(True)
        
        # Enable scrolling and set scroll policies
        self.results_table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.results_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        # Set header properties
        horizontal_header = self.results_table.horizontalHeader()
        horizontal_header.setSectionResizeMode(QHeaderView.Interactive)  # Allow column resizing
        horizontal_header.setStretchLastSection(True)  # Stretch last column
        
        vertical_header = self.results_table.verticalHeader()
        vertical_header.setVisible(True)
        vertical_header.setDefaultSectionSize(25)  # Set row height
        
        # Set minimum size to ensure scrollbars appear when needed
        self.results_table.setMinimumSize(400, 300)
        # A result row names a settings key ("Name" column) - double-click jumps to it.
        self.results_table.doubleClicked.connect(self._on_row_double_clicked)

        # The check's own output, in THIS window: it used to go to the main output
        # box behind a modal dialog, i.e. nowhere the user could see it.
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(4000)
        self.log_view.setPlaceholderText("CWatM's check output appears here")
        self.log_view.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {theme.c('out_bg')}; "
            f"color: {theme.c('out_text')}; "
            f"border: 1px solid {theme.c('out_border')}; border-radius: 6px; "
            "font-family: Consolas, monospace; font-size: 11px; }")

        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(self.results_table)
        splitter.addWidget(self.log_view)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 150])
        right_layout.addWidget(splitter)

        right_panel.setLayout(right_layout)
        parent_layout.addWidget(right_panel, 6)  # Right panel weight 6 (20% wider than previous weight 5)
        
    def browse_netcdf_file(self):
        """Open file dialog to select NetCDF discharge file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Discharge NetCDF File", "",
            "NetCDF Files (dischar*.nc);;All Files (*)"
        )
        
        if file_path:
            self.netcdf_file_path = file_path
            self.netcdf_filename_label.setText(file_path)
            # Enable the restore settings button when a NetCDF file is selected
            self.restore_settings_button.setEnabled(True)
    
    def browse_output_file(self):
        """Open file dialog to select output CSV file"""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Check Output As", self.output_file_path,
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if file_path:
            self.output_file_path = file_path
            self.output_filename_label.setText(file_path)
            
    # ---------------------------------------------------------------- log pane
    def _log(self, text, is_error=False):
        """Append to the window's own log pane (auto-scrolling, errors dark red)."""
        if not text:
            return
        view = getattr(self, "log_view", None)
        if view is None:
            return
        bar = view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        cursor = view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = cursor.charFormat()
        fmt.setForeground(QColor(theme.c('out_error') if is_error
                                 else theme.c('out_text')))
        cursor.setCharFormat(fmt)
        cursor.insertText(text if text.endswith("\n") else text + "\n")
        if at_bottom:
            bar.setValue(bar.maximum())

    def _on_worker_output(self, text, is_error):
        """Live output of the running check (one write of the tee'd stream)."""
        for line in str(text).replace("\r", "\n").split("\n"):
            if line.strip():
                self._log(line.rstrip(), is_error)

    # ------------------------------------------------------------- run the check
    def run_check(self):
        """Start the CWatM data check in a worker thread.

        The old version called ``run_cwatm.main`` straight from this handler, so the
        whole application froze - with no output, because everything was printed into
        the main window's box behind a modal dialog."""
        if self._worker is not None and self._worker.isRunning():
            return
        if not self._check_maskmap_supported():
            QMessageBox.information(
                self, "Check Data",
                "Check Data works only with a MaskMap map file, not with "
                "coordinates.\n\nChange MaskMap to a mask raster and try again.")
            return

        settings_file = ""
        try:
            settings_file = self.parent_window.file_manager.get_current_file_path() or ""
        except Exception:
            log.debug("no file manager on the parent", exc_info=True)
        if not settings_file or not os.path.isfile(settings_file):
            self._log("No settings file loaded - load one first.", True)
            QMessageBox.warning(self, "Check Data",
                                "No settings file is loaded.\nLoad one first.")
            return
        # The check reads the file from DISK, so unsaved edits would be checked as
        # they were, not as they are.
        if getattr(self.parent_window, "_is_dirty", False):
            answer = QMessageBox.question(
                self, "Check Data",
                "The settings file has unsaved changes.\n\n"
                "CWatM reads the file from disk, so the check would use the saved "
                "version, not what you see.\n\nSave it first and then check?",
                QMessageBox.Save | QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Save)
            if answer == QMessageBox.Cancel:
                return
            if answer == QMessageBox.Save:
                try:
                    self.parent_window.save_file()
                except Exception as e:  # noqa: BLE001
                    self._log(f"Saving failed: {e}", True)
                    return
                if getattr(self.parent_window, "_is_dirty", False):
                    self._log("The file was not saved - check cancelled.", True)
                    return

        netcdf_file = self.netcdf_file_path or None
        self.log_view.clear()
        self._log(f"Starting CWatM data check for: {os.path.basename(settings_file)}")
        self._log("Check mode: analysis only (-c flag)")
        if netcdf_file:
            self._log(f"Comparison with: {os.path.basename(netcdf_file)}")
        self._log("-" * 50)

        self._set_busy(True)
        self._worker = _CheckWorker(settings_file, netcdf_file)
        self._worker.output.connect(self._on_worker_output)   # bound -> queued
        self._worker.done.connect(self._on_check_done)
        self._worker.start()

    def _set_busy(self, busy):
        """Disable what must not be touched during a check and tick the elapsed time."""
        self.run_check_button.setEnabled(not busy)
        self.run_check_button.setText("Checking…" if busy else "Run Check")
        self.browse_button.setEnabled(not busy)
        self.output_browse_button.setEnabled(not busy)
        if busy:
            self._started_at = time.time()
            self._busy_timer = QTimer(self)
            self._busy_timer.timeout.connect(self._tick_elapsed)
            self._busy_timer.start(1000)
            self._tick_elapsed()
        else:
            timer = getattr(self, "_busy_timer", None)
            if timer is not None:
                timer.stop()
                self._busy_timer = None

    def _tick_elapsed(self):
        if self._started_at is None:
            return
        seconds = int(time.time() - self._started_at)
        self.summary_label.setText(
            f"checking… {seconds // 60}:{seconds % 60:02d} elapsed  "
            "(the window stays usable)")

    def _on_check_done(self, success, checkinfo, error):
        """Worker finished: write the csv, fill the table, report what happened."""
        duration = int(time.time() - (self._started_at or time.time()))
        self._worker = None
        self._set_busy(False)
        self._started_at = None

        if error:
            self._log(error, True)
        if not success:
            self._log("CWatM check completed with warnings or errors - see above.",
                      True)

        output_file = self.output_filename_label.text().strip()
        if output_file and checkinfo:
            try:
                folder = os.path.dirname(os.path.abspath(output_file))
                if folder and not os.path.isdir(folder):
                    os.makedirs(folder, exist_ok=True)
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(checkinfo)
                self._log(f"Check results saved to: {output_file}")
            except Exception as e:  # noqa: BLE001
                self._log(f"Error saving output file: {e}", True)

        if checkinfo:
            self.display_check_results_table(checkinfo)
            self._summarize(duration)
        else:
            self._log("No check data returned from CWatM", True)
            self.summary_label.setText(f"no results  ·  {duration} s")

    def _summarize(self, duration=None):
        """The line above the table: how many rows, and how many are trouble."""
        headers = [h.strip().lower() for h in self.original_headers]
        counts = {}
        for name in _TROUBLE_COLUMNS:
            if name in headers:
                col = headers.index(name)
                counts[name] = sum(1 for row in self.original_data
                                   if col < len(row)
                                   and str(row[col]).strip().lower() == "false")
        parts = [f"{len(self.original_data)} rows"]
        if counts.get("valid"):
            parts.append(f"{counts['valid']} not valid")
        if counts.get("same date"):
            parts.append(f"{counts['same date']} date mismatches")
        if not any(counts.values()):
            parts.append("no problems found")
        if duration is not None:
            parts.append(f"{duration} s")
        self.summary_label.setText("  ·  ".join(parts))
        trouble = sum(counts.values())
        self.summary_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 11px; font-weight: 600; "
            f"color: {theme.c('warn_color') if trouble else theme.c('ok_color')};")

    def closeEvent(self, event):
        """Never let a running check outlive the window (it writes into its widgets)."""
        worker = self._worker
        if worker is not None and worker.isRunning():
            answer = QMessageBox.question(
                self, "Check Data",
                "A data check is still running.\n\nWait for it to finish?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                event.ignore()
                return
            # Let it run out on its own: disconnect so it cannot write into widgets
            # that are going away, and keep the QThread referenced so Python does not
            # collect a running thread object (its stdout tee still emits its signal).
            try:
                worker.output.disconnect()
                worker.done.disconnect()
            except (RuntimeError, TypeError):
                log.debug("closeEvent: ignored", exc_info=True)
            _ORPHANED_WORKERS.append(worker)
            worker.finished.connect(
                lambda w=worker: _ORPHANED_WORKERS.remove(w)
                if w in _ORPHANED_WORKERS else None)
            self._worker = None
        super().closeEvent(event)

    def display_check_results_table(self, checkinfo):
        """Parse CWatM's check CSV and show every line in the results table."""
        try:
            table_lines = str(checkinfo).strip().split('\n')
            if not table_lines:
                self._log("No table data found in the check results", True)
                return

            # Parse CSV data
            csv_data = []
            headers = []

            for i, line in enumerate(table_lines):
                if line.strip():
                    # Split by comma and clean up values
                    row = [cell.strip().strip('"') for cell in line.split(',')]
                    if i == 0:
                        headers = row
                    else:
                        csv_data.append(row)

            if not headers or not csv_data:
                self._log("No valid table data found in the check results", True)
                return

            # Store original data for filtering
            self.original_headers = headers.copy()
            self.original_data = [row.copy() for row in csv_data]

            # One renderer for both paths (this one and the trouble filter) - the two
            # copies of the fill/colour/width code had already drifted apart.
            self._render_results_table(self.original_data)

            self._log(f"Check results table: {len(csv_data)} rows, "
                      f"{len(headers)} columns")

            # Enable the Select trouble / Copy / Export buttons now that there is data
            self.select_trouble_button.setEnabled(True)
            self.copy_table_button.setEnabled(True)
            self.export_button.setEnabled(True)
            # Fresh results: reset the trouble-filter toggle back to "Select trouble"
            self._trouble_filtered = False
            self.select_trouble_button.setText("Select trouble")

        except Exception as e:
            self._log(f"Error displaying check results table: {e}", True)
            log.warning("check results table failed", exc_info=True)

    def filter_trouble_rows(self):
        """Toggle between showing only troublesome rows (valid=False or Same Date=False)
        and showing all rows again. Clicking the button flips between the two."""
        try:
            if not self.original_headers or not self.original_data:
                self._log("No check results to filter yet.")
                return

            # Second click: restore all rows
            if getattr(self, "_trouble_filtered", False):
                self._render_results_table(self.original_data)
                self._trouble_filtered = False
                self.select_trouble_button.setText("Select trouble")
                self._log(f"Showing all {len(self.original_data)} rows")
                return

            # First click: keep only the troublesome rows
            trouble_cols = self._trouble_column_indexes()
            filtered_data = [row for row in self.original_data
                             if self._row_is_trouble(row, trouble_cols)]
            self._render_results_table(filtered_data)
            self._trouble_filtered = True
            self.select_trouble_button.setText("Show all")
            self._log(f"Filtered trouble rows: {len(filtered_data)} of "
                      f"{len(self.original_data)} rows")

        except Exception as e:  # noqa: BLE001
            self._log(f"Error filtering trouble rows: {e}", True)
            log.warning("trouble filter failed", exc_info=True)

    def _trouble_column_indexes(self):
        """Indexes of the columns whose "False" marks a problem (valid / Same Date)."""
        lowered = [h.strip().lower() for h in self.original_headers]
        return [lowered.index(name) for name in _TROUBLE_COLUMNS if name in lowered]

    @staticmethod
    def _row_is_trouble(row, trouble_cols):
        return any(0 <= c < len(row) and str(row[c]).strip().lower() == "false"
                   for c in trouble_cols)

    def _render_results_table(self, data):
        """(Re)populate the results table: **the** renderer, used by the full view and
        by the Select trouble / Show all toggle.

        A row with a problem is tinted as a **whole row** - the old version coloured
        only the two True/False cells, so a bad row was easy to scroll past."""
        table = self.results_table
        table.setSortingEnabled(False)          # never fill a sorted table
        table.setRowCount(len(data))
        table.setColumnCount(len(self.original_headers))
        table.setHorizontalHeaderLabels(self.original_headers)
        trouble_cols = self._trouble_column_indexes()

        for row_idx, row_data in enumerate(data):
            bad = self._row_is_trouble(row_data, trouble_cols)
            for col_idx, cell_data in enumerate(row_data):
                if col_idx >= len(self.original_headers):
                    continue
                item = _CheckItem(str(cell_data))
                header = self.original_headers[col_idx].strip().lower()
                if bad:
                    item.setBackground(_cell_false_bg())
                elif col_idx == 0 or header in _TROUBLE_COLUMNS:
                    # The key name and the OK verdicts stay lightly marked.
                    item.setBackground(_cell_true_bg())
                table.setItem(row_idx, col_idx, item)

        # Column widths / resize behavior
        table.resizeColumnsToContents()
        horizontal_header = table.horizontalHeader()
        if len(self.original_headers) >= 1:
            horizontal_header.setSectionResizeMode(0, QHeaderView.Interactive)
            table.setColumnWidth(0, 150)
        if len(self.original_headers) >= 2:
            horizontal_header.setSectionResizeMode(1, QHeaderView.Interactive)
            table.setColumnWidth(1, 220)
        for i in range(2, len(self.original_headers)):
            if i < len(self.original_headers) - 1:
                horizontal_header.setSectionResizeMode(i, QHeaderView.Interactive)
            else:
                horizontal_header.setSectionResizeMode(i, QHeaderView.Stretch)
        table.setSortingEnabled(True)           # click a header to sort
        self._apply_row_filter()

    # ------------------------------------------------------------- filter / jump
    def _apply_row_filter(self):
        """Hide the rows that do not contain the filter text (any column)."""
        table = self.results_table
        needle = self.filter_edit.text().strip().lower() \
            if hasattr(self, "filter_edit") else ""
        shown = 0
        for row in range(table.rowCount()):
            hit = not needle
            if needle:
                for col in range(table.columnCount()):
                    item = table.item(row, col)
                    if item is not None and needle in item.text().lower():
                        hit = True
                        break
            table.setRowHidden(row, not hit)
            shown += 1 if hit else 0
        if needle:
            self.filter_edit.setToolTip(f"{shown} of {table.rowCount()} rows match")

    def _on_row_double_clicked(self, index):
        """Jump to the settings line of the key named in this row.

        CWatM's check table starts with the settings key ("Name" column,
        cwatm/management_modules/checks.py), so a result can be traced straight back
        to the line that caused it."""
        if not index.isValid():
            return
        item = self.results_table.item(index.row(), 0)
        key = item.text().strip() if item is not None else ""
        if not key:
            return
        editor = getattr(self.parent_window, "text_area", None)
        if editor is None:
            return
        want = key.lower()
        for row, line in enumerate(editor.toPlainText().split('\n')):
            s = line.strip()
            if not s or s[0] in '#;[':
                continue
            eq = s.find('=')
            if eq > 0 and s[:eq].strip().lower() == want:
                block = editor.document().findBlockByNumber(row)
                if block.isValid():
                    editor.setTextCursor(QTextCursor(block))
                    try:
                        editor.reveal_cursor()
                    except Exception:
                        log.debug("reveal_cursor failed", exc_info=True)
                    editor.ensureCursorVisible()
                self._log(f"→ settings line {row + 1}: {s}")
                return
        self._log(f"'{key}' is not a key in the loaded settings file.", True)

    def export_table_csv(self):
        """Write the rows currently shown (filter included) to a .csv."""
        table = self.results_table
        suggested = self.output_filename_label.text().strip() or \
            self._default_output_path()
        base, ext = os.path.splitext(suggested)
        path, _ = QFileDialog.getSaveFileName(
            self, "Export check results", f"{base}_shown{ext or '.csv'}",
            "CSV Files (*.csv);;All Files (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(",".join(f'"{h}"' for h in self.original_headers) + "\n")
                for row in range(table.rowCount()):
                    if table.isRowHidden(row):
                        continue
                    cells = []
                    for col in range(table.columnCount()):
                        item = table.item(row, col)
                        cells.append('"%s"' % (item.text().replace('"', '""')
                                               if item else ""))
                    f.write(",".join(cells) + "\n")
        except Exception as e:  # noqa: BLE001
            self._log(f"Export failed: {e}", True)
            QMessageBox.warning(self, "Export CSV", f"Could not write the file:\n{e}")
            return
        self._log(f"Exported to {path}")

    def copy_table_to_clipboard(self):
        """Copy the current table data to clipboard in CSV format"""
        try:
            # Get current table data (either original or filtered)
            row_count = self.results_table.rowCount()
            col_count = self.results_table.columnCount()
            
            if row_count == 0 or col_count == 0:
                self._log("No table data to copy")
                return
            
            # Build CSV content starting with headers
            csv_content = []
            
            # Add headers
            headers = []
            for col in range(col_count):
                header_item = self.results_table.horizontalHeaderItem(col)
                if header_item:
                    headers.append(header_item.text())
                else:
                    headers.append(f"Column {col + 1}")
            csv_content.append(",".join(f'"{header}"' for header in headers))
            
            # Add data rows (what is on screen: a filtered-out row is not copied)
            for row in range(row_count):
                if self.results_table.isRowHidden(row):
                    continue
                row_data = []
                for col in range(col_count):
                    item = self.results_table.item(row, col)
                    if item:
                        # Escape quotes and wrap in quotes for proper CSV format
                        cell_text = item.text().replace('"', '""')
                        row_data.append(f'"{cell_text}"')
                    else:
                        row_data.append('""')
                csv_content.append(",".join(row_data))
            
            # Join all rows with newlines
            clipboard_text = "\n".join(csv_content)
            
            # Copy to clipboard
            clipboard = QApplication.clipboard()
            clipboard.setText(clipboard_text)

            self._log(f"Table copied to clipboard: {len(csv_content) - 1} rows, "
                      f"{col_count} columns")

        except Exception as e:  # noqa: BLE001
            self._log(f"Error copying table to clipboard: {e}", True)
            log.warning("copy table failed", exc_info=True)
    
    def restore_settings_from_discharge(self):
        """Open the selected discharge NetCDF in **Tools ▸ Restore settingsfile**.

        This used to write the settings file itself with
        ``for line in settings_content: settingsnew += line + "\\n"`` - but
        ``version_settingsfile`` is a single string (cwatm ``data_handling.py`` writes
        ``'\\n'.join(...)``), so that iterated **characters** and produced a file with
        one character per line. The Restore settingsfile window does it correctly and
        adds preview / compare / the input-file check, so there is one implementation
        instead of two."""
        if not self.netcdf_file_path:
            self._log("No NetCDF file selected", True)
            QMessageBox.information(self, "Restore settings",
                                    "Select a discharge NetCDF file first.")
            return
        try:
            from src.gui.widgets.restore_settings_window import (
                read_netcdf_attrs, RestoreSettingsWindow)
            attrs = read_netcdf_attrs(self.netcdf_file_path)
        except Exception as e:  # noqa: BLE001
            log.warning("reading the NetCDF metadata failed", exc_info=True)
            self._log(f"Error reading the NetCDF file: {e}", True)
            QMessageBox.warning(self, "Restore settings",
                                f"Could not read the NetCDF metadata:\n{e}")
            return
        self._log(f"Opening Restore settingsfile for "
                  f"{os.path.basename(self.netcdf_file_path)}")
        RestoreSettingsWindow(self.netcdf_file_path, attrs, self).exec()

