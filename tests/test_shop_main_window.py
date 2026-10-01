"""The Shop's rules on the REAL main window (shop.md Step 7): the level button
refuses a level that is not owned, Preferences ▸ Select animal lists only bought
animals, and the session-only Cheat tick is off again after a restart.

The window's settings go to a throwaway ini file: QSettings("IIASA", "CWatM_GUI")
always means the registry (setDefaultFormat does not apply to that constructor), so
main_window's QSettings is replaced by an ini-backed one. No network: the account
server counts as configured, but the worker is a fake.
Windows are never closed (see test_startup_speed: closeEvent's file cleanup can take
pytest's capture stream down). So the logins here are "restore" (the silent re-login),
never "login": an interactive login schedules the one-time run-location QMessageBox
400 ms later, and on a window that stays alive it popped up - modal, unanswered -
inside whichever LATER test processed events, hanging the whole suite."""

import pytest

pytestmark = pytest.mark.qt

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from tests.test_account_ui import FakeWorker, STATUS  # noqa: E402


def _status(*owned):
    return dict(STATUS, earned_points=60, balance=10,
                purchases=[{"code": c} for c in owned])


@pytest.fixture
def make_window(qapp, tmp_path, monkeypatch):
    from src.gui.components import main_window as M
    from src.gui.utils import account_config
    ini = str(tmp_path / "cwatm_gui.ini")
    monkeypatch.setattr(M, "QSettings",
                        lambda *a, **k: QSettings(ini, QSettings.IniFormat))
    monkeypatch.setattr(account_config, "is_configured", lambda: True)
    monkeypatch.chdir(tmp_path)
    messages = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *a, **k: messages.append(a[2]) or QMessageBox.No))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(
        lambda *a, **k: messages.append(a[2])))

    def make():
        w = M.CWatMMainWindow()
        w.fake = FakeWorker()
        w.account_worker = lambda: w.fake          # never a real network thread
        return w
    make.messages = messages
    make.ini = ini
    return make


class TestLevelButton:
    def test_logged_out_the_button_refuses_and_says_how(self, make_window):
        w = make_window()
        assert w._experience_level == "Beginner"   # preferred Expert, nothing owned
        w.cycle_experience_level()
        assert w._experience_level == "Beginner"
        msg = make_window.messages[-1]
        assert "Advanced" in msg and "Cheat" in msg   # both ways out are named

    def test_set_level_refuses_an_unowned_level(self, make_window):
        w = make_window()
        w._on_account_succeeded("restore", _status("advanced"))
        assert w._experience_level == "Advanced"   # preferred Expert -> highest owned
        make_window.messages.clear()
        w.set_experience_level("Expert")
        assert w._experience_level == "Advanced"
        assert "Expert" in make_window.messages[-1]
        assert "Shop" in make_window.messages[-1]

    def test_buying_expert_switches_to_the_preferred_level(self, make_window):
        w = make_window()
        w._on_account_succeeded("restore", _status("advanced"))
        w._on_account_succeeded("buy", _status("advanced", "expert"))
        assert w._experience_level == "Expert"


class TestPreferencesAnimals:
    def _prefs(self, w):
        from src.gui.widgets.preferences_window import PreferencesWindow
        return PreferencesWindow(w)

    def test_none_bought(self, make_window):
        w = make_window()
        p = self._prefs(w)
        assert p.cmb_animal.count() == 1 and not p.cmb_animal.isEnabled()
        assert "buy one in the Shop" in p.cmb_animal.itemText(0)
        assert w.discharge_sparkline._animal is None        # the plain dot
        p.deleteLater()

    def test_only_the_bought_ones(self, make_window):
        w = make_window()
        w._on_account_succeeded("restore", _status("otter", "octopus"))
        p = self._prefs(w)
        offered = [p.cmb_animal.itemData(i) for i in range(p.cmb_animal.count())]
        assert offered == ["Otter", "Octopus (for Carla)"]
        assert w.discharge_sparkline._animal == "Otter"     # Fish chosen, not owned
        p.deleteLater()


class TestCheat:
    def test_cheat_is_off_after_a_restart(self, make_window):
        w1 = make_window()
        w1._set_cheat_levels(True)
        w1.set_experience_level("Expert")
        assert w1._experience_level == "Expert"
        w1._settings.sync()
        w2 = make_window()                                  # "the next start"
        assert w2.cheat_levels() is False
        assert w2._experience_level == "Beginner"
        with open(make_window.ini, encoding="utf-8") as f:
            assert "cheat" not in f.read().lower()          # never persisted

    def test_cheat_in_preferences_enables_the_level_box(self, make_window):
        from src.gui.widgets.preferences_window import PreferencesWindow
        w = make_window()
        p = PreferencesWindow(w)
        assert not p.cmb_level.isEnabled()
        p.cb_cheat.setChecked(True)                         # before Apply
        assert p.cmb_level.isEnabled()
        p._select_data(p.cmb_level, "Expert")
        p._apply()                                          # cheat applied first
        assert w._experience_level == "Expert"
        p.deleteLater()
