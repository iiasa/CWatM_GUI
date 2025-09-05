"""
Configuration file parser for CWatM GUI.

Handles INI file parsing, validation, and formatting with syntax highlighting.
Provides methods for extracting configuration parameters, formatting content
for display, and updating configuration values.
"""

from PySide6.QtCore import QDate
import re


class ConfigParser:
    """Handles parsing and manipulation of CWatM configuration files.
    
    This class provides functionality for parsing INI configuration files,
    extracting date values and settings, formatting content with HTML styling
    for display, and updating configuration parameters.
    
    Attributes
    ----------
    current_content : str
        The raw content of the configuration file
    date_values : dict
        Extracted date values (stepstart, spinup, stepend)
    settings_values : dict
        Extracted settings (pathout, maskmap, etc.)
    """
    
    def __init__(self):
        """Initialize the configuration parser.
        
        Sets up empty containers for content, date values, and settings.
        """
        self.current_content = ""
        self.date_values = {}
        self.settings_values = {}
        
    def parse_content(self, content):
        """Parse INI file content and extract date values and settings.
        
        Processes the raw configuration file content to extract date parameters
        (StepStart, SpinUp, StepEnd) and settings (PathOut, MaskMap).
        
        Parameters
        ----------
        content : str
            Raw INI file content to parse
            
        Returns
        -------
        tuple
            (date_values dict, settings_values dict)
        """
        self.current_content = content
        self.date_values = {}
        self.settings_values = {}
        
        lines = content.split('\n')
        for line in lines:
            line_stripped = line.strip()
            if '=' in line and not line_stripped.startswith('#') and not line_stripped.startswith(';'):
                key, value = line.split('=', 1)
                key_clean = key.strip().lower()
                value_clean = value.strip()
                
                if key_clean in ['stepstart', 'spinup', 'stepend']:
                    self.date_values[key_clean] = value_clean
                elif key_clean == 'pathout':
                    self.settings_values['pathout'] = value_clean
                elif key_clean == 'maskmap':
                    self.settings_values['maskmap'] = value_clean
                    
        return self.date_values, self.settings_values
    
    def format_content_for_display(self, content):
        """Format content with HTML styling for display"""
        formatted_lines = []
        
        for line in content.split('\n'):
            line_stripped = line.strip()
            
            if line_stripped.startswith('[') and line_stripped.endswith(']'):
                # Section headers in bold
                formatted_lines.append(f'<span style="font-weight: bold;">{line}</span>')
            elif '=' in line and not line_stripped.startswith('#') and not line_stripped.startswith(';'):
                # Key-value pairs with styling
                key, value = line.split('=', 1)
                key_clean = key.strip()
                value_clean = value.strip()
                
                if value_clean.lower() == 'true':
                    formatted_line = f'<span style="color: black;">{key}= </span><span style="color: blue; font-weight: bold;">True</span>'
                elif value_clean.lower() == 'false':
                    formatted_line = f'<span style="color: black;">{key}= </span><span style="color: red; font-weight: bold;">False</span>'
                else:
                    formatted_line = f'{key}= {value.strip()}'
                
                formatted_lines.append(formatted_line)
            elif line_stripped.startswith('#'):
                # Comments in light gray with preserved whitespace
                preserved_line = line.replace(' ', '&nbsp;').replace('\t', '&nbsp;&nbsp;&nbsp;&nbsp;')
                formatted_lines.append(f'<span style="color: darkgray;">{preserved_line}</span>')
            elif line_stripped and not line_stripped.startswith(';'):
                formatted_lines.append(f"Note: {line}")
            else:
                # Preserve empty lines
                formatted_lines.append(line)
                
        return formatted_lines
    
    def update_dates(self, content, start_date, spin_date, end_date):
        """Update date values in content"""
        start_date_str = start_date.toString("dd/MM/yyyy")
        spin_date_str = spin_date.toString("dd/MM/yyyy")
        end_date_str = end_date.toString("dd/MM/yyyy")
        
        lines = content.split('\n')
        updated_lines = []
        
        for line in lines:
            line_stripped = line.strip()
            if '=' in line and not line_stripped.startswith('#') and not line_stripped.startswith(';'):
                key, value = line.split('=', 1)
                key_clean = key.strip().lower()
                
                if key_clean == 'stepstart':
                    updated_lines.append(f"{key}= {start_date_str}")
                elif key_clean == 'spinup':
                    updated_lines.append(f"{key}= {spin_date_str}")
                elif key_clean == 'stepend':
                    updated_lines.append(f"{key}= {end_date_str}")
                else:
                    updated_lines.append(line)
            else:
                updated_lines.append(line)
                
        return '\n'.join(updated_lines)
    
    def update_settings(self, content, settings_dict):
        """Update settings values in content"""
        lines = content.split('\n')
        updated_lines = []
        
        for line in lines:
            line_stripped = line.strip()
            if '=' in line and not line_stripped.startswith('#') and not line_stripped.startswith(';'):
                key, value = line.split('=', 1)
                key_clean = key.strip().lower()
                
                # Check if this key is in our settings to update
                if key_clean in settings_dict:
                    updated_lines.append(f"{key}= {settings_dict[key_clean]}")
                else:
                    updated_lines.append(line)
            else:
                updated_lines.append(line)
                
        return '\n'.join(updated_lines)
    
    def parse_date_value(self, date_string):
        """Parse date string with multiple format support"""
        if not date_string:
            return None
            
        date_formats = [
            "dd/MM/yyyy", "d/MM/yyyy", "dd/M/yyyy", "d/M/yyyy", 
            "yyyy-MM-dd", "yyyy-M-dd", "yyyy-MM-d", "yyyy-M-d"
        ]
        
        for fmt in date_formats:
            date_obj = QDate.fromString(date_string, fmt)
            if date_obj.isValid():
                return date_obj
                
        return None
    
    def find_parameter_line(self, content, parameter_name):
        """Find line number of a specific parameter"""
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            if '=' in line and not line.strip().startswith('#') and not line.strip().startswith(';'):
                key, value = line.split('=', 1)
                key_clean = key.strip().lower()
                
                if key_clean == parameter_name.lower():
                    return i
        return -1
    
    def get_current_date_values(self, content):
        """Extract current date values from content"""
        current_values = {}
        lines = content.split('\n')
        
        for line in lines:
            line_stripped = line.strip()
            if '=' in line and not line_stripped.startswith('#') and not line_stripped.startswith(';'):
                key, value = line.split('=', 1)
                key_clean = key.strip().lower()
                value_clean = value.strip()
                
                if key_clean in ['stepstart', 'spinup', 'stepend']:
                    current_values[key_clean] = value_clean
                    
        return current_values
    
    def get_current_settings_values(self, content):
        """Extract current settings values from content"""
        current_values = {}
        lines = content.split('\n')
        
        for line in lines:
            line_stripped = line.strip()
            if '=' in line and not line_stripped.startswith('#') and not line_stripped.startswith(';'):
                key, value = line.split('=', 1)
                key_clean = key.strip().lower()
                value_clean = value.strip()
                
                if key_clean in ['pathout', 'maskmap']:
                    current_values[key_clean] = value_clean
                    
        return current_values