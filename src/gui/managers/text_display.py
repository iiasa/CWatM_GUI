"""
Text display management for CWatM GUI
Handles text area operations and cursor positioning.

Since the §3.2 editor refactor the settings editor (SettingsEditor,
a QPlainTextEdit) holds the file as PLAIN TEXT at all times - there is no
formatted/HTML mode any more, so getting the content is simply toPlainText().
"""

from PySide6.QtGui import QTextCursor


class TextDisplayManager:
    """Manages the settings editor text area and cursor operations."""

    def __init__(self, text_widget):
        self.text_area = text_widget
        self.original_content = ""  # Last programmatically applied content

    def set_plain_content(self, content):
        """Set plain text content"""
        self.text_area.setPlainText(content)
        self.original_content = content

    def get_content(self):
        """Get current text content (the document is always plain text)."""
        return self.text_area.toPlainText()

    def set_original_content(self, content):
        """Set the original content reference"""
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
