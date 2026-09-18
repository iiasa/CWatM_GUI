"""GeoJSON/shapefile readers shared by Show Basin's and NetCDF's File > Load JSON /
Load shape (`basin_viewer2._read_geojson_file` / `_read_shapefile`).

Both feed the same `window.addGeoJson` JS helper, so the contract that matters is:
a well-formed GeoJSON ``FeatureCollection`` dict, geometry + properties intact.
`_read_shapefile` is also the regression test for the ``pyshp`` dependency added
this session - a broken/missing pyshp install would fail here first.
"""

import json

import pytest

from src.gui.widgets.basin_viewer2 import _read_geojson_file, _read_shapefile

# Needs Qt: basin_viewer2 imports PySide6.QtWidgets at module level.
pytestmark = pytest.mark.qt


class TestReadGeojsonFile:
    def test_reads_a_feature_collection(self, tmp_path):
        obj = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point",
             "coordinates": [10.0, 50.0]}, "properties": {"name": "x"}}]}
        path = tmp_path / "test.geojson"
        path.write_text(json.dumps(obj), encoding="utf-8")
        result = _read_geojson_file(str(path))
        assert result == obj

    def test_bad_json_raises(self, tmp_path):
        path = tmp_path / "bad.geojson"
        path.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(Exception):
            _read_geojson_file(str(path))

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(Exception):
            _read_geojson_file(str(tmp_path / "does_not_exist.geojson"))


class TestReadShapefile:
    def _write_polygon_shapefile(self, tmp_path, name="test"):
        shapefile = pytest.importorskip("shapefile")
        path = str(tmp_path / name)
        w = shapefile.Writer(path, shapeType=shapefile.POLYGON)
        w.field("name", "C")
        w.field("value", "N")
        # Counter-clockwise ring = exterior ring in shapefile convention.
        w.poly([[[10.0, 50.0], [10.0, 50.1], [10.1, 50.1], [10.1, 50.0], [10.0, 50.0]]])
        w.record("basin1", 42)
        w.close()
        return path

    def _write_point_shapefile(self, tmp_path, name="pts"):
        shapefile = pytest.importorskip("shapefile")
        path = str(tmp_path / name)
        w = shapefile.Writer(path, shapeType=shapefile.POINT)
        w.field("label", "C")
        w.point(10.5, 50.5)
        w.record("gauge1")
        w.close()
        return path

    def test_reads_a_polygon_as_a_feature_collection(self, tmp_path):
        path = self._write_polygon_shapefile(tmp_path)
        obj = _read_shapefile(path)
        assert obj["type"] == "FeatureCollection"
        assert len(obj["features"]) == 1
        feature = obj["features"][0]
        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] == "Polygon"
        assert feature["properties"] == {"name": "basin1", "value": 42}

    def test_polygon_geometry_has_five_coordinate_pairs(self, tmp_path):
        path = self._write_polygon_shapefile(tmp_path)
        obj = _read_shapefile(path)
        ring = obj["features"][0]["geometry"]["coordinates"][0]
        assert len(ring) == 5           # closed ring: first point repeated last
        assert ring[0] == ring[-1]

    def test_reads_points(self, tmp_path):
        path = self._write_point_shapefile(tmp_path)
        obj = _read_shapefile(path)
        feature = obj["features"][0]
        assert feature["geometry"]["type"] == "Point"
        assert feature["geometry"]["coordinates"] == pytest.approx((10.5, 50.5))
        assert feature["properties"] == {"label": "gauge1"}

    def test_result_is_json_serialisable(self, tmp_path):
        # The result is handed to json.dumps() before going into the page's JS -
        # pyshp's tuples/records must not break that.
        path = self._write_polygon_shapefile(tmp_path)
        obj = _read_shapefile(path)
        json.dumps(obj)     # must not raise

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(Exception):
            _read_shapefile(str(tmp_path / "does_not_exist.shp"))
