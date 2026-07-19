"""
Show Basin2 - folium (Leaflet) basin viewer in EPSG:4326 (Tools menu).

A functional duplicate of Show Basin in a single view, built on **folium**
(``folium.Map(crs='EPSG4326')``) rendered in a QtWebEngine view.

Why EPSG:4326 (vs. the classic viewer's EPSG:3857 Web-Mercator): the CWatM
raster results (ups.nc, mask, and the NetCDF analysis maps) are all in plain
lon/lat (EPSG:4326). Showing the basin in the *same* projection means the ups.nc
and mask overlays need **no rasterio reprojection** - they are handed to Leaflet
as ``ImageOverlay`` with their lon/lat corner bounds and drawn 1:1, so the raster
stays **crisp** (no Mercator warp blur). The previous Plotly/MapLibre experiment
warped the overlays onto a Mercator basemap and did not render well.

Note: OpenStreetMap XYZ tiles are Web-Mercator (EPSG:3857). On an EPSG:4326 map
the basemap tile grid does not line up perfectly with the lon/lat overlays - the
raster + markers (the data) are correct and crisp; the OSM basemap underneath is
a rough geographic reference only.

Everything else works like Show Basin: red = gauges, blue = mask-start,
black = last clicked cell (all drawn as **folium.Icon** pins); Create new Mask /
Copy Mask, Create gauge / Copy Gauge, Zoom to Mask, Hide/Show Mask, a
transparency slider and a basemap selector. Clicks are routed to Python via
``document.title`` (like the classic viewer and the NetCDF window).
"""

import json
import os
import re
import sys
import tempfile

import numpy as np

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QSlider, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtGui import QIcon

from src.gui.utils.window_geometry import GeometryMemoryMixin
from src.gui.utils import display_format
from src.gui.utils import theme
from src.gui.utils.gui_log import get_logger

# Reuse the classic viewer's display-agnostic helpers (marker sources, colour
# rasters, gauge check plumbing) - they only touch data/fields, not the canvas.
from src.gui.widgets.basin_viewer import (
    BasinDataHelpers, BasinViewer, _parse_coord_pairs)

log = get_logger("basin_viewer2")

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    import folium
    _B2_AVAILABLE = True
    _B2_IMPORT_ERROR = ""
except Exception as _e:  # pragma: no cover - import guard
    _B2_AVAILABLE = False
    _B2_IMPORT_ERROR = f"{type(_e).__name__}: {_e}"

# Basemap providers - EPSG:4326 **WMS** layers (an EPSG:4326 map cannot use the
# Web-Mercator OSM XYZ tiles the classic viewer uses; WMS returns imagery in the
# map's own CRS). The value is the WMS LAYERS name sent to the terrestris OSM WMS
# through the osmtile:// scheme handler (Python-fetched, cached, proxy-proof).
_B2_PROVIDERS = [
    ("OSM", "OSM-WMS"), ("Topographic", "TOPO-OSM-WMS"),
    ("Terrain", "SRTM30-Colored-Hillshade"), ("Dark", "Dark"),
]
_B2_DEFAULT_LAYER = "OSM-WMS"


def _strip_unused_assets(html):
    """Remove CDN <script>/<link> tags folium adds that the map does not need
    (jquery, bootstrap, glyphicons, font-awesome, and leaflet.awesome-markers -
    the pins are now self-contained CSS `L.divIcon`s). Dropping them (rather than
    inlining) keeps the page small and avoids Chromium trying - and failing behind
    the proxy - to fetch them."""
    blocked = r"(jquery|bootstrap|glyphicon|awesome)"
    html = re.sub(r'<script\b[^>]*\bsrc=["\'][^"\']*%s[^"\']*["\'][^>]*>\s*</script>'
                  % blocked, "", html, flags=re.IGNORECASE)
    html = re.sub(r'<link\b[^>]*\bhref=["\'][^"\']*%s[^"\']*["\'][^>]*/?>'
                  % blocked, "", html, flags=re.IGNORECASE)
    return html


# ---------------------------------------------------------------------------
# Offline asset inlining: fetch folium's CDN JS/CSS (Leaflet, awesome-markers,
# font-awesome, bootstrap, jquery) with Python's network stack - which works
# behind the proxy that blocks Chromium - and inline them into the page so the
# map and the folium.Icon pins render without any Chromium CDN request. CSS
# url() assets (marker PNGs, fonts) are inlined as data: URIs too.
# Everything here is defensive: any failure leaves the original markup, so the
# page is never worse than plain folium.
# ---------------------------------------------------------------------------
def _web_cache_dir():
    d = os.path.join(tempfile.gettempdir(), "cwatm_web")
    os.makedirs(d, exist_ok=True)
    return d


_WEB_SESSION = None


def _web_session():
    global _WEB_SESSION
    if _WEB_SESSION is None:
        import requests
        s = requests.Session()
        s.headers.update({"User-Agent": "CWatM-GUI/1.0 (basin viewer2)"})
        _WEB_SESSION = s
    return _WEB_SESSION


def _dl_bytes(url):
    """Download a URL to bytes, cached on disk by name."""
    import hashlib
    key = hashlib.md5(url.encode("utf-8")).hexdigest()
    ext = os.path.splitext(url.split("?")[0])[1][:6] or ".bin"
    fp = os.path.join(_web_cache_dir(), key + ext)
    if not os.path.exists(fp):
        r = _web_session().get(url, timeout=15)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} for {url}")
        with open(fp, "wb") as f:
            f.write(r.content)
    with open(fp, "rb") as f:
        return f.read()


def _dl_text(url):
    return _dl_bytes(url).decode("utf-8", errors="ignore")


def _mime_for(url):
    u = url.lower().split("?")[0]
    for ext, mime in ((".png", "image/png"), (".gif", "image/gif"),
                      (".jpg", "image/jpeg"), (".jpeg", "image/jpeg"),
                      (".svg", "image/svg+xml"), (".woff2", "font/woff2"),
                      (".woff", "font/woff"), (".ttf", "font/ttf"),
                      (".eot", "application/vnd.ms-fontobject")):
        if u.endswith(ext):
            return mime
    return "application/octet-stream"


def _inline_css_urls(css, base_url):
    """Replace url(...) references in a stylesheet with inlined data: URIs."""
    import base64
    from urllib.parse import urljoin

    def repl(m):
        raw = m.group(1).strip().strip('"').strip("'")
        if raw.startswith("data:") or raw.startswith("#"):
            return m.group(0)
        abs_url = raw if raw.startswith("http") else urljoin(base_url, raw)
        try:
            data = _dl_bytes(abs_url)
            uri = "data:%s;base64,%s" % (_mime_for(abs_url),
                                         base64.b64encode(data).decode("ascii"))
            return "url(%s)" % uri
        except Exception:
            # Leave an absolute URL so at least Chromium can try (never relative).
            return "url(%s)" % abs_url

    return re.sub(r"url\(([^)]+)\)", repl, css)


def _inline_remote_assets(html):
    """Inline every http(s) <script src> and <link rel=stylesheet href> so the
    page is self-contained (proxy-proof). Fully defensive - returns the original
    html on any failure."""
    try:
        def sub_script(m):
            url = m.group(1)
            if not url.startswith("http"):
                return m.group(0)
            try:
                return "<script>\n%s\n</script>" % _dl_text(url)
            except Exception:
                return m.group(0)

        def sub_link(m):
            url = m.group(1)
            if not url.startswith("http"):
                return m.group(0)
            try:
                css = _inline_css_urls(_dl_text(url), url)
                return "<style>\n%s\n</style>" % css
            except Exception:
                return m.group(0)

        html = re.sub(r'<script\b[^>]*\bsrc=["\']([^"\']+)["\'][^>]*>\s*</script>',
                      sub_script, html, flags=re.IGNORECASE)
        html = re.sub(r'<link\b[^>]*\bhref=["\']([^"\']+\.css[^"\']*)["\'][^>]*/?>',
                      sub_link, html, flags=re.IGNORECASE)
    except Exception:
        log.debug("basin2: asset inlining failed", exc_info=True)
    return html


def show_basin2(config_content, settings_file, parent=None,
                default_basemap="standard"):
    """Load the basin data (same loaders as Show Basin) and open BasinWindow2."""
    viewer = BasinViewer(config_content)
    viewer.settings_file = settings_file
    ups_path = viewer._find_ups_path()
    if not ups_path:
        print("No UPS path found in configuration", file=sys.stderr)
        return
    resolved = viewer._resolve_placeholders(ups_path)
    if not resolved or not os.path.exists(resolved):
        print(f"Basin file not found: {resolved}", file=sys.stderr)
        return
    basin_data, lats, lons = viewer._load_netcdf_data(resolved)
    if basin_data is None:
        return
    mask_data = viewer._load_mask_data(settings_file, basin_data.shape)
    title = viewer._find_title() or f"Basin: {os.path.basename(resolved)}"
    win = BasinWindow2(basin_data, lats, lons, title, mask_data,
                       settings_file, parent, default_basemap)
    win.exec()


class BasinWindow2(BasinDataHelpers, GeometryMemoryMixin, QDialog):
    """folium/Leaflet EPSG:4326 basin viewer (Tools ▸ Show Basin). Inherits the
    display-agnostic data helpers from BasinDataHelpers (ups/mask RGBA, gauge/mask
    field readers, gauge-in-mask check)."""

    def _field_gauges(self):
        """Gauge (lon, lat) pairs taken **only** from the live left-window Gauges box
        (no settings-file fallback), so the map always mirrors that box - removing a
        station on the map (which empties/shortens the box) is reflected at once and
        never re-read from the settings file."""
        mw = self._main_window()
        if mw is not None:
            try:
                return _parse_coord_pairs(mw.gauges_field.text()) or []
            except Exception:
                pass
        return []

    def __init__(self, basin_data, lats, lons, title="Basin Display",
                 mask_data=None, settings_file=None, parent=None,
                 default_basemap="standard"):
        super().__init__(parent)
        self.basin_data = basin_data
        self.lats = np.asarray(lats)
        self.lons = np.asarray(lons)
        self.mask_data = mask_data
        self.settings_file = settings_file
        _keys = {k for _l, k in _B2_PROVIDERS}
        # The Configure-menu default is a Mercator XYZ key (e.g. "standard") that
        # does not apply to the WMS layers here -> fall back to plain OSM.
        self._basemap_key = default_basemap if default_basemap in _keys else _B2_DEFAULT_LAYER
        # One transparency slider fades BOTH layers (like NetCDF): OSM basemap opacity
        # 0..1 and the ups.nc/mask overlay opacity 1.0..0.5 as the slider goes 0..100%.
        # The start value comes from Configure > Transparency (0-100).
        _t = max(0.0, min(1.0, display_format.get_transparency() / 100.0))
        self._base_opacity = _t               # OSM basemap opacity (slider)
        self._overlay_opacity = 1.0 - 0.5 * _t  # ups.nc/mask overlay opacity
        self.show_mask = True
        self._blue_pt = self._mask_start_point()
        # Working list of gauges (lon, lat) shown as numbered red pins; seeded from the
        # live Gauges box. Create gauge appends, clicking a pin removes, Copy gauge
        # commits the whole list to the box.
        self._gauges = list(self._field_gauges() or [])
        self._temp_html = None
        # JS is queued until the folium page has finished loading (the Leaflet
        # map + helper functions only exist then).
        self._map_ready = False
        self._js_queue = []

        self.setWindowTitle(f"🗺️ {title} — Basin (folium / EPSG:4326)")
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.WindowMinMaxButtonsHint
                            | Qt.WindowCloseButtonHint)
        # Key bumped ("basin2f") so a geometry saved by the old Plotly variant is
        # ignored and the folium default below takes effect.
        if not self._init_geometry_memory("basin2f"):
            self.resize(1000, 700)
        try:
            icon = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(__file__)))), 'assets', 'cwatm.ico')
            if os.path.exists(icon):
                self.setWindowIcon(QIcon(icon))
        except Exception:
            pass

        self._build_ui(title)
        self._show_map()

    # ------------------------------------------------------------------- UI
    def _build_ui(self, title):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)

        head = QLabel(title)
        head.setAlignment(Qt.AlignCenter)
        head.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 15px; "
            f"font-weight: 700; color: {theme.c('text')}; padding: 4px;")
        lay.addWidget(head)

        self.web_view = QWebEngineView()
        self.web_view.titleChanged.connect(self._on_web_title)
        lay.addWidget(self.web_view, 1)

        self.info_label = QLabel("Click on the map to see coordinates and values")
        self.info_label.setStyleSheet(
            "font-family: 'Segoe UI', 'Consolas', monospace; font-size: 12px; "
            f"color: {theme.c('text')}; padding: 6px 10px; "
            f"background: {theme.c('surface_bg')}; "
            f"border: 1px solid {theme.c('border')}; border-radius: 6px;")
        lay.addWidget(self.info_label)

        blue = """
            QPushButton { font-family: 'Segoe UI', sans-serif; font-size: 11px;
                font-weight: 500; color: white; border: none; border-radius: 6px;
                padding: 6px 12px; min-width: 70px; min-height: 26px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #87ceeb, stop:1 #5dade2); }
            QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #add8e6, stop:1 #87ceeb); }
            QPushButton:checked { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #b0c4de, stop:1 #778899); }
            QPushButton:disabled { background: #d3d3d3; color: #a9a9a9; }
        """
        red = blue.replace("#87ceeb", "#f1948a").replace("#5dade2", "#e74c3c") \
                  .replace("#add8e6", "#f5b7b1")
        gray = blue.replace("#87ceeb", "#b0b0b0").replace("#5dade2", "#808080") \
                   .replace("#add8e6", "#c8c8c8")

        row = QHBoxLayout()
        row.setSpacing(10)

        self.mask_button = QPushButton("Hide Mask")
        self.mask_button.setCheckable(True)
        self.mask_button.setChecked(True)
        self.mask_button.setStyleSheet(blue)
        self.mask_button.clicked.connect(self._toggle_mask)
        if self.mask_data is None:
            self.mask_button.setEnabled(False)
            self.mask_button.setText("Mask (N/A)")
        row.addWidget(self.mask_button)

        self.create_mask_button = QPushButton("Create new Mask")
        self.create_mask_button.setStyleSheet(blue)
        self.create_mask_button.clicked.connect(self._create_new_mask)
        row.addWidget(self.create_mask_button)

        self.use_coords_button = QPushButton("Copy Mask")
        self.use_coords_button.setStyleSheet(blue)
        self.use_coords_button.setEnabled(False)
        self.use_coords_button.setToolTip(
            "Copy the mask location to the settings MaskMap field")
        self.use_coords_button.clicked.connect(self._use_coordinates)
        row.addWidget(self.use_coords_button)

        self.zoom_mask_button = QPushButton("Zoom to Mask")
        self.zoom_mask_button.setStyleSheet(blue)
        self.zoom_mask_button.clicked.connect(self._zoom_to_mask)
        row.addWidget(self.zoom_mask_button)

        self.create_gauge_button = QPushButton("Create gauge")
        self.create_gauge_button.setStyleSheet(red)
        self.create_gauge_button.clicked.connect(self._create_gauge)
        row.addWidget(self.create_gauge_button)

        self.copy_gauge_button = QPushButton("Copy Gauge")
        self.copy_gauge_button.setStyleSheet(red)
        self.copy_gauge_button.setToolTip(
            "Write ALL displayed gauges to the main-window Gauges box")
        self.copy_gauge_button.setEnabled(bool(self._gauges))
        self.copy_gauge_button.clicked.connect(self._copy_gauge)
        row.addWidget(self.copy_gauge_button)

        self.load_json_button = QPushButton("Load JSON")
        self.load_json_button.setStyleSheet(blue)
        self.load_json_button.setToolTip("Load a GeoJSON file and display it on the map")
        self.load_json_button.clicked.connect(self._load_json)
        row.addWidget(self.load_json_button)

        row.addStretch()

        self.exit_button = QPushButton("Exit")
        self.exit_button.setStyleSheet(gray)
        self.exit_button.clicked.connect(self.close)
        row.addWidget(self.exit_button)
        lay.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        bl = QLabel("Basemap:")
        bl.setStyleSheet(f"font-size: 11px; color: {theme.c('text')};")
        row2.addWidget(bl)
        self.basemap_combo = QComboBox()
        for label, key in _B2_PROVIDERS:
            self.basemap_combo.addItem(label, key)
        idx = self.basemap_combo.findData(self._basemap_key)
        if idx >= 0:
            self.basemap_combo.setCurrentIndex(idx)
        self.basemap_combo.currentIndexChanged.connect(self._on_basemap_changed)
        row2.addWidget(self.basemap_combo)

        tl = QLabel("OSM transparency:")
        tl.setStyleSheet(f"font-size: 11px; color: {theme.c('text')};")
        row2.addWidget(tl)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setToolTip(
            "0% = OSM hidden + ups.nc fully opaque (only the data, on white); "
            "100% = OSM fully visible + ups.nc 50% opaque on top")
        self.opacity_slider.setValue(int(self._base_opacity * 100))
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        row2.addWidget(self.opacity_slider, 1)
        lay.addLayout(row2)

    # ------------------------------------------------------------ map build
    def _grid_bounds(self):
        """(west, east, south, north) of the CELL EDGES (centres +- half a cell)."""
        lats, lons = self.lats, self.lons
        dlat = abs(float(lats[1] - lats[0])) if lats.size > 1 else 0.01
        dlon = abs(float(lons[1] - lons[0])) if lons.size > 1 else 0.01
        west = float(lons.min()) - dlon / 2.0
        east = float(lons.max()) + dlon / 2.0
        south = float(lats.min()) - dlat / 2.0
        north = float(lats.max()) + dlat / 2.0
        return west, east, south, north

    @staticmethod
    def _upscale_rgba(rgba, target=1000):
        """Modest nearest-neighbour upscale of the grid-resolution RGBA. Leaflet's
        `image-rendering:pixelated` already keeps the cells crisp when zoomed, so
        this only guards tiny grids; the cap keeps the data URI small (fast page)."""
        h, w = rgba.shape[:2]
        k = max(1, min(4, int(round(target / max(h, w)))))
        if k > 1:
            rgba = np.repeat(np.repeat(rgba, k, axis=0), k, axis=1)
        return rgba

    @staticmethod
    def _image_overlay(data_uri, bounds, opacity, name):
        """A folium ImageOverlay carrying a data: URI. folium's ``image_to_url``
        treats a non-http string as a *file path* (and would crash on a data URI),
        so it is constructed with a throwaway URL and the real data URI is set
        onto ``.url`` afterwards (that is what the Leaflet template renders)."""
        ov = folium.raster_layers.ImageOverlay(
            image="https://cwatm.invalid/overlay.png", bounds=bounds,
            opacity=opacity, mercator_project=False, pixelated=True, name=name)
        ov.url = data_uri
        return ov

    def _build_map_html(self):
        """Build the folium (Leaflet) EPSG:4326 page: OSM tile basemap + the ups.nc
        and mask ImageOverlays (plain lon/lat, no reprojection) + JS helpers that
        the Python action methods drive. Returns the HTML string."""
        west, east, south, north = self._grid_bounds()
        clat, clon = (south + north) / 2.0, (west + east) / 2.0
        # Leaflet lat/lon bounds: [[south, west], [north, east]]
        bounds = [[south, west], [north, east]]

        m = folium.Map(location=[clat, clon], zoom_start=8, crs="EPSG4326",
                       tiles=None, control_scale=True, zoom_control=True)
        # No folium tile layer: the WMS basemap is created in the helper JS
        # (setBasemap) so both the initial map and a basemap switch share one path.

        ups = self._image_overlay(
            self._rgba_to_datauri(self._upscale_rgba(self._build_ups_rgba())),
            bounds, self._overlay_opacity, "ups")
        ups.add_to(m)

        mask_name = "null"
        if self.mask_data is not None:
            mask = self._image_overlay(
                self._rgba_to_datauri(self._upscale_rgba(self._build_mask_rgba())),
                bounds, self._overlay_opacity, "mask")
            mask.add_to(m)
            mask_name = mask.get_name()

        # NB: folium already bundles Leaflet + leaflet.awesome-markers + font-awesome
        # (so L.AwesomeMarkers exists for the folium.Icon pins we build in JS).

        # Render, then inject our CSS/JS by STRING INSERTION - not via
        # folium.Element, which re-renders the string as a Jinja template and would
        # mangle JS/CSS braces. The map-sizing CSS is essential: a standalone folium
        # page gives <body> no height, so the map div would collapse to 0 px (blank).
        js = self._helper_js(m.get_name(), ups.get_name(), mask_name, bounds)
        html = m.get_root().render()
        # Drop CDN libs the map does not need (jquery/bootstrap/font-awesome) so the
        # page stays small and Chromium never blocks on them.
        html = _strip_unused_assets(html)

        css = ("<style>html,body{width:100%;height:100%;margin:0;padding:0;}"
               ".folium-map{position:absolute!important;top:0;left:0;"
               "width:100%!important;height:100%!important;}"
               ".leaflet-image-layer{image-rendering:pixelated;"
               "image-rendering:crisp-edges;}"
               # Arrow cursor over the map (not the Leaflet grab/hand cursor).
               ".leaflet-container,.leaflet-grab,"
               ".leaflet-dragging .leaflet-grab{cursor:default!important;}"
               # CSS teardrop pins with a centred letter (self-contained - no
               # font-awesome), the folium.Icon look but compact.
               ".cwatm-pin{width:22px;height:22px;border-radius:50% 50% 50% 0;"
               "transform:rotate(-45deg);border:2px solid #fff;"
               "box-shadow:0 1px 3px rgba(0,0,0,.45);display:flex;"
               "align-items:center;justify-content:center;}"
               ".cwatm-pin span{transform:rotate(45deg);color:#fff;"
               "font:bold 12px 'Segoe UI',Arial,sans-serif;line-height:1;}"
               "</style>")
        if "</head>" in html:
            html = html.replace("</head>", css + "</head>", 1)
        else:
            html = css + html

        # Inline folium's CDN JS/CSS (proxy-proof) BEFORE adding our own inline
        # script, so the inliner regexes never touch our helper block.
        html = _inline_remote_assets(html)

        # Our helper JS must run AFTER folium's map-init script (which defines the
        # global map/overlay vars). folium puts that script last, so insert ours
        # right before </html> (top-level vars are global -> reachable).
        helper = "<script>\n%s\n</script>" % js
        if "</html>" in html:
            html = html.replace("</html>", helper + "\n</html>", 1)
        else:
            html = html + helper
        return html

    def _helper_js(self, map_var, ups_var, mask_var, bounds):
        """The JS driven by the Python actions: WMS basemap, markers (folium.Icon
        pins), overlay opacity/visibility, mask update, basemap switch, clicks."""
        dec = display_format.get_decimals()
        gauges = [[lat, lon, self._ups_text(lon, lat)]
                  for lon, lat in self._gauges]
        blue_init = ""
        if self._blue_pt:
            blue_init = ("window.setBlue(%f,%f,%s);"
                         % (self._blue_pt[1], self._blue_pt[0],
                            json.dumps(self._ups_text(*self._blue_pt))))
        tpl = r"""
        (function(){
          var MAP=__MAP__;
          window._map=MAP; window._ups=__UPS__; window._mask=__MASK__;
          window._tile=null; window._bounds=__BOUNDS__; window._op=__OP__;
          window._baseOp=__BASEOP__;
          window.maskVisible=true; var DEC=__DEC__;
          function pin(color,letter){return L.divIcon({className:'',
            html:'<div class="cwatm-pin" style="background:'+color+'">'
                 +'<span>'+(letter||'')+'</span></div>',
            iconSize:[24,24], iconAnchor:[12,23], tooltipAnchor:[0,-20]});}
          function tip(lon,lat,ups,label){
            return label+' '+lon.toFixed(DEC)+' '+lat.toFixed(DEC)
                   +(ups?'<br>UPS: '+ups:'');}
          window.redGroup=L.layerGroup().addTo(MAP);
          window.setRedAll=function(arr){window.redGroup.clearLayers();
            arr.forEach(function(g,i){
              var mk=L.marker([g[0],g[1]],{icon:pin('#e74c3c',String(i+1))})
               .addTo(window.redGroup)
               .bindTooltip(tip(g[1],g[0],g[2],'Gauge '+(i+1))+'<br>(click to remove)');
              mk.on('click',function(ev){L.DomEvent.stopPropagation(ev);
                document.title='B2DEL '+i+' '+Date.now();});});};
          window.setRed=function(lat,lon,ups){window.setRedAll([[lat,lon,ups]]);};
          window.blueMarker=null;
          window.setBlue=function(lat,lon,ups){
            if(window.blueMarker){MAP.removeLayer(window.blueMarker);}
            window.blueMarker=L.marker([lat,lon],{icon:pin('#2c7fff','M')})
              .addTo(MAP).bindTooltip(tip(lon,lat,ups,'Mask start'));};
          window.blackMarker=null;
          window.setBlack=function(lat,lon,ups){
            if(window.blackMarker){MAP.removeLayer(window.blackMarker);}
            window.blackMarker=L.marker([lat,lon],{icon:pin('#111111','')})
              .addTo(MAP).bindTooltip(tip(lon,lat,ups,'Clicked'));};
          window.clearBlack=function(){if(window.blackMarker){
            MAP.removeLayer(window.blackMarker);window.blackMarker=null;}};
          window.setOverlayOpacity=function(o){window._op=o;
            if(window._ups)window._ups.setOpacity(o);
            if(window._mask)window._mask.setOpacity(window.maskVisible?o:0);};
          window.setMaskVisible=function(v){window.maskVisible=v;
            if(window._mask)window._mask.setOpacity(v?window._op:0);};
          window.updateMask=function(uri){
            if(window._mask){window._mask.setUrl(uri);}
            else{window._mask=L.imageOverlay(uri,window._bounds,
              {opacity:window.maskVisible?window._op:0,className:'leaflet-image-layer',
               interactive:false}).addTo(MAP);}
            window._mask.setOpacity(window.maskVisible?window._op:0);};
          window.setBasemap=function(layer){
            if(window._tile){MAP.removeLayer(window._tile);}
            window._tile=L.tileLayer.wms('osmtile://wms/service',{layers:layer,
              format:'image/png',version:'1.1.1',transparent:false,maxZoom:19,
              opacity:window._baseOp,
              attribution:'(c) OpenStreetMap contributors'}).addTo(MAP);
            if(window._tile.bringToBack)window._tile.bringToBack();};
          window.setBaseOpacity=function(o){window._baseOp=o;
            if(window._tile)window._tile.setOpacity(o);};
          window.geoGroup=L.layerGroup().addTo(MAP);
          window.addGeoJson=function(obj){try{
            var gj=L.geoJSON(obj,{style:{color:'#ff7800',weight:2,
                fillColor:'#ffb347',fillOpacity:0.25},
              pointToLayer:function(f,ll){return L.circleMarker(ll,{radius:5,
                color:'#ff7800',fillColor:'#ffb347',fillOpacity:0.7,weight:2});},
              onEachFeature:function(f,layer){if(f.properties){
                var t=Object.keys(f.properties).map(function(k){
                  return k+': '+f.properties[k];}).join('<br>');
                if(t)layer.bindPopup(t);}}}).addTo(window.geoGroup);
            try{MAP.fitBounds(gj.getBounds());}catch(e){}
            }catch(e){document.title='B2ERR geojson '+e;}};
          window.clearGeoJson=function(){window.geoGroup.clearLayers();};
          window.setBasemap(__BASEKEY__);
          window.zoomBounds=function(a,b,c,d){MAP.fitBounds([[a,b],[c,d]]);};
          MAP.on('click',function(e){
            document.title='B2 '+e.latlng.lng+'|'+e.latlng.lat;});
          window.onerror=function(msg){document.title='B2ERR '+msg;return false;};
          setTimeout(function(){MAP.invalidateSize();MAP.fitBounds(window._bounds);
            if(window._tile&&window._tile.bringToBack)window._tile.bringToBack();},300);
          window.setRedAll(__GAUGES__);
          __BLUEINIT__
        })();
        """
        return (tpl.replace("__MAP__", map_var)
                   .replace("__UPS__", ups_var)
                   .replace("__MASK__", mask_var)
                   .replace("__BASEKEY__", json.dumps(self._basemap_key))
                   .replace("__BOUNDS__", json.dumps(bounds))
                   .replace("__OP__", repr(float(self._overlay_opacity)))
                   .replace("__BASEOP__", repr(float(self._base_opacity)))
                   .replace("__DEC__", str(int(dec)))
                   .replace("__GAUGES__", json.dumps(gauges))
                   .replace("__BLUEINIT__", blue_init))

    def _show_map(self):
        try:
            html = self._build_map_html()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.info_label.setText(f"Basin2 map build failed: {e}")
            return
        # Serve the page through the shared osmtile:// handler (same origin as the
        # tiles -> proxy-proof, cached) - the same mechanism as classic Show Basin.
        try:
            from src.gui.widgets.basin_viewer import _get_tile_handler
            self._tile_handler = _get_tile_handler()
            self._tile_handler.set_html2(html)
            profile = self.web_view.page().profile()
            try:
                profile.removeUrlSchemeHandler(self._tile_handler)
            except Exception:
                pass
            profile.installUrlSchemeHandler(b"osmtile", self._tile_handler)
            self.web_view.loadFinished.connect(self._on_loaded)
            self.web_view.load(QUrl("osmtile://map2/"))
        except Exception:
            # Fallback: plain temp file (basemap may stay blank behind a proxy)
            log.debug("basin2: osmtile page serving failed", exc_info=True)
            tmp = tempfile.NamedTemporaryFile(
                prefix="cwatm_basin2_", suffix=".html", delete=False,
                mode="w", encoding="utf-8")
            tmp.write(html)
            tmp.close()
            self._temp_html = tmp.name
            self.web_view.loadFinished.connect(self._on_loaded)
            self.web_view.load(QUrl.fromLocalFile(tmp.name))

    def _on_loaded(self, ok):
        if not ok:
            print("Basin2: map page failed to load", file=sys.stderr)
            return
        # The Leaflet map + helper functions exist now: flush queued JS, then
        # re-apply the markers from the current text boxes.
        self._map_ready = True
        queued, self._js_queue = self._js_queue, []
        for code in queued:
            self._js(code)
        QTimer.singleShot(300, self._refresh_markers)

    # ---------------------------------------------------------- JS plumbing
    def _js(self, code):
        """Run JS on the map page; queued until the page finished loading."""
        if not self._map_ready:
            self._js_queue.append(code)
            return
        try:
            self.web_view.page().runJavaScript(code)
        except Exception:
            log.debug("basin2 JS failed", exc_info=True)

    def _refresh_markers(self):
        """RED = the working gauge list (numbered), BLUE = mask start, BLACK cleared."""
        arr = [[lat, lon, self._ups_text(lon, lat)]
               for lon, lat in self._gauges]
        self._js("if(window.setRedAll) setRedAll(%s);" % json.dumps(arr))
        self._blue_pt = self._mask_start_point()
        if self._blue_pt:
            lon, lat = self._blue_pt
            self._js("if(window.setBlue) setBlue(%f,%f,%s);"
                     % (lat, lon, json.dumps(self._ups_text(lon, lat))))
        self._js("if(window.clearBlack) clearBlack();")

    def _on_web_title(self, title):
        if title.startswith("B2ERR"):
            print(f"Basin2 map error: {title[6:]}", file=sys.stderr)
            return
        if title.startswith("B2DEL "):
            # A gauge pin was clicked -> remove it from the working gauge list.
            try:
                idx = int(title.split()[1])
            except Exception:
                return
            self._remove_gauge(idx)
            return
        if not title.startswith("B2 "):
            return
        try:
            lon_s, lat_s = title[3:].split("|", 1)
            lon, lat = float(lon_s), float(lat_s)
        except Exception:
            return
        self.last_clicked_lon, self.last_clicked_lat = lon, lat
        self._js("if(window.setBlack) setBlack(%f,%f,%s);"
                 % (lat, lon, json.dumps(self._ups_text(lon, lat))))
        # Same read-out as the classic viewer (global display decimals)
        try:
            row = int(np.abs(self.lats - lat).argmin())
            col = int(np.abs(self.lons - lon).argmin())
            basin = np.asarray(self.basin_data, dtype=float)
            val = basin[row, col]
            area = "no data" if np.isnan(val) else f"{display_format.fmt(val)} km²"
            if self.mask_data is not None and \
               np.asarray(self.mask_data).shape == basin.shape:
                inmask = "yes" if np.asarray(self.mask_data)[row, col] == 1 else "no"
            else:
                inmask = "-"
            self.info_label.setText(
                f"Lat: {display_format.fmt(lat)} | Lon: {display_format.fmt(lon)}"
                f" | Basin area: {area} | Mask: {inmask}")
        except Exception:
            self.info_label.setText(
                f"Lat: {display_format.fmt(lat)} | Lon: {display_format.fmt(lon)}")

    # -------------------------------------------------------------- actions
    def _toggle_mask(self):
        self.show_mask = self.mask_button.isChecked()
        self.mask_button.setText("Hide Mask" if self.show_mask else "Show Mask")
        self._js("if(window.setMaskVisible) setMaskVisible(%s);"
                 % ("true" if self.show_mask else "false"))

    def _on_opacity_changed(self, value):
        # One slider fades BOTH layers as it goes 0 -> 100% (like NetCDF):
        #   OSM basemap opacity   : 0.0 -> 1.0  (hidden -> fully visible)
        #   ups.nc/mask overlay   : 1.0 -> 0.5  (fully opaque -> 50% on top)
        t = max(0.0, min(1.0, value / 100.0))
        self._base_opacity = t
        self._overlay_opacity = 1.0 - 0.5 * t
        self._js("if(window.setBaseOpacity) setBaseOpacity(%f);" % self._base_opacity)
        self._js("if(window.setOverlayOpacity) setOverlayOpacity(%f);"
                 % self._overlay_opacity)

    def _on_basemap_changed(self, index):
        key = self.basemap_combo.itemData(index)
        if key:
            self._basemap_key = key
            self._js("if(window.setBasemap) setBasemap(%s);" % json.dumps(key))

    def _load_json(self):
        """Open a GeoJSON file and draw it on the map as an L.geoJSON overlay."""
        start_dir = os.path.dirname(self.settings_file) if getattr(
            self, "settings_file", "") else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Load GeoJSON", start_dir,
            "GeoJSON files (*.geojson *.json);;All files (*)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "Load JSON",
                                f"Could not read/parse the file:\n{e}")
            return
        self.info_label.setText(f"Loaded GeoJSON: {os.path.basename(path)}")
        self._js("if(window.addGeoJson) addGeoJson(%s);" % json.dumps(obj))

    def _zoom_to_mask(self):
        bbox = self._mask_bbox()
        if bbox is None:
            self.info_label.setText("No mask to zoom to.")
            return
        r0, r1, c0, c1 = bbox
        south = float(min(self.lats[r0], self.lats[r1]))
        north = float(max(self.lats[r0], self.lats[r1]))
        west = float(min(self.lons[c0], self.lons[c1]))
        east = float(max(self.lons[c0], self.lons[c1]))
        self._js("if(window.zoomBounds) zoomBounds(%f,%f,%f,%f);"
                 % (south, west, north, east))

    def _use_coordinates(self):
        """Copy Mask: write the clicked coordinate into the MaskMap box and re-run
        the gauge-in-mask check (identical behaviour to the classic viewer)."""
        if not hasattr(self, "last_clicked_lon"):
            print("No coordinates available - create a mask first", file=sys.stderr)
            return
        coord = f"{self.last_clicked_lon:.4f} {self.last_clicked_lat:.4f}"
        mw = self._main_window()
        if mw is None:
            print("Could not find MaskMap field in main GUI", file=sys.stderr)
            return
        mw.maskmap_field.setText(coord)
        self._run_gauge_check(mw, rebuild_mask=True)
        self._refresh_markers()
        self.use_coords_button.setEnabled(False)
        self.info_label.setText(f"Mask copied to settings: {coord}")

    def _create_gauge(self):
        """Append the clicked point to the working gauge list as a new numbered red
        pin (does NOT replace the existing gauges)."""
        if hasattr(self, "last_clicked_lon"):
            lon, lat = self.last_clicked_lon, self.last_clicked_lat
        elif self._blue_pt:
            lon, lat = self._blue_pt
        else:
            self.info_label.setText("Click a location first to create a gauge.")
            return
        self._gauges.append((lon, lat))
        self._js("if(window.clearBlack) clearBlack();")
        self._refresh_markers()
        self.copy_gauge_button.setEnabled(True)
        self.info_label.setText(
            f"Added gauge {len(self._gauges)} ({lon:.4f} {lat:.4f}) - "
            "use Copy Gauge to write all gauges to the settings.")

    def _copy_gauge(self):
        """Write the whole working gauge list to the main-window Gauges box (which
        auto-applies to the settings) and re-run the gauge-in-mask check."""
        mw = self._main_window()
        if mw is not None:
            mw.gauges_field.setText(
                " ".join(f"{lon:.4f} {lat:.4f}" for lon, lat in self._gauges))
            self._run_gauge_check(mw, rebuild_mask=False)
        self.info_label.setText(
            f"Copied {len(self._gauges)} gauge(s) to the settings"
            + ("" if mw is not None else " (main Gauges field not found)"))

    def _remove_gauge(self, idx):
        """Clicking a red gauge pin removes it from the working list; the remaining
        pins are renumbered. (Commit to the settings with Copy Gauge.)"""
        if idx < 0 or idx >= len(self._gauges):
            return
        removed = self._gauges.pop(idx)
        self._refresh_markers()
        self.copy_gauge_button.setEnabled(True)
        self.info_label.setText(
            f"Removed gauge {idx + 1} ({removed[0]:.4f} {removed[1]:.4f}) - "
            "use Copy Gauge to update the settings.")

    def _create_new_mask(self):
        """Generate a new mask from the clicked coordinate (same CWatM -vgm call
        as the classic viewer) and update the mask image overlay in place."""
        if not hasattr(self, "last_clicked_lat"):
            print("No coordinates available - click on the map first", file=sys.stderr)
            return
        if not self.settings_file:
            print("No settings file available for mask creation", file=sys.stderr)
            return
        try:
            import cwatm.run_cwatm as run_cwatm
            import configparser
            config = configparser.ConfigParser()
            config.optionxform = str
            config.read(self.settings_file)
            coord = f"{self.last_clicked_lon:.4f} {self.last_clicked_lat:.4f}"
            if not config.has_section('MASK_OUTLET'):
                config.add_section('MASK_OUTLET')
            config.set('MASK_OUTLET', 'MaskMap', coord)
            config.set('MASK_OUTLET', 'Gauges', coord)

            temp_path = os.path.join(os.path.dirname(self.settings_file),
                                     f"temp_mask2_{os.getpid()}.ini")
            with open(temp_path, 'w') as f:
                config.write(f)
            try:
                result = run_cwatm.mainwarm(temp_path, ["-vgm"], [])
            finally:
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            if not result:
                print("Failed to create new mask - no result from CWatM",
                      file=sys.stderr)
                return

            new_mask = np.where(result[0].data != 1, 0, 1)
            if new_mask.shape != self.basin_data.shape:
                x, y = result[1], result[2]
                big = np.zeros(self.basin_data.shape)
                big[y:y + new_mask.shape[0], x:x + new_mask.shape[1]] = new_mask
                self.mask_data = big
            else:
                self.mask_data = new_mask

            # Update / add the mask image overlay in place (keeps zoom/pan)
            self.show_mask = True
            uri = self._rgba_to_datauri(self._upscale_rgba(self._build_mask_rgba()))
            self._js("if(window.updateMask) updateMask(%s);" % json.dumps(uri))

            # The clicked point is the new mask start: black -> blue
            self._blue_pt = (self.last_clicked_lon, self.last_clicked_lat)
            self._js("if(window.setBlue) setBlue(%f,%f,%s);"
                     % (self._blue_pt[1], self._blue_pt[0],
                        json.dumps(self._ups_text(*self._blue_pt))))
            self._js("if(window.clearBlack) clearBlack();")
            if not self.mask_button.isEnabled():
                self.mask_button.setEnabled(True)
            self.mask_button.setChecked(True)
            self.mask_button.setText("Hide Mask")
            self.use_coords_button.setEnabled(True)
            self.info_label.setText(
                f"New mask created at {coord} - use Copy Mask to save it.")
        except Exception as e:
            print(f"Error creating new mask: {e}", file=sys.stderr)

    # ------------------------------------------------------------- cleanup
    def closeEvent(self, event):
        try:
            if self._temp_html and os.path.exists(self._temp_html):
                os.remove(self._temp_html)
        except Exception:
            pass
        super().closeEvent(event)
