"""What the map windows may load and run - and where they cache (security.md #2).

Pure Python, no Qt, cheap to import (``cwatm_gui.py`` uses it before QApplication).

**Pinned JavaScript/CSS.** The folium/Leaflet pages of Show Basin, Analyse ▸ NetCDF,
the World Map and the CWatM Academy maps reference Leaflet on a CDN. Those files are
**shipped with the app** (``assets/web/``) and served from there, each checked
against the SHA-256 below - nothing is downloaded and run at run time any more. A
remote script that is NOT in ``PINNED`` is removed from the page, never fetched: an
unknown script never runs. (A folium upgrade that changes the URLs therefore shows up
as a broken map and a failing ``tests/test_web_assets.py`` - add the new files here.)
The hashes of leaflet.js / leaflet.css equal the integrity values Leaflet publishes
for 1.9.3 (sha256-WBkoXOwT... / sha256-kLaT2GOS...).

**Per-user cache.** Map tiles are cached in the user's own cache folder
(``%LOCALAPPDATA%\\CWatM_GUI\\cache`` / ``$XDG_CACHE_HOME`` or ``~/.cache``), not in
the shared temp directory, where - on a multi-user Linux machine - another user
could have planted files.

**Chromium sandbox.** QtWebEngine's sandbox stays ON unless it cannot work:
QtWebEngineProcess.exe on a network path (Windows refuses to start it sandboxed) or
a non-Windows system (Linux remote/container sessions, gui.sh). The environment
variable ``CWATM_GUI_WEBENGINE_SANDBOX`` = ``1`` / ``0`` forces it on / off.
"""

import hashlib
import os
import sys

_PINNED_DIR = "web"          # assets/web/

# URL as folium emits it (or as leaflet.css resolves it) -> (file, sha256)
PINNED = {
    "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js":
        ("leaflet-1.9.3-leaflet.js",
         "5819285cec137b229c94e1ee5ad73e8b6b84345a4367d60f75fe477fe0fb7b03"),
    "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css":
        ("leaflet-1.9.3-leaflet.css",
         "90b693d86392a4779c861b28cf307e7e59c3fb35328c4d8b95f58f814d38c722"),
    "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/images/layers.png":
        ("leaflet-1.9.3-layers.png",
         "1dbbe9d028e292f36fcba8f8b3a28d5e8932754fc2215b9ac69e4cdecf5107c6"),
    "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/images/layers-2x.png":
        ("leaflet-1.9.3-layers-2x.png",
         "066daca850d8ffbef007af00b06eac0015728dee279c51f3cb6c716df7c42edf"),
    "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/images/marker-icon.png":
        ("leaflet-1.9.3-marker-icon.png",
         "574c3a5cca85f4114085b6841596d62f00d7c892c7b03f28cbfa301deb1dc437"),
}


class UnpinnedAsset(Exception):
    """A remote file that is not shipped and pinned - it is not loaded."""


def pinned_bytes(url):
    """The shipped bytes for ``url`` after checking their SHA-256. Raises
    UnpinnedAsset for any URL not in PINNED, or a file that fails the check."""
    entry = PINNED.get(url)
    if entry is None:
        raise UnpinnedAsset(url)
    name, sha = entry
    from src.gui.utils.assets import asset_path
    path = asset_path(os.path.join(_PINNED_DIR, name))
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise UnpinnedAsset(f"{url}: shipped file missing ({e})") from e
    if hashlib.sha256(data).hexdigest() != sha:
        raise UnpinnedAsset(f"{url}: shipped file does not match its pinned hash")
    return data


def user_cache_dir(name):
    """A cache folder that belongs to this user only (created on demand)."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        root = os.path.join(base, "CWatM_GUI", "cache")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
            os.path.expanduser("~"), ".cache")
        root = os.path.join(base, "cwatm_gui")
    path = os.path.join(root, name)
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


# ---- Chromium sandbox --------------------------------------------------------------

def _is_network_path(path, drive_type=None):
    """True for a UNC path (\\\\server\\share) or a mapped network drive (P:)."""
    path = os.path.abspath(path)
    if path.startswith("\\\\") or path.startswith("//"):
        return True
    drive, _rest = os.path.splitdrive(path)
    if not drive:
        return False
    if drive_type is None:
        try:
            import ctypes
            drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")
        except Exception:
            return False
    return drive_type == 4                         # DRIVE_REMOTE


def webengine_process_dir():
    """Where QtWebEngineProcess(.exe) lives: inside the frozen app, else PySide6."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    try:
        import importlib.util
        spec = importlib.util.find_spec("PySide6")
        if spec and spec.origin:
            return os.path.dirname(spec.origin)
    except Exception:
        from src.gui.utils.gui_log import get_logger
        get_logger("web_assets").debug("PySide6 not found", exc_info=True)
    return os.path.dirname(sys.executable)


def sandbox_must_be_off(platform=None, process_dir=None, env=None, drive_type=None):
    """Should QtWebEngine run with --no-sandbox? Only when the sandbox cannot work."""
    env = os.environ if env is None else env
    forced = env.get("CWATM_GUI_WEBENGINE_SANDBOX", "").strip()
    if forced in ("0", "1"):
        return forced == "0"
    platform = platform or sys.platform
    if platform != "win32":
        return True        # Linux remote / container sessions: keep the old behaviour
    return _is_network_path(process_dir or webengine_process_dir(), drive_type)
