"""Excel-style autofill (`src/gui/utils/cell_fill.py`).

The rule that matters most: a **single** source cell is copied, never extrapolated.
Excel guesses a series from one cell in some cases; this deliberately does not, because
silently turning one reservoir ID into a counting sequence would corrupt a settings
sheet.
"""

import pytest

from src.gui.utils.cell_fill import extend_series


class TestSingleCellCopies:
    def test_one_number_is_repeated_not_continued(self):
        assert extend_series(["5"], 3) == ["5", "5", "5"]

    def test_one_list_name_is_repeated_not_continued(self):
        # Two names would continue the weekday list; one must not.
        assert extend_series(["Mon"], 3) == ["Mon", "Mon", "Mon"]

    def test_one_text_number_is_repeated(self):
        assert extend_series(["Crop1"], 2) == ["Crop1", "Crop1"]


class TestNumberSeries:
    def test_constant_step(self):
        assert extend_series(["1", "3"], 3) == ["5", "7", "9"]

    def test_step_of_one(self):
        assert extend_series(["1", "2"], 3) == ["3", "4", "5"]

    def test_descending(self):
        assert extend_series(["10", "8"], 2) == ["6", "4"]

    def test_fractional_step_keeps_decimals(self):
        assert extend_series(["1", "1.5"], 2) == ["2", "2.5"]

    def test_non_constant_step_falls_back_to_repeat(self):
        # 1, 2, 4 is not linear -> the block repeats rather than inventing a rule.
        assert extend_series(["1", "2", "4"], 3) == ["1", "2", "4"]


class TestTextNumberSeries:
    def test_prefix_and_number_continue(self):
        assert extend_series(["Crop1", "Crop2"], 2) == ["Crop3", "Crop4"]

    def test_zero_padding_is_kept(self):
        assert extend_series(["Crop01", "Crop02"], 2) == ["Crop03", "Crop04"]

    def test_differing_prefixes_repeat(self):
        assert extend_series(["Crop1", "Farm2"], 2) == ["Crop1", "Farm2"]


class TestLists:
    def test_weekdays_continue_and_wrap(self):
        assert extend_series(["Sat", "Sun"], 2) == ["Mon", "Tue"]

    def test_months_continue(self):
        assert extend_series(["Jan", "Feb"], 2) == ["Mar", "Apr"]

    def test_quarters_wrap(self):
        assert extend_series(["Q3", "Q4"], 2) == ["Q1", "Q2"]

    def test_case_follows_the_last_source_cell(self):
        assert extend_series(["JAN", "FEB"], 1) == ["MAR"]
        assert extend_series(["jan", "feb"], 1) == ["mar"]

    def test_step_of_two_is_honoured(self):
        assert extend_series(["Jan", "Mar"], 2) == ["May", "Jul"]


class TestEdges:
    @pytest.mark.parametrize("count", [0, -1])
    def test_non_positive_count_returns_empty(self, count):
        assert extend_series(["1", "2"], count) == []

    def test_no_values_gives_blanks(self):
        assert extend_series([], 2) == ["", ""]

    def test_none_becomes_empty_string(self):
        assert extend_series([None], 2) == ["", ""]

    def test_mixed_block_repeats(self):
        assert extend_series(["a", "1"], 4) == ["a", "1", "a", "1"]

    def test_text_that_looks_numeric_but_is_not(self):
        # '1-2' must stay text (it is a range, not a number), so this repeats.
        assert extend_series(["1-2", "3-4"], 2) == ["1-2", "3-4"]
