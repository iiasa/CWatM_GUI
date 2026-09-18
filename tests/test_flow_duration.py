"""Flow duration curve computation (`analysis_flow_duration.py`).

`compute_flow_duration`/`flow_duration_points` are the pure-math core behind
Analyse > NetCDF/Timeseries > Action > Flow duration - never exercised by the test
suite before, only checked by hand against synthetic data while the feature was
built. Pins down: per-year ranking (Weibull plotting position), the pooled
all-years average curve, and the cross-year percentile bands.
"""

import pytest

from src.gui.widgets.analysis_flow_duration import (
    compute_flow_duration, flow_duration_points,
)

# Needs Qt: the module imports PySide6.QtWidgets at module level (the window class
# lives alongside the pure functions under test).
pytestmark = pytest.mark.qt


def _daily_dates(year, n):
    assert n <= 28, "keep within January so day numbers stay valid"
    return [f"{year}-01-{d:02d}" for d in range(1, n + 1)]


class TestFlowDurationPoints:
    def test_empty_input_returns_empty(self):
        probs, vals = flow_duration_points([])
        assert probs == [] and vals == []

    def test_none_entries_are_dropped(self):
        probs, vals = flow_duration_points([1.0, None, 3.0, None])
        assert len(probs) == 2
        assert len(vals) == 2

    def test_values_are_ranked_descending(self):
        _probs, vals = flow_duration_points([1.0, 5.0, 3.0, 2.0, 4.0])
        assert vals == sorted(vals, reverse=True)

    def test_probabilities_are_ascending(self):
        probs, _vals = flow_duration_points([1.0, 5.0, 3.0])
        assert probs == sorted(probs)

    def test_weibull_plotting_position(self):
        # n=3 -> probs = 100*m/(n+1) for m=1..3 = 25, 50, 75
        probs, _vals = flow_duration_points([10.0, 20.0, 30.0])
        assert probs == pytest.approx([25.0, 50.0, 75.0])

    def test_highest_value_gets_lowest_probability(self):
        probs, vals = flow_duration_points([1.0, 2.0, 3.0])
        assert vals[0] == 3.0
        assert probs[0] == min(probs)


class TestComputeFlowDuration:
    def test_empty_series_returns_empty_everything(self):
        year_curves, avg_probs, avg_vals, bands = compute_flow_duration([], [])
        assert year_curves == []
        assert avg_probs == [] and avg_vals == []
        assert bands == dict(x=[], p0=[], p40=[], p60=[], p100=[])

    def test_all_none_values_returns_empty(self):
        dates = _daily_dates(2020, 5)
        year_curves, avg_probs, _avg_vals, _bands = compute_flow_duration(
            dates, [None] * 5)
        assert year_curves == []
        assert avg_probs == []

    def test_single_year_produces_one_curve(self):
        dates = _daily_dates(2020, 10)
        values = list(range(1, 11))
        year_curves, avg_probs, avg_vals, _bands = compute_flow_duration(dates, values)
        assert len(year_curves) == 1
        year, probs, vals = year_curves[0]
        assert year == 2020
        assert len(probs) == 10
        assert len(vals) == 10
        # With a single year, the pooled average curve is the same curve.
        assert avg_probs == probs
        assert avg_vals == vals

    def test_multiple_years_produce_separate_curves(self):
        dates = _daily_dates(2020, 5) + _daily_dates(2021, 5)
        values = [1, 2, 3, 4, 5, 10, 20, 30, 40, 50]
        year_curves, _avg_probs, _avg_vals, _bands = compute_flow_duration(
            dates, values)
        years = sorted(y for y, _p, _v in year_curves)
        assert years == [2020, 2021]

    def test_percentile_bands_are_ordered(self):
        dates = (_daily_dates(2018, 20) + _daily_dates(2019, 20)
                 + _daily_dates(2020, 20))
        values = list(range(1, 61))
        _yc, _ap, _av, bands = compute_flow_duration(dates, values)
        assert len(bands["x"]) == 101      # 0..100 in 1% steps
        for lo, p40, p60, hi in zip(bands["p0"], bands["p40"],
                                     bands["p60"], bands["p100"]):
            assert lo <= p40 <= p60 <= hi

    def test_bands_x_axis_is_full_probability_range(self):
        dates = _daily_dates(2020, 10) + _daily_dates(2021, 10)
        values = list(range(20))
        _yc, _ap, _av, bands = compute_flow_duration(dates, values)
        assert bands["x"][0] == pytest.approx(0.0)
        assert bands["x"][-1] == pytest.approx(100.0)

    def test_unparseable_dates_are_dropped(self):
        dates = ["not-a-date", "2020-01-02", "2020-01-03"]
        values = [1.0, 2.0, 3.0]
        year_curves, _ap, _av, _bands = compute_flow_duration(dates, values)
        total_points = sum(len(v) for _y, _p, v in year_curves)
        assert total_points == 2
