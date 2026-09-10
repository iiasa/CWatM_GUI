"""
GUI package for CWatM application
"""

# The ONE place the CWatM GUI version is written down. Read by the About dialog
# (Info > About CWatM) and scraped by installer/CWatM_GUI.iss at compile time, so
# bumping it here is enough for both the app and the installer. Keep the literal
# on one line as `__version__ = "X.YZ"` - the installer's preprocessor looks for
# that pattern and aborts the build if it cannot find it.
__version__ = "1.06"
