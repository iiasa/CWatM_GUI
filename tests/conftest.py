"""Shared test setup.

Two jobs: put the repo root on `sys.path` so `src.gui...` imports resolve however
pytest was invoked, and make Qt headless before anything imports PySide6 - a few
modules (`settings_check` imports QDate, `temp_page` imports QUrl) pull Qt in even
though the logic under test is pure.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Must be set before the first PySide6 import, not before the first widget.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CWATM_GUI_NO_MAXIMIZE", "1")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session (Qt allows only one)."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
