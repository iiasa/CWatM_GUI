"""NetCDF ▸ point popup ▸ Make all points to gauges: which points of a loaded
shape/GeoJSON are used."""

import pytest

pytest.importorskip("PySide6.QtWebEngineWidgets")

from src.gui.widgets.analysis_netcdf import _geojson_points  # noqa: E402


def test_points_and_multipoints_in_file_order_other_geometries_ignored():
    obj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [18, 46]}},
        {"type": "Feature", "geometry": {"type": "Polygon",
                                         "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}},
        {"type": "Feature", "geometry": {"type": "MultiPoint",
                                         "coordinates": [[19, 47], [20.5, 45.5]]}},
        {"type": "Feature", "geometry": {"type": "GeometryCollection", "geometries": [
            {"type": "Point", "coordinates": [21, 44, 100]}]}},
        {"type": "Feature", "geometry": None},
    ]}
    assert _geojson_points(obj) == [(18.0, 46.0), (19.0, 47.0), (20.5, 45.5), (21.0, 44.0)]


def test_single_feature_bare_geometry_and_junk():
    assert _geojson_points({"type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [1, 2]}}) == [(1.0, 2.0)]
    assert _geojson_points({"type": "Point", "coordinates": [3, 4]}) == [(3.0, 4.0)]
    assert _geojson_points({"type": "Point", "coordinates": ["x"]}) == []
    assert _geojson_points(None) == []
