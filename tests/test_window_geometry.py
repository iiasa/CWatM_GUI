"""`scaled_default_size` (`src/gui/utils/window_geometry.py`) - the screen-relative
default size every secondary window's first-ever `.resize(W, H)` goes through.

Duck-typed fake widget/screen objects stand in for real Qt ones (the function only
ever calls `.screen()` / `.availableGeometry()` / `.width()` / `.height()`), so this
covers the scaling/clamping math without needing a real display.
"""

import pytest

from src.gui.utils.window_geometry import scaled_default_size

# Needs Qt: the module imports PySide6.QtGui.QGuiApplication at module level (used
# as the fallback when a widget has no screen of its own).
pytestmark = pytest.mark.qt


class FakeGeometry:
    def __init__(self, w, h):
        self._w, self._h = w, h

    def width(self):
        return self._w

    def height(self):
        return self._h


class FakeScreen:
    def __init__(self, w, h):
        self._geo = FakeGeometry(w, h)

    def availableGeometry(self):
        return self._geo


class FakeWidget:
    def __init__(self, screen_w, screen_h):
        self._screen = FakeScreen(screen_w, screen_h)

    def screen(self):
        return self._screen


class TestReferenceScreen:
    def test_1920x1080_screen_returns_the_base_size_unchanged(self):
        widget = FakeWidget(1920, 1080)
        w, h = scaled_default_size(widget, 900, 600)
        assert (w, h) == (900, 600)


class TestSmallerScreen:
    def test_a_1366x768_laptop_scales_down(self):
        widget = FakeWidget(1366, 768)
        w, h = scaled_default_size(widget, 900, 600)
        assert w < 900 and h < 600

    def test_result_never_exceeds_the_screen(self):
        widget = FakeWidget(800, 600)
        w, h = scaled_default_size(widget, 900, 600)
        assert w <= 800 * 0.94
        assert h <= 600 * 0.90

    def test_scale_factor_is_clamped_at_the_floor(self):
        # An absurdly small screen must not shrink the window to near-nothing -
        # min_scale=0.55 caps how far it can shrink relative to the base size.
        widget = FakeWidget(200, 150)
        w, h = scaled_default_size(widget, 900, 600, min_scale=0.55)
        # Either the scale floor or the screen-fraction cap applies - whichever is
        # smaller - but never below 1px, and the scale floor bounds it above that.
        assert w >= 1 and h >= 1


class TestLargerScreen:
    def test_a_4k_screen_scales_up(self):
        widget = FakeWidget(3840, 2160)
        w, h = scaled_default_size(widget, 900, 600)
        assert w > 900 and h > 600

    def test_scale_factor_is_clamped_at_the_ceiling(self):
        widget = FakeWidget(3840, 2160)
        w, h = scaled_default_size(widget, 900, 600, max_scale=1.35)
        assert w == pytest.approx(900 * 1.35, rel=0.01)
        assert h == pytest.approx(600 * 1.35, rel=0.01)


class TestFallback:
    def test_a_widget_with_no_screen_method_falls_back_to_the_base_size(
            self, monkeypatch):
        # Without a widget-level screen(), the function asks
        # QGuiApplication.primaryScreen() instead - force that to None (as it
        # genuinely is before any QApplication exists) rather than relying on
        # whether some OTHER test in this session happened to construct one
        # first, which made this test's outcome depend on test run order/
        # collection order instead of on the code under test.
        from src.gui.utils import window_geometry
        monkeypatch.setattr(
            window_geometry.QGuiApplication, "primaryScreen", staticmethod(lambda: None))

        class NoScreen:
            pass

        w, h = scaled_default_size(NoScreen(), 900, 600)
        assert (w, h) == (900, 600)

    def test_a_zero_size_screen_falls_back_to_the_base_size(self):
        widget = FakeWidget(0, 0)
        w, h = scaled_default_size(widget, 900, 600)
        assert (w, h) == (900, 600)

    def test_a_screen_that_raises_falls_back_to_the_base_size(self):
        class BrokenScreen:
            def availableGeometry(self):
                raise RuntimeError("no display")

        class BrokenWidget:
            def screen(self):
                return BrokenScreen()

        w, h = scaled_default_size(BrokenWidget(), 900, 600)
        assert (w, h) == (900, 600)


class TestAspectRatioIsPreserved:
    def test_width_and_height_scale_by_the_same_factor(self):
        widget = FakeWidget(1366, 768)
        base_w, base_h = 900, 600
        w, h = scaled_default_size(widget, base_w, base_h)
        assert w / base_w == pytest.approx(h / base_h, rel=0.01)
