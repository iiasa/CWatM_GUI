"""The Journal of Runs store (`src/gui/utils/run_ledger.py`).

Every test redirects the ledger at a `tmp_path` by monkeypatching `history_dir`, so the
user's real `%LOCALAPPDATA%/CWatM_GUI/run_ledger.json` and their QSettings are never
touched - a test that pruned someone's actual run history would be a poor trade for
coverage.
"""

import json
import time

import pytest

from src.gui.utils import run_ledger


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(run_ledger, "history_dir", lambda: str(tmp_path))
    monkeypatch.setattr(run_ledger, "retention_days", lambda: 0)   # keep forever
    return tmp_path


def entry(title="run", ts=None, **kw):
    e = {
        "ts": ts if ts is not None else time.time(),
        "kind": "run", "settings": "s.ini", "title": title, "pathout": "out",
        "duration_s": 1.0, "success": True, "last_dis": 1.0,
    }
    e.update(kw)
    return e


class TestRoundTrip:
    def test_empty_ledger_reads_as_empty(self, ledger):
        assert run_ledger.load_entries() == []

    def test_add_then_load(self, ledger):
        run_ledger.add_entry(entry(title="first"))
        rows = run_ledger.load_entries()
        assert len(rows) == 1
        assert rows[0]["title"] == "first"

    def test_entries_accumulate(self, ledger):
        for i in range(5):
            run_ledger.add_entry(entry(title=f"run{i}"))
        assert len(run_ledger.load_entries()) == 5

    def test_the_file_is_valid_json(self, ledger):
        run_ledger.add_entry(entry())
        data = json.loads((ledger / "run_ledger.json").read_text(encoding="utf-8"))
        assert isinstance(data, list)

    def test_unicode_title_survives(self, ledger):
        run_ledger.add_entry(entry(title="Donau – Morava tescík 48.2°"))
        assert run_ledger.load_entries()[0]["title"] == "Donau – Morava tescík 48.2°"

    def test_clear_empties_it(self, ledger):
        run_ledger.add_entry(entry())
        run_ledger.clear()
        assert run_ledger.load_entries() == []


class TestCorruptFile:
    """The journal is written on every run; a half-written or hand-edited file must
    not take the window down."""

    @pytest.mark.parametrize("text", ["", "   ", "not json at all", "{", '{"a": 1}'])
    def test_unreadable_file_reads_as_empty(self, ledger, text):
        (ledger / "run_ledger.json").write_text(text, encoding="utf-8")
        assert run_ledger.load_entries() == []

    def test_a_corrupt_file_can_still_be_appended_to(self, ledger):
        (ledger / "run_ledger.json").write_text("garbage", encoding="utf-8")
        run_ledger.add_entry(entry(title="after"))
        rows = run_ledger.load_entries()
        assert [r["title"] for r in rows] == ["after"]


class TestRetention:
    def test_zero_keeps_everything(self, ledger, monkeypatch):
        monkeypatch.setattr(run_ledger, "retention_days", lambda: 0)
        old = time.time() - 3600 * 24 * 500
        run_ledger.add_entry(entry(title="ancient", ts=old))
        run_ledger.add_entry(entry(title="fresh"))
        assert {r["title"] for r in run_ledger.load_entries()} == {"ancient", "fresh"}

    def test_old_entries_are_pruned_on_write(self, ledger, monkeypatch):
        monkeypatch.setattr(run_ledger, "retention_days", lambda: 30)
        old = time.time() - 3600 * 24 * 90
        run_ledger.add_entry(entry(title="ancient", ts=old))
        run_ledger.add_entry(entry(title="fresh"))
        titles = {r["title"] for r in run_ledger.load_entries()}
        assert "fresh" in titles
        assert "ancient" not in titles

    def test_an_entry_inside_the_window_is_kept(self, ledger, monkeypatch):
        monkeypatch.setattr(run_ledger, "retention_days", lambda: 30)
        recent = time.time() - 3600 * 24 * 5
        run_ledger.add_entry(entry(title="recent", ts=recent))
        run_ledger.add_entry(entry(title="fresh"))
        assert {r["title"] for r in run_ledger.load_entries()} == {"recent", "fresh"}


class TestMakeEntry:
    def test_records_the_common_run_facts(self, ledger):
        started = time.time() - 5
        e = run_ledger.make_entry("s.ini", "Morava", "out/", started, True, 12.5)
        assert e["settings"] == "s.ini"
        assert e["title"] == "Morava"
        assert e["pathout"] == "out/"
        assert e["success"] is True
        assert e["last_dis"] == 12.5
        assert e["kind"] == "run"
        assert e["duration_s"] >= 4.5

    def test_duration_is_never_negative(self, ledger):
        e = run_ledger.make_entry("s.ini", "t", "o", time.time() + 60, True, 0)
        assert e["duration_s"] >= 0

    def test_missing_start_time_gives_zero_duration(self, ledger):
        assert run_ledger.make_entry("s.ini", "t", "o", None, True, 0)["duration_s"] == 0

    def test_kind_and_batch_id_are_carried(self, ledger):
        e = run_ledger.make_entry("s.ini", "t", "o", time.time(), True, 0,
                                  kind="hidden", batch_id="abc")
        assert e["kind"] == "hidden"
        assert e["batch_id"] == "abc"

    def test_log_path_is_recorded_only_when_given(self, ledger):
        with_log = run_ledger.make_entry("s.ini", "t", "o", time.time(), True, 0,
                                         log_path="out/cwatm_out.txt")
        without = run_ledger.make_entry("s.ini", "t", "o", time.time(), True, 0)
        assert with_log["log"] == "out/cwatm_out.txt"
        assert "log" not in without

    def test_content_is_snapshotted_for_compare_settings(self, ledger):
        e = run_ledger.make_entry("s.ini", "t", "o", time.time(), True, 0,
                                  content="[OPTIONS]\nx = True\n")
        assert e.get("snapshot")
        import os
        assert os.path.exists(e["snapshot"])
        assert "x = True" in open(e["snapshot"], encoding="utf-8").read()

    def test_a_failed_run_is_recorded_as_such(self, ledger):
        assert run_ledger.make_entry("s.ini", "t", "o", time.time(),
                                     False, None)["success"] is False


class TestNotesAndRemoval:
    """A journal row is identified across a reload by `_entry_key` =
    (ts rounded to the millisecond, settings, pathout) - the window edits copies, so
    there is no object identity to rely on. Real runs differ in at least one of those
    (Batch Run's preflight even refuses a duplicate PathOut), which is what makes the
    key workable."""

    def test_a_note_survives_a_reload(self, ledger):
        run_ledger.add_entry(entry(title="noted"))
        stored = run_ledger.load_entries()[0]
        run_ledger.set_note(stored, "check the spin-up")
        assert run_ledger.load_entries()[0].get("note") == "check the spin-up"

    def test_an_empty_note_clears_it(self, ledger):
        run_ledger.add_entry(entry(title="noted"))
        stored = run_ledger.load_entries()[0]
        run_ledger.set_note(stored, "something")
        run_ledger.set_note(run_ledger.load_entries()[0], "")
        assert "note" not in run_ledger.load_entries()[0]

    def test_remove_entries_drops_only_the_named_rows(self, ledger):
        # Distinct timestamps + PathOuts, as real runs have.
        now = time.time()
        for i in range(3):
            run_ledger.add_entry(entry(title=f"run{i}", ts=now + i, pathout=f"out{i}"))
        victim = [r for r in run_ledger.load_entries() if r["title"] == "run1"]
        run_ledger.remove_entries(victim)
        assert {r["title"] for r in run_ledger.load_entries()} == {"run0", "run2"}

    def test_a_note_targets_only_its_own_row(self, ledger):
        now = time.time()
        for i in range(3):
            run_ledger.add_entry(entry(title=f"run{i}", ts=now + i, pathout=f"out{i}"))
        target = [r for r in run_ledger.load_entries() if r["title"] == "run1"][0]
        run_ledger.set_note(target, "this one")
        noted = [r["title"] for r in run_ledger.load_entries() if r.get("note")]
        assert noted == ["run1"]

    def test_rows_sharing_a_key_are_treated_as_one(self, ledger):
        """Documented consequence, not a recommendation: two entries with the same
        timestamp-to-the-millisecond AND the same settings AND the same PathOut are
        indistinguishable, so removing one removes both and a note lands on both.
        Reachable only by two runs of the same file writing to the same folder and
        finishing in the same millisecond."""
        ts = time.time()
        run_ledger.add_entry(entry(title="a", ts=ts, pathout="same"))
        run_ledger.add_entry(entry(title="b", ts=ts, pathout="same"))
        first = run_ledger.load_entries()[0]
        run_ledger.remove_entries([first])
        assert run_ledger.load_entries() == []
