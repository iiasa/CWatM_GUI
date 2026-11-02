"""Remember the Accelerator login between sessions - the refresh token in the
OS keyring. Same pattern as ``account_store.py`` (the unrelated Supabase
CWatM account), just under ``accelerator_config``'s own keyring entry so the
two logins never collide.

No keyring backend (e.g. a Linux remote session without a Secret Service) is
not an error: the login simply is not remembered. Every function here
swallows keyring failures into gui.log and never raises.
"""

from src.gui.utils.accelerator_config import keyring_entry
from src.gui.utils.gui_log import get_logger

log = get_logger("accelerator_store")


def load_refresh_token():
    try:
        import keyring
        service, user = keyring_entry()
        return keyring.get_password(service, user) or None
    except Exception:
        log.info("keyring unavailable - Accelerator login not remembered", exc_info=True)
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
        log.info("could not store the Accelerator refresh token in the keyring", exc_info=True)
        return False


def clear_refresh_token():
    try:
        import keyring
        from keyring.errors import PasswordDeleteError
        service, user = keyring_entry()
        try:
            keyring.delete_password(service, user)
        except PasswordDeleteError:
            log.debug("no stored Accelerator refresh token to delete")
    except Exception:
        log.info("could not clear the Accelerator refresh token from the keyring", exc_info=True)
