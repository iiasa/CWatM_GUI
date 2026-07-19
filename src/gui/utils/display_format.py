"""Global display-precision setting for the GUI.

A single value, `_DECIMALS`, controls how many decimals are shown throughout all
numeric read-outs (live discharge, basin click info, NetCDF cell values, point
labels, ...). It is set from the **Configure > Show Decimals** menu (default 3) and
persisted via QSettings by the caller.

Display code reads `get_decimals()`, `fmt()` or `spec()` so one setting drives every
read-out. Windows read the current value when they are built, so newly opened
displays pick up any change; values computed on the fly update immediately.

This deliberately does NOT touch coordinate strings written back into the settings
file (gauge / mask copy) - those are data serialisation and keep their fixed
precision.
"""

_DECIMALS = 3
_MIN = 0
_MAX = 12

# Initial map transparency (0-100) used by the NetCDF and Show Basin viewers as the
# start value of their transparency slider (Configure > Transparency). 0 = OSM hidden
# / data fully opaque; 100 = OSM fully visible / data 50% opaque on top.
_TRANSPARENCY = 100


def get_transparency():
    """Current initial map-transparency percentage (0-100)."""
    return _TRANSPARENCY


def set_transparency(n):
    """Set the initial map transparency (clamped to 0-100). Ignores bad input."""
    global _TRANSPARENCY
    try:
        n = int(n)
    except (TypeError, ValueError):
        return
    _TRANSPARENCY = max(0, min(100, n))


def get_decimals():
    """Current number of decimals shown in displays."""
    return _DECIMALS


def set_decimals(n):
    """Set the global display decimals (clamped to a sane range). Ignores bad input."""
    global _DECIMALS
    try:
        n = int(n)
    except (TypeError, ValueError):
        return
    _DECIMALS = max(_MIN, min(_MAX, n))


def fmt(value, default="N/A"):
    """Format a number with the current global decimal count; `default` on failure."""
    try:
        return f"{float(value):.{_DECIMALS}f}"
    except (TypeError, ValueError):
        return default


def spec(kind="f"):
    """Return a format spec like ``.3f`` for the current decimals.

    Handy for building Plotly hovertemplates (``%{{z:{spec()}}}``) or format strings."""
    return f".{_DECIMALS}{kind}"
