"""Goodness-of-fit scores (`src/gui/utils/metrics.py`).

Checked against values computed by hand from the standard definitions, plus the
degenerate cases where each score is undefined - those return None rather than raising,
because they are rendered straight into the Timeseries window.
"""

import math

import pytest

from src.gui.utils import metrics


class TestNSE:
    def test_perfect_fit_is_one(self):
        obs = [1.0, 2.0, 3.0, 4.0]
        assert metrics.nse(obs, obs) == pytest.approx(1.0)

    def test_predicting_the_observed_mean_is_zero(self):
        obs = [1.0, 2.0, 3.0, 4.0]
        sim = [2.5] * 4                       # the mean of obs
        assert metrics.nse(sim, obs) == pytest.approx(0.0)

    def test_worse_than_the_mean_is_negative(self):
        assert metrics.nse([4.0, 3.0, 2.0, 1.0], [1.0, 2.0, 3.0, 4.0]) < 0

    def test_hand_computed(self):
        sim, obs = [2.0, 3.0], [1.0, 4.0]
        # num = 1 + 1 = 2 ; obar = 2.5 ; denom = 2.25 + 2.25 = 4.5
        assert metrics.nse(sim, obs) == pytest.approx(1 - 2 / 4.5)

    def test_constant_observed_is_undefined(self):
        # denom == 0 -> NSE has no meaning
        assert metrics.nse([1.0, 2.0], [3.0, 3.0]) is None


class TestKGE:
    def test_perfect_fit_is_one(self):
        obs = [1.0, 2.0, 3.0, 4.0]
        assert metrics.kge(obs, obs) == pytest.approx(1.0)

    def test_hand_computed_for_a_pure_bias(self):
        # sim = obs * 2 -> r = 1, alpha = 2, beta = 2 -> 1 - sqrt(0 + 1 + 1)
        obs = [1.0, 2.0, 3.0, 4.0]
        sim = [2 * o for o in obs]
        assert metrics.kge(sim, obs) == pytest.approx(1 - math.sqrt(2))

    def test_zero_observed_mean_is_undefined(self):
        assert metrics.kge([1.0, 2.0], [-1.0, 1.0]) is None

    def test_constant_observed_is_undefined(self):
        assert metrics.kge([1.0, 2.0], [3.0, 3.0]) is None


class TestPBIAS:
    def test_no_bias(self):
        obs = [1.0, 2.0, 3.0]
        assert metrics.pbias(obs, obs) == pytest.approx(0.0)

    def test_positive_means_overestimate(self):
        # sum(sim-obs) = 3, sum(obs) = 6 -> +50 %
        assert metrics.pbias([2.0, 3.0, 4.0], [1.0, 2.0, 3.0]) == pytest.approx(50.0)

    def test_negative_means_underestimate(self):
        assert metrics.pbias([1.0, 2.0, 3.0], [2.0, 3.0, 4.0]) < 0

    def test_zero_observed_sum_is_undefined(self):
        assert metrics.pbias([1.0, 1.0], [-2.0, 2.0]) is None


class TestRMSE:
    def test_perfect_fit_is_zero(self):
        obs = [1.0, 2.0, 3.0]
        assert metrics.rmse(obs, obs) == pytest.approx(0.0)

    def test_hand_computed(self):
        # errors 1, -1 -> sqrt((1+1)/2) = 1
        assert metrics.rmse([2.0, 2.0], [1.0, 3.0]) == pytest.approx(1.0)

    def test_single_pair_is_the_absolute_error(self):
        assert metrics.rmse([5.0], [2.0]) == pytest.approx(3.0)


class TestMissingData:
    """Gaps are the normal case for observed discharge, so pairing must be strict."""

    def test_none_pairs_are_dropped(self):
        assert metrics.rmse([1.0, None, 3.0], [1.0, 99.0, 3.0]) == pytest.approx(0.0)

    def test_nan_pairs_are_dropped(self):
        assert metrics.rmse([1.0, float("nan")], [1.0, 99.0]) == pytest.approx(0.0)

    def test_unparsable_pairs_are_dropped(self):
        assert metrics.rmse([1.0, "x"], [1.0, 99.0]) == pytest.approx(0.0)

    def test_series_are_truncated_to_the_shorter_one(self):
        assert metrics.rmse([1.0, 2.0, 3.0], [1.0, 2.0]) == pytest.approx(0.0)

    def test_too_few_pairs_is_none(self):
        assert metrics.nse([1.0], [1.0]) is None
        assert metrics.kge([1.0], [1.0]) is None

    def test_no_pairs_at_all_is_none(self):
        assert metrics.rmse([None], [None]) is None
        assert metrics.pbias([None], [None]) is None


class TestComputeAll:
    def test_reports_every_score_and_the_pair_count(self):
        obs = [1.0, 2.0, 3.0, 4.0]
        out = metrics.compute_all(obs, obs)
        assert set(out) == {"KGE", "NSE", "PBIAS", "RMSE", "n"}
        assert out["n"] == 4
        assert out["NSE"] == pytest.approx(1.0)
        assert out["KGE"] == pytest.approx(1.0)
        assert out["RMSE"] == pytest.approx(0.0)

    def test_n_counts_only_usable_pairs(self):
        assert metrics.compute_all([1.0, None, 3.0], [1.0, 2.0, 3.0])["n"] == 2
