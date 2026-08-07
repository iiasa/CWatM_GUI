#!/usr/bin/env python3
"""
CWatM GUI Application - Main Entry Point
A graphical user interface for the Community Water Model (CWatM) by IIASA

This application provides an intuitive interface for loading, parsing, editing,
and managing CWatM configuration files.

Usage:
    python cwatm_gui.py [settings.ini]

Requirements:
    - PySide6 (see requirements.txt for the pinned runtime stack)
"""

import os
import sys
import threading

# Silence the rasterio 1.5.0 x numpy 2.5 "Setting the shape on a NumPy array has
# been deprecated" spam before anything imports numpy/rasterio/cwatm, and export
# it to every child process. See src/gui/utils/warning_filters.py for the why.
# (src/ is importable here in every launch path: sys.path[0] is the script's own
# folder from source, the PYZ when frozen.)
from src.gui.utils.warning_filters import apply as _apply_warning_filters

_apply_warning_filters()

# =============================================================================
# Everything above the Qt import runs in the CHILD process too, so it must stay
# free of Qt and of the scientific stack (report §3.1 / §4.1).
# =============================================================================


def _splash(action, text=None):
    """Talk to the PyInstaller splash screen; no-op when not running frozen.

    The splash is touched from five places (both child-process dispatches, the two
    "loading ..." updates around the Qt import, and the close after the window is
    up). Routing them all through here keeps the "are we frozen?" test - a failed
    ``import pyi_splash`` - in one place instead of a module-global sentinel.

    action: "text" (update the caption) or "close". Returns True when a splash
    was actually present.
    """
    try:
        import pyi_splash
    except Exception:
        return False          # not running from a PyInstaller bundle
    try:
        if action == "text" and text:
            pyi_splash.update_text(text)
        elif action == "close":
            pyi_splash.close()
    except Exception:
        pass
    return True


# --- Child-process dispatch (subprocess run, report §3.1) --------------------
# "CWatM_GUI.exe --run-cwatm <settings.ini>" runs ONLY the model runner and exits;
# "CWatM_GUI.exe --notebooklm-login <args...>" runs ONLY the bundled notebooklm
# CLI (the frozen build has no "python -m notebooklm", and the CWatM AI Login flow
# needs a fresh child process that can open a browser / write the session file and
# exit without touching the running GUI).
#
# Both are dispatched BEFORE any Qt import so the child process stays light. Each
# handler keeps its own imports inside itself for the same reason.

def _run_model_child(args):
    """--run-cwatm: hand off to the model runner. Returns its exit code."""
    from src.gui.utils.cwatm_model_runner import main as _model_runner_main
    return _model_runner_main(args)


def _run_notebooklm_child(args):
    """--notebooklm-login: everything after the flag goes to notebooklm's click CLI."""
    # click reads sys.argv[1:]; argv[0] is just the program name.
    sys.argv = ["notebooklm"] + args
    from notebooklm.notebooklm_cli import main as _nlm_cli_main
    _nlm_cli_main()   # click runs the command and calls sys.exit itself
    return 0          # reached only if click returns without exiting


_CHILD_DISPATCH = (
    ("--run-cwatm", _run_model_child),
    ("--notebooklm-login", _run_notebooklm_child),
)


def _dispatch_child_process():
    """Run and exit if this process was started as one of the child modes."""
    for flag, handler in _CHILD_DISPATCH:
        if flag in sys.argv:
            _splash("close")   # the bootloader already showed it - close it
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            sys.exit(handler(sys.argv[sys.argv.index(flag) + 1:]))


_dispatch_child_process()


def _configure_qtwebengine():
    """QtWebEngine flags. MUST run before QApplication / any QtWebEngine import.

    - --disable-gpu: GPU-accelerated QtWebEngine renders a blank page on many Windows
      setups (VMs, remote desktop, some drivers); software rendering is reliable.
    - --use-gl=angle --use-angle=swiftshader: SOFTWARE WebGL. With --disable-gpu
      alone Chromium has NO WebGL at all, and MapLibre requires WebGL - its canvas
      stays empty ("Failed to initialize WebGL"). SwiftShader is pure software, so
      the VM/RDP robustness of --disable-gpu is kept. Leaflet/Plotly 2-D views are
      unaffected.
    - --no-sandbox + QTWEBENGINE_DISABLE_SANDBOX: Chromium's sandbox refuses to launch
      QtWebEngineProcess.exe from a network path ("Can not launch QtWebEngineProcess
      from network path if sandbox is enabled") - this app lives on a mapped network
      share (P: -> \\\\pdrive\\...), so the sandbox must be disabled.
    """
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                          "--disable-gpu --no-sandbox "
                          "--use-gl=angle --use-angle=swiftshader")
    os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")


# Splash progress (frozen build only; §4.5). Since the §4.1 lazy imports the
# startup cost is PySide6 + the GUI modules - the scientific stack loads in the
# background after the window is up.
_splash("text", "Loading Qt ...")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon

_splash("text", "Loading user interface ...")

from src.gui.components.main_window import CWatMMainWindow
from src.gui.utils.assets import asset_path
from src.gui.utils.print_redirector import PrintRedirector
from src.gui.utils.gui_log import get_logger

log = get_logger("app")

# Startup timings (ms). Tuned: the WebEngine pre-warm deliberately lands after the
# module warm-up so the two heavy tasks do not contend at startup.
_FOREGROUND_RETRY_MS = 300
_WARMUP_DELAY_MS = 500
_WEBENGINE_PREWARM_DELAY_MS = 1500


def _bring_to_front(window):
    """Raise the window, activate it and force it to the foreground. After the
    PyInstaller splash screen closes, the main window otherwise stays behind other
    windows and is not the active app. No-op on failure."""
    try:
        window.setWindowState(
            (window.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        window.show()
        window.raise_()
        window.activateWindow()
        if sys.platform == "win32":
            import ctypes
            hwnd = int(window.winId())
            user32 = ctypes.windll.user32
            # Keep a maximized window maximized: SW_SHOWMAXIMIZED (3) for a maximized
            # window, SW_RESTORE (9) otherwise. Using SW_RESTORE unconditionally
            # un-maximizes the window (that was the bug - the app opens maximized but
            # this foreground call restored it to the default 1200x800 size).
            user32.ShowWindow(hwnd, 3 if window.isMaximized() else 9)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
    except Exception:
        log.debug("bring-to-front failed", exc_info=True)


def _set_windows_app_id():
    """Give the app its own AppUserModelID on Windows so the taskbar shows the
    CWatM icon instead of the python.exe icon. Must run before any window is
    created. No-op on other platforms or on failure."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                u"IIASA.CWatM.GUI"
            )
        except Exception:
            log.debug("setting AppUserModelID failed", exc_info=True)


def _close_splash():
    """Close the PyInstaller splash screen once the main window is shown."""
    _splash("text", "UI loaded")
    _splash("close")


def _warm_up_heavy_modules():
    """Import the heavy scientific stack in a background thread AFTER the window
    is shown (report §4.1): cwatm.run_cwatm (scipy/pandas/netCDF4 - first Run in
    the in-process fallback and Tools > Check Data), xarray + rasterio (Show
    Basin / Analyse > NetCDF). The user can already read/edit the settings file
    while these load; a feature used before its warm-up finishes simply blocks
    on the import as it always did."""
    def _work():
        try:
            # pandas first: it is by far the slowest single import (its own cold
            # import dominates the stack), so front-load it while the user reads the UI.
            import pandas          # noqa: F401
            import cwatm.run_cwatm  # noqa: F401
            import xarray           # noqa: F401
            import rasterio         # noqa: F401
            # plotly is cheap (~0.2 s) and the Analyse menu is a common path.
            import plotly.graph_objects  # noqa: F401
            # NOT pre-warmed on purpose (report §1.3): openpyxl (~6 s) and folium
            # (~4 s) are only needed by the Excel menu and the map viewers, which
            # most sessions never open - and Python holds the GIL while executing
            # import bytecode, so ~10 s of that competes with the UI thread during
            # the first minute. Both are already lazy at their call sites, so the
            # first Excel/map click just pays the import then, exactly as it does
            # today whenever the click beats the warm-up.
            log.debug("background warm-up finished")
        except Exception:
            log.debug("background warm-up failed", exc_info=True)
    threading.Thread(target=_work, name="warmup-imports", daemon=True).start()


def _prewarm_webengine(window):
    """Initialise the QtWebEngine stack once on a hidden view (report §T8).

    The first Show Basin / Analyse map / Timeseries plot otherwise pays the cost of
    loading Qt6WebEngineCore.dll (~196 MB) and spawning QtWebEngineProcess.exe. Doing
    it here on a throw-away hidden view keeps the subsystem warm so the first real map
    window opens near-instantly. Must run on the GUI thread (Qt widgets are not
    thread-safe), hence a QTimer callback rather than the warm-up thread. No-op on
    failure - the real windows still work, just without the head start."""
    try:
        from PySide6.QtWebEngineWidgets import QWebEngineView
        view = QWebEngineView(window)
        view.resize(0, 0)
        view.setHtml("<!doctype html><html><body></body></html>")
        view.hide()
        # Keep a reference alive so the WebEngine process is not torn down again.
        window._prewarm_webview = view
        log.debug("QtWebEngine pre-warm done")
    except Exception:
        log.debug("QtWebEngine pre-warm failed", exc_info=True)


def _err(*lines):
    """Print to stderr (i.e. dark red in the CWatM output box)."""
    for line in lines:
        print(line, file=sys.stderr)


def handle_exception(exc_type, exc_value, exc_traceback):
    """Global exception handler - prevents application termination on errors"""
    if issubclass(exc_type, KeyboardInterrupt):
        # Allow KeyboardInterrupt to propagate normally
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    if issubclass(exc_type, SystemExit):
        # Intercept SystemExit to prevent application termination
        code = exc_value.code if hasattr(exc_value, 'code') else 'unknown'
        error_msg = f"SYSTEM EXIT INTERCEPTED: CWatM attempted to exit with code: {code}"
        log.warning(error_msg)
        _err(error_msg,
             "Application prevented from terminating. CWatM execution stopped safely.",
             "=" * 50)
        return  # Don't propagate SystemExit

    # Log the full traceback to the GUI log file, and print it to stderr so it
    # appears in dark red in cwatminfo
    import traceback
    error_msg = f"APPLICATION ERROR: {exc_type.__name__}: {exc_value}"
    log.error(error_msg, exc_info=(exc_type, exc_value, exc_traceback))
    _err(error_msg,
         "The application encountered an error but will continue running.",
         "Full error details:")
    traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)
    _err("=" * 50)


def _create_app():
    """QApplication + Windows taskbar identity + colour theme + app icon."""
    # Set the Windows taskbar identity before any window exists
    _set_windows_app_id()

    # Required for QtWebEngine (OpenStreetMap view in the basin viewer)
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)

    # Restore the saved colour mode (Configure > Mode: Normal / Dark / Mikhail)
    # BEFORE the main window is built, so every widget style is generated from
    # the right theme tokens from the start.
    from src.gui.utils import theme
    theme.load_saved_theme()
    theme.apply_app_theme(app)

    # Application-wide icon (taskbar + all windows). Use the small multi-size icon
    # (16/32/48 px) so the taskbar renders it; fall back to cwatm.ico. Only set it
    # if it loads, so a missing file does not blank the icon embedded in the .exe.
    app_icon = QIcon(asset_path("cwatm_small.ico"))
    if app_icon.isNull():
        app_icon = QIcon(asset_path("cwatm.ico"))
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    return app


def _install_stdio_redirects(window):
    """Route stdout/stderr into the window's CWatM output box (I5: before show()).

    Returns the two redirectors; the caller must keep them referenced for as long
    as they are installed as sys.stdout / sys.stderr.
    """
    stdout_redirector = PrintRedirector(is_error=False)
    stderr_redirector = PrintRedirector(is_error=True)
    stdout_redirector.text_written.connect(window.append_to_cwatminfo)
    stderr_redirector.text_written.connect(window.append_to_cwatminfo)
    sys.stdout = stdout_redirector
    sys.stderr = stderr_redirector
    return stdout_redirector, stderr_redirector


def _schedule_startup_tasks(window):
    """Foreground the window, then warm the heavy stack up once the UI is idle.

    Registration order matters: the two 0 ms callbacks fire in the order they are
    queued, and _load_initial_settings must queue its own after these.
    """
    # Bring the GUI to the foreground and make it the active app once the splash
    # screen closes. Do it now and again shortly after (the splash may still be
    # closing when show() runs).
    _bring_to_front(window)
    QTimer.singleShot(0, lambda: _bring_to_front(window))
    QTimer.singleShot(_FOREGROUND_RETRY_MS, lambda: _bring_to_front(window))

    # Warm the heavy modules up in the background while the user reads the UI
    # (report §4.1) - keeps the first Run / Show Basin / Check Data responsive.
    QTimer.singleShot(_WARMUP_DELAY_MS, _warm_up_heavy_modules)

    # Pre-warm the QtWebEngine stack on a hidden view (report §T8) so the first
    # Show Basin / Analyse map / Timeseries plot opens without the one-off cost of
    # loading Qt6WebEngineCore.dll + spawning QtWebEngineProcess.
    QTimer.singleShot(_WEBENGINE_PREWARM_DELAY_MS,
                      lambda: _prewarm_webengine(window))


def _initial_settings_file(window):
    """The settings file to open at startup, or None.

    A path on the command line wins (this is what enables Windows file association
    / "Open with": CWatM_GUI.exe settings.ini). Otherwise, if Configure > "Load
    previous settings at start" is ticked, the most recently used file is reopened.
    """
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        return os.path.abspath(sys.argv[1])
    try:
        if window._settings.value("startup/load_previous", False, type=bool):
            recents = getattr(window, "_recent_files", None) or []
            prev = recents[0] if recents else None
            if prev and os.path.isfile(prev):
                return prev
    except Exception:
        log.debug("load-previous-at-start failed", exc_info=True)
    return None


def _load_initial_settings(window):
    """Queue the startup settings file (if any) for loading once the UI is up."""
    path = _initial_settings_file(window)
    if path:
        QTimer.singleShot(0, lambda p=path: window.load_recent_file(p))


def _exec(app):
    """Run the Qt event loop and return the process exit code.

    EXIT-STATUS POLICY (settled 2026-07-19; this replaced the original code):

    * A clean shutdown returns 0 **silently**. The old code called ``sys.exit(0)``
      *inside* a ``try`` that caught ``SystemExit``, so every normal quit printed
      "System exit intercepted in main loop: 0" / "Application will continue
      running..." into the output box while the window was closing. That message
      described a stray exit from model code, but in practice only ever announced
      a normal quit - it is gone.
    * A non-zero code is reported **and propagated** (the caller exits with it).
      The old code printed it and fell through, so the process always exited 0 and
      no caller or script could tell that the GUI had failed.

    Genuine stray ``sys.exit()`` calls from model code are still intercepted - that
    protection lives in ``handle_exception`` (installed as ``sys.excepthook``) and
    is unaffected. Only the never-triggered second layer here was removed.
    """
    try:
        return app.exec()
    except Exception as e:
        # A crash in the event loop itself: report it, but do not take the app down
        # harder than it already is.
        _err(f"Main application loop error: {str(e)}",
             "Attempting to continue...")
        return 0


def main():
    """Main application entry point"""
    _configure_qtwebengine()
    try:
        app = _create_app()

        # Set the global exception handler BEFORE the window is built, so a failure
        # during construction is reported rather than killing the app.
        sys.excepthook = handle_exception

        window = CWatMMainWindow()
        _redirectors = _install_stdio_redirects(window)   # noqa: F841 (keep alive)

        window.show()
        # The window is up - now the splash can go (§4.5: it showed real progress
        # instead of freezing over the import cascade).
        _close_splash()

        _schedule_startup_tasks(window)
        _load_initial_settings(window)

        # Run application with error protection
        exit_code = _exec(app)
        if exit_code:
            _err(f"Application exited with code: {exit_code}")
        sys.exit(exit_code)

    except Exception as e:
        # Last resort error handling
        print(f"Critical application error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
