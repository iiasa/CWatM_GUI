"""CWatM Academy - Level 1's Field Test: locate the outlet of a big river basin,
unaided.

Where the Level 1 lesson (``academy_outlet_map.OutletMapWidget``) frames the
whole Danube basin, points a pulsing suggestion marker at the answer, and
*writes* the pick into MaskMap/Gauges, this is a Field Test - a graded
check, not a second lesson. ``BasinFieldTestWindow`` shows the same kind of
upstream-area map (the bundled ``academy_ups_30min.nc`` grid is global), but
deliberately has **no** suggestion marker and never touches the main window's
settings - it only grades a click and reports pass/fail.

**Which basin**: a random one of the 50 largest in
``assets/academy_biggest_basins.csv`` (rank, basin_size_km2, name, lon, lat -
the outlet cell centre on this same 30' grid), the Danube included.
**Another basin** draws a new one. The
view is framed *around* the outlet but deliberately off-centre
(``view_bounds``), so the middle of the map is not the answer.

**Graded against the 4 biggest upstream cells of that basin**
(``target_cells``), computed from the grid at runtime rather than hard-coded:
the outlet cell (the listed one - its upstream area equals the listed basin
size for all 50) plus, best-first, the three largest cells draining into what
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
confirmed - that is the outlet of the <basin>" and the Confirm button enables;
a miss reads "Not the outlet - look further downstream" and lets the learner
click again, no penalty. Confirm emits ``passed`` and closes the window;
academy_outlet_map.OutletMapWidget._on_nile_field_test_passed picks up from
there (the level's completion celebration).
"""

import csv
import os
import random

import numpy as np

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
)
from PySide6.QtCore import Qt, QUrl, Signal

from src.gui.utils import theme
from src.gui.utils.window_geometry import scaled_default_size
from src.gui.utils.gui_log import get_logger

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
    _hex_to_rgb, _rgb_css, _MAP_LABEL_FONT, _BASEMAP_WMS_LAYER,
)

_C = theme.theme_colors("mikhail")

_BASINS_ASSET = "academy_biggest_basins.csv"
_POOL_SIZE = 50                  # draw from the 50 largest basins
_EXCLUDED = set()                # basins never drawn (none at the moment)
TARGET_CELLS = 4                 # pass = one of the basin's 4 biggest cells


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


def view_bounds(basin, rng=random):
    """[[south, west], [north, east]] around the outlet, sized from the basin
    area, shifted at random so the outlet is never the centre of the view (but
    always well inside it)."""
    half = min(25.0, max(4.0, (basin["size_km2"] ** 0.5) / 111.0 * 0.9))
    clat = basin["lat"] + rng.uniform(-0.5, 0.5) * half
    clon = basin["lon"] + rng.uniform(-0.5, 0.5) * half
    south, north = max(-85.0, clat - half), min(85.0, clat + half)
    return [[south, clon - half], [north, clon + half]]


class BasinFieldTestWindow(QDialog):
    """Level 1's Field Test - see the module docstring. Emits ``passed``
    once Confirm is clicked after a correct pick."""

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
        try:
            self._basins = load_basins()
        except Exception:
            log.warning("academy basin list unreadable", exc_info=True)
        self.setWindowTitle("CWatM Academy - Field Test")
        self._build_ui()
        self._apply_style()
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

        tag = QLabel("FIELD TEST")
        tag.setObjectName("nftTag")
        outer.addWidget(tag)

        self.title_label = QLabel("Locate the outlet")
        self.title_label.setObjectName("nftTitle")
        outer.addWidget(self.title_label)

        self.instructions_label = QLabel("")
        self.instructions_label.setObjectName("nftInstructions")
        self.instructions_label.setWordWrap(True)
        outer.addWidget(self.instructions_label)

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
        self.another_button.setToolTip("Try the outlet of a different river basin")
        self.another_button.clicked.connect(self._next_basin)
        status_lay.addWidget(self.another_button)
        self.confirm_button = QPushButton("Confirm target")
        self.confirm_button.setObjectName("nftConfirm")
        self.confirm_button.setEnabled(False)
        self.confirm_button.clicked.connect(self._on_confirm_clicked)
        status_lay.addWidget(self.confirm_button)
        outer.addWidget(status_row)

    def _apply_style(self):
        c = _C
        self.setStyleSheet(f"""
            QDialog {{ background-color: {c['window_bg']}; }}
            QLabel#nftTag {{ color: {c['accent']}; font-size: 11px; font-weight: 700; }}
            QLabel#nftTitle {{ color: {c['accent']}; font-size: 18px; font-weight: 700; }}
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
          window.frame=function(b){MAP.invalidateSize();
            MAP.fitBounds(b,{padding:[30,30]});};
          // the stamp makes a repeated click on the same spot a new title
          MAP.on('click',function(e){
            document.title='NILETEST '+e.latlng.lng+'|'+e.latlng.lat+'|'+Date.now();});
          setTimeout(function(){window.frame(__BOUNDS__);},300);
        })();
        """
        return (tpl.replace("__MAP__", map_var)
                   .replace("__LAYER__", repr(_BASEMAP_WMS_LAYER))
                   .replace("__BOUNDS__", repr(self._view)))

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
        pool = [b for b in self._basins if b is not self._basin] or self._basins
        self._basin = random.choice(pool)
        b = self._basin
        self._targets = target_cells(self._basin_data, self._lats, self._lons,
                                     b["lat"], b["lon"])
        self._view = view_bounds(b)
        self._picked_ok = False
        self.confirm_button.setEnabled(False)
        self.title_label.setText(f"Locate the outlet of the {b['name']}")
        self.instructions_label.setText(
            f"The {b['name']} basin covers about {b['size_km2']:,.0f} km². Surface "
            "water flows downstream - click the point where the river ends: at the "
            "sea, or, for an inland basin, in its lake or sink. Land on one of the "
            f"{TARGET_CELLS} biggest cells of the basin to pass. The same idea as the "
            "Danube exercise, but this time nothing on the map points at the answer.")
        self.status_label.setText("Awaiting target …")

    def _next_basin(self):
        """Another basin: new question, new framing, the old pick removed."""
        if not self._basins or getattr(self, "_basin_data", None) is None:
            return
        self._choose_basin()
        self._js("if(window.clearPick) clearPick();")
        self._js("if(window.frame) frame(%s);" % repr(self._view))

    def _on_web_title(self, title):
        if not title.startswith("NILETEST ") or not self._targets:
            return
        try:
            lon_s, lat_s = title[9:].split("|")[:2]
            lon, lat = float(lon_s), float(lat_s)
        except Exception:
            return
        self._js("if(window.setPick) setPick(%f,%f);" % (lat, lon))
        self._picked_ok = is_target(self._lats, self._lons, lat, lon, self._targets)
        if self._picked_ok:
            self.status_label.setText(
                f"✓ Target confirmed - that is the outlet of the {self._basin['name']}.")
            self.confirm_button.setEnabled(True)
        else:
            self.status_label.setText(
                "✗ Not the outlet - look further downstream.")
            self.confirm_button.setEnabled(False)

    def _on_confirm_clicked(self):
        if not self._picked_ok:
            return
        self.passed.emit()
        self.close()


# the window's earlier name, kept for callers (academy_outlet_map)
NileFieldTestWindow = BasinFieldTestWindow
