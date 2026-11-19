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

# Resolution of a saved PNG (Save PNG in the Analyse windows), in dots per inch
# (Preferences ▸ Editor & Dates ▸ PNG dpi, persisted as display/png_dpi). Plotly
# draws at 96 dpi on screen, so the image is rendered at scale png_dpi / 96.
PNG_DPI_DEFAULT = 150
PNG_DPI_MIN = 50
PNG_DPI_MAX = 1200
_PNG_DPI = PNG_DPI_DEFAULT


def get_png_dpi():
    """Current dpi for saved PNG images."""
    return _PNG_DPI


def set_png_dpi(n):
    """Set the PNG dpi (clamped to PNG_DPI_MIN..PNG_DPI_MAX). Ignores bad input."""
    global _PNG_DPI
    try:
        n = int(n)
    except (TypeError, ValueError):
        return
    _PNG_DPI = max(PNG_DPI_MIN, min(PNG_DPI_MAX, n))


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
