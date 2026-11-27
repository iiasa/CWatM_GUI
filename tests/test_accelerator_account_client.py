"""`AcceleratorAccountClient` - the CWatM account over the Accelerator login.

No network and no keyring: `accelerator_auth` is replaced by a fake, so these cover
only what the client adds - the status dict the UI reads, the error codes it maps to,
"stay logged in", and the operations that are not built yet.
"""

import sys

import pytest

from src.gui.utils import accelerator_account_client as AAC
from src.gui.utils.account_client import AccountError

ME = {"full_name": "SMILOVIC Mikhail", "email": "m@example.org",
      "roles": ["APP__VIEW"], "uid": 315}


class FakeAuth:
    AcceleratorAuthError = AAC.auth.AcceleratorAuthError

    def __init__(self, logged_in=True, me=None, redeem_error=None, me_error=None):
        self.logged_in = logged_in
        self.me = ME if me is None else me
        self.redeem_error = redeem_error
        self.me_error = me_error
        self.redeemed = []
        self.logouts = 0

    def is_logged_in(self):
        return self.logged_in

    def redeem_device_code(self, code):
        if self.redeem_error:
            raise self.redeem_error
        self.redeemed.append(code)
        self.logged_in = True

    def get_access_token(self):
        return "access-token"

    def who_am_i(self):
        if self.me_error:
            raise self.me_error
        return self.me

    def logout(self):
        self.logouts += 1
        self.logged_in = False


@pytest.fixture
def fake(monkeypatch):
    f = FakeAuth()
    monkeypatch.setattr(AAC, "auth", f)
    monkeypatch.setenv("CWATM_GUI_POINTS_URL", "https://points.example")
    return f


class TestIdentity:
    def test_restore_without_a_stored_login_is_none(self, fake):
        fake.logged_in = False
        assert AAC.AcceleratorAccountClient().restore() is None

    def test_restore_returns_the_status(self, fake):
        status = AAC.AcceleratorAccountClient().restore()
        assert status["profile"]["username"] == "SMILOVIC Mikhail"
        assert status["uid"] == 315 and status["email"] == "m@example.org"

    def test_login_redeems_the_stripped_code_and_returns_the_status(self, fake):
        status = AAC.AcceleratorAccountClient().login("  abc123 ")
        assert fake.redeemed == ["abc123"]
        assert status["profile"]["uid"] == 315

    def test_login_and_restore_show_no_points_until_the_service_answers(self, fake):
        status = AAC.AcceleratorAccountClient().login("abc")
        assert status["earned_points"] == 0 and status["balance"] == 0
        assert status["badges"] == [] and status["purchases"] == []
        assert status["next_badge"] is None

    def test_username_falls_back_to_the_email_then_account(self, fake):
        fake.me = {"full_name": "", "email": "m@example.org", "uid": 1}
        assert AAC.AcceleratorAccountClient().restore()["profile"]["username"] \
            == "m@example.org"
        fake.me = {"uid": 1}
        assert AAC.AcceleratorAccountClient().restore()["profile"]["username"] \
            == "Account"

    def test_logout_forgets_the_login(self, fake):
        AAC.AcceleratorAccountClient().logout()
        assert fake.logouts == 1 and fake.logged_in is False


class TestErrors:
    @pytest.mark.parametrize("code", ["offline", "invalid_code", "not_logged_in",
                                      "session_expired"])
    def test_known_codes_pass_through_with_the_message(self, fake, code):
        fake.redeem_error = fake.AcceleratorAuthError("the reason", code)
        with pytest.raises(AccountError) as exc:
            AAC.AcceleratorAccountClient().login("x")
        assert exc.value.code == code and exc.value.message == "the reason"

    def test_anything_else_is_a_server_error(self, fake):
        fake.me_error = fake.AcceleratorAuthError("HTTP 500")
        with pytest.raises(AccountError) as exc:
            AAC.AcceleratorAccountClient().get_status()
        assert exc.value.code == "server_error"

    def test_a_failed_login_does_not_ask_who_i_am(self, fake):
        fake.redeem_error = fake.AcceleratorAuthError("bad", "invalid_code")
        fake.me_error = AssertionError("who_am_i must not be called")
        with pytest.raises(AccountError):
            AAC.AcceleratorAccountClient().login("x")


class TestStayLoggedIn:
    def test_without_it_close_drops_the_stored_login(self, fake):
        AAC.AcceleratorAccountClient(remember=False).close()
        assert fake.logouts == 1

    def test_with_it_close_keeps_the_login(self, fake):
        AAC.AcceleratorAccountClient(remember=True).close()
        assert fake.logouts == 0

    def test_switching_it_off_forgets_now(self, fake):
        AAC.AcceleratorAccountClient().set_remember(False)
        assert fake.logouts == 1

    def test_switching_it_on_forgets_nothing(self, fake):
        AAC.AcceleratorAccountClient(remember=False).set_remember(True)
        assert fake.logouts == 0


class TestNotBuiltYet:
    @pytest.mark.parametrize("op", ["get_leaderboard", "buy", "record_feature_run",
                                    "academy_complete_level", "claim_reward"])
    def test_other_operations_answer_not_available(self, fake, op):
        with pytest.raises(AccountError) as exc:
            getattr(AAC.AcceleratorAccountClient(), op)("anything", key=1)
        assert exc.value.code == "not_available"

    def test_private_names_are_not_operations(self, fake):
        with pytest.raises(AttributeError):
            AAC.AcceleratorAccountClient()._nothing


class FakeResponse:
    def __init__(self, code=200, body=None, text_only=False):
        self.status_code = code
        self._body = body
        self._text_only = text_only

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        if self._text_only:
            raise ValueError("not json")
        return self._body


class FakeRequests:
    class RequestException(Exception):
        pass

    class Timeout(RequestException):
        pass

    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def request(self, method, url, json=None, timeout=None, headers=None):
        self.calls.append((method, url, json, timeout, headers))
        if self.error:
            raise self.error
        return self.response


@pytest.fixture
def service(fake, monkeypatch):
    def install(response=None, error=None):
        f = FakeRequests(response, error)
        monkeypatch.setitem(sys.modules, "requests", f)
        return f
    return install


class TestPointsService:
    ME = {"uid": 315, "name": "M", "earned_points": 7, "balance": 7,
          "badges": [{"code": "breg", "name": "Breg", "points_required": 5}],
          "next_badge": {"code": "thames", "name": "Thames", "points_required": 15}}

    def test_get_status_adds_the_points_to_the_identity(self, service):
        f = service(FakeResponse(200, self.ME))
        status = AAC.AcceleratorAccountClient().get_status()
        assert status["profile"]["uid"] == 315 and status["earned_points"] == 7
        assert status["badges"][0]["code"] == "breg" and status["next_badge"]["code"] == "thames"
        method, url, _body, _timeout, headers = f.calls[0]
        assert (method, url) == ("GET", "https://points.example/me")
        assert headers["x-authorization"] == "access-token"

    def test_touch_activity_waits_for_a_sleeping_service(self, service):
        f = service(FakeResponse(200, self.ME))
        AAC.AcceleratorAccountClient().touch_activity()
        assert f.calls[0][3] == AAC._WAKE_TIMEOUT_S

    def test_award_run_sends_only_the_fingerprint_and_timesteps(self, service):
        f = service(FakeResponse(200, {"status": "awarded", "points_awarded": 1,
                                       "total_points": 8, "new_badges": []}))
        res = AAC.AcceleratorAccountClient().award_run("run-uid", {
            "settings_hash": "a" * 64, "timesteps": 365, "title": "secret"})
        assert res["status"] == "awarded" and res["total_points"] == 8
        method, url, body, timeout, _h = f.calls[0]
        assert (method, url.endswith("/claim")) == ("POST", True)
        assert body == {"settings_hash": "a" * 64, "timesteps": 365}
        assert timeout == AAC._WAKE_TIMEOUT_S

    @pytest.mark.parametrize("response,code", [
        (FakeResponse(401, {}), "session_expired"),
        (FakeResponse(429, {}), "rate_limited"),
        (FakeResponse(503, {}), "offline"),
        (FakeResponse(502, {}), "offline"),
        (FakeResponse(200, text_only=True), "offline"),          # the "waking up" page
        (FakeResponse(500, {"error": "x"}), "server_error"),
        (FakeResponse(200, [1, 2]), "server_error"),
    ])
    def test_service_answers_map_to_account_codes(self, service, response, code):
        service(response)
        with pytest.raises(AccountError) as exc:
            AAC.AcceleratorAccountClient().get_status()
        assert exc.value.code == code

    def test_unreachable_service_is_offline(self, service):
        service(error=FakeRequests.Timeout("slow"))
        with pytest.raises(AccountError) as exc:
            AAC.AcceleratorAccountClient().award_run("u", {"settings_hash": "a" * 64})
        assert exc.value.code == "offline"

    def test_service_switched_off(self, fake, monkeypatch):
        monkeypatch.setenv("CWATM_GUI_POINTS_URL", "")
        with pytest.raises(AccountError) as exc:
            AAC.AcceleratorAccountClient().award_run("u", {})
        assert exc.value.code == "not_available"

    def test_expired_accelerator_login_is_reported(self, service, fake):
        service(FakeResponse(200, self.ME))
        fake.get_access_token = lambda: (_ for _ in ()).throw(
            fake.AcceleratorAuthError("Session expired.", "session_expired"))
        with pytest.raises(AccountError) as exc:
            AAC.AcceleratorAccountClient().get_status()
        assert exc.value.code == "session_expired"
