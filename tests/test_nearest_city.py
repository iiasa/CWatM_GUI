"""Nearest-city label next to a station's lon/lat (src/gui/utils/nearest_city.py)."""

from src.gui.utils import nearest_city as nc


def test_city_in_its_own_centre():
    name, country, dist = nc.nearest_city(16.37208, 48.20849)
    assert (name, country) == ("Vienna", "AT")
    assert dist < 0.01
    assert nc.city_label(16.37208, 48.20849) == "< 1 km from Vienna (AT)"


def test_distance_in_km_and_string_input():
    # CWatM writes xloc/yloc as text; ~26 km from Breclav
    label = nc.city_label("16.6084", "48.9083")
    assert label.endswith("km from Břeclav (CZ)")
    assert 20 <= int(label.split()[0]) <= 30


def test_projected_station_gets_no_city():
    assert nc.city_label(114481.0, 6897523.0) == ""     # UTM metres
    assert nc.city_label("x", "1") == ""
    assert nc.city_label(None, None) == ""


def test_longitude_0_to_360():
    assert nc.as_lonlat(350.0, 10.0) == (-10.0, 10.0)
