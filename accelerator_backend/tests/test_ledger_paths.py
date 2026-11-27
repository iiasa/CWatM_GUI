"""ledger_paths - pure path building/parsing for the event log."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ledger_paths as LP

H = "0123456789abcdef" * 4


def test_run_filename_round_trips():
    name = LP.run_event_filename(H, "2026-11-30")
    assert name == f"2026-11-30-{H}.json"
    assert LP.parse_run_filename(name) == ("2026-11-30", H)


def test_stray_names_are_ignored():
    for name in ("README.md", f"{H}.json", f"2026-11-30-{H}.txt",
                 "2026-11-30-" + "ABCDEF" * 10 + "ABCD.json", "2026-11-30-" + "a" * 32 + ".json"):
        assert LP.parse_run_filename(name) is None


def test_directories():
    assert LP.run_events_dir(319) == "ledger/319/runs"
    assert LP.badge_path(319, "breg") == "ledger/319/badges/breg.json"
