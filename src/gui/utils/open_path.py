"""Open a file or a folder in whatever the desktop uses for it.

``os.startfile`` is **Windows only** - on Linux (or macOS) it does not exist at all,
so the three "show me this in the file manager" actions (Analyse > Open PathOut
Folder, the Run Ledger's PathOut column, Output Explorer's fallback for .html/.txt)
raised ``AttributeError`` and reported "could not open".

``open_path`` is the portable stand-in: Windows keeps using ``os.startfile`` (its
behaviour there is unchanged), everything else goes through Qt's
``QDesktopServices``, with the desktop's own opener as a last resort - always as an
argument LIST, never through a shell.

Programs and scripts are never opened (that would run them) - see
``RUNNABLE_EXTENSIONS``.
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

#: File types the desktop would RUN rather than show (Windows PATHEXT and the other
#: script/installer/shortcut types, plus the Linux/macOS ones). Output Explorer and
#: Restore settingsfile pass whatever file sits in an output folder - often a shared
#: one - so a double-click must never start a program (security review, B606-type).
RUNNABLE_EXTENSIONS = frozenset((
    ".exe", ".com", ".bat", ".cmd", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
    ".msc", ".ps1", ".psm1", ".psd1", ".lnk", ".url", ".hta", ".msi", ".msp",
    ".scr", ".cpl", ".pif", ".jar", ".reg", ".application", ".appref-ms",
    ".gadget", ".inf", ".sct", ".chm", ".py", ".pyw", ".pyc", ".sh", ".bash",
    ".desktop", ".app", ".command", ".run", ".appimage",
))


def is_runnable(path):
    """True for a FILE whose type the desktop would execute."""
    return (os.path.splitext(path)[1].lower() in RUNNABLE_EXTENSIONS
            and not os.path.isdir(path))


_SAFE_SCHEMES = ("http", "https", "mailto")


def open_link(url, browser=None):
    """A link clicked in a rich-text view (Help viewer, CWatM AI transcript).

    Never QTextBrowser.setOpenExternalLinks(True): that hands ANY URL to the desktop,
    and a ``file:///…/x.exe`` or ``\\\\server\\share\\x.bat`` link - e.g. in an AI
    answer, which comes from outside - would RUN it. Here:
    - ``#anchor`` (same document) -> scroll ``browser`` to it;
    - http / https / mailto -> the desktop's browser / mail client;
    - a local file -> open_path(), which never opens a program (shows its folder);
    - anything else (javascript:, data:, ftp:, smb:, unknown) -> ignored, logged.
    Returns True when something was opened."""
    from PySide6.QtCore import QUrl
    url = url if isinstance(url, QUrl) else QUrl(str(url))
    scheme = url.scheme().lower()
    if not scheme and not url.path() and url.hasFragment():
        if browser is not None:
            browser.scrollToAnchor(url.fragment())
        return True
    if scheme in _SAFE_SCHEMES:
        return bool(QDesktopServices.openUrl(url))
    if scheme == "file" or (not scheme and url.path()):
        local = url.toLocalFile() if scheme == "file" else url.path()
        if browser is not None and not os.path.isabs(local):
            base = browser.document().baseUrl().toLocalFile()
            local = os.path.join(os.path.dirname(base) if base else "", local)
        if local.startswith("\\\\") or local.startswith("//"):
            log.warning("link to a network share ignored: %s", local)
            return False
        return open_path(local)
    log.warning("link with scheme %r ignored: %s", scheme, url.toString())
    return False


def make_links_safe(browser):
    """Route every link of a QTextBrowser through open_link()."""
    browser.setOpenExternalLinks(False)
    browser.setOpenLinks(False)
    browser.anchorClicked.connect(lambda url, b=browser: open_link(url, b))


def open_path(path):
    """Show ``path`` (a file or a directory) in the desktop's default handler.

    A file the desktop would RUN (``RUNNABLE_EXTENSIONS``) is never handed over -
    its folder is opened instead, so the user sees it without executing it.

    Returns True when something was launched, False when every way failed - the
    caller decides what to tell the user (all three call sites show a message)."""
    if not path:
        return False
    path = os.path.abspath(path)
    if is_runnable(path):
        log.warning("not opening a runnable file, showing its folder: %s", path)
        path = os.path.dirname(path)
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
