"""Basin built from a MaskMap POINT ("lon lat") is placed and shown correctly.

For a coordinate MaskMap the GUI asks CWatM for the catchment (`mainwarm -vgm`),
which returns ``(mask2D, xleft, yup)``: the catchment's bounding box plus its
column/row offset on the Ldd (= ups.nc) grid. The GUI pastes it onto the ups grid
(`BasinViewer._load_mask_data`), checks the gauges against it
(`build_mask_context` / `gauges_inside`) and draws it as the green overlay
(`BasinDataHelpers._build_mask_rgba`).

CWatM's catchment() used to return a masked array and now returns a plain ndarray;
the GUI took ``.data`` of it, which on a plain ndarray is a memoryview and ended in
"Error loading mask data: tuple index out of range". These tests pin both return
types, the placement, the gauge check and the on-screen orientation - with a fake
CWatM, so they need no model data. A last test runs the real CWatM on the Morava
setup when that data is on the machine (skipped otherwise).
"""

import os
import sys
import types

import numpy as np
import pytest

pytestmark = pytest.mark.qt  # basin_viewer imports PySide6 (QImage) at module level

from src.gui.widgets import basin_viewer  # noqa: E402
from src.gui.widgets.basin_viewer import (  # noqa: E402
    BasinDataHelpers, BasinViewer, build_mask_context, gauges_inside)


# ---------------------------------------------------------------------------
# A small synthetic setup: ups grid 20 x 30, 1 degree cells, lat north -> south
# ---------------------------------------------------------------------------

NROWS, NCOLS = 20, 30
LONS = 10.5 + np.arange(NCOLS, dtype=float)          # 10.5 .. 39.5
LATS = 59.5 - np.arange(NROWS, dtype=float)          # 59.5 .. 40.5 (north -> south)

# The catchment CWatM returns: its bounding box (an L shape with holes, so a
# shifted or mirrored paste cannot match by accident) and the box's offset.
CATCH = np.array([[1, 0, 0, 0, 0],
                  [1, 1, 0, 0, 0],
                  [1, 1, 1, 0, 0],
                  [0, 1, 1, 1, 1]], dtype=np.int64)
XLEFT, YUP = 7, 3


def _expected_big():
    big = np.zeros((NROWS, NCOLS), dtype=int)
    big[YUP:YUP + CATCH.shape[0], XLEFT:XLEFT + CATCH.shape[1]] = CATCH
    return big


def _cell_centre(row, col):
    return float(LONS[col]), float(LATS[row])


def _as_plain(catch):
    """What the current CWatM returns: a plain ndarray, 0 outside the catchment."""
    return np.array(catch)


def _as_masked(catch):
    """What older CWatM returned: a masked array; the cells under the mask may hold
    any value (it was uninitialised memory) - here a 1, which must NOT count."""
    data = np.where(catch == 1, 1, 1)                 # junk 1 under the mask
    return np.ma.masked_array(data, mask=(catch == 0))


@pytest.fixture
def fake_cwatm(monkeypatch):
    """Replace cwatm.run_cwatm with a stub whose mainwarm(-vgm) returns a chosen
    catchment, and record the settings file it was given."""
    calls = []
    fake = types.ModuleType("cwatm.run_cwatm")
    fake.result = None

    def mainwarm(settings, args, meteo):
        calls.append((settings, list(args)))
        # The GUI hands CWatM a temp copy of the LIVE content - it must exist now
        assert os.path.exists(settings)
        return fake.result

    fake.mainwarm = mainwarm
    fake.calls = calls
    import cwatm
    monkeypatch.setitem(sys.modules, "cwatm.run_cwatm", fake)
    monkeypatch.setattr(cwatm, "run_cwatm", fake, raising=False)
    return fake


def _settings_content(maskmap, gauges, ldd_dir):
    ldd = os.path.join(ldd_dir, "ldd.nc").replace("\\", "/")
    return (
        "[FILE_PATHS]\nPathRoot = .\n\n"
        f"[MASK_OUTLET]\nMaskMap = {maskmap}\nGauges = {gauges}\n\n"
        f"[TOPOP]\nLdd = {ldd}\n"
    )


# ---------------------------------------------------------------------------
# 1. _load_mask_data: both CWatM return types, pasted at the right place
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wrap", [_as_plain, _as_masked], ids=["plain", "masked"])
def test_point_mask_is_pasted_at_its_offset(tmp_path, fake_cwatm, wrap):
    fake_cwatm.result = (wrap(CATCH), XLEFT, YUP)
    settings = tmp_path / "settings.ini"
    content = _settings_content("12.5 55.5", "12.5 55.5", str(tmp_path))
    settings.write_text(content, encoding="utf-8")

    viewer = BasinViewer(content)
    mask = viewer._load_mask_data(str(settings), (NROWS, NCOLS), LATS, LONS)

    assert mask is not None, "mask not built (the 'tuple index out of range' bug)"
    mask = np.asarray(mask)
    assert mask.shape == (NROWS, NCOLS)
    np.testing.assert_array_equal(mask, _expected_big())
    assert int(mask.sum()) == int(CATCH.sum())
    assert fake_cwatm.calls and fake_cwatm.calls[0][1] == ["-vgm"]
    # the temp copy of the live content is cleaned up again
    assert not list(tmp_path.glob("temp_gaugecheck_*.ini"))


def test_point_mask_already_on_ups_grid_is_kept(tmp_path, fake_cwatm):
    """A catchment returned at the full ups size needs no pasting."""
    fake_cwatm.result = (_expected_big(), 0, 0)
    content = _settings_content("12.5 55.5", "12.5 55.5", str(tmp_path))
    mask = BasinViewer(content)._load_mask_data(
        str(tmp_path / "s.ini"), (NROWS, NCOLS), LATS, LONS)
    np.testing.assert_array_equal(np.asarray(mask), _expected_big())


def test_no_catchment_gives_no_mask(tmp_path, fake_cwatm):
    fake_cwatm.result = None
    content = _settings_content("12.5 55.5", "12.5 55.5", str(tmp_path))
    assert BasinViewer(content)._load_mask_data(
        str(tmp_path / "s.ini"), (NROWS, NCOLS), LATS, LONS) is None


# ---------------------------------------------------------------------------
# 2. build_mask_context + gauges_inside: the gauge check sees the same basin
# ---------------------------------------------------------------------------

def _write_ups(path, lats=LATS):
    xr = pytest.importorskip("xarray")
    ups = np.arange(NROWS * NCOLS, dtype="float32").reshape(NROWS, NCOLS)
    xr.Dataset({"ups": (("lat", "lon"), ups)},
               coords={"lat": lats, "lon": LONS}).to_netcdf(path)


def _first_inside_and_outside():
    big = _expected_big()
    inside = tuple(int(v) for v in np.argwhere(big == 1)[0])
    # a hole INSIDE the bounding box - wrongly "inside" if the box were used
    holes = np.argwhere(big[YUP:YUP + CATCH.shape[0],
                            XLEFT:XLEFT + CATCH.shape[1]] == 0)[0]
    outside = (int(holes[0]) + YUP, int(holes[1]) + XLEFT)
    return inside, outside


@pytest.mark.parametrize("wrap", [_as_plain, _as_masked], ids=["plain", "masked"])
def test_gauge_check_uses_the_point_basin(tmp_path, fake_cwatm, wrap):
    _write_ups(tmp_path / "ups.nc")
    fake_cwatm.result = (wrap(CATCH), XLEFT, YUP)
    (r_in, c_in), (r_out, c_out) = _first_inside_and_outside()
    lon_in, lat_in = _cell_centre(r_in, c_in)
    lon_out, lat_out = _cell_centre(r_out, c_out)

    content = _settings_content("12.5 55.5", f"{lon_in} {lat_in}", str(tmp_path))
    settings = tmp_path / "settings.ini"
    settings.write_text(content, encoding="utf-8")

    ctx = build_mask_context(str(settings), content)
    assert ctx is not None and ctx["type"] == "grid"
    np.testing.assert_array_equal(ctx["mask"], _expected_big())

    assert gauges_inside(ctx, content) is True
    outside = content.replace(f"Gauges = {lon_in} {lat_in}",
                              f"Gauges = {lon_out} {lat_out}")
    assert gauges_inside(ctx, outside) is False
    both = content.replace(f"Gauges = {lon_in} {lat_in}",
                           f"Gauges = {lon_in} {lat_in} {lon_out} {lat_out}")
    assert gauges_inside(ctx, both) is False


# ---------------------------------------------------------------------------
# 3. The green overlay: north at the top, west at the left
# ---------------------------------------------------------------------------

class _Host(BasinDataHelpers):
    def __init__(self, lats, lons, mask):
        self.lats, self.lons = lats, lons
        self.basin_data = np.ones((len(lats), len(lons)))
        self.mask_data = mask


def _green(rgba):
    return (rgba[..., 1] == 170) & (rgba[..., 3] > 0)


def test_overlay_north_to_south_grid():
    """lat north -> south: the image rows are the grid rows."""
    rgba = _Host(LATS, LONS, _expected_big())._build_mask_rgba()
    assert rgba.shape == (NROWS, NCOLS, 4)
    np.testing.assert_array_equal(_green(rgba), _expected_big() == 1)


def test_overlay_south_to_north_grid():
    """lat south -> north: the image is flipped so its top row is still north."""
    lats_sn = LATS[::-1]
    mask_sn = _expected_big()[::-1]           # the same basin on that grid
    rgba = _Host(lats_sn, LONS, mask_sn)._build_mask_rgba()
    np.testing.assert_array_equal(_green(rgba), _expected_big() == 1)


def test_overlay_skips_a_mask_of_the_wrong_shape():
    """A catchment that was never pasted onto the ups grid must not be drawn
    somewhere at the grid's top-left corner."""
    rgba = _Host(LATS, LONS, CATCH)._build_mask_rgba()
    assert not _green(rgba).any()


# ---------------------------------------------------------------------------
# 4. The real CWatM on the Morava/Thaya setup (only where the data exists)
# ---------------------------------------------------------------------------

MORAVA = os.environ.get(
    "CWATM_TEST_MORAVA_SETTINGS",
    r"C:\work\CWatM_GUI_all\Morava\settings_morava_1min_thaya.ini")


@pytest.mark.skipif(not os.path.exists(MORAVA),
                    reason="Morava test data not on this machine")
def test_real_cwatm_morava_thaya_basin(monkeypatch):
    """MaskMap = 16.9264 48.6276 (Thaya): CWatM reports 5727 cells = 12914 km2.
    The GUI must get exactly those cells on the ups grid, contain the gauge, and
    the outlet (largest upstream area inside the basin) must be at the MaskMap
    point."""
    monkeypatch.chdir(os.path.dirname(MORAVA))       # PathRoot = .
    with open(MORAVA, encoding="utf-8", errors="ignore") as f:
        content = f.read()

    ctx = build_mask_context(MORAVA, content)
    assert ctx is not None and ctx["type"] == "grid"
    mask = ctx["mask"]
    assert int(mask.sum()) == 5727
    assert gauges_inside(ctx, content) is True

    # outlet = the largest ups cell inside the basin, at the MaskMap point
    viewer = BasinViewer(content)
    ups_path = viewer._resolve_placeholders(viewer._find_ups_path())
    ups, lats, lons = viewer._load_netcdf_data(ups_path)
    assert ups.shape == mask.shape
    host = _Host(lats, lons, mask)
    host.basin_data = ups
    lon, lat = host._largest_ups_point()
    cell = abs(float(lons[1] - lons[0]))
    assert abs(lon - 16.9264) <= cell and abs(lat - 48.6276) <= cell

    # and it is drawn: as many green pixels as basin cells
    assert int(_green(host._build_mask_rgba()).sum()) == 5727
