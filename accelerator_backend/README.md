# Accelerator-backed points/badges ledger (in progress)

Replaces the Supabase-backed CWatM account (`supabase/`) entirely - login
moves to IIASA's Accelerator platform, and this becomes the new backend for
points/badges/shop/leaderboard/academy progress. Everything resets: no
migration of existing Supabase accounts (decided explicitly - a clean
cutover).

**Future direction (not scoped or built yet)**: once real accounts exist,
the same event-log design extends naturally to broader usage data beyond
points - anything that helps understand or improve the model, not just
gamification. Respecting the project's existing privacy stance matters
here: `CWatM_Account_Privacy.md`/`account_config.PRIVACY_VERSION` already
spell out exactly what's collected today, and any new category of data
would need that notice updated and consent asked for, not just quietly
added. Revisit once the login/points migration itself is done.

## Current design: the points service (interactive routine)

Agreed with the Accelerator team (2026-11-30). A small HTTP service runs as an Accelerator
**interactive routine** in `cwatm-points-ledger`; the desktop GUI calls it with the user's
Accelerator access token. Anyone with the app can use it - no project membership, no stored
service login (an interactive routine is reachable by anyone with its address, and a plain
API call wakes it when it sleeps).

- `identity.py` - the caller is identified **only** by the token (`GET /user/me`, read-only,
  cached 5 min). Nothing identity-like in a request body is trusted.
- `points_service.py` - `GET /health`, `GET /me` (points, badges, next badge),
  `POST /claim` (`settings_hash`, `timesteps`). Rules: `award_run.py` + `badges.py`.
- `event_store.py` - one tiny immutable file per event in the routine's read-write folder
  (`ledger/<uid>/runs/<date>-<settings_hash>.json`, `ledger/<uid>/badges/<code>.json`), created
  once, never overwritten; only filenames are ever read. Accelerator saves the folder when
  the app stops (also after a crash) and shows it again after the next wake.
- The service never dispatches jobs and never uses the platform's built-in service token
  (which cannot be restricted).
- `service.Dockerfile` - standard library only. Start the routine with
  `"interactive_socket": "0.0.0.0:8000"`, `"WDRV_ACCESS": "read-write"` (and a fixed
  `TUNNEL_NAME` so the address stays the same). A project admin must enable interactive
  routines first. Not build-tested yet (no Docker daemon where it was written); the same
  file set was run in an isolated folder.
- A sleeping app needs about 1-2 minutes to wake; a job ends after 7 days at the latest -
  the GUI's offline queue retries.

**Rules** (the old server's final `award_run`): a run's identity is the one-way fingerprint of
its model setup - one point per distinct setup (`same_settings` otherwise), at least 30
timesteps, at most 20 counted runs per UTC day. Stored per point: only the day and the
fingerprint (the file name). Badges follow the earned points (`badges.py`).

**Desktop GUI**: `accelerator_account_client.py` logs in through Accelerator and calls this
service (`award_run`, `get_status`, `touch_activity`; address from
`accelerator_config.points_service_url()`, override `CWATM_GUI_POINTS_URL`, default
`https://cwatm-points.wkube.iiasa.ac.at` - the name must match the `TUNNEL_NAME` used when
dispatching). Not built yet: shop, leaderboard, academy progress, feature badges, run
locations, Field Test record. The privacy notice (`documentation/CWatM_Account_Privacy.md`)
still describes the old Supabase account and must be rewritten before release.

The earlier GitHub-Actions validator, job-dispatch writer and manual probes were removed:
users cannot read or write the ledger project, and a refresh token is single-use.
