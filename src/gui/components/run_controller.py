"""
CWatM run control for the CWatM GUI main window.

Extracted verbatim from main_window.py: starting/stopping the threaded CWatM run,
progress/finished/error handling, run-log file handling, menu locking while a run
is active, RUN-button styling, and post-run resource cleanup. Mixed into
CWatMMainWindow - all state lives on the main window instance.
"""

import os
import sys
import gc
import time

from PySide6.QtCore import QTimer

from src.gui.utils.cwatm_worker import CWatMWorker
from src.gui.utils.cwatm_process_worker import CWatMProcessWorker
from src.gui.utils import display_format
from src.gui.utils import run_ledger
from src.gui.utils.gui_log import get_logger

log = get_logger("run_controller")


class RunControllerMixin:
    """Run/stop CWatM, track its progress and clean up afterwards."""

    def open_hidden_run(self):
        """RUN CWATM > Hidden Run CWatM: open an independent window that runs CWatM in
        its own OS process, pre-loaded with the current settings file. It does not
        touch the main run or the main GUI, and several can be open/running at once."""
        # Lazy import (fast-startup rule): only pulls light Qt/subprocess modules.
        from src.gui.widgets.hidden_run_window import HiddenRunWindow
        if not hasattr(self, "_hidden_run_windows"):
            self._hidden_run_windows = []  # keep refs so the non-modal windows live
        win = HiddenRunWindow(self)
        # Drop the reference when the window is closed so the list does not grow.
        win.destroyed.connect(
            lambda *_: self._hidden_run_windows.remove(win)
            if win in self._hidden_run_windows else None)
        self._hidden_run_windows.append(win)
        win.show()
        win.raise_()
        win.activateWindow()

    def run_cwatm(self):
        """Handle CWatM button click - run or stop CWatM model"""
        if self.cwatm_running:
            # If CWatM is running, stop it
            self.stop_cwatm_execution()
            return
            
        # Close open windows before starting CWatM
        self.close_subsidiary_windows()
            
        # If not running, start CWatM
        if not self.file_manager.has_file_loaded():
            self.status_bar.showMessage("No settings file loaded")
            return

        # Apply any pending (debounced) field changes before running
        self._flush_pending_field_changes()

        # Get current file path and name
        file_path = self.file_manager.get_current_file_path()
        
        if not file_path:
            self.status_bar.showMessage("No settings file information available")
            print("No settings file available for CWatM execution")
            return
            
        # Clear previous output first
        self._pending_output.clear()
        self._last_was_progress = False
        self.cwatminfo_box.clear()  # placeholder text shows again

        # Setup output file if the Configure > "Write output" menu item is ticked.
        # Location is the custom file (Configure > Set output box file) or the default
        # <PathOut>/cwatm_out.txt. Read the mirrored bool so a deleted QAction C++
        # object can never crash the run. The file handle is opened once here and kept
        # open for the whole run (closed in _finalize_output_file) - per-line
        # open/append/flush was a real slowdown on network shares.
        try:
            _write_output = self.write_output_action.isChecked()
        except RuntimeError:
            _write_output = getattr(self, "_write_output_enabled", False)
        self._close_output_file_handle()  # safety: never leak a handle from a previous run
        if _write_output:
            self.output_file_path = self._output_file()
            # Make sure the target folder exists
            try:
                os.makedirs(os.path.dirname(self.output_file_path), exist_ok=True)
            except Exception:
                log.warning("could not create run-log directory", exc_info=True)
            # Append a header block to the output file (do not overwrite previous runs
            # and do not show these lines in the output box).
            try:
                self._output_file_handle = open(self.output_file_path, 'a', encoding='utf-8')
                self._output_file_handle.write("=================================\n")
                self._output_file_handle.write(time.strftime('%Y-%m-%d %H:%M:%S') + "\n")
                self._output_file_handle.write("---------------------------------\n")
                self._output_file_handle.flush()
                print(f"Writing output to file: {self.output_file_path}")
            except Exception as e:
                print(f"Error creating output file: {e}")
                self._close_output_file_handle()
                self.output_file_path = None
        else:
            self.output_file_path = None
        
        # Reset progress clock to 0 and start the elapsed/remaining display.
        # A 1-second timer keeps "elapsed" ticking between progress signals (which
        # only arrive once per model timestep and can be minutes apart).
        self.progress_clock.setValue(0)
        # Reset the live discharge sparkline for the new run
        spark = getattr(self, "discharge_sparkline", None)
        if spark is not None:
            spark.clear()
        self._run_start_time = time.time()
        # Capture facts for the Run Ledger (logged on finish/error/stop). The
        # settings content the run uses is the file on disk - snapshot it so Compare
        # settings can diff exactly what ran, even if the file is edited later.
        run_content = None
        try:
            with open(file_path, encoding="utf-8", errors="ignore") as _f:
                run_content = _f.read()
        except Exception:
            run_content = None
        self._run_ledger_ctx = {
            "settings": file_path,
            "title": self._current_settings_title(),
            "pathout": self._resolved_pathout_dir() or "",
            "started_at": self._run_start_time,
            "content": run_content,
        }
        self._last_progress_value = 0
        self.progress_clock.set_time_lines("elapsed 0:00:00")
        if getattr(self, "_run_time_timer", None) is None:
            self._run_time_timer = QTimer(self)
            self._run_time_timer.setInterval(1000)
            self._run_time_timer.timeout.connect(self._on_run_time_tick)
        self._run_time_timer.start()

        print(f"Starting CWatM with settings file: {file_path}")
        self.status_bar.showMessage(f"Settings file: {file_path} - Starting run")
        
        # Set running state
        self.cwatm_running = True
        self.set_cwatm_button_running_state()

        # Disable the menu tools while CWatM runs (re-enabled on finish/error)
        self._set_tools_enabled(False)

        # Create and start the worker. Default: a separate OS process (report
        # §3.1 - real Stop, crash isolation, fresh interpreter each run); the
        # Configure > "Run model in separate process" toggle falls back to the
        # old in-process QThread worker.
        if getattr(self, "_run_subprocess_enabled", True):
            # Run from the working directory (File > Change Working Dir; by default
            # the settings file's own folder) so relative paths resolve from there.
            self.cwatm_worker = CWatMProcessWorker(
                file_path, self, working_dir=self.working_dir() or None)
        else:
            self.cwatm_worker = CWatMWorker(file_path, ['-lg'], self)
        self.cwatm_worker.finished.connect(self.on_cwatm_finished)
        self.cwatm_worker.error.connect(self.on_cwatm_error)
        self.cwatm_worker.progress.connect(self.on_cwatm_progress)
        self.cwatm_worker.start()
    
    def on_cwatm_progress(self, value):
        """Handle CWatM execution progress updates (queued signal on the GUI thread;
        the event loop repaints once this slot returns - no processEvents needed)."""
        self.progress_clock.setValue(value)
        self._last_progress_value = value
        self._update_run_time_label(value)

    # ------------------------------------------------------ elapsed / remaining time
    @staticmethod
    def _fmt_duration(seconds):
        """Format seconds as h:mm:ss."""
        seconds = max(0, int(seconds))
        return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"

    def _on_run_time_tick(self):
        """1-second heartbeat: refresh elapsed/remaining with the last known progress."""
        self._update_run_time_label(getattr(self, "_last_progress_value", 0))

    def _update_run_time_label(self, value):
        """Refresh the 'elapsed' / 'remaining' lines shown INSIDE the progress
        clock face. The remaining time is a linear estimate from the completed
        fraction."""
        if self._run_start_time is None:
            return
        elapsed = time.time() - self._run_start_time
        lines = [f"elapsed {self._fmt_duration(elapsed)}"]
        if 0 < value < 100:
            remaining = elapsed * (100 - value) / value
            lines.append(f"remaining ~{self._fmt_duration(remaining)}")
        self.progress_clock.set_time_lines(*lines)

    def _finish_run_time_label(self, prefix):
        """Freeze the time display when the run ends (finished / failed / stopped)."""
        timer = getattr(self, "_run_time_timer", None)
        if timer is not None:
            timer.stop()
        if self._run_start_time is not None:
            elapsed = time.time() - self._run_start_time
            self.progress_clock.set_time_lines(f"{prefix} {self._fmt_duration(elapsed)}")
            self._run_start_time = None



    def _current_settings_title(self):
        """The settings ``Title`` value from the current editor content, or ""."""
        try:
            content = self.text_area.toPlainText()
        except Exception:
            return ""
        for line in content.split("\n"):
            s = line.strip()
            if not s or s[0] in "#;[" or "=" not in s:
                continue
            key, value = s.split("=", 1)
            if key.strip().lower() == "title":
                return value.strip()
        return ""

    def _log_run_to_ledger(self, success, last_dis, kind="run"):
        """Append this run to the Run Ledger (best-effort; never breaks the run)."""
        ctx = getattr(self, "_run_ledger_ctx", None)
        if not ctx:
            return
        self._run_ledger_ctx = None  # log a run only once
        try:
            last = None
            if last_dis is not None:
                try:
                    last = float(last_dis)
                except (TypeError, ValueError):
                    last = None
            run_ledger.add_entry(run_ledger.make_entry(
                ctx.get("settings"), ctx.get("title"), ctx.get("pathout"),
                ctx.get("started_at"), success, last, kind=kind,
                content=ctx.get("content")))
        except Exception:
            log.debug("run-ledger logging failed", exc_info=True)

    def _close_output_file_handle(self):
        """Close the run-log file handle if one is open. Safe to call at any time."""
        fh = self._output_file_handle
        self._output_file_handle = None
        if fh is not None:
            try:
                fh.close()
            except Exception:
                log.debug("run-log close failed", exc_info=True)

    def _open_output_file_note(self, label):
        """Open the output-box log file (append) for a non-run note - e.g. the
        Check settingsfile summary - so that, when Configure ▸ 'Write output box'
        is on, whatever is printed via append_to_cwatminfo is also written to the
        file. Writes the same header block as a run and returns True if a handle
        was opened (the caller must call _finalize_output_file afterwards).

        No-op (returns False) if a handle is already open (a run is writing the
        file): append_to_cwatminfo then just appends to that active log."""
        if self._output_file_handle is not None:
            return False
        self.output_file_path = self._output_file()
        try:
            os.makedirs(os.path.dirname(self.output_file_path), exist_ok=True)
            self._output_file_handle = open(self.output_file_path, 'a', encoding='utf-8')
            self._output_file_handle.write("=================================\n")
            self._output_file_handle.write(
                time.strftime('%Y-%m-%d %H:%M:%S') + f"  {label}\n")
            self._output_file_handle.write("---------------------------------\n")
            self._output_file_handle.flush()
            return True
        except Exception:
            log.warning("could not open output file for note", exc_info=True)
            self._close_output_file_handle()
            self.output_file_path = None
            return False

    def _finalize_output_file(self):
        """Append a trailing blank line to the output-box file after a run's content
        (not shown in the output box) and close the run-log file handle."""
        if self._output_file_handle is not None:
            try:
                self._output_file_handle.write("\n")
            except Exception:
                log.debug("run-log trailer not written", exc_info=True)
            self._close_output_file_handle()

    def on_cwatm_finished(self, success, last_dis):
        """Handle CWatM execution completion"""
        if success:
            # Format last discharge with the global display decimals
            try:
                last_dis_formatted = display_format.fmt(last_dis) if last_dis is not None else "N/A"
            except (ValueError, TypeError):
                last_dis_formatted = str(last_dis) if last_dis is not None else "N/A"

            print(f"CWatM completed successfully.")
            self.status_bar.showMessage(f"CWatM success: {success}  last discharge: {last_dis_formatted}")
        else:
            print("CWatM execution failed")
            self.status_bar.showMessage("CWatM execution failed")

        # Trailing blank line in the output file after the run's content
        self._finalize_output_file()
        self._log_run_to_ledger(success, last_dis)
        self._finish_run_time_label("run time")

        # Reset state but keep progress clock value
        self.cwatm_running = False
        self.cwatm_worker = None
        # Don't reset progress clock - keep final completion percentage
        self.set_cwatm_button_ready_state()

        self._set_tools_enabled(True)

    def on_cwatm_error(self, error_message):
        """Handle CWatM execution error"""
        print(f"CWatM execution error: {error_message}", file=sys.stderr)
        self.status_bar.showMessage(f"CWatM execution error: {error_message}")

        # Trailing blank line in the output file after the run's content
        self._finalize_output_file()
        self._log_run_to_ledger(False, None)
        self._finish_run_time_label("failed after")

        # Clean up file operations after error - only for the in-process worker
        # (a subprocess owns its files; the OS reclaims them when it exits)
        if not isinstance(self.cwatm_worker, CWatMProcessWorker):
            self.cleanup_file_operations()
        
        # Reset state but keep progress clock value
        self.cwatm_running = False
        self.cwatm_worker = None
        # Don't reset progress clock - keep progress where error occurred
        self.set_cwatm_button_ready_state()
        
        self._set_tools_enabled(True)

    def _set_tools_enabled(self, enabled):
        """While CWatM runs, keep all functionality available except **Save** (the
        run uses the file on disk, so overwriting it mid-run is disallowed). Only the
        Save button and the File > Save .ini menu action are greyed out; Save As stays
        available. Re-enabled when the run finishes, errors, or is stopped."""
        # Save button (left window) - grey out while running, restore afterwards.
        btn = getattr(self, "save_button", None)
        if btn is not None:
            try:
                btn.setEnabled(enabled)
            except RuntimeError:
                pass
        # File > Save .ini menu action.
        act = getattr(self, "_save_menu_action", None)
        if act is not None:
            try:
                act.setEnabled(enabled)
            except RuntimeError:
                pass

    def set_cwatm_button_running_state(self):
        """Set RUN CWatM button to running state (light red)"""
        self._run_btn_state = "running"
        self.run_cwatm_button.setText("STOP CWatM")
        self.run_cwatm_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #e74c3c, stop:1 #c0392b);
                border: 2px solid #c0392b;
                border-radius: 8px;
                color: white;
                font-weight: 600;
                font-size: 13px;
                padding: 8px 16px;
                min-height: 32px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #ec7063, stop:1 #a93226);
                border-color: #a93226;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #c0392b, stop:1 #922b21);
                border-color: #922b21;
            }
        """)
        
    def set_cwatm_button_ready_state(self):
        """Set RUN CWatM button to ready state (blue)"""
        self._run_btn_state = "ready"
        self.run_cwatm_button.setText("RUN CWatM")
        self.run_cwatm_button.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #2980b9, stop:1 #3498db);
                border: 2px solid #3498db;
                border-radius: 8px;
                color: white;
                font-weight: 600;
                font-size: 13px;
                padding: 8px 16px;
                min-height: 32px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #3498db, stop:1 #5dade2);
                border-color: #5dade2;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #2471a3, stop:1 #2980b9);
                border-color: #2471a3;
            }
            QPushButton:disabled {
                background: #bdc3c7;
                color: #7f8c8d;
                border: 2px solid #95a5a6;
            }
        """)
        
    def stop_cwatm_execution(self):
        """Stop CWatM execution and clean up file operations"""
        if self.cwatm_running and isinstance(self.cwatm_worker, CWatMProcessWorker):
            # Subprocess run: Stop is a real kill - immediate, works even when the
            # model hangs in C code, and needs no in-GUI file cleanup.
            try:
                self.cwatm_worker.stop()
                print("CWatM process stopped (killed) by user", file=sys.stderr)
                self.status_bar.showMessage("CWatM execution stopped by user")
            except Exception as e:
                print(f"Error stopping CWatM process: {e}", file=sys.stderr)
                self.status_bar.showMessage(f"Error stopping CWatM: {e}")
        elif self.cwatm_running and self.cwatm_worker:
            try:
                # Request worker thread to stop
                self.cwatm_worker.stop()
                print("CWatM execution stop requested by user", file=sys.stderr)
                self.status_bar.showMessage("Stopping CWatM execution...")
                
                # Clean up file operations immediately
                self.cleanup_file_operations()
                
                # Disconnect signals to prevent issues during termination
                try:
                    self.cwatm_worker.finished.disconnect()
                    self.cwatm_worker.error.disconnect() 
                    self.cwatm_worker.progress.disconnect()
                except Exception:
                    log.debug("worker signals already disconnected")
                
                # Wait a longer time for graceful stop
                if self.cwatm_worker.wait(5000):  # Wait up to 5 seconds
                    print("CWatM execution stopped gracefully", file=sys.stderr)
                else:
                    # Force terminate if not stopped gracefully
                    print("Forcing CWatM thread termination...", file=sys.stderr)
                    self.cwatm_worker.terminate()
                    
                    # Wait for termination to complete
                    if self.cwatm_worker.wait(2000):  # Wait 2 more seconds after terminate
                        print("CWatM execution terminated", file=sys.stderr)
                    else:
                        print("CWatM thread termination timed out", file=sys.stderr)
                    
                    # Additional cleanup after force termination
                    self.cleanup_file_operations()
                    
                self.status_bar.showMessage("CWatM execution stopped by user")
            except Exception as e:
                print(f"Error stopping CWatM: {str(e)}", file=sys.stderr)
                self.status_bar.showMessage(f"Error stopping CWatM: {str(e)}")

        # Close the run-log file (trailing blank line) - the run is over
        self._finalize_output_file()
        self._log_run_to_ledger(False, None, kind="stopped")
        self._finish_run_time_label("stopped after")

        # Reset state but keep progress clock value
        self.cwatm_running = False
        
        # Clear the worker reference safely
        if self.cwatm_worker:
            self.cwatm_worker.deleteLater()
            self.cwatm_worker = None
            
        # Don't reset progress clock - keep progress where execution was stopped
        self.set_cwatm_button_ready_state()

        # Re-enable the menu tools after the run is stopped
        self._set_tools_enabled(True)

    

    def cleanup_file_operations(self):
        """Clean up all open file operations including netCDF files"""
        try:
            print("Cleaning up file operations...", file=sys.stderr)
            
            # 1. Close all netCDF files
            self._cleanup_netcdf_files()
            
            # 2. Close any other file handles
            self._cleanup_general_files()
            
            # 3. Force garbage collection to clean up unreferenced objects
            gc.collect()
            
            print("File cleanup completed", file=sys.stderr)
            
        except Exception as e:
            print(f"Error during file cleanup: {str(e)}", file=sys.stderr)
    
    def _cleanup_netcdf_files(self):
        """Specifically clean up netCDF4 files"""
        try:
            import netCDF4
            
            # Get all netCDF4 Dataset objects and close them
            for obj in gc.get_objects():
                if isinstance(obj, netCDF4.Dataset):
                    try:
                        if not obj._isopen:
                            continue
                        obj.close()
                    except Exception as e:
                        print(f"Error closing netCDF file: {str(e)}", file=sys.stderr)
                        
        except ImportError:
            # netCDF4 not available
            pass
        except Exception as e:
            print(f"Error in netCDF cleanup: {str(e)}", file=sys.stderr)
    
    def _protected_file_objects(self):
        """File-like objects that must NEVER be closed by the generic cleanup:
        the process std streams, the GUI log-file stream and the run-log handle.
        (Closing sys.stdout/stderr kills all further output; closing the logging
        stream silently disables the diagnostic log.)"""
        import logging
        roots = [sys.stdin, sys.stdout, sys.stderr,
                 sys.__stdin__, sys.__stdout__, sys.__stderr__,
                 self._output_file_handle]
        for handler in logging.getLogger("cwatm_gui").handlers:
            roots.append(getattr(handler, "stream", None))
        # Include the wrapped layers (TextIOWrapper -> BufferedWriter -> FileIO):
        # closing an inner layer breaks the outer stream just the same.
        protected = set()
        for obj in roots:
            while obj is not None and obj not in protected:
                protected.add(obj)
                obj = getattr(obj, "buffer", None) or getattr(obj, "raw", None)
        return protected

    def _cleanup_general_files(self):
        """Close file handles left open by an interrupted CWatM run. Skips the
        process/log streams (see _protected_file_objects) - closing those broke all
        subsequent output and logging."""
        try:
            import io

            protected = self._protected_file_objects()
            for obj in gc.get_objects():
                if isinstance(obj, io.IOBase) and obj not in protected:
                    try:
                        if not obj.closed:
                            obj.close()
                    except Exception as e:
                        print(f"Error closing file handle: {str(e)}", file=sys.stderr)

        except Exception as e:
            print(f"Error in general file cleanup: {str(e)}", file=sys.stderr)
