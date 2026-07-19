"""Diagnostic file logging for the CWatM GUI.

The GUI deliberately never crashes on an error (global excepthook, defensive
``try/except`` around Qt object access), which historically meant swallowed
exceptions were invisible. This module gives them a destination: a rotating log
file under ``%LOCALAPPDATA%/CWatM_GUI/gui.log`` (falling back to the system temp
directory). UI behaviour is unchanged - nothing is shown to the user.

Usage:
    from src.gui.utils.gui_log import get_logger
    log = get_logger(__name__)
    ...
    except RuntimeError:
        log.debug("menu action already deleted", exc_info=True)

``get_logger`` configures the handler on first use and can never raise: if the
log file cannot be created (read-only install, exotic permissions) logging
silently degrades to a no-op NullHandler.
"""

import logging
import logging.handlers
import os
import tempfile

_ROOT_NAME = "cwatm_gui"
_configured = False


def _log_dir():
    """Directory for the log file: %LOCALAPPDATA%/CWatM_GUI, else <temp>/CWatM_GUI."""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return os.path.join(base, "CWatM_GUI")


def log_file_path():
    """Full path of the GUI log file (the directory may not exist yet)."""
    return os.path.join(_log_dir(), "gui.log")


def _configure():
    """Attach a rotating file handler to the root GUI logger. Never raises."""
    global _configured
    if _configured:
        return
    _configured = True
    root = logging.getLogger(_ROOT_NAME)
    root.setLevel(logging.DEBUG)
    root.propagate = False  # never echo into stdout (it is redirected to the GUI)
    try:
        os.makedirs(_log_dir(), exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_file_path(), maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        root.addHandler(handler)
        root.info("---- logging started ----")
    except Exception:
        # No usable log location - degrade to a silent no-op.
        root.addHandler(logging.NullHandler())


def get_logger(name=""):
    """Logger below the GUI root (e.g. ``get_logger(__name__)``); sets up the file
    handler on first call."""
    _configure()
    if not name or name == _ROOT_NAME:
        return logging.getLogger(_ROOT_NAME)
    return logging.getLogger(f"{_ROOT_NAME}.{name}")
