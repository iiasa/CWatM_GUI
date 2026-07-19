"""Line-number gutter for the settings editor.

A slim sibling widget placed left of the SettingsEditor (QPlainTextEdit) that
paints the **file line number** of each visible block - numbers jump across a
folded section, showing how many lines are hidden - plus a ▾ / ▸ fold marker on
section header lines and an orange dot on bookmarked lines. Clicking a header's
row in the gutter toggles that section's fold; clicking any other row toggles a
bookmark on that line.
"""

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPainter, QColor, QFont

from src.gui.utils.gui_log import get_logger
from src.gui.utils import theme
from src.gui.widgets.settings_editor import is_section_header

log = get_logger("line_number_gutter")


class LineNumberGutter(QWidget):
    """Paints block numbers + fold markers next to a SettingsEditor."""

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self._editor = editor
        self.setFixedWidth(62)
        self.setCursor(Qt.PointingHandCursor)
        # Repaint whenever the editor scrolls, edits, folds or bookmarks change
        editor.verticalScrollBar().valueChanged.connect(lambda *_: self.update())
        editor.textChanged.connect(self.update)
        editor.cursorPositionChanged.connect(self.update)
        editor.foldingChanged.connect(self.update)
        editor.bookmarksChanged.connect(self.update)

    def _top_offset(self):
        """Vertical offset of the editor's viewport (frame + stylesheet padding),
        so the numbers line up with the text."""
        return self._editor.viewport().mapTo(self._editor, QPoint(0, 0)).y()

    def _visible_blocks(self):
        """Yield (block, top_y, height) for the blocks visible in the viewport,
        in this widget's coordinates."""
        editor = self._editor
        top = self._top_offset()
        block = editor.firstVisibleBlock()
        offset = editor.contentOffset()
        height = self.height()
        while block.isValid():
            geo = editor.blockBoundingGeometry(block).translated(offset)
            y = geo.top() + top
            if y > height:
                break
            if block.isVisible() and geo.bottom() + top >= 0:
                yield block, y, geo.height()
            block = block.next()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), theme.qcolor("gutter_bg"))
            font = QFont(self._editor.font())
            font.setPointSizeF(max(7.0, font.pointSizeF() - 1))
            painter.setFont(font)
            for block, y, h in self._visible_blocks():
                text = block.text()
                # Bookmark: filled orange dot at the far left
                if self._editor.is_bookmarked(block):
                    d = 8
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(theme.qcolor("bookmark"))
                    painter.drawEllipse(3, int(y + (h - d) / 2), d, d)
                    painter.setBrush(Qt.NoBrush)
                if is_section_header(text):
                    # Fold marker: ▾ expanded, ▸ folded (hidden lines follow)
                    folded = self._editor.is_folded(text.strip())
                    painter.setPen(theme.qcolor("fold_marker"))
                    painter.drawText(14, int(y), 12, int(h),
                                     Qt.AlignLeft | Qt.AlignTop,
                                     "▸" if folded else "▾")
                painter.setPen(theme.qcolor("gutter_num"))
                painter.drawText(0, int(y), self.width() - 6, int(h),
                                 Qt.AlignRight | Qt.AlignTop,
                                 str(block.blockNumber() + 1))
        except Exception:
            log.debug("gutter paint failed", exc_info=True)
        finally:
            painter.end()

    def mousePressEvent(self, event):
        """Clicking a section header's gutter row toggles its fold; clicking any
        other row (on the line number) toggles a bookmark on that line."""
        try:
            y = event.pos().y()
            for block, top, h in self._visible_blocks():
                if top <= y <= top + h:
                    if is_section_header(block.text()):
                        self._editor.toggle_block_section(block)
                    else:
                        self._editor.toggle_bookmark_block(block)
                    break
        except Exception:
            log.debug("gutter click failed", exc_info=True)
        super().mousePressEvent(event)
