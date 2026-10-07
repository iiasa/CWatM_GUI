"""Show Basin ▸ Copy Mask: gauges outside the NEW mask (left over from the previous
basin) are taken out of the Gauges box; with none left, the mask outlet becomes
the gauge."""

import numpy as np
import pytest

pytest.importorskip("PySide6.QtWebEngineWidgets")

from src.gui.widgets.basin_viewer2 import BasinWindow2  # noqa: E402


class _Field:
    def __init__(self, text=""):
        self.t = text

    def setText(self, t):
        self.t = t

    def text(self):
        return self.t


class _MW:
    def __init__(self, ctx):
        self._mask_context = ctx
        self.gauges_field = _Field()


class _Host:
    """Just what _drop_gauges_outside_mask uses of the window."""
    def __init__(self, gauges):
        self._gauges = list(gauges)
        self.checks = 0

    def _run_gauge_check(self, mw, rebuild_mask=False):
        self.checks += 1


def _ctx():
    # 1° grid, lon 10..14, lat 50..54; inside = the cells lon 11-12, lat 51-52
    lons = np.arange(10.0, 15.0)
    lats = np.arange(54.0, 49.0, -1.0)
    mask = np.zeros((5, 5), dtype=int)
    for lat in (51.0, 52.0):
        for lon in (11.0, 12.0):
            mask[int(np.where(lats == lat)[0][0]), int(np.where(lons == lon)[0][0])] = 1
    return {"type": "grid", "lats": lats, "lons": lons, "mask": mask}


def _drop(host, mw, outlet="11.0000 51.0000"):
    return BasinWindow2._drop_gauges_outside_mask(host, mw, outlet)


def test_outside_gauges_are_removed():
    host, mw = _Host([(11.0, 51.0), (40.0, 10.0), (12.0, 52.0)]), _MW(_ctx())
    note = _drop(host, mw)
    assert host._gauges == [(11.0, 51.0), (12.0, 52.0)]
    assert mw.gauges_field.text() == "11.0000 51.0000 12.0000 52.0000"
    assert "removed 1 gauge" in note and host.checks == 1


def test_all_outside_falls_back_to_the_outlet():
    host, mw = _Host([(40.0, 10.0), (13.9, 53.9)]), _MW(_ctx())
    note = _drop(host, mw, outlet="12.0000 52.0000")
    assert host._gauges == [(12.0, 52.0)]
    assert mw.gauges_field.text() == "12.0000 52.0000"
    assert "outlet" in note


def test_nothing_changes_when_all_inside_or_no_mask():
    host, mw = _Host([(11.0, 51.0)]), _MW(_ctx())
    assert _drop(host, mw) == "" and mw.gauges_field.text() == "" and host.checks == 0
    host, mw = _Host([(40.0, 10.0)]), _MW(None)
    assert _drop(host, mw) == "" and host._gauges == [(40.0, 10.0)]
