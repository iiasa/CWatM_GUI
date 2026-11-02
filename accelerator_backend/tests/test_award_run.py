"""award_run.decide() - a port of award_run()'s SQL logic, so these tests mirror
the status codes/thresholds that function is documented to return."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import award_run as AR

VALID_UID = "0123456789abcdef0123456789abcdef"


def _claim(run_uid=VALID_UID, timesteps=100, kind="run"):
    return {"run_uid": run_uid, "timesteps": timesteps, "kind": kind}


class TestInvalidRunUid:
    def test_missing(self):
        result = AR.decide(_claim(run_uid=None), set(), 0)
        assert result == {"status": "invalid_run_uid"}

    def test_wrong_shape(self):
        result = AR.decide(_claim(run_uid="not-a-valid-uid"), set(), 0)
        assert result["status"] == "invalid_run_uid"

    def test_uppercase_is_rejected(self):
        # the SQL pattern is explicitly lowercase hex only.
        result = AR.decide(_claim(run_uid=VALID_UID.upper()), set(), 0)
        assert result["status"] == "invalid_run_uid"


class TestDuplicate:
    def test_already_recorded_run_uid(self):
        result = AR.decide(_claim(), {VALID_UID}, 0)
        assert result == {"status": "duplicate"}

    def test_duplicate_check_runs_before_too_short(self):
        # matches the SQL's own ordering: the duplicate check happens before
        # the daily-cap check (both after the shape/too-short checks there,
        # but duplicate wins over too_short here too - a too-short duplicate
        # is still a duplicate, not newly rejected for a different reason).
        result = AR.decide(_claim(timesteps=1), {VALID_UID}, 0)
        assert result["status"] == "duplicate"


class TestTooShort:
    def test_below_minimum(self):
        result = AR.decide(_claim(timesteps=AR.MIN_TIMESTEPS - 1), set(), 0)
        assert result == {"status": "too_short", "min_timesteps": AR.MIN_TIMESTEPS}

    def test_missing_timesteps_counts_as_zero(self):
        result = AR.decide(_claim(timesteps=None), set(), 0)
        assert result["status"] == "too_short"

    def test_exactly_the_minimum_is_enough(self):
        result = AR.decide(_claim(timesteps=AR.MIN_TIMESTEPS), set(), 0)
        assert result["status"] == "awarded"


class TestDailyLimit:
    def test_at_the_cap(self):
        result = AR.decide(_claim(), set(), AR.DAILY_RUN_CAP)
        assert result == {"status": "daily_limit", "daily_run_cap": AR.DAILY_RUN_CAP}

    def test_just_under_the_cap_is_awarded(self):
        result = AR.decide(_claim(), set(), AR.DAILY_RUN_CAP - 1)
        assert result["status"] == "awarded"


class TestAwarded:
    def test_builds_the_event_to_write(self):
        result = AR.decide(_claim(timesteps=365, kind="batch"), set(), 0)
        assert result["status"] == "awarded"
        assert result["points_awarded"] == AR.POINTS_PER_RUN
        assert result["event"] == {
            "source": "run",
            "source_ref": VALID_UID,
            "points": AR.POINTS_PER_RUN,
            "kind": "batch",
            "timesteps": 365,
        }

    def test_unknown_kind_is_dropped_not_passed_through(self):
        result = AR.decide(_claim(kind="something-the-client-made-up"), set(), 0)
        assert result["event"]["kind"] is None
