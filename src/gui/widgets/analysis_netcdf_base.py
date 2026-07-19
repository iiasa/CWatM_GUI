"""
NetCDF **data layer** for the CWatM GUI (shared, no UI).

``NetcdfDataBase`` reads a CWatM result / input ``.nc`` file with xarray and exposes
the pieces the NetCDF map viewer (``analysis_netcdf.py``) needs: the per-timestep
grid loading (``_load``), the variable/coordinate guessing, the settings-``Title``
and ``metaNetcdf.xml`` lookups, and the lazy per-cell time-series re-read
(``_point_series``) used by *Display timeserie*. The classic Plotly heatmap viewer
that used to live here was removed - there is only one NetCDF viewer now (the folium
EPSG:4326 map in ``analysis_netcdf.py``, which subclasses this base).

The variable's unit / long name / description are looked up in ``cwatm/metaNetcdf.xml``
exactly as in the Timeseries window.
"""

import os
import re
import sys
import json
import math
import tempfile

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QIcon, QGuiApplication

from src.gui.utils.window_geometry import GeometryMemoryMixin
from src.gui.utils import theme


def _position_offset(win, frac):
    """Place ``win`` shifted horizontally from the screen centre by ``frac`` of the
    screen width (negative = left of centre, positive = right of centre)."""
    try:
        geo = QGuiApplication.primaryScreen().availableGeometry()
        x = geo.x() + (geo.width() - win.width()) // 2 + int(frac * geo.width())
        y = geo.y() + (geo.height() - win.height()) // 2
        win.move(max(geo.x(), x), max(geo.y(), y))
    except Exception:
        pass

# Optional dependencies: xarray for reading the file, Plotly for the figure and
# QtWebEngine to render it.
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    import plotly.graph_objects as go
    import xarray as xr
    import numpy as np
    _NC_AVAILABLE = True
    _NC_IMPORT_ERROR = ""
except Exception as _nc_err:  # pragma: no cover - import guard
    _NC_AVAILABLE = False
    _NC_IMPORT_ERROR = f"{type(_nc_err).__name__}: {_nc_err}"
    print(f"NetCDF analysis unavailable: {_NC_IMPORT_ERROR}", file=sys.stderr)

# Cap the number of animation frames (time steps embedded in the HTML). Longer time
# axes are subsampled with a stride so the figure stays a reasonable size.
_MAX_FRAMES = 400

# Candidate coordinate names (lower-case, substring match as a fallback).
_LON_NAMES = ["lon", "longitude", "rlon", "x", "east"]
_LAT_NAMES = ["lat", "latitude", "rlat", "y", "north"]

# Colour scales offered in the selector. Each value is (scale, reverse) where scale is
# a Plotly named scale (str) or explicit [fraction, colour] stops, and reverse flips the
# direction. All named scales are shown **reversed**; the light-gray -> dark-blue default
# is kept in its natural (gray -> blue) direction. Insertion order = dropdown order.
_GRAY_BLUE = [[0.0, "#e8e8e8"], [0.5, "#4292c6"], [1.0, "#08306b"]]
_COLORSCALES = {
    "Light gray → dark blue": (_GRAY_BLUE, False),
    "Viridis": ("Viridis", True),
    "Blues": ("Blues", True),
    "Cividis": ("Cividis", True),
    "YlGnBu": ("YlGnBu", True),
    "Turbo": ("Turbo", True),
    "Greys": ("Greys", True),
    "Jet": ("Jet", True),
    # Diverging (used by the A−B difference map: blue = negative, red = positive).
    "RdBu (diff)": ("RdBu", True),
}
_DEFAULT_COLORSCALE = "Light gray → dark blue"

# Play-speed selector: per-frame duration (ms) used by the plot's ▶ Play button.
# Insertion order = dropdown order.
_PLAY_SPEEDS = {
    "Slow": 1000,
    "Normal": 400,
    "Fast": 150,
    "Very fast": 40,
}
_DEFAULT_PLAY_SPEED = "Normal"


# Raw time-axis values at/above this magnitude are treated as fill values (the
# netCDF default fill for float64 is ~9.97e36). A killed/stopped CWatM run leaves
# the trailing, never-written time steps at the fill value, which makes xarray's
# time decoding fail with OutOfBounds/OverflowError ("unable to decode time
# units ... or installing cftime").
_TIME_FILL_LIMIT = 1e30


def _open_dataset_safe(path):
    """``xr.open_dataset`` that survives fill values in the time axis.

    First try the normal decoded open. If time decoding fails, re-open with
    ``decode_times=False``, drop the unwritten (fill-valued) time steps and
    decode the remaining, valid time axis with ``xr.decode_cf``. As a last
    resort the dataset is returned with raw numeric times (still plottable)."""
    try:
        return xr.open_dataset(path, decode_times=True, mask_and_scale=True)
    except Exception:
        pass  # fall through to the tolerant path below
    ds = xr.open_dataset(path, decode_times=False, mask_and_scale=True)
    try:
        for name, var in list(ds.variables.items()):
            if var.ndim != 1 or "since" not in str(var.attrs.get("units", "")):
                continue  # only 1-D CF time-like variables ("<unit> since <date>")
            vals = np.asarray(var.values, dtype="float64")
            bad = ~np.isfinite(vals) | (np.abs(vals) >= _TIME_FILL_LIMIT)
            fill = var.attrs.get("_FillValue")
            if fill is not None:
                try:
                    bad |= vals == float(fill)
                except Exception:
                    pass
            if bad.any() and not bad.all():
                # Keep only the written time steps (usually the leading ones).
                ds = ds.isel({var.dims[0]: np.nonzero(~bad)[0]})
        return xr.decode_cf(ds)
    except Exception:
        return ds  # undecoded times (raw numbers) - degrade gracefully


class NetcdfDataBase(GeometryMemoryMixin, QDialog):
    """Window showing a NetCDF variable as an EPSG:4326 heatmap with a time slider."""

    def _load(self, path):
        """Open the dataset, choose a data variable and return
        (varname, lons, lats, frames, time_labels, zmin, zmax, settings_title) where
        ``frames`` is a list of 2-D (lat, lon) arrays - one per time step - with the
        latitude axis ascending (south -> north)."""
        ds = _open_dataset_safe(path)
        try:
            lon_name = self._guess_coord(ds, _LON_NAMES)
            lat_name = self._guess_coord(ds, _LAT_NAMES)
            if not lon_name or not lat_name:
                raise ValueError("Could not find longitude/latitude coordinates in the file.")

            varname = self._pick_data_var(ds, lat_name, lon_name)
            if varname is None:
                raise ValueError("The file has no plottable data variable.")
            da = ds[varname]

            # Reduce any extra, non-time dimensions to their first index (remembered
            # so the lazy point re-read applies the same selection).
            time_name = self._guess_time(da, lat_name, lon_name)
            extra_sel = {}
            for d in list(da.dims):
                if d in (lat_name, lon_name, time_name):
                    continue
                da = da.isel({d: 0})
                extra_sel[d] = 0

            lon_vals = np.asarray(ds[lon_name].values, dtype="float64")
            lat_vals = np.asarray(ds[lat_name].values, dtype="float64")

            # Ascending latitude so the map is north-up (NetCDF often stores it
            # descending). We reorder both the axis and the data accordingly.
            lat_ascending = lat_vals[0] <= lat_vals[-1]

            def _grid(arr2d):
                # float32 halves the build-time memory; plenty for a colour map.
                arr2d = np.asarray(arr2d, dtype="float32")
                if not lat_ascending:
                    arr2d = arr2d[::-1, :]
                return arr2d

            lats_plot = lat_vals if lat_ascending else lat_vals[::-1]

            # Build the frames one timestep at a time from the lazily-read dataset,
            # tracking zmin/zmax incrementally (no full-copy concatenate). The frame
            # list itself is released after rendering (see _show_map, report §3.4).
            frames = []
            time_labels = []
            zmin, zmax = math.inf, -math.inf
            # Full date labels for every timestep (used by "Total Timeseries", which
            # plots the whole series - not just the strided map-animation frames).
            point_time_labels = [""]
            time_indices = []   # strided frame indices (used by "Fast Display Timeserie")
            if time_name and time_name in da.dims:
                ntime = da.sizes[time_name]
                # The map animation caps the number of frames (stride), but the point
                # time-series must stay full-resolution, so keep every date label here.
                stride = max(1, int(math.ceil(ntime / _MAX_FRAMES)))
                time_indices = list(range(0, ntime, stride))
                tvals = ds[time_name].values
                point_time_labels = [self._fmt_time(tvals[i]) for i in range(ntime)]
                for i in time_indices:
                    layer = _grid(da.isel({time_name: i})
                                  .transpose(lat_name, lon_name).values)
                    frames.append(layer)
                    time_labels.append(self._fmt_time(tvals[i]))
                    finite = layer[np.isfinite(layer)]
                    if finite.size:
                        zmin = min(zmin, float(finite.min()))
                        zmax = max(zmax, float(finite.max()))
            else:
                layer = _grid(da.transpose(lat_name, lon_name).values)
                frames.append(layer)
                time_labels.append("")
                finite = layer[np.isfinite(layer)]
                if finite.size:
                    zmin, zmax = float(finite.min()), float(finite.max())
            if not (zmin <= zmax):
                raise ValueError("The selected variable has no valid (non-NaN) values.")

            # Everything the timeserie plots need to re-read a cell's series lazily from
            # the file after the frames are released. "Total Timeseries" reads EVERY
            # timestep (full_time_labels); "Fast Display Timeserie" reads only the
            # strided map-animation frames (time_indices / time_labels) - fast, with gaps.
            self._point_source = dict(
                path=path, varname=varname, lat_name=lat_name, lon_name=lon_name,
                time_name=time_name, extra_sel=extra_sel,
                lat_ascending=lat_ascending, full_time_labels=point_time_labels,
                time_indices=time_indices)

            settings_title = self._read_settings_title(ds)
            return (varname, lon_vals, lats_plot, frames, time_labels,
                    zmin, zmax, settings_title)
        finally:
            try:
                ds.close()
            except Exception:
                pass

    @staticmethod
    def _fmt_time(v):
        """Human-readable time-step label (date for datetime64, else str)."""
        try:
            import pandas as pd
            if np.issubdtype(np.asarray(v).dtype, np.datetime64):
                return str(pd.to_datetime(v).date())
        except Exception:
            pass
        return str(v)

    def _guess_coord(self, ds, names):
        keys = list(ds.coords) + list(ds.variables)
        for want in names:
            for k in keys:
                if k.lower() == want:
                    return k
        for k in keys:
            lk = k.lower()
            if any(want in lk for want in names):
                return k
        return None

    def _guess_time(self, da, lat_name, lon_name):
        """Name of the time-like dimension of ``da`` (the remaining dim once lat/lon are
        removed, preferring one literally called 'time'); '' if there is none."""
        for d in da.dims:
            if d.lower() == "time":
                return d
        others = [d for d in da.dims if d not in (lat_name, lon_name)]
        return others[0] if others else ""

    def _pick_data_var(self, ds, lat_name, lon_name):
        """The data variable spanning lat & lon with the most cells; ignore obvious
        coordinate/bounds/crs helper variables."""
        best, best_size = None, -1
        for name, da in ds.data_vars.items():
            lname = name.lower()
            if lname.endswith("_bnds") or lname.endswith("_bounds") or "crs" in lname:
                continue
            if lat_name in da.dims and lon_name in da.dims and da.size > best_size:
                best, best_size = name, da.size
        if best is not None:
            return best
        return next(iter(ds.data_vars), None)

    # ------------------------------------------------ meta / settings title
    @staticmethod
    def _lookup_meta(varname):
        """(unit, long_name, description) for varname from the process-wide cached
        metaNetcdf.xml lookup (src/gui/utils/meta_netcdf.py - parsed once, not per
        window open). Missing values come back as empty strings."""
        from src.gui.utils.meta_netcdf import get_meta
        return get_meta(varname) or ("", "", "")

    def _title_from_settings_content(self, content):
        """Extract the 'Title' value from settings-file content, or '' if absent."""
        for line in (content or "").split("\n"):
            s = line.strip()
            if s.startswith("#") or s.startswith(";") or "=" not in s:
                continue
            key, value = s.split("=", 1)
            if key.strip().lower() == "title":
                return value.strip()
        return ""

    def _read_settings_title(self, ds):
        """The settings-file 'Title': read from the CWatM 'version_settingsfile' global
        attribute (which stores the settings content); fall back to the settings
        currently loaded in the main window. Empty string if neither is available."""
        try:
            content = ds.attrs.get("version_settingsfile", "")
            if content:
                t = self._title_from_settings_content(content)
                if t:
                    return t
        except Exception:
            pass
        try:
            mw = self.parent()
            if mw is not None and hasattr(mw, "original_content"):
                t = self._title_from_settings_content(mw.original_content or "")
                if t:
                    return t
        except Exception:
            pass
        return ""

    # ----------------------------------------------------------------- UI
    def _point_series(self, lati, loni, full=True):
        """Read one cell's series lazily from the file (the in-memory frame grids are
        released after rendering - report §3.4). ``lati`` indexes the ascending
        self.lats axis; it is mapped back to the file's latitude order. NaN cells come
        back as None. ``full=True`` reads **every** timestep (Total Timeseries);
        ``full=False`` reads only the strided map-animation frames (Fast Display
        Timeserie - fast, with gaps, and aligned with ``time_labels``)."""
        src = self._point_source
        ds = _open_dataset_safe(src["path"])
        try:
            da = ds[src["varname"]]
            for d, i in src["extra_sel"].items():
                da = da.isel({d: i})
            file_lat = (lati if src["lat_ascending"]
                        else da.sizes[src["lat_name"]] - 1 - lati)
            cell = da.isel({src["lat_name"]: file_lat, src["lon_name"]: loni})
            if not full and src["time_name"] and src["time_name"] in cell.dims:
                # Fast: only the strided timesteps (far fewer reads on a big file).
                cell = cell.isel({src["time_name"]: src["time_indices"]})
            vals = np.asarray(cell.values, dtype="float64").ravel()
            return [float(v) if np.isfinite(v) else None for v in vals]
        finally:
            try:
                ds.close()
            except Exception:
                pass
