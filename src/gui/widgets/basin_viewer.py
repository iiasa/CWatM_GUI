"""
Basin Viewer - Pure PySide6 Implementation
==========================================

A comprehensive basin data visualization tool using Qt's native rendering capabilities.
Displays NetCDF basin data with interactive zoom, pan, and overlay features.

Features:
- Native Qt painting (no matplotlib dependency)
- Mouse wheel and button zoom controls
- Click and drag panning
- UPS data visualization with viridis-like colormap
- Semi-transparent mask overlay in green
- Coordinate display on click
- Keyboard shortcuts
- Clean axis frame without gridlines

Author: CWatM GUI Team
"""

import os
import sys
import numpy as np
import xarray as xr
import rasterio
import configparser
import re
from typing import Optional, Tuple, Union

from src.gui.utils.window_geometry import GeometryMemoryMixin
from src.gui.utils import display_format
from src.gui.utils import theme

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QApplication, QMessageBox, QStackedWidget, QSlider, QComboBox
)
from PySide6.QtCore import (Qt, QPoint, Signal, QRect, QUrl, QByteArray, QBuffer, QObject,
                            Slot, QTimer, QFile, QIODevice)
from PySide6.QtGui import (
    QPainter, QWheelEvent, QKeyEvent, QMouseEvent,
    QColor, QBrush, QPen, QFont, QPixmap, QImage, QIcon
)

# Optional interactive OpenStreetMap view (Leaflet rendered in QtWebEngine)
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    from PySide6.QtWebEngineCore import QWebEnginePage
    from PySide6.QtWebChannel import QWebChannel
    import folium
    _OSM_AVAILABLE = True
    _OSM_IMPORT_ERROR = ""

    class _MapBridge(QObject):
        """Exposed to the map's JavaScript for click + logging callbacks."""
        def __init__(self, click_cb, log_cb):
            super().__init__()
            self._click_cb = click_cb
            self._log_cb = log_cb

        @Slot(float, float)
        def click(self, lat, lon):
            self._click_cb(lat, lon)

        @Slot(str)
        def log(self, msg):
            self._log_cb(msg)

    class _MapPage(QWebEnginePage):
        """Web page that ignores TLS certificate errors so OpenStreetMap tiles load
        behind HTTPS-intercepting proxies (a common cause of blank tiles)."""
        def certificateError(self, error):
            try:
                error.acceptCertificate()
            except Exception:
                pass
            return True

    from PySide6.QtWebEngineCore import (QWebEngineUrlScheme, QWebEngineUrlSchemeHandler,
                                         QWebEngineUrlRequestJob)

    # Custom "osmtile" scheme so map tiles are fetched with Python's network stack
    # (which works) instead of QtWebEngine/Chromium (which may be blocked by a proxy).
    # registerScheme must run before the QApplication is created - this module is
    # imported before that happens.
    try:
        _tile_scheme = QWebEngineUrlScheme(b"osmtile")
        _flags = (QWebEngineUrlScheme.Flag.SecureScheme
                  | QWebEngineUrlScheme.Flag.LocalAccessAllowed
                  | QWebEngineUrlScheme.Flag.CorsEnabled)
        # Qt >= 6.6: fetch()/XHR on a custom scheme needs FetchApiAllowed.
        # Leaflet loads tiles via <img> (no fetch), but MapLibre (Show Basin2)
        # fetches them - without this flag it dies with "Failed to fetch".
        _fetch_flag = getattr(QWebEngineUrlScheme.Flag, "FetchApiAllowed", None)
        if _fetch_flag is not None:
            _flags |= _fetch_flag
        _tile_scheme.setFlags(_flags)
        QWebEngineUrlScheme.registerScheme(_tile_scheme)
    except Exception:
        pass

    # Selectable basemaps (all free, no API key). "Transport"/"Cycle" (Thunderforest)
    # need an API key and are intentionally omitted.
    _TILE_PROVIDERS = {
        "standard": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "hot": "https://a.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
        "topo": "https://a.tile.opentopomap.org/{z}/{x}/{y}.png",
        "cartolight": "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
        "cartovoyager": "https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png",
    }

    class _TileSchemeHandler(QWebEngineUrlSchemeHandler):
        """Serve BOTH the map page and basemap tiles via Python (same origin, so a proxy
        that blocks Chromium's own network is bypassed and there is no cross-origin
        restriction between the page and the tiles). Tile URLs carry the provider:
        osmtile://tile/{provider}/{z}/{x}/{y}.png"""
        _session = None
        _logged = False

        def __init__(self):
            super().__init__()
            self._html = b""
            self._html2 = b""  # Show Basin2's Plotly/MapLibre page (osmtile://map2)
            self._pages = {}   # extra same-origin pages by host (e.g. NetCDF)

        def set_html(self, html):
            self._html = html.encode("utf-8") if isinstance(html, str) else html

        def set_html2(self, html):
            self._html2 = html.encode("utf-8") if isinstance(html, str) else html

        def set_page(self, name, html):
            """Register an extra page served at osmtile://<name>/ (same-origin as the
            tiles/WMS). Used by Analyse ▸ NetCDF."""
            self._pages[name] = html.encode("utf-8") if isinstance(html, str) else html

        def requestStarted(self, job):
            url = job.requestUrl()
            # The map pages themselves (served same-origin as the tiles, so no
            # cross-origin restriction applies to the tile fetches)
            host = url.host()
            if host in ("map", "map2") or host in self._pages:
                buf = QBuffer(job)
                buf.setData(QByteArray(self._html if host == "map"
                                       else self._html2 if host == "map2"
                                       else self._pages[host]))
                buf.open(QBuffer.ReadOnly)
                job.reply(b"text/html", buf)
                return
            import re as _re, os as _os, tempfile
            # A WMS GetMap request (Show Basin2, EPSG:4326): osmtile://wms/service?<query>.
            # The query (LAYERS/BBOX/SRS/...) is forwarded verbatim to a real OSM WMS
            # endpoint - so an EPSG:4326 map gets a correctly-projected OSM basemap
            # (XYZ tiles are Web-Mercator and cannot align on a 4326 map). Fetched with
            # Python (proxy-proof) and cached by the query.
            if url.host() == "wms":
                import hashlib
                q = url.query()
                real = "https://ows.terrestris.de/osm/service?" + q
                cache = _os.path.join(tempfile.gettempdir(), 'cwatm_wms')
                _os.makedirs(cache, exist_ok=True)
                fp = _os.path.join(cache, hashlib.md5(q.encode("utf-8")).hexdigest() + ".png")
                try:
                    if not _os.path.exists(fp):
                        import requests
                        if _TileSchemeHandler._session is None:
                            sess = requests.Session()
                            sess.headers.update({"User-Agent": "CWatM-GUI/1.0 (basin viewer)"})
                            _TileSchemeHandler._session = sess
                        r = _TileSchemeHandler._session.get(real, timeout=15)
                        if r.status_code != 200 or "image" not in r.headers.get("content-type", ""):
                            job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)
                            return
                        with open(fp, "wb") as f:
                            f.write(r.content)
                    buf = QBuffer(job)
                    buf.setData(QByteArray(open(fp, "rb").read()))
                    buf.open(QBuffer.ReadOnly)
                    job.reply(b"image/png", buf)
                except Exception as _e:
                    if not _TileSchemeHandler._logged:
                        _TileSchemeHandler._logged = True
                        print("WMS: fetch via Python FAILED: %s" % _e, file=sys.stderr)
                    try:
                        job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)
                    except Exception:
                        pass
                return
            # A tile: osmtile://tile/{provider}/{z}/{x}/{y}.png
            m = _re.search(r'/tile/([^/]+)/(\d+)/(\d+)/(\d+)\.png', url.toString())
            if not m:
                job.fail(QWebEngineUrlRequestJob.Error.UrlNotFound)
                return
            provider, z, x, y = m.groups()
            tmpl = _TILE_PROVIDERS.get(provider, _TILE_PROVIDERS["standard"])
            tile_url = tmpl.format(z=z, x=x, y=y)
            cache = _os.path.join(tempfile.gettempdir(), 'cwatm_tiles')
            _os.makedirs(cache, exist_ok=True)
            fp = _os.path.join(cache, "%s_%s_%s_%s.png" % (provider, z, x, y))
            try:
                if not _os.path.exists(fp):
                    import requests
                    if _TileSchemeHandler._session is None:
                        sess = requests.Session()
                        sess.headers.update({"User-Agent": "CWatM-GUI/1.0 (basin viewer)"})
                        _TileSchemeHandler._session = sess
                    r = _TileSchemeHandler._session.get(tile_url, timeout=12)
                    if r.status_code != 200:
                        job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)
                        return
                    with open(fp, "wb") as f:
                        f.write(r.content)
                buf = QBuffer(job)
                buf.setData(QByteArray(open(fp, "rb").read()))
                buf.open(QBuffer.ReadOnly)
                job.reply(b"image/png", buf)
            except Exception as _e:
                if not _TileSchemeHandler._logged:
                    _TileSchemeHandler._logged = True
                    print("OSM: tile fetch via Python FAILED: %s" % _e, file=sys.stderr)
                try:
                    job.fail(QWebEngineUrlRequestJob.Error.RequestFailed)
                except Exception:
                    pass

    # A single, app-lifetime scheme handler. QWebEngineView uses the shared default
    # profile, so re-installing a per-window handler on the 2nd Show Basin was ignored
    # ("already registered") and left a dead handler -> blank map. Reuse one handler.
    _TILE_HANDLER_SINGLETON = None

    def _get_tile_handler():
        global _TILE_HANDLER_SINGLETON
        if _TILE_HANDLER_SINGLETON is None:
            _TILE_HANDLER_SINGLETON = _TileSchemeHandler()
        return _TILE_HANDLER_SINGLETON
except Exception as _osm_err:
    _OSM_AVAILABLE = False
    _OSM_IMPORT_ERROR = f"{type(_osm_err).__name__}: {_osm_err}"
    print(f"OpenStreetMap view unavailable: {_OSM_IMPORT_ERROR}", file=sys.stderr)

import cwatm.run_cwatm as run_cwatm


class BasinDataHelpers:
    """Display-agnostic helpers shared by the basin viewer. They only read
    ``self.basin_data`` / ``lats`` / ``lons`` / ``mask_data`` / ``settings_file`` and
    the live main-window fields, so they carry no UI of their own. (Extracted from the
    former classic ``BasinWindow`` / ``BasinCanvas``, now removed - Show Basin is the
    folium EPSG:4326 viewer in ``basin_viewer2``.)"""

    def _orient(self, rgba):
        """Flip an image so the top row is north and the left column is west (as the
        map's ImageOverlay expects), based on the lat/lon coordinate order."""
        lats = np.asarray(self.lats)
        lons = np.asarray(self.lons)
        if lats.ndim == 1 and lats.size > 1 and lats[0] < lats[-1]:
            rgba = rgba[::-1]
        if lons.ndim == 1 and lons.size > 1 and lons[0] > lons[-1]:
            rgba = rgba[:, ::-1]
        return rgba

    def _build_ups_rgba(self):
        """RGBA image of the full upstream-area grid (ups.nc), blue by log(area)."""
        basin = np.asarray(self.basin_data, dtype=float)
        H, W = basin.shape
        valid = np.isfinite(basin) & (basin > 0)
        if valid.any():
            v = np.log1p(np.where(valid, basin, 0.0))
            vmin, vmax = float(v[valid].min()), float(v[valid].max())
            norm = np.clip((v - vmin) / (vmax - vmin + 1e-9), 0.0, 1.0)
        else:
            norm = np.zeros((H, W))
        c0 = np.array([222, 235, 247], dtype=float)  # light blue
        c1 = np.array([8, 48, 107], dtype=float)      # dark blue
        col = (c0 * (1 - norm[..., None]) + c1 * norm[..., None]).astype(np.uint8)
        rgba = np.zeros((H, W, 4), dtype=np.uint8)
        rgba[..., :3] = col
        # Valid cells are FULLY opaque (alpha 255): the overlay opacity is then
        # controlled solely by the transparency slider, so at the slider's left
        # extreme (opacity 1.0) the ups overlay completely hides the OSM basemap.
        rgba[..., 3] = np.where(valid, 255, 0).astype(np.uint8)
        return self._orient(rgba)

    def _build_mask_rgba(self):
        """RGBA image of the mask (basin) as a semi-transparent green layer."""
        basin = np.asarray(self.basin_data, dtype=float)
        H, W = basin.shape
        mask = np.asarray(self.mask_data) if self.mask_data is not None else None
        rgba = np.zeros((H, W, 4), dtype=np.uint8)
        if mask is not None and mask.shape == (H, W):
            inside = mask == 1
            rgba[inside] = np.array([0, 170, 0, 110], dtype=np.uint8)
        return self._orient(rgba)

    def _rgba_to_datauri(self, rgba):
        """Encode an RGBA numpy array to a base64 PNG data URI (via QImage)."""
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

    def _main_window(self):
        """Return the main GUI window (holds the live MaskMap/Gauges text boxes)."""
        app = QApplication.instance()
        if app:
            for w in app.allWidgets():
                if hasattr(w, 'maskmap_field') and hasattr(w, 'gauges_field'):
                    return w
        return None

    def _field_gauges(self):
        """Red-point source: gauge (lon, lat) pairs from the live Gauges text box,
        falling back to the settings file if the text box is unavailable."""
        mw = self._main_window()
        if mw is not None:
            try:
                pairs = _parse_coord_pairs(mw.gauges_field.text())
                if pairs:
                    return pairs
            except Exception:
                pass
        try:
            return _parse_gauges(open(self.settings_file, encoding="utf-8",
                                      errors="ignore").read())
        except Exception:
            return []

    def _mask_start_point(self):
        """Blue-point source: the MaskMap coordinate from the live MaskMap text box (if
        it is a 'lon lat' pair), else the MaskMap in the settings file, else the
        largest-ups cell inside the mask (the catchment outlet)."""
        mw = self._main_window()
        if mw is not None:
            try:
                pairs = _parse_coord_pairs(mw.maskmap_field.text())
                if pairs:
                    return pairs[0]
            except Exception:
                pass
        try:
            content = open(self.settings_file, encoding="utf-8", errors="ignore").read()
            viewer = BasinViewer(content)
            mask_path = viewer._find_mask_path()
            if mask_path:
                resolved = viewer._resolve_placeholders(mask_path) or mask_path
                parts = resolved.split()
                if len(parts) >= 2:
                    return float(parts[0]), float(parts[1])
        except Exception:
            pass
        return self._largest_ups_point()

    def _largest_ups_point(self):
        """Return (lon, lat) of the ups.nc cell with the largest upstream area that is
        inside the mask, computed directly from the in-memory arrays. None if absent."""
        try:
            basin = np.asarray(self.basin_data, dtype=float)
            lats = np.asarray(self.lats)
            lons = np.asarray(self.lons)
            if basin.ndim != 2 or lats.ndim != 1 or lons.ndim != 1:
                return None
            if self.mask_data is not None and np.asarray(self.mask_data).shape == basin.shape:
                inside = np.asarray(self.mask_data) == 1
            else:
                inside = np.isfinite(basin)
            u = np.where(inside & np.isfinite(basin), basin, -np.inf)
            if not np.isfinite(u).any():
                return None
            r, c = np.unravel_index(int(np.argmax(u)), u.shape)
            return float(lons[c]), float(lats[r])
        except Exception as e:
            print(f"Error finding largest ups point: {e}", file=sys.stderr)
            return None

    def _ups_text(self, lon, lat):
        """ups.nc value (upstream area) at the cell nearest to (lon, lat), shown in
        the marker tooltips as 'UPS: <n> km2' - no decimals by design. Empty string
        when it cannot be determined."""
        try:
            lats = np.asarray(self.lats)
            lons = np.asarray(self.lons)
            if lats.ndim != 1 or lons.ndim != 1:
                return ""
            row = int(np.abs(lats - float(lat)).argmin())
            col = int(np.abs(lons - float(lon)).argmin())
            basin = np.asarray(self.basin_data, dtype=float)
            if not (0 <= row < basin.shape[0] and 0 <= col < basin.shape[1]):
                return ""
            val = basin[row, col]
            if np.isnan(val):
                return "no data"
            return "%d km<sup>2</sup>" % int(round(val))
        except Exception:
            return ""

    def _mask_bbox(self):
        """Return (row0, row1, col0, col1) bounding box of the mask==1 cells, or None."""
        if self.mask_data is None:
            return None
        m = np.asarray(self.mask_data) == 1
        if not m.any():
            return None
        rows = np.where(m.any(axis=1))[0]
        cols = np.where(m.any(axis=0))[0]
        return int(rows.min()), int(rows.max()), int(cols.min()), int(cols.max())

    def _run_gauge_check(self, main_window, rebuild_mask=False):
        """Apply the just-edited field into the settings content and re-check whether
        the gauge is inside the mask (rebuilding the mask cache first if MaskMap
        changed). Called after Copy Mask / Copy Gauge / gauge removal."""
        try:
            flush = getattr(main_window, "_flush_pending_field_changes", None)
            if callable(flush):
                flush()
            if rebuild_mask:
                rebuild = getattr(main_window, "_rebuild_mask_cache", None)
                if callable(rebuild):
                    rebuild(force=True)
            check = getattr(main_window, "_update_warnings", None)
            if callable(check):
                check(check_pathout=False)
        except Exception as e:
            print(f"Gauge-in-mask check failed: {e}", file=sys.stderr)


class BasinViewer:
    """
    Main basin viewer class for loading and displaying NetCDF basin data.
    Handles configuration parsing, data loading, and window management.
    """
    
    def __init__(self, config_content: Optional[str] = None):
        """
        Initialize the basin viewer.
        
        Args:
            config_content: INI configuration file content as string
        """
        self.config_content = config_content
        # Data loader only now: the window is opened by basin_viewer2.show_basin2
        # (Tools ▸ Show Basin). The classic BasinWindow launcher was removed.

    def _find_ups_path(self) -> Optional[str]:
        """Find UPS file path from TOPOP.ldd configuration."""
        if not self.config_content:
            return None
            
        try:
            config = configparser.ConfigParser()
            config.read_string(self.config_content)
            
            if config.has_section("TOPOP") and config.has_option("TOPOP", "ldd"):
                ldd_path = config.get("TOPOP", "ldd")
                # Replace filename with ups.nc
                directory = os.path.dirname(ldd_path)
                return os.path.join(directory, "ups.nc")
            else:
                print("Warning: ldd not found in [TOPOP] section", file=sys.stderr)
                return None
                
        except Exception as e:
            print(f"Error finding UPS path: {e}", file=sys.stderr)
            return None
            
    def _find_title(self) -> Optional[str]:
        """Return the 'Title' value from the settings file, or None if absent."""
        if not self.config_content:
            return None
        try:
            config = configparser.ConfigParser(interpolation=None)
            config.read_string(self.config_content)
            for section_name in config.sections():
                for key, value in config.items(section_name):
                    if key.lower() == 'title':
                        return value.strip()
        except Exception as e:
            print(f"Error finding Title: {e}", file=sys.stderr)
        return None

    def _find_mask_path(self) -> Optional[str]:
        """Find mask file path from configuration."""
        if not self.config_content:
            return None
            
        try:
            config = configparser.ConfigParser()
            config.read_string(self.config_content)
            
            # Search for MaskMap in all sections
            for section_name in config.sections():
                for key, value in config.items(section_name):
                    if key.lower() == 'maskmap':
                        return value
            return None
            
        except Exception as e:
            print(f"Error finding mask path: {e}", file=sys.stderr)
            return None
            
    def _resolve_placeholders(self, path: str) -> str:
        """Resolve $(section:key) placeholders in file paths."""
        if not path or '$' not in path or not self.config_content:
            return path
            
        try:
            config = configparser.ConfigParser()
            config.read_string(self.config_content)
            
            # Resolve placeholders iteratively (up to 10 iterations)
            for _ in range(10):
                placeholders = re.findall(r'\$\(([^)]+)\)', path)

                if not placeholders:
                    break
                    
                for placeholder in placeholders:
                    parts = placeholder.split(":")
                    if len(parts) >= 2:
                        section_name, key_name = parts[0], parts[1]
                        if config.has_section(section_name) and config.has_option(section_name, key_name):
                            value = config.get(section_name, key_name)
                            path = path.replace(f'$({placeholder})', value)
                    else:
                        # Try FILE_PATHS section
                        key_name = parts[0]
                        if config.has_section("FILE_PATHS") and config.has_option("FILE_PATHS", key_name):
                            value = config.get("FILE_PATHS", key_name)
                            path = path.replace(f'$({placeholder})', value)
                            
            return path
            
        except Exception as e:
            print(f"Error resolving placeholders: {e}", file=sys.stderr)
            return path
            
    def _load_netcdf_data(self, file_path: str) -> Tuple[Optional[np.ndarray], Optional[np.ndarray], Optional[np.ndarray]]:
        """Load basin data from NetCDF file."""
        try:
            ds = xr.open_dataset(file_path)
            
            # Find data variable
            data_vars = [var for var in ds.data_vars.keys()]
            coord_vars = [var for var in ds.coords.keys()]
            
            # Pick the first data variable that is at least 2D. GDAL-written NetCDFs
            # often expose a 0-dim grid-mapping variable (e.g. 'crs') as the first
            # data_var; using it blindly makes basin_data 0-dimensional and later
            # crashes mask loading with "too many indices ... array is 0-dim".
            basin_var = next((v for v in data_vars if ds[v].ndim >= 2), None)
            if basin_var is not None:
                basin_data = ds[basin_var]
            else:
                # Fallback to first suitable variable
                suitable_var = None
                for var in ds.variables.keys():
                    if var not in coord_vars and len(ds[var].dims) >= 2:
                        suitable_var = var
                        break
                        
                if suitable_var:
                    basin_data = ds[suitable_var]
                else:
                    print("No suitable data variable found", file=sys.stderr)
                    ds.close()
                    return None, None, None
                    
            # Find coordinate variables
            lat_var = lon_var = None
            lat_names = ['lat', 'latitude', 'y', 'LAT', 'LATITUDE', 'Y']
            lon_names = ['lon', 'longitude', 'x', 'LON', 'LONGITUDE', 'X']
            
            for name in lat_names:
                if name in ds.coords or name in ds.variables:
                    lat_var = name
                    break
                    
            for name in lon_names:
                if name in ds.coords or name in ds.variables:
                    lon_var = name
                    break
                    
            if not lat_var or not lon_var:
                # Use dimensions as fallback
                dims = list(basin_data.dims)
                if len(dims) >= 2:
                    lat_var, lon_var = dims[-2], dims[-1]
                else:
                    print("Cannot determine coordinate system", file=sys.stderr)
                    ds.close()
                    return None, None, None
                    
            # Extract data
            lats = ds[lat_var].values
            lons = ds[lon_var].values
            
            # Handle extra dimensions
            if basin_data.ndim > 2:
                # Reduce non-spatial dims (everything except the last two, which are
                # the spatial axes) to their first index. Using positions avoids
                # over-reducing to 0-dim when dim names differ from the coord names.
                spatial_dims = basin_data.dims[-2:]
                basin_data = basin_data.isel({dim: 0 for dim in basin_data.dims
                                              if dim not in spatial_dims})

            basin_array = basin_data.values
            ds.close()

            if basin_array.ndim != 2:
                print(f"Basin data is not 2D (shape {basin_array.shape}); cannot display",
                      file=sys.stderr)
                return None, None, None

            return basin_array, lats, lons
            
        except Exception as e:
            print(f"Error loading NetCDF data: {e}", file=sys.stderr)
            return None, None, None
            
    @staticmethod
    def _paste_mask_on_ups(mask, transform, upsshape, ups_lats, ups_lons):
        """Place a region MaskMap raster at its geographic position in the ups grid.

        The offset is found by matching the mask's first cell CENTRE against the
        ups lat/lon coordinate arrays (both grids are cell-centred and, for a CWatM
        setup, share the resolution). Returns the mask unchanged when it cannot be
        placed (no coordinates, different resolution, or no overlap) - callers
        already guard on a shape mismatch.
        """
        try:
            if ups_lats is None or ups_lons is None or transform is None:
                return mask
            lats = np.asarray(ups_lats, dtype=float)
            lons = np.asarray(ups_lons, dtype=float)
            if lats.ndim != 1 or lons.ndim != 1 or lats.size < 2 or lons.size < 2:
                return mask
            # Resolutions must match (cell-for-cell paste, no resampling)
            ups_dlon = abs(float(lons[1] - lons[0]))
            ups_dlat = abs(float(lats[1] - lats[0]))
            m_dlon, m_dlat = abs(float(transform.a)), abs(float(transform.e))
            if (abs(m_dlon - ups_dlon) > ups_dlon * 0.01
                    or abs(m_dlat - ups_dlat) > ups_dlat * 0.01):
                print("MaskMap resolution differs from ups.nc - mask not aligned",
                      file=sys.stderr)
                return mask
            # Longitude always runs west->east (both grids), so columns need no
            # direction handling. LATITUDE does vary: north->south is the common
            # NetCDF/raster layout, but south->north occurs too (_orient flips the
            # overlay for it). Pasting rows against the ups grid's direction would
            # land the mask mirrored and a full mask-height off the basin, silently.
            mask_n_to_s = float(transform.e) < 0        # raster row 0 is the north edge
            ups_n_to_s = float(lats[0]) > float(lats[-1])
            if mask_n_to_s != ups_n_to_s:
                mask = mask[::-1]                       # flip rows to the ups direction
            h, w = mask.shape
            # Geographic centre of the row that is now first, and of column 0
            first_row = 0 if mask_n_to_s == ups_n_to_s else h - 1
            lat0 = float(transform.f) + float(transform.e) * (first_row + 0.5)
            lon0 = float(transform.c) + float(transform.a) / 2.0
            col0 = int(np.abs(lons - lon0).argmin())
            row0 = int(np.abs(lats - lat0).argmin())
            big = np.zeros(tuple(upsshape), dtype=mask.dtype)
            # Clip to the ups grid in case the mask overhangs an edge
            r1, c1 = min(row0 + h, big.shape[0]), min(col0 + w, big.shape[1])
            if r1 <= row0 or c1 <= col0:
                print("MaskMap lies outside the ups.nc grid - mask not aligned",
                      file=sys.stderr)
                return mask
            big[row0:r1, col0:c1] = mask[:r1 - row0, :c1 - col0]
            return big
        except Exception as e:
            print(f"Could not align MaskMap to the ups grid: {e}", file=sys.stderr)
            return mask

    def _load_mask_data(self, settings_file: str, upsshape,
                        ups_lats=None, ups_lons=None):
        """Load mask data if available, always returned on the ups.nc grid.

        A MaskMap raster (.map/.tif/.nc) usually covers only the modelled region,
        while ups.nc is often the full global grid - e.g. rhine5min.map is 68x77
        against a 1800x4320 ups. Such a mask must be PASTED at its geographic
        position in the ups grid (the coordinate branch below already does this
        with mainwarm's x/y offsets); returned raw, its indices mean nothing on the
        ups grid, which left the mask overlay invisible (shape guard in
        _build_mask_rgba), the blue marker at the GLOBAL ups maximum instead of the
        basin outlet, and "zoom to mask" pointing at the wrong place.
        Pass ups_lats/ups_lons to enable the alignment; without them (or if the
        resolutions differ) the raster is returned as read, as before.
        """
        try:
            mask_path = self._find_mask_path()
            if not mask_path:
                return None

            coord = mask_path.split()
            if len(coord) < 2:
                # File path - load with rasterio
                resolved_path = self._resolve_placeholders(mask_path)
                if resolved_path and os.path.exists(resolved_path):
                    with rasterio.open(resolved_path) as src:
                        mask = src.read(1)
                        transform = src.transform
                    mask = np.where(mask > 1, 0, 1)
                    if mask.shape != tuple(upsshape):
                        mask = self._paste_mask_on_ups(
                            mask, transform, upsshape, ups_lats, ups_lons)
                    return mask
                else:
                    print(f"Mask file not found: {resolved_path}", file=sys.stderr)
                    return None
            else:
                # Coordinate-based - use CWatM's mask routine (mainwarm -vgm).
                # IMPORTANT: the gauge check is defined against the LIVE settings
                # content (self.config_content = the left-window boxes), which can
                # differ from the file on disk - e.g. right after Copy Mask /
                # Copy Gauge or a manual MaskMap edit, before saving. mainwarm can
                # only read a file, so write the live content to a temporary .ini
                # next to the original (same dir, so relative paths and
                # placeholders resolve identically) and run the routine on that.
                # Running it on `settings_file` directly built the OLD basin and
                # made the check wrongly flag gauges as outside.
                import tempfile
                run_file = settings_file
                temp_path = None
                try:
                    if self.config_content:
                        base_dir = (os.path.dirname(os.path.abspath(settings_file))
                                    if settings_file else os.getcwd())
                        fd, temp_path = tempfile.mkstemp(
                            suffix=".ini", prefix="temp_gaugecheck_", dir=base_dir)
                        with os.fdopen(fd, "w", encoding="utf-8") as f:
                            f.write(self.config_content)
                        run_file = temp_path
                    mask_result = run_cwatm.mainwarm(run_file, ["-vgm"], [])
                finally:
                    if temp_path:
                        try:
                            os.remove(temp_path)
                        except Exception:
                            pass
                if mask_result:
                    mask_data = mask_result[0].data
                    mask_data = np.where(mask_data != 1, 0, 1)
                    if mask_data.shape != upsshape:
                        x = mask_result[1]
                        y = mask_result[2]
                        maskbig = np.zeros(upsshape)
                        maskbig[y:y + mask_data.shape[0], x:x + mask_data.shape[1]] = mask_data
                        mask_data = maskbig
                    # (a mask generated on the full ups grid needs no pasting -
                    # the old code fell through to `return None` in that case)
                    return mask_data
                return None
                
        except Exception as e:
            print(f"Error loading mask data: {e}", file=sys.stderr)
            return None


def grid_is_latlon(lats, lons):
    """True if the coordinate arrays look like geographic lon/lat (EPSG:4326).

    Projected grids (e.g. Norway UTM33 in metres, with y around 6.9e6) have
    values far outside the +-90 / +-360 degree ranges; those are shown without
    an OSM basemap (Leaflet ``CRS.Simple``) by the map viewers."""
    try:
        la = np.asarray(lats, dtype=float)
        lo = np.asarray(lons, dtype=float)
        if la.size == 0 or lo.size == 0:
            return True
        lamax = float(np.nanmax(np.abs(la)))
        lomax = float(np.nanmax(np.abs(lo)))
        if not (np.isfinite(lamax) and np.isfinite(lomax)):
            return True  # unusable coords -> keep the normal lat/lon path
        return lamax <= 90.0001 and lomax <= 360.0001
    except Exception:
        return True


def _parse_gauges(config_content: str):
    """Extract gauge (lon, lat) pairs from the 'Gauges' setting.

    CWatM gives Gauges as whitespace-separated "lon lat" pairs. Returns a list of
    (lon, lat) tuples, or an empty list if none can be parsed.
    """
    try:
        config = configparser.ConfigParser(interpolation=None)
        config.read_string(config_content)
        value = None
        for section in config.sections():
            for key, val in config.items(section):
                if key.lower() == 'gauges':
                    value = val
                    break
            if value is not None:
                break
        if not value:
            return []
        nums = [float(x) for x in re.split(r'[\s,]+', value.strip()) if x]
        return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
    except Exception:
        return []


def _parse_coord_pairs(value: str):
    """Parse a raw 'lon lat [lon lat ...]' string (e.g. a Gauges/MaskMap text-box
    value) into a list of (lon, lat) tuples. Empty list if it is not coordinates."""
    try:
        nums = [float(x) for x in re.split(r'[\s,]+', (value or '').strip()) if x]
        return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]
    except Exception:
        return []


def build_mask_context(settings_file: str, config_content: str):
    """Build an in-memory mask for gauge-in-basin checks.

    Handles both a file-based MaskMap (a raster path) and a coordinate-based
    MaskMap (a "lon lat" pair), for which a basin is generated with CWatM's mask
    routine (BasinViewer._load_mask_data / mainwarm). The result is a small binary
    mask kept in memory so the gauge check can run repeatedly without regenerating
    it. Rebuild this only when a settings file is loaded or the MaskMap changes.

    Returns a context dict, or None if it cannot be built:
      - {'type': 'raster', 'mask': uint8[H,W] (1=inside), 'transform', 'nrows', 'ncols'}
      - {'type': 'grid',   'mask': uint8[H,W] (1=inside), 'lats': 1D, 'lons': 1D}
    """
    try:
        viewer = BasinViewer(config_content)
        mask_path = viewer._find_mask_path()
        if not mask_path:
            return None

        if len(mask_path.split()) < 2:
            # --- File-based raster mask ---
            resolved = viewer._resolve_placeholders(mask_path)
            if not resolved or not os.path.exists(resolved):
                return None
            with rasterio.open(resolved) as src:
                band = src.read(1, masked=True)
                filled = np.ma.filled(band, 0)
                inside = (~np.ma.getmaskarray(band)) & (filled != 0)
                if src.nodata is not None:
                    inside &= (np.ma.filled(band, src.nodata) != src.nodata)
                return {
                    'type': 'raster',
                    'mask': inside.astype(np.uint8),
                    'transform': src.transform,
                    'nrows': band.shape[0],
                    'ncols': band.shape[1],
                }
        else:
            # --- Coordinate-based mask: generate a basin and align to the ups grid ---
            ups_path = viewer._find_ups_path()
            if not ups_path:
                return None
            resolved_ups = viewer._resolve_placeholders(ups_path)
            if not resolved_ups or not os.path.exists(resolved_ups):
                return None
            basin_data, lats, lons = viewer._load_netcdf_data(resolved_ups)
            if basin_data is None:
                return None
            lats = np.asarray(lats)
            lons = np.asarray(lons)
            if lats.ndim != 1 or lons.ndim != 1:
                return None
            mask = viewer._load_mask_data(settings_file, basin_data.shape,
                                          lats, lons)
            if mask is None:
                return None
            return {
                'type': 'grid',
                'mask': (np.asarray(mask) == 1).astype(np.uint8),
                'lats': lats,
                'lons': lons,
            }
    except Exception as e:
        print(f"Error building mask context: {e}", file=sys.stderr)
        return None


def _point_in_mask(context, lon, lat):
    """Return True if (lon, lat) falls on an inside (==1) cell of the mask context."""
    if context is None:
        return False
    if context['type'] == 'raster':
        from rasterio.transform import rowcol
        try:
            row, col = rowcol(context['transform'], lon, lat)
        except Exception:
            return False
        if 0 <= row < context['nrows'] and 0 <= col < context['ncols']:
            return context['mask'][row, col] == 1
        return False
    else:  # grid
        lats, lons, mask = context['lats'], context['lons'], context['mask']
        # Point must be within the grid extent
        if lat < lats.min() or lat > lats.max() or lon < lons.min() or lon > lons.max():
            return False
        row = int(np.abs(lats - lat).argmin())
        col = int(np.abs(lons - lon).argmin())
        if 0 <= row < mask.shape[0] and 0 <= col < mask.shape[1]:
            return mask[row, col] == 1
        return False


def gauges_inside(context, config_content):
    """Check the Gauges from config against a prebuilt mask context.

    Returns True if all gauges are inside, False if any is outside, or None if the
    check cannot be performed (no context or no gauges).
    """
    if context is None:
        return None
    gauges = _parse_gauges(config_content)
    if not gauges:
        return None
    for lon, lat in gauges:
        if not _point_in_mask(context, lon, lat):
            return False
    return True


def gauges_in_maskmap(settings_file: str, config_content: str):
    """Convenience: build the mask context and check the gauges in one call.
    (main_window caches the context and calls gauges_inside directly.)"""
    return gauges_inside(build_mask_context(settings_file, config_content), config_content)


def find_largest_ups_gauge(settings_file: str, config_content: str, context=None):
    """Find the cell centre (lon, lat) with the largest upstream area (from ups.nc)
    that lies inside the mask map. Returns (lon, lat) or None.

    Works for both a file-based and a coordinate-based MaskMap: candidate cells are
    the ups grid cells, tested for membership against the (prebuilt) mask context.
    """
    try:
        viewer = BasinViewer(config_content)
        ups_path = viewer._find_ups_path()
        if not ups_path:
            return None
        resolved_ups = viewer._resolve_placeholders(ups_path)
        if not resolved_ups or not os.path.exists(resolved_ups):
            return None
        ups, lats, lons = viewer._load_netcdf_data(resolved_ups)
        if ups is None:
            return None
        ups = np.asarray(ups, dtype=float)
        lats = np.asarray(lats)
        lons = np.asarray(lons)
        if ups.ndim != 2 or lats.ndim != 1 or lons.ndim != 1:
            return None

        if context is None:
            context = build_mask_context(settings_file, config_content)
        if context is None:
            return None

        # Fast path: a grid mask already aligned to the ups grid
        if context.get('type') == 'grid' and context['mask'].shape == ups.shape:
            inside = context['mask'] == 1
            u = np.where(inside & ~np.isnan(ups), ups, -np.inf)
            if not np.isfinite(u).any():
                return None
            r, c = np.unravel_index(int(np.argmax(u)), u.shape)
            return float(lons[c]), float(lats[r])

        # General path: walk ups cells from largest to smallest, return the first
        # one that falls inside the mask.
        flat = ups.ravel()
        ncols = ups.shape[1]
        order = np.argsort(np.where(np.isnan(flat), -np.inf, flat))[::-1]
        for fi in order:
            val = flat[fi]
            if not np.isfinite(val):
                break
            r, c = divmod(int(fi), ncols)
            if _point_in_mask(context, float(lons[c]), float(lats[r])):
                return float(lons[c]), float(lats[r])
        return None
    except Exception as e:
        print(f"Error finding largest-ups gauge: {e}", file=sys.stderr)
        return None


def _find_setting_value(config, key_wanted):
    """Return the value of a key from any section (case-insensitive), or None."""
    for section in config.sections():
        for key, val in config.items(section):
            if key.lower() == key_wanted.lower():
                return val
    return None


def _resolve_settings_placeholders(value, config):
    """Resolve $(section:key) and $(key) placeholders in a settings value using the
    other entries of the settings file. Unresolvable placeholders are left as-is."""
    for _ in range(10):
        placeholders = re.findall(r'\$\(([^)]+)\)', value)
        if not placeholders:
            break
        replaced_any = False
        for ph in placeholders:
            parts = ph.split(':')
            repl = None
            if len(parts) >= 2:
                sec, k = parts[0], parts[1]
                if config.has_section(sec) and config.has_option(sec, k):
                    repl = config.get(sec, k)
            else:
                repl = _find_setting_value(config, parts[0])
            if repl is not None:
                value = value.replace(f'$({ph})', repl)
                replaced_any = True
        if not replaced_any:
            break
    return value


def pathout_exists(config_content):
    """Check whether the PathOut folder from the settings exists.

    Placeholders such as $(PathRoot) / $(FILE_PATHS:PathRoot) are resolved from the
    other settings entries first.

    Returns
    -------
    (True,  resolved_path) - PathOut exists
    (False, resolved_path) - PathOut does not exist
    (None,  None)          - PathOut not found / could not be checked
    """
    try:
        config = configparser.ConfigParser(interpolation=None)
        config.read_string(config_content)
        pathout = _find_setting_value(config, 'pathout')
        if pathout is None:
            return None, None
        resolved = _resolve_settings_placeholders(pathout.strip(), config)
        if not resolved:
            return None, None
        return os.path.exists(resolved), resolved
    except Exception as e:
        print(f"Error checking PathOut: {e}", file=sys.stderr)
        return None, None


# === Module Exports ===
__all__ = ['BasinViewer', 'BasinDataHelpers', 'gauges_in_maskmap',
           'build_mask_context', 'gauges_inside', 'pathout_exists',
           'find_largest_ups_gauge']