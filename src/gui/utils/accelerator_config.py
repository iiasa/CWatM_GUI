"""Where IIASA's Accelerator platform lives - server URLs, mirroring the
Tauri client's own ``tauri-app/src/lib/accelerator/config.ts`` (same
defaults, confirmed against the live OpenAPI spec at ``{SERVER_URL}/api/docs``).

Kept separate from ``account_config.py`` (the unrelated Supabase-backed
CWatM account) on purpose - two different identity providers, two
different keyring entries, never conflated.
"""

SERVER_URL = "https://accelerator.iiasa.ac.at"
WEBCLI_URL = "https://accelerator.iiasa.ac.at"

# Where a user gets their device-flow authorization code (opened in a real browser).
AUTH_CODE_URL = f"{WEBCLI_URL}/acli-auth-code"

# The CWatM points service (an Accelerator interactive routine, accelerator_backend/):
# https://<TUNNEL_NAME>.wkube.iiasa.ac.at - the name is chosen when the routine is
# dispatched. CWATM_GUI_POINTS_URL overrides it (a dev instance); empty = points off.
_DEFAULT_POINTS_URL = "https://cwatm-points.wkube.iiasa.ac.at"

API_BASE = f"{SERVER_URL}/api/v1"
OAUTH_BASE = f"{API_BASE}/oauth/device"
ATERM_BASE = f"{API_BASE}/aterm-cli"


def keyring_entry():
    """(service, username) under which the Accelerator refresh token is kept
    in the OS keyring. Keyed by the server host, same convention as
    account_config.keyring_entry (a dev/prod split would never overwrite
    each other), under a distinct username prefix from the Supabase entry."""
    host = SERVER_URL.split("://", 1)[-1]
    return "CWatM_GUI", f"accelerator:{host}"


def points_service_url():
    """Base URL of the points service, or "" when switched off."""
    import os
    return (os.environ.get("CWATM_GUI_POINTS_URL", _DEFAULT_POINTS_URL) or "").rstrip("/")
