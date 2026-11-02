"""The Shop's rules on the REAL main window (shop.md Step 7): every skill level is
free (logged in or not, no Cheat tick), and Preferences ▸ Select animal lists the
free Trout + Bottle plus the bought animals.

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
    def test_logged_out_every_level_is_free(self, make_window):
        w = make_window()
        assert w._experience_level == "Expert"     # the preferred level, nothing owned
        w.cycle_experience_level()
        assert w._experience_level == "Beginner"
        w.cycle_experience_level()
        assert w._experience_level == "Advanced"
        w.cycle_experience_level()
        assert w._experience_level == "Expert"
        assert make_window.messages == []          # no "buy it" box

    def test_logged_in_without_purchases_every_level_is_free(self, make_window):
        w = make_window()
        w._on_account_succeeded("restore", _status())
        assert w._experience_level == "Expert"
        w.set_experience_level("Advanced")
        assert w._experience_level == "Advanced"
        w.set_experience_level("Expert")
        assert w._experience_level == "Expert"
        assert make_window.messages == []

    def test_level_survives_a_logout(self, make_window):
        w = make_window()
        w._on_account_succeeded("restore", _status())
        w.set_experience_level("Advanced")
        w._on_account_succeeded("logout", None)
        assert w._experience_level == "Advanced"


class TestPreferencesAnimals:
    @pytest.fixture(autouse=True)
    def emoji_animals(self, monkeypatch):
        from src.gui.widgets import discharge_sparkline
        monkeypatch.setattr(discharge_sparkline, "USE_IMAGE_ANIMALS", False)

    def _prefs(self, w):
        from src.gui.widgets.preferences_window import PreferencesWindow
        return PreferencesWindow(w)

    def test_none_bought_the_free_ones_logged_out(self, make_window):
        w = make_window()
        p = self._prefs(w)
        offered = [p.cmb_animal.itemData(i) for i in range(p.cmb_animal.count())]
        assert offered == ["Fish", "Sailboat"]              # = trout + bottle, free
        assert p.cmb_animal.isEnabled()
        assert w.discharge_sparkline._animal == "Fish"      # the default, free
        p._select_data(p.cmb_animal, "Sailboat")
        p._apply()                                          # selectable logged out
        assert w.discharge_sparkline._animal == "Sailboat"
        p.deleteLater()

    def test_the_free_and_the_bought_ones(self, make_window):
        w = make_window()
        w._on_account_succeeded("restore", _status("otter", "octopus"))
        p = self._prefs(w)
        offered = [p.cmb_animal.itemData(i) for i in range(p.cmb_animal.count())]
        assert offered == ["Fish", "Otter", "Sailboat", "Octopus (for Carla)"]
        assert w.discharge_sparkline._animal == "Fish"
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
        offered = [p.cmb_animal.itemData(i) for i in range(p.cmb_animal.count())]
        assert offered == ["Fish", "Sailboat"]              # back to the free ones
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
        assert offered == ["Bottle", "Octopus (Carla)", "Trout"]   # Bottle is free
        assert w.discharge_sparkline._animal == "Trout"      # the image default
        p.deleteLater()

    def test_images_logged_out_trout_and_bottle(self, make_window, monkeypatch):
        from src.gui.widgets import discharge_sparkline as ds
        monkeypatch.setattr(ds, "USE_IMAGE_ANIMALS", True)
        w = make_window()
        p = self._prefs(w)
        offered = [p.cmb_animal.itemData(i) for i in range(p.cmb_animal.count())]
        assert offered == ["Bottle", "Trout"]
        assert w.discharge_sparkline._animal == "Trout"
        p.deleteLater()


class TestLevelPreferences:
    def test_no_level_cheat_and_the_level_box_is_always_usable(self, make_window):
        from src.gui.widgets.preferences_window import PreferencesWindow
        w = make_window()
        p = PreferencesWindow(w)
        assert not hasattr(p, "cb_cheat")
        assert p.cmb_level.isEnabled()                      # logged out, nothing bought
        p._select_data(p.cmb_level, "Advanced")
        p._apply()
        assert w._experience_level == "Advanced"
        assert make_window.messages == []
        p.deleteLater()
