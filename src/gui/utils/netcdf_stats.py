"""Statistics over the time axis of a NetCDF variable (Analyse ▸ NetCDF ▸ Action ▸
Calculate mean / Calculate percentile).

``compute_statistic`` reads the variable the NetCDF viewer shows, reduces it over
time (mean, or a percentile) and writes a new NetCDF holding one map. The result
keeps **all metadata of the original** - every global attribute and the variable's
attributes - and adds where it came from: ``source_file`` (name), ``source_folder``
(location), ``source_file_created`` / ``source_file_modified`` (the original file's
times), ``source_time_range``, ``statistic`` and ``created``, plus a ``history`` line.

Pure (no Qt), so it runs on a worker thread and is tested on its own. xarray is
imported inside the functions: this module is imported by the viewer, never on the
GUI's startup path, but it stays cheap to import anyway.
"""

import datetime as _dt
import os

from src.gui.utils.gui_log import get_logger

log = get_logger("netcdf_stats")

GUI_NAME = "CWatM GUI"


def default_name(varname, statistic, percentile=None):
    """``discharge_mean.nc`` / ``discharge_50_percentile.nc``."""
    if statistic == "mean":
        return f"{varname}_mean.nc"
    return f"{varname}_{format_percentile(percentile)}_percentile.nc"


def format_percentile(p):
    """50 -> '50', 2.5 -> '2.5' (no trailing '.0')."""
    return f"{float(p):g}"


def _iso(ts):
    return _dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


def source_attributes(src_path, statistic_text, time_range=""):
    """The provenance attributes added to the result (pure - tested)."""
    src_path = os.path.abspath(src_path)
    attrs = {
        "source_file": os.path.basename(src_path),
        "source_folder": os.path.dirname(src_path),
        "statistic": statistic_text,
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "created_by": GUI_NAME,
    }
    try:
        st = os.stat(src_path)
        # Windows: st_ctime is the creation time; elsewhere the last metadata change
        attrs["source_file_created"] = _iso(st.st_ctime)
        attrs["source_file_modified"] = _iso(st.st_mtime)
    except OSError:
        log.debug("source file times unreadable", exc_info=True)
    if time_range:
        attrs["source_time_range"] = time_range
    return attrs


def compute_statistic(src_path, out_path, varname, lat_name, lon_name, time_name,
                      extra_sel=None, statistic="mean", percentile=None):
    """Reduce ``varname`` over ``time_name`` and write the one-map result to
    ``out_path``. ``statistic`` is "mean" or "percentile" (``percentile`` 0..100).
    ``extra_sel`` = the index selection the viewer applies to extra dimensions, so
    the result is the map the user was looking at. Returns ``out_path``."""
    import numpy as np
    import xarray as xr

    if os.path.abspath(src_path) == os.path.abspath(out_path):
        raise ValueError("The result cannot overwrite the original file.")
    if statistic == "percentile":
        if percentile is None or not 0 <= float(percentile) <= 100:
            raise ValueError("The percentile must be between 0 and 100.")

    # decode_times=False: the reduction does not need dates, and an axis with fill
    # values (unwritten steps) cannot fail the open; the range is decoded below.
    ds = xr.open_dataset(src_path, decode_times=False, chunks={})
    try:
        da = ds[varname]
        if extra_sel:
            da = da.isel({k: v for k, v in extra_sel.items() if k in da.dims})
        if not time_name or time_name not in da.dims:
            raise ValueError("The variable has no time dimension to reduce.")
        ntime = int(da.sizes[time_name])

        if statistic == "mean":
            result = da.mean(dim=time_name, skipna=True, keep_attrs=True)
            stat_text = f"mean over {time_name} ({ntime} timesteps)"
            method = f"{time_name}: mean"
        else:
            q = float(percentile) / 100.0
            # a quantile needs the whole time axis of a cell in one chunk
            chunked = da.chunk({time_name: -1})
            result = chunked.quantile(q, dim=time_name, skipna=True, keep_attrs=True)
            if "quantile" in result.coords:
                result = result.drop_vars("quantile")
            stat_text = (f"{format_percentile(percentile)}th percentile over "
                         f"{time_name} ({ntime} timesteps)")
            method = f"{time_name}: percentile {format_percentile(percentile)}"

        result = result.astype("float32")
        result.attrs = dict(da.attrs)
        prev = str(da.attrs.get("cell_methods", "")).strip()
        result.attrs["cell_methods"] = f"{prev} {method}".strip()
        result.name = varname

        out = result.to_dataset()
        # keep the lat/lon coordinate attributes (units, standard_name, ...)
        for c in (lat_name, lon_name):
            if c in ds.variables and c in out.coords:
                out[c].attrs = dict(ds[c].attrs)

        time_range = _time_range_text(ds, time_name)
        out.attrs = dict(ds.attrs)                     # all original metadata
        out.attrs.update(source_attributes(src_path, stat_text, time_range))
        line = (f"{out.attrs['created']}: {GUI_NAME} - {stat_text} of "
                f"{os.path.basename(src_path)}")
        history = str(ds.attrs.get("history", "")).strip()
        out.attrs["history"] = f"{line}\n{history}" if history else line

        encoding = {varname: {"zlib": True, "complevel": 4,
                              "_FillValue": np.float32(1e20)}}
        out.to_netcdf(out_path, encoding=encoding)
    finally:
        ds.close()
    return out_path


def _time_range_text(ds, time_name):
    """'2000-01-01 to 2010-12-31' from the (undecoded) time axis, or ''."""
    if time_name not in ds.variables:
        return ""
    try:
        import xarray as xr
        decoded = xr.decode_cf(ds[[time_name]])[time_name].values
        first, last = decoded[0], decoded[-1]
        return f"{str(first)[:10]} to {str(last)[:10]}"
    except Exception:
        try:
            vals = ds[time_name].values
            units = ds[time_name].attrs.get("units", "")
            return f"{vals[0]} to {vals[-1]} {units}".strip()
        except Exception:
            return ""
