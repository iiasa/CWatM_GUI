"""
Analyse ▸ NetCDF ▸ Action ▸ Save as a .tif - write the map currently shown (one
timestep) as a single-band GeoTIFF.

Pure logic, no Qt. rasterio / xarray are imported inside the functions (the
fast-startup rule: nothing heavy at module level).
"""

import os
import re

import numpy as np

from src.gui.utils.gui_log import get_logger

log = get_logger("netcdf_tif")

_DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


def date_suffix(label):
    """'1992-08-01' (or a cftime '1992-08-01 00:00:00') -> '01081992' (ddmmyyyy).
    A label that is not a date gives a filename-safe version of it, '' gives ''."""
    label = str(label or "").strip()
    if not label:
        return ""
    m = _DATE_RE.search(label)
    if m:
        y, mo, d = m.groups()
        return f"{int(d):02d}{int(mo):02d}{y}"
    return re.sub(r"[^\w.-]+", "_", label).strip("_")


def tif_name(nc_path, label):
    """<netcdf name without .nc>_<ddmmyyyy>.tif, e.g.
    modflow_watertable_monthavg_01081992.tif"""
    base = os.path.splitext(os.path.basename(nc_path))[0]
    suffix = date_suffix(label)
    return f"{base}_{suffix}.tif" if suffix else f"{base}.tif"


def file_crs_wkt(nc_path):
    """The CRS stored in the NetCDF (a grid-mapping variable's ``crs_wkt`` /
    ``spatial_ref``), or None. Best-effort - any read error gives None."""
    try:
        import xarray as xr
        with xr.open_dataset(nc_path, decode_times=False) as ds:
            for name in list(ds.variables):
                attrs = ds[name].attrs
                for key in ("crs_wkt", "spatial_ref"):
                    wkt = attrs.get(key)
                    if isinstance(wkt, str) and wkt.strip():
                        return wkt
    except Exception:
        log.debug("file_crs_wkt: could not read the CRS", exc_info=True)
    return None


def write_geotiff(path, frame, lons, lats, crs=None):
    """Write ``frame`` (2-D, rows = ``lats``, cols = ``lons``; any axis order) as a
    float32 GeoTIFF with north-up rows and NaN as nodata. ``lons``/``lats`` are the
    cell centres (regular grid)."""
    import rasterio
    from rasterio.transform import from_origin

    data = np.asarray(frame, dtype="float32")
    lons = np.asarray(lons, dtype="float64")
    lats = np.asarray(lats, dtype="float64")
    if data.shape != (lats.size, lons.size):
        raise ValueError("Map shape %s does not match the coordinates (%d x %d)."
                         % (data.shape, lats.size, lons.size))
    if lons.size > 1 and lons[0] > lons[-1]:
        lons, data = lons[::-1], data[:, ::-1]
    if lats.size > 1 and lats[0] < lats[-1]:      # GeoTIFF row 0 = north
        lats, data = lats[::-1], data[::-1, :]
    dx = abs(lons[1] - lons[0]) if lons.size > 1 else 1.0
    dy = abs(lats[0] - lats[1]) if lats.size > 1 else dx
    transform = from_origin(lons[0] - dx / 2.0, lats[0] + dy / 2.0, dx, dy)
    with rasterio.open(path, "w", driver="GTiff", height=data.shape[0],
                       width=data.shape[1], count=1, dtype="float32",
                       crs=crs, transform=transform, nodata=np.nan,
                       compress="deflate") as dst:
        dst.write(np.ascontiguousarray(data), 1)
