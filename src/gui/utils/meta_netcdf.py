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
    global _cache
    _cache = {}
    path = _meta_xml_path()
    if not path:
        return
    try:
        content = open(path, encoding="utf-8", errors="ignore").read()
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
        description = desc.group(1) if desc else ""
        # Drop the trailing "[Array]" / "[Flag]" / ... marker
        description = re.sub(r'\s*\[[^\]]*\]\s*$', '', description)
        _cache[vn.group(1)] = (unit.group(1) if unit else "",
                               ln.group(1) if ln else "",
                               description)


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
