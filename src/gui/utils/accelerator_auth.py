"""Accelerator device-flow login - a Python port of the Tauri client's own
``tauri-app/src/lib/accelerator/auth.ts`` (same sequencing, confirmed live
there against the real server; mirrored here rather than re-derived):

  1. The user opens ``accelerator_config.AUTH_CODE_URL`` in a real browser
     while logged into the Accelerator web session; that page shows them a
     short code.
  2. ``redeem_device_code(code)`` exchanges it for a refresh token.
  3. ``get_access_token()`` exchanges the stored refresh token for a
     short-lived access token, rotating the refresh token each time - every
     authenticated call goes through this.
  4. ``who_am_i()`` - the logged-in user's identity (``full_name``,
     ``email``, ``roles``, ``uid``), to identify the caller to whatever
     replaces the points/badges backend. ``GET /v1/auth/user/`` (tried
     first) turned out to be browser-only (confirmed by the Accelerator
     team, 2026-11-02 - its "Invalid token" response to our working
     device-flow access token wasn't a bug on our side). The team added
     a proper one under aterm-cli for this exact purpose and sent the
     link once it shipped (2026-11-04): ``GET
     /v1/aterm-cli/user/me/`` - same response shape, not yet
     re-verified live against the real server with this new path
     (steps 1-3 were, 2026-11-02; update this note once step 4 is too).

Unrelated to ``account_auth``/``account_client.py``'s Supabase-backed CWatM
account login - a separate identity provider entirely, its own keyring
entry (``accelerator_store.py``), never conflated.

``requests`` is imported lazily inside each function (never at module top
level) per the fast-startup rule in CLAUDE.md - same convention already
used for it elsewhere in this codebase (e.g. ``basin_viewer.py``).
"""

import threading
import time

from src.gui.utils import accelerator_config as config
from src.gui.utils import accelerator_store as store
from src.gui.utils.gui_log import get_logger

log = get_logger("accelerator_auth")

_REQUEST_TIMEOUT_SECONDS = 15


class AcceleratorAuthError(Exception):
    pass


def redeem_device_code(device_authorization_code):
    """Exchange a device authorization code (from AUTH_CODE_URL) for a refresh token, and store it."""
    import requests

    try:
        res = requests.post(
            f"{config.OAUTH_BASE}/token/",
            json={"device_authorization_code": device_authorization_code},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise AcceleratorAuthError("Could not reach Accelerator - check your internet connection.") from exc

    if res.status_code == 400:
        detail = None
        try:
            detail = res.json().get("detail")
        except Exception:
            log.debug("400 response body was not the expected {detail: ...} shape", exc_info=True)
        raise AcceleratorAuthError(detail or "Invalid or expired authorization code.")
    if not res.ok:
        raise AcceleratorAuthError(f"Login failed (HTTP {res.status_code}).")

    # The token/ endpoint's response body is the refresh token itself
    # (a JSON-encoded string, not an object) - matches auth.ts's own finding.
    refresh_token = res.json()
    # save_refresh_token degrades to a logged, swallowed failure by design
    # (account_store.py's same convention - a missing keyring backend is
    # not fatal to the rest of the app) - but here it would silently leave
    # the user "logged in" for this one call and logged out the moment
    # get_access_token next tries to read it back, which looked exactly
    # like a successful login until it didn't (caught live: the real cause
    # was a missing keyring package in the Python running this, not a
    # keyring failure at all - still worth never masking either case).
    if not store.save_refresh_token(refresh_token):
        raise AcceleratorAuthError(
            "Logged in, but could not save the session (see gui.log) - you will need to log in again next time."
        )


def is_logged_in():
    return store.load_refresh_token() is not None


def logout():
    store.clear_refresh_token()
    with _cache_lock:
        _cache["access_token"] = None
        _cache["expires_at"] = 0.0


# In-memory access-token cache - same shape as auth.ts's: short-lived
# (expires in ~1h), refreshed with a few minutes of headroom. A lock
# (rather than auth.ts's single-shared-Promise trick, which has no direct
# Python equivalent) makes concurrent callers from different threads wait
# for one exchange instead of each rotating the refresh token out from
# under the others - the same race auth.ts's own comment describes.
_cache = {"access_token": None, "expires_at": 0.0}
_cache_lock = threading.Lock()
_EXPIRY_HEADROOM_SECONDS = 5 * 60


def get_access_token():
    """Returns a valid access token, refreshing the stored refresh token if needed. Raises AcceleratorAuthError if not logged in or the session has expired."""
    import requests

    with _cache_lock:
        now = time.monotonic()
        if _cache["access_token"] and _cache["expires_at"] - now > _EXPIRY_HEADROOM_SECONDS:
            return _cache["access_token"]

        refresh_token = store.load_refresh_token()
        if not refresh_token:
            raise AcceleratorAuthError("Not logged in.")

        try:
            res = requests.post(
                f"{config.OAUTH_BASE}/access-token/",
                json={"refresh_token": refresh_token},
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise AcceleratorAuthError("Could not reach Accelerator - check your internet connection.") from exc

        if res.status_code in (400, 401, 403):
            store.clear_refresh_token()
            raise AcceleratorAuthError("Session expired. Please log in again.")
        if not res.ok:
            raise AcceleratorAuthError(f"Could not refresh session (HTTP {res.status_code}).")

        data = res.json()
        store.save_refresh_token(data["refresh_token"])

        _cache["access_token"] = data["access_token"]
        # Server tokens last ~1h; match auth.ts's conservative ~50 min cache window.
        _cache["expires_at"] = time.monotonic() + 50 * 60
        return _cache["access_token"]


def who_am_i():
    """The logged-in user's identity: {full_name, email, roles, uid} -
    GET /v1/aterm-cli/user/me/ (not yet re-verified live with this path -
    see this module's own doc comment)."""
    import requests

    access_token = get_access_token()
    try:
        res = requests.get(
            f"{config.ATERM_BASE}/user/me/",
            headers={"x-authorization": access_token},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise AcceleratorAuthError("Could not reach Accelerator - check your internet connection.") from exc

    if res.status_code in (401, 403):
        # Surface the server's own detail rather than a generic message -
        # same lesson auth.ts's own atermFetch.ts already learned live:
        # it's the useful diagnostic signal, not just "not authorized".
        detail = None
        try:
            detail = res.json().get("detail")
        except Exception:
            log.debug("401/403 response body was not the expected {detail: ...} shape", exc_info=True)
        raise AcceleratorAuthError(detail or "Not authorized.")
    if not res.ok:
        raise AcceleratorAuthError(f"Could not fetch account info (HTTP {res.status_code}).")
    return res.json()
