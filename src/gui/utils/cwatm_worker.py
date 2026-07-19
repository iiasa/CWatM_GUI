"""
CWatM Worker Thread - Handles CWatM model execution in separate thread
"""

import sys
import gc
from PySide6.QtCore import QThread, Signal
from src.gui.utils.gui_log import get_logger
# cwatm.run_cwatm is NOT imported at module level (report §4.1): each run
# re-imports it fresh anyway (_fresh_cwatm), and cwatm_gui.py warms it up in a
# background thread after the window is shown, so the first Run stays responsive
# without paying the scientific-stack import at startup.

log = get_logger("cwatm_worker")


class _ProgressClockProxy:
    """Stand-in for the GUI progress clock handed to the model. The GUI hook in
    cwatm/management_modules/output.py calls meteo.progress_clock.setValue(pct)
    once per timestep - from the worker thread. Re-emitting the value as the
    worker's `progress` signal (a queued connection) updates the real clock AND
    the elapsed/remaining label on the GUI thread instead of touching a widget
    cross-thread."""

    def __init__(self, emit):
        self._emit = emit

    def setValue(self, value):
        self._emit(int(value))


class _GuiWindowProxy:
    """Wraps the main window for run_cwatm.mainwarm: every attribute falls through
    to the real window except progress_clock, which is the thread-safe proxy."""

    def __init__(self, gui_window, progress_clock):
        self._gui_window = gui_window
        self.progress_clock = progress_clock

    def __getattr__(self, name):
        return getattr(self._gui_window, name)


class CWatMWorker(QThread):
    """Worker thread for running CWatM model"""
    finished = Signal(bool, object)  # success, last_dis
    error = Signal(str)  # error message
    progress = Signal(int)  # progress value 0-100
    
    def __init__(self, file_path, args, gui_window):
        super().__init__()
        self.file_path = file_path
        self.args = args
        self.gui_window = gui_window
        self.should_stop = False
        
    @staticmethod
    def _fresh_cwatm():
        """Purge every cwatm.* module and re-import run_cwatm so each run starts from a
        completely fresh model state.

        CWatM keeps a lot of module-level state (globals dicts, scalar caches like
        cutmap / cdfFlag / MMaskMap, and caches inside individual modules). A partial
        reset left arrays from the previous run behind, which occasionally made a 2nd
        run of the same settings file fail. Reloading the whole package guarantees a
        clean slate every time."""
        for _name in [n for n in list(sys.modules) if n == 'cwatm' or n.startswith('cwatm.')]:
            try:
                del sys.modules[_name]
            except Exception:
                log.debug("could not purge module %s", _name, exc_info=True)
        import cwatm.run_cwatm as _fresh
        return _fresh

    def run(self):
        """Run CWatM in separate thread"""
        success = False
        last_dis = None

        try:
            # Check for stop signal before running
            if self.should_stop:
                return

            # Set progress to 0% before starting CWatM
            self.progress.emit(0)

            # Start every run from a clean, freshly imported CWatM (no stale caches).
            run_cwatm = self._fresh_cwatm()

            print(f"Worker: About to call run_cwatm.mainwarm with file: {self.file_path}, args: {self.args}")
            gui_proxy = _GuiWindowProxy(self.gui_window, _ProgressClockProxy(self.progress.emit))
            success, last_dis = run_cwatm.mainwarm(self.file_path, self.args, gui_proxy)
            print(f"Worker: CWatM returned: success={success}, last_dis={last_dis}")

        except Exception as e:
            if not self.should_stop:
                # Print the full CWatM traceback (file + line, e.g. readmeteo.py:137)
                # to the output box, then report a short message on the status bar.
                import traceback
                print(traceback.format_exc(), file=sys.stderr)
                self.error.emit(str(e))
        finally:
            # Clean up resources before finishing (the next run re-imports cwatm fresh,
            # so no explicit global-state clear is needed here).
            try:
                self._cleanup_worker_files()
            except Exception as cleanup_error:
                print(f"Cleanup error in worker thread: {str(cleanup_error)}", file=sys.stderr)

            # Only emit finished signal if not stopped
            if not self.should_stop:
                self.finished.emit(success, last_dis)

    def stop(self):
        """Request thread to stop and clean up resources"""
        self.should_stop = True

        # Clean up file operations in the worker thread context (the next run will
        # re-import cwatm fresh, so there is no cached global state to clear here).
        try:
            self._cleanup_worker_files()
        except Exception as e:
            print(f"Error in worker cleanup: {str(e)}", file=sys.stderr)
    
    def _cleanup_worker_files(self):
        """Clean up files from worker thread context"""
        try:
            import gc
            import netCDF4
            
            # Close netCDF files in this thread's context
            for obj in gc.get_objects():
                if isinstance(obj, netCDF4.Dataset):
                    try:
                        if obj._isopen:
                            obj.close()
                    except Exception:
                        log.debug("netCDF dataset close failed", exc_info=True)

            # Force garbage collection
            gc.collect()

        except ImportError:
            pass  # netCDF4 not available - nothing to clean up
        except Exception:
            log.debug("worker file cleanup failed", exc_info=True)