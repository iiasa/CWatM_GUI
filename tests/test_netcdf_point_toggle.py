"""Analyse ▸ NetCDF: a left click toggles a point (select / deselect), so several
stations are collected directly on the map. Driven on a bare NetcdfWindow (no web
page, no file): only the plain-Python selection logic runs."""

import numpy as np
import pytest

pytestmark = pytest.mark.qt

from PySide6.QtWidgets import QLabel  # noqa: E402


@pytest.fixture
def win(qapp):
    from src.gui.widgets.analysis_netcdf import NetcdfWindow
    w = NetcdfWindow.__new__(NetcdfWindow)      # skip __init__: no file, no page
    w.lons = np.array([10.0, 10.5, 11.0])
    w.lats = np.array([48.0, 47.5, 47.0])
    w.frames = [np.arange(9, dtype=float).reshape(3, 3)]
    w._ti = 0
    w._displayed_points = []
    w._clicked = None
    w._projected = False
    w.unit = "m3/s"
    w.time_labels = ["2020-01-01"]
    w.info_label = QLabel()
    w.js = []
    w.refreshed = []
    w._js = w.js.append
    w._open_or_refresh_timeseries = lambda **kw: w.refreshed.append(kw)
    yield w
    w.info_label.deleteLater()


def test_click_adds_then_same_cell_removes(win):
    win._on_web_title("NC2 10.02|47.98|1")
    assert win._displayed_points == [(10.0, 48.0)]
    assert win._clicked[:2] == (10.0, 48.0)
    assert win.refreshed[-1] == {"open_if_closed": False}   # open plot follows
    # the same cell again (another spot inside it, new nonce) -> removed
    win._on_web_title("NC2 9.99|48.01|2")
    assert win._displayed_points == []
    assert win._clicked is None
    assert win.info_label.text().startswith("Removed point")


def test_several_stations_and_removing_an_earlier_one(win):
    win._on_web_title("NC2 10.0|48.0|1")
    win._on_web_title("NC2 10.5|47.5|2")
    win._on_web_title("NC2 11.0|47.0|3")
    assert win._displayed_points == [(10.0, 48.0), (10.5, 47.5), (11.0, 47.0)]
    win._on_web_title("NC2 10.5|47.5|4")                    # an earlier one
    assert win._displayed_points == [(10.0, 48.0), (11.0, 47.0)]
    assert win._clicked[:2] == (11.0, 47.0)                 # newest stays current
    # removing the newest falls back to the newest remaining point
    win._on_web_title("NC2 11.0|47.0|5")
    assert win._clicked[:2] == (10.0, 48.0)


def test_pin_click_removes(win):
    win._on_web_title("NC2 10.0|48.0|1")
    win._on_web_title("NC2 10.5|47.5|2")
    win._on_web_title("NC2DEL 1 123")
    assert win._displayed_points == [(10.5, 47.5)]
    assert any("setPoints" in code for code in win.js)
