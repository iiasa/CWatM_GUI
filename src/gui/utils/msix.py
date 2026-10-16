"""Is this process running from an MSIX package (the Microsoft Store build)?

The Store build is the unchanged one-folder PyInstaller build, wrapped in an MSIX
package (``installer/msix``, ``build_release.ps1`` step ``msix``). Packaged, a few
things work differently, and the code that cares asks :func:`is_packaged`:

- **AppUserModelID**: the package assigns it (``<family name>!CWatMGUI``), so
  ``cwatm_gui._set_windows_app_id`` leaves it alone; setting our own would split
  the taskbar button from the Start menu entry and the pinned icon.
- **Create batch**: a ``.bat`` outside the package starts the model through its
  execution alias ``CWatM_model.exe`` (:data:`MODEL_ALIAS`, declared in the
  manifest), not through the ``C:\\Program Files\\WindowsApps\\...`` path.

Light on purpose (``sys`` only, ``ctypes`` imported on first use), so it may be
imported on the startup path.
"""

import sys

# The execution alias of the model exe (installer/msix/AppxManifest.xml, Application
# "CWatMModel"). Windows puts it in %LOCALAPPDATA%\Microsoft\WindowsApps, on PATH.
MODEL_ALIAS = "CWatM_model.exe"

_ERROR_SUCCESS = 0
_ERROR_INSUFFICIENT_BUFFER = 122
_APPMODEL_ERROR_NO_PACKAGE = 15700

_packaged = None   # cache: the answer cannot change while the process runs


def _kernel32_api():
    """kernel32.GetCurrentPackageFullName, or None where it does not exist
    (not Windows; Windows 7 has no package API)."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        return ctypes.windll.kernel32.GetCurrentPackageFullName
    except (ImportError, AttributeError, OSError):
        return None


def package_full_name(api=None):
    """The package full name (``Name_Version_Arch_ResourceId_PublisherId``) when this
    process runs from an MSIX package, else None.

    `api` stands in for ``GetCurrentPackageFullName(UINT32 *length, PWSTR name)``
    in tests: called with a zero length and no buffer it returns
    ERROR_INSUFFICIENT_BUFFER and the needed length when packaged, and
    APPMODEL_ERROR_NO_PACKAGE when not."""
    import ctypes
    if api is None:
        api = _kernel32_api()
        if api is None:
            return None
    length = ctypes.c_uint32(0)
    rc = api(ctypes.byref(length), None)
    if rc != _ERROR_INSUFFICIENT_BUFFER or length.value == 0:
        return None          # APPMODEL_ERROR_NO_PACKAGE, or an unexpected answer
    buf = ctypes.create_unicode_buffer(length.value)
    if api(ctypes.byref(length), buf) != _ERROR_SUCCESS:
        return None
    return buf.value or None


def is_packaged():
    """True when running from the MSIX package (Microsoft Store install)."""
    global _packaged
    if _packaged is None:
        try:
            _packaged = package_full_name() is not None
        except Exception:
            from src.gui.utils.gui_log import get_logger
            get_logger("msix").debug("package check failed", exc_info=True)
            _packaged = False
    return _packaged
