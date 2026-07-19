"""
NetCDF analysis widget (Analyse ▸ NetCDF) - the NetCDF viewer on a **folium**
(Leaflet, EPSG:4326) map with an OpenStreetMap background.

Draws the variable as a Leaflet **ImageOverlay** over an OSM **WMS** basemap
(EPSG:4326, like Show Basin), with a timestep slider + Play, colour-scale selector,
Log-scale toggle, an OSM-transparency slider, a basemap selector, click-to-mark,
Display timeserie and Save HTML.

The data-reading, meta lookup and per-cell time-series re-read are **reused from
``NetcdfDataBase``** (in ``analysis_netcdf_base.py``; this class subclasses it); only
the rendering/interaction is implemented here. The clicked points are drawn as
**numbered pin icons coloured to match their line** in the Timeseries window.
"""

import os
import sys
import json
import base64
import tempfile

import numpy as np

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QSlider, QFileDialog, QMessageBox, QProgressBar,
)
from PySide6.QtCore import Qt, QUrl, QTimer, QThread, Signal
from PySide6.QtGui import QIcon, QImage
from PySide6.QtCore import QByteArray, QBuffer

from src.gui.utils import theme
from src.gui.utils.gui_log import get_logger

log = get_logger("analysis_netcdf")

# The shared NetCDF data layer (file reading + point series) and the colour-scale /
# play-speed tables live in analysis_netcdf_base.
from src.gui.widgets.analysis_netcdf_base import (
    NetcdfDataBase, _NC_AVAILABLE, _NC_IMPORT_ERROR, _COLORSCALES,
    _DEFAULT_COLORSCALE, _PLAY_SPEEDS, _DEFAULT_PLAY_SPEED, _position_offset,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    import folium
    import plotly.colors as _pcolors
    _NC2_AVAILABLE = _NC_AVAILABLE
    _NC2_IMPORT_ERROR = _NC_IMPORT_ERROR
except Exception as _e:  # pragma: no cover - import guard
    _NC2_AVAILABLE = False
    _NC2_IMPORT_ERROR = f"{type(_e).__name__}: {_e}"

# EPSG:4326 WMS basemaps (same set as Show Basin2).
from src.gui.widgets.basin_viewer2 import (
    _B2_PROVIDERS, _B2_DEFAULT_LAYER, _strip_unused_assets, _inline_remote_assets,
)


class _PointSeriesWorker(QThread):
    """Read the full-resolution time series of each requested cell off the GUI thread.

    Reading every timestep for a cell (now that the whole series is loaded, not the
    strided map frames) can be slow on large / networked files, so it runs here and
    reports per-point progress. ``_series_for``/``_point_series`` open their own dataset
    per call, so this is safe to run in a worker thread."""

    progress = Signal(int, int)     # points done, total
    finished_ok = Signal(list)      # [ [values...], ... ] one entry per point
    failed = Signal(str)

    def __init__(self, reader, points, full=True, parent=None):
        super().__init__(parent)
        self._reader = reader       # the NetcdfWindow (uses _series_for)
        self._points = list(points)
        self._full = full

    def run(self):
        try:
            out = []
            n = len(self._points)
            for i, p in enumerate(self._points):
                out.append(self._reader._series_for(p, full=self._full))
                self.progress.emit(i + 1, n)
            self.finished_ok.emit(out)
        except Exception as e:  # pragma: no cover - defensive
            self.failed.emit(str(e))


def open_netcdf(parent=None):
    """Prompt for a .nc file and open the folium NetCDF window."""
    if not _NC2_AVAILABLE:
        QMessageBox.warning(
            parent, "NetCDF",
            "xarray / folium / QtWebEngine are not available.\n\n" + _NC2_IMPORT_ERROR
            + "\n\nInstall with:  pip install xarray folium plotly")
        return
    start_dir = ""
    try:
        if parent is not None and hasattr(parent, "_resolved_pathout_dir"):
            start_dir = parent._resolved_pathout_dir() or ""
    except Exception:
        start_dir = ""
    path, _ = QFileDialog.getOpenFileName(
        parent, "Open NetCDF file", start_dir, "NetCDF files (*.nc)")
    if not path:
        return
    try:
        win = NetcdfWindow(path, parent)
        win.exec()
    except Exception as e:
        import traceback
        traceback.print_exc()
        QMessageBox.warning(parent, "NetCDF", f"Could not open the file:\n{e}")


class NetcdfWindow(NetcdfDataBase):
    """folium (Leaflet, EPSG:4326) NetCDF viewer with an OSM WMS background."""

    def __init__(self, nc_path, parent=None):
        # NetcdfDataBase provides the data-loading helpers (no UI); build our own
        # folium UI here.
        QDialog.__init__(self, parent)
        self.nc_path = nc_path
        (self.varname, self.lons, self.lats, self.frames,
         self.time_labels, self.zmin, self.zmax,
         self.settings_title) = self._load(nc_path)
        self.unit, self.long_name, self.description = self._lookup_meta(self.varname)

        self._multi = len(self.frames) > 1
        self._clicked = None
        self._ts_window = None
        self._ts_worker = None                # background point-series reader
        self._ts_next = None                  # latest (pts, open_if_closed, full) request
        self._ts_full = True                  # current mode: True=Total, False=Fast
        self._displayed_points = []           # [(lon, lat, colour)]
        self._colorscale_name = _DEFAULT_COLORSCALE
        self._compare_mode = False            # showing an A−B difference?
        self._orig = None                     # saved A state while comparing
        self._ti = 0                          # current timestep index
        # Initial transparency from Configure > Transparency (0-100). The slider couples
        # both layers: OSM opacity = t, NetCDF overlay opacity = 1 - 0.5*t.
        from src.gui.utils import display_format as _df
        _t = max(0.0, min(1.0, _df.get_transparency() / 100.0))
        self._base_opacity = _t               # OSM basemap opacity (the slider)
        self._overlay_opacity = 1.0 - 0.5 * _t  # NetCDF overlay opacity
        self._log_scale = True                # logarithmic colour mapping (default)
        self._basemap_key = _B2_DEFAULT_LAYER
        self._lut_cache = {}                  # colorscale name -> (256,3) uint8
        self._uri_cache = {}                  # (colorscale, log, ti) -> data URI
        self._map_ready = False
        self._js_queue = []
        self._temp_html = None
        # lon orientation for the ImageOverlay (data columns must run west->east)
        self._lon_ascending = bool(self.lons[0] <= self.lons[-1])

        self.setWindowTitle(f"\U0001F5FA NetCDF: {os.path.basename(nc_path)}")
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        if not self._init_geometry_memory("netcdf"):
            self.resize(1000, 780)
            _position_offset(self, -0.15)
        try:
            icon_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                'assets', 'cwatm.ico')
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass

        # Qt timer that drives Play (the folium overlay has no built-in animation).
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._play_tick)

        self._build_ui()
        self._show_map()

    # -------------------------------------------------------- colour mapping
    def _lut(self, name):
        """256x3 uint8 colour lookup table for a colour-scale name (cached)."""
        if name in self._lut_cache:
            return self._lut_cache[name]
        scale, reverse = _COLORSCALES[name]
        cols = _pcolors.sample_colorscale(scale, list(np.linspace(0, 1, 256)),
                                          colortype="rgb")
        lut = np.array([[int(c) for c in s[4:-1].split(",")] for s in cols],
                       dtype=np.uint8)
        if reverse:
            lut = lut[::-1]
        self._lut_cache[name] = lut
        return lut

    def _colorize(self, ti):
        """Colour timestep ``ti`` to a north-up, west->east RGBA image. When
        ``_log_scale`` the value->colour mapping is logarithmic (log1p of the value
        shifted by zmin, so it works for a zero/negative minimum too)."""
        z = self.frames[ti]
        finite = np.isfinite(z)
        if self._log_scale:
            den = np.log1p(max(self.zmax - self.zmin, 0.0)) or 1.0
            a = np.clip(z, self.zmin, self.zmax)
            norm = np.where(finite, np.log1p(a - self.zmin) / den, 0.0)
        else:
            denom = (self.zmax - self.zmin) or 1.0
            norm = np.where(finite, np.clip((z - self.zmin) / denom, 0.0, 1.0), 0.0)
        idx = np.clip((norm * 255).astype(np.int32), 0, 255)
        rgb = self._lut(self._colorscale_name)[idx]
        rgba = np.zeros((z.shape[0], z.shape[1], 4), dtype=np.uint8)
        rgba[..., :3] = rgb
        rgba[..., 3] = np.where(finite, 255, 0).astype(np.uint8)
        if not self._lon_ascending:
            rgba = rgba[:, ::-1]
        # self.lats is ascending (south->north); ImageOverlay origin='upper' wants
        # the first row to be north, so flip vertically.
        return rgba[::-1]

    @staticmethod
    def _rgba_to_datauri(rgba):
        h, w = rgba.shape[:2]
        qimg = QImage(np.ascontiguousarray(rgba).tobytes(), w, h, 4 * w,
                      QImage.Format_RGBA8888).copy()
        ba = QByteArray()
        b = QBuffer(ba)
        b.open(QBuffer.WriteOnly)
        qimg.save(b, "PNG")
        b.close()
        return "data:image/png;base64," + base64.b64encode(bytes(ba)).decode("ascii")

    def _frame_uri(self, ti):
        key = (self._colorscale_name, self._log_scale, ti)
        uri = self._uri_cache.get(key)
        if uri is None:
            uri = self._rgba_to_datauri(self._colorize(ti))
            self._uri_cache[key] = uri
        return uri

    def _grid_bounds(self):
        lons, lats = self.lons, self.lats
        dlon = abs(float(lons[1] - lons[0])) if lons.size > 1 else 0.01
        dlat = abs(float(lats[1] - lats[0])) if lats.size > 1 else 0.01
        west = float(lons.min()) - dlon / 2.0
        east = float(lons.max()) + dlon / 2.0
        south = float(lats.min()) - dlat / 2.0
        north = float(lats.max()) + dlat / 2.0
        return west, east, south, north

    def _colorbar_gradient(self):
        lut = self._lut(self._colorscale_name)
        stops = []
        for i in range(9):
            r, g, b = lut[int(i / 8 * 255)]
            stops.append("rgb(%d,%d,%d) %d%%" % (r, g, b, int(i / 8 * 100)))
        return "linear-gradient(to top," + ",".join(stops) + ")"

    # ----------------------------------------------------------------- UI
    def _build_ui(self):
        from src.gui.utils import display_format  # noqa: F401 (keeps parity/import warm)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        head = os.path.basename(self.nc_path)
        if self.settings_title:
            head += f"   —   {self.settings_title}"
        self.header_label = QLabel(head)
        self.header_label.setAlignment(Qt.AlignCenter)
        self.header_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 14px; font-weight: 600; "
            f"color: {theme.c('text')}; padding: 4px;")
        layout.addWidget(self.header_label)

        self.web_view = QWebEngineView()
        self.web_view.titleChanged.connect(self._on_web_title)
        layout.addWidget(self.web_view, 1)

        self.info_label = QLabel("Click on the map to see coordinates and values")
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 12px; "
            f"color: {theme.c('text_muted')}; padding: 3px;")
        layout.addWidget(self.info_label)

        _btn = """
            QPushButton { font-family: 'Segoe UI', sans-serif; font-size: 12px;
                font-weight: 500; color: white; border: none; border-radius: 6px;
                padding: 5px 14px; min-height: 22px;
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #5dade2, stop:1 #3498db); }
            QPushButton:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #85c1e9, stop:1 #5dade2); }
            QPushButton:disabled { background: #d3d3d3; color: #a9a9a9; }
        """
        _lbl = f"font-family:'Segoe UI',sans-serif; font-size:12px; color:{theme.c('text')};"

        # Row 1 (time control): Play | timestep slider | date | Speed
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        self.play_button = QPushButton("▶ Play")
        self.play_button.setStyleSheet(_btn)
        self.play_button.clicked.connect(self._toggle_play)
        self.play_button.setVisible(self._multi)
        row1.addWidget(self.play_button)

        self.time_slider = QSlider(Qt.Horizontal)
        self.time_slider.setRange(0, max(0, len(self.frames) - 1))
        self.time_slider.valueChanged.connect(self._on_time_changed)
        self.time_slider.setVisible(self._multi)
        row1.addWidget(self.time_slider, 1)

        self.time_label = QLabel(self.time_labels[0] if self.time_labels else "")
        self.time_label.setStyleSheet(_lbl)
        self.time_label.setMinimumWidth(90)
        self.time_label.setVisible(self._multi)
        row1.addWidget(self.time_label)

        speed_label = QLabel("Speed:")
        speed_label.setStyleSheet(_lbl)
        speed_label.setVisible(self._multi)
        row1.addWidget(speed_label)
        self.speed_combo = QComboBox()
        for name in _PLAY_SPEEDS:
            self.speed_combo.addItem(name)
        self.speed_combo.setCurrentText(_DEFAULT_PLAY_SPEED)
        self.speed_combo.currentTextChanged.connect(self._on_play_speed)
        self.speed_combo.setVisible(self._multi)
        row1.addWidget(self.speed_combo)
        layout.addLayout(row1)

        # Row 2 (appearance): Colour scale | Overlay transparency | Basemap | Hide OSM
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        cs = QLabel("Colour scale:")
        cs.setStyleSheet(_lbl)
        row2.addWidget(cs)
        self.colorscale_combo = QComboBox()
        for name in _COLORSCALES:
            self.colorscale_combo.addItem(name)
        self.colorscale_combo.setCurrentText(_DEFAULT_COLORSCALE)
        self.colorscale_combo.currentTextChanged.connect(self._on_colorscale)
        row2.addWidget(self.colorscale_combo)

        tl = QLabel("OSM transparency:")
        tl.setStyleSheet(_lbl)
        row2.addWidget(tl)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setToolTip(
            "0% = OSM hidden + NetCDF fully opaque (only the NetCDF, on white); "
            "100% = OSM fully visible + NetCDF 50% opaque on top")
        self.opacity_slider.setValue(int(self._base_opacity * 100))
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        row2.addWidget(self.opacity_slider, 1)

        bl = QLabel("Basemap:")
        bl.setStyleSheet(_lbl)
        row2.addWidget(bl)
        self.basemap_combo = QComboBox()
        for label, key in _B2_PROVIDERS:
            self.basemap_combo.addItem(label, key)
        _i = self.basemap_combo.findData(self._basemap_key)
        if _i >= 0:
            self.basemap_combo.setCurrentIndex(_i)
        self.basemap_combo.currentIndexChanged.connect(self._on_basemap_changed)
        row2.addWidget(self.basemap_combo)

        self.log_button = QPushButton("Log scale")
        self.log_button.setStyleSheet(_btn)
        self.log_button.setCheckable(True)
        self.log_button.setToolTip("Map the values to colour on a logarithmic scale")
        # Log scale is the default: reflect it in the button (checked + "Linear
        # scale" label) before connecting the toggle, so no premature update fires.
        self.log_button.setChecked(self._log_scale)
        self.log_button.setText("Linear scale" if self._log_scale else "Log scale")
        self.log_button.toggled.connect(self._toggle_log)
        row2.addWidget(self.log_button)
        layout.addLayout(row2)

        # Row 3 (actions): Fast Display Timeserie | Total Timeseries | ... | Save HTML
        row3 = QHBoxLayout()
        row3.setSpacing(8)
        self.ts_fast_button = QPushButton("Fast Display Timeserie")
        self.ts_fast_button.setStyleSheet(_btn)
        self.ts_fast_button.setToolTip(
            "Plot the clicked point quickly using the map's timesteps (has gaps)")
        self.ts_fast_button.clicked.connect(self._display_timeseries_fast)
        self.ts_fast_button.setVisible(self._multi)
        row3.addWidget(self.ts_fast_button)
        self.ts_button = QPushButton("Total Timeseries")
        self.ts_button.setStyleSheet(_btn)
        self.ts_button.setToolTip(
            "Load and plot the FULL time series of the clicked point (every timestep) - "
            "can take a while; progress is shown on the right")
        self.ts_button.clicked.connect(self._display_timeseries_full)
        self.ts_button.setVisible(self._multi)
        row3.addWidget(self.ts_button)
        # Progress bar (right of the buttons): the full-resolution point series can take
        # a while to read, so show per-point progress while it loads.
        self.ts_progress = QProgressBar()
        self.ts_progress.setTextVisible(True)
        self.ts_progress.setFixedWidth(180)
        self.ts_progress.setVisible(False)
        self.ts_progress.setStyleSheet(
            f"QProgressBar {{ border: 1px solid {theme.c('border')}; border-radius: 4px; "
            f"background: {theme.c('out_bg')}; color: {theme.c('text')}; "
            "text-align: center; height: 18px; }"
            "QProgressBar::chunk { background: #3498db; border-radius: 3px; }")
        row3.addWidget(self.ts_progress)
        row3.addStretch(1)
        self.compare_button = QPushButton("Compare A−B")
        self.compare_button.setStyleSheet(_btn)
        self.compare_button.setToolTip(
            "Load a second .nc on the same grid and show the difference (this − other) "
            "on a diverging colour scale")
        self.compare_button.clicked.connect(self._toggle_compare)
        row3.addWidget(self.compare_button)
        self.save_html_button = QPushButton("Save HTML")
        self.save_html_button.setStyleSheet(_btn)
        self.save_html_button.clicked.connect(self._save_html)
        row3.addWidget(self.save_html_button)
        layout.addLayout(row3)

    # -------------------------------------------------------------- map build
    def _show_map(self):
        west, east, south, north = self._grid_bounds()
        bounds = [[south, west], [north, east]]
        m = folium.Map(location=[(south + north) / 2.0, (west + east) / 2.0],
                       zoom_start=8, crs="EPSG4326", tiles=None,
                       control_scale=True, zoom_control=True)
        ov = folium.raster_layers.ImageOverlay(
            image="https://cwatm.invalid/overlay.png", bounds=bounds,
            opacity=self._overlay_opacity, mercator_project=False,
            pixelated=True, name="nc")
        ov.url = self._frame_uri(0)
        ov.add_to(m)

        js = self._helper_js(m.get_name(), ov.get_name(), bounds)
        html = m.get_root().render()

        cbar_unit = f"[{self.unit}]" if self.unit else ""
        css = ("<style>html,body{width:100%;height:100%;margin:0;padding:0;}"
               ".folium-map{position:absolute!important;top:0;left:0;"
               "width:100%!important;height:100%!important;}"
               ".leaflet-image-layer{image-rendering:pixelated;image-rendering:crisp-edges;}"
               ".leaflet-container,.leaflet-grab,"
               ".leaflet-dragging .leaflet-grab{cursor:default!important;}"
               ".nc-pin{width:24px;height:24px;border-radius:50% 50% 50% 0;"
               "transform:rotate(-45deg);border:2px solid #fff;"
               "box-shadow:0 1px 3px rgba(0,0,0,.45);display:flex;"
               "align-items:center;justify-content:center;}"
               ".nc-pin span{transform:rotate(45deg);color:#fff;"
               "font:bold 12px 'Segoe UI',Arial,sans-serif;line-height:1;}"
               ".nc-gauge{width:17px;height:17px;border-radius:50% 50% 50% 0;"
               "transform:rotate(-45deg);background:#e11d1d;border:2px solid #fff;"
               "box-shadow:0 1px 2px rgba(0,0,0,.4);display:flex;"
               "align-items:center;justify-content:center;}"
               ".nc-gauge span{transform:rotate(45deg);color:#fff;"
               "font:bold 9px 'Segoe UI',Arial,sans-serif;line-height:1;}"
               "#nc-cbar{position:absolute;right:12px;top:60px;z-index:1000;"
               "background:rgba(255,255,255,.85);border:1px solid #999;border-radius:5px;"
               "padding:6px 8px;font:11px 'Segoe UI',Arial,sans-serif;color:#222;"
               "text-align:center;}"
               "#nc-cbar-grad{width:16px;height:120px;margin:2px auto;border:1px solid #888;}"
               "</style>")
        cbar = ("<div id='nc-cbar'><div id='nc-cbar-max'>%s</div>"
                "<div id='nc-cbar-grad' style=\"background:%s\"></div>"
                "<div id='nc-cbar-min'>%s</div><div>%s</div></div>"
                % (self._fmt_val(self.zmax), self._colorbar_gradient(),
                   self._fmt_val(self.zmin), cbar_unit))
        if "</head>" in html:
            html = html.replace("</head>", css + "</head>", 1)
        html = _strip_unused_assets(html)
        html = _inline_remote_assets(html)
        # The colour-bar div is plain chrome -> inside <body>.
        if "</body>" in html:
            html = html.replace("</body>", cbar + "</body>", 1)
        else:
            html = html + cbar
        # The helper <script> must run AFTER folium's map-init script (which defines
        # the global map/overlay vars). folium puts that script last, so insert ours
        # right before </html> — inserting before </body> ran it too early, leaving
        # __MAP__ undefined so the IIFE threw and none of the window.* helpers
        # (basemap / opacity / colour scale / timestep / points) were ever defined.
        helper = "<script>\n%s\n</script>" % js
        if "</html>" in html:
            html = html.replace("</html>", helper + "\n</html>", 1)
        else:
            html = html + helper
        self._page_html = html
        # Serve same-origin through the shared osmtile handler (proxy-proof tiles/WMS).
        try:
            from src.gui.widgets.basin_viewer import _get_tile_handler
            self._tile_handler = _get_tile_handler()
            self._tile_handler.set_page("ncmap", html)
            profile = self.web_view.page().profile()
            try:
                profile.removeUrlSchemeHandler(self._tile_handler)
            except Exception:
                pass
            profile.installUrlSchemeHandler(b"osmtile", self._tile_handler)
            self.web_view.loadFinished.connect(self._on_loaded)
            self.web_view.load(QUrl("osmtile://ncmap/"))
        except Exception:
            log.debug("netcdf: osmtile serving failed", exc_info=True)
            tmp = tempfile.NamedTemporaryFile(
                prefix="cwatm_nc2_", suffix=".html", delete=False, mode="w",
                encoding="utf-8")
            tmp.write(html)
            tmp.close()
            self._temp_html = tmp.name
            self.web_view.loadFinished.connect(self._on_loaded)
            self.web_view.load(QUrl.fromLocalFile(tmp.name))

    def _fmt_val(self, v):
        from src.gui.utils import display_format
        try:
            return display_format.fmt(float(v))
        except Exception:
            return str(v)

    def _helper_js(self, map_var, ov_var, bounds):
        tpl = r"""
        (function(){
          var MAP=__MAP__; window._map=MAP; window._ov=__OV__;
          window._bounds=__BOUNDS__; window._op=__OP__; window._tile=null;
          window._baseOp=__BASEOP__;
          function pin(color,label){return L.divIcon({className:'',
            html:'<div class="nc-pin" style="background:'+color+'">'
                 +'<span>'+(label||'')+'</span></div>',
            iconSize:[24,24], iconAnchor:[12,23], tooltipAnchor:[0,-20]});}
          function gpin(label){return L.divIcon({className:'',
            html:'<div class="nc-gauge"><span>'+(label||'')+'</span></div>',
            iconSize:[17,17], iconAnchor:[8,16], tooltipAnchor:[0,-14]});}
          window.gaugeGroup=L.layerGroup().addTo(MAP);
          window.setGauges=function(arr){window.gaugeGroup.clearLayers();
            arr.forEach(function(g,i){
              L.marker([g[0],g[1]],{icon:gpin(String(i+1))}).addTo(window.gaugeGroup)
               .bindTooltip('Gauge '+(i+1));});};
          window.setBasemap=function(layer){
            if(window._tile){MAP.removeLayer(window._tile);}
            window._tile=L.tileLayer.wms('osmtile://wms/service',{layers:layer,
              format:'image/png',version:'1.1.1',transparent:false,maxZoom:19,
              opacity:window._baseOp,
              attribution:'(c) OpenStreetMap contributors'}).addTo(MAP);
            if(window._tile.bringToBack)window._tile.bringToBack();};
          window.setBaseOpacity=function(o){window._baseOp=o;
            if(window._tile)window._tile.setOpacity(o);};
          window.updateNc=function(uri){if(window._ov)window._ov.setUrl(uri);};
          window.setNcOpacity=function(o){window._op=o;
            if(window._ov)window._ov.setOpacity(o);};
          window.pendingMarker=null;
          window.setPending=function(lat,lon){
            if(window.pendingMarker){MAP.removeLayer(window.pendingMarker);}
            window.pendingMarker=L.marker([lat,lon],{icon:pin('#e11d1d','')})
              .addTo(MAP);};
          window.clearPending=function(){if(window.pendingMarker){
            MAP.removeLayer(window.pendingMarker);window.pendingMarker=null;}};
          window.ptGroup=L.layerGroup().addTo(MAP);
          window.setPoints=function(arr){window.ptGroup.clearLayers();
            arr.forEach(function(p){
              var mk=L.marker([p[0],p[1]],{icon:pin(p[2],p[3])}).addTo(window.ptGroup)
               .bindTooltip('Point '+p[3]+' (click to remove)');
              mk.on('click',function(ev){L.DomEvent.stopPropagation(ev);
                document.title='NC2DEL '+p[3]+' '+Date.now();});});};
          window.setColorbar=function(grad,mx,mn){
            var g=document.getElementById('nc-cbar-grad');if(g)g.style.background=grad;
            var a=document.getElementById('nc-cbar-max');if(a)a.textContent=mx;
            var b=document.getElementById('nc-cbar-min');if(b)b.textContent=mn;};
          MAP.on('click',function(e){document.title='NC2 '+e.latlng.lng+'|'+e.latlng.lat;});
          window.onerror=function(m){document.title='NC2ERR '+m;return false;};
          window.setBasemap(__BASEKEY__);
          setTimeout(function(){MAP.invalidateSize();MAP.fitBounds(window._bounds);
            if(window._tile&&window._tile.bringToBack)window._tile.bringToBack();},300);
        })();
        """
        return (tpl.replace("__MAP__", map_var)
                   .replace("__OV__", ov_var)
                   .replace("__BOUNDS__", json.dumps(bounds))
                   .replace("__OP__", repr(float(self._overlay_opacity)))
                   .replace("__BASEOP__", repr(float(self._base_opacity)))
                   .replace("__BASEKEY__", json.dumps(self._basemap_key)))

    def _on_loaded(self, ok):
        if not ok:
            print("NetCDF: map page failed to load", file=sys.stderr)
            return
        self._map_ready = True
        queued, self._js_queue = self._js_queue, []
        for code in queued:
            self._js(code)
        self._refresh_gauges()

    def _gauge_stations(self):
        """(lon, lat) gauge pairs from the main-window Gauges box (the parent), shown
        on the map as small red numbered reference pins."""
        try:
            from src.gui.widgets.basin_viewer import _parse_coord_pairs
            mw = self.parent()
            if mw is not None and hasattr(mw, "gauges_field"):
                return _parse_coord_pairs(mw.gauges_field.text()) or []
        except Exception:
            log.debug("netcdf: reading gauges failed", exc_info=True)
        return []

    def _refresh_gauges(self):
        arr = [[lat, lon] for lon, lat in self._gauge_stations()]
        self._js("if(window.setGauges) setGauges(%s);" % json.dumps(arr))

    def _js(self, code):
        if not self._map_ready:
            self._js_queue.append(code)
            return
        try:
            self.web_view.page().runJavaScript(code)
        except Exception:
            log.debug("netcdf JS failed", exc_info=True)

    # -------------------------------------------------------------- handlers
    def _on_time_changed(self, ti):
        self._ti = int(ti)
        if self.time_labels:
            self.time_label.setText(self.time_labels[self._ti])
        self._js("if(window.updateNc) updateNc(%s);" % json.dumps(self._frame_uri(self._ti)))

    def _toggle_play(self):
        if self._play_timer.isActive():
            self._play_timer.stop()
            self.play_button.setText("▶ Play")
        else:
            self._play_timer.start(_PLAY_SPEEDS.get(self.speed_combo.currentText(), 400))
            self.play_button.setText("⏸ Pause")

    def _play_tick(self):
        n = len(self.frames)
        if n <= 1:
            return
        self.time_slider.setValue((self._ti + 1) % n)

    def _on_play_speed(self, name):
        if self._play_timer.isActive():
            self._play_timer.start(_PLAY_SPEEDS.get(name, 400))

    def _on_opacity_changed(self, value):
        # One slider fades BOTH layers as it goes 0 -> 100%:
        #   OSM basemap opacity  : 0.0 -> 1.0  (hidden -> fully visible)
        #   NetCDF overlay opacity: 1.0 -> 0.5  (fully opaque -> 50% on top)
        t = max(0.0, min(1.0, value / 100.0))
        self._base_opacity = t
        self._overlay_opacity = 1.0 - 0.5 * t
        self._js("if(window.setBaseOpacity) setBaseOpacity(%f);" % self._base_opacity)
        self._js("if(window.setNcOpacity) setNcOpacity(%f);" % self._overlay_opacity)

    def _toggle_log(self, checked):
        self._log_scale = bool(checked)
        self.log_button.setText("Linear scale" if self._log_scale else "Log scale")
        self._js("if(window.updateNc) updateNc(%s);"
                 % json.dumps(self._frame_uri(self._ti)))

    def _on_basemap_changed(self, index):
        key = self.basemap_combo.itemData(index)
        if key:
            self._basemap_key = key
            self._js("if(window.setBasemap) setBasemap(%s);" % json.dumps(key))

    def _on_colorscale(self, name):
        if name not in _COLORSCALES:
            return
        self._colorscale_name = name
        self._js("if(window.updateNc) updateNc(%s);" % json.dumps(self._frame_uri(self._ti)))
        self._js("if(window.setColorbar) setColorbar(%s,%s,%s);"
                 % (json.dumps(self._colorbar_gradient()),
                    json.dumps(self._fmt_val(self.zmax)),
                    json.dumps(self._fmt_val(self.zmin))))

    # ------------------------------------------------------------ A−B compare
    def _toggle_compare(self):
        """Load a second .nc and show (this − other) as a diverging difference map;
        or, if already comparing, restore the original view."""
        if self._compare_mode:
            self._exit_compare()
            return
        start_dir = os.path.dirname(self.nc_path)
        path, _ = QFileDialog.getOpenFileName(
            self, "Open second NetCDF (B) to subtract (this − B)", start_dir,
            "NetCDF files (*.nc)")
        if not path:
            return
        if os.path.abspath(path) == os.path.abspath(self.nc_path):
            QMessageBox.information(self, "Compare A−B", "Pick a different file for B.")
            return
        try:
            self._enter_compare(path)
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "Compare A−B", f"Could not compare:\n{e}")

    def _enter_compare(self, bpath):
        # Load B without clobbering A's point-series source (restored below).
        saved_ps = getattr(self, "_point_source", None)
        try:
            (_vB, _lonsB, _latsB, framesB, _labelsB,
             _zminB, _zmaxB, _titleB) = self._load(bpath)
        finally:
            if saved_ps is not None:
                self._point_source = saved_ps
        if not framesB:
            raise ValueError("The second file has no data.")
        if framesB[0].shape != self.frames[0].shape:
            raise ValueError(
                "The two files are on different grids (%s vs %s) — they must share the "
                "same lon/lat grid to subtract." % (self.frames[0].shape, framesB[0].shape))
        n = min(len(self.frames), len(framesB))
        if n == 0:
            raise ValueError("No overlapping timesteps.")
        diff = [self.frames[i] - framesB[i] for i in range(n)]
        vmax = 0.0
        for d in diff:
            fin = d[np.isfinite(d)]
            if fin.size:
                vmax = max(vmax, float(np.abs(fin).max()))
        if vmax == 0.0:
            vmax = 1.0
        # Save A's state so Clear compare can restore it.
        self._orig = dict(frames=self.frames, zmin=self.zmin, zmax=self.zmax,
                          cs=self._colorscale_name, log=self._log_scale,
                          labels=self.time_labels, header=self.header_label.text(),
                          ti=self._ti)
        self.frames = diff
        self.zmin, self.zmax = -vmax, vmax
        self._colorscale_name = "RdBu (diff)"
        self._log_scale = False
        self.time_labels = list(self.time_labels[:n])
        self._ti = min(self._ti, n - 1)
        self._compare_mode = True
        self._apply_data_swap(
            "Δ  %s  −  %s" % (os.path.basename(self.nc_path), os.path.basename(bpath)))
        self.compare_button.setText("Clear compare")

    def _exit_compare(self):
        o = self._orig
        self._compare_mode = False
        self._orig = None
        self.compare_button.setText("Compare A−B")
        if not o:
            return
        self.frames = o["frames"]
        self.zmin, self.zmax = o["zmin"], o["zmax"]
        self._colorscale_name = o["cs"]
        self._log_scale = o["log"]
        self.time_labels = o["labels"]
        self._ti = min(o["ti"], len(self.frames) - 1)
        self._apply_data_swap(o["header"])

    def _apply_data_swap(self, header_text):
        """Refresh the UI after frames / zmin-zmax / colour-scale change (compare toggle):
        clear the URI cache, resync the slider + colour-scale + log controls, push the
        current frame and the colour-bar."""
        self._uri_cache.clear()
        self._multi = len(self.frames) > 1
        self.time_slider.blockSignals(True)
        self.time_slider.setRange(0, max(0, len(self.frames) - 1))
        self.time_slider.setValue(self._ti)
        self.time_slider.blockSignals(False)
        self.colorscale_combo.blockSignals(True)
        self.colorscale_combo.setCurrentText(self._colorscale_name)
        self.colorscale_combo.blockSignals(False)
        self.log_button.blockSignals(True)
        self.log_button.setChecked(self._log_scale)
        self.log_button.setText("Linear scale" if self._log_scale else "Log scale")
        self.log_button.blockSignals(False)
        # Point time-series makes no sense on a difference map — disable while comparing.
        for b in (self.ts_button, self.ts_fast_button):
            b.setEnabled(self._multi and not self._compare_mode)
        self.header_label.setText(header_text)
        if self.time_labels:
            self.time_label.setText(
                self.time_labels[min(self._ti, len(self.time_labels) - 1)])
        self._js("if(window.updateNc) updateNc(%s);" % json.dumps(self._frame_uri(self._ti)))
        self._js("if(window.setColorbar) setColorbar(%s,%s,%s);"
                 % (json.dumps(self._colorbar_gradient()),
                    json.dumps(self._fmt_val(self.zmax)),
                    json.dumps(self._fmt_val(self.zmin))))

    def _on_web_title(self, title):
        if not title:
            return
        if title.startswith("NC2ERR"):
            print(f"NetCDF map error: {title[7:]}", file=sys.stderr)
            return
        if title.startswith("NC2DEL "):
            # A confirmed point pin was clicked -> remove it (map + timeseries).
            try:
                num = int(title.split()[1])
            except Exception:
                return
            self._remove_point(num - 1)
            return
        if not title.startswith("NC2 "):
            return
        try:
            lon_s, lat_s = title[4:].split("|", 1)
            lon, lat = float(lon_s), float(lat_s)
        except Exception:
            return
        # Nearest cell + its value on the current timestep.
        loni = int(np.argmin(np.abs(self.lons - lon)))
        lati = int(np.argmin(np.abs(self.lats - lat)))
        lonc, latc = float(self.lons[loni]), float(self.lats[lati])
        z = None
        try:
            val = float(self.frames[self._ti][lati, loni])
            z = val if np.isfinite(val) else None
        except Exception:
            pass
        self._clicked = (lonc, latc, z)
        self._js("if(window.setPending) setPending(%f,%f);" % (latc, lonc))
        # Coordinate/value read-out (like Show Basin's info label).
        from src.gui.utils import display_format
        vtxt = "no data" if z is None else (
            display_format.fmt(z) + (f" {self.unit}" if self.unit else ""))
        step = f" | {self.time_labels[self._ti]}" if self.time_labels else ""
        self.info_label.setText(
            f"Lon: {display_format.fmt(lonc)} | Lat: {display_format.fmt(latc)} | "
            f"Value: {vtxt}{step}")

    # ------------------------------------------------- points / timeseries
    # ``self._displayed_points`` holds the confirmed cell centres as (lon, lat)
    # tuples; each point's colour is derived from its index so the map pins match
    # the Timeseries line colours. Points PERSIST when the Timeseries window closes
    # (reopen re-plots them); clicking a pin removes that point everywhere.
    @staticmethod
    def _point_color(i):
        from .analysis_timeseries import TimeseriesWindow
        cc = TimeseriesWindow._COMPARE_COLORS
        return TimeseriesWindow._MAIN_COLOR if i == 0 else cc[(i - 1) % len(cc)]

    def _point_name(self, pt):
        from src.gui.utils import display_format
        return f"lon {display_format.fmt(pt[0])}, lat {display_format.fmt(pt[1])}"

    def _series_for(self, pt, full=True):
        loni = int(np.argmin(np.abs(self.lons - pt[0])))
        lati = int(np.argmin(np.abs(self.lats - pt[1])))
        return self._point_series(lati, loni, full=full)

    def _display_timeseries_fast(self):
        """Fast Display Timeserie: quick plot using the strided map timesteps (gaps)."""
        self._display_timeseries(full=False)

    def _display_timeseries_full(self):
        """Total Timeseries: load and plot the full series (every timestep)."""
        self._display_timeseries(full=True)

    def _display_timeseries(self, full=True):
        """Add the currently clicked cell to the persisted point set (if any) and
        (re)build the Timeseries window from all persisted points, in ``full`` mode
        (Total = every timestep, off-thread with a progress bar) or fast mode (strided
        map timesteps, read synchronously - quick, with gaps)."""
        if not self._multi:
            QMessageBox.information(self, "Timeserie",
                                    "This file has no time dimension to plot.")
            return
        if self._clicked:
            lon, lat, _z = self._clicked
            loni = int(np.argmin(np.abs(self.lons - lon)))
            lati = int(np.argmin(np.abs(self.lats - lat)))
            cell = (float(self.lons[loni]), float(self.lats[lati]))
            if cell not in self._displayed_points:
                self._displayed_points.append(cell)
        if not self._displayed_points:
            QMessageBox.information(
                self, "Timeserie",
                "Click a point on the map first, then press a Timeserie button.")
            return
        self._ts_full = full
        self._open_or_refresh_timeseries()
        self._update_map_markers()

    def _open_or_refresh_timeseries(self, open_if_closed=True):
        """(Re)build the Timeseries window from the full persisted point set. Recreated
        from scratch each time so a removal is reflected (TimeseriesWindow has no
        remove-series API). With ``open_if_closed=False`` it only refreshes an already
        open window (used when removing a point) instead of popping it open.

        In **Total** mode (`self._ts_full`) each cell's full series is read off the GUI
        thread (`_PointSeriesWorker`) with a progress bar right of the buttons, since
        reading every timestep can be slow. In **Fast** mode the strided series is read
        synchronously (quick, with gaps). The window is (re)built once the data is
        ready."""
        old = self._ts_window
        open_now = False
        if old is not None:
            try:
                open_now = old.isVisible()
            except RuntimeError:
                open_now = False
        if not open_now and not open_if_closed:
            return
        pts = list(self._displayed_points)
        if not pts:
            self._close_ts_window()
            return
        # Queue this request (pts, open_if_closed, full); the latest one wins if a read
        # is already running.
        self._ts_next = (pts, open_if_closed, self._ts_full)
        if self._ts_worker is None:
            self._run_next_ts_read()

    def _run_next_ts_read(self):
        """Serve the latest pending request: Fast = synchronous strided read; Total =
        background full read with a progress bar."""
        if self._ts_next is None:
            return
        pts, open_if_closed, full = self._ts_next
        self._ts_next = None
        if not pts:
            self._close_ts_window()
            return
        if not full:
            # Fast: strided series (few points), read synchronously - quick, "like before".
            try:
                series = [self._series_for(p, full=False) for p in pts]
            except Exception as e:
                self._on_ts_failed(str(e))
                return
            self._build_ts_window(series, pts, open_if_closed, full=False)
            if self._ts_next is not None:   # a newer request queued meanwhile
                self._run_next_ts_read()
            return
        # Total: full-resolution read off the GUI thread, with the progress bar.
        if len(pts) <= 1:
            self.ts_progress.setRange(0, 0)   # busy/indeterminate for a single point
            self.ts_progress.setFormat("loading…")
        else:
            self.ts_progress.setRange(0, len(pts))
            self.ts_progress.setValue(0)
            self.ts_progress.setFormat("loading %v/%m")
        self.ts_progress.setVisible(True)
        self.ts_button.setEnabled(False)
        self.ts_fast_button.setEnabled(False)
        worker = _PointSeriesWorker(self, pts, full=True, parent=self)
        self._ts_worker = worker
        worker.progress.connect(self._on_ts_progress)
        worker.finished_ok.connect(
            lambda series, p=pts, o=open_if_closed:
            self._build_ts_window(series, p, o, full=True))
        worker.failed.connect(self._on_ts_failed)
        worker.finished.connect(self._on_ts_worker_finished)
        worker.start()

    def _on_ts_progress(self, done, total):
        if total <= 1:
            return  # single point stays indeterminate (busy)
        try:
            self.ts_progress.setRange(0, total)
            self.ts_progress.setValue(done)
        except RuntimeError:
            pass

    def _on_ts_failed(self, msg):
        try:
            QMessageBox.warning(self, "Display timeserie",
                                f"Could not read the time series:\n{msg}")
        except RuntimeError:
            pass

    def _on_ts_worker_finished(self):
        """Reader thread finished: hide the bar, re-enable the buttons, chain the next
        request if a newer one arrived while reading."""
        self._ts_worker = None
        try:
            self.ts_progress.setVisible(False)
            self.ts_button.setEnabled(True)
            self.ts_fast_button.setEnabled(True)
        except RuntimeError:
            pass
        if self._ts_next is not None:
            self._run_next_ts_read()

    def _close_ts_window(self):
        """Close and forget the current Timeseries window (e.g. no points left)."""
        old = self._ts_window
        self._ts_window = None
        if old is not None:
            try:
                old.finished.disconnect(self._on_ts_closed)
            except Exception:
                pass
            try:
                old.close()
            except Exception:
                pass

    def _build_ts_window(self, series_list, pts, open_if_closed, full=True):
        """(Re)build the Timeseries window from the precomputed series (main thread).
        Dates match the mode: full-resolution (every timestep) for Total, the strided
        map timesteps (`time_labels`) for Fast."""
        from .analysis_timeseries import TimeseriesWindow
        old = self._ts_window
        open_now = False
        if old is not None:
            try:
                open_now = old.isVisible()
            except RuntimeError:
                open_now = False
        if not open_now and not open_if_closed:
            return
        if not pts or not series_list:
            return
        self._close_ts_window()
        dates = (self._point_source.get("full_time_labels") if full
                 else self.time_labels) or self.time_labels
        first = pts[0]
        win = TimeseriesWindow.from_point(
            dates, series_list[0], self._point_name(first), self.varname,
            self.settings_title, first[0], first[1], parent=self)
        win.setModal(False)
        if not getattr(win, "_geometry_was_restored", False):
            win.resize(740, 520)
            _position_offset(win, 0.18)
        for p, series in zip(pts[1:], series_list[1:]):
            win.add_point_series(dates, series, self._point_name(p))
        win.finished.connect(self._on_ts_closed)
        self._ts_window = win
        win.show()
        win.raise_()
        win.activateWindow()

    def _on_ts_closed(self, *args):
        """Timeseries window closed: forget the window but KEEP the points/markers
        on the map (persist across open/close)."""
        self._ts_window = None

    def _remove_point(self, idx):
        """Remove a confirmed point (clicked pin) from the map and the Timeseries."""
        if idx < 0 or idx >= len(self._displayed_points):
            return
        del self._displayed_points[idx]
        self._update_map_markers()
        self._open_or_refresh_timeseries(open_if_closed=False)

    def _update_map_markers(self):
        """Redraw the confirmed points as NUMBERED pin icons (colour = Timeseries line
        colour, by index) and clear the pending red marker."""
        arr = [[p[1], p[0], self._point_color(i), str(i + 1)]   # [lat, lon, colour, num]
               for i, p in enumerate(self._displayed_points)]
        self._js("if(window.setPoints) setPoints(%s);" % json.dumps(arr))
        self._js("if(window.clearPending) clearPending();")

    def _save_html(self):
        if not getattr(self, "_page_html", None):
            QMessageBox.information(self, "Save HTML", "Nothing to save yet.")
            return
        from .analysis_timeseries import resolved_pathout_dir
        base = os.path.splitext(os.path.basename(self.nc_path))[0] + "_map.html"
        default = os.path.join(resolved_pathout_dir(self), base)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save map as HTML", default, "HTML files (*.html)")
        if not path:
            return
        try:
            # Note: the saved page's basemap tiles/WMS resolve through the app's
            # osmtile:// scheme, so an external browser shows the data overlay only.
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._page_html)
        except Exception as e:
            QMessageBox.warning(self, "Save HTML", f"Could not save the file:\n{e}")

    def closeEvent(self, event):
        try:
            self._play_timer.stop()
        except Exception:
            pass
        # Let a running point-series read finish so its QThread is not destroyed while
        # active (it only reads files + emits signals, so this is a short wait).
        worker = getattr(self, "_ts_worker", None)
        if worker is not None:
            self._ts_next = None
            try:
                worker.finished_ok.disconnect()
                worker.progress.disconnect()
            except Exception:
                pass
            try:
                worker.wait(4000)
            except Exception:
                pass
        try:
            if self._temp_html and os.path.exists(self._temp_html):
                os.remove(self._temp_html)
        except Exception:
            pass
        super().closeEvent(event)
