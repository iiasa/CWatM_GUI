"""
NetCDF analysis widget (Analyse ▸ NetCDF) - the NetCDF viewer on a **folium**
(Leaflet, EPSG:4326) map with an OpenStreetMap background.

Draws the variable as a Leaflet **ImageOverlay** over an OSM **WMS** basemap
(EPSG:4326, like Show Basin), with a timestep slider + Play, Speed and Log-scale
toggle inline; File (Save HTML / Load JSON / Load shape) and Action (Fast Display
Timeserie / Total Timeseries / Compare A-B / Flow duration / Flow regime / Calculate
mean / Calculate percentile - the last two write a new one-map NetCDF via
``netcdf_stats`` and show it in place of the original, ``_show_file``) menus; and
a top-level Display action that opens a small window (colour-scale selector,
OSM-transparency slider, basemap selector). Load JSON/Load shape are the same
feature as Show Basin's (shared readers + shared window.addGeoJson JS helper from
``basin_viewer2.py``) - draws a GeoJSON or ESRI shapefile overlay on the map. A left
click on the map (or on a gauge pin) **toggles** that cell: a new cell is added to
the selected points (a numbered pin), a selected one - or its pin - is removed
again; the newest selection is also self._clicked. Right-clicking anywhere on the map then opens every
Action-menu item at the cursor (same label/tooltip, mirrored off the real
QActions) - Qt-native (customContextMenuRequested), not the page's own
'contextmenu' DOM event, which raced unreliably with QWebEngineView's native
Back/Forward/Reload menu. Fast/Total Timeserie, Flow duration and Flow regime all
work off the selection - the Timeseries items plot every selected point, Flow
duration/regime only ever the most recent one, each plotting every
calendar year as its own curve plus the multi-year average in black at double
width.

The data-reading, meta lookup and per-cell time-series re-read are **reused from
``NetcdfDataBase``** (in ``analysis_netcdf_base.py``; this class subclasses it); only
the rendering/interaction is implemented here. The selected points are drawn as
**numbered pin icons coloured to match their line** in the Timeseries window.
"""

import os
import sys
import json
import time
import base64
import tempfile
from collections import OrderedDict

import numpy as np

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QSlider, QFileDialog, QMessageBox, QProgressBar, QMenuBar,
)
from PySide6.QtCore import Qt, QUrl, QTimer, QThread, Signal
from PySide6.QtGui import QIcon, QImage
from PySide6.QtCore import QByteArray, QBuffer

from src.gui.utils import theme
from src.gui.utils.gui_log import get_logger
from src.gui.utils.window_geometry import scaled_default_size

log = get_logger("analysis_netcdf")

# Upper bound on the rendered-frame data-URI cache (report §5.2). Each entry is a
# base64 PNG of one timestep (~30-100 KB), so an unbounded cache grows by a full
# frame set per colour-scale / log-toggle combination the user plays through.
_URI_CACHE_MAX = 64

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
    _read_geojson_file, _read_shapefile,
)
from src.gui.widgets.basin_viewer import grid_is_latlon


class _PointSeriesWorker(QThread):
    """Read the full-resolution time series of each requested cell off the GUI thread.

    Reading every timestep for a cell can be slow on a large / networked file, so it
    runs here and reports per-point progress. ``_series_for``/``_point_series`` share
    one dataset handle across calls (``NetcdfDataBase._shared_point_dataset``) and
    cache each cell's result, so several of these workers (Total Timeseries, Flow
    duration, Flow regime) reading concurrently, or re-reading a point another one
    already read, is safe and cheap."""

    progress = Signal(int, int)     # points done, total
    finished_ok = Signal(list)      # [ [values...], ... ] one entry per point
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, reader, points, full=True, parent=None):
        super().__init__(parent)
        self._reader = reader       # the NetcdfWindow (uses _series_for)
        self._points = list(points)
        self._full = full
        self._stop = False

    def request_stop(self):
        """Cooperative cancel, checked between points. A read already in flight for
        one point still has to finish - the underlying netCDF4/HDF5/dask call can't
        be safely interrupted mid-I/O without risking the shared dataset handle other
        reads reuse (QThread.terminate() is deliberately never used here)."""
        self._stop = True

    def run(self):
        try:
            out = []
            n = len(self._points)
            for i, p in enumerate(self._points):
                if self._stop:
                    self.cancelled.emit()
                    return
                out.append(self._reader._series_for(p, full=self._full))
                self.progress.emit(i + 1, n)
            self.finished_ok.emit(out)
        except Exception as e:  # pragma: no cover - defensive
            self.failed.emit(str(e))


_DETACHED_WORKERS = []    # statistic workers whose window closed while they ran


class _StatisticWorker(QThread):
    """Calculate mean / Calculate percentile off the GUI thread: reads the whole
    variable once, so on a large file it takes a while (netcdf_stats does the work)."""

    done = Signal(str)          # the written file
    failed = Signal(str)

    def __init__(self, kwargs, parent=None):
        super().__init__(parent)
        self._kwargs = kwargs

    def run(self):
        try:
            from src.gui.utils.netcdf_stats import compute_statistic
            self.done.emit(compute_statistic(**self._kwargs))
        except Exception as e:
            log.warning("NetCDF statistic failed", exc_info=True)
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
        # Parenting transfers ownership to the C++ parent, so the dialog would
        # outlive exec() and keep its frame list + _uri_cache + QWebEngine page
        # alive until the main window closes (report §5.3).
        win.setAttribute(Qt.WA_DeleteOnClose)
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
        # Projected (non lat/lon) grid, e.g. Norway UTM33 with x/y coordinates:
        # no OSM basemap (its tiles are lon/lat), map runs in Leaflet CRS.Simple
        # on the raw x/y, data shown fully opaque on white.
        self._projected = not grid_is_latlon(self.lats, self.lons)
        if self._projected:
            self._base_opacity = 0.0
            self._overlay_opacity = 1.0
        self._log_scale = True                # logarithmic colour mapping (default)
        self._basemap_key = _B2_DEFAULT_LAYER
        self._lut_cache = {}                  # colorscale name -> (256,3) uint8
        # (colorscale, log, ti) -> data URI, LRU-bounded to _URI_CACHE_MAX entries
        self._uri_cache = OrderedDict()
        self._map_ready = False
        self._js_queue = []
        self._temp_html = None
        # lon orientation for the ImageOverlay (data columns must run west->east)
        self._lon_ascending = bool(self.lons[0] <= self.lons[-1])

        self.setWindowTitle(f"\U0001F5FA NetCDF: {os.path.basename(nc_path)}")
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        if not self._init_geometry_memory("netcdf"):
            self.resize(*scaled_default_size(self, 1000, 780))
            _position_offset(self, -0.15)
        try:
            icon_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                'assets', 'cwatm.ico')
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            log.debug("__init__: ignored", exc_info=True)

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
        if uri is not None:
            self._uri_cache.move_to_end(key)   # mark as most recently used
            return uri
        uri = self._rgba_to_datauri(self._colorize(ti))
        self._uri_cache[key] = uri
        while len(self._uri_cache) > _URI_CACHE_MAX:
            self._uri_cache.popitem(last=False)   # evict the least recently used
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
        self._build_menubar(layout)

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
        # Custom, Qt-driven right-click: QWebEngineView's own native context menu
        # (Back/Forward/Reload) would otherwise show regardless of what the page's JS
        # does. CustomContextMenu hands the click position straight to Qt (no
        # dependency on the page's 'contextmenu' DOM event or preventDefault, which
        # proved unreliable here); _on_web_context_menu asks the page (JS hit-test)
        # whether a gauge sits under that pixel.
        self.web_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.web_view.customContextMenuRequested.connect(self._on_web_context_menu)
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
        self.speed_label = speed_label
        row1.addWidget(speed_label)
        self.speed_combo = QComboBox()
        for name in _PLAY_SPEEDS:
            self.speed_combo.addItem(name)
        self.speed_combo.setCurrentText(_DEFAULT_PLAY_SPEED)
        self.speed_combo.currentTextChanged.connect(self._on_play_speed)
        self.speed_combo.setVisible(self._multi)
        row1.addWidget(self.speed_combo)

        self.log_button = QPushButton("Log scale")
        self.log_button.setStyleSheet(_btn)
        self.log_button.setCheckable(True)
        self.log_button.setToolTip("Map the values to colour on a logarithmic scale")
        # Log scale is the default: reflect it in the button (checked + "Linear
        # scale" label) before connecting the toggle, so no premature update fires.
        self.log_button.setChecked(self._log_scale)
        self.log_button.setText("Linear scale" if self._log_scale else "Log scale")
        self.log_button.toggled.connect(self._toggle_log)
        row1.addWidget(self.log_button)

        # Progress bar: the full-resolution point series (Total Timeseries / Flow
        # duration / Flow regime) can take a while to read on a big file, so show
        # per-point progress while it loads, an elapsed-time readout (there is no
        # honest per-byte ETA to give for a single point), and a way to cancel.
        self.ts_progress = QProgressBar()
        self.ts_progress.setTextVisible(True)
        self.ts_progress.setFixedWidth(180)
        self.ts_progress.setVisible(False)
        self.ts_progress.setStyleSheet(
            f"QProgressBar {{ border: 1px solid {theme.c('border')}; border-radius: 4px; "
            f"background: {theme.c('out_bg')}; color: {theme.c('text')}; "
            "text-align: center; height: 18px; }"
            "QProgressBar::chunk { background: #3498db; border-radius: 3px; }")
        row1.addWidget(self.ts_progress)

        self.ts_elapsed_label = QLabel("")
        self.ts_elapsed_label.setStyleSheet(_lbl)
        self.ts_elapsed_label.setVisible(False)
        row1.addWidget(self.ts_elapsed_label)

        self.ts_cancel_button = QPushButton("Cancel")
        self.ts_cancel_button.setStyleSheet(_btn)
        self.ts_cancel_button.setToolTip(
            "Stop the running read (takes effect once the point in progress finishes)")
        self.ts_cancel_button.setVisible(False)
        self.ts_cancel_button.clicked.connect(self._cancel_point_series_read)
        row1.addWidget(self.ts_cancel_button)
        layout.addLayout(row1)

        self._ts_elapsed_timer = QTimer(self)
        self._ts_elapsed_timer.setInterval(1000)
        self._ts_elapsed_timer.timeout.connect(self._update_ts_elapsed_label)

        # Colour scale / OSM transparency / Basemap - live map-appearance controls,
        # moved out of the button row into their own Display window (Menu ▸ Display)
        # so this row stays uncluttered; not added to `layout`.
        self.colorscale_combo = QComboBox()
        for name in _COLORSCALES:
            self.colorscale_combo.addItem(name)
        self.colorscale_combo.setCurrentText(_DEFAULT_COLORSCALE)
        self.colorscale_combo.currentTextChanged.connect(self._on_colorscale)

        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setToolTip(
            "0% = OSM hidden + NetCDF fully opaque (only the NetCDF, on white); "
            "100% = OSM fully visible + NetCDF 50% opaque on top")
        self.opacity_slider.setValue(int(self._base_opacity * 100))
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)

        self.basemap_combo = QComboBox()
        for label, key in _B2_PROVIDERS:
            self.basemap_combo.addItem(label, key)
        _i = self.basemap_combo.findData(self._basemap_key)
        if _i >= 0:
            self.basemap_combo.setCurrentIndex(_i)
        self.basemap_combo.currentIndexChanged.connect(self._on_basemap_changed)
        if self._projected:
            # Projected (non lat/lon) grid: there is no OSM basemap to select/fade.
            note = ("No OpenStreetMap basemap: the grid uses projected x/y "
                    "coordinates (not lat/lon)")
            self.basemap_combo.setEnabled(False)
            self.basemap_combo.setToolTip(note)
            self.opacity_slider.setEnabled(False)
            self.opacity_slider.setToolTip(note)
        self._build_display_dialog(_lbl)

    def _build_menubar(self, layout):
        """File (Save HTML) and Action (Fast Display Timeserie / Total Timeseries /
        Compare A-B) menus, plus a top-level Display action (not a dropdown - opens
        the appearance-settings window directly, like the main window's CWatM AI)."""
        mbar = QMenuBar(self)
        mbar.setStyleSheet(
            f"QMenuBar {{ background-color: {theme.c('menubar_bg')}; "
            f"color: {theme.c('text')}; }}"
            f"QMenuBar::item:selected {{ background-color: {theme.c('menu_sel_bg')}; }}")

        file_menu = mbar.addMenu("File")
        act_load_nc = file_menu.addAction("Load netcdf", self._load_netcdf)
        act_load_nc.setToolTip(
            "Load another NetCDF file (from the folder of this one) and show it here")
        act_save_html = file_menu.addAction("Save HTML", self._save_html)
        act_save_html.setToolTip(
            "Save the map as a self-contained HTML file (opens in any browser)")
        act_load_json = file_menu.addAction("Load JSON", self._load_json)
        act_load_json.setToolTip("Load a GeoJSON file and display it on the map")
        act_load_shape = file_menu.addAction("Load shape", self._load_shape)
        act_load_shape.setToolTip("Load shapefile .shp")

        action_menu = mbar.addMenu("Action")
        self.ts_fast_action = action_menu.addAction(
            "Fast Display Timeserie", self._display_timeseries_fast)
        self.ts_fast_action.setToolTip(
            "Plot the selected points quickly using the map's timesteps but has gaps")
        self.ts_fast_action.setVisible(self._multi)
        self.ts_action = action_menu.addAction(
            "Total Timeseries", self._display_timeseries_full)
        self.ts_action.setToolTip(
            "Load and plot the full timeseries (every timestep). Can take some time")
        self.ts_action.setVisible(self._multi)
        self.compare_action = action_menu.addAction("Compare A−B", self._toggle_compare)
        self.compare_action.setToolTip(
            "Load a second netcdf and shows the differences")
        self.flowdur_action = action_menu.addAction("Flow duration", self._show_flow_duration)
        self.flowdur_action.setToolTip("Displays a flow duration curve")
        self.flowdur_action.setVisible(self._multi)
        self.flowregime_action = action_menu.addAction("Flow regime", self._show_flow_regime)
        self.flowregime_action.setToolTip("Displays a flow regime curve")
        self.flowregime_action.setVisible(self._multi)
        action_menu.addSeparator()
        self.mean_action = action_menu.addAction("Calculate mean", self._calculate_mean)
        self.mean_action.setToolTip("Calculates the mean of the given netcdf")
        self.mean_action.setVisible(self._multi)
        self.percentile_action = action_menu.addAction(
            "Calculate percentile", self._calculate_percentile)
        self.percentile_action.setToolTip(
            "Select a percentile and it calculates this percentile from the given netcdf")
        self.percentile_action.setVisible(self._multi)

        # "Display" - a clickable menu-bar button (a top-level QAction fires on click
        # instead of opening a dropdown), same pattern as the main window's CWatM AI.
        self._display_action = mbar.addAction("Display")
        self._display_action.setToolTip(
            "Colour scale, OSM transparency and Basemap for this map")
        self._display_action.triggered.connect(self._open_display_dialog)

        self._menus = [file_menu, action_menu]  # GC guard
        layout.setMenuBar(mbar)

    def _build_display_dialog(self, lbl_style):
        """Menu ▸ Display: a small non-modal window (like Preferences) holding the
        map-appearance controls - Colour scale, OSM transparency, Basemap - built
        once here and reopened by _open_display_dialog. The controls apply live to
        the map, same as when they were inline."""
        win = QDialog(self)
        win.setWindowTitle("Display")
        win.setModal(False)
        win.setStyleSheet(f"QDialog {{ background-color: {theme.c('window_bg')}; }}")
        vlayout = QVBoxLayout(win)
        vlayout.setContentsMargins(16, 16, 16, 16)
        vlayout.setSpacing(10)

        cs = QLabel("Colour scale:")
        cs.setStyleSheet(lbl_style)
        vlayout.addWidget(cs)
        vlayout.addWidget(self.colorscale_combo)

        tl = QLabel("OSM transparency:")
        tl.setStyleSheet(lbl_style)
        vlayout.addWidget(tl)
        vlayout.addWidget(self.opacity_slider)

        bl = QLabel("Basemap:")
        bl.setStyleSheet(lbl_style)
        vlayout.addWidget(bl)
        vlayout.addWidget(self.basemap_combo)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(win.close)
        vlayout.addStretch(1)
        vlayout.addWidget(close_btn, alignment=Qt.AlignRight)

        win.resize(*scaled_default_size(win, 320, 260))
        self._display_window = win

    def _open_display_dialog(self):
        win = getattr(self, "_display_window", None)
        if win is None:
            return
        try:
            win.show()
            win.raise_()
            win.activateWindow()
        except RuntimeError:
            log.debug("_open_display_dialog: ignored", exc_info=True)

    # -------------------------------------------------------------- map build
    def _show_map(self):
        # built again when File > Load netcdf brings another grid: connect the load
        # handler only once
        first_build = not getattr(self, "_load_handler_connected", False)
        self._load_handler_connected = True
        west, east, south, north = self._grid_bounds()
        bounds = [[south, west], [north, east]]
        # Projected grid: Leaflet CRS.Simple treats "lat/lng" as raw y/x, so the
        # overlay/markers/clicks all keep working on e.g. UTM coordinates; the
        # (lon/lat-only) OSM basemap is skipped entirely (see _helper_js).
        crs = "Simple" if self._projected else "EPSG4326"
        m = folium.Map(location=[(south + north) / 2.0, (west + east) / 2.0],
                       zoom_start=8, crs=crs, tiles=None,
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
                log.debug("_show_map: ignored", exc_info=True)
            profile.installUrlSchemeHandler(b"osmtile", self._tile_handler)
            if first_build:
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
            if first_build:
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
          var MAP=__MAP__; var PROJ=__PROJ__;
          window._map=MAP; window._ov=__OV__;
          window._bounds=__BOUNDS__; window._op=__OP__; window._tile=null;
          window._baseOp=__BASEOP__;
          if(PROJ){ // CRS.Simple: UTM extents need strongly negative zooms
            MAP.setMinZoom(-30); MAP.options.zoomSnap=0.25; }
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
               .bindTooltip('Gauge '+(i+1)+' (click to select)')
               .on('click',function(ev){L.DomEvent.stopPropagation(ev);
                 document.title='NC2 '+g[1]+'|'+g[0]+'|'+Date.now();});
            });};
          window.setBasemap=function(layer){
            if(PROJ)return; // projected x/y grid: no lon/lat basemap
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
            }catch(e){document.title='NC2ERR geojson '+e;}};
          // the trailing timestamp makes every click a new title, so clicking the
          // same place twice (select, then deselect) fires titleChanged both times
          MAP.on('click',function(e){
            document.title='NC2 '+e.latlng.lng+'|'+e.latlng.lat+'|'+Date.now();});
          window.onerror=function(m){document.title='NC2ERR '+m;return false;};
          window.setBasemap(__BASEKEY__);
          setTimeout(function(){MAP.invalidateSize();MAP.fitBounds(window._bounds);
            if(window._tile&&window._tile.bringToBack)window._tile.bringToBack();},300);
        })();
        """
        return (tpl.replace("__MAP__", map_var)
                   .replace("__PROJ__", "true" if self._projected else "false")
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
        # Save A's *view* state so Clear compare can restore it. Deliberately NOT
        # A's frames: keeping them here meant two full frame lists were live at once
        # for the whole compare session (400 grids each - GBs on a large grid,
        # report §5.1). Clear compare re-reads A from disk instead, trading one
        # file read on a rare action for half the memory.
        self._orig = dict(zmin=self.zmin, zmax=self.zmax,
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
        self.compare_action.setText("Clear compare")

    def _exit_compare(self):
        o = self._orig
        self._compare_mode = False
        self._orig = None
        self.compare_action.setText("Compare A−B")
        if not o:
            return
        # Re-read A from disk rather than holding a second frame list alive for the
        # whole compare session (report §5.1). _load also restores A's _point_source,
        # which _enter_compare had to save/restore explicitly.
        try:
            (_v, _lons, _lats, frames, labels,
             zmin, zmax, _title) = self._load(self.nc_path)
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "Clear compare",
                                f"Could not re-read the original file:\n{e}")
            return
        self.frames = frames
        self.zmin, self.zmax = zmin, zmax
        self.time_labels = labels
        self._colorscale_name = o["cs"]
        self._log_scale = o["log"]
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
        for a in (self.ts_action, self.ts_fast_action, self.flowdur_action,
                 self.flowregime_action, self.mean_action, self.percentile_action):
            a.setEnabled(self._multi and not self._compare_mode)
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
            # "NC2 lon|lat|stamp" (map click or gauge pin click)
            lon_s, lat_s = title[4:].split("|")[:2]
            lon, lat = float(lon_s), float(lat_s)
        except Exception:
            return
        self._toggle_point(lon, lat)

    def _cell_of(self, lon, lat):
        """(lon, lat) snapped to the nearest cell centre, plus its (lati, loni)."""
        loni = int(np.argmin(np.abs(self.lons - lon)))
        lati = int(np.argmin(np.abs(self.lats - lat)))
        return (float(self.lons[loni]), float(self.lats[lati])), lati, loni

    def _toggle_point(self, lon, lat):
        """A left click on the map (or on a gauge pin): select that cell - a new
        numbered pin, added to the points every Timeseries action plots - or, when
        the cell is already selected, deselect it. An open Timeseries window follows
        at once."""
        cell, _lati, _loni = self._cell_of(lon, lat)
        if cell in self._displayed_points:
            self._remove_point(self._displayed_points.index(cell))
            self._show_cell_info(cell, prefix="Removed point - ", value=False)
            return
        self._displayed_points.append(cell)
        self._mark_clicked_cell(*cell)
        self._update_map_markers()
        self._open_or_refresh_timeseries(open_if_closed=False)

    def _mark_clicked_cell(self, lon, lat, prefix=""):
        """Remember (lon, lat)'s cell as the most recently selected point
        (self._clicked - what Flow duration / Flow regime use) and update the info
        label."""
        cell, lati, loni = self._cell_of(lon, lat)
        z = None
        try:
            val = float(self.frames[self._ti][lati, loni])
            z = val if np.isfinite(val) else None
        except Exception:
            log.debug("_mark_clicked_cell: ignored", exc_info=True)
        self._clicked = (cell[0], cell[1], z)
        self._show_cell_info(cell, z, prefix)

    def _show_cell_info(self, cell, z=None, prefix="", value=True):
        lonc, latc = cell
        # Coordinate/value read-out (like Show Basin's info label).
        from src.gui.utils import display_format
        xl, yl = ("X", "Y") if self._projected else ("Lon", "Lat")
        text = (f"{prefix}{xl}: {display_format.fmt(lonc)} | "
                f"{yl}: {display_format.fmt(latc)}")
        if value:
            vtxt = "no data" if z is None else (
                display_format.fmt(z) + (f" {self.unit}" if self.unit else ""))
            step = f" | {self.time_labels[self._ti]}" if self.time_labels else ""
            text += f" | Value: {vtxt}{step}"
        self.info_label.setText(text)

    def _on_web_context_menu(self, pos):
        """Right-click anywhere on the map - Qt-native (customContextMenuRequested,
        see _build_ui), not the page's own 'contextmenu' DOM event, which raced with
        QWebEngineView's native Back/Forward/Reload menu unreliably. Opens every
        Action-menu item at the cursor; no hit-testing needed (and no dependency on
        gauges existing at all) since every item already works off whatever point
        was selected last (self._clicked) or, for the Timeseries items, every
        selected point."""
        global_pos = self.web_view.mapToGlobal(pos)
        self._open_map_action_menu(global_pos)

    def _open_map_action_menu(self, global_pos):
        """The right-click context menu - literally every item of Menu ▸ Action,
        same label/tooltip/enabled state AND the exact same behaviour (mirrored off
        the real QActions, so the two can never drift out of sync)."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)

        def _mirror(source_action, slot):
            act = menu.addAction(source_action.text(), slot)
            act.setToolTip(source_action.toolTip())
            act.setEnabled(source_action.isEnabled())

        _mirror(self.ts_fast_action, self._display_timeseries_fast)
        _mirror(self.ts_action, self._display_timeseries_full)
        _mirror(self.compare_action, self._toggle_compare)
        _mirror(self.flowdur_action, self._show_flow_duration)
        _mirror(self.flowregime_action, self._show_flow_regime)
        if self.mean_action.isVisible():
            menu.addSeparator()
            _mirror(self.mean_action, self._calculate_mean)
            _mirror(self.percentile_action, self._calculate_percentile)
        menu.exec(global_pos)

    # ------------------------------------------------ mean / percentile over time
    def _calculate_mean(self):
        """Action ▸ Calculate mean: the time mean of the variable -> a new NetCDF
        (``<var>_mean.nc`` next to the original), then shown instead of the original."""
        self._calculate_statistic("mean")

    def _calculate_percentile(self):
        """Action ▸ Calculate percentile: ask for the percentile, then as the mean
        (``<var>_<p>_percentile.nc``)."""
        from PySide6.QtWidgets import QInputDialog
        p, ok = QInputDialog.getDouble(
            self, "Calculate percentile",
            "Percentile (0 - 100), e.g. 50 for the 50% percentile (median):",
            50.0, 0.0, 100.0, 1)
        if ok:
            self._calculate_statistic("percentile", p)

    def _calculate_statistic(self, statistic, percentile=None):
        from src.gui.utils import netcdf_stats
        if getattr(self, "_stat_worker", None) is not None:
            QMessageBox.information(self, "NetCDF", "A calculation is already running.")
            return
        src = self._point_source
        name = netcdf_stats.default_name(self.varname, statistic, percentile)
        title = "Save mean as NetCDF" if statistic == "mean" else \
            "Save percentile as NetCDF"
        out, _ = QFileDialog.getSaveFileName(
            self, title, os.path.join(os.path.dirname(os.path.abspath(self.nc_path)), name),
            "NetCDF files (*.nc)")
        if not out:
            return
        if not out.lower().endswith(".nc"):
            out += ".nc"
        if os.path.abspath(out) == os.path.abspath(self.nc_path):
            QMessageBox.warning(self, "NetCDF",
                                "Choose another name - the original file is kept.")
            return
        worker = _StatisticWorker(dict(
            src_path=self.nc_path, out_path=out, varname=src["varname"],
            lat_name=src["lat_name"], lon_name=src["lon_name"],
            time_name=src["time_name"], extra_sel=src["extra_sel"],
            statistic=statistic, percentile=percentile), parent=self)
        self._stat_worker = worker
        worker.done.connect(self._on_statistic_done)
        worker.failed.connect(self._on_statistic_failed)
        worker.finished.connect(self._on_statistic_finished)
        self._start_point_series_read_ui(indeterminate=True)
        self.ts_progress.setFormat("calculating…")
        self.ts_cancel_button.setVisible(False)     # one read, cannot be interrupted
        self.mean_action.setEnabled(False)
        self.percentile_action.setEnabled(False)
        worker.start()

    def _on_statistic_done(self, path):
        try:
            self._show_file(path)
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "NetCDF",
                                f"Saved {path}\nbut it could not be displayed:\n{e}")

    def _on_statistic_failed(self, msg):
        QMessageBox.warning(self, "NetCDF", f"The calculation failed:\n{msg}")

    def _on_statistic_finished(self):
        self._stat_worker = None
        try:
            self._stop_point_series_read_ui()
            self.mean_action.setEnabled(self._multi and not self._compare_mode)
            self.percentile_action.setEnabled(self._multi and not self._compare_mode)
        except RuntimeError:
            log.debug("_on_statistic_finished: window gone", exc_info=True)

    def _load_netcdf(self):
        """File ▸ Load netcdf: pick another .nc (starting in this file's folder) and
        show it in this window instead of the current one."""
        start_dir = os.path.dirname(os.path.abspath(self.nc_path))
        path, _ = QFileDialog.getOpenFileName(
            self, "Load NetCDF file", start_dir, "NetCDF files (*.nc)")
        if not path:
            return
        try:
            self._show_file(path)
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "Load netcdf", f"Could not open the file:\n{e}")

    def _show_file(self, path):
        """Show ``path`` in this window instead of the current file - a calculated
        mean/percentile map, or any file picked with File ▸ Load netcdf. The selected
        points go; the time controls follow the new file. A file on another grid
        rebuilds the map page."""
        if self._compare_mode:
            self._exit_compare()
        self._play_timer.stop()
        (varname, lons, lats, frames, labels,
         zmin, zmax, title) = self._load(path)
        same_grid = (lons.shape == self.lons.shape and lats.shape == self.lats.shape
                     and np.allclose(lons, self.lons) and np.allclose(lats, self.lats))
        self.nc_path = path
        self.varname = varname
        self.settings_title = title
        self.lons, self.lats = lons, lats
        self.frames, self.time_labels = frames, labels
        self.zmin, self.zmax = zmin, zmax
        self.unit, self.long_name, self.description = self._lookup_meta(varname)
        self._ti = 0
        self._displayed_points = []
        self._clicked = None
        self._update_map_markers()
        self._close_ts_window()
        multi = len(frames) > 1
        for w in (self.play_button, self.time_slider, self.time_label,
                  self.speed_label, self.speed_combo):
            w.setVisible(multi)
        for a in (self.ts_fast_action, self.ts_action, self.flowdur_action,
                  self.flowregime_action, self.mean_action, self.percentile_action):
            a.setVisible(multi)
        head = os.path.basename(path)
        if self.settings_title:
            head += f"   —   {self.settings_title}"
        self.setWindowTitle(f"\U0001F5FA NetCDF: {os.path.basename(path)}")
        if not same_grid:
            self._rebuild_for_new_grid()
        self._apply_data_swap(head)
        self.info_label.setText(f"Shown: {path}")

    def _rebuild_for_new_grid(self):
        """The file just loaded lies on another grid: redo the grid-dependent state
        of __init__ (projected or lon/lat, lon orientation, basemap controls) and
        build the map page again (its bounds are baked into the page)."""
        from src.gui.utils import display_format as _df
        self._projected = not grid_is_latlon(self.lats, self.lons)
        self._lon_ascending = bool(self.lons[0] <= self.lons[-1])
        if self._projected:
            self._base_opacity, self._overlay_opacity = 0.0, 1.0
        else:
            t = self.opacity_slider.value() / 100.0 if self.opacity_slider.isEnabled() \
                else max(0.0, min(1.0, _df.get_transparency() / 100.0))
            self._base_opacity, self._overlay_opacity = t, 1.0 - 0.5 * t
        self.basemap_combo.setEnabled(not self._projected)
        self.opacity_slider.setEnabled(not self._projected)
        self._uri_cache.clear()
        self._map_ready = False
        self._js_queue = []
        self._show_map()

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
        xl, yl = ("x", "y") if self._projected else ("lon", "lat")
        return f"{xl} {display_format.fmt(pt[0])}, {yl} {display_format.fmt(pt[1])}"

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
        """(Re)build the Timeseries window from every selected point (the numbered
        pins - a left click selects/deselects them, see _toggle_point), in ``full``
        mode (Total = every timestep, off-thread with a progress bar) or fast mode
        (strided map timesteps, read synchronously - quick, with gaps)."""
        if not self._multi:
            QMessageBox.information(self, "Timeserie",
                                    "This file has no time dimension to plot.")
            return
        if not self._displayed_points:
            QMessageBox.information(
                self, "Timeserie",
                "Click one or more points on the map first, then press a Timeserie "
                "button.")
            return
        self._ts_full = full
        self._open_or_refresh_timeseries()
        self._update_map_markers()

    # --------------------------------------------------------- flow duration
    def _show_flow_duration(self):
        """Action ▸ Flow duration, and the gauge right-click menu's Flow duration:
        like Total Timeseries, works off the point that was last clicked on the map
        (self._clicked) - unlike Total Timeseries, which plots every persisted point,
        this only ever looks at the most recent click, never accumulating. Reads the
        FULL-resolution series off the GUI thread (same worker as Total Timeseries)
        and plots one flow duration curve per year, plus the all-years average."""
        if not self._multi:
            QMessageBox.information(self, "Flow duration",
                                    "This file has no time dimension to plot.")
            return
        if not self._clicked:
            QMessageBox.information(
                self, "Flow duration",
                "Click a point on the map first, then press Flow duration.")
            return
        if getattr(self, "_fdc_worker", None) is not None:
            return  # a read is already in progress
        lon, lat, _z = self._clicked
        self._start_point_series_read_ui(indeterminate=True)
        self.flowdur_action.setEnabled(False)
        self._fdc_point = (lon, lat)
        worker = _PointSeriesWorker(self, [(lon, lat)], full=True, parent=self)
        self._fdc_worker = worker
        worker.finished_ok.connect(self._on_fdc_ready)
        worker.failed.connect(self._on_fdc_failed)
        worker.finished.connect(self._on_fdc_worker_finished)
        worker.start()

    def _on_fdc_ready(self, series_list):
        from src.gui.widgets.analysis_flow_duration import FlowDurationWindow
        dates = self._point_source.get("full_time_labels") or []
        values = series_list[0] if series_list else []
        label = self._point_name(self._fdc_point)
        try:
            win = FlowDurationWindow(
                [(label, dates, values)], self.varname, self.unit, self.long_name,
                self.settings_title, self.nc_path, parent=self)
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "Flow duration",
                                f"Could not build the flow duration curve:\n{e}")
            return
        self._fdc_window = win  # keep a reference so the non-modal window isn't GC'd
        win.show()
        win.raise_()
        win.activateWindow()

    def _on_fdc_failed(self, msg):
        try:
            QMessageBox.warning(self, "Flow duration",
                                f"Could not read the point's series:\n{msg}")
        except RuntimeError:
            log.debug("_on_fdc_failed: ignored", exc_info=True)

    def _on_fdc_worker_finished(self):
        self._fdc_worker = None
        try:
            self._stop_point_series_read_ui()
            self.flowdur_action.setEnabled(self._multi and not self._compare_mode)
        except RuntimeError:
            log.debug("_on_fdc_worker_finished: ignored", exc_info=True)

    # ----------------------------------------------------------- flow regime
    def _show_flow_regime(self):
        """Action ▸ Flow regime, and the gauge right-click menu's Flow regime: same
        rule as Flow duration - the point last clicked on the map (self._clicked),
        never several at once."""
        if not self._multi:
            QMessageBox.information(self, "Flow regime",
                                    "This file has no time dimension to plot.")
            return
        if not self._clicked:
            QMessageBox.information(
                self, "Flow regime",
                "Click a point on the map first, then press Flow regime.")
            return
        if getattr(self, "_regime_worker", None) is not None:
            return  # a read is already in progress
        lon, lat, _z = self._clicked
        self._start_point_series_read_ui(indeterminate=True)
        self.flowregime_action.setEnabled(False)
        self._regime_point = (lon, lat)
        worker = _PointSeriesWorker(self, [(lon, lat)], full=True, parent=self)
        self._regime_worker = worker
        worker.finished_ok.connect(self._on_regime_ready)
        worker.failed.connect(self._on_regime_failed)
        worker.finished.connect(self._on_regime_worker_finished)
        worker.start()

    def _on_regime_ready(self, series_list):
        from src.gui.widgets.analysis_flow_regime import FlowRegimeWindow
        values = series_list[0] if series_list else []
        dates = self._point_source.get("full_time_labels") or []
        label = self._point_name(self._regime_point)
        try:
            win = FlowRegimeWindow(
                dates, values, label, self.varname, self.unit,
                self.long_name, self.settings_title, self.nc_path, parent=self)
        except ValueError as e:
            QMessageBox.information(self, "Flow regime", str(e))
            return
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.warning(self, "Flow regime",
                                f"Could not build the flow regime curve:\n{e}")
            return
        self._regime_window = win  # keep a reference so the non-modal window isn't GC'd
        win.show()
        win.raise_()
        win.activateWindow()

    def _on_regime_failed(self, msg):
        try:
            QMessageBox.warning(self, "Flow regime",
                                f"Could not read the point's series:\n{msg}")
        except RuntimeError:
            log.debug("_on_regime_failed: ignored", exc_info=True)

    def _on_regime_worker_finished(self):
        self._regime_worker = None
        try:
            self._stop_point_series_read_ui()
            self.flowregime_action.setEnabled(self._multi and not self._compare_mode)
        except RuntimeError:
            log.debug("_on_regime_worker_finished: ignored", exc_info=True)

    # ------------------------------------------- background read progress / cancel
    # Shared by the three _PointSeriesWorker call sites (Total Timeseries, Flow
    # duration, Flow regime): the progress bar + elapsed-time readout + Cancel
    # button. Only one of these ever runs its "start" half at a time in practice
    # (each guards on its own worker attribute being None), but Cancel stops
    # whichever one it is without needing to know which.
    def _start_point_series_read_ui(self, indeterminate, total=0):
        if indeterminate:
            self.ts_progress.setRange(0, 0)   # busy/indeterminate for a single point
            self.ts_progress.setFormat("loading…")
        else:
            self.ts_progress.setRange(0, total)
            self.ts_progress.setValue(0)
            self.ts_progress.setFormat("loading %v/%m")
        self.ts_progress.setVisible(True)
        self._ts_read_start = time.time()
        self.ts_elapsed_label.setText("0.0s")
        self.ts_elapsed_label.setVisible(True)
        self.ts_cancel_button.setEnabled(True)
        self.ts_cancel_button.setVisible(True)
        self._ts_elapsed_timer.start()

    def _stop_point_series_read_ui(self):
        self._ts_elapsed_timer.stop()
        self._ts_read_start = None
        self.ts_progress.setVisible(False)
        self.ts_elapsed_label.setVisible(False)
        self.ts_cancel_button.setVisible(False)

    def _update_ts_elapsed_label(self):
        start = getattr(self, "_ts_read_start", None)
        if start is None:
            return
        try:
            self.ts_elapsed_label.setText(f"{time.time() - start:.1f}s")
        except RuntimeError:
            log.debug("_update_ts_elapsed_label: ignored", exc_info=True)

    def _cancel_point_series_read(self):
        """Cancel button: stop whichever background point-series read is running
        (Total/Fast Timeserie, Flow duration, Flow regime all share one worker type -
        see _PointSeriesWorker.request_stop for why this is cooperative, not instant).
        Also drops a queued Timeseries request so cancelling does not immediately
        chain into reading the same points again."""
        self._ts_next = None
        for attr in ("_ts_worker", "_fdc_worker", "_regime_worker"):
            worker = getattr(self, attr, None)
            if worker is not None:
                worker.request_stop()
        self.ts_progress.setFormat("cancelling…")
        self.ts_cancel_button.setEnabled(False)

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
        self._start_point_series_read_ui(indeterminate=len(pts) <= 1, total=len(pts))
        self.ts_action.setEnabled(False)
        self.ts_fast_action.setEnabled(False)
        worker = _PointSeriesWorker(self, pts, full=True, parent=self)
        self._ts_worker = worker
        worker.progress.connect(self._on_ts_progress)
        worker.finished_ok.connect(
            lambda series, p=pts, o=open_if_closed:
            self._build_ts_window(series, p, o, full=True))
        worker.failed.connect(self._on_ts_failed)
        worker.cancelled.connect(lambda: setattr(self, "_ts_next", None))
        worker.finished.connect(self._on_ts_worker_finished)
        worker.start()

    def _on_ts_progress(self, done, total):
        if total <= 1:
            return  # single point stays indeterminate (busy)
        try:
            self.ts_progress.setRange(0, total)
            self.ts_progress.setValue(done)
        except RuntimeError:
            log.debug("_on_ts_progress: ignored", exc_info=True)

    def _on_ts_failed(self, msg):
        try:
            QMessageBox.warning(self, "Display timeserie",
                                f"Could not read the time series:\n{msg}")
        except RuntimeError:
            log.debug("_on_ts_failed: ignored", exc_info=True)

    def _on_ts_worker_finished(self):
        """Reader thread finished: hide the bar, re-enable the buttons, chain the next
        request if a newer one arrived while reading (never after a cancel - see the
        worker's cancelled signal, connected above)."""
        self._ts_worker = None
        try:
            self._stop_point_series_read_ui()
            self.ts_action.setEnabled(True)
            self.ts_fast_action.setEnabled(True)
        except RuntimeError:
            log.debug("_on_ts_worker_finished: ignored", exc_info=True)
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
                log.debug("_close_ts_window: ignored", exc_info=True)
            try:
                old.close()
            except Exception:
                log.debug("_close_ts_window: ignored", exc_info=True)

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
            win.resize(*scaled_default_size(win, 740, 520))
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
        """Remove a selected point (its pin clicked, or its cell clicked again) from
        the map and the Timeseries."""
        if idx < 0 or idx >= len(self._displayed_points):
            return
        removed = self._displayed_points.pop(idx)
        # Flow duration / regime work off the most recent selection: fall back to
        # the newest point still selected when that one goes
        if self._clicked and (self._clicked[0], self._clicked[1]) == removed:
            self._clicked = None
            if self._displayed_points:
                self._mark_clicked_cell(*self._displayed_points[-1])
        self._update_map_markers()
        self._open_or_refresh_timeseries(open_if_closed=False)

    def _update_map_markers(self):
        """Redraw the selected points as NUMBERED pin icons (colour = Timeseries line
        colour, by index)."""
        arr = [[p[1], p[0], self._point_color(i), str(i + 1)]   # [lat, lon, colour, num]
               for i, p in enumerate(self._displayed_points)]
        self._js("if(window.setPoints) setPoints(%s);" % json.dumps(arr))

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

    def _load_json(self):
        """File > Load JSON: open a GeoJSON file and draw it on the map, same as
        Show Basin's File > Load JSON (shared reader, shared window.addGeoJson JS)."""
        start_dir = os.path.dirname(self.nc_path)
        path, _ = QFileDialog.getOpenFileName(
            self, "Load GeoJSON", start_dir,
            "GeoJSON files (*.geojson *.json);;All files (*)")
        if not path:
            return
        try:
            obj = _read_geojson_file(path)
        except Exception as e:
            QMessageBox.warning(self, "Load JSON",
                                 f"Could not read/parse the file:\n{e}")
            return
        self.info_label.setText(f"Loaded GeoJSON: {os.path.basename(path)}")
        self._js("if(window.addGeoJson) addGeoJson(%s);" % json.dumps(obj))

    def _load_shape(self):
        """File > Load shape: open an ESRI shapefile and draw it on the map exactly
        like Load JSON, same as Show Basin's File > Load shape (shared
        ``_read_shapefile`` reader, shared window.addGeoJson JS)."""
        start_dir = os.path.dirname(self.nc_path)
        path, _ = QFileDialog.getOpenFileName(
            self, "Load shapefile", start_dir, "Shapefiles (*.shp);;All files (*)")
        if not path:
            return
        try:
            obj = _read_shapefile(path)
        except Exception as e:
            QMessageBox.warning(self, "Load shape",
                                 f"Could not read the shapefile:\n{e}")
            return
        self.info_label.setText(f"Loaded shapefile: {os.path.basename(path)}")
        self._js("if(window.addGeoJson) addGeoJson(%s);" % json.dumps(obj))

    def closeEvent(self, event):
        try:
            self._play_timer.stop()
        except Exception:
            log.debug("closeEvent: ignored", exc_info=True)
        try:
            self._ts_elapsed_timer.stop()
        except Exception:
            log.debug("closeEvent: ignored", exc_info=True)
        # Ask any running point-series read (Total Timeseries, Flow duration, Flow
        # regime - all share _PointSeriesWorker) to stop, then let each finish so its
        # QThread is not destroyed while active (it only reads files + emits signals,
        # so this is a short wait once request_stop takes effect between points).
        self._ts_next = None
        for attr in ("_ts_worker", "_fdc_worker", "_regime_worker"):
            worker = getattr(self, attr, None)
            if worker is None:
                continue
            worker.request_stop()
            try:
                worker.finished_ok.disconnect()
                worker.progress.disconnect()
            except Exception:
                log.debug("closeEvent: ignored", exc_info=True)
            try:
                worker.wait(4000)
            except Exception:
                log.debug("closeEvent: ignored", exc_info=True)
        # A mean/percentile calculation cannot be interrupted: let it finish writing
        # its file detached from this window (a QThread destroyed while running
        # aborts the process), just without showing the result.
        worker = getattr(self, "_stat_worker", None)
        if worker is not None and worker.isRunning():
            for sig in (worker.done, worker.failed, worker.finished):
                try:
                    sig.disconnect()
                except Exception:
                    log.debug("closeEvent: ignored", exc_info=True)
            worker.setParent(None)
            _DETACHED_WORKERS.append(worker)
            worker.finished.connect(lambda w=worker: _DETACHED_WORKERS.remove(w))
        self._stat_worker = None
        # Close the shared point-series dataset (_shared_point_dataset), if one was
        # ever opened, so the file handle is released promptly.
        ds = getattr(self, "_point_ds", None)
        if ds is not None:
            try:
                ds.close()
            except Exception:
                log.debug("closeEvent: ignored", exc_info=True)
            self._point_ds = None
        try:
            if self._temp_html and os.path.exists(self._temp_html):
                os.remove(self._temp_html)
        except Exception:
            log.debug("closeEvent: ignored", exc_info=True)
        super().closeEvent(event)
