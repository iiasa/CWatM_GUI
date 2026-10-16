"""CWatM Academy - Level 1's Field Test: locate the outlet of a big river basin,
unaided.

Where the Level 1 lesson (``academy_outlet_map.OutletMapWidget``) frames the
whole Danube basin, points a pulsing suggestion marker at the answer, and
*writes* the pick into MaskMap/Gauges, this is a Field Test - a graded
check, not a second lesson. ``BasinFieldTestWindow`` shows the same kind of
upstream-area map (the bundled ``academy_ups_30min.nc`` grid is global), but
deliberately has **no** suggestion marker and never touches the main window's
settings - it only grades a click and reports pass/fail.

**Which basin**: a random one of all 100 basins in
``assets/academy_biggest_basins.csv`` (rank, basin_size_km2, name, lon, lat -
the outlet cell centre on this same 30' grid), the Danube included.
**Another basin** draws a new one. The
view is framed *around* the outlet but deliberately off-centre
(``view_bounds``), so the middle of the map is not the answer.

**Graded against the 4 biggest upstream cells of that basin**
(``target_cells``), computed from the grid at runtime rather than hard-coded:
the outlet cell (the listed one - its upstream area equals the listed basin
size for all 100) plus, best-first, the three largest cells draining into what
is already selected (a neighbour with a smaller upstream area). Landing on any
of those four - snapped to the nearest grid cell the same way the Level 1 map
reads a value under the cursor - passes.

Reuses academy_outlet_map's module-level helpers (``load_ups_grid``,
``_ups_rgba``/``_ocean_rgba``/``_image_overlay``/``_rgba_to_datauri``, the
colour-ramp constants, the WMS basemap layer name) rather than copying them -
one implementation of "render the accumulation grid as a Leaflet overlay",
shared by the lesson map and this test map. The click-to-Python bridge is
the same ``document.title`` hijack (see basin_viewer2._helper_js for the
original), with its own ``NILETEST`` prefix so it can never collide with the
lesson map's ``ACOUT`` one if both happened to be alive at once.

Non-modal ``QDialog``, like the other secondary windows: a status line reads
"Awaiting target ..." until a pick lands on a target cell, then "Target
confirmed - that is the outlet of the <basin>"; a miss reads "Not the outlet -
you are N kilometers away" (great-circle distance from the click to the listed
outlet, ``distance_km``) and lets the learner click again. **End test** (always
enabled) shows a small statistics window (``show_end_statistics``: level, points,
basins found / failed, wrong clicks, the biggest discrepancy, own best + record and
the Field Test badge) and closes the window; with at least one basin found it emits
``passed`` - academy_outlet_map.OutletMapWidget._on_nile_field_test_passed picks up
from there (the level's completion celebration).

**The Field Test badge** (``account_shop.field_test_tier``, nothing extra stored):
bronze once played (an own best above 0), silver for a best above 10000 points,
gold while the own best is the record of all users - lost again when beaten.

**Score** (top right, "Points: n" with "Highscore: n" below): +``FOUND_POINTS``
(1000) the first time a basin's outlet is hit, minus the distance in km
(``miss_penalty``) for every wrong click before that; clicks on a basin already
found are graded but not scored. *Another basin* keeps the score running, and
costs ``SKIP_PENALTY`` (500) when the basin shown was not found yet; from
``GLOBAL_VIEW_POINTS`` (5000) on, a new basin is shown on the whole world map,
zoomed out only until the world fits the window once (no repeat left/right),
instead of framed around it.

A miss never costs more than ``PENALTY_CAPS`` (1000 for the first miss on a
basin, 500 for the second, 250 from then on - ``capped_penalty``), and a found
basin is drawn on the map under the upstream-area overlay (JS ``showBasin``).

**Level 2 / shape mode** (from ``SHAPE_MODE_POINTS``, 10000, for the rest of the
window - falling below it again does not go back), announced by
``show_level2_message`` with the Danube's basin map: a basin of the
``LEVEL2_POOL`` (50) biggest - all 100 from ``LEVEL2_ALL_POINTS`` (20000) on - is drawn at random, but its name is not given. Its area map - rebuilt from the upstream-area grid
(``basin_cells``; there is no flow-direction map) - is shown as a shape
(``basin_shape_image``, north up, true aspect) beside the instructions, and the
learner clicks anywhere inside that basin on the map: a hit is +1000, a miss
costs the distance to the nearest basin cell (``distance_to_cells_km``). The
view is framed on the outlet like Level 1's start but ``LEVEL2_ZOOM_OUT`` (2.5x)
wider, and from ``LEVEL2_GLOBAL_POINTS`` (15000) on it is the whole world map,
like the end of Level 1. The shape box draws only the bigger rivers (``RIVER_SHARE``
of the outlet's area and more) in blue, every other cell ``BASIN_ORANGE``; a found
basin is painted ``BASIN_ORANGE`` on the map with the upstream overlay on top.

Below the score: **Highscore** = the record of *all* users with its holder's
initials (Supabase table ``field_test_record``, no user column; read by everyone
via rpc ``get_field_test_record``), and **Your best** = the own best (the profile's
``field_test_highscore`` while logged in, QSettings ``academy/field_test_highscore``
otherwise - never merged, like the Academy progress). Beating the record asks once
per window (``ask_initials``) for 2 to 3 letters and sends them with the score
(``field_test_submit_score`` - the server keeps the greater one, under a row lock);
logged out the record cannot be claimed, and the status line says to log in.

A learner who finished Level 1 before comes straight here on "do it again"
(``academy_window.AcademyWindow._replay_level1``), without its first steps.
"""

import csv
import json
import math
import os
import random
import re

import numpy as np

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)
from PySide6.QtCore import Qt, QTimer, QUrl, Signal

from src.gui.utils import theme
from src.gui.utils.window_geometry import scaled_default_size
from src.gui.utils.gui_log import get_logger
from src.gui.utils.i18n import tr

log = get_logger("academy_field_test")

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    import folium
    _MAP_AVAILABLE = True
    _MAP_IMPORT_ERROR = ""
except Exception as _e:  # pragma: no cover - import guard
    _MAP_AVAILABLE = False
    _MAP_IMPORT_ERROR = f"{type(_e).__name__}: {_e}"

from src.gui.widgets.academy_outlet_map import (
    load_ups_grid, _ups_rgba, _ocean_rgba, _image_overlay, _rgba_to_datauri,
    _hex_to_rgb, _rgb_css, _MAP_LABEL_FONT, _BASEMAP_WMS_LAYER, _orient,
)

_C = theme.theme_colors("mikhail")

_BASINS_ASSET = "academy_biggest_basins.csv"
_POOL_SIZE = 100                 # draw from all 100 basins of the list
EARTH_RADIUS_KM = 6371.0
_EXCLUDED = set()                # basins never drawn (none at the moment)
TARGET_CELLS = 4                 # pass = one of the basin's 4 biggest cells

# Score: +FOUND_POINTS for every basin found, minus the km of every wrong click.
# The best score is the highscore - in the profile while logged in
# (rpc get_field_test_highscore / field_test_submit_score), else in QSettings.
FOUND_POINTS = 1000
SKIP_PENALTY = 500           # "Another basin" before this one was found
HIGHSCORE_KEY = "academy/field_test_highscore"          # own best, logged out
LAST_INITIALS_KEY = "academy/field_test_last_initials"  # suggestion for the box
_HIGHSCORE_OPS = ("get_field_test_record", "get_field_test_highscore",
                  "field_test_submit_score")
# The score steps (each counts when the next basin is drawn):
#   GLOBAL_VIEW_POINTS   Level 1: the whole world map, no more zooming in
#   SHAPE_MODE_POINTS    Level 2 for good (the rest of the window): the basin's shape
#                        without its name, framed again but LEVEL2_ZOOM_OUT wider
#   LEVEL2_GLOBAL_POINTS Level 2: the whole world map again
#   LEVEL2_ALL_POINTS    Level 2: all 100 basins, not only the LEVEL2_POOL biggest
GLOBAL_VIEW_POINTS = 5000
GLOBAL_VIEW = [[-60.0, -180.0], [85.0, 180.0]]
SHAPE_MODE_POINTS = 10000
LEVEL2_GLOBAL_POINTS = 15000
LEVEL2_ALL_POINTS = 20000
_AREA_FACTOR = 1.0022        # the grid's cell area vs the sphere formula
_SHAPE_W, _SHAPE_H = 220, 160
LEVEL2_POOL = 50             # Level 2 draws from the 50 biggest basins only
LEVEL2_ZOOM_OUT = 2.5        # Level 2 view: this many times wider than Level 1's start
PENALTY_CAPS = (1000, 500, 250)   # most a miss costs: 1st, 2nd, 3rd+ on a basin
BASIN_ORANGE = "#ff8a1e"     # a basin's area: the shape box and the found basin
RIVER_SHARE = 0.01           # shape box: rivers = cells with >= 1 % of the outlet's area
FOUND_BASIN_ALPHA = 200      # the found basin on the map (0-255), ups drawn on top
_INITIALS_RE = re.compile(r"[A-Z]{2,3}")


# ------------------------------------------------------------ pure helpers

def load_basins(path=None, pool=_POOL_SIZE, excluded=_EXCLUDED):
    """The candidate basins: [{rank, size_km2, name, lon, lat}], the first
    ``pool`` rows of the list minus ``excluded``."""
    if path is None:
        from src.gui.utils.assets import asset_path
        path = asset_path(_BASINS_ASSET)
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                basin = dict(rank=int(row["rank"]), size_km2=float(row["basin_size_km2"]),
                             name=row["name"].strip(), lon=float(row["lon"]),
                             lat=float(row["lat"]))
            except (KeyError, ValueError):
                continue
            if basin["rank"] <= pool and basin["name"] not in excluded:
                out.append(basin)
    return out


def _nearest_index(lats, lons, lat, lon):
    return (int(np.abs(np.asarray(lats) - float(lat)).argmin()),
            int(np.abs(np.asarray(lons) - float(lon)).argmin()))


def target_cells(basin_data, lats, lons, lat, lon, n=TARGET_CELLS):
    """The basin's ``n`` biggest upstream cells as [(lat, lon)], outlet first.

    Best-first upstream from the outlet cell nearest (lat, lon): among the
    8-neighbours of the cells already chosen, the next one is the largest whose
    upstream area is smaller than the chosen cell it touches (it drains into
    it). Longitude wraps around the date line."""
    grid = np.asarray(basin_data, dtype=float)
    lats, lons = np.asarray(lats), np.asarray(lons)
    nrow, ncol = grid.shape
    chosen = [_nearest_index(lats, lons, lat, lon)]
    while len(chosen) < n:
        best, best_val = None, -np.inf
        for r, c in chosen:
            here = grid[r, c]
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == dc == 0:
                        continue
                    rr, cc = r + dr, (c + dc) % ncol
                    if not 0 <= rr < nrow or (rr, cc) in chosen:
                        continue
                    v = grid[rr, cc]
                    if np.isfinite(v) and v < here and v > best_val:
                        best, best_val = (rr, cc), v
        if best is None:
            break
        chosen.append(best)
    return [(float(lats[r]), float(lons[c])) for r, c in chosen]


def is_target(lats, lons, lat, lon, targets):
    """Does a click at (lat, lon), snapped to the nearest cell, hit a target?"""
    r, c = _nearest_index(lats, lons, lat, lon)
    snapped = (float(np.asarray(lats)[r]), float(np.asarray(lons)[c]))
    return any(abs(snapped[0] - t[0]) < 1e-6 and abs(snapped[1] - t[1]) < 1e-6
               for t in targets)


def distance_km(lat1, lon1, lat2, lon2):
    """Great-circle (haversine) distance in km. A degree of longitude shrinks
    with cos(latitude), and the date line wraps - both handled by the formula."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def _settings():
    """Where the logged-out highscore lives (tests point it at a temp file - this
    constructor is always the native store, setDefaultFormat does not reach it)."""
    from PySide6.QtCore import QSettings
    return QSettings("IIASA", "CWatM_GUI")


def cell_areas(lats, lons):
    """Full cell area per grid row in km² - the grid's own convention, which is
    0.22 % above the sphere formula (an ellipsoid area; checked against the most
    common upstream area of inland headwater cells)."""
    lats = np.asarray(lats, dtype=float)
    dlat = abs(float(lats[1] - lats[0])) if lats.size > 1 else 0.5
    dlon = abs(float(np.asarray(lons)[1] - np.asarray(lons)[0])) if len(lons) > 1 else 0.5
    return (_AREA_FACTOR * EARTH_RADIUS_KM ** 2 * math.radians(dlon)
            * np.abs(np.sin(np.radians(lats + dlat / 2))
                     - np.sin(np.radians(lats - dlat / 2))))


def basin_cells(basin_data, lats, lons, lat, lon):
    """All cells draining to the outlet nearest (lat, lon), as [(row, col)].

    There is no flow-direction map, only upstream area - but a cell's upstream
    area is its own (land) area plus the upstream areas of the neighbours that
    drain into it. So, from the outlet up, each cell takes the subset of its
    smaller, unclaimed 8-neighbours whose areas leave a valid own area (0 to one
    full cell, 2 % slack for rounding), closest to a full cell (an inland cell
    is all land). Cells are expanded largest first, so a main stem claims its
    tributaries before a side cell can; when no subset fits, the best fit is taken
    anyway, so a branch is never lost. Checked against the listed sizes: 98 of
    the 100 basins within 5 % (the other two are coastal - partial land cells)."""
    import heapq
    import itertools
    grid = np.asarray(basin_data, dtype=float)
    nrow, ncol = grid.shape
    full_row = cell_areas(lats, lons)
    r0, c0 = _nearest_index(lats, lons, lat, lon)
    basin = {(r0, c0)}
    heap = [(-grid[r0, c0], r0, c0)]
    while heap:
        _, r, c = heapq.heappop(heap)
        full, here = full_row[r], grid[r, c]
        if not np.isfinite(here) or here <= full * 1.001:
            continue                                  # a headwater cell
        cand = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == dc == 0:
                    continue
                rr, cc = r + dr, (c + dc) % ncol
                if 0 <= rr < nrow and (rr, cc) not in basin:
                    v = grid[rr, cc]
                    if np.isfinite(v) and 0 < v < here:
                        cand.append(((rr, cc), v))
        best, best_key = (), (2, math.inf)
        for k in range(1, len(cand) + 1):
            for sub in itertools.combinations(cand, k):
                own = here - sum(v for _, v in sub)
                if -0.02 * full <= own <= 1.02 * full:
                    key = (0, abs(full - own))
                else:
                    key = (1, abs(own - min(max(own, 0.0), full)))
                if key < best_key:
                    best, best_key = sub, key
        for cell, v in best:
            basin.add(cell)
            heapq.heappush(heap, (-v, cell[0], cell[1]))
    return sorted(basin)


def distance_to_cells_km(lats, lons, cells, lat, lon):
    """Great-circle distance in km from (lat, lon) to the nearest cell centre."""
    lats, lons = np.asarray(lats, dtype=float), np.asarray(lons, dtype=float)
    rows = np.array([r for r, _ in cells])
    cols = np.array([c for _, c in cells])
    p1, p2 = math.radians(lat), np.radians(lats[rows])
    dp, dl = p2 - p1, np.radians(lons[cols] - lon)
    a = np.sin(dp / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return float((2 * EARTH_RADIUS_KM * np.arcsin(np.minimum(1.0, np.sqrt(a)))).min())


def _unwrapped(lats, lons, cells):
    """(rows, cols, lats, lons) of the cells, longitude unwrapped around the
    first cell so a basin across the date line stays in one piece."""
    lats, lons = np.asarray(lats, dtype=float), np.asarray(lons, dtype=float)
    ncol = lons.size
    rows = np.array([r for r, _ in cells])
    cols = np.array([c for _, c in cells])
    c0 = cols[0]
    rel = (cols - c0 + ncol // 2) % ncol - ncol // 2
    dlon = abs(float(lons[1] - lons[0])) if ncol > 1 else 0.5
    return rows, rel, lats[rows], float(lons[c0]) + rel * dlon


def capped_penalty(km, misses_before):
    """Points a wrong click costs: the km, but at most 1000 for the first miss on
    a basin, 500 for the second and 250 from the third on - one far-off click
    must not wipe out a whole game."""
    cap = PENALTY_CAPS[min(int(misses_before), len(PENALTY_CAPS) - 1)]
    return min(miss_penalty(km), cap)


def basin_mask_rgba(shape, cells, color, alpha=120):
    """RGBA image (grid shape, grid row order) with the basin's cells in
    ``color`` - for the found basin's overlay on the map (orient it like the ups
    overlay before use)."""
    rgba = np.zeros(tuple(shape) + (4,), dtype=np.uint8)
    r, g, b = _hex_to_rgb(color)
    rows = np.array([rc[0] for rc in cells])
    cols = np.array([rc[1] for rc in cells])
    rgba[rows, cols] = (r, g, b, alpha)
    return rgba


def basin_shape_image(lats, lons, cells, color, width=220, height=160, values=None):
    """The basin as a picture (``QImage``): its cells in ``color`` on a transparent
    background, north up, a cell's width scaled by cos(latitude) so the shape is
    true, fitted into width x height - no coordinates, no map. With ``values``
    (the upstream-area grid) only the bigger rivers are drawn - the cells with at
    least ``RIVER_SHARE`` of the outlet's upstream area, in the main map's blue
    ramp - and every other cell is the same solid ``color``."""
    from PySide6.QtGui import QImage, QPainter, QColor
    from PySide6.QtCore import QRectF
    rows, rel, clat, _ = _unwrapped(lats, lons, cells)
    colours = None
    if values is not None:
        from src.gui.widgets.academy_outlet_map import _UPS_COLOR_LOW, _UPS_COLOR_HIGH
        ups = np.maximum(np.asarray(values, dtype=float)[
            rows, np.array([c for _, c in cells])], 0.0)
        top = float(np.nanmax(ups)) if ups.size else 0.0
        river = ups >= max(top * RIVER_SHARE, 1.0)
        v = np.log1p(ups)
        lo_v = math.log1p(max(top * RIVER_SHARE, 1.0))
        norm = np.clip((v - lo_v) / (math.log1p(max(top, 1.0)) - lo_v + 1e-9), 0.0, 1.0)
        # the ramp's light end would vanish into orange - start a third of the way
        norm = 0.35 + 0.65 * norm
        lo, hi = np.array(_UPS_COLOR_LOW, float), np.array(_UPS_COLOR_HIGH, float)
        rgb = (lo * (1 - norm[:, None]) + hi * norm[:, None]).astype(int)
        colours = [QColor(int(c[0]), int(c[1]), int(c[2])) if is_river else None
                   for c, is_river in zip(rgb, river)]
    r_min, c_min = rows.min(), rel.min()
    nr, nc = rows.max() - r_min + 1, rel.max() - c_min + 1
    xscale = max(0.15, math.cos(math.radians(float(clat.mean()))))
    cell = min(width / (nc * xscale), height / nr)
    cw, ch = cell * xscale, cell
    img = QImage(width, height, QImage.Format_ARGB32)
    img.fill(0)
    x0 = (width - nc * cw) / 2
    y0 = (height - nr * ch) / 2
    fill = QColor(color)
    painter = QPainter(img)
    try:
        painter.setPen(Qt.NoPen)
        for i, (r, c) in enumerate(zip(rows, rel)):
            # a hair of overlap, so no seams show between neighbouring cells
            rect = QRectF(x0 + (c - c_min) * cw, y0 + (r - r_min) * ch,
                          cw + 0.6, ch + 0.6)
            painter.fillRect(rect, colours[i] if colours is not None
                             and colours[i] is not None else fill)
    finally:
        painter.end()
    return img


def clean_initials(text):
    """2 to 3 letters in capitals, else '' (no initials)."""
    text = str(text or "").strip().upper()
    return text if _INITIALS_RE.fullmatch(text) else ""


def ask_initials(parent, suggestion=""):
    """The arcade question after a new highscore: 2 to 3 letters, or '' when the
    learner cancels. A module function so tests can answer it."""
    from PySide6.QtGui import QRegularExpressionValidator
    from PySide6.QtCore import QRegularExpression
    from PySide6.QtWidgets import QLineEdit, QDialogButtonBox

    c = _C
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("New highscore"))
    dlg.setStyleSheet(f"""
        QDialog {{ background-color: {c['window_bg']}; }}
        QLabel {{ color: {c['text']}; font-size: 13px; }}
        QLabel#nftNewHigh {{ color: {c['accent']}; font-size: 18px; font-weight: 700; }}
        QLineEdit {{
            background-color: {c['panel_bg']}; color: {c['accent']};
            border: 1px solid {c['accent']}; border-radius: 4px;
            font-size: 22px; font-weight: 700; padding: 4px 8px;
        }}
        QPushButton {{
            background-color: {c['btn_top']}; color: {c['btn_text']};
            border: 1px solid {c['btn_border']}; border-radius: 4px; padding: 5px 16px;
        }}
        QPushButton:disabled {{ color: {c['text_gray']}; border-color: {c['border']}; }}
    """)
    lay = QVBoxLayout(dlg)
    head = QLabel("NEW HIGHSCORE!")
    head.setObjectName("nftNewHigh")
    head.setAlignment(Qt.AlignCenter)
    lay.addWidget(head)
    lay.addWidget(QLabel("Enter your initials (2 to 3 letters):"))
    edit = QLineEdit(clean_initials(suggestion))
    edit.setMaxLength(3)
    edit.setAlignment(Qt.AlignCenter)
    edit.setValidator(QRegularExpressionValidator(QRegularExpression("[A-Za-z]{0,3}"), edit))
    lay.addWidget(edit)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    ok = buttons.button(QDialogButtonBox.Ok)
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    lay.addWidget(buttons)

    def _sync(text):
        upper = text.upper()
        if upper != text:
            pos = edit.cursorPosition()
            edit.setText(upper)
            edit.setCursorPosition(pos)
        ok.setEnabled(bool(clean_initials(upper)))

    edit.textChanged.connect(_sync)
    _sync(edit.text())
    edit.selectAll()
    edit.setFocus()
    if dlg.exec() != QDialog.Accepted:
        return ""
    return clean_initials(edit.text())


def show_level2_message(parent, image=None):
    """The level-up message at SHAPE_MODE_POINTS: "Level 2 - Congratulations,
    you reached Level 2", with the Danube basin (``image``, a QImage) and the new
    rules. Modal; a module function so tests can answer it."""
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QDialogButtonBox
    c = _C
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Level 2"))
    dlg.setStyleSheet(f"""
        QDialog {{ background-color: {c['window_bg']}; }}
        QLabel {{ color: {c['text']}; font-size: 13px; }}
        QLabel#nftLevelTag {{ color: {c['accent']}; font-size: 12px; font-weight: 700;
                              letter-spacing: 3px; }}
        QLabel#nftLevelHead {{ color: {c['accent']}; font-size: 19px; font-weight: 800; }}
        QLabel#nftLevelArt {{
            background-color: {c['panel_bg']};
            border: 1px solid {c['accent']}; border-radius: 10px;
        }}
        QLabel#nftLevelCaption {{ color: {c['text_muted']}; font-size: 11px; }}
        QPushButton {{
            background-color: {c['btn_top']}; color: {c['btn_text']};
            border: 1px solid {c['accent']}; border-radius: 4px; padding: 6px 22px;
            font-weight: 700;
        }}
        QPushButton:hover {{ background-color: {c['btn_hover_top']}; }}
    """)
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(28, 22, 28, 18)
    lay.setSpacing(10)
    for text, name in (("LEVEL 2", "nftLevelTag"),
                       ("Congratulations!\nYou reached Level 2", "nftLevelHead")):
        label = QLabel(text)
        label.setObjectName(name)
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        lay.addWidget(label)
    if image is not None and not image.isNull():
        art = QLabel()
        art.setObjectName("nftLevelArt")
        art.setAlignment(Qt.AlignCenter)
        art.setPixmap(QPixmap.fromImage(image))
        art.setFixedSize(image.width() + 24, image.height() + 24)
        lay.addWidget(art, 0, Qt.AlignHCenter)
        caption = QLabel("The Danube basin - this is what a basin looks like now")
        caption.setObjectName("nftLevelCaption")
        caption.setAlignment(Qt.AlignCenter)
        lay.addWidget(caption)
    # plain text, not rich text: the language filter translates plain labels only
    rules = QLabel(
        f"From now on you see the shape of a river basin, not its name - one "
        f"of the {LEVEL2_POOL} biggest on Earth. Find it on the map and click "
        f"anywhere inside it: +{FOUND_POINTS} for a hit, a miss costs the "
        "distance to the basin (at most 1000, then 500, then 250).")
    rules.setWordWrap(True)
    rules.setAlignment(Qt.AlignCenter)
    lay.addWidget(rules)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok)
    buttons.button(QDialogButtonBox.Ok).setText("Let's go")
    buttons.accepted.connect(dlg.accept)
    buttons.setCenterButtons(True)
    lay.addWidget(buttons)
    dlg.setFixedWidth(max(460, (image.width() + 90) if image is not None else 460))
    dlg.exec()


def show_end_statistics(parent, stats):
    """End test: a small statistics window (``BasinFieldTestWindow.statistics``) -
    level, points, basins found / failed, wrong clicks, the biggest discrepancy,
    own best + record and the Field Test badge. Modal; a module function so tests
    can answer it."""
    from PySide6.QtWidgets import QDialogButtonBox, QGridLayout
    from src.gui.utils import account_shop
    from src.gui.utils.badge_images import badge_pixmap
    c = _C
    dlg = QDialog(parent)
    dlg.setWindowTitle(tr("Field Test - statistics"))
    dlg.setStyleSheet(f"""
        QDialog {{ background-color: {c['window_bg']}; }}
        QLabel {{ color: {c['text']}; font-size: 13px; }}
        QLabel#nftStatTag {{ color: {c['accent']}; font-size: 12px; font-weight: 700;
                             letter-spacing: 3px; }}
        QLabel#nftStatHead {{ color: {c['accent']}; font-size: 20px; font-weight: 800; }}
        QLabel#nftStatKey {{ color: {c['text_muted']}; }}
        QLabel#nftStatValue {{ color: {c['accent']}; font-weight: 700; }}
        QLabel#nftStatNote {{ color: {c['text_muted']}; font-size: 12px; }}
        QPushButton {{
            background-color: {c['btn_top']}; color: {c['btn_text']};
            border: 1px solid {c['accent']}; border-radius: 4px; padding: 6px 22px;
        }}
        QPushButton:hover {{ background-color: {c['btn_hover_top']}; }}
    """)
    lay = QVBoxLayout(dlg)
    lay.setContentsMargins(26, 20, 26, 16)
    lay.setSpacing(10)
    tag = QLabel("TEST ENDED")
    tag.setObjectName("nftStatTag")
    lay.addWidget(tag)
    head = QLabel("Your Field Test")
    head.setObjectName("nftStatHead")
    lay.addWidget(head)

    grid = QGridLayout()
    grid.setHorizontalSpacing(24)
    grid.setVerticalSpacing(6)
    km = stats.get("max_miss_km") or 0
    rows = [("Level", str(stats.get("level", 1))),
            ("Points", str(stats.get("points", 0))),
            ("Basins found", str(stats.get("found", 0))),
            ("Basins failed", str(stats.get("failed", 0))),
            ("Wrong clicks", str(stats.get("wrong_clicks", 0))),
            ("Biggest discrepancy", f"{km:,.0f} km" if km else "–")]
    if stats.get("best") is not None:
        rows.append(("Your best", str(stats["best"])))
    if stats.get("record") is not None:
        rows.append(("Highscore of all users", str(stats["record"])))
    for i, (key, value) in enumerate(rows):
        k = QLabel(key)
        k.setObjectName("nftStatKey")
        v = QLabel(value)
        v.setObjectName("nftStatValue")
        v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(k, i, 0)
        grid.addWidget(v, i, 1)
    lay.addLayout(grid)

    # the Field Test badge: bronze = played, silver = a best above 10000, gold =
    # holding the record of all users
    tier = stats.get("badge")
    badge_row = QHBoxLayout()
    if tier:
        pm = badge_pixmap(account_shop.field_test_badge_image(tier), 72,
                          dpr=dlg.devicePixelRatioF())
        art = QLabel()
        if pm is not None:
            art.setPixmap(pm)
        else:
            art.setText("🏅")
            art.setStyleSheet("font-size: 44px;")
        badge_row.addWidget(art)
        text = {"bronze": "Your Field Test badge: bronze",
                "silver": "Your Field Test badge: silver",
                "gold": "Your Field Test badge: gold - you hold the highscore"}[tier]
    elif not stats.get("logged_in"):
        text = "Log in to your CWatM account to earn the Field Test badge."
    else:
        text = "Find a basin to earn the bronze Field Test badge."
    note = QLabel(text)
    note.setObjectName("nftStatNote")
    note.setWordWrap(True)
    badge_row.addWidget(note, 1)
    lay.addLayout(badge_row)
    buttons = QDialogButtonBox(QDialogButtonBox.Close)
    buttons.rejected.connect(dlg.reject)
    buttons.setCenterButtons(True)
    lay.addWidget(buttons)
    dlg.setMinimumWidth(360)
    dlg.exec()


def miss_penalty(km):
    """Points a wrong click costs: the distance to the outlet, in whole km."""
    return int(round(float(km)))


def view_bounds(basin, rng=random, scale=1.0):
    """[[south, west], [north, east]] around the outlet, sized from the basin
    area, shifted at random so the outlet is never the centre of the view (but
    always well inside it). ``scale`` > 1 zooms out (Level 2)."""
    half = min(25.0, max(4.0, (basin["size_km2"] ** 0.5) / 111.0 * 0.9))
    half = min(70.0, half * float(scale))
    clat = basin["lat"] + rng.uniform(-0.5, 0.5) * half
    clon = basin["lon"] + rng.uniform(-0.5, 0.5) * half
    south, north = max(-85.0, clat - half), min(85.0, clat + half)
    return [[south, clon - half], [north, clon + half]]


class BasinFieldTestWindow(QDialog):
    """Level 1's Field Test - see the module docstring. Emits ``passed`` when
    End test is clicked after at least one basin was found."""

    passed = Signal()

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.mw = main_window
        self._picked_ok = False
        self._map_ready = False
        self._js_queue = []
        self._basins = []
        self._basin = None
        self._targets = []
        self._score = 0
        self._basin_found = False
        self._shape_mode = False         # Level 2, latched at SHAPE_MODE_POINTS
        self._level2_shown = False       # the level-up message, once per window
        self._misses = 0                 # wrong clicks on the current basin
        # the statistics shown by End test
        self._found_count = 0            # basins found
        self._failed_count = 0           # basins given up (skipped, or open at the end)
        self._wrong_clicks = 0
        self._max_miss_km = 0.0          # the biggest discrepancy of a wrong click
        self._basin_cell_cache = {}      # basin name -> [(row, col)]
        self._basin_cells = []
        self._basin_cell_set = set()
        self._best = 0                   # own best ("Your best")
        self._best_known = True
        self._record = 0                 # the record of all users ("Highscore")
        self._record_initials = ""       # of whoever holds it
        self._record_known = False
        self._record_pending = False     # asked the server, no answer yet
        self._my_initials = None         # typed in this window (None = not asked)
        self._login_hint_shown = False
        self._account_worker = None
        self._remote = False             # logged in: own best in the profile
        try:
            self._basins = load_basins()
        except Exception:
            log.warning("academy basin list unreadable", exc_info=True)
        self.setWindowTitle(tr("CWatM Academy - Field Test"))
        # a maximize button in the title bar (a QDialog has none by default)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self._build_ui()
        self._apply_style()
        self._init_highscore()
        self.resize(*scaled_default_size(self, 900, 640))
        if _MAP_AVAILABLE:
            self._load_and_show()
        else:
            self.status_label.setText(
                f"Map unavailable: {_MAP_IMPORT_ERROR}\n"
                "(needs folium and PySide6 QtWebEngine)")

    # ------------------------------------------------------------------ ui

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        header = QHBoxLayout()
        heading = QVBoxLayout()
        heading.setSpacing(4)
        tag = QLabel("FIELD TEST")
        tag.setObjectName("nftTag")
        heading.addWidget(tag)
        self.title_label = QLabel("Locate the outlet")
        self.title_label.setObjectName("nftTitle")
        heading.addWidget(self.title_label)
        header.addLayout(heading, 1)

        # top right: the running score, the highscore below it
        scores = QVBoxLayout()
        scores.setSpacing(2)
        self.points_label = QLabel("Points: 0")
        self.points_label.setObjectName("nftPoints")
        self.points_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.points_label.setToolTip(
            f"+{FOUND_POINTS} for every basin found, minus the kilometers of every "
            "wrong click")
        scores.addWidget(self.points_label)
        self.highscore_label = QLabel("Highscore: –")
        self.highscore_label.setObjectName("nftHighscore")
        self.highscore_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.highscore_label.setToolTip(
            "The best Field Test score of all CWatM users, with the initials of "
            "whoever holds it")
        scores.addWidget(self.highscore_label)
        self.best_label = QLabel("Your best: 0")
        self.best_label.setObjectName("nftBest")
        self.best_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.best_label.setToolTip("Your own best Field Test score")
        scores.addWidget(self.best_label)
        header.addLayout(scores)
        outer.addLayout(header)

        task = QHBoxLayout()
        self.instructions_label = QLabel("")
        self.instructions_label.setObjectName("nftInstructions")
        self.instructions_label.setWordWrap(True)
        task.addWidget(self.instructions_label, 1)
        # the basin to find, as a shape (from SHAPE_MODE_POINTS on)
        self.shape_label = QLabel()
        self.shape_label.setObjectName("nftShape")
        self.shape_label.setFixedSize(_SHAPE_W + 12, _SHAPE_H + 12)
        self.shape_label.setAlignment(Qt.AlignCenter)
        self.shape_label.setToolTip("The river basin to find - north is up")
        self.shape_label.setVisible(False)
        task.addWidget(self.shape_label)
        outer.addLayout(task)

        if _MAP_AVAILABLE:
            self.web_view = QWebEngineView()
            self.web_view.titleChanged.connect(self._on_web_title)
            outer.addWidget(self.web_view, 1)
        else:
            self.web_view = None

        status_row = QFrame()
        status_row.setObjectName("nftStatusRow")
        status_lay = QHBoxLayout(status_row)
        status_lay.setContentsMargins(12, 8, 12, 8)
        self.status_label = QLabel("Awaiting target …")
        self.status_label.setObjectName("nftStatus")
        status_lay.addWidget(self.status_label, 1)
        self.another_button = QPushButton("Another basin")
        self.another_button.setObjectName("nftConfirm")
        self.another_button.setToolTip(
            "Try the outlet of a different river basin - costs "
            f"{SKIP_PENALTY} points while this one is not found yet")
        self.another_button.clicked.connect(self._next_basin)
        status_lay.addWidget(self.another_button)
        # ends the game at any time: the statistics, then the window closes
        self.end_button = QPushButton("End test")
        self.end_button.setObjectName("nftConfirm")
        self.end_button.setToolTip("End the Field Test and see your statistics")
        self.end_button.clicked.connect(self._on_end_clicked)
        status_lay.addWidget(self.end_button)
        outer.addWidget(status_row)

    def _apply_style(self):
        c = _C
        self.setStyleSheet(f"""
            QDialog {{ background-color: {c['window_bg']}; }}
            QLabel#nftTag {{ color: {c['accent']}; font-size: 11px; font-weight: 700; }}
            QLabel#nftTitle {{ color: {c['accent']}; font-size: 18px; font-weight: 700; }}
            QLabel#nftPoints {{ color: {c['accent']}; font-size: 16px; font-weight: 700; }}
            QLabel#nftHighscore {{ color: {c['text_muted']}; font-size: 13px;
                                   font-weight: 600; }}
            QLabel#nftBest {{ color: {c['text_gray']}; font-size: 12px; }}
            QLabel#nftShape {{
                background-color: {c['panel_bg']};
                border: 1px solid {c['border']};
                border-radius: 8px;
            }}
            QLabel#nftInstructions {{ color: {c['text']}; font-size: 13px; }}
            QFrame#nftStatusRow {{
                background-color: {c['panel_bg']};
                border: 1px solid {c['border']};
                border-radius: 8px;
            }}
            QLabel#nftStatus {{ color: {c['text_muted']}; font-size: 13px; font-weight: 600; }}
            QPushButton#nftConfirm {{
                background-color: {c['btn_top']};
                color: {c['btn_text']};
                border: 1px solid {c['btn_border']};
                border-radius: 4px;
                padding: 6px 16px;
            }}
            QPushButton#nftConfirm:hover {{ background-color: {c['btn_hover_top']}; }}
            QPushButton#nftConfirm:disabled {{
                color: {c['text_gray']};
                border-color: {c['border']};
            }}
        """)

    # ------------------------------------------------------------- map build

    def _load_and_show(self):
        basin_data, lats, lons = load_ups_grid()
        if basin_data is None:
            self.status_label.setText("Could not load the upstream-area map.")
            return
        self._basin_data, self._lats, self._lons = basin_data, lats, lons
        if not self._basins:
            self.status_label.setText("Could not load the list of river basins.")
            return
        self._choose_basin()
        try:
            html = self._build_map_html()
        except Exception:
            log.warning("Nile field test map build failed", exc_info=True)
            self.status_label.setText("Could not build the map.")
            return
        try:
            from src.gui.widgets.basin_viewer import _get_tile_handler
            self._tile_handler = _get_tile_handler()
            self._tile_handler.set_page("academy_nile_test", html)
            profile = self.web_view.page().profile()
            try:
                profile.removeUrlSchemeHandler(self._tile_handler)
            except Exception:
                log.debug("_load_and_show: ignored", exc_info=True)
            profile.installUrlSchemeHandler(b"osmtile", self._tile_handler)
            self.web_view.loadFinished.connect(self._on_loaded)
            self.web_view.load(QUrl("osmtile://academy_nile_test/"))
        except Exception:
            log.warning("Nile field test map page serving failed", exc_info=True)
            self.status_label.setText("Could not display the map.")

    def _grid_bounds(self):
        lats, lons = np.asarray(self._lats), np.asarray(self._lons)
        dlat = abs(float(lats[1] - lats[0])) if lats.size > 1 else 0.01
        dlon = abs(float(lons[1] - lons[0])) if lons.size > 1 else 0.01
        west = float(lons.min()) - dlon / 2.0
        east = float(lons.max()) + dlon / 2.0
        south = float(lats.min()) - dlat / 2.0
        north = float(lats.max()) + dlat / 2.0
        return west, east, south, north

    def _build_map_html(self):
        from src.gui.widgets.basin_viewer2 import _strip_unused_assets, _inline_remote_assets
        west, east, south, north = self._grid_bounds()
        bounds = [[south, west], [north, east]]

        (s, w), (n, e) = self._view
        m = folium.Map(location=[(s + n) / 2.0, (w + e) / 2.0], zoom_start=4,
                       crs="EPSG4326", tiles=None, control_scale=False, zoom_control=True)
        ocean = _image_overlay(
            _rgba_to_datauri(_ocean_rgba(self._basin_data, self._lats, self._lons)),
            bounds, 1.0, "ocean")
        ocean.add_to(m)
        ups = _image_overlay(
            _rgba_to_datauri(_ups_rgba(self._basin_data, self._lats, self._lons)),
            bounds, 1.0, "ups")
        ups.add_to(m)

        js = self._helper_js(m.get_name(), ups.get_name())
        html = m.get_root().render()
        html = _strip_unused_assets(html)

        panel_rgb = _hex_to_rgb(_C["panel_bg"])
        accent_rgb = _hex_to_rgb(_C["accent"])
        css = ("<style>html,body{width:100%;height:100%;margin:0;padding:0;"
               f"background:{_C['window_bg']};}}"
               ".folium-map{position:absolute!important;top:0;left:0;right:0;bottom:0;"
               "width:auto!important;height:auto!important;}"
               f".leaflet-container{{background:{_C['window_bg']}!important;}}"
               ".leaflet-image-layer{image-rendering:pixelated;"
               "image-rendering:crisp-edges;}"
               ".leaflet-container,.leaflet-grab,"
               ".leaflet-dragging .leaflet-grab{cursor:default!important;}"
               ".leaflet-control-zoom{border:none!important;"
               "border-radius:10px!important;overflow:hidden;"
               "box-shadow:0 6px 18px rgba(0,0,0,.5)!important;}"
               f".leaflet-control-zoom a{{background:{_C['panel_bg']}!important;"
               f"color:{_C['accent']}!important;border:none!important;"
               f"border-bottom:1px solid {_C['border']}!important;"
               "width:30px!important;height:30px!important;"
               "line-height:30px!important;font-size:16px!important;}}"
               f".leaflet-control-zoom a:hover{{background:{_C['accent']}!important;"
               f"color:{_C['window_bg']}!important;}}"
               ".leaflet-control-attribution{"
               "background:rgba(0,0,0,.45)!important;"
               f"color:{_C['text_gray']}!important;"
               "border-radius:6px 0 0 0!important;font-size:10px!important;"
               "padding:1px 6px!important;}"
               f".leaflet-control-attribution a{{color:{_C['text_gray']}!important;}}"
               ".cwatm-marker{width:22px;height:22px;}"
               ".cwatm-marker-dot{position:absolute;left:50%;top:50%;"
               "transform:translate(-50%,-50%);width:16px;height:16px;"
               "border-radius:50%;background:#ff4433;border:3px solid #fff;"
               "box-shadow:0 3px 10px rgba(0,0,0,.55),"
               "0 0 0 5px rgba(255,68,51,.22);}"
               "</style>")
        if "</head>" in html:
            html = html.replace("</head>", css + "</head>", 1)
        else:
            html = css + html

        html = _inline_remote_assets(html)

        helper = "<script>\n%s\n</script>" % js
        if "</html>" in html:
            html = html.replace("</html>", helper + "\n</html>", 1)
        else:
            html = html + helper
        return html

    def _helper_js(self, map_var, ups_var):
        """Topographic WMS basemap + click marker + document.title click
        bridge - same technique as academy_outlet_map._helper_js, its own
        NILETEST prefix, and deliberately no suggestion marker (see the
        module docstring)."""
        tpl = r"""
        (function(){
          var MAP=__MAP__;
          window._map=MAP;
          MAP.setMaxBounds([[-90,-180],[90,180]]);
          MAP.options.maxBoundsViscosity=1.0;
          MAP.setMinZoom(2);
          window._tile=L.tileLayer.wms('osmtile://wms/service',
            {layers:__LAYER__,format:'image/png',version:'1.1.1',
             transparent:false,maxZoom:19,
             attribution:'(c) OpenStreetMap contributors'}).addTo(MAP);
          window._tile.bringToBack();
          window.pickMarker=null;
          window.setPick=function(lat,lon){
            if(window.pickMarker){MAP.removeLayer(window.pickMarker);}
            var icon=L.divIcon({className:'',
              html:'<div class="cwatm-marker"><div class="cwatm-marker-dot">'+
                   '</div></div>',
              iconSize:[22,22],iconAnchor:[11,11]});
            window.pickMarker=L.marker([lat,lon],{icon:icon}).addTo(MAP);};
          window.clearPick=function(){
            if(window.pickMarker){MAP.removeLayer(window.pickMarker);
              window.pickMarker=null;}};
          // the found basin, under the upstream-area map (which stays on top)
          window._ups=__UPS__;
          window.basinLayer=null;
          window.showBasin=function(uri,b){window.clearBasin();
            window.basinLayer=L.imageOverlay(uri,b,{opacity:1.0,interactive:false,
              className:'leaflet-image-layer'}).addTo(MAP);
            if(window._ups){window._ups.bringToFront();}};
          window.clearBasin=function(){
            if(window.basinLayer){MAP.removeLayer(window.basinLayer);
              window.basinLayer=null;}};
          // the least zoom at which the world (360 deg) is at least as wide as
          // the window - zoomed out further, the map would show the same part
          // on the left and the right; it is the min zoom, so fitBounds of the
          // global view lands exactly there
          window.worldOnceZoom=function(){
            var w=MAP.getSize().x, z=0;
            while(z<6 && MAP.project([0,180],z).x-MAP.project([0,-180],z).x<w){z++;}
            return z;};
          window.frame=function(b){MAP.invalidateSize();
            MAP.setMinZoom(window.worldOnceZoom());
            MAP.fitBounds(b,{padding:[30,30]});};
          // the stamp makes a repeated click on the same spot a new title
          MAP.on('click',function(e){
            document.title='NILETEST '+e.latlng.lng+'|'+e.latlng.lat+'|'+Date.now();});
          setTimeout(function(){window.frame(__BOUNDS__);},300);
        })();
        """
        return (tpl.replace("__MAP__", map_var)
                   .replace("__UPS__", ups_var)
                   .replace("__LAYER__", repr(_BASEMAP_WMS_LAYER))
                   .replace("__BOUNDS__", self._view_js()))

    def _view_js(self):
        """The view bounds as a JS array literal. Plain floats via json - a repr
        of numpy numbers reads ``np.float64(…)`` under numpy 2, which is a JS
        syntax error: the frame call then silently never runs (no zoom)."""
        return json.dumps([[float(v) for v in corner] for corner in self._view])

    def _on_loaded(self, ok):
        if not ok:
            log.warning("Nile field test map page failed to load")
            return
        self._map_ready = True
        queued, self._js_queue = self._js_queue, []
        for code in queued:
            self._js(code)

    def _js(self, code):
        if not self._map_ready:
            self._js_queue.append(code)
            return
        try:
            self.web_view.page().runJavaScript(code)
        except Exception:
            log.debug("Nile field test JS failed", exc_info=True)

    # ------------------------------------------------------------- grading

    # --------------------------------------------------------------- basins

    def _choose_basin(self):
        """Draw a basin (never the one just shown), compute its target cells and
        framing, and set the texts."""
        # from SHAPE_MODE_POINTS on the game changes (Level 2) - and stays
        # changed, even if the score falls below it again
        if self._score >= SHAPE_MODE_POINTS:
            self._shape_mode = True
        basins = ([b for b in self._basins if b["rank"] <= self._level2_pool()]
                  if self._shape_mode else self._basins) or self._basins
        pool = [b for b in basins if b is not self._basin] or basins
        self._basin = random.choice(pool)
        b = self._basin
        self._targets = target_cells(self._basin_data, self._lats, self._lons,
                                     b["lat"], b["lon"])
        self._picked_ok = False
        self._basin_found = False
        self._misses = 0
        self._js("if(window.clearBasin) clearBasin();")
        if self._shape_mode:
            self._choose_shape_question(b)
            return
        self.shape_label.setVisible(False)
        # an expert (GLOBAL_VIEW_POINTS and up) gets no framing - the whole world
        global_view = self._score >= GLOBAL_VIEW_POINTS
        self._view = [list(p) for p in GLOBAL_VIEW] if global_view else view_bounds(b)
        self.title_label.setText(f"Locate the outlet of the {b['name']}")
        self.instructions_label.setText(
            f"The {b['name']} basin covers about {b['size_km2']:,.0f} km². Surface "
            "water flows downstream - click the point where the river ends: at the "
            "sea, or, for an inland basin, in its lake or sink. Land on one of the "
            f"{TARGET_CELLS} biggest cells of the basin to pass. The same idea as the "
            "Danube exercise, but this time nothing on the map points at the answer."
            + (f" From {GLOBAL_VIEW_POINTS} points on you get the whole world map - "
               "find the basin yourself." if global_view else ""))
        self.status_label.setText("Awaiting target …")

    def _choose_shape_question(self, b):
        """Shape mode: the basin's own area map, without its name; framed around
        the basin again (zooming in is back), off-centre."""
        cells = self._cells_of(b)
        self._basin_cells, self._basin_cell_set = cells, set(cells)
        # framed around the outlet like Level 1's start, but zoomed out further
        # (LEVEL2_ZOOM_OUT); from LEVEL2_GLOBAL_POINTS on the whole world map
        if self._score >= LEVEL2_GLOBAL_POINTS:
            self._view = [list(p) for p in GLOBAL_VIEW]
        else:
            self._view = view_bounds(b, scale=LEVEL2_ZOOM_OUT)
        try:
            from PySide6.QtGui import QPixmap
            img = basin_shape_image(self._lats, self._lons, cells, BASIN_ORANGE,
                                    _SHAPE_W, _SHAPE_H, values=self._basin_data)
            self.shape_label.setPixmap(QPixmap.fromImage(img))
        except Exception:
            log.warning("basin shape could not be drawn", exc_info=True)
        self.shape_label.setVisible(True)
        self.title_label.setText("Level 2 - which river basin is this? Find it on the map")
        self.instructions_label.setText(
            f"You see the shape of a river basin (right, north up, with its rivers) - "
            f"about {b['size_km2']:,.0f} km², one of the {self._level2_pool()} biggest - but "
            "not its name. Click anywhere inside that basin on the map: a hit earns "
            f"{FOUND_POINTS} points, a miss costs the distance to the basin in "
            "kilometers (at most 1000, then 500, then 250).")
        self.status_label.setText("Awaiting target …")

    def _level2_pool(self):
        """How many of the biggest basins Level 2 draws from: LEVEL2_POOL, all of
        them (_POOL_SIZE) from LEVEL2_ALL_POINTS on."""
        return _POOL_SIZE if self._score >= LEVEL2_ALL_POINTS else LEVEL2_POOL

    def _cells_of(self, b):
        """The basin's cells (``basin_cells``), computed once per basin."""
        cells = self._basin_cell_cache.get(b["name"])
        if cells is None:
            cells = basin_cells(self._basin_data, self._lats, self._lons,
                                b["lat"], b["lon"])
            self._basin_cell_cache[b["name"]] = cells
        return cells

    def _show_found_basin(self):
        """The found basin's area on the map, under the upstream-area overlay."""
        try:
            cells = self._cells_of(self._basin)
            rgba = basin_mask_rgba(np.asarray(self._basin_data).shape, cells,
                                   BASIN_ORANGE, alpha=FOUND_BASIN_ALPHA)
            uri = _rgba_to_datauri(_orient(rgba, self._lats, self._lons))
            west, east, south, north = self._grid_bounds()
            self._js("if(window.showBasin) showBasin(%s,%s);"
                     % (json.dumps(uri), json.dumps([[south, west], [north, east]])))
        except Exception:
            log.warning("found basin could not be drawn", exc_info=True)

    def _next_basin(self):
        """Another basin: new question, new framing, the old pick removed."""
        if not self._basins or getattr(self, "_basin_data", None) is None:
            return
        skipped = not self._basin_found
        if skipped:
            self._failed_count += 1
            # giving up on a basin costs SKIP_PENALTY (before the next basin is
            # drawn, so the global-view threshold sees the score after it)
            self._add_points(-SKIP_PENALTY)
        self._choose_basin()
        if skipped:
            self.status_label.setText(
                f"Basin skipped: -{SKIP_PENALTY} points. Awaiting target …")
        self._js("if(window.clearPick) clearPick();")
        self._js("if(window.frame) frame(%s);" % self._view_js())

    def _on_web_title(self, title):
        if not title.startswith("NILETEST ") or not self._targets:
            return
        try:
            lon_s, lat_s = title[9:].split("|")[:2]
            lon, lat = float(lon_s), float(lat_s)
        except Exception:
            return
        self._js("if(window.setPick) setPick(%f,%f);" % (lat, lon))
        if self._shape_mode:
            self._grade_shape_pick(lat, lon)
            return
        self._picked_ok = is_target(self._lats, self._lons, lat, lon, self._targets)
        # a found basin is scored once; clicks after that are graded but free
        scored = not self._basin_found
        if self._picked_ok:
            self.status_label.setText(
                f"✓ Target confirmed - that is the outlet of the {self._basin['name']}."
                + (f" +{FOUND_POINTS} points" if scored else ""))
            if scored:
                self._basin_found = True
                self._found_count += 1
                self._show_found_basin()
                self._add_points(FOUND_POINTS)
        else:
            km = distance_km(lat, lon, self._basin["lat"], self._basin["lon"])
            penalty = capped_penalty(km, self._misses)
            if scored:
                self._misses += 1
                self._wrong_clicks += 1
                self._max_miss_km = max(self._max_miss_km, km)
            self.status_label.setText(
                f"✗ Not the outlet - you are {km:,.0f} kilometers away."
                + (f" -{penalty} points" if scored else ""))
            if scored:
                self._add_points(-penalty)

    def _grade_shape_pick(self, lat, lon):
        """Shape mode: a click on any cell of the basin wins; a miss costs the
        distance (km) to the nearest cell of the basin."""
        r, c = _nearest_index(self._lats, self._lons, lat, lon)
        self._picked_ok = (r, c) in self._basin_cell_set
        scored = not self._basin_found
        if self._picked_ok:
            self.status_label.setText(
                f"✓ Found - that is the {self._basin['name']} basin."
                + (f" +{FOUND_POINTS} points" if scored else ""))
            if scored:
                self._basin_found = True
                self._found_count += 1
                self._show_found_basin()
                self._add_points(FOUND_POINTS)
        else:
            km = distance_to_cells_km(self._lats, self._lons, self._basin_cells, lat, lon)
            penalty = capped_penalty(km, self._misses)
            if scored:
                self._misses += 1
                self._wrong_clicks += 1
                self._max_miss_km = max(self._max_miss_km, km)
            self.status_label.setText(
                f"✗ Not inside the basin - you are {km:,.0f} kilometers away from it."
                + (f" -{penalty} points" if scored else ""))
            if scored:
                self._add_points(-penalty)

    # ---------------------------------------------------------- score / highscore
    #
    # Two numbers next to the score: the Highscore = the record of ALL users with
    # its holder's initials (Supabase, public), and the learner's own best ("Your
    # best": the profile while logged in, this computer otherwise - never merged).

    def _add_points(self, points):
        # the score never goes below 0
        self._score = max(0, self._score + int(points))
        self.points_label.setText(f"Points: {self._score}")
        submit = False
        if self._score > self._best:
            self._best = self._score
            if self._remote:
                submit = self._best_known      # unknown: settled on the answer
            else:
                _settings().setValue(HIGHSCORE_KEY, int(self._best))
        if self._record_known and self._score > self._record:
            submit = self._claim_record() or submit
        self._show_scores()
        if submit:
            self._submit_score()
        if (points > 0 and not self._shape_mode and not self._level2_shown
                and self._score >= SHAPE_MODE_POINTS):
            # after this click is fully handled (the initials box comes first)
            self._level2_shown = True
            QTimer.singleShot(0, self, self._level_up)

    def _level_up(self):
        """Level 2 reached: the congratulation (with the Danube's basin map), then
        straight on to a Level 2 basin - this one is found, so no skip penalty."""
        image = None
        try:
            danube = next((b for b in self._basins if b["name"] == "Danube"), None)
            if danube is not None:
                image = basin_shape_image(self._lats, self._lons, self._cells_of(danube),
                                          BASIN_ORANGE, 340, 220, values=self._basin_data)
        except Exception:
            log.warning("Danube basin map for the level-up failed", exc_info=True)
        show_level2_message(self, image)
        if self._score >= SHAPE_MODE_POINTS:
            self._next_basin()

    def _claim_record(self):
        """The score beat the record of all users. Logged in: ask for the initials
        (once per window - a later record keeps them) and take the record; logged
        out it cannot be sent, so say how to claim it. True = send it."""
        if not self._remote:
            if not self._login_hint_shown:
                self._login_hint_shown = True
                self.status_label.setText(
                    self.status_label.text()
                    + " - a new highscore! Log in to put your initials on it.")
            return False
        if self._my_initials is None:
            self._my_initials = clean_initials(
                ask_initials(self, self._last_initials()))
            if self._my_initials:
                # only a suggestion for the next time
                _settings().setValue(LAST_INITIALS_KEY, self._my_initials)
        self._record, self._record_initials = self._score, self._my_initials
        return True

    def _submit_score(self):
        if self._account_worker is None:
            return
        try:
            self._account_worker.submit("field_test_submit_score", self._score,
                                        self._my_initials or None)
        except Exception:
            log.warning("field test score not sent", exc_info=True)

    def _show_scores(self):
        if self._record_known:
            text = f"Highscore: {self._record} {self._record_initials}".rstrip()
        else:
            text = "Highscore: …" if self._record_pending else "Highscore: –"
        self.highscore_label.setText(text)
        self.best_label.setText(f"Your best: {self._best}" if self._best_known
                                else "Your best: …")

    def _last_initials(self):
        """The initials typed last on this computer - only a suggestion for the box."""
        return clean_initials(str(_settings().value(LAST_INITIALS_KEY, "") or ""))

    def _logged_in(self):
        status = getattr(self.mw, "account_status", None)
        try:
            return callable(status) and status() is not None
        except Exception:
            log.debug("account status unavailable", exc_info=True)
            return False

    def _init_highscore(self):
        """Ask the account server for the record (and, logged in, the own best);
        the own best of a logged-out learner is the one stored on this computer."""
        self._remote = self._logged_in()
        if not self._remote:
            try:
                self._best = max(0, int(_settings().value(HIGHSCORE_KEY, 0)))
            except (TypeError, ValueError):
                self._best = 0
        worker = None
        if self.mw is not None and hasattr(self.mw, "account_worker"):
            try:
                from src.gui.utils import account_config
                if self._remote or account_config.is_configured():
                    worker = self.mw.account_worker()
                    worker.succeeded.connect(self._on_account_succeeded)
                    worker.failed.connect(self._on_account_failed)
            except Exception:
                log.warning("field test highscore: account unavailable", exc_info=True)
                worker = None
        self._account_worker = worker
        if worker is not None:
            self._record_pending = True
            if self._remote:
                self._best_known = False
                worker.submit("get_field_test_highscore")   # own best + record
            else:
                worker.submit("get_field_test_record")
        elif self._remote:
            self._remote = False          # no way to reach the account
        self._show_scores()

    def _on_account_succeeded(self, op, result):
        if op not in _HIGHSCORE_OPS or not isinstance(result, dict):
            return
        submit = False
        if "highscore" in result:
            try:
                server_best = int(result.get("highscore") or 0)
            except (TypeError, ValueError):
                server_best = 0
            was_known, self._best_known = self._best_known, True
            if self._score > server_best and not was_known:
                submit = True                 # played past it before the answer
            self._best = max(self._best, server_best)
        if "record_score" in result:
            try:
                server_record = int(result.get("record_score") or 0)
            except (TypeError, ValueError):
                server_record = 0
            self._record_known, self._record_pending = True, False
            self._record = server_record
            self._record_initials = clean_initials(
                str(result.get("record_initials") or ""))
            if self._score > server_record:
                submit = self._claim_record() or submit
        self._show_scores()
        if submit and self._remote:
            self._submit_score()

    def _on_account_failed(self, op, code, message):
        if op not in _HIGHSCORE_OPS:
            return
        log.info("field test highscore %s failed: %s", op, code)
        self._record_pending = False
        if not self._best_known:
            self._best_known = True           # show at least this session's best
        self._show_scores()

    def _disconnect_account(self):
        worker, self._account_worker = self._account_worker, None
        if worker is None:
            return
        for signal, slot in ((worker.succeeded, self._on_account_succeeded),
                             (worker.failed, self._on_account_failed)):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                log.debug("field test: account signal already disconnected",
                          exc_info=True)

    def done(self, result):
        # the funnel of End test (close), the X button and Esc
        self._disconnect_account()
        super().done(result)

    def closeEvent(self, event):
        self._disconnect_account()
        super().closeEvent(event)

    def statistics(self):
        """The game so far, for End test: level, points, basins found / failed,
        wrong clicks, the biggest discrepancy (km), own best + the record (None
        while unknown) and the Field Test badge they give (``field_test_tier``)."""
        failed = self._failed_count
        if not self._basin_found and self._misses:
            failed += 1                    # the basin open at the end, tried and missed
        best = self._best if self._best_known else None
        record = self._record if self._record_known else None
        from src.gui.utils import account_shop
        return {
            "level": 2 if self._shape_mode else 1,
            "points": self._score,
            "found": self._found_count,
            "failed": failed,
            "wrong_clicks": self._wrong_clicks,
            "max_miss_km": self._max_miss_km,
            "best": best,
            "record": record,
            "logged_in": bool(self._remote),
            "badge": (account_shop.field_test_tier(best, record)
                      if self._remote and best is not None else None),
        }

    def _on_end_clicked(self):
        """End test: the statistics window, then the Field Test closes. At least one
        basin found passes Level 1 of CWatM Academy (``passed``)."""
        stats = self.statistics()
        show_end_statistics(self, stats)
        if stats["found"]:
            self.passed.emit()
        self.close()


# the window's earlier name, kept for callers (academy_outlet_map)
NileFieldTestWindow = BasinFieldTestWindow