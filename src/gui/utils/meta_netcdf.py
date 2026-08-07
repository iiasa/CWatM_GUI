"""Cached variable-metadata lookup from ``cwatm/metaNetcdf.xml``.

The file contains non-XML ``#`` comment lines, so it is scanned with a regex - and
parsed **once** into a dict cached for the lifetime of the process. Used by the
editor hover tooltips and by both Analyse windows (``get_meta``).
"""

import os
import re
import sys

from src.gui.utils.gui_log import get_logger

log = get_logger("meta_netcdf")

_cache = None  # {varname: (unit, long_name, description)}
_types = None  # {varname: type marker without brackets, e.g. "Array"/"Flag"/"Number"}
_priority = None  # {varname: priority attribute, e.g. "high"/"med"/"low"}
_dim = None  # {varname: dim attribute, e.g. "1D(N)"/"2D(6,N)"}


def _meta_xml_path():
    """Locate cwatm/metaNetcdf.xml both from source and when frozen (PyInstaller)."""
    candidates = []
    gui_root = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", ".."))          # .../gui
    candidates.append(os.path.join(gui_root, "cwatm", "metaNetcdf.xml"))
    candidates.append(os.path.join(os.getcwd(), "cwatm", "metaNetcdf.xml"))
    if getattr(sys, "frozen", False):
        candidates.insert(0, os.path.join(getattr(sys, "_MEIPASS", ""),
                                          "cwatm", "metaNetcdf.xml"))
        candidates.append(os.path.join(os.path.dirname(sys.executable),
                                       "cwatm", "metaNetcdf.xml"))
    return next((c for c in candidates if os.path.exists(c)), None)


def _load():
    """Parse metaNetcdf.xml into the cache dict (empty on any failure)."""
    global _cache, _types, _priority, _dim
    _cache = {}
    _types = {}
    _priority = {}
    _dim = {}
    path = _meta_xml_path()
    if not path:
        return
    try:
        with open(path, encoding="utf-8", errors="ignore") as _f:
            content = _f.read()
    except Exception:
        log.debug("could not read metaNetcdf.xml", exc_info=True)
        return
    for m in re.finditer(r'<metanetcdf\s+([^>]*?)/?>', content):
        attrs = m.group(1)
        vn = re.search(r'varname="([^"]*)"', attrs)
        if not vn:
            continue
        unit = re.search(r'unit="([^"]*)"', attrs)
        ln = re.search(r'long_name="([^"]*)"', attrs)
        desc = re.search(r'description="([^"]*)"', attrs)
        prio = re.search(r'priority="([^"]*)"', attrs)
        dim = re.search(r'dim="([^"]*)"', attrs)
        description = desc.group(1) if desc else ""
        # The trailing "[Array]" / "[Flag]" / "[Number]" / ... marker is the variable
        # "type": capture it, then drop it from the human description.
        mt = re.search(r'\[([^\]]*)\]\s*$', description)
        _types[vn.group(1)] = mt.group(1).strip() if mt else ""
        _priority[vn.group(1)] = prio.group(1).strip().lower() if prio else ""
        _dim[vn.group(1)] = dim.group(1).strip() if dim else ""
        description = re.sub(r'\s*\[[^\]]*\]\s*$', '', description)
        _cache[vn.group(1)] = (unit.group(1) if unit else "",
                               ln.group(1) if ln else "",
                               description)


def all_varnames():
    """Every varname listed in metaNetcdf.xml (empty tuple if unreadable).
    Used by Check settingsfile (F4) to validate output-variable names."""
    if _cache is None:
        _load()
    return tuple(_cache.keys())


def output_varnames(high_only=False):
    """Varnames that make sense as CWatM **output** (Tools ▸ Add output variables).

    metaNetcdf.xml tags each variable's description with a trailing type marker that is
    really its **dimensionality** - ``[1D(N)]`` / ``[2D(6,N)]`` / ``[3D(3,4,N)]`` (N =
    grid cells) for spatial data fields, ``[list(4)]`` etc. for parameter lookup
    tables, ``[Flag]``/``[Number]``/``[String]`` for settings scalars, and **no marker
    at all** for the rest. Excluded: variables with **no type marker**, ``_``-prefixed
    (internal) names, parameter-list tables (``list(...)``), and scalar settings types
    (Flag/Number/String/Bool). Everything else (the spatial data arrays) is kept.

    When ``high_only`` is True only the variables with ``priority="high"`` are returned
    (the picker's default view; the "Load all Variable" toggle passes False)."""
    if _cache is None:
        _load()
    out = []
    for vn, t in _types.items():
        tl = t.strip().lower()
        if not tl:                                          # no type value -> skip
            continue
        if vn.startswith("_"):                              # internal/private vars
            continue
        if tl.startswith("list("):                          # parameter lookup tables
            continue
        if tl in ("flag", "number", "string", "bool"):      # settings scalars
            continue
        if high_only and _priority.get(vn, "") != "high":   # priority filter
            continue
        out.append(vn)
    return tuple(out)


def dim_of(varname):
    """The ``dim`` attribute (e.g. ``1D(N)``) for ``varname``, or "" if unknown."""
    if _cache is None:
        _load()
    return _dim.get(varname, "")


def priority_of(varname):
    """The ``priority`` attribute (``high``/``med``/``low``) for ``varname``, or ""."""
    if _cache is None:
        _load()
    return _priority.get(varname, "")


def get_meta(varname):
    """Return (unit, long_name, description) for ``varname``, or None if unknown.
    Case-sensitive first, then case-insensitive."""
    if not varname:
        return None
    if _cache is None:
        _load()
    hit = _cache.get(varname)
    if hit is not None:
        return hit
    lower = varname.lower()
    for k, v in _cache.items():
        if k.lower() == lower:
            return v
    return None
