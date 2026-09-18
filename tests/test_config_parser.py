"""`src/gui/components/config_parser.py` - ConfigParser.

Pure line-based INI parsing/rewriting used by `main_window`'s auto-apply of field
changes (Start/Spin/End Date, PathOut, MaskMap, Gauges - see the Auto-apply behavioral
note in CLAUDE.md) and by `date_manager`/`tab_manager` to read dates on tab switch.
Every method works on a plain string, so it needs no window - only Qt itself, since
`parse_date_value` goes through `QDate.fromString`.

"""

import pytest

from PySide6.QtCore import QDate

from src.gui.components.config_parser import ConfigParser

pytestmark = pytest.mark.qt


@pytest.fixture
def cp():
    return ConfigParser()


class TestParseContent:
    def test_extracts_dates_and_settings(self, cp):
        content = ("[TIME-RELATED_CONSTANTS]\nStepStart = 1/1/2000\nSpinUp = 1/1/2001\n"
                   "StepEnd = 31/12/2010\n\n[FILE_PATHS]\nPathOut = out\n"
                   "MaskMap = mask.nc\nGauges = 1,2\n")
        dates, settings = cp.parse_content(content)
        assert dates == {"stepstart": "1/1/2000", "spinup": "1/1/2001",
                          "stepend": "31/12/2010"}
        assert settings == {"pathout": "out", "maskmap": "mask.nc", "gauges": "1,2"}

    def test_keys_are_matched_case_insensitively(self, cp):
        dates, settings = cp.parse_content("STEPSTART = 1/1/2000\nPathout = out\n")
        assert dates == {"stepstart": "1/1/2000"}
        assert settings == {"pathout": "out"}

    def test_commented_lines_are_ignored(self, cp):
        dates, _ = cp.parse_content("# StepStart = 1/1/1999\n; StepEnd = 1/1/1999\n"
                                     "StepStart = 1/1/2000\n")
        assert dates == {"stepstart": "1/1/2000"}

    def test_duplicate_key_keeps_the_last_occurrence(self, cp):
        _dates, settings = cp.parse_content("PathOut = first\nPathOut = second\n")
        assert settings["pathout"] == "second"

    def test_unrelated_keys_are_ignored(self, cp):
        dates, settings = cp.parse_content("Title = My run\nsome_flag = True\n")
        assert dates == {}
        assert settings == {}

    def test_state_is_reset_on_each_call(self, cp):
        cp.parse_content("PathOut = out\n")
        dates, settings = cp.parse_content("StepStart = 1/1/2000\n")
        assert settings == {}                 # not leaked from the previous parse
        assert dates == {"stepstart": "1/1/2000"}

    def test_stores_raw_content_and_return_value_matches_attributes(self, cp):
        dates, settings = cp.parse_content("PathOut = out\n")
        assert cp.current_content == "PathOut = out\n"
        assert cp.date_values is dates
        assert cp.settings_values is settings


class TestGetCurrentValues:
    """get_current_date_values / get_current_settings_values - standalone readers,
    same extraction rules as parse_content but without touching parser state."""

    def test_get_current_date_values(self, cp):
        content = "StepStart=1/1/2000\n# StepEnd=1/1/1999\nStepEnd=1/1/2010\n"
        assert cp.get_current_date_values(content) == {
            "stepstart": "1/1/2000", "stepend": "1/1/2010"}

    def test_get_current_settings_values(self, cp):
        content = "PathOut = C:\\x\nMaskMap = m.nc\nGauges = 1,2\nOther=5\n"
        assert cp.get_current_settings_values(content) == {
            "pathout": "C:\\x", "maskmap": "m.nc", "gauges": "1,2"}

    def test_does_not_mutate_parser_state(self, cp):
        cp.parse_content("PathOut = keep\n")
        cp.get_current_date_values("StepStart = 1/1/2000\n")
        assert cp.settings_values == {"pathout": "keep"}


class TestUpdateDates:
    def test_rewrites_all_three_date_lines(self, cp):
        content = "StepStart = 1/1/2000\nSpinUp = 1/1/2001\nStepEnd = 31/12/2010\n"
        out = cp.update_dates(content, QDate(2020, 3, 4), QDate(2020, 3, 5),
                               QDate(2020, 3, 6))
        assert out == ("StepStart = 04/03/2020\nSpinUp = 05/03/2020\n"
                        "StepEnd = 06/03/2020\n")

    def test_other_lines_are_left_untouched(self, cp):
        content = "[TIME]\nTitle = keep me\nStepStart = 1/1/2000\n"
        out = cp.update_dates(content, QDate(2020, 1, 1), QDate(2020, 1, 2),
                               QDate(2020, 1, 3))
        lines = out.split('\n')
        assert lines[0] == "[TIME]"
        assert lines[1] == "Title = keep me"

    def test_missing_date_keys_leave_content_unchanged(self, cp):
        content = "PathOut = out\n"
        out = cp.update_dates(content, QDate(2020, 1, 1), QDate(2020, 1, 2),
                               QDate(2020, 1, 3))
        assert out == content


class TestUpdateSettings:
    def test_rewrites_only_the_requested_keys(self, cp):
        content = "PathOut = C:\\old\nMaskMap = mask.nc\nGauges = 1,2\n"
        out = cp.update_settings(content, {"pathout": "C:\\new", "gauges": "3,4"})
        assert out == "PathOut = C:\\new\nMaskMap = mask.nc\nGauges = 3,4\n"

    def test_lookup_is_by_lowercased_key(self, cp):
        out = cp.update_settings("PathOut = old\n", {"pathout": "new"})
        assert "new" in out

    def test_unknown_settings_dict_keys_are_simply_not_applied(self, cp):
        content = "PathOut = old\n"
        out = cp.update_settings(content, {"nosuchkey": "value"})
        assert out == content

    def test_commented_lines_are_never_rewritten(self, cp):
        content = "# PathOut = commented\n"
        out = cp.update_settings(content, {"pathout": "new"})
        assert out == content


class TestParseDateValue:
    @pytest.mark.parametrize("value,expected", [
        ("01/02/2021", (2021, 2, 1)),
        ("1/2/2021", (2021, 2, 1)),
        ("2021-02-01", (2021, 2, 1)),
    ])
    def test_accepted_formats(self, cp, value, expected):
        d = cp.parse_date_value(value)
        assert (d.year(), d.month(), d.day()) == expected

    def test_invalid_string_returns_none(self, cp):
        assert cp.parse_date_value("not-a-date") is None

    def test_empty_string_returns_none(self, cp):
        assert cp.parse_date_value("") is None

    def test_none_returns_none(self, cp):
        assert cp.parse_date_value(None) is None


