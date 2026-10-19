"""Where the CWatM account server lives (Supabase project URL + public key).

Only the project URL and the **anon / publishable** key belong here - both are public
by design (every client holds them; row level security decides what they may do).
The service-role / secret key must NEVER appear in the GUI - see supabase/README.md.

The environment variables ``CWATM_GUI_SUPABASE_URL`` / ``CWATM_GUI_SUPABASE_KEY``
override the built-in values, so a developer can point the GUI at the ``dev``
project without editing code.
"""

import os

# The CWatM account project (Supabase, EU / Frankfurt).
_PROJECT_REF = "heseqywpazkdvmnieuqn"
_DEFAULT_URL = f"https://{_PROJECT_REF}.supabase.co"
# Project Settings > API: the anon (legacy JWT) or publishable (sb_publishable_...)
# key. Empty = the account feature is off until it is filled in.
_DEFAULT_KEY = "sb_publishable_nN1YHaYvwk80HMo82aAS-Q_Q71ibQSl"


# The privacy notice a new account agrees to (documentation/CWatM_Account_Privacy.md).
# Sent with every sign-up and stored in the profile as the proof of consent - keep it
# equal to the "Version ..." line of that file (tests/test_account_privacy.py checks),
# and change both whenever the notice changes in a way that matters: every existing
# user is then shown the new notice at the next login and asked to agree again
# (privacy_consent_needed below; account_ui._on_privacy_consent).
PRIVACY_VERSION = "2026-10-19-draft6"      # draft6: proposed answers for IIASA, + outside the account
PRIVACY_DOC = "CWatM_Account_Privacy.md"
# The minimum age for an account (the notice's "Age" section; the Register tick box).
MIN_AGE = 16


def privacy_consent_needed(consent):
    """Must the logged-in user agree to the privacy notice again?

    ``consent`` is the server's answer to get_privacy_consent: {privacy_version,
    privacy_accepted_at}. True when the stored version is not PRIVACY_VERSION,
    including none at all (an account older than the consent record). False when
    there is no answer (``None``, e.g. a server without the function yet): an
    unknown state never locks anyone out - the next login asks again."""
    if not isinstance(consent, dict):
        return False
    return (consent.get("privacy_version") or None) != PRIVACY_VERSION


def supabase_url():
    return (os.environ.get("CWATM_GUI_SUPABASE_URL") or _DEFAULT_URL).rstrip("/")


def supabase_key():
    return os.environ.get("CWATM_GUI_SUPABASE_KEY") or _DEFAULT_KEY


def is_configured():
    """True when both the URL and the public key are known."""
    return bool(supabase_url() and supabase_key())


def functions_url(name):
    """URL of one of the project's Edge Functions."""
    return f"{supabase_url()}/functions/v1/{name}"


def keyring_entry():
    """(service, username) under which the refresh token is kept in the OS keyring.
    Keyed by the project URL, so a dev and a prod login never overwrite each other."""
    host = supabase_url().split("://", 1)[-1]
    return "CWatM_GUI", f"supabase:{host}"
