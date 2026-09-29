"""``AccountWorker`` - a long-lived QThread that runs every CWatM account request.

Login, registration, points etc. are network calls of up to a few seconds, so they
never run on the GUI thread (same pattern as ``NotebookLMWorker``). The UI calls
``submit(op, *args)`` and gets the answer through queued signals:

    succeeded(op, result)       result = the AccountClient method's return value
    failed(op, code, message)   code = AccountError.code, message = for the user
    busy(bool)                  a request is in flight

``op`` is the name of an ``AccountClient`` method (``OPS``). The client - and with
it the supabase import - is created lazily on the first request, on this thread,
so creating the worker costs nothing at startup. Requests run one at a time in the
order submitted. Arguments are never logged (they hold passwords).
"""

import queue

from PySide6.QtCore import QThread, Signal

from src.gui.utils.gui_log import get_logger

log = get_logger("account_worker")

OPS = frozenset({
    "restore", "login", "logout",
    "username_available", "register", "confirm_signup", "resend_confirmation",
    "request_password_reset", "reset_password",
    "get_status", "update_profile", "award_run", "get_leaderboard", "get_badges",
    "export_data", "delete_account", "set_remember", "record_location",
    "get_run_locations", "get_user_locations",
    "academy_complete_level", "academy_reset",
})


class AccountWorker(QThread):
    succeeded = Signal(str, object)
    failed = Signal(str, str, str)
    busy = Signal(bool)

    def __init__(self, remember=True, parent=None):
        super().__init__(parent)
        self._remember = remember
        self._queue = queue.Queue()
        self._client = None

    # ---- called from the GUI thread -------------------------------------------
    def submit(self, op, *args, **kwargs):
        """Queue one request (returns immediately)."""
        if op not in OPS:
            raise ValueError(f"unknown account operation: {op}")
        self._queue.put((op, args, kwargs))

    def stop(self):
        """Finish the queued requests, then close the client and end the thread."""
        self._queue.put(None)

    # ---- runs on the worker thread --------------------------------------------
    def run(self):
        while True:
            item = self._queue.get()
            if item is None:
                break
            op, args, kwargs = item
            self.busy.emit(True)
            try:
                if self._client is None:
                    from src.gui.utils.account_client import AccountClient
                    self._client = AccountClient(remember=self._remember)
                result = getattr(self._client, op)(*args, **kwargs)
                self.succeeded.emit(op, result)
            except Exception as e:  # noqa: BLE001 - surfaced to the UI, never crash
                # account_client imports only light modules at its top (supabase is
                # imported inside AccountClient), so this import cannot fail.
                from src.gui.utils.account_client import translate_error
                err = translate_error(e)
                if err.code in ("offline", "server_error"):
                    log.warning("account %s failed: %s (%s)", op, err.code,
                                err.detail, exc_info=err.code == "server_error")
                else:
                    log.info("account %s: %s", op, err.code)
                self.failed.emit(op, err.code, err.message)
            finally:
                self.busy.emit(False)
        if self._client is not None:
            self._client.close()
            self._client = None
