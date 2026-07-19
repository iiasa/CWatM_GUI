"""
Progress Clock Widget - Custom circular progress indicator for CWatM GUI.

Provides a circular progress indicator with CWatM branding colors for
displaying model execution progress as a percentage (0-100%).
"""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPainter, QPen, QColor

from src.gui.utils import theme


class ProgressClock(QWidget):
    """Custom circular progress clock widget.
    
    A circular progress indicator that displays progress as a colored arc
    with percentage text. Uses CWatM brand colors (blue #0066CC) and
    provides smooth visual feedback for model execution progress.
    
    Attributes
    ----------
    progress_value : int
        Current progress value (0-100)
    """
    
    def __init__(self, parent=None):
        """Initialize the progress clock widget.

        Parameters
        ----------
        parent : QWidget, optional
            Parent widget, by default None
        """
        super().__init__(parent)
        self.progress_value = 0  # 0-100
        self._time_lines = []  # elapsed/remaining lines shown inside the face
        self.setFixedSize(240, 240)  # Increased by 50% (160 * 1.5)

    def setValue(self, value):
        """Set progress value and update display.

        Parameters
        ----------
        value : int or float
            Progress value, automatically clamped to 0-100 range
        """
        self.progress_value = max(0, min(100, value))
        self.update()  # Trigger repaint

    def set_time_lines(self, *lines):
        """Show up to two short text lines INSIDE the clock face, under the
        percentage - used for the run's 'elapsed' / 'remaining' times (and the
        frozen 'run time' / 'failed after' / 'stopped after' line at the end).
        Call with no arguments (or empty strings) to clear them.
        """
        self._time_lines = [str(line) for line in lines if line][:2]
        self.update()

    def paintEvent(self, event):
        """Custom paint event to draw the progress clock.
        
        Renders a circular progress indicator with light gray background
        circle and blue progress arc. Includes percentage text display.
        
        Parameters
        ----------
        event : QPaintEvent
            Paint event from Qt framework
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Get widget dimensions
        width = self.width()
        height = self.height()
        side = min(width, height)
        
        # Set up coordinate system
        painter.translate(width / 2, height / 2)
        painter.scale(side / 200.0, side / 200.0)
        
        # Draw 100% progress circle as background (light gray; darker in a dark mode)
        ring = QColor("#4a5056") if theme.is_dark() else QColor(Qt.lightGray)
        painter.setPen(QPen(ring, 12))
        painter.drawEllipse(-75, -75, 150, 150)
        
        # Calculate progress angle (0-360 degrees)
        progress_angle = (self.progress_value / 100.0) * 360
        
        # Draw progress arc (CWatM blue color: #0066CC)
        if self.progress_value > 0:
            # Theme accent (Normal: the CWatM title blue #0066CC)
            painter.setPen(QPen(theme.qcolor("clock_accent"), 12))
            painter.drawArc(-75, -75, 150, 150, 90 * 16,
                            -int(progress_angle * 16))
        
        # Draw percentage text in same blue. With time lines shown the whole
        # text block (percentage + up to two time lines) is centred in the face;
        # without them the percentage keeps its classic lower position.
        painter.setPen(QPen(theme.qcolor("clock_accent"), 1))
        painter.setFont(QFont("Arial", 14, QFont.Bold))
        text = f"{self.progress_value}%"
        text_rect = painter.fontMetrics().boundingRect(text)
        pct_baseline = -14 if self._time_lines else 40
        painter.drawText(-text_rect.width() // 2, pct_baseline, text)

        # Elapsed / remaining run time inside the face (below the percentage).
        # Small font; the lines sit near the centre so they fit the circle chord.
        if self._time_lines:
            painter.setPen(QPen(theme.qcolor("clock_text"), 1))
            painter.setFont(QFont("Arial", 10))
            fm = painter.fontMetrics()
            y = 10
            for line in self._time_lines:
                painter.drawText(-fm.horizontalAdvance(line) // 2, y, line)
                y += 22