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
    ("Random",     "\U0001F3B2"),       # 🎲 - a different animal each appearance
]
_ANIMAL_EMOJI = dict(ANIMALS)
_DEFAULT_ANIMAL = "Fish"
_RANDOM_ANIMAL = "Random"

# Pool the "Random" cameo draws from - animals only (no sailboat, no dice, no
# mythical creatures), so the marker is always a real animal. Water, land and air
# alike. Emoji needing a variation selector (chipmunk, spider, dove) are left out:
# without VS16 they can render as monochrome text glyphs.
_RANDOM_POOL = [
    # --- water ---
    "\U0001F41F",  # fish
    "\U0001F420",  # tropical fish
    "\U0001F421",  # blowfish
    "\U0001F42C",  # dolphin
    "\U0001F433",  # spouting whale
    "\U0001F40B",  # whale
    "\U0001F988",  # shark
    "\U0001F419",  # octopus
    "\U0001F980",  # crab
    "\U0001F990",  # shrimp
    "\U0001F991",  # squid
    "\U0001F99E",  # lobster
    "\U0001F422",  # turtle
    "\U0001F438",  # frog
    "\U0001F9AB",  # beaver
    "\U0001F9A6",  # otter
    "\U0001F9AD",  # seal
    "\U0001F40A",  # crocodile
    "\U0001F98E",  # lizard
    "\U0001F40D",  # snake
    "\U0001F427",  # penguin
    # --- land mammals ---
    "\U0001F415",  # dog
    "\U0001F408",  # cat
    "\U0001F40E",  # horse
    "\U0001F404",  # cow
    "\U0001F402",  # ox
    "\U0001F403",  # water buffalo
    "\U0001F416",  # pig
    "\U0001F417",  # boar
    "\U0001F411",  # ewe
    "\U0001F410",  # goat
    "\U0001F42A",  # camel
    "\U0001F42B",  # two-hump camel
    "\U0001F999",  # llama
    "\U0001F992",  # giraffe
    "\U0001F418",  # elephant
    "\U0001F98F",  # rhinoceros
    "\U0001F99B",  # hippopotamus
    "\U0001F993",  # zebra
    "\U0001F98C",  # deer
    "\U0001F401",  # mouse
    "\U0001F400",  # rat
    "\U0001F407",  # rabbit
    "\U0001F994",  # hedgehog
    "\U0001F987",  # bat
    "\U0001F412",  # monkey
    "\U0001F98D",  # gorilla
    "\U0001F9A7",  # orangutan
    "\U0001F9A5",  # sloth
    "\U0001F998",  # kangaroo
    "\U0001F9A1",  # badger
    "\U0001F9A8",  # skunk
    "\U0001F405",  # tiger
    "\U0001F406",  # leopard
    "\U0001F43B",  # bear
    "\U0001F43C",  # panda
    "\U0001F428",  # koala
    "\U0001F98A",  # fox
    "\U0001F43A",  # wolf
    # --- birds ---
    "\U0001F426",  # bird
    "\U0001F986",  # duck
    "\U0001F9A2",  # swan
    "\U0001F989",  # owl
    "\U0001F985",  # eagle
    "\U0001F99C",  # parrot
    "\U0001F9A9",  # flamingo
    "\U0001F99A",  # peacock
    "\U0001F413",  # rooster
    "\U0001F414",  # chicken
    "\U0001F983",  # turkey
    "\U0001F9A4",  # dodo
    # --- small crawlers & fliers ---
    "\U0001F98B",  # butterfly
    "\U0001F41D",  # honeybee
    "\U0001F41E",  # ladybug
    "\U0001F41C",  # ant
    "\U0001F997",  # cricket
    "\U0001F982",  # scorpion
    "\U0001F40C",  # snail
    "\U0001F99F",  # mosquito
    # --- long extinct, still animals ---
    "\U0001F995",  # sauropod
    "\U0001F996",  # T-rex
]


def current_animal():
    """The animal name selected in Configure ▸ Select animal (default 'Fish')."""
    name = QSettings("IIASA", "CWatM_GUI").value("display/animal", _DEFAULT_ANIMAL)
    return name if name in _ANIMAL_EMOJI else _DEFAULT_ANIMAL


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
        self._random_emoji = random.choice(_RANDOM_POOL)  # current "Random" pick
        self._animal_timer = QTimer(self)
        self._animal_timer.setInterval(600)
        self._animal_timer.timeout.connect(self._tick_animal)

    def set_animal(self, name):
        """Set the cameo animal (Configure ▸ Select animal) and repaint."""
        self._animal = name if name in _ANIMAL_EMOJI else _DEFAULT_ANIMAL
        self.update()

    def _tick_animal(self):
        """Occasionally toggle the newest-point marker between a dot and the animal."""
        if self._show_animal:
            if random.random() < 0.20:      # the animal lingers a while (~5 ticks ≈ 3 s)
                self._show_animal = False
                self.update()
        elif random.random() < 0.08:        # ...and rare (~8% chance per 0.6 s)
            self._show_animal = True
            # Re-roll "Random" once per appearance, not per repaint - otherwise the
            # creature would flicker through the pool on every frame.
            self._random_emoji = random.choice(_RANDOM_POOL)
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
        if self._show_animal:
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
        size = 15
        painter.save()
        painter.translate(p)
        painter.rotate(angle)
        painter.scale(-1, 1)                     # face right (forward in time)
        f = QFont()
        f.setPixelSize(size)
        painter.setFont(f)
        if self._animal == _RANDOM_ANIMAL:
            emoji = self._random_emoji or random.choice(_RANDOM_POOL)
        else:
            emoji = _ANIMAL_EMOJI.get(self._animal, _ANIMAL_EMOJI[_DEFAULT_ANIMAL])
        # Centred in a symmetric rect, so the horizontal flip keeps it centred.
        painter.drawText(QRectF(-size, -size, 2 * size, 2 * size),
                         Qt.AlignCenter, emoji)
        painter.restore()
