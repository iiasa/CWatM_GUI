"""Tools ▸ Check Data - the worker that runs CWatM's ``-c`` data check.

The check runs CWatM **inside the GUI process** (``run_cwatm.main``), so it inherits
whatever an earlier in-process CWatM call left in CWatM's global ``Flags``.
``run_cwatm.main`` clears CWatM's other globals but not ``Flags``; an earlier
``mainwarm -vgm`` (coordinate MaskMap: gauge-in-mask check / Show Basin) leaves
``Flags['maskmap']`` set, the model's ``initial()`` then returns before
``readmeteo.initial`` and the check died with
``AttributeError: 'Variables' object has no attribute 'preMaps'``.

Two tests: a fast one that needs no data (the worker hands CWatM clean Flags), and a
real check over ``settings_rhine5min1.ini`` that is skipped where its input is not
reachable.
"""

import configparser
import os

import pytest

pytestmark = pytest.mark.qt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RHINE = os.path.join(ROOT, "settings_rhine5min1.ini")


def _run_worker(settings, netcdf=None, log=None):
    """Run the worker synchronously (``run()``, not ``start()``) and return what its
    ``done`` signal carried: (success, checkinfo, error). ``log`` (a list) collects
    what the check printed - what the window's log pane shows."""
    from src.gui.widgets.check_data_window import _CheckWorker
    worker = _CheckWorker(settings, netcdf)
    result = []
    worker.done.connect(lambda ok, info, err: result.append((ok, info, err)))
    if log is not None:
        worker.output.connect(lambda text, is_error: log.append(str(text)))
    worker.run()
    assert len(result) == 1, "done must be emitted exactly once"
    return result[0]


def _stale_vgm_flags():
    """What an in-process ``mainwarm(file, ['-vgm'], [])`` leaves behind."""
    from cwatm.management_modules.globals import Flags
    Flags["veryquiet"] = True
    Flags["gui"] = True
    Flags["maskmap"] = True
    return Flags


def test_worker_resets_stale_cwatm_flags(qapp, monkeypatch):
    import cwatm.run_cwatm as run_cwatm
    _stale_vgm_flags()
    seen = {}

    def fake_main(settings, args):
        from cwatm.management_modules.globals import Flags
        seen.update(Flags)
        seen["_args"] = list(args)
        return True, "checkinfo"

    monkeypatch.setattr(run_cwatm, "main", fake_main)
    ok, info, err = _run_worker("settings.ini")

    assert (ok, info, err) == (True, "checkinfo", "")
    assert seen.pop("_args") == ["-c"]
    on = [k for k, v in seen.items() if v]
    assert not on, f"CWatM got stale flags from an earlier in-process call: {on}"


def test_worker_reports_an_exception_instead_of_raising(qapp, monkeypatch):
    import cwatm.run_cwatm as run_cwatm

    def broken_main(settings, args):
        raise RuntimeError("boom")

    monkeypatch.setattr(run_cwatm, "main", broken_main)
    ok, info, err = _run_worker("settings.ini")
    assert ok is False and info is None
    assert "boom" in err


def _rhine_input_reachable():
    if not os.path.isfile(RHINE):
        return False
    cfg = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        cfg.read(RHINE, encoding="utf-8")
        root = cfg.get("FILE_PATHS", "PathRoot").strip()
    except Exception:  # noqa: BLE001 - unreadable settings = no data here
        return False
    return os.path.isdir(root)


@pytest.mark.skipif(not _rhine_input_reachable(),
                    reason="input data of settings_rhine5min1.ini not reachable")
def test_check_data_runs_on_real_settings_after_a_mask_call(qapp, monkeypatch, tmp_path):
    """The reported failure end to end: stale -vgm Flags, then a real ``-c`` check.

    The check may still stop on a missing input file further on - that is the check
    doing its job on an incomplete dataset. What must not happen is the ``preMaps``
    crash when the meteo forcing is read."""
    monkeypatch.chdir(tmp_path)      # CWatM may drop files into the working dir
    # The Rhine set lacks init/baseflow_totalavg.nc, which waterdemand.initial reads
    # only while swAbstractionFrac < 0 - a fixed fraction lets the check reach the
    # first timestep (readmeteo.dynamic), where the stale-Flags crash happened.
    with open(RHINE, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    lines = ["swAbstractionFrac = 0.5" if ln.split("=")[0].strip() == "swAbstractionFrac"
             else ln for ln in lines]
    settings = tmp_path / "settings_rhine_check.ini"
    settings.write_text("\n".join(lines) + "\n", encoding="utf-8")

    flags = _stale_vgm_flags()
    log = []
    try:
        ok, info, err = _run_worker(str(settings), log=log)
    finally:
        for key in flags:
            flags[key] = False

    text = "".join(log) + err
    assert "preMaps" not in text, "readmeteo.initial was skipped (stale Flags)"
    assert "PrecipitationMaps" in text, "the check never reached the meteo forcing"
    if ok:
        assert info, "No check data returned from CWatM"
