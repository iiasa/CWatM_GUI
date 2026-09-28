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
# and change both whenever the notice changes in a way that matters.
PRIVACY_VERSION = "2026-09-28-draft"
PRIVACY_DOC = "CWatM_Account_Privacy.md"


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
