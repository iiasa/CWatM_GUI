"""Temp-page lifetime for the Plotly viewers (`src/gui/utils/temp_page.py`).

The defect this guards: those pages inline plotly.js, so each is several MB, and the
windows re-render on every tick of a debounced range slider. Before `TempPageMixin` each
redraw orphaned one file in the user's temp directory, for the life of the machine.
"""

import os

import pytest

from src.gui.utils.temp_page import TempPageMixin


class FakeView:
    """Stands in for QWebEngineView - the mixin only calls .load()."""

    def __init__(self):
        self.loaded = []

    def load(self, url):
        self.loaded.append(url.toLocalFile())


# TempPageMixin.done() calls super().done(); a plain object has none, so the tests
# terminate the chain here. In the real windows that next link is GeometryMemoryMixin,
# which is why test_done_reaches_the_rest_of_the_chain matters.
class _Terminator:
    def done(self, result):
        self.done_result = result


class PageWindow(TempPageMixin, _Terminator):
    def __init__(self):
        self.web_view = FakeView()


@pytest.fixture
def win():
    w = PageWindow()
    yield w
    w._discard_temp_page()


class TestOnePageAtATime:
    def test_first_render_writes_a_file(self, win):
        path = win._load_temp_page("<html>1</html>", "cwatm_test_")
        assert os.path.exists(path)
        assert open(path, encoding="utf-8").read() == "<html>1</html>"

    def test_rerender_deletes_the_page_it_replaces(self, win):
        first = win._load_temp_page("<html>1</html>", "cwatm_test_")
        second = win._load_temp_page("<html>2</html>", "cwatm_test_")
        assert first != second
        assert not os.path.exists(first), "the replaced page leaked"
        assert os.path.exists(second)

    def test_many_renders_leave_exactly_one_file(self, win):
        paths = [win._load_temp_page(f"<html>{i}</html>", "cwatm_test_")
                 for i in range(10)]
        alive = [p for p in paths if os.path.exists(p)]
        assert alive == [paths[-1]]

    def test_the_view_is_pointed_at_every_render(self, win):
        paths = [win._load_temp_page(f"<html>{i}</html>", "cwatm_test_")
                 for i in range(3)]
        # QUrl normalises the separators, so compare resolved paths.
        loaded = [os.path.normpath(p) for p in win.web_view.loaded]
        assert loaded == [os.path.normpath(p) for p in paths]

    def test_prefix_is_used(self, win):
        path = win._load_temp_page("<html/>", "cwatm_wc_")
        assert os.path.basename(path).startswith("cwatm_wc_")
        assert path.endswith(".html")


class TestCleanup:
    def test_done_removes_the_last_page(self):
        w = PageWindow()
        path = w._load_temp_page("<html/>", "cwatm_test_")
        assert os.path.exists(path)
        w.done(0)
        assert not os.path.exists(path)

    def test_done_reaches_the_rest_of_the_chain(self):
        w = PageWindow()
        w._load_temp_page("<html/>", "cwatm_test_")
        w.done(3)
        assert w.done_result == 3, "super().done() must still run (geometry save)"

    def test_discard_is_idempotent(self, win):
        win._load_temp_page("<html/>", "cwatm_test_")
        win._discard_temp_page()
        win._discard_temp_page()               # must not raise
        assert win._temp_html is None

    def test_discard_without_a_page_is_harmless(self):
        PageWindow()._discard_temp_page()

    def test_a_page_removed_behind_our_back_is_not_an_error(self, win):
        path = win._load_temp_page("<html/>", "cwatm_test_")
        os.remove(path)
        win._discard_temp_page()               # must not raise


class TestUnicode:
    def test_non_ascii_content_round_trips(self, win):
        html = "<html>Donau Oder Morava - 48.2°N – tescík</html>"
        path = win._load_temp_page(html, "cwatm_test_")
        assert open(path, encoding="utf-8").read() == html
