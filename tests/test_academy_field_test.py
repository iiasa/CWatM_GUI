"""CWatM Academy Level 1 Field Test: a random basin of all 100, graded
against its 4 biggest upstream cells on the bundled 30' grid."""

import random

import numpy as np
import pytest

pytestmark = pytest.mark.qt

from src.gui.widgets import academy_field_test as ft  # noqa: E402


@pytest.fixture(scope="module")
def grid(qapp):
    data, lats, lons = ft.load_ups_grid()
    assert data is not None
    return np.asarray(data, dtype=float), np.asarray(lats), np.asarray(lons)


def test_pool_is_all_100_basins():
    basins = ft.load_basins()
    assert len(basins) == 100
    assert all(b["rank"] <= 100 for b in basins)
    assert "Danube" in {b["name"] for b in basins}
    assert basins[0]["name"] == "Amazon"


def test_four_biggest_cells_for_every_basin(grid):
    data, lats, lons = grid
    for b in ft.load_basins():
        cells = ft.target_cells(data, lats, lons, b["lat"], b["lon"])
        assert len(cells) == 4, b["name"]
        assert cells[0] == (b["lat"], b["lon"]), b["name"]        # listed outlet
        vals = [data[ft._nearest_index(lats, lons, la, lo)] for la, lo in cells]
        assert vals[0] == pytest.approx(b["size_km2"], rel=1e-4), b["name"]
        assert all(vals[0] > v for v in vals[1:]), b["name"]
        # (a *neighbour* may still be larger - the Uruguay's outlet borders the
        # Parana / Rio de la Plata cells of a bigger basin - so the targets only
        # ever step to smaller neighbours, which drain into the outlet)


def test_grading_snaps_to_cells(grid):
    data, lats, lons = grid
    nile = next(b for b in ft.load_basins() if b["name"] == "Nile")
    targets = ft.target_cells(data, lats, lons, nile["lat"], nile["lon"])
    lat, lon = targets[1]
    assert ft.is_target(lats, lons, lat + 0.1, lon - 0.1, targets)   # same cell
    assert not ft.is_target(lats, lons, 0.0, 0.0, targets)


def test_distance_shrinks_longitude_with_latitude():
    assert ft.distance_km(0, 0, 0, 1) == pytest.approx(111.19, rel=1e-3)
    assert ft.distance_km(60, 0, 60, 1) == pytest.approx(111.19 / 2, rel=1e-2)
    assert ft.distance_km(0, 0, 1, 0) == pytest.approx(111.19, rel=1e-3)
    assert ft.distance_km(0, 179.5, 0, -179.5) == pytest.approx(111.19, rel=1e-3)


def test_a_miss_reports_the_distance(qapp):
    from PySide6.QtCore import QCoreApplication, QEvent
    win = ft.BasinFieldTestWindow()
    try:
        b = win._basin
        lat = b["lat"] + 10 if b["lat"] < 70 else b["lat"] - 10
        win._on_web_title(f"NILETEST {b['lon']}|{lat}|1")
        assert not win.confirm_button.isEnabled()
        assert "Not the outlet - you are 1,112 kilometers away." in \
            win.status_label.text()
    finally:
        win.close()
        if win.web_view is not None:
            win.web_view.setPage(None)
        win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        qapp.processEvents()


def test_view_contains_the_outlet_off_centre():
    b = dict(size_km2=2_904_390, lat=31.25, lon=31.25)
    rng = random.Random(3)
    for _ in range(20):
        (s, w), (n, e) = ft.view_bounds(b, rng)
        assert s < b["lat"] < n and w < b["lon"] < e


def test_window_picks_a_basin_and_grades(qapp):
    from PySide6.QtCore import QCoreApplication, QEvent
    win = ft.BasinFieldTestWindow()
    try:
        name = win._basin["name"]
        assert name in win.title_label.text()
        lat, lon = win._targets[0]
        win._on_web_title(f"NILETEST {lon}|{lat}|1")
        assert win.confirm_button.isEnabled()
        win._next_basin()
        assert win._basin["name"] != name and not win.confirm_button.isEnabled()
    finally:
        win.close()
        if win.web_view is not None:
            win.web_view.setPage(None)
        win.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        qapp.processEvents()
