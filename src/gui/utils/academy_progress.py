"""CWatM Academy - persisted progress (QSettings, same convention as the rest of
the GUI's small persisted flags, e.g. ``src/gui/utils/modflow.py``).

Namespace: ``academy/enabled`` (bool) and ``academy/completed`` (comma-separated
level ids, e.g. ``"1,2,3"``) under ``QSettings("IIASA", "CWatM_GUI")``.
"""

from PySide6.QtCore import QSettings

from src.gui.utils.academy_content import LEVEL_COUNT

_ENABLED_KEY = "academy/enabled"
_COMPLETED_KEY = "academy/completed"
_OUTLET_LON_KEY = "academy/outlet_lon"
_OUTLET_LAT_KEY = "academy/outlet_lat"


def _settings():
    return QSettings("IIASA", "CWatM_GUI")


def is_enabled():
    return _settings().value(_ENABLED_KEY, False, type=bool)


def set_enabled(value):
    s = _settings()
    s.setValue(_ENABLED_KEY, bool(value))
    s.sync()


def completed_levels():
    """The set of completed level ids (1-based), from the persisted CSV."""
    raw = _settings().value(_COMPLETED_KEY, "", type=str)
    out = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


def mark_complete(level_id):
    """Record ``level_id`` as completed. Returns True the first time it is."""
    done = completed_levels()
    if level_id in done:
        return False
    done.add(level_id)
    s = _settings()
    s.setValue(_COMPLETED_KEY, ",".join(str(i) for i in sorted(done)))
    s.sync()
    return True


def current_level():
    """The lowest not-yet-completed level (1-based), capped at LEVEL_COUNT - the
    level the learner should land on when the Academy reopens."""
    done = completed_levels()
    for i in range(1, LEVEL_COUNT + 1):
        if i not in done:
            return i
    return LEVEL_COUNT


def is_first_visit():
    """True if no level has ever been completed - used to trigger the one-time
    switch to the Beginner editor view when Academy is entered."""
    return not completed_levels()


def reset():
    """Clear all recorded progress (kept for a future 'Restart Academy' action)."""
    s = _settings()
    s.remove(_COMPLETED_KEY)
    s.remove(_OUTLET_LON_KEY)
    s.remove(_OUTLET_LAT_KEY)
    s.sync()


def set_outlet(lon, lat):
    """Persist the catchment outlet picked in Level 1's map exercise."""
    s = _settings()
    s.setValue(_OUTLET_LON_KEY, float(lon))
    s.setValue(_OUTLET_LAT_KEY, float(lat))
    s.sync()


def get_outlet():
    """(lon, lat) of the picked outlet, or None if Level 1 hasn't been done yet."""
    s = _settings()
    if not s.contains(_OUTLET_LON_KEY):
        return None
    return s.value(_OUTLET_LON_KEY, type=float), s.value(_OUTLET_LAT_KEY, type=float)
