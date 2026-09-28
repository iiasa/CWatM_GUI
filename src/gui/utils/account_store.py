"""Remember the CWatM login between sessions - the refresh token in the OS keyring.

Only the **refresh token** is stored (a full Supabase session is larger than one
Windows Credential Manager entry may be). It lives in the Windows Credential
Manager / macOS Keychain / Linux Secret Service via ``keyring`` - never in QSettings
or a plain file. Supabase rotates the token on every refresh, so the client saves it
again after each one (``AccountClient._on_auth_event``).

No keyring backend (e.g. a Linux remote session without a Secret Service) is not an
error: the login simply is not remembered. Every function here swallows keyring
failures into gui.log and never raises.
"""

from src.gui.utils.account_config import keyring_entry
from src.gui.utils.gui_log import get_logger

log = get_logger("account_store")


def load_refresh_token():
    try:
        import keyring
        service, user = keyring_entry()
        return keyring.get_password(service, user) or None
    except Exception:
        log.info("keyring unavailable - login not remembered", exc_info=True)
        return None


def save_refresh_token(token):
    if not token:
        clear_refresh_token()
        return False
    try:
        import keyring
        service, user = keyring_entry()
        keyring.set_password(service, user, token)
        return True
    except Exception:
        log.info("could not store the refresh token in the keyring", exc_info=True)
        return False


def clear_refresh_token():
    try:
        import keyring
        from keyring.errors import PasswordDeleteError
        service, user = keyring_entry()
        try:
            keyring.delete_password(service, user)
        except PasswordDeleteError:
            log.debug("no stored refresh token to delete")
    except Exception:
        log.info("could not clear the refresh token from the keyring", exc_info=True)
