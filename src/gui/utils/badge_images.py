"""River badge images for the CWatM account (``assets/badges/<badge code>.png``).

A badge image is a round medal on a square background (white or dark, sometimes with
a generator watermark in a corner), and the medal fills a different share of the
square in every image. ``badge_pixmap`` therefore finds the medal itself: along the
middle row and the middle column it looks for the first and last pixel that differs
from the corner colour, crops to that square and clips it to a circle - so the badge
reads the same on the Normal, Dark and Mikhail themes and a new image needs no
per-file setup. A badge without an image returns None (callers fall back to 🏅 + the
name). A new river = a PNG named after its ``badges.code``.
"""

import os

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPainterPath, QPixmap

from src.gui.utils.assets import asset_path
from src.gui.utils.gui_log import get_logger

log = get_logger("badge_images")

_THRESHOLD = 40          # colour distance that counts as "not background"
_cache = {}


def badge_image_path(code):
    """The image file of a badge, or None when there is none."""
    if not code:
        return None
    path = asset_path("badges", f"{code}.png")
    return path if os.path.exists(path) else None


def _medal_rect(img):
    """The square around the medal inside ``img`` (the whole image if not found)."""
    w, h = img.width(), img.height()
    bg = img.pixelColor(2, 2)

    def differs(x, y):
        c = img.pixelColor(x, y)
        return (abs(c.red() - bg.red()) + abs(c.green() - bg.green())
                + abs(c.blue() - bg.blue())) > _THRESHOLD

    xs = [x for x in range(w) if differs(x, h // 2)]
    ys = [y for y in range(h) if differs(w // 2, y)]
    if not xs or not ys:
        return QRect(0, 0, w, h)
    left, right, top, bottom = xs[0], xs[-1], ys[0], ys[-1]
    side = max(right - left, bottom - top) + 1
    cx, cy = (left + right) / 2.0, (top + bottom) / 2.0
    return QRect(int(round(cx - side / 2.0)), int(round(cy - side / 2.0)), side, side)


def badge_pixmap(code, size, faded=False, dpr=1.0):
    """The badge as a round ``size``×``size`` pixmap (logical px), or None.

    ``faded`` draws it at low opacity (a badge not earned yet); ``dpr`` = the
    widget's devicePixelRatio, so it stays sharp on a scaled screen."""
    key = (code, int(size), bool(faded), round(float(dpr), 2))
    if key in _cache:
        return _cache[key]
    path = badge_image_path(code)
    pix = None
    if path:
        img = QImage(path)
        if img.isNull():
            log.warning("badge image unreadable: %s", path)
        else:
            img = img.convertToFormat(QImage.Format_ARGB32)
            src = _medal_rect(img)
            px = max(1, int(round(size * dpr)))
            pix = QPixmap(px, px)
            pix.fill(Qt.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            clip = QPainterPath()
            clip.addEllipse(QRectF(0.5, 0.5, px - 1, px - 1))
            p.setClipPath(clip)
            if faded:
                p.setOpacity(0.3)
            p.drawImage(QRectF(0, 0, px, px), img, QRectF(src))
            p.end()
            pix.setDevicePixelRatio(dpr)
    _cache[key] = pix
    return pix
