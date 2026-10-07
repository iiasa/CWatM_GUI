import numpy as np
import pytest

from src.gui.utils import netcdf_tif


def test_date_suffix():
    assert netcdf_tif.date_suffix("1992-08-01") == "01081992"
    assert netcdf_tif.date_suffix("1992-08-01 00:00:00") == "01081992"
    assert netcdf_tif.date_suffix("") == ""
    assert netcdf_tif.date_suffix("step 3") == "step_3"


def test_tif_name():
    assert (netcdf_tif.tif_name(r"C:\out\modflow_watertable_monthavg.nc", "1992-08-01")
            == "modflow_watertable_monthavg_01081992.tif")
    assert netcdf_tif.tif_name("mean.nc", "") == "mean.tif"


def test_write_geotiff_north_up(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    lons = np.array([10.0, 10.5, 11.0])
    lats = np.array([45.0, 45.5])                 # ascending, as the viewer holds them
    frame = np.array([[1, 2, 3], [4, 5, np.nan]], dtype="float32")  # row 0 = south
    path = tmp_path / "x.tif"
    netcdf_tif.write_geotiff(str(path), frame, lons, lats, "EPSG:4326")
    with rasterio.open(path) as src:
        data = src.read(1)
        assert data[0, 0] == 4 and np.isnan(data[0, 2])     # row 0 = north
        assert data[1].tolist() == [1, 2, 3]
        assert src.bounds.left == pytest.approx(9.75)
        assert src.bounds.top == pytest.approx(45.75)
        assert src.crs.to_epsg() == 4326
