"""
Live discharge sparkline for the CWatM GUI main window.

A lightweight custom-painted widget (no Plotly / QtWebEngine, so it stays out of the
fast-startup budget and off the hot path) that plots the discharge value as it streams
in during a run. It sits next to the progress clock and shows a **rolling ~3-month
window** of the most recent timesteps; older points **fade out** (lower opacity the
further back in time they are) so the eye follows the recent trend.

Fed from ``OutputBoxMixin.append_to_cwatminfo`` (the same '\\r' progress line the
output box overwrites in place) via ``add_from_progress_line`` — no extra plumbing
from the model side. Cleared at the start of every run.
"""

import math
import random
from datetime import datetime, timedelta

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QSize, QPointF, QRectF, QTimer, QSettings
from PySide6.QtGui import QPainter, QPen, QColor, QFont

from src.gui.utils import theme

# Selectable cameo animals (Configure ▸ Select animal) — name -> side-view emoji.
# All face left by default, so the draw code flips them to face forward in time.
ANIMALS = [
    ("Fish",       "\U0001F41F"),       # 🐟
    ("Otter",      "\U0001F9A6"),      # 🦦
    ("Beaver",     "\U0001F9AB"),  #
    ("Sailboat",   "\U000026F5"),       #
    ("Octopus (for Carla)", "\U0001F419"),   # 🐙
]
_ANIMAL_EMOJI = dict(ANIMALS)
_DEFAULT_ANIMAL = "Fish"     # also the fallback for a stored, no longer offered one

# Cameo drawn as an image (assets/ani/<name>.png, facing left) instead of the emoji.
# True (the standard) = Preferences ▸ Display ▸ Select animal offers the images found
# in assets/ani; False = the original emoji animals (ANIMALS). The emoji path is kept
# intact so this switch alone restores it.
USE_IMAGE_ANIMALS = True
_DEFAULT_IMAGE_ANIMAL = "Trout"
# True = the selected animal is the newest-point marker all the time; False = it
# appears only now and then (random timer), the dot otherwise.
animals_always = True

_IMAGE_BASE_SIZE = 32     # <name>_32x32.png is listed as plain '<Name>'
_image_animals = None     # [(name, file path)], scanned once
_pixmap_cache = {}


def image_animals():
    """[(name, path)] of the cameo images in assets/ani: '<name>.png' -> '<Name>';
    '<name>_<N>x<N>.png' -> '<Name>' for N = 32, '<Name> <N>x<N>' for any other size
    ('mole_64x64.png' -> 'Mole 64x64'). Every image is drawn at the same on-screen
    size (_ANIMAL_LOOK_IMAGE), whatever its resolution."""
    global _image_animals
    if _image_animals is None:
        import os
        import re
        from src.gui.utils.assets import asset_path
        folder = asset_path("ani")
        try:
            files = os.listdir(folder)
        except OSError:
            files = []
        found = []
        for f in files:
            m = re.fullmatch(r"(.+?)(?:_(\d+)x(\d+))?\.png", f, re.IGNORECASE)
            if not m:
                continue
            name = m.group(1).replace("_", " ")
            name = name[:1].upper() + name[1:]          # 'octopus (Carla)' keeps 'C'
            size = int(m.group(2)) if m.group(2) else 0
            if size and (size != _IMAGE_BASE_SIZE or int(m.group(3)) != size):
                name = f"{name} {m.group(2)}x{m.group(3)}"
            found.append(((m.group(1).lower(), size), name, os.path.join(folder, f)))
        _image_animals = [(name, path) for _key, name, path in sorted(found)]
    return _image_animals


def shop_name(name):
    """The Shop's name for an animal (account_shop.ANIMAL_CODES key): an image size
    variant ('Otter 64x64') is the same Shop animal as its base ('Otter')."""
    import re
    return re.sub(r" \d+x\d+$", "", name or "")


def animal_names(use_images=None):
    """The selectable animal names - the images in assets/ani or the emoji ones.
    `use_images` None = the current USE_IMAGE_ANIMALS."""
    if USE_IMAGE_ANIMALS if use_images is None else use_images:
        return [name for name, _path in image_animals()]
    return [name for name, _emoji in ANIMALS]


def default_animal():
    names = animal_names()
    preferred = _DEFAULT_IMAGE_ANIMAL if USE_IMAGE_ANIMALS else _DEFAULT_ANIMAL
    if preferred in names:
        return preferred
    return names[0] if names else None


def animal_pixmap(name):
    """The QPixmap of an image animal (cached), None if it has no readable image."""
    if name not in _pixmap_cache:
        from PySide6.QtGui import QPixmap
        path = dict(image_animals()).get(name)
        pm = QPixmap(path) if path else None
        _pixmap_cache[name] = pm if pm is not None and not pm.isNull() else None
    return _pixmap_cache[name]


def current_animal():
    """The animal name selected in Preferences ▸ Display ▸ Select animal."""
    name = QSettings("IIASA", "CWatM_GUI").value("display/animal", default_animal())
    return name if name in animal_names() else default_animal()


def parse_progress(text):
    """Pull ``(date, discharge)`` out of a CWatM per-timestep progress line.

    The model prints ``"\\r%-6i %10s %10.2f     "`` = ``<timestep> <date> <discharge>``
    (output.py), the date as ``dd/mm/yyyy`` (timestep.py ``date2str``). Returns
    ``(datetime|None, float)`` for a discharge line, or ``(None, None)`` otherwise.
    """
    s = (text or "").strip().strip("\r").strip()
    if not s:
        return None, None
    parts = s.split()
    if len(parts) < 2:      # the "\r%d" dots-only progress line has a single token
        return None, None
    try:
        value = float(parts[-1])
    except (TypeError, ValueError):
        return None, None
    date = None
    try:
        date = datetime.strptime(parts[-2], "%d/%m/%Y")
    except (ValueError, IndexError):
        date = None
    return date, value


class DischargeSparkline(QWidget):
    """A small live discharge plot: last ~3 months, older points faded out."""

    _WINDOW = timedelta(days=92)  # "~3 months" of data kept when dates are available
    _MAX_POINTS = 4000            # memory cap / fallback window when dates are absent
    # Left→right brightness fade exponent: opacity = 255 * frac**_FADE_GAMMA, where
    # frac is the horizontal position (0 = left edge → fully transparent, 1 = right =
    # newest → opaque). >1 pushes the left side more transparent so the trace clearly
    # fades out before the clock instead of butting up against it.
    _FADE_GAMMA = 1.5
    # The animal marker per mode: (half its drawn size in px, (shift x, shift y) from
    # the newest point; negative x = left, negative y = up) - the emoji and the 32x32
    # images need different values to sit on the newest point.
    _ANIMAL_LOOK_EMOJI = (16, (-1, -1))
    _ANIMAL_LOOK_IMAGE = (12, (-6, -1))
    # True = the animal is pushed back inside the widget (never cut off, but at the
    # right edge it then sits behind the newest point); False = centred on the point
    # + its shift.
    _ANIMAL_KEEP_INSIDE = False

    def __init__(self, parent=None):
        super().__init__(parent)
        self._points = []  # list of (datetime|None, value)
        self._animal = current_animal()  # which cameo emoji to draw (Configure)
        self.setMinimumSize(180, 120)
        self.setToolTip(
            "Live discharge at the first gauge — last ~3 months, older values fade out")
        # The newest-point marker is usually a dot, but every so often it briefly turns
        # into a little animal swimming along the trace (tilted to the local slope). A
        # slow timer flips the state at random so it feels spontaneous.
        # NOT started here (report §3.3): the plot is empty until a run streams data,
        # and a 600 ms timer running for the whole application lifetime defeats Windows
        # timer coalescing / idle power states for no visible effect. It starts on the
        # first sample and stops when the plot is cleared.
        self._show_animal = False
        self._animal_timer = QTimer(self)
        self._animal_timer.setInterval(600)
        self._animal_timer.timeout.connect(self._tick_animal)

    def set_animal(self, name):
        """Set the cameo animal (Preferences ▸ Display ▸ Select animal) and repaint.
        None = no animal (none bought in the Shop): only the plain dot."""
        if name is None:
            self._animal = None
            self._show_animal = False
        else:
            self._animal = name if name in animal_names() else default_animal()
        self.update()

    def _tick_animal(self):
        """Occasionally toggle the newest-point marker between a dot and the animal."""
        if self._animal is None:
            return                          # no animal owned - always the dot
        if self._show_animal:
            if random.random() < 0.20:      # the animal lingers a while (~5 ticks ≈ 3 s)
                self._show_animal = False
                self.update()
        elif random.random() < 0.08:        # ...and rare (~8% chance per 0.6 s)
            self._show_animal = True
            self.update()

    # -------------------------------------------------------------- data feed
    def clear(self):
        """Reset the plot (called at the start of every run)."""
        self._points = []
        self._animal_timer.stop()      # nothing to animate on an empty plot (§3.3)
        self._show_animal = False
        self.update()

    def add_value(self, date, value):
        """Append one ``(date, discharge)`` sample, trim to the window, and repaint."""
        if value is None:
            return
        self._points.append((date, float(value)))
        if not self._animal_timer.isActive():
            self._animal_timer.start()   # data is flowing - the cameo can appear (§3.3)
        self._trim()
        self.update()

    def _trim(self):
        """Keep only the last ~3 months (by date when available) plus a memory cap."""
        if not self._points:
            return
        last_date = self._points[-1][0]
        if last_date is not None:
            cutoff = last_date - self._WINDOW
            self._points = [
                p for p in self._points if p[0] is None or p[0] >= cutoff]
        if len(self._points) > self._MAX_POINTS:
            self._points = self._points[-self._MAX_POINTS:]

    def add_from_progress_line(self, text):
        """Parse a CWatM '\\r' progress line and append its (date, discharge), if any."""
        date, value = parse_progress(text)
        if value is not None:
            self.add_value(date, value)

    def sizeHint(self):
        return QSize(253, 140)   # 15% wider than the former 220

    # ------------------------------------------------------------------ paint
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        pad = 6
        plot_x0 = pad
        plot_y0 = pad
        plot_w = max(1, w - 2 * pad)
        plot_h = max(1, h - 2 * pad)

        pts = self._points
        if not pts:
            return

        vals = [p[1] for p in pts]
        vmin = min(vals)
        vmax = max(vals)
        span = vmax - vmin
        if span == 0:
            span = abs(vmax) or 1.0
            vmin -= span / 2
            vmax += span / 2
            span = vmax - vmin

        n = len(pts)
        if n == 1:
            xs = [plot_x0 + plot_w / 2.0]
        else:
            step = plot_w / (n - 1)
            xs = [plot_x0 + i * step for i in range(n)]

        def y_of(v):
            return plot_y0 + plot_h - (v - vmin) / span * plot_h

        base = theme.qcolor("clock_accent")
        pts_xy = [QPointF(xs[i], y_of(vals[i])) for i in range(n)]

        # Fade by horizontal position: opaque on the right (newest sample), fading to
        # fully transparent towards the left, so the trace visibly dissolves before
        # the clock instead of ending in a hard edge that reads as overlap. The fade
        # follows x (not timestep age) so it always matches the left→right layout.
        denom = max(1, n - 1)
        for i in range(1, n):
            frac = i / denom                       # 0 = left edge, 1 = right (newest)
            alpha = int(255 * (frac ** self._FADE_GAMMA))
            col = QColor(base)
            col.setAlpha(alpha)
            painter.setPen(QPen(col, 1.6))
            painter.drawLine(pts_xy[i - 1], pts_xy[i])

        # Latest point marker at full opacity — a dot, or the occasional animal cameo.
        if (self._show_animal or animals_always) and self._animal is not None:
            self._draw_animal(painter, pts_xy)
        else:
            painter.setBrush(base)
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(pts_xy[-1], 2.6, 2.6)

    def _draw_animal(self, painter, pts_xy):
        """Draw the selected animal emoji at the newest point, tilted to the local slope
        so it looks like it swims up/down the hydrograph (and faces forward in time)."""
        p = pts_xy[-1]
        angle = 0.0
        if len(pts_xy) >= 2:
            dx = p.x() - pts_xy[-2].x()
            dy = p.y() - pts_xy[-2].y()          # screen y grows downward
            if dx or dy:
                # Rising discharge -> dy<0 -> negative angle -> nose tilts up.
                angle = max(-55.0, min(55.0, math.degrees(math.atan2(dy, dx))))
        pm = animal_pixmap(self._animal) if USE_IMAGE_ANIMALS else None
        size, (shift_x, shift_y) = (self._ANIMAL_LOOK_IMAGE if pm is not None
                                    else self._ANIMAL_LOOK_EMOJI)
        cx = p.x() + shift_x
        cy = p.y() + shift_y
        if self._ANIMAL_KEEP_INSIDE:
            cx = min(max(cx, size), self.width() - size)
            cy = min(max(cy, size), self.height() - size)
        painter.save()
        painter.translate(QPointF(cx, cy))
        painter.rotate(angle)
        painter.scale(-1, 1)                     # face right (forward in time)
        if pm is not None:
            # 32x32 source drawn at 2*size, about the emoji's visible size; smooth
            # scaling so the downsized pixel art stays clean.
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawPixmap(QRectF(-size, -size, 2 * size, 2 * size), pm,
                               QRectF(pm.rect()))
            painter.restore()
            return
        f = QFont()
        f.setPixelSize(size)
        painter.setFont(f)
        emoji = _ANIMAL_EMOJI.get(self._animal, _ANIMAL_EMOJI[_DEFAULT_ANIMAL])
        # Centred in a symmetric rect, so the horizontal flip keeps it centred.
        painter.drawText(QRectF(-size, -size, 2 * size, 2 * size),
                         Qt.AlignCenter, emoji)
        painter.restore()
