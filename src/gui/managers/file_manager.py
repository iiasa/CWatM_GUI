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
        
    def choose_load_path(self):
        """Ask for a settings file and return its path ('' when cancelled).

        Split out of load_file so the caller can run its checks - the
        duplicate-tab guard (one settings file must never be open in two tabs) -
        *before* anything is read or the current file path is replaced.
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self.parent, "Load Configuration File", "",
            "INI Files (*.ini);;Text Files (*.txt);;All Files (*)"
        )
        return file_path

    def choose_save_path(self):
        """Ask where to save ('' when cancelled) - same split as choose_load_path,
        so Save As can be checked against the other tabs before it writes."""
        file_path, _ = QFileDialog.getSaveFileName(
            self.parent, "Save File As", "",
            "INI Files (*.ini);;Text Files (*.txt);;All Files (*)"
        )
        return file_path

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
        file_path = self.choose_load_path()

        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8') as file:
                    content = file.read()
                    self.current_file_path = file_path
                    return content, os.path.basename(file_path)
            except Exception as e:
                return None, f"Error: {str(e)}"
        
        return None, None
    
    def load_file_from_path(self, file_path):
        """Load a specific configuration file by path (no dialog).

        Returns (content, filename) or (None, error message).
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()
            self.current_file_path = file_path
            return content, os.path.basename(file_path)
        except Exception as e:
            return None, f"Error: {str(e)}"

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
    
    def save_as_file(self, content, file_path=None):
        """Save content to a new file (asking for the path when none is given -
        main_window passes one it has already checked against the other tabs)."""
        if file_path is None:
            file_path = self.choose_save_path()

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