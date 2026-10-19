"""Per-user folder for the GUI's own files (``gui.log``, the run journal).

``%LOCALAPPDATA%`` on Windows; ``~/Library/Application Support`` on macOS (the temp
folder there is cleared by the system, which would lose the journal); the system
temp folder elsewhere (Linux keeps its previous behaviour).
"""
import os
import sys
import tempfile


def user_data_base():
    """The folder that holds the ``CWatM_GUI`` directory."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return base
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    return tempfile.gettempdir()
