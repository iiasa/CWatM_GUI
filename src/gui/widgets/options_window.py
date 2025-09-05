"""
Options Window for CWatM GUI
Manages boolean options from the [Options] section of configuration files
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                             QCheckBox, QPushButton, QScrollArea, QWidget, QFrame)
from PySide6.QtCore import Qt
import re


class OptionsWindow(QDialog):
    """Window for managing boolean options from [Options] section"""
    
    def __init__(self, parent=None, config_content=None):
        super().__init__(parent)
        self.config_content = config_content
        self.parent_window = parent
        self.checkboxes = {}  # Dictionary to store checkboxes by option name
        self.options_data = {}  # Dictionary to store parsed options
        
        self.setWindowTitle("Configuration Options")
        self.setModal(True)
        self.resize(600, 500)
        
        # Position window on the left side of the screen
        self.move(150, 100)  # Left side positioning, 100 pixels to the right
        
        self.init_ui()
        self.parse_options_section()
        self.create_option_checkboxes()
        
    def init_ui(self):
        """Initialize the user interface"""
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Title label with modern styling
        title_label = QLabel("Configuration Options")
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
                margin-bottom: 10px;
            }
        """)
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # Subtitle with modern styling
        subtitle_label = QLabel("Boolean options from the [Options] section:")
        subtitle_label.setStyleSheet("""
            QLabel {
                font-family: 'Segoe UI', sans-serif;
                font-size: 14px; 
                color: #6c757d;
                font-weight: 400;
                margin: 0px 0px 15px 0px;
                line-height: 1.4;
            }
        """)
        main_layout.addWidget(subtitle_label)
        
        # Scrollable area for options with modern styling
        scroll_area = QScrollArea()
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: 1px solid #e1e5e9;
                border-radius: 12px;
                background-color: #ffffff;
                box-shadow: 0 4px 12px rgba(0,0,0,0.05);
            }
            QScrollBar:vertical {
                background-color: #f8f9fa;
                width: 10px;
                border-radius: 5px;
                margin: 2px;
            }
            QScrollBar::handle:vertical {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #74b9ff, stop:1 #0984e3);
                border-radius: 5px;
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
        """)
        
        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("background-color: #ffffff; border-radius: 12px;")
        self.scroll_layout = QVBoxLayout(scroll_widget)
        self.scroll_layout.setSpacing(1)  # Much closer spacing
        self.scroll_layout.setContentsMargins(15, 15, 15, 15)
        
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        main_layout.addWidget(scroll_area)
        
        self.setLayout(main_layout)
    
    def parse_options_section(self):
        """Parse the [Options] section from configuration content"""
        if not self.config_content:
            return
        
        lines = self.config_content.split('\n')
        in_options_section = False
        
        for line in lines:
            line = line.strip()
            
            # Check if we're entering the [Options] section
            if line.lower() == '[options]':
                in_options_section = True
                continue
            
            # Check if we're entering a different section
            if line.startswith('[') and line.endswith(']') and line.lower() != '[options]':
                in_options_section = False
                continue
            
            # Parse options within the [Options] section
            if in_options_section and line and not line.startswith('#'):
                # Look for key = value pairs
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # Check if value is boolean (True/False case insensitive)
                    if value.lower() in ['true', 'false']:
                        self.options_data[key] = value.lower() == 'true'
    
    def create_option_checkboxes(self):
        """Create checkboxes for each boolean option"""
        if not self.options_data:
            # No boolean options found
            no_options_frame = QFrame()
            no_options_frame.setStyleSheet("""
                QFrame {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 #ffeaa7, stop:1 #fdcb6e);
                    border: none;
                    border-radius: 12px;
                    padding: 25px;
                    margin: 15px;
                    box-shadow: 0 4px 12px rgba(255, 234, 167, 0.3);
                }
            """)
            
            no_options_layout = QVBoxLayout(no_options_frame)
            no_options_label = QLabel("No boolean options found")
            no_options_label.setStyleSheet("""
                QLabel {
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 16px;
                    font-weight: 700;
                    color: #2d3436;
                    text-align: center;
                }
            """)
            no_options_label.setAlignment(Qt.AlignCenter)
            
            info_label = QLabel("The [Options] section does not contain any True/False settings.")
            info_label.setStyleSheet("""
                QLabel {
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 13px;
                    color: #636e72;
                    font-weight: 400;
                    text-align: center;
                    margin-top: 8px;
                }
            """)
            info_label.setAlignment(Qt.AlignCenter)
            
            no_options_layout.addWidget(no_options_label)
            no_options_layout.addWidget(info_label)
            
            self.scroll_layout.addWidget(no_options_frame)
            return
        
        # Create checkboxes for each option with simpler styling
        for i, (option_name, option_value) in enumerate(self.options_data.items()):
            option_layout = QHBoxLayout()
            option_layout.setContentsMargins(5, 2, 5, 2)  # Minimal margins
            option_layout.setSpacing(1)  # Compact spacing
            
            # Create checkbox with custom styling
            checkbox = QCheckBox()
            checkbox.setChecked(option_value)
            checkbox.stateChanged.connect(lambda state, name=option_name: self.on_checkbox_changed(name, state))
            checkbox.setStyleSheet("""
                QCheckBox {
                    spacing: 12px;
                    font-size: 14px;
                    font-family: 'Segoe UI', sans-serif;
                    color: #2c3e50;
                    padding: 8px;
                    border-radius: 6px;
                }
                QCheckBox:hover {
                    background-color: #f8f9fa;
                }
                QCheckBox::indicator {
                    width: 20px;
                    height: 20px;
                    border-radius: 6px;
                    border: 2px solid #e1e5e9;
                    background-color: white;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                }
                QCheckBox::indicator:hover {
                    border-color: #74b9ff;
                    box-shadow: 0 0 0 3px rgba(116, 185, 255, 0.1);
                }
                QCheckBox::indicator:checked {
                    border-color: #00b894;
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 #00b894, stop:1 #00a085);
                    image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iOSIgdmlld0JveD0iMCAwIDEyIDkiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+CjxwYXRoIGQ9Ik0xIDQuNUw0LjUgOEwxMSAxIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjIiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIvPgo8L3N2Zz4K);
                    box-shadow: 0 4px 8px rgba(0, 184, 148, 0.3);
                }
                QCheckBox::indicator:checked:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                        stop:0 #17a085, stop:1 #008a75);
                    box-shadow: 0 0 0 3px rgba(0, 184, 148, 0.2);
                }
            """)
            
            # Create label with improved styling
            label = QLabel(option_name)
            label.setStyleSheet("""
                QLabel {
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 14px;
                    font-weight: 600;
                    color: #2c3e50;
                }
            """)
            
            # Add row number for easier identification (optional)
            row_label = QLabel(f"{i+1}.")
            row_label.setStyleSheet("""
                QLabel {
                    font-family: 'Segoe UI', sans-serif;
                    font-size: 12px;
                    color: #95a5a6;
                    font-weight: 500;
                    min-width: 25px;
                }
            """)
            
            option_layout.addWidget(row_label)
            option_layout.addWidget(checkbox)
            option_layout.addWidget(label)
            option_layout.addStretch()  # Push content to left
            
            self.scroll_layout.addLayout(option_layout)
            self.checkboxes[option_name] = checkbox
        
        # Add stretch to push all options to top
        self.scroll_layout.addStretch()
    
    def on_checkbox_changed(self, option_name, state):
        """Handle checkbox state changes and update configuration immediately"""
        # Update the configuration content immediately
        self.update_single_option(option_name, state == 2)  # 2 = Qt.Checked
        
        # Update the parent window's configuration immediately
        if self.parent_window and hasattr(self.parent_window, 'text_display'):
            self.parent_window.text_display.set_original_content(self.config_content)
            
            # Color the actualize button light blue to indicate changes
            if hasattr(self.parent_window, 'on_field_changed'):
                self.parent_window.on_field_changed()
            
            # Re-parse and display the updated configuration
            if hasattr(self.parent_window, 'parse_file'):
                self.parent_window.parse_file(expand_all=False, load=False, content=self.config_content)
    
    
    def update_configuration(self):
        """Update the configuration content with new checkbox values"""
        if not self.config_content:
            return
        
        lines = self.config_content.split('\n')
        updated_lines = []
        in_options_section = False
        
        for line in lines:
            original_line = line
            line_stripped = line.strip()
            
            # Check if we're entering the [Options] section
            if line_stripped.lower() == '[options]':
                in_options_section = True
                updated_lines.append(original_line)
                continue
            
            # Check if we're entering a different section
            if line_stripped.startswith('[') and line_stripped.endswith(']') and line_stripped.lower() != '[options]':
                in_options_section = False
                updated_lines.append(original_line)
                continue
            
            # Update options within the [Options] section
            if in_options_section and line_stripped and not line_stripped.startswith('#'):
                if '=' in line_stripped:
                    key, value = line_stripped.split('=', 1)
                    key = key.strip()
                    
                    if key in self.checkboxes:
                        # Update the value based on checkbox state
                        new_value = "True" if self.checkboxes[key].isChecked() else "False"
                        # Preserve original line formatting (spaces, tabs, etc.)
                        indent = original_line[:len(original_line) - len(original_line.lstrip())]
                        updated_line = f"{indent}{key} = {new_value}"
                        updated_lines.append(updated_line)
                        continue
            
            # Keep original line if not modified
            updated_lines.append(original_line)
        
        # Update the configuration content
        self.config_content = '\n'.join(updated_lines)
    
    def update_single_option(self, option_name, is_checked):
        """Update a single option in the configuration content"""
        if not self.config_content:
            return
        
        lines = self.config_content.split('\n')
        updated_lines = []
        in_options_section = False
        
        for line in lines:
            original_line = line
            line_stripped = line.strip()
            
            # Check if we're entering the [Options] section
            if line_stripped.lower() == '[options]':
                in_options_section = True
                updated_lines.append(original_line)
                continue
            
            # Check if we're entering a different section
            if line_stripped.startswith('[') and line_stripped.endswith(']') and line_stripped.lower() != '[options]':
                in_options_section = False
                updated_lines.append(original_line)
                continue
            
            # Update the specific option within the [Options] section
            if in_options_section and line_stripped and not line_stripped.startswith('#'):
                if '=' in line_stripped:
                    key, value = line_stripped.split('=', 1)
                    key = key.strip()
                    
                    if key == option_name:
                        # Update the value based on checkbox state
                        new_value = "True" if is_checked else "False"
                        # Preserve original line formatting (spaces, tabs, etc.)
                        indent = original_line[:len(original_line) - len(original_line.lstrip())]
                        updated_line = f"{indent}{key} = {new_value}"
                        updated_lines.append(updated_line)
                        continue
            
            # Keep original line if not modified
            updated_lines.append(original_line)
        
        # Update the configuration content
        self.config_content = '\n'.join(updated_lines)