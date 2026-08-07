"""``NotebookLMWorker`` - a long-lived QThread that talks to NotebookLM.

Network/automation calls block for seconds, so all ``notebooklm`` work lives on
this worker and the UI talks to it only through signals (queued connections), the
same pattern as ``CWatMWorker``. The wrapper (which owns the async client + its
event loop) is created lazily inside ``run()`` on the first question, so opening
the window stays instant.

Questions are handed off through a ``queue.Queue`` (``ask()`` enqueues; ``run()``
loops ``queue.get()``); ``stop()`` enqueues a ``None`` sentinel. Everything raised
inside ``run()`` is caught, logged and surfaced as ``error(str)`` - never a crash.
"""

import queue

from PySide6.QtCore import QThread, Signal

from src.gui.utils.gui_log import get_logger

log = get_logger("notebooklm_worker")

# Sentinel queued by warm(): connect the client in the background without asking a
# question, so the first real question skips the connect + notebook-resolve cost.
_WARM = object()


class NotebookLMWorker(QThread):
    status = Signal(str)          # progress notes ("Connecting…", "Thinking…")
    reply = Signal(str, str)      # (question, answer)
    error = Signal(str)           # friendly error message
    busy = Signal(bool)           # drives Send enable/disable + "thinking…" hint

    def __init__(self, notebook_id=None, profile=None, response_length=None,
                 parent=None):
        super().__init__(parent)
        self._notebook_id = notebook_id
        self._profile = profile
        self._response_length = response_length   # "short"/"medium"/"long" or None
        self._queue = queue.Queue()
        self._client = None
        self._stop = False

    # ---- called from the GUI thread -----------------------------------------
    def ask(self, question):
        """Enqueue a question (returns immediately)."""
        self._queue.put(question)

    def warm(self):
        """Pre-connect the client in the background (no question). Call once the
        session is confirmed valid so the first real question doesn't pay the
        connect + notebooks.list + configure round-trips."""
        self._queue.put(_WARM)

    def set_response_length(self, key):
        """Change the desired answer length; applied before the next question
        (the run loop pushes it to the client on the worker thread)."""
        self._response_length = key

    def stop(self):
        """Ask the worker to finish and close the client."""
        self._stop = True
        # If a question is in flight, cancel it so run() unblocks promptly.
        self.cancel()
        self._queue.put(None)

    def cancel(self):
        """Stop the in-flight question (Stop thinking) without closing the worker.
        Safe from the GUI thread - the client cancels on its own loop."""
        c = self._client
        if c is not None:
            try:
                c.cancel()
            except Exception:
                log.debug("cancel failed", exc_info=True)

    # ---- runs on the worker thread ------------------------------------------
    def run(self):
        while not self._stop:
            item = self._queue.get()
            if item is None:
                break
            if item is _WARM:
                # Background connect only - no busy() (Send stays live) and a
                # warm failure is quiet: the real ask will surface any error.
                if self._client is None and not self._stop:
                    try:
                        self.status.emit("Connecting to NotebookLM…")
                        self._client = self._make_client()
                        self.status.emit("Ready.")
                    except Exception:  # noqa: BLE001
                        log.debug("NotebookLM warm-up failed", exc_info=True)
                continue
            question = item
            try:
                self.busy.emit(True)
                if self._client is None:
                    self.status.emit("Connecting to NotebookLM…")
                    self._client = self._make_client()
                    self.status.emit("Connected.")
                # Apply the current Short/Medium/Long choice on the worker thread.
                self._client.set_response_length(self._response_length)
                self.status.emit("Thinking…")
                answer, _refs = self._client.ask(question)
                self.reply.emit(question, answer)
            except Exception as e:  # noqa: BLE001 - surfaced to the UI, never crash
                from src.gui.utils.notebooklm_client import QuestionCancelled
                if isinstance(e, QuestionCancelled):
                    # User pressed "Stop thinking" - a clean stop, not an error.
                    self.status.emit("Stopped.")
                else:
                    log.warning("NotebookLM question failed", exc_info=True)
                    self.error.emit(str(e))
            finally:
                self.busy.emit(False)
        self._close_client()

    def _make_client(self):
        from src.gui.utils.notebooklm_client import NotebookLMClientWrapper
        client = NotebookLMClientWrapper(
            self._notebook_id, self._profile, self._response_length)
        client.connect()
        return client

    def _close_client(self):
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                log.debug("client close failed", exc_info=True)
            self._client = None
