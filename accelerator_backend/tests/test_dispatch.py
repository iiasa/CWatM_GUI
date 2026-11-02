"""dispatch.py - the write-job command builder (pure) and the dispatch call
(mocked network, same fake-module-injection pattern test_accelerator_auth.py
uses in src/gui/'s own test suite)."""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import dispatch as D


class TestShellDoubleQuote:
    def test_escapes_backslash_and_quote(self):
        assert D.shell_double_quote('a\\b"c') == '"a\\\\b\\"c"'

    def test_leaves_real_newlines_untouched(self):
        quoted = D.shell_double_quote("line1\nline2")
        assert quoted == '"line1\nline2"'
        assert "\\n" not in quoted


class TestBuildWriteCommand:
    def test_embeds_the_path_and_content(self):
        command = D.build_write_command("ledger/42/runs/abc.json", '{"points": 1}')
        assert command.startswith("python -c ")
        assert "/mnt/wdrv/ledger/42/runs/abc.json" in command
        assert "points" in command and "@@LEDGER_WRITE:True@@" in command
        # Exact escaping of the content itself is proven by the subprocess
        # round-trip test below, not by guessing the literal escaped form here.

    def test_round_trips_through_an_actual_shell_and_python(self):
        # The real proof: build the command, write it to a .sh script (so a
        # real shell does the outer-quote parsing, same uncertainty jobs.ts's
        # own comment flags about the Accelerator build server), run it
        # against a temp file standing in for /mnt/wdrv, and check the
        # written content matches exactly - including a real embedded
        # newline and a quote character in the content, the two cases that
        # actually broke the TypeScript version before shellDoubleQuote was
        # fixed there.
        content = 'line one\nline two with a "quote" and a \\backslash\\'
        with tempfile.TemporaryDirectory() as tmp:
            mnt_wdrv = os.path.join(tmp, "mnt_wdrv")
            relative_path = "ledger/test/event.json"
            command = D.build_write_command(relative_path, content)
            # Redirect /mnt/wdrv to our temp dir without changing the command
            # string itself - sed the one occurrence of the absolute prefix.
            patched = command.replace("/mnt/wdrv/", mnt_wdrv.replace("\\", "\\\\") + "/")
            script_path = os.path.join(tmp, "run.sh")
            with open(script_path, "w") as f:
                f.write("#!/bin/sh\n" + patched + "\n")
            result = subprocess.run(["sh", script_path], capture_output=True, text=True)
            assert "@@LEDGER_WRITE:True@@" in result.stdout, result.stdout + result.stderr
            written_path = os.path.join(mnt_wdrv, relative_path)
            with open(written_path) as f:
                assert f.read() == content


class TestBuildDispatchPayload:
    def test_required_fields_present_for_wkube(self):
        payload = D.build_dispatch_payload("write event", "ledger/42/runs/abc.json", "{}")
        assert payload["execute_cluster"] == "WKUBE"
        assert payload["job_kwargs"]["repo_url"] == "https://github.com/iiasa/CWatM_GUI"
        assert payload["job_kwargs"]["repo_branch"] == "cwatm-docker-image"
        assert payload["timeout"] == D.DEFAULT_TIMEOUT_SECONDS

    def test_timeout_is_small_not_the_cwatm_run_default(self):
        payload = D.build_dispatch_payload("x", "p", "c")
        assert payload["timeout"] < 3600


class _FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body
        self.text = str(body)

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._body


class _FakeRequests:
    RequestException = Exception

    def __init__(self, response):
        self._response = response
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json, headers))
        return self._response


class TestDispatchWriteJob:
    def test_sends_the_payload_with_the_service_account_token(self, monkeypatch):
        fake = _FakeRequests(_FakeResponse(200, {"job_id": 12345}))
        monkeypatch.setitem(sys.modules, "requests", fake)
        monkeypatch.setattr(D.service_account, "get_access_token", lambda: "sa-token")

        job_id = D.dispatch_write_job("cwatm-points-ledger", "write event", "ledger/42/runs/abc.json", "{}")

        assert job_id == 12345
        url, body, headers = fake.calls[0]
        assert url.endswith("/cwatm-points-ledger/jobs/dispatch/")
        assert headers["x-authorization"] == "sa-token"
        assert body["job_kwargs"]["command"].startswith("python -c")

    def test_dispatch_failure_raises(self, monkeypatch):
        fake = _FakeRequests(_FakeResponse(500, "server error"))
        monkeypatch.setitem(sys.modules, "requests", fake)
        monkeypatch.setattr(D.service_account, "get_access_token", lambda: "sa-token")

        try:
            D.dispatch_write_job("cwatm-points-ledger", "x", "p", "c")
            assert False, "expected RuntimeError"
        except RuntimeError as exc:
            assert "500" in str(exc)
