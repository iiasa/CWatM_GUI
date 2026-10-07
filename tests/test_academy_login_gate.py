"""CWatM Academy: from Level 4 on a login is needed (same check as the Advanced /
Expert skill levels). Driven on a bare AcademyWindow - no map page."""

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


def test_levels_1_to_3_are_free(qapp):
    w = _window(_MW(unlocked=False))
    assert not any(w._needs_login(i) for i in (1, 2, 3))


def test_level_4_and_up_need_a_login(qapp):
    from src.gui.widgets.academy_window import LOGIN_LEVEL
    assert LOGIN_LEVEL == 4
    logged_out = _window(_MW(unlocked=False))
    assert logged_out._needs_login(4) and logged_out._needs_login(10)
    logged_in = _window(_MW(unlocked=True))
    assert not logged_in._needs_login(4)


def test_complete_button_explains_and_offers_the_login(qapp, monkeypatch):
    from src.gui.widgets import academy_window
    mw = _MW(unlocked=False)
    w = _window(mw)
    w._current_level_id = 4
    monkeypatch.setattr(academy_window.QMessageBox, "exec",
                        lambda self: academy_window.QMessageBox.Yes)
    marked = []
    monkeypatch.setattr(academy_window.progress, "mark_complete", marked.append)
    w._on_complete_clicked()
    assert mw.login_opened == 1          # the login dialog was offered and opened
    assert marked == []                  # nothing was marked complete


def test_login_box_sets_its_own_colours(qapp, monkeypatch):
    """The box inherits the Academy window's black QDialog background, so it must
    set its text colour itself - relying on the app palette gave black on black in
    Normal mode."""
    from src.gui.widgets import academy_window
    seen = []

    def fake_exec(box):
        seen.append(box.styleSheet())
        return academy_window.QMessageBox.No

    monkeypatch.setattr(academy_window.QMessageBox, "exec", fake_exec)
    w = _window(_MW(unlocked=False))
    assert w._academy_question("t", "x") is False
    css = seen[0]
    text = academy_window._C["text"]
    bg = academy_window._C["window_bg"]
    assert f"QMessageBox QLabel {{ color: {text};" in css
    assert f"background-color: {bg};" in css
    assert text.lower() != bg.lower()


@pytest.mark.parametrize("level, expected", [
    (1, "_replay_level1"), (2, "_start_level2_tour"), (3, "go_to_level")])
def test_a_completed_level_stays_available(qapp, monkeypatch, level, expected):
    """Completed is not greyed out: Levels 1/2 replay their exercise, a text
    level moves on - and nothing is marked (or paid) again."""
    from PySide6.QtWidgets import QPushButton, QLabel, QTextBrowser
    from src.gui.widgets import academy_window
    w = _window(_MW(unlocked=True))
    w.complete_button, w.lesson_title, w.lesson_badge = QPushButton(), QLabel(), QLabel()
    w.lesson_body = QTextBrowser()
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
