"""Excel-style cell formulas (`src/gui/utils/cell_formula.py`).

Two things are load-bearing here:

* **`is_formula` must not over-claim.** Everything it says yes to gets computed and the
  *number* is written to the workbook, so a misdetected text cell ("Winter wheat",
  "A-B") would be silently replaced by a number CWatM then reads.
* **evaluation is an ast whitelist, never `eval`** - the cells come from a file the user
  may not have written, so attribute access, calls to unknown names, imports and
  comprehensions must all be refused.
"""

import pytest

from src.gui.utils import cell_formula as cf
from src.gui.utils.cell_formula import FormulaError, evaluate, is_formula


# A tiny sheet:  A1=1  B1=2  C1=3
#                A2=4  B2=5  C2=6
SHEET = {(0, 0): 1, (0, 1): 2, (0, 2): 3,
         (1, 0): 4, (1, 1): 5, (1, 2): 6}


def resolver(row, col):
    return SHEET.get((row, col), "")


def ev(text):
    return evaluate(text, resolver)


class TestColumnNames:
    @pytest.mark.parametrize("letters,index", [
        ("A", 0), ("B", 1), ("Z", 25), ("AA", 26), ("AB", 27), ("BA", 52),
    ])
    def test_col_to_index(self, letters, index):
        assert cf.col_to_index(letters) == index

    @pytest.mark.parametrize("index", [0, 1, 25, 26, 27, 52, 701, 702])
    def test_round_trip(self, index):
        assert cf.col_to_index(cf.index_to_col(index)) == index

    def test_parse_ref(self):
        assert cf.parse_ref("I3") == (2, 8)
        assert cf.parse_ref("$A$1") == (0, 0)
        assert cf.parse_ref("A0") is None      # rows are 1-based
        assert cf.parse_ref("hello") is None

    def test_ref_name(self):
        assert cf.ref_name(2, 8) == "I3"
        assert cf.ref_name(0, 0) == "A1"


class TestIsFormula:
    @pytest.mark.parametrize("text", [
        "=1+1", "=SUM(A1:C1)", "2+3.5", "2 + A1", "A1*B1", "(1+2)/3", "2^3",
        "SUM(A1:C1)", "-1 + 2",
    ])
    def test_detected(self, text):
        assert is_formula(text)

    @pytest.mark.parametrize("text", [
        "", "   ", "Winter wheat", "A-B", "hello world", "1", "-5", "A1",
        "N/A", "yes/no",
    ])
    def test_not_detected(self, text):
        assert not is_formula(text)

    def test_a_bare_number_is_not_a_formula(self):
        # It needs no computing, and treating it as one would round-trip the text.
        assert not is_formula("42")

    def test_leading_sign_is_not_an_operation(self):
        assert not is_formula("-5")

    def test_leading_equals_always_wins(self):
        assert is_formula("=anything at all")

    def test_absurdly_long_input_is_refused(self):
        assert not is_formula("1+" * 400)


class TestDataIsNotArithmetic:
    """Regression guard for a silent data-loss bug: values that are only numbers joined
    by '-' or '/' were auto-detected as formulas, so the *computed number* was written
    into the workbook - '1-2' became -1.0 and '10-2020' became -2010.0, in a file CWatM
    then reads. They are dates, ids and ranges, and must stay text."""

    @pytest.mark.parametrize("text", [
        "1-2", "10-2020", "400001-2", "2026-08-13", "13/08/2026", "2026-08",
        "10/2", "1.5-2.5", "1 - 2", "01-02-2026",
    ])
    def test_kept_as_text(self, text):
        assert not is_formula(text)

    @pytest.mark.parametrize("text,expected", [
        ("=1-2", -1), ("=10/2", 5), ("=1.5-2.5", -1.0),
    ])
    def test_an_explicit_equals_still_computes(self, text, expected):
        # The escape hatch: a user who really wants the arithmetic types '='.
        assert ev(text) == pytest.approx(expected)

    @pytest.mark.parametrize("text", [
        "2+3.5",        # '+' cannot be mistaken for a date or an id
        "2*3",
        "(1+2)/3",      # parentheses signal intent
        "2 + A1",       # a cell reference does too
        "A1-B1",
        "SUM(A1:C1)",
        "A1/B1",
    ])
    def test_real_formulas_are_unaffected(self, text):
        assert is_formula(text)

    def test_the_two_modules_now_agree_about_a_hyphenated_value(self):
        """cell_fill deliberately keeps '1-2' as text (_as_number returns None); before
        the fix cell_formula turned the same cell into -1.0."""
        from src.gui.utils.cell_fill import extend_series
        assert not is_formula("1-2")
        assert extend_series(["1-2", "3-4"], 2) == ["1-2", "3-4"]


class TestAbsoluteReferences:
    """'$' is Excel's absolute marker. It used to work inside a range and nowhere else,
    because only _rewrite_ranges stripped it; a standalone '=$B$2' reached ast.parse
    with the '$' still there and raised #SYNTAX."""

    def test_standalone(self):
        assert ev("=$B$2") == pytest.approx(5)

    def test_column_only(self):
        # $B2 = column B, row 2 -> 5 (the '$' fixes the column, not the row)
        assert ev("=$B2") == pytest.approx(5)

    def test_row_only(self):
        assert ev("=B$1") == pytest.approx(2)

    def test_inside_a_range_still_works(self):
        assert ev("=SUM($A$1:$C$1)") == pytest.approx(6)

    def test_mixed_with_arithmetic(self):
        assert ev("=$A$1 + $B$1") == pytest.approx(3)

    def test_same_result_as_the_relative_form(self):
        assert ev("=$B$2") == ev("=B2")

    @pytest.mark.parametrize("text,expected", [
        ('="Price $10"', "Price $10"),
        ('="$5"', "$5"),
        ('="see $B$2"', "see $B$2"),
        ("='cost $3'", "cost $3"),
    ])
    def test_a_dollar_inside_a_string_literal_is_left_alone(self, text, expected):
        """Regression: the first version of the '$' fix substituted over the whole
        expression, so `="Price $10"` evaluated to "Price 10" - and the computed value
        is what gets written into the workbook."""
        assert ev(text) == expected

    def test_a_dollar_that_is_not_a_reference_marker_is_left_alone(self):
        # No letter+digit after it, so it is not an absolute reference.
        assert ev('="100 $"') == "100 $"


class TestArithmetic:
    @pytest.mark.parametrize("text,expected", [
        ("=1+1", 2), ("2+3.5", 5.5), ("=10-4", 6), ("=3*4", 12),
        ("=10/4", 2.5), ("=2^3", 8), ("=2**3", 8), ("=-3+1", -2),
        ("=(1+2)*3", 9), ("=10%3", 1),
    ])
    def test_operators(self, text, expected):
        assert ev(text) == pytest.approx(expected)

    def test_precedence(self):
        assert ev("=1+2*3") == pytest.approx(7)

    def test_division_by_zero(self):
        with pytest.raises(FormulaError) as e:
            ev("=1/0")
        assert str(e.value) == "#DIV/0!"


class TestCellReferences:
    def test_single_ref(self):
        assert ev("=A1") == pytest.approx(1)

    def test_ref_arithmetic(self):
        assert ev("2 + C1") == pytest.approx(5)

    def test_empty_cell_counts_as_zero(self):
        assert ev("=Z9+1") == pytest.approx(1)

    def test_lowercase_ref(self):
        assert ev("=a1+b1") == pytest.approx(3)


class TestRanges:
    def test_sum(self):
        assert ev("=SUM(A1:C1)") == pytest.approx(6)

    def test_sum_two_rows(self):
        assert ev("=SUM(A1:C2)") == pytest.approx(21)

    def test_average(self):
        assert ev("=AVERAGE(A1:C1)") == pytest.approx(2)

    def test_min_max_count(self):
        assert ev("=MIN(A1:C2)") == pytest.approx(1)
        assert ev("=MAX(A1:C2)") == pytest.approx(6)
        assert ev("=COUNT(A1:C2)") == pytest.approx(6)

    def test_range_mixed_with_scalars(self):
        assert ev("=SUM(A1:C1) + 4") == pytest.approx(10)

    def test_custom_range_resolver_is_used(self):
        calls = []

        def ranges(r0, c0, r1, c1):
            calls.append((r0, c0, r1, c1))
            return [10, 20]

        assert evaluate("=SUM(A1:B1)", resolver, ranges) == pytest.approx(30)
        assert calls == [(0, 0, 0, 1)]


class TestFunctions:
    @pytest.mark.parametrize("text,expected", [
        ("=ABS(-3)", 3), ("=ROUND(2.567, 1)", 2.6), ("=ROUND(2.5)", 2),
        ("=INT(2.9)", 2), ("=SQRT(9)", 3), ("=POWER(2, 10)", 1024),
        ("=MOD(7, 3)", 1), ("=LOG10(100)", 2), ("=LOG(8, 2)", 3),
    ])
    def test_functions(self, text, expected):
        assert ev(text) == pytest.approx(expected)

    def test_constants(self):
        assert ev("=PI") == pytest.approx(3.14159, abs=1e-4)
        assert ev("=E") == pytest.approx(2.71828, abs=1e-4)

    def test_case_insensitive(self):
        assert ev("=sum(A1:C1)") == pytest.approx(6)


class TestRefusesUnsafeInput:
    """The ast whitelist: anything that is not arithmetic must raise, not execute."""

    @pytest.mark.parametrize("text", [
        "=__import__('os').system('echo hi')",
        "=(1).__class__",
        "=open('x')",
        "=[i for i in range(3)]",
        "=lambda: 1",
        "=A1 if A1 else 0",
        "={1: 2}",
        "=globals()",
    ])
    def test_rejected(self, text):
        with pytest.raises(FormulaError):
            ev(text)

    def test_unknown_function_is_a_name_error(self):
        with pytest.raises(FormulaError) as e:
            ev("=NOSUCHFUNC(1)")
        assert str(e.value) == "#NAME?"

    def test_bad_syntax(self):
        with pytest.raises(FormulaError) as e:
            ev("=1+")
        assert str(e.value) == "#SYNTAX"

    def test_empty_formula(self):
        with pytest.raises(FormulaError):
            ev("=")

    def test_text_cell_in_arithmetic_is_a_value_error(self):
        with pytest.raises(FormulaError) as e:
            evaluate("=A1+1", lambda r, c: "not a number")
        assert str(e.value) == "#VALUE!"
