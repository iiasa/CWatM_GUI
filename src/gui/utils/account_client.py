"""``AccountClient`` - the CWatM account (login, profile, points) over Supabase.

The **only** module that imports ``supabase`` (like ``notebooklm_client`` for
NotebookLM). It is synchronous and does network I/O, so it is used from the
``AccountWorker`` thread only - never from the GUI thread - and imported lazily by
that worker, keeping supabase/pydantic off the startup path.

Session handling: the supabase client keeps the session in memory with
``auto_refresh_token=False`` (no background timer threads); ``_session()`` calls
``auth.get_session()`` before every authenticated request, which refreshes an
expired access token on this same thread. Every new/rotated session arrives through
``_on_auth_event`` and its refresh token is written to the OS keyring
(``account_store``) when "stay logged in" is on.

Every failure leaves this module as an ``AccountError(code, message)`` - ``code`` is a
stable identifier the UI can branch on, ``message`` a sentence for the user,
``detail`` the technical text (logged, not shown).

The server side (tables, rpc functions, Edge Functions) is in ``supabase/`` - see
``supabase/README.md`` for the API these methods call.
"""

from src.gui.utils import account_config, account_store, account_validation as V
from src.gui.utils.gui_log import get_logger

log = get_logger("account_client")

MESSAGES = {
    "not_configured": "The CWatM account server is not configured in this version.",
    "offline": "No connection to the CWatM account server. "
               "Check your internet connection and try again.",
    "invalid_input": "Please check your input.",
    "invalid_credentials": "Wrong username/email or password.",
    "email_not_confirmed": "Please confirm your email address first - "
                           "enter the code from the confirmation email.",
    "too_many_attempts": "Too many failed logins. Please wait a few minutes "
                         "and try again.",
    "username_taken": "This username is already taken.",
    "already_registered": "An account with this email address already exists. "
                          "Log in, or reset the password.",
    "weak_password": "The password is too weak - please choose a stronger one.",
    "same_password": "The new password must be different from the old one.",
    "invalid_email": "The email address is not valid.",
    "invalid_code": "The code is wrong or has expired. Request a new one.",
    "rate_limited": "Too many requests. Please wait a moment and try again.",
    "not_logged_in": "You are not logged in.",
    "session_expired": "Your login has expired. Please log in again.",
    "invalid_password": "The password is wrong.",
    "server_error": "The CWatM account server reported an error. "
                    "Please try again later.",
    "not_installed": "The CWatM account libraries (supabase, keyring) are not "
                     "installed for the Python running this GUI.",
    # the Shop (shop_buy refusals)
    "unknown_item": "This item is not sold in the Shop.",
    "already_owned": "You already own this.",
    "badge_required": "The Shop opens once you have earned the Breg badge.",
    "requires_item": "Buy the previous item first.",
    "not_enough_points": "You do not have enough points for this.",
}

# shop_buy() answers 'status'; everything but 'bought' is a refusal with these codes.
_SHOP_REFUSALS = ("unknown_item", "already_owned", "badge_required",
                  "requires_item", "not_enough_points")


def shop_refusal(result):
    """A shop_buy() answer that refused the purchase -> ``AccountError`` (else None).
    The message names what is missing: the points still needed, or the item to buy
    first (Expert needs Advanced)."""
    status = (result or {}).get("status")
    if status == "bought":
        return None
    if status not in _SHOP_REFUSALS:
        return AccountError("server_error", detail=f"shop_buy status {status!r}")
    message = MESSAGES[status]
    if status == "not_enough_points" and result.get("missing") is not None:
        n = int(result["missing"])
        message = f"You need {n} more point{'s' if n != 1 else ''} for this."
    elif status == "requires_item" and result.get("requires"):
        message = f"Buy {str(result['requires']).capitalize()} first."
    return AccountError(status, message)


def _import_supabase():
    """Import the supabase library, or raise ``not_installed`` with the fix.

    The repo keeps its server files in a ``supabase/`` folder, and Python imports that
    folder as an empty namespace package when the real library is missing - which
    surfaced as a baffling "cannot import name 'ClientOptions' from 'supabase'
    (unknown location)" reported as a server error. A package without ``__file__``
    is that folder, not the library."""
    import sys
    try:
        import supabase
        if getattr(supabase, "__file__", None) is None:
            raise ImportError("only the repo's supabase/ folder was found")
        from supabase import ClientOptions, create_client
    except ImportError as e:
        raise AccountError(
            "not_installed",
            MESSAGES["not_installed"] + "\n\nPython: " + sys.executable +
            # Only the two account libraries - `-r requirements.txt` would also
            # re-pin every other package of that Python.
            "\nInstall them with:\n    \"" + sys.executable +
            "\" -m pip install supabase keyring",
            detail=repr(e)) from e
    return ClientOptions, create_client

# Supabase Auth error codes -> our codes.
_AUTH_CODES = {
    "invalid_credentials": "invalid_credentials",
    "email_not_confirmed": "email_not_confirmed",
    "user_already_exists": "already_registered",
    "email_exists": "already_registered",
    "weak_password": "weak_password",
    "same_password": "same_password",
    "email_address_invalid": "invalid_email",
    "otp_expired": "invalid_code",
    "over_email_send_rate_limit": "rate_limited",
    "over_request_rate_limit": "rate_limited",
    "refresh_token_not_found": "session_expired",
    "refresh_token_already_used": "session_expired",
    "session_not_found": "session_expired",
    "session_expired": "session_expired",
    "user_not_found": "session_expired",
    "bad_jwt": "session_expired",
}

# Edge Function error bodies ({"error": ...}) -> our codes.
_FUNCTION_CODES = {
    "invalid_credentials": "invalid_credentials",
    "email_not_confirmed": "email_not_confirmed",
    "too_many_attempts": "too_many_attempts",
    "invalid_password": "invalid_password",
    "not_authenticated": "session_expired",
}

# Profile columns a user may change (= the column grants on public.profiles).
PROFILE_FIELDS = ("username", "full_name", "country", "institute",
                  "show_on_leaderboard", "share_locations",
                  "location_lat", "location_lon", "show_location_on_map")
_COORD_FIELDS = ("location_lat", "location_lon")
_BOOL_FIELDS = ("show_on_leaderboard", "share_locations", "show_location_on_map")

_TIMEOUT_S = 20


class AccountError(Exception):
    def __init__(self, code, message=None, detail=None):
        self.code = code
        self.message = message or MESSAGES.get(code, MESSAGES["server_error"])
        self.detail = detail
        super().__init__(self.message)


def translate_error(exc):
    """Any exception from supabase/httpx/postgrest -> ``AccountError``."""
    if isinstance(exc, AccountError):
        return exc
    try:
        import httpx
        from postgrest.exceptions import APIError
        from supabase_auth.errors import (AuthApiError, AuthError,
                                          AuthRetryableError,
                                          AuthSessionMissingError)
    except Exception:   # supabase itself failed to import
        log.warning("account libraries unavailable", exc_info=True)
        return AccountError("server_error", detail=repr(exc))

    if isinstance(exc, (httpx.TransportError, AuthRetryableError)):
        return AccountError("offline", detail=repr(exc))
    if isinstance(exc, AuthSessionMissingError):
        return AccountError("not_logged_in", detail=repr(exc))
    if isinstance(exc, AuthApiError):
        code = _AUTH_CODES.get(str(exc.code or ""))
        if code:
            return AccountError(code, detail=exc.message)
        if exc.status == 429:
            return AccountError("rate_limited", detail=exc.message)
        return AccountError("server_error",
                            detail=f"{exc.status} {exc.code}: {exc.message}")
    if isinstance(exc, AuthError):
        return AccountError("server_error", detail=repr(exc))
    if isinstance(exc, APIError):
        if exc.code == "23505":                          # unique violation
            return AccountError("username_taken", detail=exc.message)
        if exc.code in ("28000", "PGRST301", "PGRST302", "PGRST303"):
            return AccountError("session_expired", detail=exc.message)
        return AccountError("server_error", detail=f"{exc.code}: {exc.message}")
    return AccountError("server_error", detail=repr(exc))


def _check(problem):
    if problem:
        raise AccountError("invalid_input", problem)


class AccountClient:
    """Synchronous account API. Construct and call on one worker thread."""

    def __init__(self, remember=True):
        if not account_config.is_configured():
            raise AccountError("not_configured")
        ClientOptions, create_client = _import_supabase()
        import httpx

        self._remember = bool(remember)
        self._stored_refresh = None
        self._client = create_client(
            account_config.supabase_url(),
            account_config.supabase_key(),
            options=ClientOptions(
                auto_refresh_token=False,     # refreshed on demand in _session()
                persist_session=True,         # in-memory storage (the default)
                flow_type="implicit",         # no redirects in a desktop app
                postgrest_client_timeout=_TIMEOUT_S,
                function_client_timeout=_TIMEOUT_S,
            ))
        self._client.auth.on_auth_state_change(self._on_auth_event)
        self._http = httpx.Client(timeout=_TIMEOUT_S)

    # ---- session plumbing ------------------------------------------------------
    def _on_auth_event(self, event, session):
        """Keep the keyring's refresh token in step with the (rotating) session."""
        if event not in ("SIGNED_IN", "TOKEN_REFRESHED") or session is None:
            return
        token = session.refresh_token
        if self._remember and token and token != self._stored_refresh:
            if account_store.save_refresh_token(token):
                self._stored_refresh = token

    def _session(self):
        """The current session (refreshed if expired), or ``not_logged_in``."""
        try:
            session = self._client.auth.get_session()
        except Exception as e:
            err = translate_error(e)
            if err.code == "session_expired":
                self._forget_local_session()
            raise err
        if session is None:
            raise AccountError("not_logged_in")
        return session

    def _forget_local_session(self):
        account_store.clear_refresh_token()
        self._stored_refresh = None
        try:
            # sign_out() needs the network before it clears the local session; this
            # is the local-only half of it.
            self._client.auth._remove_session()
        except Exception:
            log.debug("could not clear the local session", exc_info=True)

    def _rpc(self, fn, params=None):
        try:
            return self._client.rpc(fn, params or {}).execute().data
        except Exception as e:
            raise translate_error(e) from e

    def _post_function(self, name, body, access_token=None):
        """POST to an Edge Function; returns its JSON body or raises AccountError."""
        key = account_config.supabase_key()
        headers = {"apikey": key, "Content-Type": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        elif key.startswith("eyJ"):                   # legacy JWT anon key
            headers["Authorization"] = f"Bearer {key}"
        try:
            resp = self._http.post(account_config.functions_url(name),
                                   json=body, headers=headers)
        except Exception as e:
            raise translate_error(e) from e
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code >= 400:
            code = _FUNCTION_CODES.get(str(data.get("error", "")))
            if code:
                raise AccountError(code)
            if resp.status_code == 429:
                raise AccountError("rate_limited")
            raise AccountError("server_error",
                               detail=f"{name}: {resp.status_code} {resp.text[:300]}")
        return data

    def _logged_in_status(self):
        status = self.get_status()
        status["email"] = self._session().user.email
        return status

    # ---- settings --------------------------------------------------------------
    def set_remember(self, remember):
        """Stay logged in across GUI restarts (keyring) - or forget the stored token."""
        self._remember = bool(remember)
        if not self._remember:
            account_store.clear_refresh_token()
            self._stored_refresh = None
            return {"remember": False}
        try:
            session = self._client.auth.get_session()
        except Exception:
            log.debug("no session to remember", exc_info=True)
            session = None
        if session is not None:
            self._on_auth_event("SIGNED_IN", session)
        return {"remember": True}

    # ---- login / logout --------------------------------------------------------
    def restore(self):
        """Log in again with the refresh token stored at the last session. Returns the
        status dict, or None when nothing is stored."""
        token = account_store.load_refresh_token()
        if not token:
            return None
        self._stored_refresh = token
        try:
            self._client.auth.refresh_session(token)
        except Exception as e:
            err = translate_error(e)
            if err.code in ("session_expired", "not_logged_in"):
                self._forget_local_session()
            raise err from e
        return self._logged_in_status()

    def login(self, identifier, password):
        """Log in with an email address or a username (told apart by the '@')."""
        identifier = (identifier or "").strip()
        if not identifier or not password:
            raise AccountError("invalid_input",
                               "Please enter your username or email and password.")
        if V.is_email(identifier):
            try:
                self._client.auth.sign_in_with_password(
                    {"email": identifier, "password": password})
            except Exception as e:
                raise translate_error(e) from e
        else:
            data = self._post_function("login-with-username",
                                       {"username": identifier, "password": password})
            session = data.get("session") or {}
            try:
                self._client.auth.set_session(session["access_token"],
                                              session["refresh_token"])
            except KeyError as e:
                raise AccountError("server_error", detail="no session in reply") from e
            except Exception as e:
                raise translate_error(e) from e
        return self._logged_in_status()

    def logout(self):
        """Log out on this computer (other computers stay logged in)."""
        try:
            self._client.auth.sign_out({"scope": "local"})
        except Exception:
            log.info("server-side sign-out failed; clearing locally", exc_info=True)
        self._forget_local_session()
        return {"status": "logged_out"}

    # ---- registration ----------------------------------------------------------
    def username_available(self, username):
        return bool(self._rpc("username_available", {"p_username": username.strip()}))

    def register(self, email, password, username,
                 full_name=None, country=None, institute=None, privacy_version=None,
                 share_locations=False, location_lat=None, location_lon=None,
                 show_on_leaderboard=False, show_location_on_map=False):
        """Create an account. Returns {"status": "confirm_email", "email": ...} - the
        user then enters the emailed code (``confirm_signup``).

        ``privacy_version`` = the privacy notice the user agreed to; required (the
        server refuses a sign-up without it too). The three choices are stored in
        the profile by the server's sign-up trigger (handle_new_user)."""
        email = (email or "").strip()
        username = (username or "").strip()
        if not privacy_version:
            raise AccountError("invalid_input",
                               "Please agree to the privacy notice first.")
        _check(V.email_problem(email))
        _check(V.username_problem(username))
        _check(V.password_problem(password))
        if not self.username_available(username):
            raise AccountError("username_taken")

        data = {"username": username, "privacy_version": str(privacy_version)[:40],
                "share_locations": bool(share_locations),
                "show_on_leaderboard": bool(show_on_leaderboard),
                "show_location_on_map": bool(show_location_on_map)}
        if location_lat is not None and location_lon is not None:
            data["location_lat"] = V.round_location(location_lat)
            data["location_lon"] = V.round_location(location_lon)
        for field, value in (("full_name", full_name), ("country", country),
                             ("institute", institute)):
            value = V.clean_optional(field, value)
            if value:
                data[field] = value
        try:
            resp = self._client.auth.sign_up(
                {"email": email, "password": password, "options": {"data": data}})
        except Exception as e:
            raise translate_error(e) from e

        user = resp.user
        # With email confirmation on, Supabase answers a sign-up for an address that
        # already has an account with a user without identities instead of an error.
        if user is not None and user.identities is not None and not user.identities:
            raise AccountError("already_registered")
        if resp.session is not None:          # confirmation switched off on the server
            return dict(self._logged_in_status(), status="logged_in")
        return {"status": "confirm_email", "email": email}

    def confirm_signup(self, email, code):
        """Confirm the email with the 6-digit code; logs the user in."""
        _check(V.code_problem(code))
        try:
            self._client.auth.verify_otp(
                {"email": email.strip(), "token": code.strip(), "type": "signup"})
        except Exception as e:
            raise translate_error(e) from e
        return dict(self._logged_in_status(), status="logged_in")

    def resend_confirmation(self, email):
        try:
            self._client.auth.resend({"type": "signup", "email": email.strip()})
        except Exception as e:
            raise translate_error(e) from e
        return {"status": "sent", "email": email.strip()}

    # ---- password reset --------------------------------------------------------
    def request_password_reset(self, email):
        email = (email or "").strip()
        _check(V.email_problem(email))
        try:
            self._client.auth.reset_password_for_email(email)
        except Exception as e:
            raise translate_error(e) from e
        return {"status": "sent", "email": email}

    def reset_password(self, email, code, new_password):
        """Set a new password with the emailed code; logs the user in."""
        _check(V.code_problem(code))
        _check(V.password_problem(new_password))
        try:
            self._client.auth.verify_otp(
                {"email": email.strip(), "token": code.strip(), "type": "recovery"})
            self._client.auth.update_user({"password": new_password})
        except Exception as e:
            raise translate_error(e) from e
        return dict(self._logged_in_status(), status="logged_in")

    # ---- profile + points ------------------------------------------------------
    def get_status(self):
        """{profile, total_points, badges, next_badge} of the logged-in user."""
        self._session()
        return self._rpc("get_my_status") or {}

    def update_profile(self, **fields):
        unknown = set(fields) - set(PROFILE_FIELDS)
        if unknown:
            raise AccountError("invalid_input",
                               f"Unknown profile field(s): {', '.join(sorted(unknown))}")
        if ("location_lat" in fields) != ("location_lon" in fields):
            # the server keeps both or neither (profiles_location_both_or_none)
            raise AccountError("invalid_input",
                               "Latitude and longitude are changed together.")
        changes = {}
        for field, value in fields.items():
            if field == "username":
                value = (value or "").strip()
                _check(V.username_problem(value))
            elif field in _BOOL_FIELDS:
                value = bool(value)
            elif field in _COORD_FIELDS:
                value = None if value in (None, "") else V.round_location(value)
            else:
                value = V.clean_optional(field, value)
            changes[field] = value
        session = self._session()
        if not changes:
            return self.get_status()
        try:
            self._client.table("profiles").update(changes) \
                .eq("id", session.user.id).execute()
        except Exception as e:
            raise translate_error(e) from e
        return self._logged_in_status()

    def award_run(self, run_uid, meta=None):
        """Ask the server for the points of one full run (idempotent per run_uid).
        Returns the award_run() answer: {status, total_points, new_badges, ...}."""
        self._session()
        return self._rpc("award_run", {"p_run_uid": run_uid, "p_meta": meta or {}}) or {}

    def record_location(self, lon, lat):
        """Report one successful run's first gauge to the ANONYMOUS run-location
        count (no user stored server-side). Needs the user's consent
        (profile.share_locations) - the server checks it. {status}."""
        self._session()
        return self._rpc("record_run_location",
                         {"p_lon": float(lon), "p_lat": float(lat)}) or {}

    def academy_complete_level(self, level):
        """A finished CWatM Academy level -> the profile's progress, and its points
        (once per level). {status, level, points_awarded, total_points, new_badges,
        academy_completed}."""
        self._session()
        return self._rpc("academy_complete_level", {"p_level": int(level)}) or {}

    def academy_reset(self):
        """Academy Start Over: clear the profile's progress (the points stay)."""
        self._session()
        return self._rpc("academy_reset") or {}

    def touch_activity(self):
        """A login = CWatM GUI was used: the server records the point decay due
        since the last use, then restarts the clock. Returns the status (get_status
        shape) plus decayed_points and inactive_weeks."""
        session = self._session()
        result = self._rpc("touch_activity") or {}
        return dict(result, email=session.user.email)

    # ---- the Shop --------------------------------------------------------------
    def get_shop_items(self):
        """The price list (public): [{code, kind, name, price, requires}], in shop
        order. kind = 'level' | 'animal'; requires = an item code or None."""
        rows = self._rpc("get_shop_items") or []
        return [{"code": r["code"], "kind": r["kind"], "name": r["name"],
                 "price": int(r["price"]), "requires": r.get("requires")}
                for r in rows]

    def buy(self, item_code):
        """Buy one Shop item. Returns the new status (get_status() shape, plus
        status='bought', item, price). A refusal - not enough points, already owned,
        no Breg badge yet, Expert before Advanced - raises AccountError with that
        code and a readable message; the server checked it, the GUI only explains."""
        item_code = (item_code or "").strip().lower()
        if not item_code:
            raise AccountError("invalid_input", "No item chosen.")
        session = self._session()
        result = self._rpc("shop_buy", {"p_item": item_code}) or {}
        refusal = shop_refusal(result)
        if refusal is not None:
            raise refusal
        return dict(result, email=session.user.email)

    def get_run_locations(self):
        """The anonymous run-location totals for Info ▸ World Map:
        [{lon, lat, runs}] (public - no login needed)."""
        rows = self._rpc("get_run_locations") or []
        return [{"lon": float(r["lon"]), "lat": float(r["lat"]),
                 "runs": int(r["runs"])} for r in rows]

    def get_user_locations(self):
        """Users' own locations for Info ▸ World Map ▸ User location - only users
        who opted in, no names, 0.5 degree: [{lon, lat, users}] (public)."""
        rows = self._rpc("get_user_locations") or []
        return [{"lon": float(r["lon"]), "lat": float(r["lat"]),
                 "users": int(r["users"])} for r in rows]

    def get_leaderboard(self, limit=50):
        return self._rpc("get_leaderboard", {"p_limit": int(limit)}) or []

    def get_badges(self):
        """The whole badge ladder (public): [{code, name, points_required}], in order."""
        try:
            return self._client.table("badges") \
                .select("code,name,points_required,sort_order") \
                .order("sort_order").execute().data or []
        except Exception as e:
            raise translate_error(e) from e

    def export_data(self):
        """Everything the server stores about the user (GDPR export)."""
        self._session()
        return self._rpc("export_my_data") or {}

    def delete_account(self, password):
        """Permanently delete the account and all its data (password re-checked)."""
        if not password:
            raise AccountError("invalid_input", "Please enter your password.")
        session = self._session()
        self._post_function("delete-account", {"password": password},
                            access_token=session.access_token)
        self._forget_local_session()
        return {"status": "deleted"}

    def close(self):
        try:
            self._http.close()
        except Exception:
            log.debug("closing the http client failed", exc_info=True)
