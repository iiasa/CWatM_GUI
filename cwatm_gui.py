#!/usr/bin/env python3
"""
CWatM GUI Application - Main Entry Point
A graphical user interface for the Community Water Model (CWatM) by IIASA

This application provides an intuitive interface for loading, parsing, editing,
and managing CWatM configuration files.

Usage:
    python cwatm_gui.py

Requirements:
    - Python 3.8+
    - PySide6
"""

import os
import sys

# --- Child-process model dispatch (subprocess run, report §3.1) ---------------
# "CWatM_GUI.exe --run-cwatm <settings.ini>" (or "python cwatm_gui.py --run-cwatmh
# <settings.ini>") runs ONLY the model runner and exits - placed before any Qt
# import so the child process stays light. In a frozen build this path is the
# fallback for when the dedicated CWatM_model.exe is missing (older build).
if "--run-cwatm" in sys.argv:
    try:  # frozen build: the bootloader has already shown the splash - close it
        import pyi_splash
        pyi_splash.close()
    except Exception:
        pass
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from src.gui.utils.cwatm_model_runner import main as _model_runner_main
    sys.exit(_model_runner_main(sys.argv[sys.argv.index("--run-cwatm") + 1:]))

# --- Child-process notebooklm CLI dispatch (CWatM AI login from the frozen exe) --
# The frozen build has no `python -m notebooklm`, so the CWatM AI Login… flow runs
# the bundled notebooklm CLI on THIS executable instead:
#   CWatM_GUI.exe --notebooklm-login login --browser-cookies firefox
# Everything after --notebooklm-login is passed straight to notebooklm's click CLI,
# in a fresh child process (so it can open a browser / write the session file and
# exit without touching the running GUI). Placed before any Qt import to stay light.
if "--notebooklm-login" in sys.argv:
    try:  # frozen build: close the bootloader splash if it is showing
        import pyi_splash
        pyi_splash.close()
    except Exception:
        pass
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    _idx = sys.argv.index("--notebooklm-login")
    _cli_args = sys.argv[_idx + 1:]
    # click reads sys.argv[1:]; argv[0] is just the program name.
    sys.argv = ["notebooklm"] + _cli_args
    from notebooklm.notebooklm_cli import main as _nlm_cli_main
    _nlm_cli_main()   # click runs the command and calls sys.exit itself
    sys.exit(0)       # reached only if click returns without exiting

# QtWebEngine (basin viewer OpenStreetMap view + Timeseries plot) configuration.
# Must be set BEFORE QApplication / any QtWebEngine import.
# - --disable-gpu: GPU-accelerated QtWebEngine renders a blank page on many Windows
#   setups (VMs, remote desktop, some drivers); software rendering is reliable.
# - --use-gl=angle --use-angle=swiftshader: SOFTWARE WebGL. With --disable-gpu
#   alone Chromium has NO WebGL at all, and MapLibre (Show Basin2's Plotly map)
#   requires WebGL - its canvas stays empty ("Failed to initialize WebGL").
#   SwiftShader is pure software, so the VM/RDP robustness of --disable-gpu is
#   kept. Leaflet/Plotly 2-D views are unaffected.
# - --no-sandbox + QTWEBENGINE_DISABLE_SANDBOX: Chromium's sandbox refuses to launch
#   QtWebEngineProcess.exe from a network path ("Can not launch QtWebEngineProcess
#   from network path if sandbox is enabled") - this app lives on a mapped network
#   share (P: -> \\pdrive\...), so the sandbox must be disabled.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--disable-gpu --no-sandbox "
                      "--use-gl=angle --use-angle=swiftshader")
os.environ.setdefault("QTWEBENGINE_DISABLE_SANDBOX", "1")

# Splash progress (frozen build only; §4.5). Since the §4.1 lazy imports the
# startup cost is PySide6 + the GUI modules - the scientific stack loads in the
# background after the window is up.
try:
    import pyi_splash
    pyi_splash.update_text("Loading Qt ...")
except Exception:
    pyi_splash = None  # not running from a PyInstaller bundle

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal, Qt, QTimer
from PySide6.QtGui import QIcon

if pyi_splash is not None:
    try:
        pyi_splash.update_text("Loading user interface ...")
    except Exception:
        pass

from src.gui.components.main_window import CWatMMainWindow
from src.gui.utils.gui_log import get_logger

log = get_logger("app")


def asset_path(*parts):
    """Absolute path to a bundled asset, working from source and when frozen.

    Handles both PyInstaller one-file (assets unpacked under sys._MEIPASS) and
    one-folder builds (assets in _internal/ AND/or next to the .exe).
    """
    bases = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            bases.append(meipass)                      # one-file temp / one-folder _internal
        bases.append(os.path.dirname(sys.executable))  # one-folder: folder with the .exe
    else:
        bases.append(os.path.dirname(os.path.abspath(__file__)))
    for base in bases:
        candidate = os.path.join(base, "assets", *parts)
        if os.path.exists(candidate):
            return candidate
    return os.path.join(bases[0], "assets", *parts)


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
    if pyi_splash is not None:
        try:
            pyi_splash.update_text("UI loaded")
            pyi_splash.close()
        except Exception:
            pass


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
            import openpyxl         # noqa: F401  (Excel menu; cold import is slow)
            # Analyse windows: plotly (Timeseries/Watercycle/Flow) + folium (maps),
            # so the first Analyse click doesn't block on their import.
            import plotly.graph_objects  # noqa: F401
            import folium               # noqa: F401
            log.debug("background warm-up finished")
        except Exception:
            log.debug("background warm-up failed", exc_info=True)
    import threading
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


class PrintRedirector(QObject):
    """Redirect print output to GUI"""
    text_written = Signal(str, bool)  # text, is_error
    
    def __init__(self, is_error=False):
        super().__init__()
        self.is_error = is_error
        
    def write(self, text):
        if text.strip():  # Only emit non-empty text
            self.text_written.emit(text, self.is_error)
    
    def flush(self):
        pass



def handle_exception(exc_type, exc_value, exc_traceback):
    """Global exception handler - prevents application termination on errors"""
    if issubclass(exc_type, KeyboardInterrupt):
        # Allow KeyboardInterrupt to propagate normally
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    if issubclass(exc_type, SystemExit):
        # Intercept SystemExit to prevent application termination
        error_msg = f"SYSTEM EXIT INTERCEPTED: CWatM attempted to exit with code: {exc_value.code if hasattr(exc_value, 'code') else 'unknown'}"
        log.warning(error_msg)
        print(error_msg, file=sys.stderr)
        print("Application prevented from terminating. CWatM execution stopped safely.", file=sys.stderr)
        print("=" * 50, file=sys.stderr)
        return  # Don't propagate SystemExit

    # Log the full traceback to the GUI log file, and print it to stderr so it
    # appears in dark red in cwatminfo
    import traceback
    error_msg = f"APPLICATION ERROR: {exc_type.__name__}: {exc_value}"
    log.error(error_msg, exc_info=(exc_type, exc_value, exc_traceback))
    print(error_msg, file=sys.stderr)
    print("The application encountered an error but will continue running.", file=sys.stderr)
    print("Full error details:", file=sys.stderr)
    traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)
    print("=" * 50, file=sys.stderr)


def main():
    """Main application entry point"""
    try:
        # Set the Windows taskbar identity before any window exists
        _set_windows_app_id()

        # Required for QtWebEngine (OpenStreetMap view in the basin viewer)
        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)

        app = QApplication(sys.argv)

        # Restore the saved colour mode (Configure ▸ Mode: Normal / Dark / Mikhail)
        # BEFORE the main window is built, so every widget style is generated from
        # the right theme tokens from the start.
        from src.gui.utils import theme
        theme.load_saved_theme()
        theme.apply_app_theme(app)

        # Application-wide icon (taskbar + all windows). Use the small multi-size icon
        # (16/32/48 px) so the taskbar renders it; fall back to cwatm.ico. Only set it
        # if it loads, so a missing file does not blank the icon embedded in the .exe.
        _app_icon = QIcon(asset_path("cwatm_small.ico"))
        if _app_icon.isNull():
            _app_icon = QIcon(asset_path("cwatm.ico"))
        if not _app_icon.isNull():
            app.setWindowIcon(_app_icon)

        # Set global exception handler
        sys.excepthook = handle_exception
        
        # Create separate print redirectors for stdout and stderr
        stdout_redirector = PrintRedirector(is_error=False)
        stderr_redirector = PrintRedirector(is_error=True)
        
        # Create and show main window
        window = CWatMMainWindow()
        
        # Connect print redirectors to window
        stdout_redirector.text_written.connect(window.append_to_cwatminfo)
        stderr_redirector.text_written.connect(window.append_to_cwatminfo)
        
        # Redirect stdout and stderr to our custom redirectors
        sys.stdout = stdout_redirector
        sys.stderr = stderr_redirector
        
        window.show()
        # The window is up - now the splash can go (§4.5: it showed real progress
        # instead of freezing over the import cascade).
        _close_splash()
        # Bring the GUI to the foreground and make it the active app once the splash
        # screen closes. Do it now and again shortly after (the splash may still be
        # closing when show() runs).
        _bring_to_front(window)
        QTimer.singleShot(0, lambda: _bring_to_front(window))
        QTimer.singleShot(300, lambda: _bring_to_front(window))

        # Warm the heavy modules up in the background while the user reads the UI
        # (report §4.1) - keeps the first Run / Show Basin / Check Data responsive.
        QTimer.singleShot(500, _warm_up_heavy_modules)

        # Pre-warm the QtWebEngine stack on a hidden view (report §T8) so the first
        # Show Basin / Analyse map / Timeseries plot opens without the one-off cost of
        # loading Qt6WebEngineCore.dll + spawning QtWebEngineProcess. A bit after the
        # module warm-up so the two heavy tasks do not contend at startup.
        QTimer.singleShot(1500, lambda: _prewarm_webengine(window))

        # Load a settings file passed on the command line (enables Windows
        # file association / "Open with"):  CWatM_GUI.exe  settings.ini
        if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
            settings_path = os.path.abspath(sys.argv[1])
            QTimer.singleShot(0, lambda: window.load_recent_file(settings_path))
        else:
            # Configure > "Load previous settings at start": if ticked, re-open the
            # most recently used settings file automatically.
            try:
                if window._settings.value("startup/load_previous", False, type=bool):
                    recents = getattr(window, "_recent_files", None) or []
                    prev = recents[0] if recents else None
                    if prev and os.path.isfile(prev):
                        QTimer.singleShot(0, lambda p=prev: window.load_recent_file(p))
            except Exception:
                log.debug("load-previous-at-start failed", exc_info=True)

        # Run application with error protection
        try:
            exit_code = app.exec()
            # Only exit if the application was closed normally
            if exit_code == 0:
                sys.exit(0)
            else:
                print(f"Application exited with code: {exit_code}", file=sys.stderr)
                
        except SystemExit as e:
            # Handle any remaining SystemExit attempts
            print(f"System exit intercepted in main loop: {e.code}", file=sys.stderr)
            print("Application will continue running...", file=sys.stderr)
            
        except Exception as e:
            # Handle any other exceptions in the main loop
            print(f"Main application loop error: {str(e)}", file=sys.stderr)
            print("Attempting to continue...", file=sys.stderr)
            
    except Exception as e:
        # Last resort error handling
        print(f"Critical application error: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()