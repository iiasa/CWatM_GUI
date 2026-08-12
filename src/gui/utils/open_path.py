"""Open a file or a folder in whatever the desktop uses for it.

``os.startfile`` is **Windows only** - on Linux (or macOS) it does not exist at all,
so the three "show me this in the file manager" actions (Analyse > Open PathOut
Folder, the Run Ledger's PathOut column, Output Explorer's fallback for .html/.txt)
raised ``AttributeError`` and reported "could not open".

``open_path`` is the portable stand-in: Windows keeps using ``os.startfile`` (its
behaviour there is unchanged), everything else goes through Qt's
``QDesktopServices``, with the desktop's own opener as a last resort.
"""

import os
import subprocess
import sys

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from src.gui.utils.gui_log import get_logger

log = get_logger("open_path")

#: Command line openers to try when Qt cannot do it (per platform, first that works).
_OPENERS = {
    "darwin": ["open"],
    "default": ["xdg-open", "gio", "gnome-open", "kde-open"],
}


def open_path(path):
    """Show ``path`` (a file or a directory) in the desktop's default handler.

    Returns True when something was launched, False when every way failed - the
    caller decides what to tell the user (all three call sites show a message)."""
    if not path:
        return False
    path = os.path.abspath(path)
    startfile = getattr(os, "startfile", None)      # Windows only
    if startfile is not None:
        try:
            startfile(path)
            return True
        except Exception:
            log.debug("os.startfile failed for %s", path, exc_info=True)
    try:
        if QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            return True
    except Exception:
        log.debug("QDesktopServices failed for %s", path, exc_info=True)
    for opener in _OPENERS.get(sys.platform, _OPENERS["default"]):
        try:
            # Detached: the file manager must outlive this call, and its own
            # chatter must not land in the CWatM output box.
            subprocess.Popen([opener, path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except (OSError, ValueError):
            continue                                # not installed - try the next
    log.warning("no way to open %s on this desktop", path)
    return False
