"""
Excel-like cell formulas for the Excel sheet editor (``excel_sheet_window.py``).

Evaluates arithmetic a user types into a cell — ``2+3.5``, ``2 + I3``,
``=(A1+B1)/2``, ``=SUM(C2:C10)`` — over the sheet's other cells.

Two ways to enter one, as in Excel:

* a leading ``=`` always means "this is a formula";
* a **bare** expression is auto-detected (``is_formula``) when every token is a
  number, a cell reference (``I3``), a known function/constant or an operator,
  and it contains at least one operator or function call. So ``2 + I3`` computes
  while ``Winter wheat`` or ``A-B`` stay text. Prefix with ``'`` to force text.

Evaluation is done over Python's ``ast`` with a **whitelist** of node types and
names — never ``eval`` of arbitrary code. Unknown names, bad syntax, division by
zero and cycles raise ``FormulaError`` carrying an Excel-ish marker
(``#NAME?``/``#SYNTAX``/``#DIV/0!``/``#VALUE!``/``#CYCLE``) that the model shows
in the cell.

The **values** are what gets saved: the model writes a formula cell's computed
number into the xlsx, not the formula text — CWatM reads these sheets with
pandas/openpyxl, which would hand the model a formula *string* instead of a
number (there is no cached result in a file openpyxl wrote). The formula itself
stays live for the session, so editing the cell shows it again and it
recalculates when a referenced cell changes.
"""

import ast
import math
import re

__all__ = ["FormulaError", "is_formula", "evaluate", "parse_ref", "ref_name",
           "col_to_index", "index_to_col"]


class FormulaError(Exception):
    """Raised for anything the cell cannot compute; ``str(e)`` is the marker
    shown in the cell (e.g. ``#DIV/0!``)."""


# --------------------------------------------------------------------- refs
_CELL_RE = re.compile(r"^\$?([A-Za-z]{1,3})\$?([0-9]{1,7})$")
_RANGE_RE = re.compile(
    r"\$?[A-Za-z]{1,3}\$?[0-9]{1,7}\s*:\s*\$?[A-Za-z]{1,3}\$?[0-9]{1,7}")


def col_to_index(letters):
    """'A' -> 0, 'B' -> 1, 'AA' -> 26."""
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def index_to_col(index):
    """0 -> 'A', 26 -> 'AA'."""
    s = ""
    n = index + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        s = chr(65 + rem) + s
    return s


def parse_ref(text):
    """'I3' -> (row0, col0) = (2, 8); None when it is not a cell reference."""
    m = _CELL_RE.match(text.strip())
    if not m:
        return None
    row = int(m.group(2))
    if row < 1:
        return None
    return row - 1, col_to_index(m.group(1))


def ref_name(row0, col0):
    """(2, 8) -> 'I3'."""
    return f"{index_to_col(col0)}{row0 + 1}"


# ---------------------------------------------------------------- functions
def _flat(args):
    """Flatten function arguments (a range argument arrives as a list)."""
    out = []
    for a in args:
        if isinstance(a, (list, tuple)):
            out.extend(_flat(a))
        else:
            out.append(a)
    return out


def _num(v):
    """Coerce a cell value to a number; empty cells count as 0 (like Excel)."""
    if v is None or v == "":
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).strip().replace(",", "."))
    except (TypeError, ValueError):
        raise FormulaError("#VALUE!")


def _nums(args):
    """Numbers of the arguments, silently skipping empty/among-text cells of a
    range (Excel's SUM/AVERAGE ignore text inside a range)."""
    out = []
    for v in _flat(args):
        if v is None or v == "":
            continue
        try:
            out.append(_num(v))
        except FormulaError:
            continue
    return out


def _safe(fn):
    def wrapped(*args):
        try:
            return fn(*args)
        except FormulaError:
            raise
        except ZeroDivisionError:
            raise FormulaError("#DIV/0!")
        except (TypeError, ValueError, OverflowError):
            raise FormulaError("#VALUE!")
    return wrapped


_FUNCS = {
    "SUM": _safe(lambda *a: math.fsum(_nums(a))),
    "AVERAGE": _safe(lambda *a: math.fsum(_nums(a)) / len(_nums(a))),
    "AVG": _safe(lambda *a: math.fsum(_nums(a)) / len(_nums(a))),
    "MIN": _safe(lambda *a: min(_nums(a))),
    "MAX": _safe(lambda *a: max(_nums(a))),
    "COUNT": _safe(lambda *a: float(len(_nums(a)))),
    "ABS": _safe(lambda x: abs(_num(x))),
    "ROUND": _safe(lambda x, n=0: round(_num(x), int(_num(n)))),
    "INT": _safe(lambda x: float(math.floor(_num(x)))),
    "SQRT": _safe(lambda x: math.sqrt(_num(x))),
    "EXP": _safe(lambda x: math.exp(_num(x))),
    "LN": _safe(lambda x: math.log(_num(x))),
    "LOG10": _safe(lambda x: math.log10(_num(x))),
    "LOG": _safe(lambda x, b=10: math.log(_num(x), _num(b))),
    "MOD": _safe(lambda x, y: math.fmod(_num(x), _num(y))),
    "POWER": _safe(lambda x, y: _num(x) ** _num(y)),
}
_CONSTS = {"PI": math.pi, "E": math.e}

# The internal marker the pre-pass rewrites 'A1:B3' into. It must stay a valid
# Python identifier (ast.parse sees it) and is not reachable from a bare
# expression - is_formula rejects any name that is neither a cell ref nor a
# known function.
_RANGE_FN = "_RNG_"


# ------------------------------------------------------------ is_formula
_TOKEN_RE = re.compile(r"""
      (?P<space>\s+)
    | (?P<num>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
    | (?P<name>[A-Za-z_][A-Za-z_0-9]*)
    | (?P<op>\*\*|[-+*/^%])
    | (?P<punct>[(),:])
""", re.VERBOSE)


# Values that are nothing but numbers joined by '-' or '/' are DATA, not arithmetic:
# a date (2026-08-13, 13/08/2026), an id or a range (1-2, 10-2020, 400001-2). Without
# this they were auto-detected as formulas and the *computed number* was written to
# the workbook - '1-2' became -1.0 and '10-2020' became -2010.0, silently, in a file
# CWatM then reads. Excel does not compute these either: it needs a leading '=', which
# still works here ('=1-2' is 1 minus 2).
#
# Deliberately narrow. Anything with a cell reference ('2 + I3'), a function
# ('SUM(A1:C1)'), parentheses ('(1+2)/3') or another operator ('2+3.5', '2*3') is
# unaffected, because none of those can be mistaken for a date or an id.
_DATA_NOT_FORMULA_RE = re.compile(
    r"^\s*\d+(?:\.\d+)?(?:\s*[-/]\s*\d+(?:\.\d+)?)+\s*$")


def _tokens(text):
    """Tokenize; returns None as soon as an unexpected character shows up."""
    out, pos, n = [], 0, len(text)
    while pos < n:
        m = _TOKEN_RE.match(text, pos)
        if m is None:
            return None
        pos = m.end()
        kind = m.lastgroup
        if kind != "space":
            out.append((kind, m.group()))
    return out


def is_formula(text):
    """Whether ``text`` should be computed rather than stored verbatim: a leading
    ``=``, or a bare expression made only of numbers / cell refs / known
    functions / operators that contains at least one operation."""
    t = (text or "").strip()
    if t.startswith("="):
        return True
    if not t or len(t) > 500:
        return False
    if _DATA_NOT_FORMULA_RE.match(t):
        return False
    toks = _tokens(t)
    if not toks:
        return False
    has_op = False
    for i, (kind, val) in enumerate(toks):
        if kind == "op":
            # A leading sign is not an operation ('-5' is just a number).
            if i > 0:
                has_op = True
        elif kind == "name":
            call = i + 1 < len(toks) and toks[i + 1][1] == "("
            if call:
                if val.upper() not in _FUNCS:
                    return False
                has_op = True
            elif parse_ref(val) is None and val.upper() not in _CONSTS:
                return False
    return has_op


def normalize(text):
    """The expression source of a formula (the ``=`` prefix removed)."""
    t = (text or "").strip()
    return t[1:].strip() if t.startswith("=") else t


# -------------------------------------------------------------- evaluation
_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: math.fmod(a, b),
    ast.Pow: lambda a, b: a ** b,
}


def _rewrite_ranges(expr):
    """'SUM(A1:B3)' -> 'SUM(_RNG$("A1:B3"))' so the range survives ast.parse
    (a bare ``A1:B3`` is not valid Python)."""
    def sub(m):
        return '%s("%s")' % (_RANGE_FN, m.group(0).replace("$", "").replace(" ", ""))
    return _RANGE_RE.sub(sub, expr)


# A '$' anywhere else is Excel's absolute-reference marker ('$B$2'). It is not valid
# Python, so it has to go before ast.parse - _rewrite_ranges only strips the ones
# inside a matched range, which used to leave a standalone '=$B$2' raising #SYNTAX.
# Dropping it loses nothing: absolute vs relative only matters when a formula is
# copied to another cell, and the editor copies a formula's *value*, never rewrites
# its references. Ranges are already string literals by this point, so their content
# is untouched.
_ABS_MARK_RE = re.compile(r"\$(?=[A-Za-z0-9])")


def _strip_abs_marks(expr):
    return _ABS_MARK_RE.sub("", expr)


def evaluate(text, resolver, range_resolver=None):
    """Compute ``text`` (with or without a leading ``=``).

    ``resolver(row0, col0)`` returns the value of a referenced cell,
    ``range_resolver(r0, c0, r1, c1)`` the list of values of a range (defaults to
    calling ``resolver`` for each cell). Raises ``FormulaError``.
    """
    expr = _strip_abs_marks(_rewrite_ranges(normalize(text))).replace("^", "**")
    if not expr:
        raise FormulaError("#SYNTAX")
    try:
        tree = ast.parse(expr, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        raise FormulaError("#SYNTAX")
    if range_resolver is None:
        def range_resolver(r0, c0, r1, c1):
            return [resolver(r, c)
                    for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)]
    return _eval(tree.body, resolver, range_resolver)


def _eval(node, resolver, range_resolver):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return 1.0 if node.value else 0.0
        if isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node.value, str):
            return node.value
        raise FormulaError("#VALUE!")

    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.UAdd):
            return _num(_eval(node.operand, resolver, range_resolver))
        if isinstance(node.op, ast.USub):
            return -_num(_eval(node.operand, resolver, range_resolver))
        raise FormulaError("#SYNTAX")

    if isinstance(node, ast.BinOp):
        fn = _BINOPS.get(type(node.op))
        if fn is None:
            raise FormulaError("#SYNTAX")
        a = _num(_eval(node.left, resolver, range_resolver))
        b = _num(_eval(node.right, resolver, range_resolver))
        try:
            return float(fn(a, b))
        except ZeroDivisionError:
            raise FormulaError("#DIV/0!")
        except (ValueError, OverflowError, TypeError):
            raise FormulaError("#NUM!")

    if isinstance(node, ast.Name):
        ref = parse_ref(node.id)
        if ref is not None:
            return resolver(ref[0], ref[1])
        const = _CONSTS.get(node.id.upper())
        if const is not None:
            return const
        raise FormulaError("#NAME?")

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.keywords:
            raise FormulaError("#NAME?")
        name = node.func.id
        if name == _RANGE_FN:
            return _range_values(node, range_resolver)
        fn = _FUNCS.get(name.upper())
        if fn is None:
            raise FormulaError("#NAME?")
        args = [_eval(a, resolver, range_resolver) for a in node.args]
        return fn(*args)

    raise FormulaError("#SYNTAX")


def _range_values(node, range_resolver):
    if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant):
        raise FormulaError("#REF!")
    a, _, b = str(node.args[0].value).partition(":")
    ra, rb = parse_ref(a), parse_ref(b)
    if ra is None or rb is None:
        raise FormulaError("#REF!")
    r0, r1 = sorted((ra[0], rb[0]))
    c0, c1 = sorted((ra[1], rb[1]))
    if (r1 - r0 + 1) * (c1 - c0 + 1) > 200000:
        raise FormulaError("#REF!")
    return range_resolver(r0, c0, r1, c1)
