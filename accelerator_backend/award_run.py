"""Decides whether a claimed CWatM run earns a point - a Python port of
``supabase/migrations/20260928120100_gamification_functions.sql``'s
``award_run()``, for the Accelerator-backed replacement (see
``accelerator_backend/README.md`` for how this fits into the validator).

Pure logic only: no Accelerator API calls, no file I/O. The caller (the
GitHub Actions validator, not yet built) reads the claim and the user's
existing ledger state, calls ``decide()``, and acts on the result -
writing the event file at ``ledger/<uid>/runs/<run_uid>.json`` when the
status is ``"awarded"``.

Deliberately NOT ported: ``award_run()``'s own email-confirmation check
(no equivalent concept once Accelerator is the identity provider - an
Accelerator login already implies a real, usable account) and its
``pg_advisory_xact_lock`` (Postgres-specific concurrency control; a
GitHub Actions workflow run is not expected to process the same user's
claims concurrently with itself, so this is not a gap worth closing
speculatively - revisit if it ever is one).

Point value and limits mirror the SQL function's own inline defaults
(``_game_int('points_per_run', 1)`` etc.) - the old system allowed a
server-side ``game_config`` table to override them without a GUI update;
no equivalent exists here yet, so these are plain constants for now.
"""

import re

POINTS_PER_RUN = 1
MIN_TIMESTEPS = 30
DAILY_RUN_CAP = 20

_RUN_UID_RE = re.compile(r"^[0-9a-f]{32}$")


def decide(claim, already_recorded_run_uids, runs_in_last_24h):
    """``claim`` is {run_uid, timesteps, kind} (kind one of "run"/"hidden"/"batch",
    or None). ``already_recorded_run_uids`` is the set of run_uid values this user
    already has an event file for (ledger/<uid>/runs/*.json's filenames, without
    the .json). ``runs_in_last_24h`` is how many of this user's existing "run"
    events were recorded in the last 24 hours (the caller computes this from
    each event file's own stored timestamp, same as the SQL's created_at check).

    Returns the same status vocabulary as award_run(): awarded | duplicate |
    too_short | daily_limit | invalid_run_uid. On "awarded", the result also
    carries the event dict ready to write to the ledger."""
    run_uid = claim.get("run_uid")
    if not run_uid or not _RUN_UID_RE.match(run_uid):
        return {"status": "invalid_run_uid"}

    if run_uid in already_recorded_run_uids:
        return {"status": "duplicate"}

    timesteps = claim.get("timesteps") or 0
    if MIN_TIMESTEPS > 0 and timesteps < MIN_TIMESTEPS:
        return {"status": "too_short", "min_timesteps": MIN_TIMESTEPS}

    if DAILY_RUN_CAP > 0 and runs_in_last_24h >= DAILY_RUN_CAP:
        return {"status": "daily_limit", "daily_run_cap": DAILY_RUN_CAP}

    kind = claim.get("kind")
    if kind not in ("run", "hidden", "batch"):
        kind = None

    return {
        "status": "awarded",
        "points_awarded": POINTS_PER_RUN,
        "event": {
            "source": "run",
            "source_ref": run_uid,
            "points": POINTS_PER_RUN,
            "kind": kind,
            "timesteps": claim.get("timesteps"),
        },
    }
