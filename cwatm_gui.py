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

import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal

from src.gui.components.main_window import CWatMMainWindow

# for closing the splash scfreen of the GUI
try:
    import pyi_splash
    pyi_splash.update_text("UI loaded")
    pyi_splash.close()
except:
    ii =1


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
        import traceback
        error_msg = f"SYSTEM EXIT INTERCEPTED: CWatM attempted to exit with code: {exc_value.code if hasattr(exc_value, 'code') else 'unknown'}"
        print(error_msg, file=sys.stderr)
        print("Application prevented from terminating. CWatM execution stopped safely.", file=sys.stderr)
        print("=" * 50, file=sys.stderr)
        return  # Don't propagate SystemExit
    
    # Print exception to stderr so it appears in dark red in cwatminfo
    import traceback
    error_msg = f"APPLICATION ERROR: {exc_type.__name__}: {exc_value}"
    print(error_msg, file=sys.stderr)
    print("The application encountered an error but will continue running.", file=sys.stderr)
    print("Full error details:", file=sys.stderr)
    traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)
    print("=" * 50, file=sys.stderr)


def main():
    """Main application entry point"""
    try:
        app = QApplication(sys.argv)
        
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