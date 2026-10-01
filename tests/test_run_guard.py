"""The early output-entry check (src/gui/utils/run_guard.py, security.md #1).

CWatM no longer evaluates output entries: data_handling.parseoutvar accepts an entry
only when it fully matches a name + whole-number indices and otherwise stops with
Error 135. The GUI check must give EXACTLY that verdict - before the run, with the
line named - so these tests compare it with CWatM's own parseoutvar.
"""

import pytest

from src.gui.utils import run_guard as G

INI = """[FILE_PATHS]
PathRoot = C:/data
[OPTIONS]
out_strange = whatever(1)
[OUTPUT]
OUT_Dir = $(FILE_PATHS:PathRoot)/out
OUT_MAP_Daily = discharge, actualET[1], rootDepth[0][1]
OUT_TSS_Daily = None
OUT_TSS_MonthTot = {tss}
"""

ACCEPTED = ["discharge", "WaterCycle", "actualET[1]", "rootDepth[0][1]",
            "discharge[-1]", "x_1", "_private", "Präzip"]
REFUSED = ["discharge[__import__('os').system('calc')]", "discharge[1+1]",
           "__import__('os').system('calc')", "discharge.__class__",
           "$(FILE_PATHS:PathRoot)", "discharge  # comment", "dis charge",
           "discharge[]", "discharge[1.5]", "1discharge"]


def _problems(tss):
    return G.output_problems(INI.format(tss=tss))


@pytest.mark.parametrize("tss", ["discharge", "WaterCycle", "", "None",
                                 "discharge, Precipitation", "discharge[-1]"])
def test_accepted_values_pass(tss):
    assert _problems(tss) == []


@pytest.mark.parametrize("entry", REFUSED)
def test_refused_entries_are_found_on_their_line(entry):
    (row, key, found, _why), = _problems(entry)
    assert (key, found) == ("OUT_TSS_MonthTot", entry)
    assert INI.format(tss=entry).split("\n")[row].startswith("OUT_TSS_MonthTot")


def test_an_empty_entry_after_the_first_is_refused_like_cwatm():
    # splitout turns only an empty FIRST entry into "None"
    assert _problems("discharge,") and _problems("discharge,,Precipitation")
    assert _problems("") == []
    # ", " = two empty entries: the first becomes None, the second is refused
    assert [p[2] for p in _problems(", ")] == [""]


def test_options_section_and_dir_keys_are_not_output_entries():
    # CWatM reads [OPTIONS] as booleans and *_Dir as a folder
    assert _problems("discharge") == []


def test_a_continuation_line_is_part_of_the_value():
    content = INI.format(tss="discharge,\n    evil[__import__('os')]")
    assert [p[2] for p in G.output_problems(content)] == ["evil[__import__('os')]"]


def test_same_verdict_as_cwatm_parseoutvar():
    """The real CWatM function decides; the GUI must agree on every case."""
    dh = pytest.importorskip("cwatm.management_modules.data_handling")
    if not hasattr(dh, "parseoutvar"):
        pytest.skip("this cwatm/ has no parseoutvar")
    for entry in ACCEPTED + REFUSED:
        try:
            dh.parseoutvar(entry)
            cwatm_ok = True
        except Exception:
            cwatm_ok = False
        gui_ok = G.OUTVARNAME.fullmatch(entry) is not None
        assert gui_ok == cwatm_ok, entry


def test_the_gui_pattern_is_cwatm_s_pattern():
    dh = pytest.importorskip("cwatm.management_modules.data_handling")
    if not hasattr(dh, "_OUTVARNAME"):
        pytest.skip("this cwatm/ has no _OUTVARNAME")
    assert G.OUTVARNAME.pattern == dh._OUTVARNAME.pattern


def test_check_lists_readable_lines():
    lines = G.check(INI.format(tss="discharge[x]"))
    assert len(lines) == 1 and lines[0].startswith("line 9: OUT_TSS_MonthTot")


@pytest.mark.qt          # imports a Qt module
def test_check_settingsfile_marks_the_same_lines():
    from tests.test_settings_check import Host      # the bare host of that suite
    probs = Host()._semantic_settings_problems(
        INI.format(tss="discharge[__import__('os')]"))
    assert any("Error 135" in m for _r, m in probs)
