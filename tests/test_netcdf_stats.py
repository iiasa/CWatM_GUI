"""Analyse ▸ NetCDF ▸ Calculate mean / Calculate percentile (``netcdf_stats``): the
values, the suggested names, and that the original metadata plus the source's
name / location / times end up in the result."""

import os

import numpy as np
import pytest

xr = pytest.importorskip("xarray")

from src.gui.utils import netcdf_stats  # noqa: E402


@pytest.fixture
def src(tmp_path):
    rng = np.random.default_rng(1)
    data = rng.random((12, 3, 4)).astype("float32") * 100
    data[0, 0, 0] = np.nan                                    # a gap is skipped
    ds = xr.Dataset(
        {"discharge": (("time", "lat", "lon"), data,
                       {"units": "m3/s", "long_name": "discharge"})},
        coords={"time": np.arange(12), "lat": [48.0, 47.5, 47.0],
                "lon": [10.0, 10.5, 11.0, 11.5]})
    ds["time"].attrs["units"] = "days since 2000-01-01"
    ds["lat"].attrs["units"] = "degrees_north"
    ds.attrs.update({"title": "Morava run", "institution": "IIASA",
                     "history": "created by CWatM"})
    path = tmp_path / "discharge_daily.nc"
    ds.to_netcdf(path)
    return str(path), data


def _run(src_path, out, **kw):
    return netcdf_stats.compute_statistic(
        src_path, str(out), "discharge", "lat", "lon", "time", **kw)


def test_default_names():
    assert netcdf_stats.default_name("discharge", "mean") == "discharge_mean.nc"
    assert (netcdf_stats.default_name("discharge", "percentile", 50.0)
            == "discharge_50_percentile.nc")
    assert (netcdf_stats.default_name("discharge", "percentile", 2.5)
            == "discharge_2.5_percentile.nc")


def test_mean_values_and_metadata(src, tmp_path):
    path, data = src
    out = _run(path, tmp_path / "discharge_mean.nc")
    with xr.open_dataset(out) as ds:
        res = ds["discharge"].values
        assert res.shape == (3, 4)                           # one map, no time
        assert np.allclose(res, np.nanmean(data, axis=0), rtol=1e-5)
        # all original metadata kept
        assert ds.attrs["title"] == "Morava run"
        assert ds.attrs["institution"] == "IIASA"
        assert ds["discharge"].attrs["units"] == "m3/s"
        assert ds["discharge"].attrs["cell_methods"] == "time: mean"
        assert ds["lat"].attrs["units"] == "degrees_north"
        # + where it came from
        assert ds.attrs["source_file"] == "discharge_daily.nc"
        assert ds.attrs["source_folder"] == os.path.dirname(os.path.abspath(path))
        assert "source_file_created" in ds.attrs
        assert "source_file_modified" in ds.attrs
        assert ds.attrs["source_time_range"] == "2000-01-01 to 2000-01-12"
        assert ds.attrs["statistic"].startswith("mean over time (12 timesteps)")
        assert ds.attrs["history"].endswith("created by CWatM")


def test_percentile(src, tmp_path):
    path, data = src
    out = _run(path, tmp_path / "p.nc", statistic="percentile", percentile=90)
    with xr.open_dataset(out) as ds:
        assert np.allclose(ds["discharge"].values,
                           np.nanpercentile(data, 90, axis=0), rtol=1e-4)
        assert "quantile" not in ds.coords
        assert ds["discharge"].attrs["cell_methods"] == "time: percentile 90"
        assert ds.attrs["statistic"].startswith("90th percentile")


def test_refuses_to_overwrite_the_original(src):
    path, _data = src
    with pytest.raises(ValueError):
        _run(path, path)


def test_bad_percentile(src, tmp_path):
    path, _data = src
    with pytest.raises(ValueError):
        _run(path, tmp_path / "x.nc", statistic="percentile", percentile=150)


@pytest.mark.qt
def test_viewer_shows_the_result_instead(src, tmp_path, qapp):
    """The window swaps to the calculated map in place: one frame, the new file,
    the time controls and time-based actions gone."""
    from src.gui.widgets.analysis_netcdf import NetcdfWindow
    path, _data = src
    win = NetcdfWindow(path)
    try:
        assert win._multi and win.mean_action.isVisible()
        out = _run(path, tmp_path / "discharge_mean.nc")
        win._show_file(out)
        assert win.nc_path == out
        assert len(win.frames) == 1 and not win._multi
        assert not win.mean_action.isVisible()
        assert not win.ts_action.isVisible()
        assert "discharge_mean.nc" in win.header_label.text()
    finally:
        # dispose inside the test (not at interpreter exit, where tearing down a
        # QWebEngineView crashes the process) - same rule as test_account_ui._dispose
        from PySide6.QtCore import QCoreApplication, QEvent
        win.close()
        win.web_view.setPage(None)
        win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        qapp.processEvents()


@pytest.mark.qt
def test_load_netcdf_other_grid(src, tmp_path, qapp):
    """File ▸ Load netcdf is the first File item; a file on another grid (with a
    time axis) replaces the shown one and rebuilds the map page."""
    from PySide6.QtCore import QCoreApplication, QEvent
    from src.gui.widgets.analysis_netcdf import NetcdfWindow
    path, _data = src
    other = tmp_path / "runoff.nc"
    xr.Dataset(
        {"runoff": (("time", "lat", "lon"),
                    np.ones((5, 2, 2), dtype="float32"))},
        coords={"time": np.arange(5), "lat": [40.0, 39.0], "lon": [5.0, 6.0]}
    ).to_netcdf(other)
    win = NetcdfWindow(path)
    try:
        file_menu = win._menus[0]
        assert file_menu.title() == "File"
        assert file_menu.actions()[0].text() == "Load netcdf"
        win._show_file(str(other))
        assert win.varname == "runoff"
        assert list(win.lons) == [5.0, 6.0]
        assert len(win.frames) == 5 and win._multi
        assert win.ts_action.isVisible() and win.mean_action.isVisible()
    finally:
        win.close()
        win.web_view.setPage(None)
        win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        qapp.processEvents()
