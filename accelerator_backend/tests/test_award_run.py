"""award_run.decide - the old server's final rules (one point per distinct setup)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import award_run as AR

H1 = "a" * 64
H2 = "b" * 64


def claim(h=H1, timesteps=365):
    return {"settings_hash": h, "timesteps": timesteps}


def test_a_new_setup_earns_a_point():
    assert AR.decide(claim(), set(), 0) == {"status": "awarded", "points_awarded": 1}


def test_the_same_setup_earns_nothing_twice():
    assert AR.decide(claim(), {H1}, 0) == {"status": "same_settings"}
    assert AR.decide(claim(H2), {H1}, 0)["status"] == "awarded"


def test_a_missing_or_malformed_fingerprint_counts_nothing():
    for bad in (None, "", "abc", "A" * 64, "g" * 64, "a" * 63, 7):
        assert AR.decide({"settings_hash": bad, "timesteps": 365}, set(), 0) == \
            {"status": "no_settings_hash"}
    assert AR.decide({"timesteps": 365}, set(), 0)["status"] == "no_settings_hash"


def test_too_short():
    assert AR.decide(claim(timesteps=29), set(), 0) == {"status": "too_short", "min_timesteps": 30}
    assert AR.decide(claim(timesteps=30), set(), 0)["status"] == "awarded"
    assert AR.decide(claim(timesteps=None), set(), 0)["status"] == "too_short"


def test_daily_limit():
    assert AR.decide(claim(), set(), 19)["status"] == "awarded"
    assert AR.decide(claim(), set(), 20) == {"status": "daily_limit", "daily_run_cap": 20}


def test_order_of_the_checks_matches_the_old_server():
    # no fingerprint beats too short; too short beats same setup; same setup beats the cap
    assert AR.decide({"timesteps": 1}, {H1}, 99)["status"] == "no_settings_hash"
    assert AR.decide(claim(timesteps=1), {H1}, 99)["status"] == "too_short"
    assert AR.decide(claim(), {H1}, 99)["status"] == "same_settings"
