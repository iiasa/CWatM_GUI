"""Info ▸ World Map (`src/gui/widgets/world_map_window.py`) - the pure parts.

The circle size must grow with the number of runs (and stop growing), the circles
must be drawn biggest-first so small ones stay visible, bad rows must be dropped, and
the page must use the Preferences basemap through the osmtile:// WMS proxy.
"""

import json
import re

import pytest

from src.gui.widgets import world_map_window as W


class TestCircleRadius:
    def test_documented_values(self):
        assert [round(W.circle_radius(n)) for n in (1, 4, 25, 100)] == [7, 10, 19, 34]

    def test_more_runs_bigger_circle(self):
        radii = [W.circle_radius(n) for n in (1, 2, 5, 10, 50, 150)]
        assert radii == sorted(radii) and len(set(radii)) == len(radii)

    def test_capped(self):
        assert W.circle_radius(10 ** 6) == W.MAX_RADIUS

    def test_zero_or_bad_counts_as_one(self):
        assert W.circle_radius(0) == W.circle_radius(1)


class TestCircleData:
    def test_biggest_first_and_bad_rows_dropped(self):
        rows = W.circle_data([
            {"lon": 17.253, "lat": 48.607, "runs": 3},
            {"lon": -60.0, "lat": -3.1, "runs": 40},
            {"lon": 200, "lat": 10, "runs": 5},          # impossible longitude
            {"lon": 10, "lat": 50, "runs": 0},           # nothing to show
            {"lat": 50, "runs": 2},                      # incomplete
        ])
        assert [r[3] for r in rows] == [40, 3]           # runs, biggest first
        assert rows[1][:2] == [48.607, 17.253]           # [lat, lon] for Leaflet
        assert rows[0][2] > rows[1][2]                   # bigger radius

    def test_empty(self):
        assert W.circle_data([]) == []


folium = pytest.importorskip("folium")


def test_page_uses_the_preferences_basemap_and_the_data(monkeypatch):
    # no network in tests: skip the CDN inlining
    import src.gui.widgets.basin_viewer2 as b2
    monkeypatch.setattr(b2, "_inline_remote_assets", lambda html: html)
    html = W.build_world_map_html([{"lon": 17.253, "lat": 48.607, "runs": 3}],
                                  [{"lon": 16.36, "lat": 48.07, "users": 2}],
                                  "TOPO-OSM-WMS", mode="users")
    assert "osmtile://wms/service" in html
    assert '"TOPO-OSM-WMS"' in html
    runs = json.loads(re.search(r"layer\((\[\[.*?\]\]),", html).group(1))
    assert runs == [[48.607, 17.253, round(W.circle_radius(3), 1), 3]]
    users = json.loads(re.search(r"users: layer\((\[\[.*?\]\]),", html).group(1))
    assert users == [[48.07, 16.36, round(W.circle_radius(2), 1), 2]]
    assert W.RUNS_FILL in html and W.USERS_FILL in html
    assert 'window.setMode("users")' in html                # the first view
    assert "var N=80, S=-60;" in html                       # 80N..60S only


def test_users_are_counted_by_their_own_key():
    rows = W.circle_data([{"lon": 16.36, "lat": 48.07, "users": 4},
                          {"lon": 16.36, "lat": 48.07, "runs": 9}], key="users")
    assert [r[3] for r in rows] == [4]                      # the runs row has no users


def test_first_map_size_fits_the_world_from_90n_to_60s():
    # Leaflet EPSG:4326, zoom 1: 1024 px for 360 deg -> 2.844 px per degree
    px_per_deg = 1024 / 360
    assert W.MAP_W == round(360 * px_per_deg)
    assert W.MAP_H == round((90 - -60) * px_per_deg)


def test_both_modes_have_texts():
    for spec in W.MODES.values():
        assert spec["title"] and "{places}" in spec["info"] and "{count}" in spec["info"]
