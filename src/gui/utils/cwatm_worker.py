"""
CWatM Worker Thread - Handles CWatM model execution in separate thread
"""

import sys
import gc
from PySide6.QtCore import QThread, Signal
import cwatm.run_cwatm as run_cwatm
from cwatm.management_modules.globals import calibclear


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

            print(f"Worker: About to call run_cwatm.mainwarm with file: {self.file_path}, args: {self.args}")
            success, last_dis = run_cwatm.mainwarm(self.file_path, self.args, self.gui_window)
            print(f"Worker: CWatM returned: success={success}, last_dis={last_dis}")
            
        except Exception as e:
            if not self.should_stop:
                self.error.emit(str(e))
        finally:
            # Clean up resources before finishing
            try:
                self._cleanup_worker_files()
                calibclear()
            except Exception as cleanup_error:
                print(f"Cleanup error in worker thread: {str(cleanup_error)}", file=sys.stderr)
            
            # Only emit finished signal if not stopped
            if not self.should_stop:
                self.finished.emit(success, last_dis)
    
    def stop(self):
        """Request thread to stop and clean up resources"""
        self.should_stop = True
        
        # Clean up file operations in the worker thread context
        try:
            self._cleanup_worker_files()
        except Exception as e:
            print(f"Error in worker cleanup: {str(e)}", file=sys.stderr)
        
        # Clear the calibration cache to prevent issues
        try:
            calibclear()
        except Exception as e:
            print(f"Error clearing calibration cache: {str(e)}", file=sys.stderr)
    
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
                    except:
                        pass
                        
            # Force garbage collection
            gc.collect()
            
        except ImportError:
            pass
        except Exception:
            pass