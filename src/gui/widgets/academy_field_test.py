"""CWatM Academy - Level 1's Field Test: locate the Nile's outlet, unaided.

Where the Level 1 lesson (``academy_outlet_map.OutletMapWidget``) frames the
whole Danube basin, points a pulsing suggestion marker at the answer, and
*writes* the pick into MaskMap/Gauges, this is a Field Test - a graded
check, not a second lesson. ``NileFieldTestWindow`` shows the same kind of
upstream-area map over the Nile basin instead (the bundled
``academy_ups_30min.nc`` grid is global, so the Nile is already in it - no
second dataset needed), but deliberately has **no** suggestion marker (that
would just hand over the answer) and never touches the main window's
settings - it only grades a click against ``_NILE_TARGET_CELLS`` and reports
pass/fail.

``_NILE_TARGET_CELLS`` was derived, not guessed: the five highest
upstream-area cells inside a Nile bounding box of the same bundled grid form
a single north-south run of consecutive cells (lon 31.25, lat 29.75 through
31.75) with strictly decreasing accumulation heading south - exactly the
river's last few cells before the Mediterranean, in accumulation-rank order.
"One of the last 5 cells" is graded as landing on any of those five, snapped
to the nearest grid cell the same way the Level 1 map reads a value under
the cursor.

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
confirmed - that is the Nile's outlet" and the Confirm button enables; a
miss reads "Not the outlet - look further downstream" and lets the learner
click again, no penalty. Confirm emits ``passed`` and closes the window;
academy_outlet_map.OutletMapWidget._on_nile_field_test_passed picks up from
there (the level's completion celebration).
"""

import os

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

# The five highest-accumulation cells in the bundled ups.nc within a Nile
# bounding box - see the module docstring for how these were derived. Order
# doesn't matter for grading (any one of the five passes); listed
# north-to-south (most downstream first) for readability.
_NILE_TARGET_CELLS = [
    (31.750, 31.250),
    (31.250, 31.250),
    (30.750, 31.250),
    (30.250, 31.250),
    (29.750, 31.250),
]

# Nile basin bounding box (south, west, north, east) - Lake Victoria/the
# White Nile headwaters down to the Ethiopian highlands (Blue Nile) up to
# the Mediterranean delta. Framing, like OutletMapWidget's _BASIN_BOUNDS -
# never used for grading, only the initial map view.
_BASIN_BOUNDS = [[-4.5, 24.0], [32.5, 40.0]]
_DEFAULT_ZOOM = 4


def _nearest_cell(lats, lons, lat, lon):
    row = int(np.abs(lats - float(lat)).argmin())
    col = int(np.abs(lons - float(lon)).argmin())
    return float(lats[row]), float(lons[col])


def _is_target_cell(lats, lons, lat, lon):
    snapped_lat, snapped_lon = _nearest_cell(lats, lons, lat, lon)
    for t_lat, t_lon in _NILE_TARGET_CELLS:
        if abs(snapped_lat - t_lat) < 1e-6 and abs(snapped_lon - t_lon) < 1e-6:
            return True
    return False


class NileFieldTestWindow(QDialog):
    """Level 1's Field Test - see the module docstring. Emits ``passed``
    once Confirm is clicked after a correct pick."""

    passed = Signal()

    def __init__(self, main_window=None, parent=None):
        super().__init__(parent)
        self.mw = main_window
        self._picked_ok = False
        self._map_ready = False
        self._js_queue = []
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

        title = QLabel("Locate the outlet of the Nile")
        title.setObjectName("nftTitle")
        outer.addWidget(title)

        instructions = QLabel(
            "Surface water flows downstream. Click the point where the "
            "Nile reaches the sea - the same idea as Level 1's Danube "
            "exercise, but this time nothing on the map points at the "
            "answer for you.")
        instructions.setObjectName("nftInstructions")
        instructions.setWordWrap(True)
        outer.addWidget(instructions)

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

        m = folium.Map(location=[15.0, 32.0], zoom_start=_DEFAULT_ZOOM,
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
          MAP.on('click',function(e){
            document.title='NILETEST '+e.latlng.lng+'|'+e.latlng.lat;});
          setTimeout(function(){MAP.invalidateSize();
            MAP.fitBounds(__BOUNDS__,{padding:[30,30]});},300);
        })();
        """
        return (tpl.replace("__MAP__", map_var)
                   .replace("__LAYER__", repr(_BASEMAP_WMS_LAYER))
                   .replace("__BOUNDS__", repr(_BASIN_BOUNDS)))

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

    def _on_web_title(self, title):
        if not title.startswith("NILETEST "):
            return
        try:
            lon_s, lat_s = title[9:].split("|", 1)
            lon, lat = float(lon_s), float(lat_s)
        except Exception:
            return
        self._js("if(window.setPick) setPick(%f,%f);" % (lat, lon))
        self._picked_ok = _is_target_cell(self._lats, self._lons, lat, lon)
        if self._picked_ok:
            self.status_label.setText(
                "✓ Target confirmed - that is the Nile's outlet.")
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
