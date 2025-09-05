"""
Check Data Window for CWatM GUI
Provides functionality for checking CWatM configuration data and comparing outputs
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QCheckBox, QPushButton, QLineEdit, QFileDialog, 
                             QScrollArea, QWidget, QFrame, QTextEdit, QTableWidget,
                             QTableWidgetItem, QHeaderView, QApplication)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QKeySequence
import os
import sys
import re
import cwatm.run_cwatm as run_cwatm
try:
    import netCDF4
    NETCDF_AVAILABLE = True
except ImportError:
    NETCDF_AVAILABLE = False


class CheckDataWindow(QDialog):
    """Window for checking CWatM data and comparing outputs"""
    
    def __init__(self, parent=None, config_content=None):
        super().__init__(parent)
        self.config_content = config_content
        self.parent_window = parent
        self.output_file_path = "check_cwatm1.csv"
        self.netcdf_file_path = ""
        self.original_headers = []
        self.original_data = []
        
        self.setWindowTitle("Check Data")
        self.setModal(True)
        self.resize(1050, 630)  # Width same, height decreased by 30% from 900
        
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
        title_label.setStyleSheet("""
            QLabel {
                font-family: 'Segoe UI', sans-serif;
                font-weight: 700; 
                font-size: 24px; 
                color: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #2980b9, stop:1 #3498db);
                padding: 15px 0px 20px 0px;
                border-bottom: 3px solid qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #74b9ff, stop:1 #0984e3);
                margin-bottom: 20px;
            }
        """)
        left_layout.addWidget(title_label)
        
        # Description text
        description_text = QLabel(
            "With this window you can check the data of the settings file\n"
            "It will run CWatM but only analyse the data in the settings file\n\n"
        )
        description_text.setStyleSheet("""
            QLabel {
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                color: #2c3e50;
                padding: 10px 0px;
                line-height: 1.4;
            }
        """)
        left_layout.addWidget(description_text)
        
        # Output file section
        output_section_layout = QHBoxLayout()
        

        self.output_browse_button = QPushButton("Save result file as .csv")
        self.output_browse_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #ffffff, stop:1 #f1f3f4);
                border: 2px solid #e1e5e9;
                border-radius: 6px;
                color: #2c3e50;
                font-weight: 600;
                font-size: 12px;
                padding: 8px 16px;
                min-width: 80px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                border-color: #74b9ff;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #e9ecef, stop:1 #dee2e6);
                border-color: #0984e3;
            }
        """)
        self.output_browse_button.clicked.connect(self.browse_output_file)
        
        # Create filename display label
        self.output_filename_label = QLabel(self.output_file_path)
        self.output_filename_label.setStyleSheet("""
            QLabel {
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
                color: #666;
                padding: 2px 5px;
                background-color: #f8f9fa;
                border: 1px solid #e1e5e9;
                border-radius: 3px;
                margin-top: 5px;
            }
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
        separator1.setStyleSheet("QFrame { color: #e1e5e9; }")
        left_layout.addWidget(separator1)
        
        # Comparison section description
        comparison_text = QLabel(
            "It can also be used to check against an existing output\n"
            "output must be a discharge... netcdf file\n"
        )
        comparison_text.setStyleSheet("""
            QLabel {
                font-family: 'Segoe UI', sans-serif;
                font-size: 12px;
                color: #2c3e50;
                padding: 10px 0px;
                line-height: 1.4;
            }
        """)
        left_layout.addWidget(comparison_text)
        
        # NetCDF file selection
        netcdf_section_layout = QVBoxLayout()


        self.browse_button = QPushButton("Select discharge NetCDF file")
        self.browse_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #ffffff, stop:1 #f1f3f4);
                border: 2px solid #e1e5e9;
                border-radius: 6px;
                color: #2c3e50;
                font-weight: 600;
                font-size: 12px;
                padding: 8px 16px;
                min-width: 80px;
                margin-top: -10px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                border-color: #74b9ff;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #e9ecef, stop:1 #dee2e6);
                border-color: #0984e3;
            }
        """)
        self.browse_button.clicked.connect(self.browse_netcdf_file)
        
        # Create NetCDF filename display label
        self.netcdf_filename_label = QLabel("No file selected")
        self.netcdf_filename_label.setStyleSheet("""
            QLabel {
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
                color: #666;
                padding: 2px 5px;
                background-color: #f8f9fa;
                border: 1px solid #e1e5e9;
                border-radius: 3px;
                margin-top: -5px;
            }
        """)
        
        #netcdf_section_layout.addWidget(netcdf_label)
        netcdf_section_layout.addWidget(self.browse_button)
        netcdf_section_layout.addWidget(self.netcdf_filename_label)
        
        # Restore settings button
        self.restore_settings_button = QPushButton("Restore settings from discharge map")
        self.restore_settings_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #ffffff, stop:1 #f1f3f4);
                border: 2px solid #e1e5e9;
                border-radius: 6px;
                color: #2c3e50;
                font-weight: 600;
                font-size: 12px;
                padding: 8px 16px;
                min-width: 80px;
                margin-top: 5px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                border-color: #74b9ff;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #e9ecef, stop:1 #dee2e6);
                border-color: #0984e3;
            }
            QPushButton:disabled {
                background: #f8f9fa;
                border-color: #e1e5e9;
                color: #adb5bd;
            }
        """)
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
        self.close_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #ffffff, stop:1 #f1f3f4);
                border: 2px solid #e1e5e9;
                border-radius: 8px;
                color: #2c3e50;
                font-weight: 600;
                font-size: 13px;
                padding: 10px 20px;
                min-width: 100px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                border-color: #74b9ff;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #e9ecef, stop:1 #dee2e6);
                border-color: #0984e3;
            }
        """)
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
        results_label.setStyleSheet("""
            QLabel {
                font-family: 'Segoe UI', sans-serif;
                font-weight: 600; 
                font-size: 16px; 
                color: #2c3e50;
                padding: 15px 0px 20px 0px;
                border-bottom: 2px solid #e1e5e9;
                margin-bottom: 20px;
            }
        """)
        
        self.select_trouble_button = QPushButton("Select trouble")
        self.select_trouble_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #ffffff, stop:1 #f1f3f4);
                border: 2px solid #e1e5e9;
                border-radius: 6px;
                color: #2c3e50;
                font-weight: 600;
                font-size: 11px;
                padding: 4px 12px;
                min-width: 80px;
                max-height: 21px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                border-color: #74b9ff;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #e9ecef, stop:1 #dee2e6);
                border-color: #0984e3;
            }
            QPushButton:disabled {
                background: #f8f9fa;
                border-color: #e1e5e9;
                color: #adb5bd;
            }
        """)
        self.select_trouble_button.clicked.connect(self.filter_trouble_rows)
        self.select_trouble_button.setEnabled(False)  # Initially disabled
        
        self.copy_table_button = QPushButton("Copy Table")
        self.copy_table_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #ffffff, stop:1 #f1f3f4);
                border: 2px solid #e1e5e9;
                border-radius: 6px;
                color: #2c3e50;
                font-weight: 600;
                font-size: 11px;
                padding: 4px 12px;
                min-width: 80px;
                max-height: 21px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #f8f9fa, stop:1 #e9ecef);
                border-color: #74b9ff;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #e9ecef, stop:1 #dee2e6);
                border-color: #0984e3;
            }
            QPushButton:disabled {
                background: #f8f9fa;
                border-color: #e1e5e9;
                color: #adb5bd;
            }
        """)
        self.copy_table_button.clicked.connect(self.copy_table_to_clipboard)
        self.copy_table_button.setEnabled(False)  # Initially disabled
        
        label_button_layout.addWidget(results_label)
        label_button_layout.addWidget(self.select_trouble_button)
        label_button_layout.addWidget(self.copy_table_button)
        label_button_layout.addStretch()  # Push buttons to the right of label
        
        right_layout.addLayout(label_button_layout)
        
        # Results table widget 
        self.results_table = QTableWidget()

        self.results_table.setStyleSheet("""
            QTableWidget {
                border: 2px solid #e1e5e9;
                border-radius: 8px;
                gridline-color: #e1e5e9;
                selection-background-color: #74b9ff;
                selection-color: white;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10px;
            }

            QTableWidget::item:selected {
                color: white;
            }
            QHeaderView::section {
                background-color: #f8f9fa;
                border: 1px solid #e1e5e9;
                padding: 8px;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 11px;
                font-weight: 600;
                color: #2c3e50;
            }
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
        
        right_layout.addWidget(self.results_table)
        
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
            
    def run_check(self):
        """Run the data check process with CWatM"""
        try:
            # Get current values
            output_file = self.output_filename_label.text().strip()
            netcdf_file = self.netcdf_filename_label.text().strip() if self.netcdf_filename_label.text().strip() and self.netcdf_filename_label.text() != "No file selected" else None
            
            # Get settings file path from parent window's file manager
            if not hasattr(self.parent_window, 'file_manager') or not self.parent_window.file_manager.current_file_path:
                print("No configuration file loaded. Please load a settings file first.", file=sys.stderr)
                return
                
            settings_file = self.parent_window.file_manager.current_file_path
            
            # Print status to main window
            print(f"Starting CWatM data check for: {os.path.basename(settings_file)}")
            print(f"Check mode: Analysis only (-c flag)")
            if output_file:
                print(f"Output will be saved to: {output_file}")
            if netcdf_file:
                print(f"Comparison with: {os.path.basename(netcdf_file)}")
            print("-" * 50)
            
            # Run CWatM with -c flag for check mode
            print("Executing CWatM in check mode...")
            
            try:
                # Prepare arguments for CWatM
                args = ['-c']

                if netcdf_file:
                    args.append(netcdf_file)

                success, checkinfo = run_cwatm.main(settings_file, args)

                if success:
                    print("CWatM check completed successfully!")
                    
                    # Save checkinfo to file
                    #with open(output_file, 'r', encoding='utf-8') as f:
                    #    checkinfo = f.read()

                    if output_file and checkinfo:
                        try:
                            with open(output_file, 'w', encoding='utf-8') as f:
                                f.write(checkinfo)
                            print(f"Check results saved to: {output_file}")
                        except Exception as e:
                            print(f"Error saving output file: {str(e)}", file=sys.stderr)

                    # Display checkinfo as table from line 17 onward
                    if checkinfo:
                        self.display_check_results_table(checkinfo)
                    else:
                        print("No check data returned from CWatM", file=sys.stderr)
                else:
                    print("CWatM check completed with warnings or errors. See output above.", file=sys.stderr)



            except Exception as e:
                print(f"Error running CWatM check: {str(e)}", file=sys.stderr)
                print("Check the configuration file and try again.", file=sys.stderr)
                
        except Exception as e:
            print(f"Error in check data process: {str(e)}", file=sys.stderr)
    
    def display_check_results_table(self, checkinfo):
        """Display checkinfo CSV data as table, showing all lines"""
        try:
            lines = checkinfo.strip().split('\n')
            
            # Use all lines (do not skip any lines)
            table_lines = lines
            
            if not table_lines:
                print("No table data found in check results")
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
                print("No valid table data found in check results")
                return
                
            # Store original data for filtering
            self.original_headers = headers.copy()
            self.original_data = [row.copy() for row in csv_data]
                
            # Configure table
            self.results_table.setRowCount(len(csv_data))
            self.results_table.setColumnCount(len(headers))
            self.results_table.setHorizontalHeaderLabels(headers)

            #self.results_table.verticalHeader().setStyle(QtGui.QStyleFactory.create('CleanLooks'))
            
            # Use numeric row indices (default behavior)
            vertical_header = self.results_table.verticalHeader()
            vertical_header.setVisible(True)
            vertical_header.setDefaultSectionSize(25)  # Set row height
            
            # Fill table with data and apply custom formatting 
            for row_idx, row_data in enumerate(csv_data):
                
                for col_idx, cell_data in enumerate(row_data):
                    if col_idx < len(headers):  # Ensure we don't exceed column count
                        item = QTableWidgetItem(str(cell_data))

                        # Color first column light blue
                        if col_idx == 0:
                            item.setBackground(QColor("#d9eff9"))
                        
                        # Color non-numeric cells in 2nd column light red
                        if col_idx == 1:
                            cell_str = str(cell_data).strip()
                            # Check if the cell contains a number (int or float)
                            try:
                                float(cell_str)  # Try to convert to float
                                # It's a number - no special coloring
                            except ValueError:
                                # Not a number - color light red
                                item.setBackground(QColor("#d9eff9"))  #
                        
                        # Color "Same Date" column based on True/False values
                        if col_idx < len(headers) and headers[col_idx] == "Same Date":
                            cell_str = str(cell_data).strip()
                            if cell_str == "False":
                                item.setBackground(QColor("#FFB6C1"))  # Light red for False
                            elif cell_str == "True":
                                item.setBackground(QColor("#d9eff9"))  # Light blue for True
                            # No coloring for other values
                        
                        # Color "valid" column based on True/False values
                        if col_idx < len(headers) and headers[col_idx] == "valid":
                            cell_str = str(cell_data).strip()
                            if cell_str == "False":
                                item.setBackground(QColor("#FFB6C1"))  # Light red for False
                            elif cell_str == "True":
                                item.setBackground(QColor("#d9eff9"))  # Light blue for True
                            # No coloring for other values
                        
                        self.results_table.setItem(row_idx, col_idx, item)
            
            # Set column widths with special handling
            self.results_table.resizeColumnsToContents()
            
            # Configure header properties for individual columns
            horizontal_header = self.results_table.horizontalHeader()
            
            # Set fixed width for first 2 columns (non-resizable)
            if len(headers) >= 1:
                # First column (Path/Filename) - fixed width, non-resizable, 40% narrower
                horizontal_header.setSectionResizeMode(0, QHeaderView.Fixed)
                self.results_table.setColumnWidth(0, 120)  # Fixed width for first column (40% narrower than 200)
                
            if len(headers) >= 2:
                # Second column (Name/Variable/Parameter) - fixed width, non-resizable
                horizontal_header.setSectionResizeMode(1, QHeaderView.Fixed)
                self.results_table.setColumnWidth(1, 150)  # Fixed width for second column
                
            # Make remaining columns interactive (resizable)
            for i in range(2, len(headers)):
                if i < len(headers) - 1:  # All columns except last
                    horizontal_header.setSectionResizeMode(i, QHeaderView.Interactive)
                else:  # Last column stretches
                    horizontal_header.setSectionResizeMode(i, QHeaderView.Stretch)
            
            # If there are many columns, ensure horizontal scrolling works
            if len(headers) > 5:
                for i in range(len(headers) - 1):  # Don't resize last column (it stretches)
                    if i > 1:  # Don't override first 2 columns fixed width
                        self.results_table.setColumnWidth(i, max(100, self.results_table.columnWidth(i)))
            
            print(f"Check results table displayed: {len(csv_data)} rows, {len(headers)} columns")
            
            # Enable the Select trouble and Copy Table buttons now that we have valid table data
            self.select_trouble_button.setEnabled(True)
            self.copy_table_button.setEnabled(True)
            
        except Exception as e:
            print(f"Error displaying check results table: {str(e)}", file=sys.stderr)
    
    def filter_trouble_rows(self):
        """Filter table to show only rows where valid=False or Same Date=False"""
        try:
            if not self.original_headers or not self.original_data:
                print("No original data available for filtering")
                return
            
            # Find column indices for "valid" and "Same Date"
            valid_col_idx = -1
            same_date_col_idx = -1
            
            for i, header in enumerate(self.original_headers):
                if header.strip().lower() == "valid":
                    valid_col_idx = i
                elif header.strip().lower() == "same date":
                    same_date_col_idx = i
            
            # Filter rows based on criteria
            filtered_data = []
            for row in self.original_data:
                should_include = False
                
                # Check if valid column exists and is False
                if valid_col_idx >= 0 and valid_col_idx < len(row):
                    valid_value = str(row[valid_col_idx]).strip().lower()
                    if valid_value == "false":
                        should_include = True
                
                # Check if "Same Date" column exists and is False
                if same_date_col_idx >= 0 and same_date_col_idx < len(row):
                    same_date_value = str(row[same_date_col_idx]).strip().lower()
                    if same_date_value == "false":
                        should_include = True
                
                if should_include:
                    filtered_data.append(row)
            
            # Clear and reconfigure table with filtered data
            self.results_table.setRowCount(len(filtered_data))
            self.results_table.setColumnCount(len(self.original_headers))
            self.results_table.setHorizontalHeaderLabels(self.original_headers)
            
            # Fill table with filtered data and apply custom formatting
            for row_idx, row_data in enumerate(filtered_data):
                for col_idx, cell_data in enumerate(row_data):
                    if col_idx < len(self.original_headers):  # Ensure we don't exceed column count
                        item = QTableWidgetItem(str(cell_data))

                        # Color first column light blue
                        if col_idx == 0:
                            item.setBackground(QColor("#d9eff9"))
                        
                        # Color non-numeric cells in 2nd column light red
                        if col_idx == 1:
                            cell_str = str(cell_data).strip()
                            # Check if the cell contains a number (int or float)
                            try:
                                float(cell_str)  # Try to convert to float
                                # It's a number - no special coloring
                            except ValueError:
                                # Not a number - color light red
                                item.setBackground(QColor("#d9eff9"))
                        
                        # Color "Same Date" column based on True/False values
                        if col_idx < len(self.original_headers) and self.original_headers[col_idx] == "Same Date":
                            cell_str = str(cell_data).strip()
                            if cell_str == "False":
                                item.setBackground(QColor("#FFB6C1"))  # Light red for False
                            elif cell_str == "True":
                                item.setBackground(QColor("#d9eff9"))  # Light blue for True
                            # No coloring for other values
                        
                        # Color "valid" column based on True/False values
                        if col_idx < len(self.original_headers) and self.original_headers[col_idx] == "valid":
                            cell_str = str(cell_data).strip()
                            if cell_str == "False":
                                item.setBackground(QColor("#FFB6C1"))  # Light red for False
                            elif cell_str == "True":
                                item.setBackground(QColor("#d9eff9"))  # Light blue for True
                            # No coloring for other values
                        
                        self.results_table.setItem(row_idx, col_idx, item)
            
            # Set column widths with special handling
            self.results_table.resizeColumnsToContents()
            
            # Configure header properties for individual columns
            horizontal_header = self.results_table.horizontalHeader()
            
            # Set fixed width for first 2 columns (non-resizable)
            if len(self.original_headers) >= 1:
                # First column (Path/Filename) - fixed width, non-resizable, 40% narrower
                horizontal_header.setSectionResizeMode(0, QHeaderView.Fixed)
                self.results_table.setColumnWidth(0, 120)  # Fixed width for first column (40% narrower than 200)
                
            if len(self.original_headers) >= 2:
                # Second column (Name/Variable/Parameter) - fixed width, non-resizable
                horizontal_header.setSectionResizeMode(1, QHeaderView.Fixed)
                self.results_table.setColumnWidth(1, 150)  # Fixed width for second column
                
            # Make remaining columns interactive (resizable)
            for i in range(2, len(self.original_headers)):
                if i < len(self.original_headers) - 1:  # All columns except last
                    horizontal_header.setSectionResizeMode(i, QHeaderView.Interactive)
                else:  # Last column stretches
                    horizontal_header.setSectionResizeMode(i, QHeaderView.Stretch)
            
            print(f"Filtered trouble rows: {len(filtered_data)} rows displayed (from {len(self.original_data)} total)")
            
        except Exception as e:
            print(f"Error filtering trouble rows: {str(e)}", file=sys.stderr)
    
    def copy_table_to_clipboard(self):
        """Copy the current table data to clipboard in CSV format"""
        try:
            # Get current table data (either original or filtered)
            row_count = self.results_table.rowCount()
            col_count = self.results_table.columnCount()
            
            if row_count == 0 or col_count == 0:
                print("No table data to copy")
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
            
            # Add data rows
            for row in range(row_count):
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
            
            print(f"Table copied to clipboard: {row_count} rows, {col_count} columns")
            
        except Exception as e:
            print(f"Error copying table to clipboard: {str(e)}", file=sys.stderr)
    
    def restore_settings_from_discharge(self):
        """Restore settings from discharge NetCDF file's global attributes"""
        try:
            if not NETCDF_AVAILABLE:
                print("NetCDF4 library not available. Cannot read NetCDF files.", file=sys.stderr)
                return
                
            if not self.netcdf_file_path or self.netcdf_filename_label.text() == "No file selected":
                print("No NetCDF file selected", file=sys.stderr)
                return
            
            # Default filename for restore settings
            default_filename = "settings_restore_dischargenc.ini"
            
            # Open save dialog to select where to save the restored settings
            save_path, _ = QFileDialog.getSaveFileName(
                self, "Save Restored Settings As", default_filename,
                "INI Files (*.ini);;All Files (*)"
            )
            
            if not save_path:
                print("Settings restore cancelled")
                return
            
            # Open NetCDF file and read global attribute
            try:
                with netCDF4.Dataset(self.netcdf_file_path, 'r') as nc_file:
                    if hasattr(nc_file, 'version_settingsfile'):
                        settings_content = getattr(nc_file, 'version_settingsfile')

                        settingsnew = ""
                        for line in settings_content:
                            settingsnew += line +"\n"

                        # Save the settings content as ASCII UTF-8 file
                        with open(save_path, 'w', encoding='utf-8') as settings_file:
                            settings_file.write(settingsnew)
                        
                        print(f"Settings restored successfully from discharge NetCDF file")
                        print(f"Restored settings saved to: {save_path}")
                        
                    else:
                        print("No 'version_settingsfile' global attribute found in NetCDF file", file=sys.stderr)
                        
            except Exception as e:
                print(f"Error reading NetCDF file: {str(e)}", file=sys.stderr)
                return
                
        except Exception as e:
            print(f"Error restoring settings from discharge map: {str(e)}", file=sys.stderr)
    
