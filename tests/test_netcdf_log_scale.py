"""Analyse ▸ NetCDF: the value -> colour normalisation (``color_norm``), in particular
Log scale on a Compare A−B difference map, which must stay symmetric around 0 (the
shifted log of ordinary maps put a zero difference at ~0.8 and painted the whole
basin red)."""

import numpy as np

from src.gui.widgets.analysis_netcdf import color_norm


def test_linear_maps_ends_and_middle():
    z = np.array([0.0, 5.0, 10.0])
    assert np.allclose(color_norm(z, 0.0, 10.0), [0.0, 0.5, 1.0])


def test_log_of_ordinary_map_unchanged():
    z = np.array([0.0, 9.0, 99.0])
    expected = np.log1p(z) / np.log1p(99.0)
    assert np.allclose(color_norm(z, 0.0, 99.0, log=True), expected)


def test_log_on_difference_keeps_zero_white_and_sign():
    vmax = 23.4
    z = np.array([-vmax, -0.5, 0.0, 0.5, vmax])
    n = color_norm(z, -vmax, vmax, log=True, diverging=True)
    assert np.isclose(n[2], 0.5)                     # no difference -> middle (white)
    assert np.isclose(n[0], 0.0) and np.isclose(n[4], 1.0)
    assert n[1] < 0.5 < n[3]                         # sign decides the side
    assert np.isclose(n[1] + n[3], 1.0)              # symmetric
    # small differences are lifted away from white compared with linear
    lin = color_norm(z, -vmax, vmax, diverging=True)
    assert n[3] - 0.5 > lin[3] - 0.5


def test_nan_cells_are_zero():
    z = np.array([np.nan, 1.0])
    for log, div in ((False, False), (True, False), (True, True)):
        assert color_norm(z, -2.0, 2.0, log=log, diverging=div)[0] == 0.0
