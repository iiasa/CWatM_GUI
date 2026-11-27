"""``AcceleratorAccountClient`` - the CWatM account over IIASA's Accelerator login.

Same interface as the old Supabase ``AccountClient`` (the ``AccountWorker`` calls
``getattr(client, op)(*args)``), so the main window, the dialogs and the offline queues
keep working unchanged; only the backend differs:

- **identity** - restore / login / logout: the Accelerator login (fast, no service call);
- **points and badges** - ``award_run`` / ``get_status`` / ``touch_activity`` call the
  CWatM points service (``accelerator_backend/``, an Accelerator interactive routine)
  with the user's access token. A sleeping service needs 1-2 minutes to wake, so the
  waits are long and an unreachable service is ``offline`` (the offline queue retries);
- everything else (shop, leaderboard, academy, locations) answers ``not_available``
  until its counterpart is built; the UI treats that like any other failed request.

Login is the device flow in ``accelerator_auth``: the user opens the Accelerator
login page in a browser, gets a short code and types it into the GUI.

Synchronous, network I/O - used from the ``AccountWorker`` thread only.
"""

from src.gui.utils import accelerator_auth as auth
from src.gui.utils import accelerator_config as config
from src.gui.utils.account_client import AccountError
from src.gui.utils.gui_log import get_logger

log = get_logger("accelerator_account_client")

_STATUS_TIMEOUT_S = 30
_WAKE_TIMEOUT_S = 150          # a sleeping service takes 1-2 minutes to wake

_NOT_AVAILABLE = ("This part of the CWatM account is not available yet with the "
                  "Accelerator login.")


def _translate(exc):
    """``AcceleratorAuthError`` -> ``AccountError`` (same codes the UI branches on)."""
    code = getattr(exc, "code", "server_error")
    if code not in ("offline", "invalid_code", "not_logged_in", "session_expired"):
        code = "server_error"
    return AccountError(code, str(exc), detail=repr(exc))


class AcceleratorAccountClient:
    def __init__(self, remember=True):
        self._remember = bool(remember)

    # ---- settings ------------------------------------------------------------------
    def set_remember(self, remember):
        """Stay logged in across GUI restarts - or forget the stored token now."""
        self._remember = bool(remember)
        if not self._remember:
            auth.logout()

    # ---- identity ------------------------------------------------------------------
    def _status(self):
        """The logged-in user as the status dict the UI reads (no points yet)."""
        try:
            me = auth.who_am_i()
        except auth.AcceleratorAuthError as exc:
            raise _translate(exc) from exc
        name = (me.get("full_name") or me.get("email") or "").strip() or "Account"
        return {
            "profile": {"username": name, "full_name": me.get("full_name") or "",
                        "uid": me.get("uid")},
            "email": me.get("email") or "",
            "uid": me.get("uid"),
            "roles": me.get("roles") or [],
            "earned_points": 0, "balance": 0,
            "badges": [], "purchases": [], "next_badge": None,
        }

    def restore(self):
        """Log in again from the stored login - ``None`` when none is stored."""
        if not auth.is_logged_in():
            return None
        return self._status()

    def login(self, code):
        """Redeem the code from the Accelerator login page and return the status."""
        try:
            auth.redeem_device_code((code or "").strip())
        except auth.AcceleratorAuthError as exc:
            raise _translate(exc) from exc
        return self._status()

    def logout(self):
        auth.logout()

    def get_status(self):
        return self._with_points(self._status(), _STATUS_TIMEOUT_S)

    def touch_activity(self):
        """A login = the GUI is in use: fetch the points (waits for a sleeping service)."""
        return self._with_points(self._status(), _WAKE_TIMEOUT_S)

    # ---- the points service --------------------------------------------------------
    def _call(self, method, path, body=None, timeout=_STATUS_TIMEOUT_S):
        """One request to the points service -> the JSON answer, or ``AccountError``."""
        base = config.points_service_url()
        if not base:
            raise AccountError("not_available", _NOT_AVAILABLE)
        import requests
        try:
            token = auth.get_access_token()
        except auth.AcceleratorAuthError as exc:
            raise _translate(exc) from exc
        try:
            res = requests.request(method, base + path, json=body, timeout=timeout,
                                   headers={"x-authorization": token})
        except requests.RequestException as exc:           # unreachable / still waking up
            raise AccountError("offline", detail=repr(exc)) from exc
        if res.status_code == 401:
            raise AccountError("session_expired")
        if res.status_code == 429:
            raise AccountError("rate_limited")
        if res.status_code >= 500 and res.status_code != 500:
            raise AccountError("offline", detail=f"HTTP {res.status_code}")
        try:
            data = res.json()
        except ValueError as exc:       # e.g. the "waking up" page instead of an answer
            raise AccountError("offline", detail="not a JSON answer") from exc
        if not res.ok or not isinstance(data, dict):
            raise AccountError("server_error", detail=f"HTTP {res.status_code}")
        return data

    def _with_points(self, status, timeout):
        me = self._call("GET", "/me", timeout=timeout)
        for key in ("earned_points", "balance", "badges", "next_badge"):
            if key in me:
                status[key] = me[key]
        return status

    def award_run(self, _uid, meta):
        """A finished full run: one point per distinct setup (the service decides)."""
        meta = meta or {}
        return self._call("POST", "/claim",
                          {"settings_hash": meta.get("settings_hash"),
                           "timesteps": meta.get("timesteps")}, _WAKE_TIMEOUT_S)

    def close(self):
        """GUI is closing: without "stay logged in" the stored login goes with it."""
        if not self._remember:
            auth.logout()

    # ---- everything else is built later ---------------------------------------------
    def __getattr__(self, op):
        if op.startswith("_"):
            raise AttributeError(op)

        def not_available(*_args, **_kwargs):
            raise AccountError("not_available", _NOT_AVAILABLE)
        return not_available
