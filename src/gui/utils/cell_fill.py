"""
Excel-like autofill for the Excel sheet editor (``excel_sheet_window.py``).

``extend_series(values, count)`` takes the values of the cells the user dragged
the **fill handle** from and returns the next ``count`` values, mimicking what
Excel does:

* **a single source cell is copied** — dragging from one cell (or from a single
  cell of each line of a one-column / one-row selection) repeats **that value**
  over the rest, never a guessed series. Series need at least two cells, which
  is what says "continue like this";
* **number series** — two or more numbers with a constant step continue it
  (``1, 3`` -> ``5, 7, …``);
* **text + trailing number** — ``Crop1, Crop2`` -> ``Crop3, Crop4`` (zero padding
  kept);
* **lists** — weekday/month names continue cyclically (``Jan, Feb`` -> ``Mar…``),
  matching the case of the source;
* **anything else** — the source block is repeated (basic copy), which is also
  what a multi-cell mixed selection does.

Filling **backwards** (dragging up/left) is the same call with the source values
reversed; the caller then writes the results outward from the block.
"""

import re

__all__ = ["extend_series"]

_LISTS = [
    ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
     "Sunday"],
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
     "Nov", "Dec"],
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"],
    ["Q1", "Q2", "Q3", "Q4"],
]

_TAIL_NUM_RE = re.compile(r"^(.*?)(\d+)$")


def _as_number(text):
    """float(text) for a plain number cell, else None (no thousands separators —
    a value like '1-2' must stay text)."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text)
    s = str(text).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _fmt_number(value, integral):
    if integral:
        return str(int(round(value)))
    s = f"{value:.10f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-", "-0") else "0"


def _constant_step(nums):
    """The common step of a numeric sequence, or None when it is not constant."""
    if len(nums) < 2:
        return None
    step = nums[1] - nums[0]
    scale = max(abs(n) for n in nums) or 1.0
    for a, b in zip(nums, nums[1:]):
        if abs((b - a) - step) > 1e-9 * scale:
            return None
    return step


def _repeat(values, count):
    return [values[i % len(values)] for i in range(count)]


def _number_series(values, count):
    nums = [_as_number(v) for v in values]
    if any(n is None for n in nums):
        return None
    step = _constant_step(nums)          # None for a single value -> copied
    if step is None:
        return None
    integral = all(str(v).strip().lstrip("+-").isdigit() for v in values) \
        and float(step).is_integer()
    last = nums[-1]
    return [_fmt_number(last + step * (i + 1), integral) for i in range(count)]


def _text_number_series(values, count):
    """'Crop1' -> 'Crop2', keeping the prefix and the zero padding."""
    parts = []
    for v in values:
        m = _TAIL_NUM_RE.match(str(v).strip())
        if not m or not m.group(1):      # no prefix -> it is a plain number
            return None
        parts.append((m.group(1), m.group(2)))
    prefix = parts[0][0]
    if any(p != prefix for p, _ in parts):
        return None
    nums = [float(n) for _, n in parts]
    step = _constant_step(nums)
    if step is None:
        return None
    width = len(parts[-1][1]) if parts[-1][1].startswith("0") else 0
    out = []
    for i in range(count):
        n = int(round(nums[-1] + step * (i + 1)))
        body = str(abs(n)).rjust(width, "0")
        out.append(f"{prefix}{'-' if n < 0 else ''}{body}")
    return out


def _list_series(values, count):
    """Continue a built-in list (weekdays, months, quarters), cyclically."""
    keys = [str(v).strip() for v in values]
    if not all(keys):
        return None
    for entries in _LISTS:
        lower = [e.lower() for e in entries]
        try:
            idx = [lower.index(k.lower()) for k in keys]
        except ValueError:
            continue
        if len(idx) < 2:
            return None                  # a single name is copied, not continued
        n = len(entries)
        step = (idx[1] - idx[0]) % n or n
        for a, b in zip(idx, idx[1:]):
            if (b - a) % n != step % n:
                return None
        src = keys[-1]
        upper = src.isupper()
        title = src[:1].isupper()
        out = []
        for i in range(count):
            e = entries[(idx[-1] + step * (i + 1)) % n]
            out.append(e.upper() if upper else e if title else e.lower())
        return out
    return None


def extend_series(values, count):
    """The next ``count`` values continuing ``values`` (as strings)."""
    values = [("" if v is None else str(v)) for v in values]
    if count <= 0:
        return []
    if not values:
        return [""] * count
    if len(values) == 1:
        return _repeat(values, count)     # one cell -> fill the rest with its value
    for builder in (_number_series, _list_series, _text_number_series):
        try:
            out = builder(values, count)
        except Exception:
            out = None
        if out is not None:
            return out
    return _repeat(values, count)
