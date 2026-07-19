"""
Output box handling for the CWatM GUI main window.

Extracted verbatim from main_window.py: queues the redirected CWatM prints and
appends them to the read-only QPlainTextEdit output box (throttled, with '\r'
progress lines overwriting in place and errors in dark red), writes the run-log
file, and provides the copy actions. Mixed into CWatMMainWindow - all state lives
on the main window instance.
"""

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QTextCursor, QTextCharFormat, QColor

from src.gui.utils.gui_log import get_logger

log = get_logger("output_box")


class OutputBoxMixin:
    """CWatM output box: throttled appends, progress-line overwrite, copy actions."""

    def _show_cwatminfo_menu(self, pos):
        """Right-click menu for the CWatM output: the standard actions (Copy /
        Select All) plus "Copy all output"."""
        menu = self.cwatminfo_box.createStandardContextMenu()
        menu.addSeparator()
        copy_all = menu.addAction("Copy all output")
        copy_all.triggered.connect(self.copy_cwatminfo_to_clipboard)
        menu.exec(self.cwatminfo_box.mapToGlobal(pos))

    def copy_cwatminfo_to_clipboard(self):
        """Copy the full CWatM output to the clipboard as plain text."""
        self._flush_cwatminfo_display()  # include lines still queued for display
        QApplication.clipboard().setText(self.cwatminfo_box.toPlainText())

    def append_to_cwatminfo(self, text, is_error=False):
        """Queue a printed line for the output box (and write it to the run-log file).
        The box itself is updated by the ~150 ms throttle timer."""
        if not text.strip():  # Only add non-empty text
            return
        # CWatM prints per-timestep progress (date + discharge) with a leading
        # carriage return and end='' (see output.py), so a console overwrites a
        # single line in place. Mirror that: a '\r' line replaces the previous
        # progress line instead of accumulating a new line each timestep.
        is_progress = text.lstrip(' \t').startswith('\r')

        # Feed the live discharge sparkline from the same per-timestep progress line
        # (date + discharge). Guarded so a missing widget / odd line never breaks output.
        if is_progress:
            spark = getattr(self, "discharge_sparkline", None)
            if spark is not None:
                try:
                    spark.add_from_progress_line(text)
                except Exception:
                    log.debug("sparkline feed failed", exc_info=True)

        # Filter out "Worker:" messages
        text_stripped = text.strip()
        if text_stripped.startswith("Worker:"):
            return  # Skip this message

        # Write to the run-log file through the handle opened at run start; flushed
        # by the throttle timer, not per line (slow on network shares).
        if self._output_file_handle is not None:
            try:
                self._output_file_handle.write(text_stripped + '\n')
            except Exception as e:
                print(f"Error writing to output file: {e}")
                self._close_output_file_handle()
                self.output_file_path = None  # Disable file writing on error

        # Queue for display; coalesce consecutive progress lines so only the newest
        # one is rendered.
        if is_progress and self._pending_output and self._pending_output[-1][2]:
            self._pending_output[-1] = (text_stripped, is_error, True)
        else:
            self._pending_output.append((text_stripped, is_error, is_progress))
        if not self._display_timer.isActive():
            self._display_timer.start()

    def _flush_cwatminfo_display(self):
        """Throttled update of the output box: append the queued lines, and go idle
        (stop the timer) when there is nothing new."""
        if self._pending_output:
            pending, self._pending_output = self._pending_output, []
            self.update_cwatminfo_display(pending)
            # Push buffered run-log lines to disk once per flush
            if self._output_file_handle is not None:
                try:
                    self._output_file_handle.flush()
                except Exception:
                    log.debug("run-log flush failed", exc_info=True)
        else:
            self._display_timer.stop()

    def update_cwatminfo_display(self, pending):
        """Append the queued (text, is_error, is_progress) lines to the output box.
        A progress line overwrites the previous progress line in place (like '\\r' on
        a console); error lines are shown in dark red."""
        box = self.cwatminfo_box
        scroll_bar = box.verticalScrollBar()
        # Auto-scroll to the bottom only if we were already at/near the bottom, so the
        # view stays stable while the user is reading earlier entries.
        was_at_bottom = scroll_bar.value() >= scroll_bar.maximum() - 10

        from src.gui.utils import theme
        normal_fmt = QTextCharFormat()
        normal_fmt.setForeground(theme.qcolor("out_text"))
        error_fmt = QTextCharFormat()
        error_fmt.setForeground(theme.qcolor("out_error"))

        cursor = QTextCursor(box.document())
        cursor.beginEditBlock()
        try:
            for text, is_error, is_progress in pending:
                cursor.movePosition(QTextCursor.End)
                if is_progress and self._last_was_progress:
                    # Overwrite the previous progress line in place
                    cursor.movePosition(QTextCursor.StartOfBlock, QTextCursor.KeepAnchor)
                    cursor.removeSelectedText()
                elif box.document().characterCount() > 1:
                    cursor.insertBlock()
                cursor.insertText(text, error_fmt if is_error else normal_fmt)
                self._last_was_progress = is_progress
        finally:
            cursor.endEditBlock()

        if was_at_bottom:
            scroll_bar.setValue(scroll_bar.maximum())