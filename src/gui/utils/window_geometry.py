"""Remember window geometry across sessions.

``GeometryMemoryMixin`` gives a QDialog-based window a persistent position/size:
call ``_init_geometry_memory("<key>")`` at the end of ``__init__`` - it restores the
saved geometry and returns True, or returns False so the caller can apply its
default size/position on first open. The geometry is saved whenever the dialog is
closed (``done`` and ``closeEvent`` both funnel through ``_save_geometry_memory``).

Keys used: ``timeseries``, ``timeseries_point``, ``netcdf``, ``basin``
(stored under ``geometry/<key>`` in the IIASA/CWatM_GUI QSettings).
"""

from PySide6.QtCore import QSettings

from src.gui.utils.gui_log import get_logger

log = get_logger("window_geometry")


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
