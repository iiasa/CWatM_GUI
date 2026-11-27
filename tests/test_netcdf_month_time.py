"""'Months since' / 'years since' time axes (older CWatM / ISIMIP output), which
xarray refuses outside a 360_day calendar - decoded by analysis_netcdf_base."""
import numpy as np
import pytest

xr = pytest.importorskip("xarray")

from src.gui.widgets.analysis_netcdf_base import (
    _decode_month_year_time, _open_dataset_safe)


def _d(s):
    return np.datetime64(s, "ns")


def test_months_since():
    out = _decode_month_year_time([0, 13, 1368, 0.5], "Months since 1901-01-01")
    assert list(out) == [_d("1901-01-01"), _d("1902-02-01"), _d("2015-01-01"),
                         _d("1901-01-16T12")]


def test_years_since_and_other_units():
    out = _decode_month_year_time([0, 2.5], "years since 2000-01-01")
    assert list(out) == [_d("2000-01-01"), _d("2002-07-01")]
    assert _decode_month_year_time([1], "days since 1901-01-01") is None
    assert _decode_month_year_time([1], None) is None


def test_open_dataset_safe_months(tmp_path):
    path = tmp_path / "isimip_monthavg.nc"
    ds = xr.Dataset(
        {"discharge": (("time", "lat", "lon"), np.ones((3, 2, 2)))},
        coords={"time": ("time", [1368.0, 1369.0, 1370.0],
                         {"units": "Months since 1901-01-01",
                          "calendar": "proleptic_gregorian"}),
                "lat": [48.0, 48.5], "lon": [17.0, 17.5]})
    ds.to_netcdf(path, encoding={"time": {"dtype": "float64"}})
    for chunks in (None, {}):
        opened = _open_dataset_safe(str(path), chunks=chunks)
        assert np.issubdtype(opened.time.dtype, np.datetime64)
        assert opened.time.values[0] == _d("2015-01-01")
        assert opened.time.values[-1] == _d("2015-03-01")
        opened.close()
