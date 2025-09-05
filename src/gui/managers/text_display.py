"""
Text display management for CWatM GUI
Handles text area operations and cursor positioning
"""

from PySide6.QtWidgets import QTextEdit
from PySide6.QtGui import QTextCursor


class TextDisplayManager:
    """Manages text display area and cursor operations"""
    
    def __init__(self, text_widget):
        self.text_area = text_widget
        self.original_content = ""  # Store original plain text content
        self.is_formatted_mode = False  # Track if we're in formatted display mode
        
    def display_formatted_content(self, formatted_lines):
        """Display formatted content in text area"""
        self.text_area.clear()
        self.is_formatted_mode = True
        
        # Join formatted lines and set as HTML
        html_content = '<br>'.join(formatted_lines)
        self.text_area.setHtml(f'<html><body>{html_content}</body></html>')
    
    def set_plain_content(self, content):
        """Set plain text content"""
        self.text_area.setPlainText(content)
        self.original_content = content
        self.is_formatted_mode = False
    
    def get_content(self):
        """Get current text content - converts HTML to plain text if needed"""
        if self.is_formatted_mode:
            # Get the HTML content and convert it to plain text
            html_content = self.text_area.toHtml()
            plain_content = self._convert_html_to_plain_text(html_content)
            return plain_content
        else:
            # If in plain text mode, return actual text content
            return self.text_area.toPlainText()
    
    def _convert_html_to_plain_text(self, html_content):
        """Convert HTML content back to plain INI format"""
        import re
        from html import unescape
        
        # Use Qt's built-in conversion first
        plain_text = self.text_area.toPlainText()
        
        # Clean up any remaining HTML artifacts and restore original format
        lines = plain_text.split('\n')
        cleaned_lines = []
        
        for line in lines:
            # Remove any expand/collapse indicators that may have been added
            if line.strip().startswith('[-]') or line.strip().startswith('[+]'):
                # Extract just the section name
                bracket_start = line.find('[', line.find('[') + 1)  # Find second [
                if bracket_start > 0:
                    line = line[bracket_start:]
            
            # Clean up any remaining HTML entities
            line = unescape(line)
            cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines)
    
    def set_original_content(self, content):
        """Set the original content reference for formatted mode"""
        self.original_content = content
    
    def jump_to_line(self, line_number):
        """Jump to a specific line number"""
        if line_number < 0:
            return
            
        cursor = self.text_area.textCursor()
        cursor.movePosition(QTextCursor.Start)
        
        for _ in range(line_number):
            cursor.movePosition(QTextCursor.Down)
        
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()
    
    def get_current_line(self):
        """Get current cursor line number"""
        return self.text_area.textCursor().blockNumber()
    
    def restore_cursor_position(self, target_line, current_block):
        """Restore cursor to appropriate position after parsing"""
        cursor = self.text_area.textCursor()
        cursor.movePosition(QTextCursor.Start)
        
        if target_line is not None:
            # Go to specific line number
            target_line = max(0, target_line)
            for _ in range(target_line):
                cursor.movePosition(QTextCursor.Down)
        else:
            # Restore to previously stored line
            current_block = max(0, current_block)
            for _ in range(current_block):
                cursor.movePosition(QTextCursor.Down)
        
        self.text_area.setTextCursor(cursor)
        self.text_area.ensureCursorVisible()
    
    def jump_to_header(self, header_name):
        """Jump to a specific header in the text"""
        content = self.get_content()
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            if line.strip() == header_name:
                self.jump_to_line(i)
                return True
        return False
    
    def clear_content(self):
        """Clear all content from text area"""
        self.text_area.clear()