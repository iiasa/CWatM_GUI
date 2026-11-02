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
