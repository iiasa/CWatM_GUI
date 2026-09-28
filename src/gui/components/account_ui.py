"""The CWatM account in the main window - the menu-bar button and the login state.

``AccountMixin`` (mixed into ``CWatMMainWindow``) owns:

- the **account button** in the menu bar's right corner, left of the ⋮ button:
  "Log in" when logged out, "<username> · <points> pt" when logged in; a click opens
  the login dialog or the account window (``src/gui/widgets/account_dialogs.py``);
- the one ``AccountWorker`` (created lazily - the first request imports supabase on
  the worker thread, never at startup) and the login state every window reads;
- the automatic re-login at startup: only when the last session stored a login
  (``account/remembered``), started ``_RESTORE_DELAY_MS`` after construction so it
  never competes with the window coming up.

States: ``logged_out`` · ``restoring`` (re-login in flight) · ``logged_in`` ·
``offline`` (a login is stored but the server cannot be reached - kept, retried on
the next click). The account is optional: nothing else in the GUI depends on it.

QSettings keys: ``account/remember`` (Preferences: stay logged in, default on),
``account/remembered`` (a refresh token is stored in the keyring - avoids loading
supabase at startup for users who never logged in), ``account/count_runs``
(Preferences: count my runs, used by the run hook).
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QToolButton, QMessageBox

from src.gui import __version__ as GUI_VERSION
from src.gui.utils import account_config, account_runs, run_ledger
from src.gui.utils.gui_log import get_logger

log = get_logger("account_ui")

_RESTORE_DELAY_MS = 2500

# Worker operations whose result is the full status dict of the logged-in user.
_STATUS_OPS = {"restore", "login", "confirm_signup", "reset_password", "get_status",
               "update_profile", "register"}
# ...of those, the ones that start a session: the offline queue is sent after them.
_LOGIN_OPS = {"restore", "login", "confirm_signup", "reset_password", "register"}
# Interactive logins: the one-time run-location question is asked after these (not
# after the silent re-login at startup - a question out of nowhere).
_ASK_LOCATION_OPS = {"login", "confirm_signup", "reset_password"}
# award_run answers that settle a run for good (anything else = try again later).
_AWARD_FINAL = {"awarded", "duplicate", "too_short", "daily_limit", "invalid_run_uid",
                "same_settings"}


def award_messages(result):
    """Output-box lines for an award_run answer (pure - tested). Empty = say nothing."""
    status = (result or {}).get("status")
    if status == "awarded":
        pts = result.get("points_awarded", 1)
        lines = [f"CWatM account: +{pts} point{'s' if pts != 1 else ''} for this run "
                 f"(total {result.get('total_points', '?')})."]
        for badge in result.get("new_badges") or []:
            lines.append(f"CWatM account: 🏅 new badge - {badge.get('name')}!")
        return lines
    if status == "too_short":
        return [f"CWatM account: this run is too short to earn a point (at least "
                f"{result.get('min_timesteps', '?')} timesteps)."]
    if status == "same_settings":
        return ["CWatM account: these settings already earned a point - change the "
                "model setup (not only Title, PathOut or the outputs) to earn another."]
    if status == "daily_limit":
        return [f"CWatM account: daily limit reached ({result.get('daily_run_cap', '?')}"
                " counted runs in 24 h) - this run earns no point."]
    return []


def account_button_text(state, status):
    """Label of the menu-bar account button (pure - tested)."""
    if state == "logged_in" and status:
        name = (status.get("profile") or {}).get("username") or "Account"
        return f"{name} · {status.get('total_points', 0)} pt"
    if state == "restoring":
        return "Logging in…"
    if state == "offline":
        return "Account (offline)"
    return "Log in"


def account_button_tooltip(state, status):
    """Tooltip of the account button: badges and the next goal (pure - tested)."""
    if state == "logged_in" and status:
        badges = [b.get("name", "") for b in status.get("badges") or []]
        lines = [f"Logged in as {(status.get('profile') or {}).get('username', '')}",
                 f"Points: {status.get('total_points', 0)}"]
        lines.append("Badges: " + (", ".join(badges) if badges else "none yet"))
        nxt = status.get("next_badge")
        if nxt:
            missing = max(0, nxt.get("points_required", 0) - status.get("total_points", 0))
            lines.append(f"Next badge: {nxt.get('name')} "
                         f"({missing} more point{'s' if missing != 1 else ''})")
        lines.append("Click to open your account")
        return "\n".join(lines)
    if state == "offline":
        return ("Your CWatM account could not be reached (no connection).\n"
                "Click to try again.")
    if state == "restoring":
        return "Logging in to your CWatM account…"
    return ("Log in to your CWatM account (optional) - full CWatM runs earn points "
            "and river badges")


class AccountMixin:
    """Menu-bar account button + login state for CWatMMainWindow."""

    # ---- construction ------------------------------------------------------------
    def _create_account_button(self):
        """The account button for the menu bar's corner (menu_builder places it)."""
        btn = QToolButton()
        btn.setObjectName("accountButton")
        btn.setAutoRaise(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self.open_account())
        self._account_button = btn
        return btn

    def _init_account(self):
        """Called once at the end of __init__: set the initial state and, when the
        last session stored a login, schedule the background re-login."""
        self._account_state = "logged_out"
        self._account_status = None
        self._account_worker_obj = None
        # award_run requests in flight, in submit order: (uid, meta, user). The worker
        # answers strictly in order, and only this mixin submits award_run, so the
        # oldest entry is always the one an answer belongs to.
        self._award_fifo = []
        self._update_account_button()
        if not account_config.is_configured():
            self._account_button.setVisible(False)
            wm = getattr(self, "_world_map_action", None)
            if wm is not None:
                wm.setVisible(False)        # no server - nothing to show
            return
        # Every recorded run (main / Windowed / Batch) reaches _on_run_recorded.
        run_ledger.add_listener(self._on_run_recorded)
        if self.account_remember() and self._settings.value(
                "account/remembered", False, type=bool):
            self._account_state = "restoring"
            self._update_account_button()
            QTimer.singleShot(_RESTORE_DELAY_MS, self._account_restore)

    # ---- worker ------------------------------------------------------------------
    def account_worker(self):
        """The one AccountWorker (started on first use)."""
        if self._account_worker_obj is None:
            from src.gui.utils.account_worker import AccountWorker
            worker = AccountWorker(remember=self.account_remember(), parent=self)
            worker.succeeded.connect(self._on_account_succeeded)
            worker.failed.connect(self._on_account_failed)
            worker.start()
            self._account_worker_obj = worker
        return self._account_worker_obj

    def _stop_account_worker(self):
        run_ledger.remove_listener(self._on_run_recorded)
        worker = getattr(self, "_account_worker_obj", None)
        if worker is None:
            return
        try:
            worker.stop()
            if not worker.wait(3000):
                # Still inside a request (the first one imports supabase, which can
                # take long from a network share). The app is exiting and the thread
                # is a child of this window: destroyed while running, Qt aborts the
                # process - so end it here. Nothing it holds needs a clean close.
                log.info("account worker still busy at exit - terminating it")
                worker.terminate()
                worker.wait(1000)
        except RuntimeError:
            log.debug("account worker already gone", exc_info=True)

    def _account_restore(self):
        self.account_worker().submit("restore")

    # ---- state -------------------------------------------------------------------
    def account_status(self):
        """The logged-in user's status dict, or None."""
        return self._account_status if self._account_state == "logged_in" else None

    def account_remember(self):
        return self._settings.value("account/remember", True, type=bool)

    def account_count_runs(self):
        return self._settings.value("account/count_runs", True, type=bool)

    def _set_account_remember(self, value):
        """Preferences ▸ Account ▸ Stay logged in (and the login dialog's tick)."""
        value = bool(value)
        self._settings.setValue("account/remember", value)
        if value:
            # A worker not yet created picks the setting up when it is created.
            if self._account_worker_obj is not None:
                self.account_worker().submit("set_remember", True)
                if self._account_state == "logged_in":
                    self._settings.setValue("account/remembered", True)
        else:
            # Forgetting also drops a token stored by an earlier session.
            self._settings.setValue("account/remembered", False)
            self.account_worker().submit("set_remember", False)

    def _set_account_count_runs(self, value):
        self._settings.setValue("account/count_runs", bool(value))

    def _set_account_status(self, status):
        self._account_status = status
        self._account_state = "logged_in"
        if self.account_remember():
            self._settings.setValue("account/remembered", True)
        # Who the stored login belongs to - the offline queue is tagged with it while
        # the server cannot be reached (and nobody is logged in this session yet).
        name = (status.get("profile") or {}).get("username")
        if name:
            self._settings.setValue("account/last_user", name)
        self._update_account_button()

    def _account_username(self):
        return ((self._account_status or {}).get("profile") or {}).get("username")

    # ---- points for runs (S5) ------------------------------------------------------
    def _on_run_recorded(self, entry):
        """run_ledger listener: a run was recorded in the Journal of Runs."""
        if not account_runs.qualifies(entry):
            return
        if not self.account_count_runs():
            return
        meta = account_runs.run_meta(entry, GUI_VERSION)
        # The gauge stays LOCAL with the request: it is reported (anonymously, on
        # its own) only once the server has answered this run with "awarded" - so
        # the run-location map holds only runs that earned a badge point.
        gauge = account_runs.location_of(entry)
        state = self._account_state
        if state == "logged_in":
            self._submit_award(entry["uid"], meta, self._account_username(), gauge)
        elif state in ("offline", "restoring"):
            # A login is stored but not (yet) reachable: keep the run for that user.
            user = self._settings.value("account/last_user", "")
            if user:
                account_runs.add_pending(entry["uid"], meta, user, gauge)
                log.info("run kept for the CWatM account (offline)")
        # logged out: runs do not count

    def _shares_locations(self):
        profile = (self.account_status() or {}).get("profile") or {}
        return bool(profile.get("share_locations"))

    def account_share_locations(self):
        """For Preferences ▸ Account: the stored choice when logged in, else the
        default (yes)."""
        if self.account_status() is None:
            return True
        return self._shares_locations()

    def _set_share_locations(self, value):
        """Preferences ▸ Account ▸ Record the location of my runs - saved on the
        server (the profile), so it needs a login."""
        if self._account_state == "logged_in" and \
                bool(value) != self._shares_locations():
            self.account_worker().submit("update_profile", share_locations=bool(value))

    def _report_location(self, gauge):
        """An AWARDED run's first gauge -> the anonymous run-location count (consent
        only). Sent as its own request, never inside award_run: the server stores it
        without any user, and the two must not be joinable."""
        if self._account_state != "logged_in" or not self._shares_locations():
            return
        loc = account_runs.location_of({"gauge": gauge}) if gauge else None
        if loc is not None:
            self.account_worker().submit("record_location", loc[0], loc[1])

    def _ask_location_consent(self):
        """Once per user and computer, at an interactive login: may the first gauge
        of each run that earns a point be recorded (anonymously)? Accounts registered with
        the tick already agreed; the answer can be changed in the account window."""
        status = self.account_status()
        if not status or self._shares_locations():
            return
        user = account_runs.user_key(self._account_username())
        key = f"account/location_asked/{user}"
        if not user or self._settings.value(key, False, type=bool):
            return
        self._settings.setValue(key, True)
        answer = QMessageBox.question(
            self, "CWatM run locations",
            "May CWatM record where it is run?\n\n"
            "For every run that earns a badge point, the location of the FIRST gauge (rounded to "
            "about 100 m) is counted - anonymously: it is stored without your name "
            "or account, only as 'a run at this place in this month'. This helps "
            "IIASA see where CWatM is used.\n\n"
            "You can change this at any time in your account window. Details: "
            "Help ▸ CWatM account privacy.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)     # default: yes
        if answer == QMessageBox.Yes:
            self.account_worker().submit("update_profile", share_locations=True)

    def _submit_award(self, uid, meta, user, gauge=None):
        # the gauge is NOT sent - it waits here for the "awarded" answer
        self._award_fifo.append((uid, meta, user, gauge))
        self.account_worker().submit("award_run", uid, meta)

    def _send_pending_awards(self):
        """After a login: send the runs this user finished while offline."""
        user = self._account_username()
        queued = {item[0] for item in self._award_fifo}
        for item in account_runs.pending_for(user):
            if item["uid"] not in queued:
                self._submit_award(item["uid"], item.get("meta") or {}, user,
                                   item.get("gauge"))

    def _on_award_answer(self, result, code=None):
        """An award_run answer (result) or failure (code) for the oldest request."""
        if not self._award_fifo:
            return
        uid, meta, user, gauge = self._award_fifo.pop(0)
        if code is not None:                       # failed - keep it for later
            if code in ("offline", "server_error", "session_expired",
                        "not_logged_in", "rate_limited"):
                account_runs.add_pending(uid, meta, user, gauge)
            return
        status = (result or {}).get("status")
        if status in _AWARD_FINAL:
            account_runs.remove_pending(uid)
            # The server answers again: send what an earlier outage left queued
            # (requests already in flight are skipped, so nothing goes twice).
            if self._account_state == "logged_in":
                self._send_pending_awards()
        else:                                      # e.g. email_not_confirmed
            account_runs.add_pending(uid, meta, user, gauge)
        for line in award_messages(result):
            self._account_note(line)
        if status == "awarded":
            # only a run that earned a point goes on the run-location map
            self._report_location(gauge)
            if self._account_state == "logged_in":
                # points + badges changed: refresh the button (next badge included)
                self.account_worker().submit("get_status")

    def _account_note(self, text):
        try:
            self.append_to_cwatminfo(text + "\n")
        except Exception:
            log.debug("output box note failed", exc_info=True)
        try:
            self.status_bar.showMessage(text, 8000)
        except Exception:
            log.debug("status bar message failed", exc_info=True)

    def _clear_account(self, remembered=False):
        self._account_status = None
        self._account_state = "logged_out"
        self._settings.setValue("account/remembered", bool(remembered))
        self._update_account_button()

    def _update_account_button(self):
        # Info ▸ Leaderboard exists only for a logged-in user
        action = getattr(self, "_leaderboard_action", None)
        if action is not None:
            try:
                action.setVisible(self._account_state == "logged_in")
            except RuntimeError:
                log.debug("leaderboard action already gone", exc_info=True)
        btn = getattr(self, "_account_button", None)
        if btn is None:
            return
        try:
            btn.setText(account_button_text(self._account_state, self._account_status))
            btn.setToolTip(account_button_tooltip(self._account_state,
                                                  self._account_status))
            # QMenuBar sizes its corner widget only when it is set or shown/hidden
            # (its event filter reacts to Show/HideToParent, not to a new size
            # hint) - without this the label stays as wide as the first text and
            # "Blabla · 1 pt" is elided to "Bla… pt".
            corner = getattr(self, "_menu_corner", None)
            if corner is not None and corner.isVisible():
                corner.hide()
                corner.show()
        except RuntimeError:
            log.debug("account button already gone", exc_info=True)

    # ---- worker answers (GUI thread, queued) ---------------------------------------
    def _on_account_succeeded(self, op, result):
        if op == "award_run":
            self._on_award_answer(result)
        elif op == "record_location":
            log.debug("run location: %s", (result or {}).get("status"))
        elif op in _STATUS_OPS and isinstance(result, dict) and "profile" in result:
            self._set_account_status(result)
            if op in _LOGIN_OPS:
                self._send_pending_awards()
            if op in _ASK_LOCATION_OPS:
                # after the login dialog has closed
                QTimer.singleShot(400, self._ask_location_consent)
        elif op == "restore" and result is None:
            self._clear_account()               # nothing stored after all
        elif op in ("logout", "delete_account"):
            self._clear_account()
            try:
                self.status_bar.showMessage(
                    "Logged out" if op == "logout" else "Account deleted", 5000)
            except Exception:
                log.debug("status bar message failed", exc_info=True)

    def _on_account_failed(self, op, code, message):
        if op == "record_location":
            log.info("run location not recorded: %s", code)   # best-effort, no retry
            return
        if op == "award_run":
            self._on_award_answer(None, code)
            if code in ("session_expired", "not_logged_in"):
                self._clear_account()
            return
        if op == "restore":
            if code == "offline":
                self._account_state = "offline"       # keep the stored login
                self._update_account_button()
            elif code == "not_installed":
                # This Python lacks the libraries - the stored login is still fine
                # (e.g. the venv's GUI can use it), so do not forget it.
                self._account_state = "logged_out"
                self._update_account_button()
            else:
                self._clear_account()
            log.info("automatic re-login failed: %s", code)
        elif code in ("session_expired", "not_logged_in"):
            self._clear_account()

    # ---- UI entry points -----------------------------------------------------------
    def open_world_map(self):
        """Info ▸ World Map - where users applied CWatM (public, no login needed)."""
        if not account_config.is_configured():
            return
        try:
            from src.gui.widgets.world_map_window import open_world_map
            open_world_map(self)
        except Exception as e:
            log.warning("could not open the world map", exc_info=True)
            QMessageBox.warning(self, "World Map",
                                f"The world map could not be opened:\n{e}")

    def open_leaderboard(self):
        """Info ▸ Leaderboard (visible only while logged in)."""
        if self._account_state != "logged_in":
            return
        try:
            from src.gui.widgets import account_dialogs
            account_dialogs.open_leaderboard(self)
        except Exception:
            log.warning("could not open the leaderboard", exc_info=True)

    def open_account(self):
        """The account button: log in, retry an offline re-login, or show the
        account window."""
        if not account_config.is_configured():
            QMessageBox.information(self, "CWatM account",
                                    "The CWatM account is not available in this "
                                    "version.")
            return
        if self._account_state == "offline":
            self._account_state = "restoring"
            self._update_account_button()
            self._account_restore()
            return
        if self._account_state == "restoring":
            return                                   # answer is on its way
        try:
            from src.gui.widgets import account_dialogs
            if self._account_state == "logged_in":
                account_dialogs.open_account_window(self)
            else:
                account_dialogs.open_login_dialog(self)
        except Exception:
            log.warning("could not open the account window", exc_info=True)
