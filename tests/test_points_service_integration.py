"""The GUI's Accelerator client against the real points service on a local port - the
contract between them (request fields, answer shape, GUI status keys). Only the
Accelerator identity check is faked."""

import datetime
import os
import sys
import threading

import pytest

pytest.importorskip("requests")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "accelerator_backend"))

import event_store  # noqa: E402
import points_service  # noqa: E402

from src.gui.utils import accelerator_account_client as AAC  # noqa: E402
from src.gui.utils.account_client import AccountError  # noqa: E402

H = "c" * 64


class _Auth:
    AcceleratorAuthError = AAC.auth.AcceleratorAuthError

    def get_access_token(self):
        return "tok"

    def who_am_i(self):
        return {"full_name": "Test User", "email": "t@example.org", "uid": 42, "roles": []}


@pytest.fixture
def client(tmp_path, monkeypatch):
    now = datetime.datetime(2026, 11, 30, 9, 0, tzinfo=datetime.timezone.utc)
    server = points_service.make_server(
        event_store.EventStore(str(tmp_path)), "127.0.0.1", 0,
        verify=lambda token: {"uid": 42, "name": "Test User"} if token == "tok"
        else (_ for _ in ()).throw(points_service.identity.IdentityError("unauthorized")),
        now=lambda: now)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("CWATM_GUI_POINTS_URL", f"http://127.0.0.1:{server.server_address[1]}")
    monkeypatch.setattr(AAC, "auth", _Auth())
    yield AAC.AcceleratorAccountClient()
    server.shutdown()
    server.server_close()


def test_a_run_earns_a_point_once_per_setup(client):
    first = client.award_run("run-uid", {"settings_hash": H, "timesteps": 365})
    assert first["status"] == "awarded" and first["total_points"] == 1
    again = client.award_run("other-run-uid", {"settings_hash": H, "timesteps": 365})
    assert again["status"] == "same_settings"


def test_the_status_shows_the_points_and_the_next_badge(client):
    for n in range(5):
        client.award_run("u", {"settings_hash": f"{n:064x}", "timesteps": 365})
    status = client.get_status()
    assert status["earned_points"] == 5 and status["balance"] == 5
    assert [b["code"] for b in status["badges"]] == ["breg"]
    assert status["next_badge"]["code"] == "thames"
    assert status["profile"]["username"] == "Test User"


@pytest.mark.qt          # imports account_ui
def test_every_refusal_is_a_status_the_gui_knows(client):
    from src.gui.components.account_ui import _AWARD_FINAL
    results = [client.award_run("u", {"timesteps": 365}),
               client.award_run("u", {"settings_hash": H, "timesteps": 3})]
    assert {r["status"] for r in results} == {"no_settings_hash", "too_short"}
    assert {r["status"] for r in results} <= _AWARD_FINAL


def test_a_refused_token_is_a_session_problem(client, monkeypatch):
    class _Bad(_Auth):
        def get_access_token(self):
            return "wrong"
    monkeypatch.setattr(AAC, "auth", _Bad())
    with pytest.raises(AccountError) as exc:
        client.get_status()
    assert exc.value.code == "session_expired"
