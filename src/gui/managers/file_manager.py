"""
File management for CWatM GUI.

Handles file I/O operations, loading, and saving configuration files.
Provides methods for loading INI files, saving content, and managing
current file paths.
"""

from PySide6.QtWidgets import QFileDialog
import os


class FileManager:
    """Manages file operations for the CWatM GUI.
    
    This class handles all file I/O operations including loading
    configuration files, saving content, and managing file paths.
    
    Attributes
    ----------
    parent : QWidget
        Parent window for dialog operations
    current_file_path : str or None
        Path to the currently loaded file
    """
    
    def __init__(self, parent_window):
        """Initialize the file manager.
        
        Parameters
        ----------
        parent_window : QWidget
            Parent window for file dialogs
        """
        self.parent = parent_window
        self.current_file_path = None
        
    def load_file(self):
        """Load a configuration file through file dialog.
        
        Opens a file dialog to select an INI configuration file,
        reads the content, and updates the current file path.
        
        Returns
        -------
        tuple
            (content, filename) where content is file content string
            or None if failed, and filename is the base filename or
            error message
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self.parent, "Load Configuration File", "", 
            "INI Files (*.ini);;Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as file:
                    content = file.read()
                    self.current_file_path = file_path
                    return content, os.path.basename(file_path)
            except Exception as e:
                return None, f"Error: {str(e)}"
        
        return None, None
    
    def save_file(self, content, file_path=None):
        """Save content to file"""
        target_path = file_path or self.current_file_path
        
        if not target_path:
            return False, "No file path specified"
            
        try:
            with open(target_path, 'w', encoding='utf-8') as file:
                file.write(content)
            return True, f"File saved: {target_path}"
        except Exception as e:
            return False, f"Error saving file: {str(e)}"
    
    def save_as_file(self, content):
        """Save content to a new file"""
        file_path, _ = QFileDialog.getSaveFileName(
            self.parent, "Save File As", "", 
            "INI Files (*.ini);;Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            success, message = self.save_file(content, file_path)
            if success:
                self.current_file_path = file_path
                return True, os.path.basename(file_path), message
            else:
                return False, None, message
        
        return False, None, "Save cancelled"
    
    def get_current_file_path(self):
        """Get the currently loaded file path"""
        return self.current_file_path
    
    def get_current_filename(self):
        """Get the currently loaded filename"""
        if self.current_file_path:
            return os.path.basename(self.current_file_path)
        return None
    
    def has_file_loaded(self):
        """Check if a file is currently loaded"""
        return self.current_file_path is not None