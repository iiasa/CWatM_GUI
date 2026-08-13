"""The Check settingsfile semantic pass (`src/gui/components/settings_check.py`).

`_semantic_settings_problems` is the part of F4 that goes beyond "does the file exist":
date ordering, `[OPTIONS]` dependencies, and the `out_*` output grammar. It is a mixin
method whose only `self` use is `_forcing_time_range` (itself pure), so it can be
exercised on a bare host object - no window, no Qt widgets.

It returns a list of `(row_index_or_None, message)`. Row indices are **0-based**; the
output box adds 1 when it prints them.
"""

import pytest

from src.gui.components.settings_check import SettingsCheckMixin

# Needs Qt: settings_check imports QDate, and pulls rasterio in via basin_viewer.
# The dependency-free CI job selects with `pytest -m "not qt"`.
pytestmark = pytest.mark.qt


class Host(SettingsCheckMixin):
    """Minimal carrier for the mixin - the method under test needs nothing else."""


@pytest.fixture
def host():
    return Host()


def problems(host, content, config=None, base_dir=""):
    return host._semantic_settings_problems(content, config, base_dir)


def messages(host, content, **kw):
    return [m for _row, m in problems(host, content, **kw)]


def has(msgs, *fragments):
    """True when some message contains every fragment."""
    return any(all(f in m for f in fragments) for m in msgs)


BASE_DATES = """[TIME-RELATED_CONSTANTS]
StepStart = 1/1/2000
SpinUp = 1/1/2001
StepEnd = 31/12/2010
"""


class TestDateOrdering:
    def test_a_correct_order_reports_nothing(self, host):
        assert messages(host, BASE_DATES) == []

    def test_spinup_before_start(self, host):
        msgs = messages(host, """StepStart = 1/1/2005
SpinUp = 1/1/2000
StepEnd = 1/1/2010
""")
        assert has(msgs, "SpinUp", "before StepStart")

    def test_end_before_start(self, host):
        msgs = messages(host, """StepStart = 1/1/2005
StepEnd = 1/1/2000
""")
        assert has(msgs, "StepEnd", "before StepStart")

    def test_end_before_spinup(self, host):
        msgs = messages(host, """StepStart = 1/1/2000
SpinUp = 1/1/2008
StepEnd = 1/1/2005
""")
        assert has(msgs, "StepEnd", "before SpinUp")

    def test_stepstart_must_be_a_date(self, host):
        msgs = messages(host, "StepStart = not-a-date\n")
        assert has(msgs, "StepStart", "not a valid date")

    def test_integer_spinup_is_a_timestep_count_not_an_error(self, host):
        # CWatM allows SpinUp/StepEnd as an integer number of timesteps.
        assert messages(host, """StepStart = 1/1/2000
SpinUp = 100
StepEnd = 3650
""") == []

    @pytest.mark.parametrize("value", ["1/1/2000", "01/01/2000", "2000-01-01"])
    def test_accepted_date_formats(self, host, value):
        assert messages(host, f"StepStart = {value}\nStepEnd = 1/1/2010\n") == []

    def test_the_row_index_points_at_the_offending_line(self, host):
        content = "[TIME]\nStepStart = 1/1/2005\nStepEnd = 1/1/2000\n"
        found = [(r, m) for r, m in problems(host, content) if "StepEnd" in m]
        assert found and found[0][0] == 2      # 0-based: the third line

    def test_commented_keys_are_ignored(self, host):
        assert messages(host, """StepStart = 1/1/2000
# StepEnd = 1/1/1990
StepEnd = 1/1/2010
""") == []

    def test_missing_dates_report_nothing(self, host):
        assert messages(host, "[OPTIONS]\nsomething = True\n") == []


class TestOutputGrammar:
    """CWatM *silently ignores* an invalid OUT_MAP_ key - no error, just no output -
    so this check is the only thing standing between a typo and a missing result."""

    @pytest.mark.parametrize("key", [
        "OUT_TSS_Daily", "OUT_TSS_MonthTot", "OUT_TSS_MonthAvg", "OUT_TSS_MonthEnd",
        "OUT_TSS_AnnualTot", "OUT_TSS_TotalAvg",
        "OUT_MAP_Daily", "OUT_MAP_MonthTot", "OUT_MAP_TotalEnd", "OUT_MAP_Once",
        "OUT_MAP_12month", "OUT_MAP_MonthMid",
        "OUT_TSS_AreaSum_MonthTot", "OUT_TSS_AreaAvg_Daily",
    ])
    def test_valid_keys_are_accepted(self, host, key):
        content = f"[OUTPUT]\n{key} = discharge\n"
        assert not has(messages(host, content), key.lower()), key

    def test_map_has_no_area_aggregation(self, host):
        # The documented trap: CWatM ignores this silently.
        msgs = messages(host, "[OUTPUT]\nOUT_MAP_AreaSum_MonthTot = discharge\n")
        assert msgs, "an AreaSum map key must be reported"

    def test_unknown_time_type(self, host):
        assert messages(host, "[OUTPUT]\nOUT_TSS_Weekly = discharge\n")

    def test_totalend_is_map_only(self, host):
        # outputTypTss (cwatm globals.py) has no 'totalend'.
        assert messages(host, "[OUTPUT]\nOUT_TSS_TotalEnd = discharge\n")
        assert not messages(host, "[OUTPUT]\nOUT_MAP_TotalEnd = discharge\n")

    def test_out_keys_in_options_are_not_output_keys(self, host):
        assert messages(host, "[OPTIONS]\nout_something = True\n") == []


class TestOutputVariableNames:
    def test_a_real_variable_is_accepted(self, host):
        assert messages(host, "[OUTPUT]\nOUT_TSS_Daily = discharge\n") == []

    def test_several_variables_on_one_line(self, host):
        assert messages(host, "[OUTPUT]\nOUT_TSS_Daily = discharge, runoff\n") == []

    def test_unknown_variable_is_reported(self, host):
        msgs = messages(host, "[OUTPUT]\nOUT_TSS_Daily = notAVariable\n")
        assert has(msgs, "notAVariable")

    def test_wrong_case_is_reported_with_the_right_spelling(self, host):
        msgs = messages(host, "[OUTPUT]\nOUT_TSS_Daily = Discharge\n")
        assert has(msgs, "discharge")

    def test_watercycle_is_allowed(self, host):
        assert messages(host, "[OUTPUT]\nOUT_TSS_AreaSum_MonthTot = WaterCycle\n") == []

    @pytest.mark.parametrize("value", ["None", ""])
    def test_disabled_output_is_skipped(self, host, value):
        assert messages(host, f"[OUTPUT]\nOUT_TSS_Daily = {value}\n") == []

    def test_lowercase_none_is_correctly_reported(self, host):
        """Not a typo in the checker: CWatM's sentinel test is `!= "None"`, exactly
        case-sensitive (`configuration.py:249`, `output.py:198/1037/1178`), so a
        lowercase `none` is taken as a variable name and would raise CWatM's Error 132
        at run start. Flagging it here is the whole point of the check."""
        assert messages(host, "[OUTPUT]\nOUT_TSS_Daily = none\n")

    def test_array_variable_without_an_index_is_reported(self, host):
        msgs = messages(host, "[OUTPUT]\nOUT_MAP_Daily = actualET\n")
        assert has(msgs, "actualET")

    def test_array_variable_with_a_valid_index_is_accepted(self, host):
        assert messages(host, "[OUTPUT]\nOUT_MAP_Daily = actualET[1]\n") == []

    def test_array_variable_with_an_out_of_range_index_is_reported(self, host):
        assert messages(host, "[OUTPUT]\nOUT_MAP_Daily = actualET[9]\n")

    def test_two_dimensional_variable_needs_both_indices(self, host):
        assert messages(host, "[OUTPUT]\nOUT_MAP_Daily = rootDepth[0]\n")
        assert messages(host, "[OUTPUT]\nOUT_MAP_Daily = rootDepth[0][1]\n") == []


class TestOptionDependencies:
    def test_modflow_off_needs_nothing(self, host):
        assert messages(host, "[OPTIONS]\nmodflow_coupling = False\n") == []

    def test_modflow_on_without_its_keys_flags_the_option(self, host):
        rows = problems(host, "[OPTIONS]\nmodflow_coupling = True\n")
        assert rows
        row, msg = rows[0]
        assert row == 1                        # the option's OWN line, 0-based
        assert "modflow_coupling = True" in msg
        assert "not set" in msg

    def test_the_message_names_every_missing_key(self, host):
        msgs = messages(host, "[OPTIONS]\nmodflow_coupling = True\n")
        joined = " ".join(msgs)
        for key in ("path_mf6dll", "PathGroundwaterModflow", "nameModflowModel",
                    "Modflow_resolution"):
            assert key in joined

    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
    def test_truthy_spellings_all_switch_the_option_on(self, host, value):
        assert messages(host, f"[OPTIONS]\nmodflow_coupling = {value}\n")

    @pytest.mark.parametrize("value", ["false", "0", "no", "off"])
    def test_falsy_spellings_all_leave_it_off(self, host, value):
        assert messages(host, f"[OPTIONS]\nmodflow_coupling = {value}\n") == []

    def test_a_set_but_missing_modflow_input_dir_does_not_flag_the_option(self, host):
        """PathGroundwaterModflow is _REQUIRE_SET_ONLY: MODFLOW input is normally
        preprocessed, so a set-but-absent directory must not turn the option red."""
        content = ("[OPTIONS]\nmodflow_coupling = True\n"
                   "path_mf6dll = /nope/mf6.dll\n"
                   "PathGroundwaterModflow = /definitely/not/here\n"
                   "nameModflowModel = model\nModflow_resolution = 100\n")
        msgs = messages(host, content, base_dir="")
        joined = " ".join(msgs)
        assert "PathGroundwaterModflow" not in joined
        assert "path_mf6dll" in joined         # the solver DLL still must exist

    def test_all_keys_present_and_existing_is_clean(self, host, tmp_path):
        dll = tmp_path / "mf6.dll"
        dll.write_text("x")
        content = (f"[OPTIONS]\nmodflow_coupling = True\n"
                   f"path_mf6dll = {dll}\n"
                   f"PathGroundwaterModflow = {tmp_path}\n"
                   f"nameModflowModel = model\nModflow_resolution = 100\n")
        assert messages(host, content) == []


class TestRobustness:
    """F4 runs on whatever is in the editor, including half-typed files."""

    @pytest.mark.parametrize("content", [
        "", "   ", "\n\n\n", "[OPTIONS]", "no equals sign here",
        "= value with no key", "[UNCLOSED\nStepStart = 1/1/2000\n",
    ])
    def test_never_raises(self, host, content):
        assert isinstance(problems(host, content), list)

    def test_returns_row_message_pairs(self, host):
        for row, msg in problems(host, "StepStart = rubbish\n"):
            assert row is None or isinstance(row, int)
            assert isinstance(msg, str) and msg
