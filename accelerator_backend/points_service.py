"""The CWatM points service - runs as an Accelerator *interactive routine*.

A small HTTP API the desktop GUI calls with the user's Accelerator access token:

    GET  /health            -> {"ok": true}
    GET  /me                -> the caller's points, badges and next badge
    POST /claim             -> {"settings_hash", "timesteps"} : "this run completed"

The caller is identified **only** by the token (``identity.verify`` -> ``/user/me``);
anything identity-like in a request body is ignored. The rules are ``award_run`` and
``badges`` (ports of the old server functions); every point and badge becomes one
immutable file via ``event_store``. Nothing here dispatches jobs or uses the platform's
built-in service token.

Environment: ``LEDGER_DIR`` (the read-write folder, default ``/mnt/wdrv``), ``PORT``
(default 8000). The interactive routine is started with
``"interactive_socket": "0.0.0.0:8000"`` and ``"WDRV_ACCESS": "read-write"``.
"""

import datetime
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import award_run
import badges
import event_store
import identity
import ledger_paths

MAX_BODY_BYTES = 16 * 1024


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def run_state(filenames, today):
    """(recorded setup fingerprints, runs recorded today) from one folder listing."""
    recorded, today_count = set(), 0
    for name in filenames:
        parsed = ledger_paths.parse_run_filename(name)
        if parsed:
            recorded.add(parsed[1])
            today_count += parsed[0] == today
    return recorded, today_count


def status_of(store, uid, points=None):
    """What the GUI shows: points (= recorded runs), badges held, the next badge."""
    if points is None:
        points = len(run_state(store.run_filenames(uid), "")[0])
    held = store.badge_codes(uid)
    held_badges = [{"code": c, "name": n, "points_required": r}
                   for c, n, r in badges.RIVER_BADGES if c in held]
    return {"earned_points": points, "balance": points,
            "badges": held_badges, "next_badge": badges.next_badge(points)}


def handle_claim(store, uid, claim, now=_utc_now):
    """Decide and record one claim; returns the answer for the GUI."""
    moment = now()
    today = moment.strftime("%Y-%m-%d")
    recorded, today_count = run_state(store.run_filenames(uid), today)
    result = award_run.decide(claim, recorded, today_count)
    points = len(recorded)
    if result["status"] == "awarded":
        # minimal data: the file name (day + fingerprint) is the record
        if store.write_run(uid, claim["settings_hash"], today, {"points": result["points_awarded"]}):
            points += 1
            result["new_badges"] = []
            for badge in badges.new_badges(points, store.badge_codes(uid)):
                if store.write_badge(uid, badge, moment.isoformat()):
                    result["new_badges"].append(badge)
        else:                                   # lost a race with an identical claim
            result = {"status": "same_settings"}
    result["total_points"] = points
    return result


def clean_claim(body):
    """The claim fields from a request body (types enforced; anything else dropped)."""
    timesteps = body.get("timesteps")
    return {"settings_hash": body.get("settings_hash")
            if isinstance(body.get("settings_hash"), str) else None,
            "timesteps": timesteps if isinstance(timesteps, int)
            and not isinstance(timesteps, bool) else None}


def make_server(store, host="0.0.0.0", port=8000, verify=identity.verify, now=_utc_now):
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        server_version = "CWatMPoints/1"

        def log_message(self, fmt, *args):                  # no tokens, no bodies
            print(f"{self.command} {self.path.split('?')[0]} -> {args[1] if len(args) > 1 else ''}",
                  flush=True)

        def _send(self, code, payload):
            data = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _caller(self):
            token = self.headers.get("x-authorization")
            auth = self.headers.get("Authorization", "")
            if not token and auth.lower().startswith("bearer "):
                token = auth[7:].strip()
            try:
                return verify(token)
            except identity.IdentityError as exc:
                if exc.code == "unauthorized":
                    self._send(401, {"error": "unauthorized"})
                else:
                    self._send(503, {"error": "identity_unavailable"})
                return None

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/health":
                return self._send(200, {"ok": True})
            if path == "/me":
                who = self._caller()
                if who:
                    with lock:
                        body = status_of(store, who["uid"])
                    self._send(200, {"uid": who["uid"], "name": who["name"], **body})
                return None
            return self._send(404, {"error": "not_found"})

        def do_POST(self):
            if self.path.split("?")[0] != "/claim":
                return self._send(404, {"error": "not_found"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._send(400, {"error": "bad_request"})
            if length > MAX_BODY_BYTES:
                return self._send(413, {"error": "too_large"})
            who = self._caller()
            if not who:
                return None
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("not an object")
            except ValueError:
                return self._send(400, {"error": "bad_request"})
            with lock:
                result = handle_claim(store, who["uid"], clean_claim(body), now)
            return self._send(200, result)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main():
    root = os.environ.get("LEDGER_DIR", "/mnt/wdrv")
    port = int(os.environ.get("PORT", "8000"))
    server = make_server(event_store.EventStore(root), "0.0.0.0", port)
    print(f"CWatM points service on :{port}, data in {root}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
