"""CWatM Academy works without a login - every level, and the window itself.
Driven on a bare AcademyWindow - no map page."""

import pytest

pytestmark = pytest.mark.qt


class _MW:
    def __init__(self, unlocked):
        self._unlocked = unlocked
        self.login_opened = 0

    def levels_unlocked(self):
        return self._unlocked

    def open_account(self):
        self.login_opened += 1


def _window(mw):
    from src.gui.widgets.academy_window import AcademyWindow
    from PySide6.QtWidgets import QDialog
    w = AcademyWindow.__new__(AcademyWindow)          # skip __init__ (no map page)
    QDialog.__init__(w)                               # but a real Qt object (a parent)
    w.mw = mw
    return w


def _with_lesson_widgets(w):
    from PySide6.QtWidgets import QPushButton, QLabel, QTextBrowser
    w.complete_button, w.lesson_title, w.lesson_badge = QPushButton(), QLabel(), QLabel()
    w.lesson_body = QTextBrowser()
    return w


def test_no_login_gate_left():
    from src.gui.widgets import academy_window
    assert not hasattr(academy_window, "LOGIN_LEVEL")
    assert not hasattr(academy_window.AcademyWindow, "_needs_login")


@pytest.mark.parametrize("level", [4, 7, 10])
def test_a_high_level_logged_out_is_marked_complete(qapp, monkeypatch, level):
    """Logged out, Level 4 and up behave like any other level: the button marks
    it complete - no login box."""
    from src.gui.widgets import academy_window
    mw = _MW(unlocked=False)
    w = _with_lesson_widgets(_window(mw))
    monkeypatch.setattr(academy_window.progress, "completed_levels",
                        lambda: set(range(1, level)))
    monkeypatch.setattr(academy_window.progress, "current_level", lambda: level)
    w._show_level(level)
    assert w.complete_button.isEnabled()
    assert w.complete_button.text() == "Mark level complete"
    marked = []
    monkeypatch.setattr(academy_window.progress, "mark_complete",
                        lambda lvl: (marked.append(lvl), False)[1])
    w._on_complete_clicked()
    assert marked == [level]
    assert mw.login_opened == 0


@pytest.mark.parametrize("level, expected", [
    (1, "_replay_level1"), (2, "_start_level2_tour"), (3, "go_to_level")])
def test_a_completed_level_stays_available(qapp, monkeypatch, level, expected):
    """Completed is not greyed out: Levels 1/2 replay their exercise, a text
    level moves on - and nothing is marked (or paid) again."""
    from src.gui.widgets import academy_window
    w = _with_lesson_widgets(_window(_MW(unlocked=True)))
    monkeypatch.setattr(academy_window.progress, "completed_levels", lambda: {1, 2, 3})
    monkeypatch.setattr(academy_window.progress, "current_level", lambda: 4)
    marked, called = [], []
    monkeypatch.setattr(academy_window.progress, "mark_complete", marked.append)
    for name in ("_replay_level1", "_start_level2_tour", "go_to_level"):
        monkeypatch.setattr(w, name, lambda *a, n=name: called.append(n))
    w._show_level(level)
    assert w.complete_button.isEnabled()
    assert w.complete_button.text().startswith("Completed ✓ - ")
    w._on_complete_clicked()
    assert called == [expected] and marked == []


# ---- the Academy opens with or without a login ---------------------------------------

class _Host:
    """The bits of the main window open_academy touches."""

    def __init__(self, unlocked):
        self._unlocked = unlocked

    def levels_unlocked(self):
        return self._unlocked


@pytest.mark.parametrize("unlocked", [False, True])
def test_academy_opens_logged_in_or_out(qapp, monkeypatch, unlocked):
    from src.gui.components import main_window as mwm
    from src.gui.widgets import academy_window
    opened = []
    monkeypatch.setattr(mwm.QMessageBox, "question",
                        lambda *a, **k: pytest.fail("no login box"))
    monkeypatch.setattr(academy_window, "open_academy",
                        lambda parent=None: opened.append(parent))
    host = _Host(unlocked=unlocked)
    mwm.CWatMMainWindow.open_academy(host)
    assert opened == [host]
