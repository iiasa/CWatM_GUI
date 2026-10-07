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
    @pytest.fixture(autouse=True)
    def emoji_animals(self, monkeypatch):
        from src.gui.widgets import discharge_sparkline
        monkeypatch.setattr(discharge_sparkline, "USE_IMAGE_ANIMALS", False)

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

    def test_animal_cheat_lists_all_and_applies(self, make_window):
        w = make_window()
        p = self._prefs(w)
        p.cb_cheat_animals.setChecked(True)                 # before Apply: refilled
        assert p.cmb_animal.isEnabled() and p.cmb_animal.count() == 5
        p._select_data(p.cmb_animal, "Beaver")
        p._apply()                                          # cheat applied first
        assert w.discharge_sparkline._animal == "Beaver"
        p.cb_cheat_animals.setChecked(False)
        assert p.cmb_animal.itemData(0) is None             # back to "buy one"
        p.deleteLater()

    def test_image_animals_from_the_assets_folder(self, make_window, monkeypatch):
        from src.gui.widgets import discharge_sparkline as ds
        monkeypatch.setattr(ds, "USE_IMAGE_ANIMALS", True)
        w = make_window()
        p = self._prefs(w)
        p.cb_cheat_animals.setChecked(True)
        offered = [p.cmb_animal.itemData(i) for i in range(p.cmb_animal.count())]
        assert offered == [n for n, _p in ds.image_animals()] and offered  # assets/ani
        assert not p.cmb_animal.itemIcon(0).isNull()
        p._select_data(p.cmb_animal, offered[0])
        assert p.lbl_animal_preview.pixmap().width() == 64   # the bigger picture
        p._apply()
        assert w.discharge_sparkline._animal == offered[0]
        p.deleteLater()

    def test_images_are_the_standard_and_bought_ones_listed(self, make_window,
                                                            monkeypatch):
        from src.gui.widgets import discharge_sparkline as ds
        monkeypatch.setattr(ds, "USE_IMAGE_ANIMALS", True)   # the standard
        w = make_window()
        w._on_account_succeeded("restore", _status("trout", "octopus"))
        p = self._prefs(w)
        assert not hasattr(p, "cb_anim_images")              # no switch any more
        offered = [p.cmb_animal.itemData(i) for i in range(p.cmb_animal.count())]
        assert offered == ["Octopus (Carla)", "Trout"]
        assert w.discharge_sparkline._animal == "Trout"      # the image default
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
