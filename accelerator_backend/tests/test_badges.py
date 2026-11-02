import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import badges as B


class TestLadderShape:
    def test_twelve_tiers_breg_to_amazonas(self):
        assert len(B.RIVER_BADGES) == 12
        assert B.RIVER_BADGES[0][0] == "breg"
        assert B.RIVER_BADGES[-1][0] == "amazonas"

    def test_strictly_ascending_thresholds(self):
        thresholds = [required for _code, _name, required in B.RIVER_BADGES]
        assert thresholds == sorted(thresholds)
        assert len(set(thresholds)) == len(thresholds)


class TestEarnedBadges:
    def test_below_the_first_tier(self):
        assert B.earned_badges(4) == []

    def test_exactly_a_threshold_counts(self):
        assert B.earned_badges(5) == ["breg"]

    def test_between_tiers_holds_everything_reached_so_far(self):
        assert B.earned_badges(60) == ["breg", "thames", "morava", "inn"]

    def test_at_the_top(self):
        assert B.earned_badges(10000) == [code for code, _n, _r in B.RIVER_BADGES]

    def test_above_the_top_is_the_same_as_at_the_top(self):
        assert B.earned_badges(999999) == B.earned_badges(10000)


class TestNewBadges:
    def test_first_badge_from_zero(self):
        result = B.new_badges(5, already_held_codes=[])
        assert result == [{"code": "breg", "name": "Breg", "points_required": 5}]

    def test_already_held_badges_are_excluded(self):
        result = B.new_badges(30, already_held_codes=["breg"])
        codes = [b["code"] for b in result]
        assert codes == ["thames", "morava"]

    def test_nothing_new_when_everything_reached_is_already_held(self):
        held = [code for code, _n, _r in B.RIVER_BADGES if _r <= 100]
        result = B.new_badges(100, already_held_codes=held)
        assert result == []

    def test_crossing_several_tiers_at_once_returns_all_of_them(self):
        # e.g. a feature-run badge or a big batch award could jump straight
        # from 0 to past several thresholds in one event.
        result = B.new_badges(60, already_held_codes=[])
        assert [b["code"] for b in result] == ["breg", "thames", "morava", "inn"]


class TestNextBadge:
    def test_from_zero(self):
        assert B.next_badge(0) == {"code": "breg", "name": "Breg", "points_required": 5}

    def test_right_at_a_threshold_points_to_the_one_after(self):
        assert B.next_badge(5)["code"] == "thames"

    def test_none_once_the_top_badge_is_reached(self):
        assert B.next_badge(10000) is None

    def test_none_above_the_top(self):
        assert B.next_badge(999999) is None
