"""
MODFLOW coupling toggle (Configure ▸ Use Modflow).

flopy (the CWatM↔MODFLOW coupling library) is a **heavy** import — it pulls in the
whole matplotlib plotting stack — so loading it always would slow the GUI start. This
setting gates whether the GUI **pre-imports** flopy:

- **off** (default): flopy is never imported by the GUI → faster start;
- **on**: flopy is pre-warmed in the background (at startup if the setting was already
  on, or the moment it is switched on), so the first in-process MODFLOW use
  (Tools ▸ Check Data, the in-process run fallback) doesn't block on the import.

CWatM itself only imports flopy when a settings file actually enables
``modflow_coupling`` (``cwatm/run_cwatm.py``), so this only controls the GUI-side
pre-warm — it never forces MODFLOW on a run.
"""

from PySide6.QtCore import QSettings

from src.gui.utils.gui_log import get_logger

log = get_logger("modflow")

_ORG, _APP = "IIASA", "CWatM_GUI"
_KEY = "modflow/enabled"


def is_enabled():
    """Whether MODFLOW support (flopy pre-warm) is on. Default False."""
    try:
        return QSettings(_ORG, _APP).value(_KEY, False, type=bool)
    except Exception:
        return False


def set_enabled(on):
    s = QSettings(_ORG, _APP)
    s.setValue(_KEY, bool(on))
    s.sync()


def warm_flopy():
    """Import flopy in a background daemon thread (no-op if already imported / absent).
    Keeps the heavy flopy+matplotlib import off the GUI thread."""
    import threading

    def _work():
        try:
            import flopy  # noqa: F401
            log.debug("flopy pre-warm finished")
        except Exception:
            log.debug("flopy pre-warm failed (not installed / import error)",
                      exc_info=True)

    threading.Thread(target=_work, name="warmup-flopy", daemon=True).start()
