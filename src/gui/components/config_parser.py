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
                elif key_clean == 'gauges':
                    self.settings_values['gauges'] = value_clean

        return self.date_values, self.settings_values
    
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
                
                if key_clean in ['pathout', 'maskmap', 'gauges']:
                    current_values[key_clean] = value_clean
                    
        return current_values