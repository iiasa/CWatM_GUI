"""Remember window geometry across sessions, and scale a window's FIRST-EVER
default size to the screen it opens on.

``GeometryMemoryMixin`` gives a QDialog-based window a persistent position/size:
call ``_init_geometry_memory("<key>")`` at the end of ``__init__`` - it restores the
saved geometry and returns True, or returns False so the caller can apply its
default size/position on first open. The geometry is saved whenever the dialog is
closed (``done`` and ``closeEvent`` both funnel through ``_save_geometry_memory``).

Keys used: ``timeseries``, ``timeseries_point``, ``netcdf``, ``basin``
(stored under ``geometry/<key>`` in the IIASA/CWatM_GUI QSettings).

``scaled_default_size()`` is the fallback every secondary window's ``self.resize(W,
H)`` uses for that first-ever open (or for a window with no geometry memory at all,
e.g. Check Data, Preferences, the small ad-hoc log/preview dialogs): a fixed pixel
size tuned to look right on a large monitor swamps a small laptop screen (report:
Show Basin opening far too big on a 15" laptop). It is a plain function, not part of
the mixin, since several windows that need it (``CheckDataWindow``,
``PreferencesWindow``, sub-dialogs built with a bare ``QDialog(self)``) do not use
``GeometryMemoryMixin`` at all.
"""

from PySide6.QtCore import QSettings
from PySide6.QtGui import QGuiApplication

from src.gui.utils.gui_log import get_logger

log = get_logger("window_geometry")


def scaled_default_size(widget, base_width, base_height,
                        reference_size=(1920, 1080),
                        min_scale=0.55, max_scale=1.35):
    """A default ``(width, height)`` for ``widget``'s own screen, scaled from a size
    tuned for a ``reference_size`` screen (1920x1080).

    Scales by the ratio of this screen's *available* geometry to the reference size
    - logical pixels, not physical inches: Qt/Windows do not always report physical
    screen size accurately (especially over RDP/remote displays, already a known
    trouble spot for this app), while logical pixels already account for the OS's
    own per-monitor scaling, so a 15" laptop at 125% and a 24" monitor at 100% -
    which look similar to the user - report comparable logical resolutions. Clamped
    two ways: the scale factor itself (never absurdly tiny or huge, even on an
    unusually small/large screen) and an outright fraction-of-screen cap (never
    bigger than the screen itself, whatever the scale factor says)."""
    try:
        screen = None
        get_screen = getattr(widget, "screen", None)
        if callable(get_screen):
            screen = get_screen()
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
    except Exception:
        log.debug("scaled_default_size: falling back to the base size", exc_info=True)
        return base_width, base_height
    if geo.width() <= 0 or geo.height() <= 0:
        return base_width, base_height
    scale = min(geo.width() / reference_size[0], geo.height() / reference_size[1])
    scale = max(min_scale, min(max_scale, scale))
    w = min(int(round(base_width * scale)), int(geo.width() * 0.94))
    h = min(int(round(base_height * scale)), int(geo.height() * 0.90))
    return max(w, 1), max(h, 1)


class GeometryMemoryMixin:
    """Mix into a QDialog (before QDialog in the base list) to persist geometry."""

    def _init_geometry_memory(self, key):
        """Restore the saved geometry for ``key``. Returns True if there was one."""
        self._geom_key = key
        self._geom_settings = QSettings("IIASA", "CWatM_GUI")
        try:
            geo = self._geom_settings.value(f"geometry/{key}")
            if geo is not None and self.restoreGeometry(geo):
                return True
        except Exception:
            log.debug("geometry restore failed for %s", key, exc_info=True)
        return False

    def _save_geometry_memory(self):
        try:
            if getattr(self, "_geom_key", None):
                self._geom_settings.setValue(
                    f"geometry/{self._geom_key}", self.saveGeometry())
        except Exception:
            log.debug("geometry save failed", exc_info=True)

    def done(self, result):
        self._save_geometry_memory()
        super().done(result)

    def closeEvent(self, event):
        self._save_geometry_memory()
        super().closeEvent(event)
