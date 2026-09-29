"""CWatM Academy - persisted progress (QSettings, same convention as the rest of
the GUI's small persisted flags, e.g. ``src/gui/utils/modflow.py``).

Namespace: ``academy/enabled`` (bool), ``academy/link_login`` (bool, default
True) and ``academy/completed`` (comma-separated level ids, e.g. ``"1,2,3"``)
under ``QSettings("IIASA", "CWatM_GUI")``.

**Linked to the login**: while *Link CWatM Academy to your login* is ticked and a
user is logged in to the CWatM account, the progress is the one stored in that
user's profile (``profiles.academy_completed`` on the server) instead of the
local list - so it follows the user to another computer, and each finished level
earns points. The main window registers itself as the ``remote`` (``set_remote``,
done by ``AccountMixin``); it answers ``academy_remote_active()`` /
``academy_remote_levels()`` and sends ``academy_remote_complete(level)`` /
``academy_remote_reset()`` to the server. Logged out (or unlinked) the local list
is used, exactly as before; the two are never merged, so one user's local
progress can never land in someone else's account.
"""

from PySide6.QtCore import QSettings

from src.gui.utils.academy_content import LEVEL_COUNT

_ENABLED_KEY = "academy/enabled"
_LINK_KEY = "academy/link_login"
_COMPLETED_KEY = "academy/completed"
_OUTLET_LON_KEY = "academy/outlet_lon"
_OUTLET_LAT_KEY = "academy/outlet_lat"

_remote = None      # the main window (AccountMixin) - see the module docstring


def _settings():
    return QSettings("IIASA", "CWatM_GUI")


def set_remote(remote):
    """Register the object that stores the progress in the user's profile."""
    global _remote
    _remote = remote


def _active_remote():
    """The remote while it is in charge (linked + logged in), else None."""
    if _remote is None or not is_linked():
        return None
    try:
        return _remote if _remote.academy_remote_active() else None
    except RuntimeError:            # the window is already gone
        return None


def is_enabled():
    return _settings().value(_ENABLED_KEY, False, type=bool)


def set_enabled(value):
    s = _settings()
    s.setValue(_ENABLED_KEY, bool(value))
    s.sync()


def is_linked():
    """Preferences ▸ CWatM Academy ▸ Link CWatM Academy to your login."""
    return _settings().value(_LINK_KEY, True, type=bool)


def set_linked(value):
    s = _settings()
    s.setValue(_LINK_KEY, bool(value))
    s.sync()


def _local_levels():
    raw = _settings().value(_COMPLETED_KEY, "", type=str)
    out = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


def completed_levels():
    """The set of completed level ids (1-based) - from the user's profile while
    linked and logged in, else from the persisted local CSV."""
    remote = _active_remote()
    if remote is not None:
        return set(remote.academy_remote_levels())
    return _local_levels()


def mark_complete(level_id):
    """Record ``level_id`` as completed. Returns True the first time it is."""
    done = completed_levels()
    if level_id in done:
        return False
    remote = _active_remote()
    if remote is not None:
        remote.academy_remote_complete(level_id)     # server: progress + points
        return True
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
    """Clear all recorded progress (Start Over). Linked: the profile's progress is
    cleared too - the points already earned stay (a level pays once)."""
    remote = _active_remote()
    if remote is not None:
        remote.academy_remote_reset()
    s = _settings()
    if remote is None:
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
