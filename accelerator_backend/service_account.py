"""The validator's own Accelerator identity.

Exchanges a refresh token (from the ``ACCELERATOR_VALIDATOR_REFRESH_TOKEN``
environment variable - a GitHub Actions secret, never checked in) for a
short-lived access token. No keyring, no persistence beyond one process -
unlike ``src/gui/utils/accelerator_auth.py`` (the desktop GUI's own login,
a different identity entirely, kept across sessions in the OS keyring): a
GitHub Actions run is a fresh container every time, so there is nothing to
persist, and the secret itself is Actions' job, not ours.

This is a dedicated Accelerator account created for the validator alone
(collaborator with write access to the ledger project only - never the
same account as any human user's own login), so its credential can be
handed to CI without granting CI access to anyone's personal data.
"""

import os

from config import OAUTH_BASE

REFRESH_TOKEN_ENV_VAR = "ACCELERATOR_VALIDATOR_REFRESH_TOKEN"
_REQUEST_TIMEOUT_SECONDS = 15


class ServiceAccountAuthError(Exception):
    pass


def get_access_token():
    import requests

    refresh_token = os.environ.get(REFRESH_TOKEN_ENV_VAR)
    if not refresh_token:
        raise ServiceAccountAuthError(f"{REFRESH_TOKEN_ENV_VAR} is not set.")

    try:
        res = requests.post(
            f"{OAUTH_BASE}/access-token/",
            json={"refresh_token": refresh_token},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise ServiceAccountAuthError("Could not reach Accelerator.") from exc

    if not res.ok:
        raise ServiceAccountAuthError(f"Could not get an access token (HTTP {res.status_code}).")
    return res.json()["access_token"]
