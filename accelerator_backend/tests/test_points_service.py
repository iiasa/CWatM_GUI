"""event_store, identity and points_service - temp dirs, a fake identity check, and a
real HTTP round-trip on a local port (no Accelerator, no network)."""

import datetime
import io
import json
import os
import sys
import threading
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import event_store as ES
import identity as ID
import points_service as PS

RUN = "0123456789abcdef" * 4


def setup(n):
    return f"{n:064x}"


NOW = datetime.datetime(2026, 11, 30, 12, 0, tzinfo=datetime.timezone.utc)
TODAY = "2026-11-30"


@pytest.fixture
def store(tmp_path):
    return ES.EventStore(str(tmp_path))


def claim(n=1, timesteps=365):
    return {"settings_hash": setup(n), "timesteps": timesteps}


class TestEventStore:
    def test_a_run_is_written_once(self, store):
        assert store.write_run(7, RUN, TODAY, {"points": 1}) is True
        assert store.write_run(7, RUN, TODAY, {"points": 99}) is False      # never overwritten
        assert store.run_filenames(7) == [f"{TODAY}-{RUN}.json"]
        with open(os.path.join(store.root, "ledger", "7", "runs", f"{TODAY}-{RUN}.json")) as fh:
            assert json.load(fh) == {"points": 1}

    def test_unknown_user_has_nothing(self, store):
        assert store.run_filenames(5) == [] and store.badge_codes(5) == set()

    @pytest.mark.parametrize("uid", ["7", 0, -1, True, None, "../x"])
    def test_uid_must_be_a_positive_integer(self, store, uid):
        with pytest.raises(ValueError):
            store.run_filenames(uid)

    def test_badges(self, store):
        assert store.write_badge(7, {"code": "breg"}, "t") is True
        assert store.write_badge(7, {"code": "breg"}, "t2") is False
        assert store.badge_codes(7) == {"breg"}


class TestClaims:
    def test_awarded_then_same_settings(self, store):
        first = PS.handle_claim(store, 7, claim(1), lambda: NOW)
        assert first["status"] == "awarded" and first["total_points"] == 1
        again = PS.handle_claim(store, 7, claim(1), lambda: NOW)
        assert again["status"] == "same_settings" and again["total_points"] == 1
        tomorrow = NOW + datetime.timedelta(days=1)             # still the same setup
        assert PS.handle_claim(store, 7, claim(1), lambda: tomorrow)["status"] == "same_settings"

    def test_only_the_day_and_fingerprint_are_stored(self, store):
        PS.handle_claim(store, 7, claim(1), lambda: NOW)
        path = os.path.join(store.root, "ledger", "7", "runs", f"{TODAY}-{setup(1)}.json")
        with open(path) as fh:
            assert json.load(fh) == {"points": 1}

    def test_too_short_writes_nothing(self, store):
        res = PS.handle_claim(store, 7, claim(1, timesteps=5), lambda: NOW)
        assert res["status"] == "too_short" and store.run_filenames(7) == []

    def test_no_fingerprint(self, store):
        assert PS.handle_claim(store, 7, PS.clean_claim({}), lambda: NOW)["status"] == "no_settings_hash"

    def test_daily_cap_counts_today_only(self, store):
        for n in range(20):
            assert PS.handle_claim(store, 7, claim(n + 1), lambda: NOW)["status"] == "awarded"
        assert PS.handle_claim(store, 7, claim(99), lambda: NOW)["status"] == "daily_limit"
        tomorrow = NOW + datetime.timedelta(days=1)
        assert PS.handle_claim(store, 7, claim(99), lambda: tomorrow)["status"] == "awarded"

    def test_badge_at_five_points_once(self, store):
        results = [PS.handle_claim(store, 7, claim(n), lambda: NOW) for n in range(1, 8)]
        assert all(r["new_badges"] == [] for r in results[:4])
        assert [b["code"] for b in results[4]["new_badges"]] == ["breg"]
        assert results[5]["new_badges"] == [] and results[6]["new_badges"] == []
        assert store.badge_codes(7) == {"breg"}

    def test_users_are_separate(self, store):
        PS.handle_claim(store, 7, claim(1), lambda: NOW)
        assert PS.handle_claim(store, 8, claim(1), lambda: NOW)["status"] == "awarded"

    def test_status(self, store):
        for n in range(1, 6):
            PS.handle_claim(store, 7, claim(n), lambda: NOW)
        st = PS.status_of(store, 7)
        assert st["earned_points"] == 5 and st["balance"] == 5
        assert [b["code"] for b in st["badges"]] == ["breg"]
        assert st["next_badge"]["code"] == "thames"

    def test_clean_claim_drops_everything_else(self):
        body = {"settings_hash": RUN, "timesteps": "9", "kind": 3, "uid": 1, "points": 1000}
        assert PS.clean_claim(body) == {"settings_hash": RUN, "timesteps": None}


class TestIdentity:
    class _Resp:
        def __init__(self, body):
            self._b = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(self._b).encode()

    @pytest.fixture(autouse=True)
    def _clear(self):
        ID._cache.clear()

    def test_valid_token_is_cached(self, monkeypatch):
        calls = []

        def fake(req, timeout=None):
            calls.append(req.get_header("X-authorization"))
            return self._Resp({"uid": 7, "full_name": "A B", "email": "a@b.c"})
        monkeypatch.setattr(ID.urllib.request, "urlopen", fake)
        assert ID.verify("tok") == {"uid": 7, "name": "A B"}
        assert ID.verify("tok")["uid"] == 7
        assert calls == ["tok"]                                  # second call from the cache

    def test_cache_expires(self, monkeypatch):
        calls = []
        monkeypatch.setattr(ID.urllib.request, "urlopen",
                            lambda req, timeout=None: calls.append(1) or self._Resp({"uid": 7}))
        ID.verify("tok", now=lambda: 0)
        ID.verify("tok", now=lambda: ID.CACHE_SECONDS - 1)
        assert len(calls) == 1
        ID.verify("tok", now=lambda: ID.CACHE_SECONDS + 1)
        assert len(calls) == 2

    @pytest.mark.parametrize("code,expected", [(401, "unauthorized"), (403, "unauthorized"),
                                               (500, "unavailable")])
    def test_http_errors(self, monkeypatch, code, expected):
        def fake(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(b""))
        monkeypatch.setattr(ID.urllib.request, "urlopen", fake)
        with pytest.raises(ID.IdentityError) as exc:
            ID.verify("tok")
        assert exc.value.code == expected

    def test_unreachable(self, monkeypatch):
        def fake(req, timeout=None):
            raise urllib.error.URLError("down")
        monkeypatch.setattr(ID.urllib.request, "urlopen", fake)
        with pytest.raises(ID.IdentityError) as exc:
            ID.verify("tok")
        assert exc.value.code == "unavailable"

    @pytest.mark.parametrize("body", [{"uid": "7"}, {"uid": 0}, {"uid": True}, {}, []])
    def test_response_without_a_valid_uid_is_refused(self, monkeypatch, body):
        monkeypatch.setattr(ID.urllib.request, "urlopen",
                            lambda req, timeout=None: self._Resp(body))
        with pytest.raises(ID.IdentityError) as exc:
            ID.verify("tok")
        assert exc.value.code == "unauthorized"

    def test_no_token(self):
        for token in (None, "", 5):
            with pytest.raises(ID.IdentityError):
                ID.verify(token)


class TestHttp:
    """The real server on a local port, with a fake identity check."""

    USERS = {"tok7": {"uid": 7, "name": "Seven"}, "tok8": {"uid": 8, "name": "Eight"}}

    @pytest.fixture
    def base(self, store):
        def verify(token):
            if token in self.USERS:
                return self.USERS[token]
            raise ID.IdentityError("unauthorized" if token != "down" else "unavailable")
        server = PS.make_server(store, "127.0.0.1", 0, verify=verify, now=lambda: NOW)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        yield f"http://127.0.0.1:{server.server_address[1]}"
        server.shutdown()
        server.server_close()

    @staticmethod
    def call(url, token=None, body=None, bearer=False, raw=None):
        headers = {}
        if token:
            headers["Authorization" if bearer else "x-authorization"] = \
                ("Bearer " + token) if bearer else token
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_health_needs_no_token(self, base):
        assert self.call(base + "/health") == (200, {"ok": True})

    def test_claim_then_me(self, base):
        code, res = self.call(base + "/claim", "tok7", claim(1))
        assert code == 200 and res["status"] == "awarded" and res["total_points"] == 1
        code, me = self.call(base + "/me", "tok7")
        assert code == 200 and me["uid"] == 7 and me["earned_points"] == 1

    def test_bearer_token_also_works(self, base):
        assert self.call(base + "/me", "tok7", bearer=True)[0] == 200

    def test_identity_comes_from_the_token_not_the_body(self, base):
        body = {**claim(1), "uid": 8, "points": 500}
        self.call(base + "/claim", "tok7", body)
        assert self.call(base + "/me", "tok8")[1]["earned_points"] == 0
        assert self.call(base + "/me", "tok7")[1]["earned_points"] == 1

    def test_refused_token(self, base):
        assert self.call(base + "/claim", "nope", claim(1)) == (401, {"error": "unauthorized"})
        assert self.call(base + "/me") == (401, {"error": "unauthorized"})

    def test_accelerator_unreachable_is_503(self, base):
        assert self.call(base + "/me", "down") == (503, {"error": "identity_unavailable"})

    def test_bad_body(self, base):
        assert self.call(base + "/claim", "tok7", raw=b"not json")[0] == 400
        assert self.call(base + "/claim", "tok7", raw=b"[1]")[0] == 400

    def test_oversized_body(self, base):
        assert self.call(base + "/claim", "tok7", raw=b"x" * (PS.MAX_BODY_BYTES + 1))[0] == 413

    def test_unknown_path(self, base):
        assert self.call(base + "/nothing", "tok7")[0] == 404
