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


def _qt_available():
    try:
        import PySide6  # noqa: F401
    except Exception:
        return False
    return True


# A marker alone is not enough to keep a Qt-free run working: pytest **imports** every
# test module during collection, before it filters on markers, so a module whose import
# needs PySide6 fails to collect even under `-m "not qt"`. When Qt is missing, drop
# those files from collection outright. The list is derived from the files themselves
# (they declare `pytestmark = pytest.mark.qt`) rather than hand-kept here, because a
# hand-kept list is exactly what drifted before.
collect_ignore = []
if not _qt_available():
    _here = os.path.dirname(os.path.abspath(__file__))
    for _name in sorted(os.listdir(_here)):
        if not _name.startswith("test_") or not _name.endswith(".py"):
            continue
        with open(os.path.join(_here, _name), encoding="utf-8") as _fh:
            if "pytest.mark.qt" in _fh.read():
                collect_ignore.append(_name)


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session (Qt allows only one)."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def isolated_qsettings(tmp_path):
    """Redirect QSettings("IIASA", "CWatM_GUI") to a throwaway ini file for the
    duration of one test, restoring the previous default format afterward.

    Without this, constructing a real window (CWatMMainWindow, BatchRunnerWindow,
    ...) in a test reads/writes the developer's actual persisted settings (recent
    files, "Load previous settings at start", a saved batch table, ...) - both
    polluting real state and making the test's outcome depend on whatever is
    already saved on the machine it happens to run on."""
    from PySide6.QtCore import QSettings
    previous = QSettings.defaultFormat()
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    yield
    QSettings.setDefaultFormat(previous)
