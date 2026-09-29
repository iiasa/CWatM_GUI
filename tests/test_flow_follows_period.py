"""Analyse ▸ Timeseries: Flow duration / Flow regime analyse the displayed period
(the range slider), and an open window follows when the slider moves. Driven on a
bare TimeseriesWindow with stand-in flow windows (no web page)."""

import pytest

pytestmark = pytest.mark.qt


class _FakeFlowWindow:
    def __init__(self):
        self.got = None

    def isVisible(self):
        return True

    def set_series(self, series):
        self.got = series

    def set_data(self, dates, values):
        self.got = (dates, values)


@pytest.fixture
def ts(qapp):
    from src.gui.widgets.analysis_timeseries import TimeseriesWindow
    w = TimeseriesWindow.__new__(TimeseriesWindow)       # skip __init__
    w.dates = [f"{d:02d}/01/2000" for d in range(1, 11)]
    w.series = [("Gauge 1", list(range(10))), ("Gauge 2", list(range(100, 110)))]
    w.index = 0
    w._win_lo, w._win_hi = 2, 5
    return w


def test_flow_input_is_the_displayed_period(ts):
    name, dates, values = ts._flow_input(1)
    assert name == "Gauge 2"
    assert dates == ["2000-01-03", "2000-01-04", "2000-01-05", "2000-01-06"]
    assert values == [102, 103, 104, 105]


def test_open_windows_follow_the_slider(ts):
    ts._flowdur_window, ts._flowdur_index = _FakeFlowWindow(), 0
    ts._flowregime_window, ts._flowregime_index = _FakeFlowWindow(), 1
    ts._win_lo, ts._win_hi = 0, 1                          # slider moved
    ts._refresh_flow_windows()
    assert ts._flowdur_window.got == [("Gauge 1", ["2000-01-01", "2000-01-02"], [0, 1])]
    assert ts._flowregime_window.got == (["2000-01-01", "2000-01-02"], [100, 101])


def test_tooltips():
    import inspect
    from src.gui.widgets import analysis_timeseries
    src = inspect.getsource(analysis_timeseries.TimeseriesWindow._build_menubar)
    assert "Flow duration of the displayed period for the given timeserie" in src
    assert "Flow regime (diagram of one year) of the displayed period for " in src
