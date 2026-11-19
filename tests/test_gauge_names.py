"""Gauge names (GaugesNames) for the gauge tooltips of Show Basin and Analyse ▸
NetCDF, and the NetCDF global attributes Gauges / GaugesNames. Pure parts only."""

import pytest

pytestmark = pytest.mark.qt          # basin_viewer imports PySide6

from src.gui.widgets.basin_viewer import (  # noqa: E402
    gauge_names, gauge_names_from_pairs, gauge_name_at)

INI = """[FILE_PATHS]
PathRoot = .
[MASK_OUTLET]
GaugesNames = outletMorava somewhere
Gauges = 16.9750 48.1916 16.8918 48.9396
"""


def test_names_are_paired_with_the_gauges_in_order():
    assert gauge_names(INI) == {(16.975, 48.1916): "outletMorava",
                                (16.8918, 48.9396): "somewhere"}


def test_like_cwatm_commas_too_and_missing_or_extra_names():
    # CWatM output.py: names split on blanks or commas; a gauge without a name stays
    # unnamed, a name without a gauge is ignored
    assert gauge_names_from_pairs("1 2 3 4", "a,b") == {(1.0, 2.0): "a", (3.0, 4.0): "b"}
    assert gauge_names_from_pairs("1 2 3 4", "a") == {(1.0, 2.0): "a"}
    assert gauge_names_from_pairs("1 2", "a b c") == {(1.0, 2.0): "a"}


def test_no_names_or_a_gauge_map_gives_nothing():
    assert gauge_names(INI.replace("GaugesNames = outletMorava somewhere\n", "")) == {}
    assert gauge_names_from_pairs("$(FILE_PATHS:PathRoot)/gauges.tif", "a b") == {}
    assert gauge_names("") == {}


def test_placeholders_are_resolved():
    ini = INI.replace("GaugesNames = outletMorava somewhere",
                      "GaugesNames = $(FILE_PATHS:Station) other") \
             .replace("PathRoot = .", "PathRoot = .\nStation = Moravsky_Jan")
    assert gauge_names(ini)[(16.975, 48.1916)] == "Moravsky_Jan"


def test_lookup_by_coordinates():
    names = gauge_names(INI)
    assert gauge_name_at(names, 16.975, 48.1916) == "outletMorava"
    assert gauge_name_at(names, 16.97504, 48.19158) == "outletMorava"   # rounding
    assert gauge_name_at(names, 16.9755, 48.1916) == "outletMorava"     # within 0.001
    assert gauge_name_at(names, 17.5, 49.0) == ""                       # another place
    assert gauge_name_at({}, 1, 2) == ""


def test_gauges_attribute_as_cwatm_writes_it():
    from src.gui.widgets.basin_viewer import parse_gauges_attribute
    text = "G1_outletMorava 48.1916 16.9750 26695.0; G2_somewhere 48.9396 16.8918 275.7"
    assert parse_gauges_attribute(text) == [(16.975, 48.1916, "outletMorava", 26695.0),
                                           (16.8918, 48.9396, "somewhere", 275.7)]


def test_gauges_attribute_without_names_or_area_and_with_junk():
    from src.gui.widgets.basin_viewer import parse_gauges_attribute
    # a plain G<n> has no name; a name may contain "_"; a missing area is None
    assert parse_gauges_attribute("G1 48.1 16.9 10.0; G12_upper_Morava 49.0 17.0") == [
        (16.9, 48.1, "", 10.0), (17.0, 49.0, "upper_Morava", None)]
    # an unreadable entry is skipped, the rest is kept
    assert parse_gauges_attribute("G1 x y 1; G2 48.0 16.0 5") == [(16.0, 48.0, "", 5.0)]
    assert parse_gauges_attribute("") == []
    assert parse_gauges_attribute(None) == []


def test_global_attribute_any_case():
    from types import SimpleNamespace
    from src.gui.widgets.analysis_netcdf_base import _global_attr
    ds = SimpleNamespace(attrs={"gauges": " 16.975 48.1916 ", "GaugesNames": "outlet"})
    assert _global_attr(ds, "Gauges") == "16.975 48.1916"
    assert _global_attr(ds, "GaugesNames") == "outlet"
    assert _global_attr(ds, "Missing") == ""
