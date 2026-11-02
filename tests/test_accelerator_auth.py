"""Accelerator device-flow login (`src/gui/utils/accelerator_auth.py`) - no network.

`accelerator_auth.py` lazy-imports `requests` inside each function (never at
module top level, per CLAUDE.md's fast-startup rule), so it's mocked the same
way test_account.py mocks the lazily-imported `supabase` library: a fake
module injected into `sys.modules` - no real `requests` package needed for
these tests to run in the dependency-free CI job.
"""

import sys

import pytest

from src.gui.utils import accelerator_auth as AA
from src.gui.utils import accelerator_config


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._body


class _FakeRequestException(Exception):
    pass


class _FakeRequests:
    """Stand-in for the `requests` module."""

    RequestException = _FakeRequestException

    def __init__(self, response=None, raise_exc=None):
        self._response = response
        self._raise_exc = raise_exc
        self.calls = []

    def _call(self, method, url, json=None, headers=None, timeout=None):
        self.calls.append((method, url, json, headers))
        if self._raise_exc:
            raise self._raise_exc
        return self._response

    def post(self, url, json=None, headers=None, timeout=None):
        return self._call("POST", url, json=json, headers=headers, timeout=timeout)

    def get(self, url, headers=None, timeout=None):
        return self._call("GET", url, headers=headers, timeout=timeout)


@pytest.fixture(autouse=True)
def _reset_cache():
    AA._cache["access_token"] = None
    AA._cache["expires_at"] = 0.0
    yield
    AA._cache["access_token"] = None
    AA._cache["expires_at"] = 0.0


def _install_fake_requests(monkeypatch, **kwargs):
    fake = _FakeRequests(**kwargs)
    monkeypatch.setitem(sys.modules, "requests", fake)
    return fake


class TestKeyringEntry:
    def test_distinct_from_the_supabase_account_entry(self):
        service, user = accelerator_config.keyring_entry()
        assert service == "CWatM_GUI"
        assert user.startswith("accelerator:")


class TestRedeemDeviceCode:
    def test_success_saves_the_refresh_token(self, monkeypatch):
        fake = _install_fake_requests(monkeypatch, response=_FakeResponse(200, "a-refresh-token"))
        saved = {}
        monkeypatch.setattr(AA.store, "save_refresh_token", lambda t: saved.setdefault("token", t))

        AA.redeem_device_code("the-code")

        assert saved["token"] == "a-refresh-token"
        method, url, body, _headers = fake.calls[0]
        assert method == "POST"
        assert url.endswith("/oauth/device/token/")
        assert body == {"device_authorization_code": "the-code"}

    def test_invalid_code_raises_with_the_server_detail(self, monkeypatch):
        _install_fake_requests(monkeypatch, response=_FakeResponse(400, {"detail": "Code expired."}))
        with pytest.raises(AA.AcceleratorAuthError, match="Code expired."):
            AA.redeem_device_code("stale-code")

    def test_other_server_errors_raise_with_the_status_code(self, monkeypatch):
        _install_fake_requests(monkeypatch, response=_FakeResponse(500, {}))
        with pytest.raises(AA.AcceleratorAuthError, match="500"):
            AA.redeem_device_code("the-code")

    def test_network_failure_raises_a_clear_message(self, monkeypatch):
        _install_fake_requests(monkeypatch, raise_exc=_FakeRequestException("boom"))
        with pytest.raises(AA.AcceleratorAuthError, match="internet connection"):
            AA.redeem_device_code("the-code")

    def test_a_failed_save_is_never_silently_reported_as_success(self, monkeypatch):
        # Caught live: a missing keyring package made save_refresh_token
        # swallow its own exception and return False - without this check,
        # redeem_device_code returned normally, looking exactly like a
        # successful login right up until the very next call failed.
        _install_fake_requests(monkeypatch, response=_FakeResponse(200, "a-refresh-token"))
        monkeypatch.setattr(AA.store, "save_refresh_token", lambda t: False)
        with pytest.raises(AA.AcceleratorAuthError, match="could not save the session"):
            AA.redeem_device_code("the-code")


class TestGetAccessToken:
    def test_not_logged_in_raises_without_a_network_call(self, monkeypatch):
        fake = _install_fake_requests(monkeypatch)
        monkeypatch.setattr(AA.store, "load_refresh_token", lambda: None)
        with pytest.raises(AA.AcceleratorAuthError, match="Not logged in"):
            AA.get_access_token()
        assert fake.calls == []

    def test_exchanges_the_refresh_token_and_caches_the_result(self, monkeypatch):
        fake = _install_fake_requests(
            monkeypatch,
            response=_FakeResponse(200, {"access_token": "new-access", "refresh_token": "rotated-refresh"}),
        )
        monkeypatch.setattr(AA.store, "load_refresh_token", lambda: "old-refresh")
        saved = {}
        monkeypatch.setattr(AA.store, "save_refresh_token", lambda t: saved.setdefault("token", t))

        token = AA.get_access_token()

        assert token == "new-access"
        assert saved["token"] == "rotated-refresh"
        method, url, body, headers = fake.calls[0]
        assert body == {"refresh_token": "old-refresh"}

        # A second call within the cache window must not hit the network again.
        token2 = AA.get_access_token()
        assert token2 == "new-access"
        assert len(fake.calls) == 1

    def test_expired_session_clears_the_stored_token(self, monkeypatch):
        _install_fake_requests(monkeypatch, response=_FakeResponse(401, {}))
        monkeypatch.setattr(AA.store, "load_refresh_token", lambda: "old-refresh")
        cleared = {"called": False}
        monkeypatch.setattr(AA.store, "clear_refresh_token", lambda: cleared.__setitem__("called", True))

        with pytest.raises(AA.AcceleratorAuthError, match="log in again"):
            AA.get_access_token()
        assert cleared["called"]


class TestWhoAmI:
    def test_returns_the_identity_payload(self, monkeypatch):
        monkeypatch.setattr(AA, "get_access_token", lambda: "a-token")
        fake = _install_fake_requests(
            monkeypatch,
            response=_FakeResponse(200, {"full_name": "A Researcher", "email": "a@example.org", "roles": [], "uid": 42}),
        )

        identity = AA.who_am_i()

        assert identity == {"full_name": "A Researcher", "email": "a@example.org", "roles": [], "uid": 42}
        _method, url, _body, headers = fake.calls[0]
        assert url.endswith("/auth/user/")
        assert headers["x-authorization"] == "a-token"

    def test_unauthorized_raises(self, monkeypatch):
        monkeypatch.setattr(AA, "get_access_token", lambda: "a-token")
        _install_fake_requests(monkeypatch, response=_FakeResponse(401, {}))
        with pytest.raises(AA.AcceleratorAuthError, match="Not authorized"):
            AA.who_am_i()


class TestLoginState:
    def test_is_logged_in_reflects_the_stored_token(self, monkeypatch):
        monkeypatch.setattr(AA.store, "load_refresh_token", lambda: "a-token")
        assert AA.is_logged_in() is True
        monkeypatch.setattr(AA.store, "load_refresh_token", lambda: None)
        assert AA.is_logged_in() is False

    def test_logout_clears_the_store_and_the_in_memory_cache(self, monkeypatch):
        AA._cache["access_token"] = "stale"
        AA._cache["expires_at"] = 1e18
        cleared = {"called": False}
        monkeypatch.setattr(AA.store, "clear_refresh_token", lambda: cleared.__setitem__("called", True))

        AA.logout()

        assert cleared["called"]
        assert AA._cache["access_token"] is None
        assert AA._cache["expires_at"] == 0.0
