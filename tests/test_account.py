"""CWatM account client-side logic (`src/gui/utils/account_*.py`) - no network.

The input rules must agree with the server (the username rule is also the
profiles.username check constraint), library exceptions must become stable
AccountError codes the UI can branch on, and the rotating refresh token must reach
the keyring. The Supabase client and the HTTP client are replaced by fakes; nothing
here talks to a server.
"""

from types import SimpleNamespace

import pytest

from src.gui.utils import account_validation as V


class TestValidation:
    @pytest.mark.parametrize("name", ["abc", "Peter_B", "p.burek-2", "9lives",
                                      "a" * 30])
    def test_valid_usernames(self, name):
        assert V.username_problem(name) is None

    @pytest.mark.parametrize("name", ["", "ab", "a" * 31, "_peter", ".x1",
                                      "peter burek", "peter@iiasa", "pëter"])
    def test_invalid_usernames(self, name):
        assert V.username_problem(name) is not None

    def test_a_username_can_never_look_like_an_email(self):
        # The login field tells username from email by '@' alone.
        assert V.is_email("someone@example.org")
        assert not V.is_email("someone")
        assert V.username_problem("someone@example.org") is not None

    def test_password_length_limits(self):
        assert V.password_problem("1234567") is not None
        assert V.password_problem("12345678") is None
        assert V.password_problem("x" * 72) is None
        assert V.password_problem("x" * 73) is not None
        # 72 is a byte limit (bcrypt), not a character limit.
        assert V.password_problem("ä" * 37) is not None

    def test_password_repeat(self):
        assert V.password_problem("secret123", "secret123") is None
        assert V.password_problem("secret123", "secret124") is not None

    @pytest.mark.parametrize("code,ok", [("123456", True), (" 123456 ", True),
                                         ("12345", False), ("12a456", False),
                                         ("", False)])
    def test_code(self, code, ok):
        assert (V.code_problem(code) is None) is ok

    def test_clean_optional(self):
        assert V.clean_optional("country", "  ") is None
        assert V.clean_optional("country", " Austria ") == "Austria"
        assert len(V.clean_optional("country", "x" * 500)) == 60


supabase_auth = pytest.importorskip("supabase_auth")

from src.gui.utils import account_client as AC  # noqa: E402  (after the skip)


class TestTranslateError:
    def test_network_failure_is_offline(self):
        import httpx
        err = AC.translate_error(httpx.ConnectError("no route"))
        assert err.code == "offline"

    @pytest.mark.parametrize("auth_code,expected", [
        ("invalid_credentials", "invalid_credentials"),
        ("email_not_confirmed", "email_not_confirmed"),
        ("otp_expired", "invalid_code"),
        ("refresh_token_already_used", "session_expired"),
        ("weak_password", "weak_password"),
    ])
    def test_auth_codes(self, auth_code, expected):
        from supabase_auth.errors import AuthApiError
        err = AC.translate_error(AuthApiError("msg", 400, auth_code))
        assert err.code == expected
        assert err.message == AC.MESSAGES[expected]

    def test_unknown_auth_code_is_server_error_with_detail(self):
        from supabase_auth.errors import AuthApiError
        err = AC.translate_error(AuthApiError("boom", 500, "unexpected_failure"))
        assert err.code == "server_error"
        assert "boom" in err.detail

    def test_unique_violation_is_username_taken(self):
        from postgrest.exceptions import APIError
        err = AC.translate_error(APIError({"code": "23505", "message": "dup"}))
        assert err.code == "username_taken"

    def test_account_error_passes_through(self):
        e = AC.AccountError("rate_limited")
        assert AC.translate_error(e) is e


def _bare_client(auth=None, http=None, remember=True):
    """An AccountClient without __init__ (no supabase client, no network)."""
    c = AC.AccountClient.__new__(AC.AccountClient)
    c._remember = remember
    c._stored_refresh = None
    c._client = SimpleNamespace(auth=auth)
    c._http = http
    return c


class TestRefreshTokenStorage:
    def test_rotated_token_is_saved_once(self, monkeypatch):
        saved = []
        monkeypatch.setattr(AC.account_store, "save_refresh_token",
                            lambda t: saved.append(t) or True)
        c = _bare_client()
        session = SimpleNamespace(refresh_token="r1")
        c._on_auth_event("SIGNED_IN", session)
        c._on_auth_event("TOKEN_REFRESHED", session)          # unchanged token
        c._on_auth_event("TOKEN_REFRESHED", SimpleNamespace(refresh_token="r2"))
        assert saved == ["r1", "r2"]

    def test_nothing_saved_without_remember(self, monkeypatch):
        saved = []
        monkeypatch.setattr(AC.account_store, "save_refresh_token",
                            lambda t: saved.append(t) or True)
        c = _bare_client(remember=False)
        c._on_auth_event("SIGNED_IN", SimpleNamespace(refresh_token="r1"))
        assert saved == []

    def test_sign_out_event_is_ignored(self, monkeypatch):
        # Clearing the keyring is logout()'s job, not an event side effect: a failed
        # refresh while offline must not forget the login.
        cleared = []
        monkeypatch.setattr(AC.account_store, "clear_refresh_token",
                            lambda: cleared.append(1))
        _bare_client()._on_auth_event("SIGNED_OUT", None)
        assert cleared == []


class _FakeResponse:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


class TestLogin:
    def _client(self, monkeypatch, http_response):
        calls = SimpleNamespace(posted=None, set_session=None, password_login=None)

        def post(url, json, headers):
            calls.posted = (url, json, headers)
            return http_response

        auth = SimpleNamespace(
            set_session=lambda a, r: setattr(calls, "set_session", (a, r)),
            sign_in_with_password=lambda cred: setattr(calls, "password_login", cred),
        )
        c = _bare_client(auth=auth, http=SimpleNamespace(post=post))
        monkeypatch.setattr(c, "_logged_in_status", lambda: {"ok": True})
        monkeypatch.setattr(AC.account_config, "supabase_key", lambda: "sb_publishable_x")
        return c, calls

    def test_username_goes_through_the_edge_function(self, monkeypatch):
        c, calls = self._client(monkeypatch, _FakeResponse(
            200, {"session": {"access_token": "a", "refresh_token": "r"}}))
        assert c.login("peter", "secret123") == {"ok": True}
        url, body, headers = calls.posted
        assert url.endswith("/functions/v1/login-with-username")
        assert body == {"username": "peter", "password": "secret123"}
        assert headers["apikey"] == "sb_publishable_x"
        assert "Authorization" not in headers       # not a JWT key
        assert calls.set_session == ("a", "r")
        assert calls.password_login is None

    def test_email_signs_in_directly(self, monkeypatch):
        c, calls = self._client(monkeypatch, None)
        c.login(" peter@example.org ", "secret123")
        assert calls.password_login == {"email": "peter@example.org",
                                        "password": "secret123"}
        assert calls.posted is None

    @pytest.mark.parametrize("status,body,code", [
        (400, {"error": "invalid_credentials"}, "invalid_credentials"),
        (429, {"error": "too_many_attempts"}, "too_many_attempts"),
        (400, {"error": "email_not_confirmed"}, "email_not_confirmed"),
        (502, {}, "server_error"),
    ])
    def test_function_errors(self, monkeypatch, status, body, code):
        c, _ = self._client(monkeypatch, _FakeResponse(status, body))
        with pytest.raises(AC.AccountError) as info:
            c.login("peter", "secret123")
        assert info.value.code == code

    def test_empty_input_is_rejected_before_any_request(self, monkeypatch):
        c, calls = self._client(monkeypatch, None)
        with pytest.raises(AC.AccountError) as info:
            c.login("", "")
        assert info.value.code == "invalid_input"
        assert calls.posted is None and calls.password_login is None


@pytest.mark.qt          # imports a Qt module
def test_worker_rejects_unknown_operations():
    from src.gui.utils.account_worker import AccountWorker
    w = AccountWorker()
    with pytest.raises(ValueError):
        w.submit("drop_table")
    w.submit("get_status")                # known op: queued, not run (thread not started)


def test_missing_library_says_so_instead_of_server_error(monkeypatch):
    """Without the supabase library, Python imports the repo's supabase/ folder as an
    empty namespace package; that used to surface as 'server reported an error'."""
    import sys
    import types
    fake = types.ModuleType("supabase")          # no __file__ = the namespace folder
    monkeypatch.setitem(sys.modules, "supabase", fake)
    with pytest.raises(AC.AccountError) as info:
        AC.AccountClient()
    assert info.value.code == "not_installed"
    assert sys.executable in info.value.message
    assert "pip install" in info.value.message


class TestOwnLocation:
    @pytest.mark.parametrize("lat,lon,ok", [
        ("", "", True), ("48.067", "16.357", True), ("48,067", "16,357", True),
        ("-90", "180", True), ("48.067", "", False), ("", "16.357", False),
        ("north", "16.357", False), ("91", "16", False), ("48", "181", False)])
    def test_location_problem(self, lat, lon, ok):
        assert (V.location_problem(lat, lon) is None) is ok

    def test_parse_rounds_to_half_a_degree(self):
        assert V.parse_location(" 48.06749 ", "16,35712") == (48.0, 16.5)
        assert V.parse_location("", "") == (None, None)

    @pytest.mark.parametrize("value,rounded", [
        (48.067, 48.0), (16.357, 16.5), (48.25, 48.5), (48.24, 48.0),
        (-48.25, -48.5), (-0.2, 0.0), (179.9, 180.0), (-90, -90.0)])
    def test_round_location_like_the_server(self, value, rounded):
        # halves away from zero = Postgres numeric round() in the profiles trigger
        assert V.round_location(value) == rounded

    def test_format(self):
        assert V.format_coord(48.067) == "48.067"
        assert V.format_coord("16.300") == "16.3"
        assert V.format_coord(None) == ""

    def test_update_needs_both(self):
        c = _bare_client()
        with pytest.raises(AC.AccountError) as info:
            c.update_profile(location_lat=48.0)
        assert info.value.code == "invalid_input"


class TestShopClient:
    """buy() / get_shop_items(): the server decides, the client only explains."""

    def _client(self, monkeypatch, answer):
        c = _bare_client()
        sent = []
        monkeypatch.setattr(c, "_session",
                            lambda: SimpleNamespace(user=SimpleNamespace(email="p@x.org")))

        def rpc(fn, params=None):
            sent.append((fn, params))
            return answer
        monkeypatch.setattr(c, "_rpc", rpc)
        return c, sent

    def test_bought_returns_the_new_status(self, monkeypatch):
        c, sent = self._client(monkeypatch, {"status": "bought", "item": "otter",
                                             "price": 10, "balance": 2})
        result = c.buy(" Otter ")
        assert sent == [("shop_buy", {"p_item": "otter"})]
        assert result["balance"] == 2 and result["email"] == "p@x.org"

    @pytest.mark.parametrize("answer,code,text", [
        ({"status": "not_enough_points", "missing": 7}, "not_enough_points",
         "You need 7 more points for this."),
        ({"status": "not_enough_points", "missing": 1}, "not_enough_points",
         "You need 1 more point for this."),
        ({"status": "requires_item", "requires": "advanced"}, "requires_item",
         "Buy Advanced first."),
        ({"status": "already_owned"}, "already_owned", "You already own this."),
        ({"status": "badge_required", "badge": "breg"}, "badge_required", "Breg"),
        ({"status": "unknown_item"}, "unknown_item", "not sold"),
        ({"status": "surprise"}, "server_error", "server"),
    ])
    def test_refusals_become_account_errors(self, monkeypatch, answer, code, text):
        c, _sent = self._client(monkeypatch, answer)
        with pytest.raises(AC.AccountError) as info:
            c.buy("expert")
        assert info.value.code == code and text in info.value.message

    def test_empty_item_sends_nothing(self, monkeypatch):
        c, sent = self._client(monkeypatch, {"status": "bought"})
        with pytest.raises(AC.AccountError) as info:
            c.buy("  ")
        assert info.value.code == "invalid_input" and sent == []

    def test_price_list(self, monkeypatch):
        c, sent = self._client(monkeypatch, [
            {"code": "advanced", "kind": "level", "name": "Advanced", "price": 20,
             "requires": None},
            {"code": "expert", "kind": "level", "name": "Expert", "price": "40",
             "requires": "advanced"}])
        items = c.get_shop_items()
        assert sent == [("get_shop_items", None)]
        assert items[1] == {"code": "expert", "kind": "level", "name": "Expert",
                            "price": 40, "requires": "advanced"}

    @pytest.mark.qt          # imports a Qt module
    def test_worker_knows_the_shop_ops(self):
        from src.gui.utils.account_worker import OPS
        assert {"buy", "get_shop_items"} <= OPS