"""Points for runs - the pure parts (`run_ledger.settings_timesteps`, the ledger
listener hook, `account_runs`). No Qt widgets, no network.

The timestep count must read StepStart/StepEnd the way CWatM does
(`cwatm/management_modules/timestep.py` Calendar): StepEnd is a date *or* a timestep
count, dates are day-first with / . or - and a 2- or 4-digit year, and a key given
twice counts by its last value. The offline queue must never credit one user's runs to
another user logging in on the same computer.
"""

import pytest

from src.gui.utils import account_runs, run_ledger


def settings(start, end, extra=""):
    return (f"[TIME-RELATED_CONSTANTS]\nStepStart = {start}\nSpinUp = None\n"
            f"StepEnd = {end}\n{extra}")


class TestSettingsTimesteps:
    @pytest.mark.parametrize("start,end,steps", [
        ("1/1/1990", "31/12/1990", 365),
        ("01/01/2000", "31/12/2000", 366),            # leap year
        ("1.1.1990", "10.1.1990", 10),                # dots
        ("1-1-1990", "1-1-1990", 1),                  # dashes, one day
        ("1/1/90", "31/1/90", 31),                    # 2-digit year
        ("1/1/1990", "400", 400),                     # StepEnd as a count
        ("1/1/1990", "400.0", 400),
    ])
    def test_counts_like_cwatm(self, start, end, steps):
        assert run_ledger.settings_timesteps(settings(start, end)) == steps

    @pytest.mark.parametrize("content", [
        None, "", "[OPTIONS]\nx = 1",
        settings("1/1/1990", ""),                     # no end
        settings("", "31/12/1990"),                   # date end without start
        settings("31/12/1990", "1/1/1990"),           # end before start
        settings("1/1/1990", "0"),
        settings("1/1/1990", "not a date"),
    ])
    def test_unknown_is_none(self, content):
        assert run_ledger.settings_timesteps(content) is None

    def test_last_value_wins_and_comments_are_ignored(self):
        content = settings("1/1/1990", "31/12/1990",
                           extra="# StepEnd = 5\nStepEnd = 10  # short test\n")
        assert run_ledger.settings_timesteps(content) == 10

    def test_key_case_does_not_matter(self):
        assert run_ledger.settings_timesteps("stepstart = 1/1/1990\nSTEPEND = 5") == 5


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(run_ledger, "history_dir", lambda: str(tmp_path))
    monkeypatch.setattr(run_ledger, "retention_days", lambda: 0)
    return tmp_path


class TestLedgerHook:
    def test_make_entry_records_timesteps(self, ledger):
        e = run_ledger.make_entry("a.ini", "t", "out", 0, True, 1.0,
                                  content=settings("1/1/1990", "31/12/1990"))
        assert e["timesteps"] == 365

    def test_no_timesteps_key_when_unknown(self, ledger):
        e = run_ledger.make_entry("a.ini", "t", "out", 0, True, 1.0, content=None)
        assert "timesteps" not in e

    def test_listener_sees_every_entry_even_if_the_file_fails(self, ledger,
                                                              monkeypatch):
        seen = []
        run_ledger.add_listener(seen.append)
        try:
            run_ledger.add_entry({"uid": "1", "title": "ok"})
            monkeypatch.setattr(run_ledger, "ledger_path",
                                lambda: str(ledger / "no" / "such" / "dir" / "x.json"))
            monkeypatch.setattr(run_ledger.os, "makedirs",
                                lambda *a, **k: (_ for _ in ()).throw(OSError("ro")))
            run_ledger.add_entry({"uid": "2", "title": "unwritable"})
        finally:
            run_ledger.remove_listener(seen.append)
        assert [e["uid"] for e in seen] == ["1", "2"]

    def test_a_failing_listener_does_not_break_logging(self, ledger):
        def boom(_entry):
            raise RuntimeError("listener bug")
        run_ledger.add_listener(boom)
        try:
            run_ledger.add_entry({"uid": "1", "title": "still written"})
        finally:
            run_ledger.remove_listener(boom)
        assert [e["uid"] for e in run_ledger.load_entries()] == ["1"]


class TestQualifies:
    H = "f" * 64

    @pytest.mark.parametrize("entry,ok", [
        ({"uid": "u", "success": True, "kind": "run", "settings_hash": H}, True),
        ({"uid": "u", "success": True, "kind": "hidden", "settings_hash": H}, True),
        ({"uid": "u", "success": True, "kind": "batch", "settings_hash": H}, True),
        ({"uid": "u", "success": False, "kind": "run", "settings_hash": H}, False),
        ({"uid": "u", "success": True, "kind": "stopped", "settings_hash": H}, False),
        ({"success": True, "kind": "run", "settings_hash": H}, False),   # no uid
        ({"uid": "u", "success": True, "kind": "run"}, False),   # no fingerprint
    ])
    def test_qualifies(self, entry, ok):
        assert account_runs.qualifies(entry) is ok

    def test_meta_sends_only_what_the_rules_need(self):
        entry = {"uid": "u", "success": True, "kind": "batch", "timesteps": 365,
                 "duration_s": 12.34, "settings": "C:/secret/a.ini",
                 "title": "My basin", "pathout": "C:/out", "settings_hash": self.H}
        assert account_runs.run_meta(entry, "1.07") == {
            "timesteps": 365, "settings_hash": self.H}


class TestPendingQueue:
    def test_add_and_read_per_user(self, ledger):
        account_runs.add_pending("a" * 32, {"kind": "run"}, "Blabla")
        account_runs.add_pending("b" * 32, {"kind": "run"}, "other")
        assert [i["uid"] for i in account_runs.pending_for("blabla")] == ["a" * 32]
        assert [i["uid"] for i in account_runs.pending_for("OTHER")] == ["b" * 32]

    def test_same_run_is_kept_once(self, ledger):
        account_runs.add_pending("a" * 32, {}, "Blabla")
        account_runs.add_pending("a" * 32, {}, "Blabla")
        assert len(account_runs.pending_for("Blabla")) == 1

    def test_remove_and_file_disappears_when_empty(self, ledger):
        account_runs.add_pending("a" * 32, {}, "Blabla")
        account_runs.remove_pending("a" * 32)
        assert account_runs.pending_for("Blabla") == []
        assert not (ledger / "account_pending.json").exists()

    def test_old_entries_expire(self, ledger, monkeypatch):
        account_runs.add_pending("a" * 32, {}, "Blabla")
        later = account_runs.time.time() + (account_runs._MAX_AGE_DAYS + 1) * 86400
        monkeypatch.setattr(account_runs.time, "time", lambda: later)
        assert account_runs.pending_for("Blabla") == []

    def test_no_user_no_queue(self, ledger):
        account_runs.add_pending("a" * 32, {}, "")
        assert account_runs.load_pending() == []

    def test_corrupt_file_reads_as_empty(self, ledger):
        (ledger / "account_pending.json").write_text("{not json", encoding="utf-8")
        assert account_runs.load_pending() == []


BASE = """[FILE_PATHS]
PathRoot = C:/data
PathOut = C:/out/run1
[OPTIONS]
includeGlaciers = False
[TIME-RELATED_CONSTANTS]
StepStart = 1/1/1990
StepEnd = 31/12/1990
[SNOW]
SnowFactor = 1.0
[OUTPUT]
OUT_TSS_Daily = discharge
"""


class TestSettingsFingerprint:
    """'The same settings run again' - what counts as the same setup."""

    def fp(self, content):
        return run_ledger.settings_fingerprint(content)

    def test_is_a_sha256_hex(self):
        assert re_fullmatch_hex64(self.fp(BASE))

    @pytest.mark.parametrize("variant", [
        BASE.replace("SnowFactor = 1.0", "SnowFactor   =   1.0   # tuned"),  # spacing, comment
        BASE.replace("SnowFactor", "snowfactor"),                            # key case
        BASE + "\n# a new comment line\n\n",                                 # comments, blanks
        BASE.replace("PathOut = C:/out/run1", "PathOut = D:/elsewhere"),     # PathOut
        BASE.replace("[OPTIONS]", "Title = my new name\n[OPTIONS]"),         # Title
        BASE.replace("OUT_TSS_Daily = discharge", "OUT_MAP_Daily = runoff"), # outputs
        "[SNOW]\nSnowFactor = 1.0\n" + BASE.replace("[SNOW]\nSnowFactor = 1.0\n", ""),
    ])
    def test_cosmetic_changes_are_the_same_setup(self, variant):
        assert self.fp(variant) == self.fp(BASE)

    @pytest.mark.parametrize("variant", [
        BASE.replace("SnowFactor = 1.0", "SnowFactor = 1.1"),                # a parameter
        BASE.replace("StepEnd = 31/12/1990", "StepEnd = 31/12/1991"),        # the period
        BASE.replace("includeGlaciers = False", "includeGlaciers = True"),   # an option
        BASE.replace("PathRoot = C:/data", "PathRoot = C:/other_data"),      # the input data
    ])
    def test_a_model_change_is_a_new_setup(self, variant):
        assert self.fp(variant) != self.fp(BASE)

    def test_last_duplicate_wins(self):
        assert self.fp(BASE + "SnowFactor = 1.1\n") == \
            self.fp(BASE.replace("SnowFactor = 1.0", "SnowFactor = 1.1"))

    @pytest.mark.parametrize("content", [None, "", "# only a comment\n[SECTION]\n"])
    def test_nothing_to_fingerprint(self, content):
        assert self.fp(content) is None

    def test_make_entry_and_meta_carry_it(self, ledger):
        e = run_ledger.make_entry("a.ini", "t", "out", 0, True, 1.0, content=BASE)
        assert e["settings_hash"] == self.fp(BASE)
        assert account_runs.run_meta(dict(e, kind="run"), "1.07")["settings_hash"] == \
            self.fp(BASE)


def re_fullmatch_hex64(value):
    import re
    return bool(value) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


class TestSettingsGauge:
    @pytest.mark.parametrize("value,expected", [
        ("17.25 48.60", (17.25, 48.60)),
        ("17.25 48.60 18.1 49.2", (17.25, 48.60)),          # first pair only
        ("17.25, 48.60", (17.25, 48.60)),                   # commas
        ("-60.5 -3.2  # Amazon", (-60.5, -3.2)),            # comment
    ])
    def test_first_pair(self, value, expected):
        content = f"[MASK_OUTLET]\nMaskMap = 17 48\nGauges = {value}\n"
        assert run_ledger.settings_gauge(content) == expected

    @pytest.mark.parametrize("value", [
        "$(FILE_PATHS:PathRoot)/gauges.map",                # a map file
        "C:/data/gauges.tif",
        "4523000 1250000",                                  # projected x/y (UTM)
        "17.25",                                            # half a pair
        "0 0",                                              # the "unset" pair
        "",
    ])
    def test_no_location(self, value):
        assert run_ledger.settings_gauge(f"Gauges = {value}\n") is None

    def test_last_gauges_line_counts(self):
        content = "Gauges = 1 1\n[OTHER]\nGauges = 17.25 48.6\n"
        assert run_ledger.settings_gauge(content) == (17.25, 48.6)

    def test_make_entry_keeps_it_locally(self, ledger):
        e = run_ledger.make_entry("a.ini", "t", "out", 0, True, 1.0,
                                  content="Gauges = 17.25 48.6\n")
        assert e["gauge"] == [17.25, 48.6]
        assert account_runs.location_of(e) == (17.25, 48.6)

    @pytest.mark.parametrize("gauge", [None, [], [1], ["x", 2], [200, 10]])
    def test_location_of_rejects(self, gauge):
        assert account_runs.location_of({"gauge": gauge}) is None

    def test_location_is_not_part_of_the_points_request(self):
        meta = account_runs.run_meta({"kind": "run", "gauge": [17.25, 48.6],
                                      "timesteps": 400}, "1.07")
        assert "gauge" not in meta and not any("48.6" in str(v) for v in meta.values())
