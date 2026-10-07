"""File > Load shape (Show Basin + NetCDF): the shared reader must give a dict
json.dumps accepts - a dbf date field used to come through as datetime.date and
crash the overlay with "Object of type date is not JSON serializable"."""

import datetime
import json

import pytest

shapefile = pytest.importorskip("shapefile")

from src.gui.widgets.basin_viewer2 import _read_shapefile  # noqa: E402


def test_date_and_numeric_attributes_are_json_safe(tmp_path):
    path = str(tmp_path / "gauges.shp")
    w = shapefile.Writer(path, shapeType=shapefile.POINT)
    w.field("NAME", "C")
    w.field("SINCE", "D")
    w.field("AREA", "N", decimal=2)
    w.point(19.5, 47.2)
    w.record("Szeged", datetime.date(1990, 1, 1), 1234.5)
    w.close()

    obj = _read_shapefile(path)
    json.dumps(obj)    # must not raise
    props = obj["features"][0]["properties"]
    assert props["NAME"] == "Szeged"
    assert props["SINCE"] == "1990-01-01"
    assert props["AREA"] == pytest.approx(1234.5)
    assert obj["features"][0]["geometry"]["type"] == "Point"
