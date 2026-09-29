"""CWatM account UI (`account_ui.py`, `account_dialogs.py`) against a fake worker.

No network and no supabase: the dialogs and the menu-bar state machine only ever
talk to ``mw.account_worker()``, so a fake worker with the same signals drives them.
Checked: nothing is sent when local validation fails, answers for other operations
are ignored, the register -> code step, profile edits send only what changed, and
the login-state transitions of the menu-bar button.
"""

import pytest

pytestmark = pytest.mark.qt

from PySide6.QtCore import QObject, QSettings, Signal  # noqa: E402
from PySide6.QtWidgets import QStatusBar, QWidget  # noqa: E402

from src.gui.components import account_ui  # noqa: E402
from src.gui.components.account_ui import (AccountMixin,  # noqa: E402
                                           account_button_text,
                                           account_button_tooltip)

STATUS = {"profile": {"username": "Blabla", "full_name": None, "country": "Austria",
                      "institute": "IIASA", "show_on_leaderboard": False},
          "total_points": 1, "email": "b@example.org",
          "badges": [{"code": "breg", "name": "Breg"}],
          "next_badge": {"code": "thames", "name": "Thames", "points_required": 5}}


class FakeWorker(QObject):
    succeeded = Signal(str, object)
    failed = Signal(str, str, str)

    def __init__(self):
        super().__init__()
        self.sent = []

    def submit(self, op, *args, **kwargs):
        self.sent.append((op, args, kwargs))


class FakeMainWindow(QWidget):
    def __init__(self, status=None):
        super().__init__()
        self.worker = FakeWorker()
        self.status_bar = QStatusBar()
        self.remember_set = []
        self._status = status

    def account_worker(self):
        return self.worker

    def account_remember(self):
        return True

    def _set_account_remember(self, value):
        self.remember_set.append(value)

    def account_status(self):
        return self._status


class TestButtonLabels:
    def test_logged_in(self):
        assert account_button_text("logged_in", STATUS) == "Blabla · 1 pt"
        tip = account_button_tooltip("logged_in", STATUS)
        assert "Breg" in tip and "Thames (4 more points)" in tip

    def test_other_states(self):
        assert account_button_text("logged_out", None) == "Log in"
        assert account_button_text("restoring", None) == "Logging in…"
        assert account_button_text("offline", None) == "Account (offline)"

    def test_one_point_missing_is_singular(self):
        st = dict(STATUS, total_points=4)
        assert "(1 more point)" in account_button_tooltip("logged_in", st)


def _dispose(qapp, *widgets):
    """Close the widgets and run their deletion NOW, while every Python reference is
    still known. Leaving a deleteLater() pending past the test - or letting Python
    and Qt each free a parent/child pair in their own order - corrupted the heap
    (0xc0000374) a few tests later, depending on the run order."""
    from PySide6.QtCore import QEvent
    for w in widgets:
        for child in w.findChildren(QWidget):
            if child.isWindow():
                child.close()
        w.close()
        w.deleteLater()
    qapp.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture
def mw(qapp):
    w = FakeMainWindow()
    yield w
    _dispose(qapp, w)


@pytest.fixture
def mw_logged_in(qapp):
    w = FakeMainWindow(status=STATUS)
    yield w
    _dispose(qapp, w)


class TestLoginDialog:
    def _dialog(self, mw):
        from src.gui.widgets.account_dialogs import LoginDialog
        return LoginDialog(mw)

    def test_empty_login_sends_nothing(self, mw):
        d = self._dialog(mw)
        d._do_login()
        assert mw.worker.sent == []
        assert "Please enter" in d.status.text()

    def test_login_then_answer_closes(self, mw):
        d = self._dialog(mw)
        d.show()
        d.ed_identifier.setText(" Blabla ")
        d.ed_password.setText("secret123")
        d._do_login()
        assert mw.worker.sent == [("login", ("Blabla", "secret123"), {})]
        # an answer for another operation (the main window's re-login) is ignored
        mw.worker.succeeded.emit("restore", STATUS)
        assert d.isVisible()
        mw.worker.succeeded.emit("login", STATUS)
        assert not d.isVisible()

    def test_failure_shows_message_and_reenables(self, mw):
        d = self._dialog(mw)
        d.ed_identifier.setText("Blabla")
        d.ed_password.setText("wrong-password")
        d._do_login()
        assert not any(b.isEnabled() for b in d._action_buttons)
        mw.worker.failed.emit("login", "invalid_credentials", "Wrong password.")
        assert d.status.text() == "Wrong password."
        assert all(b.isEnabled() for b in d._action_buttons)

    def test_register_needs_consent_then_asks_for_code(self, mw):
        d = self._dialog(mw)
        d.reg_username.setText("Blabla")
        d.reg_email.setText("b@example.org")
        d.reg_password.setText("secret123")
        d.reg_repeat.setText("secret123")
        d._do_register()
        assert mw.worker.sent == []                       # consent not given
        d.reg_agree.setChecked(True)
        d.reg_locations.setChecked(True)                  # run locations confirmed
        d._do_register()
        op, args, kwargs = mw.worker.sent[-1]
        assert op == "register" and args[2] == "Blabla"
        from src.gui.utils.account_config import PRIVACY_VERSION
        assert kwargs["privacy_version"] == PRIVACY_VERSION     # consent recorded
        mw.worker.succeeded.emit("register", {"status": "confirm_email",
                                              "email": "b@example.org"})
        assert d.reg_stack.currentIndex() == 1
        d.reg_code.setText("221435")
        d._do_confirm()
        assert mw.worker.sent[-1] == ("confirm_signup", ("b@example.org", "221435"), {})

    def test_register_visibility_choices_default_yes(self, mw):
        d = self._dialog(mw)
        assert d.reg_locations.isChecked()
        assert d.reg_leaderboard.isChecked() and d.reg_map.isChecked()
        d.reg_username.setText("Blabla")
        d.reg_email.setText("b@example.org")
        d.reg_password.setText("secret123")
        d.reg_repeat.setText("secret123")
        d.reg_agree.setChecked(True)
        d.reg_map.setChecked(False)                       # the user may untick
        d._do_register()
        kwargs = mw.worker.sent[-1][2]
        assert kwargs["share_locations"] is True
        assert kwargs["show_on_leaderboard"] is True
        assert kwargs["show_location_on_map"] is False

    def test_register_rejects_bad_input_locally(self, mw):
        d = self._dialog(mw)
        d.reg_agree.setChecked(True)
        d.reg_username.setText("ab")
        d._do_register()
        assert mw.worker.sent == []
        assert "3 to 30" in d.status.text()

    def test_unconfirmed_email_login_jumps_to_code_step(self, mw):
        d = self._dialog(mw)
        d.ed_identifier.setText("b@example.org")
        d.ed_password.setText("secret123")
        d._do_login()
        mw.worker.failed.emit("login", "email_not_confirmed", "Please confirm.")
        assert d.tabs.currentIndex() == 1 and d.reg_stack.currentIndex() == 1
        assert d._confirm_email == "b@example.org"


class TestAccountWindow:
    def test_only_changed_fields_are_sent(self, mw_logged_in):
        from src.gui.widgets.account_dialogs import AccountWindow
        mw = mw_logged_in
        w = AccountWindow(mw)
        assert mw.worker.sent == [("get_status", (), {})]   # refresh on open
        mw.worker.succeeded.emit("get_status", STATUS)
        w.ed_full_name.setText("Peter")
        w.cb_leaderboard.setChecked(True)
        w._do_save()
        assert mw.worker.sent[-1] == ("update_profile", (),
                                      {"full_name": "Peter",
                                       "show_on_leaderboard": True})

    def test_nothing_changed_sends_nothing(self, mw_logged_in):
        from src.gui.widgets.account_dialogs import AccountWindow
        mw = mw_logged_in
        w = AccountWindow(mw)
        mw.worker.succeeded.emit("get_status", STATUS)
        w._do_save()
        assert mw.worker.sent == [("get_status", (), {})]


class _Host(AccountMixin, QWidget):
    """The mixin on a bare widget, with the fake worker instead of the real one.

    Its settings are an explicit ini file: QSettings("IIASA", "CWatM_GUI") is always
    the native store (the registry) - setDefaultFormat() does not apply to that
    constructor - so it would read and write the developer's real settings."""

    def __init__(self, settings_path):
        super().__init__()
        self._settings = QSettings(str(settings_path), QSettings.IniFormat)
        self.status_bar = QStatusBar()
        self._create_account_button().setParent(self)
        self.fake = FakeWorker()
        self.notes = []

    def account_worker(self):
        return self.fake

    def append_to_cwatminfo(self, text, is_error=False):
        self.notes.append(text.strip())


@pytest.fixture
def host(qapp, tmp_path, monkeypatch):
    from src.gui.utils import run_ledger
    monkeypatch.setattr(run_ledger, "history_dir", lambda: str(tmp_path))
    h = _Host(tmp_path / "s.ini")
    yield h
    run_ledger.remove_listener(h._on_run_recorded)
    _dispose(qapp, h)


class TestLoginState:
    def test_no_stored_login_means_no_restore(self, host, monkeypatch):
        scheduled = []
        monkeypatch.setattr(account_ui.QTimer, "singleShot",
                            lambda ms, fn: scheduled.append(ms))
        h = host
        h._init_account()
        assert scheduled == []
        assert h._account_button.text() == "Log in"

    def test_stored_login_is_restored_in_the_background(self, host, monkeypatch):
        scheduled = []
        monkeypatch.setattr(account_ui.QTimer, "singleShot",
                            lambda ms, fn: scheduled.append(ms))
        h = host
        h._settings.setValue("account/remembered", True)
        h._init_account()
        assert scheduled == [account_ui._RESTORE_DELAY_MS]
        assert h._account_button.text() == "Logging in…"

    def test_transitions(self, host):
        h = host
        h._init_account()
        h._on_account_succeeded("login", STATUS)
        assert h._account_button.text() == "Blabla · 1 pt"
        assert h._settings.value("account/remembered", type=bool)
        h._on_account_failed("restore", "offline", "no connection")
        assert h._account_button.text() == "Account (offline)"
        assert h._settings.value("account/remembered", type=bool)   # kept
        h._on_account_failed("get_status", "session_expired", "expired")
        assert h._account_button.text() == "Log in"
        assert not h._settings.value("account/remembered", type=bool)

    def test_levels_need_a_login(self, host, monkeypatch):
        monkeypatch.setattr(account_ui.account_config, "is_configured", lambda: True)
        h = host
        assert not h.levels_unlocked()                  # before init, nothing stored
        h._init_account()
        assert not h.levels_unlocked()                  # logged out -> Beginner only
        h._on_account_succeeded("login", STATUS)
        assert h.levels_unlocked()
        h._on_account_failed("restore", "offline", "no connection")
        assert h.levels_unlocked()                      # stored login kept offline
        h._on_account_succeeded("logout", None)
        assert not h.levels_unlocked()

    def test_levels_open_without_an_account_server(self, host, monkeypatch):
        monkeypatch.setattr(account_ui.account_config, "is_configured", lambda: False)
        host._init_account()
        assert host.levels_unlocked()

    def test_forgetting_drops_the_stored_login(self, host):
        h = host
        h._init_account()
        h._on_account_succeeded("login", STATUS)
        h._set_account_remember(False)
        assert h.fake.sent[-1] == ("set_remember", (False,), {})
        assert not h._settings.value("account/remembered", type=bool)


# ---- S5: points for runs ------------------------------------------------------------

def _run(uid="a" * 32, success=True, kind="run", timesteps=365):
    return {"uid": uid, "success": success, "kind": kind, "timesteps": timesteps,
            "duration_s": 42.0, "settings": "C:/secret/a.ini"}


AWARDED = {"status": "awarded", "points_awarded": 1, "total_points": 5,
           "new_badges": [{"code": "thames", "name": "Thames", "points_required": 5}]}


class TestAwardMessages:
    def test_awarded_with_badge(self):
        lines = account_ui.award_messages(AWARDED)
        assert lines[0] == "CWatM account: +1 point for this run (total 5)."
        assert "Thames" in lines[1]

    def test_quiet_for_duplicate(self):
        assert account_ui.award_messages({"status": "duplicate"}) == []

    def test_too_short_explains(self):
        lines = account_ui.award_messages({"status": "too_short", "min_timesteps": 30})
        assert "at least 30 timesteps" in lines[0]


class TestPointsForRuns:
    def _logged_in(self, host):
        host._init_account()
        host._on_account_succeeded("login", STATUS)
        host.fake.sent.clear()
        return host

    def test_a_recorded_run_is_sent_through_the_ledger_hook(self, host):
        from src.gui.utils import run_ledger
        h = self._logged_in(host)
        run_ledger.add_entry(_run())
        op, args, _kw = h.fake.sent[-1]
        assert op == "award_run" and args[0] == "a" * 32
        assert args[1] == {"gui_version": account_ui.GUI_VERSION, "kind": "run",
                           "timesteps": 365, "duration_s": 42.0}   # no path

    @pytest.mark.parametrize("entry", [_run(success=False), _run(kind="stopped")])
    def test_failed_or_stopped_runs_are_not_sent(self, host, entry):
        h = self._logged_in(host)
        h._on_run_recorded(entry)
        assert h.fake.sent == []

    def test_count_runs_off_sends_nothing(self, host):
        h = self._logged_in(host)
        h._set_account_count_runs(False)
        h._on_run_recorded(_run())
        assert h.fake.sent == []

    def test_logged_out_runs_do_not_count(self, host):
        from src.gui.utils import account_runs
        host._init_account()
        host._on_run_recorded(_run())
        assert host.fake.sent == [] and account_runs.load_pending() == []

    def test_awarded_notes_and_refreshes(self, host):
        h = self._logged_in(host)
        h._on_run_recorded(_run())
        h._on_account_succeeded("award_run", AWARDED)
        assert h.notes[0].startswith("CWatM account: +1 point")
        assert any("Thames" in n for n in h.notes)
        assert h.fake.sent[-1] == ("get_status", (), {})

    def test_offline_failure_is_queued_and_sent_at_next_login(self, host):
        from src.gui.utils import account_runs
        h = self._logged_in(host)
        h._on_run_recorded(_run())
        h._on_account_failed("award_run", "offline", "no connection")
        assert [i["uid"] for i in account_runs.pending_for("Blabla")] == ["a" * 32]
        h.fake.sent.clear()
        h._on_account_succeeded("restore", STATUS)          # next session
        assert [(op, args[0]) for op, args, _k in h.fake.sent] == [
            ("award_run", "a" * 32)]
        assert h.fake.sent[0][1][1]["timesteps"] == 365           # meta kept
        h._on_account_succeeded("award_run", {"status": "duplicate"})
        assert account_runs.pending_for("Blabla") == []

    def test_run_during_offline_state_is_kept_for_the_stored_user(self, host):
        from src.gui.utils import account_runs
        host._settings.setValue("account/last_user", "Blabla")
        host._init_account()
        host._account_state = "offline"
        host._on_run_recorded(_run())
        assert host.fake.sent == []
        assert [i["uid"] for i in account_runs.pending_for("Blabla")] == ["a" * 32]

    def test_another_user_does_not_get_queued_runs(self, host):
        from src.gui.utils import account_runs
        account_runs.add_pending("b" * 32, {"kind": "run"}, "someone_else")
        h = self._logged_in(host)
        h._on_account_succeeded("login", STATUS)            # Blabla logs in
        assert all(op != "award_run" for op, _a, _k in h.fake.sent)

    def test_answers_are_matched_in_order(self, host):
        from src.gui.utils import account_runs
        h = self._logged_in(host)
        h._on_run_recorded(_run(uid="1" * 32))
        h._on_run_recorded(_run(uid="2" * 32))
        h._on_account_succeeded("award_run", AWARDED)             # for run 1
        h._on_account_failed("award_run", "offline", "no connection")  # for run 2
        assert [i["uid"] for i in account_runs.pending_for("Blabla")] == ["2" * 32]


def test_missing_library_does_not_forget_the_stored_login(host):
    host._settings.setValue("account/remembered", True)
    host._init_account()
    host._on_account_failed("restore", "not_installed", "not installed")
    assert host._account_button.text() == "Log in"
    assert host._settings.value("account/remembered", type=bool)


def test_same_settings_message():
    lines = account_ui.award_messages({"status": "same_settings"})
    assert "already earned a point" in lines[0]


class TestLeaderboard:
    LADDER = [{"code": "breg", "name": "Breg", "points_required": 1},
              {"code": "danube", "name": "Danube", "points_required": 200}]
    ROWS = [{"rank": 1, "username": "Anna", "country": "AT", "total_points": 12,
             "top_badge": "Danube"},
            {"rank": 2, "username": "Blabla", "country": "Austria", "total_points": 2,
             "top_badge": "Breg"},
            {"rank": 3, "username": "newbie", "country": None, "total_points": 0,
             "top_badge": None}]

    def test_filled_and_own_row_highlighted(self, mw_logged_in):
        from src.gui.widgets.account_dialogs import LeaderboardWindow
        w = LeaderboardWindow(mw_logged_in)
        # the badge ladder first (name -> code for the images), then the list
        assert mw_logged_in.worker.sent == [("get_badges", (), {})]
        mw_logged_in.worker.succeeded.emit("get_badges", self.LADDER)
        assert mw_logged_in.worker.sent[-1] == ("get_leaderboard", (100,), {})
        mw_logged_in.worker.succeeded.emit("get_leaderboard", self.ROWS)
        t = w.table
        assert t.rowCount() == 3
        assert [t.item(1, c).text() for c in range(5)] == \
            ["2", "Blabla", "Austria", "Breg", "2"]
        assert not t.item(1, 3).icon().isNull()            # the medal image
        assert t.item(0, 3).text() == "🏅 Danube"          # no image yet -> emoji
        assert t.item(1, 1).font().bold() and not t.item(0, 1).font().bold()
        assert t.item(2, 3).text() == ""                   # no badge yet
        assert "number 2" in w.lbl_me.text()

    def test_not_listed_says_how_to_take_part(self, mw_logged_in):
        from src.gui.widgets.account_dialogs import LeaderboardWindow
        w = LeaderboardWindow(mw_logged_in)
        mw_logged_in.worker.succeeded.emit("get_badges", self.LADDER)
        mw_logged_in.worker.succeeded.emit("get_leaderboard", self.ROWS[:1])
        assert "not listed" in w.lbl_me.text()

    def test_menu_item_only_while_logged_in(self, host):
        from PySide6.QtGui import QAction
        host._leaderboard_action = QAction("Leaderboard", host)
        host._init_account()
        assert not host._leaderboard_action.isVisible()
        host._on_account_succeeded("login", STATUS)
        assert host._leaderboard_action.isVisible()
        host._on_account_succeeded("logout", {"status": "logged_out"})
        assert not host._leaderboard_action.isVisible()


class TestBadgeImages:
    @pytest.mark.parametrize("code", ["breg", "thames", "morava", "inn"])
    def test_the_first_four_have_images(self, qapp, code):
        from src.gui.utils.badge_images import badge_pixmap
        pix = badge_pixmap(code, 88)
        assert pix is not None and pix.width() == 88 and pix.height() == 88

    def test_round_corners_are_transparent(self, qapp):
        from src.gui.utils.badge_images import badge_pixmap
        img = badge_pixmap("inn", 88).toImage()        # inn: dark square background
        assert img.pixelColor(1, 1).alpha() == 0
        assert img.pixelColor(44, 44).alpha() == 255

    def test_the_medal_is_found_inside_the_square(self, qapp):
        from PySide6.QtGui import QImage
        from src.gui.utils.badge_images import _medal_rect, badge_image_path
        r = _medal_rect(QImage(badge_image_path("breg")))  # medal ~29..320 of 350
        assert 20 <= r.left() <= 35 and 285 <= r.width() <= 300

    def test_no_image_no_pixmap(self, qapp):
        from src.gui.utils.badge_images import badge_pixmap
        assert badge_pixmap("amazonas", 88) is None

    def test_account_window_shows_medals(self, mw_logged_in):
        from src.gui.widgets.account_dialogs import AccountWindow
        w = AccountWindow(mw_logged_in)
        mw_logged_in.worker.succeeded.emit("get_status", STATUS)
        # earned Breg + the next one (Thames) faded with its goal
        assert w.badge_grid.count() == 2
        assert w.lbl_badges.text() == "Badges"


# ---- anonymous run locations ----------------------------------------------------------

SHARING = dict(STATUS, profile=dict(STATUS["profile"], share_locations=True))


class TestRunLocations:
    def _logged_in(self, host, status):
        host._init_account()
        host._on_account_succeeded("restore", status)       # silent re-login
        host.fake.sent.clear()
        return host

    def test_sent_only_after_the_point_is_awarded(self, host):
        h = self._logged_in(host, SHARING)
        h._on_run_recorded(dict(_run(), gauge=[17.25, 48.6]))
        # first only the points request - without the gauge
        assert [op for op, _a, _k in h.fake.sent] == ["award_run"]
        assert "gauge" not in h.fake.sent[0][1][1]
        h._on_account_succeeded("award_run", AWARDED)
        ops = [op for op, _a, _k in h.fake.sent]
        assert ("record_location", (17.25, 48.6), {}) in h.fake.sent
        assert ops.index("record_location") > ops.index("award_run")  # separate, later

    @pytest.mark.parametrize("answer", [
        {"status": "same_settings"}, {"status": "too_short", "min_timesteps": 30},
        {"status": "daily_limit", "daily_run_cap": 20}, {"status": "duplicate"}])
    def test_not_sent_when_no_point_is_earned(self, host, answer):
        h = self._logged_in(host, SHARING)
        h._on_run_recorded(dict(_run(), gauge=[17.25, 48.6]))
        h._on_account_succeeded("award_run", answer)
        assert all(op != "record_location" for op, _a, _k in h.fake.sent)

    def test_not_sent_without_consent(self, host):
        h = self._logged_in(host, STATUS)                   # share_locations missing
        h._on_run_recorded(dict(_run(), gauge=[17.25, 48.6]))
        h._on_account_succeeded("award_run", AWARDED)
        assert all(op != "record_location" for op, _a, _k in h.fake.sent)

    def test_not_sent_for_a_failed_run_or_without_gauge(self, host):
        h = self._logged_in(host, SHARING)
        h._on_run_recorded(dict(_run(success=False), gauge=[17.25, 48.6]))
        h._on_run_recorded(_run())                          # no gauge in the entry
        h._on_account_succeeded("award_run", AWARDED)
        assert all(op != "record_location" for op, _a, _k in h.fake.sent)

    def test_not_sent_when_points_are_off(self, host):
        # no points request -> no point earned -> no location
        h = self._logged_in(host, SHARING)
        h._set_account_count_runs(False)
        h._on_run_recorded(dict(_run(), gauge=[17.25, 48.6]))
        assert h.fake.sent == []

    def test_offline_run_keeps_its_gauge_until_awarded(self, host):
        from src.gui.utils import account_runs
        h = self._logged_in(host, SHARING)
        h._on_run_recorded(dict(_run(), gauge=[17.25, 48.6]))
        h._on_account_failed("award_run", "offline", "no connection")
        assert account_runs.pending_for("Blabla")[0]["gauge"] == [17.25, 48.6]
        h.fake.sent.clear()
        h._on_account_succeeded("restore", SHARING)         # next session
        assert "gauge" not in h.fake.sent[0][1][1]           # not in the points request
        h._on_account_succeeded("award_run", AWARDED)
        assert ("record_location", (17.25, 48.6), {}) in h.fake.sent

    def test_asked_once_at_login_yes_turns_it_on(self, host, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        asked = []
        monkeypatch.setattr(account_ui.QMessageBox, "question",
                            lambda *a, **k: asked.append(1) or QMessageBox.Yes)
        h = self._logged_in(host, STATUS)
        h._ask_location_consent()
        assert asked == [1]
        assert h.fake.sent[-1] == ("update_profile", (), {"share_locations": True})
        h._ask_location_consent()                           # never twice
        assert asked == [1]

    def test_no_means_nothing_is_sent(self, host, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        monkeypatch.setattr(account_ui.QMessageBox, "question",
                            lambda *a, **k: QMessageBox.No)
        h = self._logged_in(host, STATUS)
        h._ask_location_consent()
        assert h.fake.sent == []

    def test_only_interactive_logins_ask(self, host, monkeypatch):
        scheduled = []
        monkeypatch.setattr(account_ui.QTimer, "singleShot",
                            lambda ms, fn: scheduled.append(fn.__name__))
        host._init_account()
        host._on_account_succeeded("restore", STATUS)
        assert "_ask_location_consent" not in scheduled
        host._on_account_succeeded("login", STATUS)
        assert "_ask_location_consent" in scheduled

    def test_register_needs_the_location_tick(self, mw):
        from src.gui.widgets.account_dialogs import LoginDialog
        d = LoginDialog(mw)
        d.reg_username.setText("Blabla")
        d.reg_email.setText("b@example.org")
        d.reg_password.setText("secret123")
        d.reg_repeat.setText("secret123")
        d.reg_agree.setChecked(True)
        assert d.reg_locations.isChecked()                  # default: yes
        d.reg_locations.setChecked(False)                   # the user unticks it
        d._do_register()
        assert mw.worker.sent == []
        assert "location" in d.status.text()
        d.reg_locations.setChecked(True)
        d._do_register()
        assert mw.worker.sent[-1][2]["share_locations"] is True

    def test_account_window_can_switch_it_off(self, qapp):
        from src.gui.widgets.account_dialogs import AccountWindow
        m = FakeMainWindow(status=SHARING)
        w = AccountWindow(m)
        m.worker.succeeded.emit("get_status", SHARING)
        assert w.cb_locations.isChecked()
        w.cb_locations.setChecked(False)
        w._do_save()
        assert m.worker.sent[-1] == ("update_profile", (), {"share_locations": False})
        _dispose(qapp, m)


class TestLocationDefaults:
    def test_question_preselects_yes(self, host, monkeypatch):
        from PySide6.QtWidgets import QMessageBox
        calls = []
        monkeypatch.setattr(account_ui.QMessageBox, "question",
                            lambda *a, **k: calls.append(a) or QMessageBox.Yes)
        host._init_account()
        host._on_account_succeeded("restore", STATUS)
        host._ask_location_consent()
        assert calls[0][-1] == QMessageBox.Yes              # the default button

    def test_preferences_value(self, host):
        host._init_account()
        assert host.account_share_locations() is True       # logged out: default yes
        host._on_account_succeeded("restore", STATUS)       # stored: no
        assert host.account_share_locations() is False
        host._on_account_succeeded("restore", SHARING)
        assert host.account_share_locations() is True

    def test_preferences_change_is_saved_in_the_account(self, host):
        host._init_account()
        host._set_share_locations(False)                    # logged out: nothing
        assert host.fake.sent == []
        host._on_account_succeeded("restore", SHARING)
        host.fake.sent.clear()
        host._set_share_locations(True)                     # unchanged: nothing
        assert host.fake.sent == []
        host._set_share_locations(False)
        assert host.fake.sent == [("update_profile", (), {"share_locations": False})]


class TestOwnLocationUI:
    def test_register_sends_the_location(self, mw):
        from src.gui.widgets.account_dialogs import LoginDialog
        d = LoginDialog(mw)
        for w, t in ((d.reg_username, "Blabla"), (d.reg_email, "b@example.org"),
                     (d.reg_password, "secret123"), (d.reg_repeat, "secret123"),
                     (d.reg_lat, "48.067"), (d.reg_lon, "16.357")):
            w.setText(t)
        d.reg_agree.setChecked(True)
        d._do_register()
        kwargs = mw.worker.sent[-1][2]
        assert (kwargs["location_lat"], kwargs["location_lon"]) == (48.067, 16.357)

    def test_register_rejects_half_a_location(self, mw):
        from src.gui.widgets.account_dialogs import LoginDialog
        d = LoginDialog(mw)
        for w, t in ((d.reg_username, "Blabla"), (d.reg_email, "b@example.org"),
                     (d.reg_password, "secret123"), (d.reg_repeat, "secret123"),
                     (d.reg_lat, "48.067")):
            w.setText(t)
        d.reg_agree.setChecked(True)
        d._do_register()
        assert mw.worker.sent == [] and "longitude" in d.status.text()

    def test_account_window_sends_the_pair(self, qapp):
        from src.gui.widgets.account_dialogs import AccountWindow
        m = FakeMainWindow(status=STATUS)
        w = AccountWindow(m)
        m.worker.succeeded.emit("get_status", STATUS)
        w.ed_lat.setText("48.067")
        w.ed_lon.setText("16.357")
        w._do_save()
        assert m.worker.sent[-1] == ("update_profile", (),
                                     {"location_lat": 48.067, "location_lon": 16.357})
        # stored value shown unchanged -> nothing to save
        loc = dict(STATUS, profile=dict(STATUS["profile"], location_lat=48.067,
                                        location_lon=16.357))
        m.worker.succeeded.emit("update_profile", loc)       # the answer to the save
        m.worker.sent.clear()
        w._do_save()
        assert m.worker.sent == []
        # emptied -> removed (both None)
        w.ed_lat.setText("")
        w.ed_lon.setText("")
        w._do_save()
        assert m.worker.sent[-1] == ("update_profile", (),
                                     {"location_lat": None, "location_lon": None})
        _dispose(qapp, m)


class TestBadgeEnlarge:
    EARNED = dict(STATUS, badges=[{"code": "breg", "name": "Breg",
                                   "awarded_at": "2026-09-28T11:03:12.5+00:00"}])

    def _window(self, qapp):
        from src.gui.widgets.account_dialogs import AccountWindow
        m = FakeMainWindow(status=self.EARNED)
        w = AccountWindow(m)
        m.worker.succeeded.emit("get_status", self.EARNED)
        return m, w

    def test_earned_badge_click_opens_it_large(self, qapp):
        from src.gui.widgets.account_dialogs import BadgeViewer, _ClickableLabel
        m, w = self._window(qapp)
        earned = w.badge_grid.itemAt(0).widget().findChild(_ClickableLabel)
        assert earned is not None and "click to enlarge" in earned.toolTip()
        earned.clicked.emit()
        v = w._badge_viewer
        assert isinstance(v, BadgeViewer) and v.windowTitle() == "Breg"
        assert v.medal.width() == BadgeViewer.BIG
        assert not v.medal.pixmap().isNull()
        texts = [lbl.text() for lbl in v.findChildren(type(v.medal))]
        assert "Earned on 28 September 2026" in texts
        _dispose(qapp, m)

    def test_next_badge_is_not_clickable(self, qapp):
        from src.gui.widgets.account_dialogs import _ClickableLabel
        m, w = self._window(qapp)
        nxt = w.badge_grid.itemAt(1).widget()              # the faded next badge
        assert nxt.findChild(_ClickableLabel) is None
        _dispose(qapp, m)

    def test_date_format(self):
        from src.gui.widgets.account_dialogs import _format_date
        assert _format_date("2026-09-28T11:03:12.5+00:00") == "28 September 2026"
        assert _format_date(None) == ""
