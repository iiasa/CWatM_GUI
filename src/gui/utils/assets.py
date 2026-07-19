"""Absolute paths to bundled assets, working from source and when frozen.

The frozen one-folder build ships ``assets/`` inside ``_internal/`` (which is
``sys._MEIPASS``), NOT next to the .exe - a relative ``QPixmap("assets/...")``
only works by accident when the current working directory happens to be the
folder that holds an assets/ copy. Always resolve through this helper.
"""

import os
import sys


def asset_path(*parts):
    """Absolute path to ``assets/<parts...>``.

    Search order: sys._MEIPASS (one-file temp dir / one-folder ``_internal``),
    the folder holding the .exe (in case assets were copied there), and - from
    source - the project root (three levels above this file). Returns the first
    existing candidate, else the first candidate path (so callers still get a
    sensible path for error messages)."""
    bases = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            bases.append(meipass)
        bases.append(os.path.dirname(sys.executable))
    else:
        # this file is <root>/src/gui/utils/assets.py -> <root> is 3 up
        bases.append(os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "..", "..")))
    for base in bases:
        candidate = os.path.join(base, "assets", *parts)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(bases[0], "assets", *parts)
