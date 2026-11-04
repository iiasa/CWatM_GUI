"""One-off manual sanity check for accelerator_auth.py's device-flow login -
not part of the test suite (needs a real browser + a real Accelerator
account), not CI-related. Run it, follow the prompts, then delete this file
once the login is confirmed working.

Usage:  python test_accelerator_login.py
"""

import sys
import webbrowser

sys.path.insert(0, ".")

from src.gui.utils import accelerator_auth as auth
from src.gui.utils import accelerator_config as config


def main():
    print(f"Opening {config.AUTH_CODE_URL} in your browser...")
    print("(log into Accelerator there if asked, then copy the code it shows you)")
    webbrowser.open(config.AUTH_CODE_URL)

    code = input("Paste the code here: ").strip()

    print("Exchanging the code for a refresh token...")
    auth.redeem_device_code(code)
    print("Logged in - refresh token stored in the OS keyring.")

    print("Fetching an access token...")
    access_token = auth.get_access_token()
    print(f"Got an access token ({len(access_token)} chars).")

    print("Calling who_am_i()...")
    identity = auth.who_am_i()
    print(f"Logged in as: {identity}")

    print("\nCalling get_access_token() again (should be instant - cache hit, no network call)...")
    auth.get_access_token()
    print("OK.")


if __name__ == "__main__":
    try:
        main()
    except auth.AcceleratorAuthError as exc:
        print(f"\nFAILED: {exc}")
        sys.exit(1)
