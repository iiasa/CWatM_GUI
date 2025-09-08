"""
Progress Clock Widget - Custom circular progress indicator for CWatM GUI.

Provides a circular progress indicator with CWatM branding colors for
displaying model execution progress as a percentage (0-100%).
"""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPainter, QPen, QColor


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
        
        # Draw 100% progress circle in light gray as background
        painter.setPen(QPen(Qt.lightGray, 12))
        painter.drawEllipse(-75, -75, 150, 150)
        
        # Calculate progress angle (0-360 degrees)
        progress_angle = (self.progress_value / 100.0) * 360
        
        # Draw progress arc (CWatM blue color: #0066CC)
        if self.progress_value > 0:
            # Same blue as CWatM GUI title
            painter.setPen(QPen(QColor("#0066CC"), 12))
            painter.drawArc(-75, -75, 150, 150, 90 * 16,
                            -int(progress_angle * 16))
        
        # Draw percentage text in same blue
        # Same blue as title
        painter.setPen(QPen(QColor("#0066CC"), 1))
        painter.setFont(QFont("Arial", 14, QFont.Bold))
        text = f"{self.progress_value}%"
        text_rect = painter.fontMetrics().boundingRect(text)
        painter.drawText(-text_rect.width() // 2, 40, text)