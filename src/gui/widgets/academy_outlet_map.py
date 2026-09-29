"""CWatM Academy - Level 1's interactive exercise: pick a catchment outlet on a
global map.

Loads the bundled global upstream-area (flow accumulation) grid
``assets/academy_ups_30min.nc`` - from the iiasa/CWatM-Earth-30min repository,
30 arcmin / 360x720 - and renders it log-scaled over the same terrestris WMS
basemap endpoint Tools ▸ Show Basin uses, on its muted "Topographic" layer
(country/city labels for orientation, without the loud roads/colours of full
OSM-WMS competing with the overlay - a NASA GIBS night-lights basemap was
tried first and dropped: it hid the river network and was noticeably laggy).
Same technique as Show Basin (``basin_viewer2.py``: WMS basemap tiles and the
map page itself both served through the shared ``osmtile://`` scheme handler
so they survive a proxy that blocks Chromium's own network, and a Leaflet
click is read back into Python by hijacking ``document.title`` - see
``basin_viewer2._helper_js``/``_on_web_title`` for the original), but
deliberately standalone: unlike Show Basin, this widget never reads the live
main window's MaskMap/Gauges boxes to seed its own markers, or any settings
file - it is a self-contained teaching exercise, not a real run's basin. It
DOES, on Confirm, *write* the picked point into the main window's MaskMap and
Gauges fields - see ``_on_confirm_clicked`` - the same one-line write Show
Basin's own Copy Mask / Create+Copy Gauge actions perform, just automatic
here - and then raises the main window and hands off to the floating
"Torus" guide (``academy_guide.TorusGuideBubble``), which scrolls to and
points at those two lines in turn (Next steps to Gauges), explaining each
one right where it lives in the real settings file rather than repeating
that explanation inside this dialog - see ``_show_written_lines`` and
``academy_guide.settings_line_point``/``goto_settings_key`` (shared with
Level 2's own settings-file targets; the key->line lookup is the same one
Check Data's double-click-to-jump uses). Finishing the guide is the end of
the *teaching* - Level 1 itself isn't done until the graded Field Test
passes: ``_on_guide_finished`` shows a "will you accept this mission"
briefing (``academy_guide.show_mission_briefing``) for locating the Nile's
outlet unaided, then ``_start_nile_field_test`` opens
``academy_field_test.NileFieldTestWindow`` for the actual graded pick; only
once that passes (``_on_nile_field_test_passed``) does the centred
celebration (``academy_guide.show_level_celebration``) show and Level 2
begin. If nothing is open in the main editor yet, Confirm loads a bundled
example settings file first
(``assets/academy_settings_danube_30min.ini``, via
``main_window.load_recent_file`` - the exact path File ▸ Load .ini itself
uses) so there is a real MaskMap/Gauges line to write into and point at - a
stand-in for the actual CWatM-Earth-30min repository's own default settings,
which Academy is meant to connect to directly once that integration exists.

The map itself is deliberately "designed" rather than a raw Leaflet dump: it
renders as a rounded, shadowed card inset from the widget's edges (CSS in
_build_map_html - simpler and more reliable than fighting Qt/WebEngine's own
widget clipping), with the Leaflet zoom/attribution chrome restyled to match,
a pulsing amber marker suggesting the Danube's outlet, a small legend card
(bottom left) for the accumulation colour ramp, and the accumulation
transparency slider itself as an on-map control (top right, plain HTML
``<input type="range">`` - see ``_helper_js``'s '#cwatmOpacityRange' listener,
entirely client-side, no Qt widget/round trip involved). The legend card is
also the natural spot for a future layers/visibility control, should this
exercise ever need to let a learner hide/reveal map elements.
"""

import os
import re

import numpy as np

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QGraphicsDropShadowEffect,
)
from PySide6.QtCore import Qt, QUrl, QByteArray, QBuffer, Signal
from PySide6.QtGui import QImage, QColor

from src.gui.utils import theme
from src.gui.utils import display_format
from src.gui.utils.assets import asset_path
from src.gui.utils.gui_log import get_logger

log = get_logger("academy_outlet_map")

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    import folium
    _MAP_AVAILABLE = True
    _MAP_IMPORT_ERROR = ""
except Exception as _e:  # pragma: no cover - import guard
    _MAP_AVAILABLE = False
    _MAP_IMPORT_ERROR = f"{type(_e).__name__}: {_e}"

_C = theme.theme_colors("mikhail")

# The map's own floating labels (legend title/labels, opacity slider label -
# not the surrounding Qt UI) use Calibri, with the usual cross-platform
# fallbacks since Academy also runs from source on Linux/Mac.
_MAP_LABEL_FONT = "Calibri, 'Segoe UI', Candara, sans-serif"

_UPS_ASSET = "academy_ups_30min.nc"
# A real, working CWatM-Earth-30min settings file (the Danube scenario) to
# load if the learner confirms an outlet with nothing open in the main
# editor - otherwise there is no MaskMap/Gauges line to write into or jump
# to. A stand-in for now (its PathRoot/PathMeteo/etc. point at the uploader's
# own machine, so a run of it won't resolve elsewhere) until Academy connects
# directly to the iiasa/CWatM-Earth-30min repository.
_DEFAULT_SETTINGS_ASSET = "academy_settings_danube_30min.ini"
# terrestris's muted topographic style (Show Basin's "Topographic" option -
# see basin_viewer2._B2_PROVIDERS), forwarded through the shared
# osmtile://wms/service proxy. Keeps light gray country/city labels for
# orientation (the plain SRTM hillshade tried before this had none, which felt
# too bare) without the loud roads/buildings/colors of full OSM-WMS that used
# to visually compete with the ups.nc accumulation overlay.
_BASEMAP_WMS_LAYER = "TOPO-OSM-WMS"

# The map opens framed on the whole Danube basin rather than the whole globe -
# a concrete, recognisable catchment the explanation panel refers to directly,
# instead of an empty world map with no obvious first move. A pulsing amber
# marker suggests the actual outlet (the Black Sea delta) within that view -
# the same coordinate used as the worked example throughout this GUI's own
# sample settings (e.g. the Watercycle sunburst's demo station) - so a learner
# sees the whole catchment the suggestion belongs to before clicking it.
_DEFAULT_LON = 29.618
_DEFAULT_LAT = 45.261

# Danube basin bounding box (south, west, north, east) - approximate, source
# to mouth (Donaueschingen, Germany to the Black Sea delta) and the basin's
# full north-south spread (the Vltava basin in Czechia down to the
# Sava/Drina basin in Montenegro/Bosnia). Only used to frame the initial map
# view, never for any calculation.
_BASIN_BOUNDS = [[42.0, 7.5], [50.8, 29.9]]
# Initial folium zoom before the JS fitBounds() below takes over - just needs
# to be roughly right so there is no visible jump during the 300ms it waits
# for the WebEngine view to settle.
_DEFAULT_ZOOM = 5

# The accumulation overlay's colour ramp, shared between _ups_rgba (the
# actual image) and the on-map legend, so the two can never drift apart.
_UPS_COLOR_LOW = (222, 235, 247)    # light blue - low accumulation
_UPS_COLOR_HIGH = (8, 48, 107)      # dark blue - rivers/outlets


def _hex_to_rgb(hex_color):
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_css(rgb):
    """'r,g,b' for embedding in a CSS rgb()/rgba() function."""
    return "%d,%d,%d" % tuple(rgb)


def _add_card_shadow(widget):
    """A soft drop shadow behind a card-style QFrame - Qt stylesheets have no
    box-shadow, so this is how the map's own control/explanation panels get
    the same 'floating card' look the map's HTML/CSS chrome uses."""
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(28)
    eff.setOffset(0, 6)
    eff.setColor(QColor(0, 0, 0, 170))
    widget.setGraphicsEffect(eff)


def _orient(rgba, lats, lons):
    """Flip so the top row is north and the left column is west - same rule as
    basin_viewer.BasinDataHelpers._orient, just taking lats/lons as arguments
    instead of reading them off self."""
    lats = np.asarray(lats)
    lons = np.asarray(lons)
    if lats.ndim == 1 and lats.size > 1 and lats[0] < lats[-1]:
        rgba = rgba[::-1]
    if lons.ndim == 1 and lons.size > 1 and lons[0] > lons[-1]:
        rgba = rgba[:, ::-1]
    return rgba


def _ups_rgba(basin_data, lats, lons):
    """RGBA image of the upstream-area grid, blue by log(area) - same ramp as
    Show Basin's own ups overlay (basin_viewer.BasinDataHelpers._build_ups_rgba),
    tuned for the topographic WMS basemap underneath it.

    Alpha follows the same normalised log(area), not a hard valid/invalid
    cutoff - a cell with zero or very low accumulation fades to fully
    transparent instead of drawing a flat, opaque low colour, so only the
    actually significant part of the river network stands out over the
    basemap (Show Basin's own overlay is opaque everywhere valid; this map
    wants the real rivers/labels underneath to show through). A gentle gamma
    (<1) keeps the mid-range of the network visible rather than only the very
    largest rivers."""
    basin = np.asarray(basin_data, dtype=float)
    H, W = basin.shape
    valid = np.isfinite(basin) & (basin > 0)
    if valid.any():
        v = np.log1p(np.where(valid, basin, 0.0))
        vmin, vmax = float(v[valid].min()), float(v[valid].max())
        norm = np.clip((v - vmin) / (vmax - vmin + 1e-9), 0.0, 1.0)
    else:
        norm = np.zeros((H, W))
    c0 = np.array(_UPS_COLOR_LOW, dtype=float)
    c1 = np.array(_UPS_COLOR_HIGH, dtype=float)
    col = (c0 * (1 - norm[..., None]) + c1 * norm[..., None]).astype(np.uint8)
    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    rgba[..., :3] = col
    alpha = np.where(valid, np.power(norm, 0.6) * 255.0, 0.0)
    rgba[..., 3] = alpha.astype(np.uint8)
    return _orient(rgba, lats, lons)


def _ocean_rgba(basin_data, lats, lons):
    """A flat, muted overlay painted only over ocean/nodata cells (basin<=0),
    to suppress whatever colour the relief WMS layer gives the ocean (a hillshade
    layer's ocean fill can be more visually prominent than the land relief
    itself, which is the opposite of what this exercise cares about - only
    land/catchments matter here). Transparent everywhere else, so land is
    completely untouched. Coloured to match the page background (Mikhail
    black) so the ocean recedes rather than drawing attention."""
    basin = np.asarray(basin_data, dtype=float)
    H, W = basin.shape
    ocean = ~(np.isfinite(basin) & (basin > 0))
    bg = _C["window_bg"].lstrip("#")
    r, g, b = (int(bg[i:i + 2], 16) for i in (0, 2, 4))
    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    rgba[..., 0], rgba[..., 1], rgba[..., 2] = r, g, b
    rgba[..., 3] = np.where(ocean, 235, 0).astype(np.uint8)
    return _orient(rgba, lats, lons)


def _rgba_to_datauri(rgba):
    """Encode an RGBA numpy array to a base64 PNG data URI (via QImage) - same
    helper as basin_viewer.BasinDataHelpers._rgba_to_datauri."""
    import base64
    H, W = rgba.shape[:2]
    buf = np.ascontiguousarray(rgba).tobytes()
    qimg = QImage(buf, W, H, 4 * W, QImage.Format_RGBA8888).copy()
    ba = QByteArray()
    b = QBuffer(ba)
    b.open(QBuffer.WriteOnly)
    qimg.save(b, "PNG")
    b.close()
    return "data:image/png;base64," + base64.b64encode(bytes(ba)).decode("ascii")


def _image_overlay(data_uri, bounds, opacity, name):
    """A folium ImageOverlay carrying a data: URI - see
    basin_viewer2.BasinWindow2._image_overlay for why .url is set after
    construction rather than passed to image=."""
    ov = folium.raster_layers.ImageOverlay(
        image="https://cwatm.invalid/overlay.png", bounds=bounds,
        opacity=opacity, mercator_project=False, pixelated=True, name=name)
    ov.url = data_uri
    return ov


def load_ups_grid(path=None):
    """(basin_data, lats, lons) for the bundled (or a given) ups.nc, via the
    same generic NetCDF loader Show Basin uses. None, None, None on failure."""
    from src.gui.widgets.basin_viewer import BasinViewer
    path = path or asset_path(_UPS_ASSET)
    if not os.path.exists(path):
        log.warning("academy ups.nc not found at %s", path)
        return None, None, None
    return BasinViewer(None)._load_netcdf_data(path)


class OutletMapWidget(QWidget):
    """Global ups.nc map + transparency slider + Confirm/Continue flow. Emits
    ``outlet_picked(lon, lat)`` once the explanation has been shown and the
    learner clicks through to the next level."""

    outlet_picked = Signal(float, float)

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.mw = main_window
        self._picked = None      # (lon, lat) of the last click
        self._confirmed = False  # Confirm already clicked -> button becomes Continue
        self._map_ready = False
        self._js_queue = []
        # The slider controls the accumulation overlay only - the basemap
        # itself always stays fully opaque underneath it.
        self._overlay_opacity = max(0.0, min(1.0, display_format.get_transparency() / 100.0))
        self._build_ui()
        if _MAP_AVAILABLE:
            self._load_and_show()
        else:
            self.info_label.setText(
                f"Map unavailable: {_MAP_IMPORT_ERROR}\n"
                "(needs folium and PySide6 QtWebEngine)")

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        body = QHBoxLayout()
        body.setSpacing(16)
        outer.addLayout(body, 1)

        # Left: just the map - its own card styling, legend and opacity
        # slider are all drawn in HTML/CSS (see _build_map_html), so it
        # floats naturally against this widget's background with nothing
        # else needed underneath it.
        if _MAP_AVAILABLE:
            self.web_view = QWebEngineView()
            self.web_view.titleChanged.connect(self._on_web_title)
            body.addWidget(self.web_view, 3)
        else:
            self.web_view = None

        # Right: two stacked cards - a static Briefing (the lesson content)
        # on top, and the live Mission (the task's evolving status + the
        # Confirm/Continue action) below it. Keeping "what this exercise is
        # about" and "what to do right now" visually separate, rather than
        # one growing block of text under the map.
        right = QVBoxLayout()
        right.setSpacing(16)
        body.addLayout(right, 2)

        brief_panel = QFrame()
        brief_panel.setObjectName("acadPanel")
        brief_lay = QVBoxLayout(brief_panel)
        brief_lay.setContentsMargins(18, 16, 18, 16)
        brief_lay.setSpacing(8)
        _add_card_shadow(brief_panel)
        brief_tag = QLabel("BRIEFING")
        brief_tag.setObjectName("acadTag")
        brief_lay.addWidget(brief_tag)
        title = QLabel("Pick the outlet of your catchment")
        title.setObjectName("acadLessonTitle")
        title.setWordWrap(True)
        brief_lay.addWidget(title)
        explain = QLabel(
            "Surface water usually flows from upstream to downstream.\n\n"
            "The map on the left shows the upstream area for each point - "
            "the more blue a cell is, the more cells are upstream of it.\n\n"
            "Choose the most downstream point of the area you want to "
            "simulate, its outlet. Everything upstream of that point is "
            "your watershed: every drop of rain that falls anywhere in the "
            "watershed and continues to flow as surface water will "
            "eventually flow through this outlet.")
        explain.setObjectName("acadExplain")
        explain.setWordWrap(True)
        explain.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        brief_lay.addWidget(explain)
        right.addWidget(brief_panel, 3)

        mission_panel = QFrame()
        mission_panel.setObjectName("acadPanel")
        mission_lay = QVBoxLayout(mission_panel)
        mission_lay.setContentsMargins(18, 16, 18, 16)
        mission_lay.setSpacing(8)
        _add_card_shadow(mission_panel)
        mission_tag = QLabel("MISSION")
        mission_tag.setObjectName("acadTag")
        mission_lay.addWidget(mission_tag)

        self.info_label = QLabel("Click on the map to pick a point.")
        self.info_label.setObjectName("acadWelcomeStatus")
        self.info_label.setWordWrap(True)
        self.info_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        mission_lay.addWidget(self.info_label, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.confirm_button = QPushButton("Confirm this outlet")
        self.confirm_button.setObjectName("acadComplete")
        self.confirm_button.setEnabled(False)
        self.confirm_button.clicked.connect(self._on_confirm_clicked)
        btn_row.addWidget(self.confirm_button)
        mission_lay.addLayout(btn_row)
        right.addWidget(mission_panel, 2)

    # ------------------------------------------------------------- map build

    def _load_and_show(self):
        basin_data, lats, lons = load_ups_grid()
        if basin_data is None:
            self.info_label.setText("Could not load the upstream-area map.")
            return
        self._basin_data, self._lats, self._lons = basin_data, lats, lons
        try:
            html = self._build_map_html()
        except Exception:
            log.warning("academy outlet map build failed", exc_info=True)
            self.info_label.setText("Could not build the map.")
            return
        try:
            from src.gui.widgets.basin_viewer import _get_tile_handler
            self._tile_handler = _get_tile_handler()
            self._tile_handler.set_page("academy_outlet", html)
            profile = self.web_view.page().profile()
            try:
                profile.removeUrlSchemeHandler(self._tile_handler)
            except Exception:
                log.debug("_load_and_show: ignored", exc_info=True)
            profile.installUrlSchemeHandler(b"osmtile", self._tile_handler)
            self.web_view.loadFinished.connect(self._on_loaded)
            self.web_view.load(QUrl("osmtile://academy_outlet/"))
        except Exception:
            log.warning("academy outlet map page serving failed", exc_info=True)
            self.info_label.setText("Could not display the map.")

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

        # control_scale=False: Leaflet's own km/mi scale bar docks bottom-left,
        # the same corner as our legend card, and rendered on top of it
        # (later-added DOM element, so it wins ties at the same z-index) -
        # the legend already carries what a learner needs to know here.
        m = folium.Map(location=[46.4, 18.7], zoom_start=_DEFAULT_ZOOM,
                       crs="EPSG4326", tiles=None, control_scale=False, zoom_control=True)
        # Ocean-suppression layer first (under the accumulation overlay), fixed
        # opacity - always suppressed, not tied to the accumulation slider.
        ocean = _image_overlay(
            _rgba_to_datauri(_ocean_rgba(self._basin_data, self._lats, self._lons)),
            bounds, 1.0, "ocean")
        ocean.add_to(m)
        ups = _image_overlay(
            _rgba_to_datauri(_ups_rgba(self._basin_data, self._lats, self._lons)),
            bounds, self._overlay_opacity, "ups")
        ups.add_to(m)

        js = self._helper_js(m.get_name(), ups.get_name())
        html = m.get_root().render()
        html = _strip_unused_assets(html)

        panel_rgb = _hex_to_rgb(_C["panel_bg"])
        accent_rgb = _hex_to_rgb(_C["accent"])

        css = ("<style>html,body{width:100%;height:100%;margin:0;padding:0;"
               f"background:{_C['window_bg']};}}"
               # The map itself, inset from the widget's edges and rounded -
               # a floating card rather than a full-bleed slab. overflow:hidden
               # clips the tile/overlay layers to the rounded corners.
               ".folium-map{position:absolute!important;"
               "top:18px;left:18px;right:18px;bottom:18px;"
               "width:auto!important;height:auto!important;"
               "border-radius:18px!important;overflow:hidden!important;"
               f"border:1px solid {_C['border']}!important;"
               "box-shadow:0 24px 60px rgba(0,0,0,.65),"
               f"0 0 0 1px rgba({_rgb_css(accent_rgb)},.10)!important;}}"
               f".leaflet-container{{background:{_C['window_bg']}!important;}}"
               ".leaflet-image-layer{image-rendering:pixelated;"
               "image-rendering:crisp-edges;}"
               ".leaflet-container,.leaflet-grab,"
               ".leaflet-dragging .leaflet-grab{cursor:default!important;}"
               # Zoom control - a small rounded amber-on-black card instead of
               # Leaflet's plain white default.
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
               # Attribution - small and translucent, out of the way.
               ".leaflet-control-attribution{"
               "background:rgba(0,0,0,.45)!important;"
               f"color:{_C['text_gray']}!important;"
               "border-radius:6px 0 0 0!important;font-size:10px!important;"
               "padding:1px 6px!important;}"
               f".leaflet-control-attribution a{{color:{_C['text_gray']}!important;}}"
               # The point you clicked - a small solid marker with a soft
               # coloured halo, well clear of the amber suggestion marker.
               ".cwatm-marker{width:22px;height:22px;}"
               ".cwatm-marker-dot{position:absolute;left:50%;top:50%;"
               "transform:translate(-50%,-50%);width:16px;height:16px;"
               "border-radius:50%;background:#ff4433;border:3px solid #fff;"
               "box-shadow:0 3px 10px rgba(0,0,0,.55),"
               "0 0 0 5px rgba(255,68,51,.22);}"
               # The suggested outlet - a soft pulsing amber ring around a
               # solid dot, drawing the eye without a hard static shape.
               ".cwatm-suggest{width:34px;height:34px;}"
               ".cwatm-suggest-ring{position:absolute;inset:0;"
               f"border-radius:50%;border:2px solid {_C['accent']};"
               "opacity:.85;animation:cwatmPulse 2.4s ease-out infinite;}"
               ".cwatm-suggest-dot{position:absolute;left:50%;top:50%;"
               "transform:translate(-50%,-50%);width:10px;height:10px;"
               f"border-radius:50%;background:{_C['accent']};"
               f"box-shadow:0 0 10px 3px rgba({_rgb_css(accent_rgb)},.65);}}"
               "@keyframes cwatmPulse{0%{transform:scale(.35);opacity:.85;}"
               "70%{transform:scale(1.7);opacity:0;}"
               "100%{transform:scale(1.7);opacity:0;}}"
               # A small legend card for the accumulation colour ramp, bottom
               # left - the natural home for a future layers/visibility panel.
               ".cwatm-legend{position:absolute;left:32px;bottom:32px;"
               f"z-index:1000;background:rgba({_rgb_css(panel_rgb)},.85);"
               f"border:1px solid {_C['border']};border-radius:10px;"
               "padding:9px 12px;pointer-events:none;"
               "box-shadow:0 8px 24px rgba(0,0,0,.5);}"
               f".cwatm-legend-title{{color:{_C['text_muted']};font-size:11px;"
               f"font-family:{_MAP_LABEL_FONT};font-weight:600;"
               "margin-bottom:6px;}"
               ".cwatm-legend-bar{width:110px;height:7px;border-radius:4px;"
               f"background:linear-gradient(90deg,rgb({_rgb_css(_UPS_COLOR_LOW)}),"
               f"rgb({_rgb_css(_UPS_COLOR_HIGH)}));}}"
               f".cwatm-legend-labels{{display:flex;justify-content:space-between;"
               f"color:{_C['text_gray']};font-size:10px;"
               f"font-family:{_MAP_LABEL_FONT};margin-top:4px;}}"
               # The accumulation-opacity slider, top right - unlike the
               # legend/caption this one is interactive, so no pointer-events:none.
               ".cwatm-opacity{position:absolute;top:32px;right:32px;"
               f"z-index:1000;width:150px;background:rgba({_rgb_css(panel_rgb)},.85);"
               f"border:1px solid {_C['border']};border-radius:10px;"
               "padding:9px 12px;box-shadow:0 8px 24px rgba(0,0,0,.5);}"
               f".cwatm-opacity-label{{color:{_C['text_muted']};font-size:11px;"
               f"font-family:{_MAP_LABEL_FONT};font-weight:600;"
               "margin-bottom:6px;}"
               ".cwatm-opacity-range{-webkit-appearance:none;appearance:none;"
               f"width:100%;height:4px;border-radius:2px;background:{_C['border']};"
               "outline:none;display:block;}"
               ".cwatm-opacity-range::-webkit-slider-runnable-track{"
               f"height:4px;border-radius:2px;background:{_C['border']};}}"
               ".cwatm-opacity-range::-webkit-slider-thumb{"
               "-webkit-appearance:none;appearance:none;width:14px;height:14px;"
               f"border-radius:50%;background:{_C['accent']};"
               f"border:2px solid {_C['window_bg']};cursor:pointer;"
               "box-shadow:0 2px 6px rgba(0,0,0,.5);margin-top:-5px;}"
               "</style>")
        if "</head>" in html:
            html = html.replace("</head>", css + "</head>", 1)
        else:
            html = css + html

        legend = ('<div class="cwatm-legend">'
                  '<div class="cwatm-legend-title">Upstream Area</div>'
                  '<div class="cwatm-legend-bar"></div>'
                  '<div class="cwatm-legend-labels"><span>low</span>'
                  '<span>high</span></div></div>')
        opacity_pct = int(round(self._overlay_opacity * 100))
        opacity_ctl = (
            '<div class="cwatm-opacity">'
            '<div class="cwatm-opacity-label">Transparency</div>'
            f'<input type="range" min="0" max="100" value="{opacity_pct}" '
            'class="cwatm-opacity-range" id="cwatmOpacityRange"></div>')
        overlay_html = legend + opacity_ctl
        if "<body>" in html:
            html = html.replace("<body>", "<body>" + overlay_html, 1)
        elif "<body" in html:
            html = re.sub(r"(<body[^>]*>)", r"\1" + overlay_html, html, count=1)
        else:
            html = overlay_html + html

        html = _inline_remote_assets(html)

        helper = "<script>\n%s\n</script>" % js
        if "</html>" in html:
            html = html.replace("</html>", helper + "\n</html>", 1)
        else:
            html = html + helper
        return html

    def _helper_js(self, map_var, ups_var):
        """Topographic WMS basemap (see basin_viewer2._B2_PROVIDERS) + the ups
        overlay handle + the click marker + a pulsing div-icon suggestion
        marker + the document.title click bridge (same trick as
        basin_viewer2._helper_js's setBlack/click handler, renamed here so it
        cannot collide with a simultaneously-open Show Basin page sharing the
        same tile handler) + the on-map opacity slider's input listener
        (overlay only - the basemap stays fixed; entirely client-side, no
        round trip through Python - the #cwatmOpacityRange element itself is
        written by _build_map_html). The CSS classes referenced here
        (.cwatm-marker/.cwatm-suggest/.cwatm-opacity/...) are defined in
        _build_map_html's injected <style> block."""
        tpl = r"""
        (function(){
          var MAP=__MAP__;
          window._map=MAP;
          window._ups=__UPS__;
          // Hard-stop panning at the single real world extent - past it Leaflet
          // would otherwise let you drag into a repeated "second world" copy,
          // where the WMS basemap tiles still render but the ups.nc/ocean
          // overlays (fixed to this one lon/lat range) do not, so it looks like
          // a different, un-shaded map. maxBoundsViscosity 1.0 makes it a firm
          // wall instead of a rubber-band snap-back.
          MAP.setMaxBounds([[-90,-180],[90,180]]);
          MAP.options.maxBoundsViscosity=1.0;
          MAP.setMinZoom(2);
          window._tile=L.tileLayer.wms('osmtile://wms/service',
            {layers:__LAYER__,format:'image/png',version:'1.1.1',
             transparent:false,maxZoom:19,
             attribution:'(c) OpenStreetMap contributors'}).addTo(MAP);
          window._tile.bringToBack();
          window.setOverlayOpacity=function(o){if(window._ups)window._ups.setOpacity(o);};
          var opRange=document.getElementById('cwatmOpacityRange');
          if(opRange){opRange.addEventListener('input',function(){
            window.setOverlayOpacity(opRange.value/100);});}
          window.outletMarker=null;
          window.setOutlet=function(lat,lon){
            if(window.outletMarker){MAP.removeLayer(window.outletMarker);}
            var icon=L.divIcon({className:'',
              html:'<div class="cwatm-marker"><div class="cwatm-marker-dot">'+
                   '</div></div>',
              iconSize:[22,22],iconAnchor:[11,11]});
            window.outletMarker=L.marker([lat,lon],{icon:icon}).addTo(MAP);};
          window.clearOutlet=function(){if(window.outletMarker){
            MAP.removeLayer(window.outletMarker);window.outletMarker=null;}};
          var suggestIcon=L.divIcon({className:'',
            html:'<div class="cwatm-suggest"><div class="cwatm-suggest-ring">'+
                 '</div><div class="cwatm-suggest-dot"></div></div>',
            iconSize:[34,34],iconAnchor:[17,17]});
          var suggestion=L.marker([__CLAT__,__CLON__],
            {icon:suggestIcon,interactive:false}).addTo(MAP);
          MAP.on('click',function(e){
            document.title='ACOUT '+e.latlng.lng+'|'+e.latlng.lat;});
          setTimeout(function(){MAP.invalidateSize();
            MAP.fitBounds(__BOUNDS__,{padding:[30,30]});},300);
        })();
        """
        return (tpl.replace("__MAP__", map_var)
                   .replace("__UPS__", ups_var)
                   .replace("__LAYER__", repr(_BASEMAP_WMS_LAYER))
                   .replace("__CLAT__", repr(_DEFAULT_LAT))
                   .replace("__CLON__", repr(_DEFAULT_LON))
                   .replace("__BOUNDS__", repr(_BASIN_BOUNDS)))

    def _on_loaded(self, ok):
        if not ok:
            log.warning("academy outlet map page failed to load")
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
            log.debug("academy outlet map JS failed", exc_info=True)

    # ------------------------------------------------------------- clicking

    def _on_web_title(self, title):
        if not title.startswith("ACOUT "):
            return
        try:
            lon_s, lat_s = title[6:].split("|", 1)
            lon, lat = float(lon_s), float(lat_s)
        except Exception:
            return
        self._picked = (lon, lat)
        self._js("if(window.setOutlet) setOutlet(%f,%f);" % (lat, lon))
        ups_text = self._ups_value_text(lon, lat)
        self.info_label.setText(
            f"Picked: lat {lat:.3f}, lon {lon:.3f}"
            + (f" — upstream area: {ups_text}" if ups_text else ""))
        if not self._confirmed:
            self.confirm_button.setEnabled(True)

    def _ups_value_text(self, lon, lat):
        """The ups.nc value (upstream area, km2) at the cell nearest (lon, lat) -
        same convention/units as basin_viewer.BasinDataHelpers._ups_text."""
        try:
            lats, lons = np.asarray(self._lats), np.asarray(self._lons)
            row = int(np.abs(lats - float(lat)).argmin())
            col = int(np.abs(lons - float(lon)).argmin())
            basin = np.asarray(self._basin_data, dtype=float)
            if not (0 <= row < basin.shape[0] and 0 <= col < basin.shape[1]):
                return ""
            val = basin[row, col]
            if np.isnan(val):
                return "no data"
            return f"{int(round(val)):,} km²"
        except Exception:
            return ""

    # ------------------------------------------------------- confirm/continue

    def _on_confirm_clicked(self):
        if not self._confirmed:
            self._confirm_outlet()
        else:
            self._continue_to_next_level()

    def _show_written_lines(self):
        """After writing MaskMap/Gauges: hide this Academy window (the map
        would otherwise sit on top of the very editor the guide is pointing
        at) and hand off to the floating Torus guide, which points at the
        MaskMap line, then - on "Next" - the Gauges line (via
        academy_guide.settings_line_point, shared with Level 2's own
        settings-file targets), explaining each in turn right where it
        lives in the real settings file, instead of repeating that
        explanation inside this dialog's Mission box. Once the guide
        finishes, a centred TorusPrompt celebrates Level 1 being done
        (academy_guide.show_level_celebration) before the Academy window
        comes back, already advanced to Level 2 - see _on_guide_finished."""
        try:
            self.window().hide()
        except Exception:
            log.debug("_show_written_lines: could not hide Academy window", exc_info=True)
        try:
            self.mw.raise_()
            self.mw.activateWindow()
        except Exception:
            log.debug("_show_written_lines: could not raise main window", exc_info=True)
        from src.gui.widgets.academy_guide import TorusGuideBubble, settings_line_point
        self._guide = TorusGuideBubble()
        self._guide.finished.connect(self._on_guide_finished)
        steps = [
            (settings_line_point(self.mw, "MaskMap"),
             "This is <b>MaskMap</b>. CWatM reads it as a coordinate and "
             "automatically delineates the whole catchment that drains to "
             "that point, using the same upstream-area grid you just "
             "clicked on."),
            (settings_line_point(self.mw, "Gauges"),
             "This is <b>Gauges</b>. It marks where discharge is measured "
             "and reported - setting it to the same point as MaskMap is the "
             "simplest way to say \"measure the discharge right at my "
             "outlet.\""),
        ]
        self._guide.start(steps)

    def _on_guide_finished(self):
        """The Torus guide's last "Got it!" - the teaching part of Level 1
        is done, but the level itself isn't: show the "will you accept
        this mission" briefing for the Nile Field Test before the graded
        check itself (_start_nile_field_test), rather than jumping
        straight to the completion celebration - see the module docstring
        on academy_guide for the teaching-guide -> mission briefing ->
        Field Test -> celebration shape every level now follows."""
        from src.gui.widgets.academy_guide import show_mission_briefing
        self._mission_prompt = show_mission_briefing(1, self._start_nile_field_test)

    def _start_nile_field_test(self):
        from src.gui.widgets.academy_field_test import NileFieldTestWindow
        self._field_test = NileFieldTestWindow(main_window=self.mw)
        self._field_test.passed.connect(self._on_nile_field_test_passed)
        self._field_test.show()
        self._field_test.raise_()
        self._field_test.activateWindow()

    def _on_nile_field_test_passed(self):
        """The Field Test's Confirm button, on a correct pick - celebrate
        with a big centred TorusPrompt before bringing the Academy window
        back and moving straight on to Level 2, no extra click needed."""
        from src.gui.widgets.academy_guide import show_level_celebration
        self._celebration = show_level_celebration(1, self._finish_level1)

    def _finish_level1(self):
        try:
            academy = self.window()
            academy.show()
            academy.raise_()
            academy.activateWindow()
        except Exception:
            log.debug("_finish_level1: could not restore Academy window", exc_info=True)
        self._continue_to_next_level()

    def _confirm_outlet(self):
        """Write the point into the main window's MaskMap/Gauges fields (same
        4-decimal 'lon lat' format and auto-apply mechanism as Show Basin's
        own Copy Mask / Create+Copy Gauge actions - basin_viewer2.py
        _use_coordinates/_copy_gauge), then hand straight off to the Torus
        guide (_show_written_lines) - which itself advances to Level 2 when
        it finishes, so there is no separate "Continue" step to click here."""
        if self._picked is None:
            return
        lon, lat = self._picked
        coord = f"{lon:.4f} {lat:.4f}"
        wrote = False
        loaded_default = False
        if self.mw is not None:
            try:
                if not self.mw.file_manager.has_file_loaded():
                    default_path = asset_path(_DEFAULT_SETTINGS_ASSET)
                    if os.path.exists(default_path):
                        self.mw.load_recent_file(default_path)
                        loaded_default = self.mw.file_manager.has_file_loaded()
                self.mw.maskmap_field.setText(coord)
                self.mw.gauges_field.setText(coord)
                wrote = True
            except Exception:
                log.debug("_confirm_outlet: could not write MaskMap/Gauges", exc_info=True)
        self._confirmed = True
        self.confirm_button.setEnabled(False)
        if wrote:
            note = ("We loaded CWatM's example Danube settings file for you "
                     "and wrote your outlet into it."
                     if loaded_default else
                     "Written into MaskMap and Gauges in your currently "
                     "loaded settings file.")
            self.info_label.setText(note)
            self._show_written_lines()
        else:
            # No guide to hand off to - fall back to the explicit Continue
            # step so the learner still has a way forward.
            self.info_label.setText(
                "No settings file is currently open in the main editor, "
                "and the example settings file could not be loaded - "
                "MaskMap/Gauges could not be written.")
            self.confirm_button.setEnabled(True)
            self.confirm_button.setText("Continue to Level 2")

    def _continue_to_next_level(self):
        if self._picked is None:
            return
        lon, lat = self._picked
        self.outlet_picked.emit(lon, lat)

    def reset(self):
        """Clear a previous pick/confirmation - the widget is built once and
        reused across repeated Begin/Start Over entries into Level 1 within the
        same AcademyWindow session, so stale state would otherwise leak through."""
        self._picked = None
        self._confirmed = False
        self.confirm_button.setText("Confirm this outlet")
        self.confirm_button.setEnabled(False)
        self.info_label.setText("Click on the map to pick a point.")
        self._js("if(window.clearOutlet) clearOutlet();")

    def showEvent(self, event):
        """Re-fit the map to the basin bounds every time this widget actually
        becomes visible. The widget (and its map page) is built eagerly as
        soon as AcademyWindow constructs it - almost always while still
        hidden behind the welcome page in the QStackedWidget. A QWebEngineView
        that is not yet shown/laid out can report a zero or stale viewport
        size to its own JS, so the first fitBounds() (run 300ms after page
        load, in _helper_js) can compute a bogus, uselessly-zoomed-in view
        against that wrong size. Re-running it here, once this widget has
        real on-screen geometry, is what reliably gets the whole basin on
        screen (queued via self._js if the page hasn't finished loading yet)."""
        super().showEvent(event)
        self._js("if(window._map){window._map.invalidateSize();"
                  "window._map.fitBounds(%s,{padding:[30,30]});}" % repr(_BASIN_BOUNDS))
