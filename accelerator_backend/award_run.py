"""Decides whether a claimed CWatM run earns a point - the final rules of the old
server's ``award_run`` (``supabase/migrations/20261001150000_minimal_point_data.sql``).

Pure logic, no I/O. A run's identity is the one-way **fingerprint of its model setup**
(``settings_hash``, 64 hex chars): one point per distinct setup, so re-running the same
settings earns nothing. Order of the checks, and the status vocabulary, are the old
server's: ``no_settings_hash`` -> ``too_short`` -> ``same_settings`` -> ``daily_limit`` ->
``awarded``. Not ported: the email-confirmation check (Accelerator is the identity
provider) and the advisory lock (the service serialises claims itself).
"""

import re

POINTS_PER_RUN = 1
MIN_TIMESTEPS = 30
DAILY_RUN_CAP = 20

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def decide(claim, recorded_hashes, runs_today):
    """``claim`` = {settings_hash, timesteps}; ``recorded_hashes`` = the fingerprints this
    user already has a point for; ``runs_today`` = counted runs recorded today (UTC)."""
    settings_hash = claim.get("settings_hash")
    if not isinstance(settings_hash, str) or not _HASH_RE.match(settings_hash):
        return {"status": "no_settings_hash"}

    timesteps = claim.get("timesteps") or 0
    if MIN_TIMESTEPS > 0 and timesteps < MIN_TIMESTEPS:
        return {"status": "too_short", "min_timesteps": MIN_TIMESTEPS}

    if settings_hash in recorded_hashes:
        return {"status": "same_settings"}

    if DAILY_RUN_CAP > 0 and runs_today >= DAILY_RUN_CAP:
        return {"status": "daily_limit", "daily_run_cap": DAILY_RUN_CAP}

    return {"status": "awarded", "points_awarded": POINTS_PER_RUN}
