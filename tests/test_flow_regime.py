"""Flow regime (seasonal cycle) computation (`analysis_flow_regime.py`).

`compute_regime` is the pure-math core behind Analyse > NetCDF/Timeseries >
Action > Flow regime - never exercised by the test suite before, only checked by
hand against synthetic data while the feature was built. Pins down: daily vs.
monthly resolution detection, the 29 Feb drop (so a leap year never shifts the
axis), per-year curves, the multi-year average, and the cross-year percentile
bands.
"""

import pytest

from src.gui.widgets.analysis_flow_regime import compute_regime

# Needs Qt: the module imports PySide6.QtWidgets at module level (the window class
# lives alongside the pure function under test).
pytestmark = pytest.mark.qt


def _daily_dates(year, n):
    assert n <= 28, "keep within January so day numbers stay valid"
    return [f"{year}-01-{d:02d}" for d in range(1, n + 1)]


def _year_of_days(year, leap=False):
    """Every calendar day of ``year`` as an ISO string (366 days if leap)."""
    import datetime
    start = datetime.date(year, 1, 1)
    days = 366 if leap else 365
    return [(start + datetime.timedelta(d)).isoformat() for d in range(days)]


class TestResolutionDetection:
    def test_daily_series_is_detected(self):
        dates = _daily_dates(2020, 10)
        _ys, _ax, _ay, resolution, _b = compute_regime(dates, list(range(10)))
        assert resolution == "daily"

    def test_monthly_series_is_detected(self):
        dates = [f"2020-{m:02d}-15" for m in range(1, 13)]
        _ys, _ax, _ay, resolution, _b = compute_regime(dates, list(range(12)))
        assert resolution == "monthly"

    def test_annual_series_is_refused(self):
        dates = [f"{y}-06-15" for y in range(2010, 2020)]
        with pytest.raises(ValueError):
            compute_regime(dates, list(range(10)))

    def test_too_little_data_is_refused(self):
        with pytest.raises(ValueError):
            compute_regime(["2020-01-01"], [1.0])

    def test_empty_series_is_refused(self):
        with pytest.raises(ValueError):
            compute_regime([], [])


class TestLeapDayHandling:
    def test_leap_day_is_dropped_from_daily_regime(self):
        dates = _year_of_days(2020, leap=True)      # 2020 is a leap year
        values = [1.0] * len(dates)
        year_series, _ax, _ay, resolution, _b = compute_regime(dates, values)
        assert resolution == "daily"
        [(_year, x, _y)] = year_series
        assert len(x) == 365
        assert not any(d.month == 2 and d.day == 29 for d in x)

    def test_non_leap_year_still_has_365_days(self):
        dates = _year_of_days(2021, leap=False)
        values = [1.0] * len(dates)
        year_series, _ax, _ay, _res, _b = compute_regime(dates, values)
        [(_year, x, _y)] = year_series
        assert len(x) == 365

    def test_multi_year_average_always_365_points(self):
        dates = _year_of_days(2019, leap=False) + _year_of_days(2020, leap=True)
        values = [1.0] * len(dates)
        _ys, avg_x, avg_y, _res, _b = compute_regime(dates, values)
        assert len(avg_x) == 365
        assert len(avg_y) == 365


class TestComputeRegime:
    def test_one_curve_per_calendar_year(self):
        dates = _daily_dates(2019, 10) + _daily_dates(2020, 10)
        values = list(range(20))
        year_series, _ax, _ay, _res, _b = compute_regime(dates, values)
        years = sorted(y for y, _x, _v in year_series)
        assert years == [2019, 2020]

    def test_average_is_the_mean_across_years(self):
        dates = _daily_dates(2019, 5) + _daily_dates(2020, 5)
        values = [10.0, 10.0, 10.0, 10.0, 10.0, 20.0, 20.0, 20.0, 20.0, 20.0]
        _ys, _ax, avg_y, _res, _b = compute_regime(dates, values)
        assert avg_y == pytest.approx([15.0] * 5)

    def test_percentile_bands_are_ordered(self):
        dates = (_daily_dates(2018, 10) + _daily_dates(2019, 10)
                 + _daily_dates(2020, 10))
        values = list(range(30))
        _ys, _ax, _ay, _res, bands = compute_regime(dates, values)
        for lo, p40, p60, hi in zip(bands["p0"], bands["p40"],
                                     bands["p60"], bands["p100"]):
            assert lo <= p40 <= p60 <= hi

    def test_bands_reference_year_is_non_leap(self):
        dates = _daily_dates(2020, 5)
        values = [1.0] * 5
        _ys, _ax, _ay, _res, bands = compute_regime(dates, values)
        assert all(x.year == 2001 for x in bands["x"])

    def test_none_values_are_dropped(self):
        dates = _daily_dates(2020, 5)
        values = [1.0, None, 3.0, None, 5.0]
        year_series, _ax, _ay, _res, _b = compute_regime(dates, values)
        [(_year, _x, y)] = year_series
        assert len(y) == 3
