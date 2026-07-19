"""Thin blocking wrapper around the async ``notebooklm-py`` library.

This is the **only** module that imports ``notebooklm`` - it isolates the
third-party (unofficial, may-break) API from the GUI. The library is fully
**async** (httpx RPC against Google's undocumented NotebookLM endpoints); its
client binds to the asyncio loop it was opened on, so this wrapper owns **one**
persistent loop and drives every ``await`` through ``run_until_complete``. Callers
(the worker thread) see a plain blocking API: ``connect() -> ask() -> close()``.

Never import this at module level from anything ``main_window`` imports at the top
level (fast-startup rule): import it lazily inside the worker thread.
"""

import asyncio
import re

from src.gui.utils.gui_log import get_logger

log = get_logger("notebooklm_client")


class NotebookLMError(Exception):
    """Base error for the wrapper (readable message for the transcript)."""


class AuthRequired(NotebookLMError):
    """No stored Google session - the user must log in once (CLI)."""


class NotebookSelectionError(NotebookLMError):
    """No notebook id set and it could not be resolved automatically."""


class QuestionCancelled(NotebookLMError):
    """The in-flight request was stopped by the user (Stop thinking)."""


def _extract_notebook_id(value):
    """Accept a bare id or a NotebookLM URL (…/notebook/<id>) and return the id."""
    if not value:
        return None
    value = str(value).strip()
    m = re.search(r"/notebook/([^/?#]+)", value)
    return m.group(1) if m else value


def is_authenticated(profile=None):
    """True if a stored NotebookLM session (cookie bundle) exists on disk."""
    try:
        import os
        from notebooklm import paths
        return os.path.exists(str(paths.get_storage_path(profile)))
    except Exception:
        log.debug("is_authenticated check failed", exc_info=True)
        return False


def storage_state_path(profile=None):
    """Path of the stored session file (for messages), or '' on failure."""
    try:
        from notebooklm import paths
        return str(paths.get_storage_path(profile))
    except Exception:
        return ""


# Substrings that identify an expired/invalid-session error (the message the user
# reported: "ValueError: Authentication expired or invalid ... Run 'notebooklm login'
# to re-authenticate", plus a Google-accounts redirect).
_AUTH_ERROR_HINTS = (
    "authentication expired", "auth expired", "expired or invalid",
    "re-authenticate", "reauthenticate", "not authenticated", "unauthenticated",
    "notebooklm login", "accounts.google.com", "sign in", "login required",
)


def is_auth_error(exc_or_text):
    """True if the exception / message looks like an expired-or-invalid session."""
    try:
        from notebooklm import AuthError
        if isinstance(exc_or_text, Exception) and isinstance(exc_or_text, AuthError):
            return True
    except Exception:
        pass
    text = str(exc_or_text).lower()
    return any(h in text for h in _AUTH_ERROR_HINTS)


def check_connection(profile=None):
    """Actually verify the stored session against NotebookLM (a real network call).

    Returns (status, message) where status is one of:
      - "ok"        : connected, session valid
      - "auth"      : session expired/invalid -> must log in again
      - "no_session": no stored session on disk at all
      - "error"     : some other failure (network/proxy) - state left unknown

    Runs its own event loop; call it from a worker thread (it blocks on the network).
    """
    if not is_authenticated(profile):
        return "no_session", "Not logged in to NotebookLM."
    import asyncio
    from notebooklm import NotebookLMClient

    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)

        async def _probe():
            ctx = NotebookLMClient.from_storage(profile=profile)
            client = await ctx.__aenter__()
            try:
                await client.notebooks.list()   # minimal authenticated call
            finally:
                await ctx.__aexit__(None, None, None)

        loop.run_until_complete(_probe())
        return "ok", ""
    except Exception as e:  # noqa: BLE001
        log.debug("connection check failed", exc_info=True)
        if is_auth_error(e):
            return "auth", ("Authentication expired or invalid - please log in "
                            "again.")
        return "error", f"Could not reach NotebookLM: {e}"
    finally:
        try:
            loop.close()
        except Exception:
            pass


class NotebookLMClientWrapper:
    """Owns one asyncio loop + one NotebookLM client, used from a single thread."""

    # Answer-length selector -> NotebookLM ChatResponseLength enum member name.
    _LENGTH_ENUM = {"short": "SHORTER", "medium": "DEFAULT", "long": "LONGER"}

    def __init__(self, notebook_id=None, profile=None, response_length=None):
        self._notebook_id = _extract_notebook_id(notebook_id)
        self._profile = profile or None
        self._loop = None
        self._ctx = None          # the async context manager from from_storage()
        self._client = None
        self._current_future = None  # the in-flight future (for cross-thread cancel)
        self._conversation_id = None
        self._resolved_title = None
        # Desired vs. already-applied answer length ("short"/"medium"/"long").
        self._response_length = response_length
        self._applied_length = None

    # ------------------------------------------------------------------ helpers
    def _run(self, coro):
        # Wrap the coroutine in a future we keep a handle to, so cancel() (called
        # from the GUI thread) can stop the in-flight call. A cancelled future makes
        # run_until_complete raise CancelledError (a BaseException, not Exception),
        # which we re-raise as QuestionCancelled so the normal except-Exception paths
        # handle it as a clean "stopped" outcome rather than crashing the thread.
        import asyncio as _asyncio
        fut = _asyncio.ensure_future(coro)   # bound to the current loop (self._loop)
        self._current_future = fut
        try:
            return self._loop.run_until_complete(fut)
        except _asyncio.CancelledError:
            raise QuestionCancelled("Stopped.")
        finally:
            self._current_future = None

    def cancel(self):
        """Stop the in-flight async call. Safe to call from another thread (Stop
        thinking): schedules the future's cancellation on the client's own loop."""
        loop, fut = self._loop, self._current_future
        if loop is not None and fut is not None and not fut.done():
            try:
                loop.call_soon_threadsafe(fut.cancel)
            except Exception:
                log.debug("cancel failed", exc_info=True)

    # ------------------------------------------------------------------ connect
    def connect(self):
        """Open the client (lazily). Raises AuthRequired if no session is stored."""
        if self._client is not None:
            return
        if not is_authenticated(self._profile):
            raise AuthRequired(
                "Not logged in to NotebookLM. Use the 'Login…' button once to "
                "store a Google session, then ask again.")
        from notebooklm import NotebookLMClient

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        async def _open():
            ctx = NotebookLMClient.from_storage(profile=self._profile)
            client = await ctx.__aenter__()
            return ctx, client

        try:
            self._ctx, self._client = self._run(_open())
        except Exception as e:
            self._close_loop()
            raise self._translate(e)

        if not self._notebook_id:
            self._notebook_id = self._resolve_notebook()
        self._apply_response_length()

    # ------------------------------------------------------------ answer length
    def set_response_length(self, key):
        """Store the desired answer length ("short"/"medium"/"long" or None).
        Store-only (safe from any thread); applied on the client's loop by
        ``_apply_response_length`` from ``ask``/``connect`` (worker thread)."""
        self._response_length = key

    def _apply_response_length(self):
        """Push the desired answer length to NotebookLM (once per change). No-op if
        unset, unchanged, or the client/notebook is not ready yet."""
        key = self._response_length
        if not key or self._client is None or not self._notebook_id:
            return
        if key == self._applied_length:
            return
        enum_name = self._LENGTH_ENUM.get(key)
        if not enum_name:
            return
        from notebooklm import ChatResponseLength
        length = getattr(ChatResponseLength, enum_name)

        async def _cfg():
            await self._client.chat.configure(
                self._notebook_id, response_length=length)
        try:
            self._run(_cfg())
            self._applied_length = key
        except Exception as e:
            raise self._translate(e)

    def _resolve_notebook(self):
        """Pick a notebook when none is configured: prefer one whose title
        mentions 'cwat', else the only one, else raise with the choices."""
        async def _list():
            return await self._client.notebooks.list()
        try:
            books = self._run(_list())
        except Exception as e:
            raise self._translate(e)
        if not books:
            raise NotebookSelectionError(
                "No NotebookLM notebooks found for this account. Create one in "
                "the NotebookLM web app (upload CWATM_shorter.pdf as a source), "
                "then set it with the 'Notebook…' button.")
        for nb in books:
            if "cwat" in (nb.title or "").lower():
                self._resolved_title = nb.title
                return nb.id
        if len(books) == 1:
            self._resolved_title = books[0].title
            return books[0].id
        titles = "\n".join(f"  • {nb.title}  (id: {nb.id})" for nb in books)
        raise NotebookSelectionError(
            "Several notebooks exist - set which one to use with the 'Notebook…' "
            "button:\n" + titles)

    # ---------------------------------------------------------------------- ask
    def ask(self, question):
        """Ask a question; returns (answer_text, references_list)."""
        if self._client is None:
            self.connect()
        self._apply_response_length()   # honour the current Short/Medium/Long choice

        async def _ask():
            return await self._client.chat.ask(
                self._notebook_id, question,
                conversation_id=self._conversation_id)
        try:
            result = self._run(_ask())
        except Exception as e:
            raise self._translate(e)
        self._conversation_id = getattr(result, "conversation_id", None) \
            or self._conversation_id
        answer = getattr(result, "answer", "") or ""
        refs = list(getattr(result, "references", None) or [])
        return answer, refs

    @property
    def notebook_title(self):
        return self._resolved_title

    # -------------------------------------------------------------------- close
    def close(self):
        if self._client is not None and self._ctx is not None and self._loop is not None:
            async def _shut():
                await self._ctx.__aexit__(None, None, None)
            try:
                self._run(_shut())
            except Exception:
                log.debug("client close failed", exc_info=True)
        self._client = None
        self._ctx = None
        self._close_loop()

    def _close_loop(self):
        if self._loop is not None:
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None

    # --------------------------------------------------------------- exceptions
    @staticmethod
    def _translate(exc):
        """Map a library/network error to a readable wrapper error."""
        try:
            from notebooklm import AuthError, NotebookNotFoundError, NetworkError
        except Exception:
            AuthError = NotebookNotFoundError = NetworkError = ()
        if (AuthError and isinstance(exc, AuthError)) or is_auth_error(exc):
            return AuthRequired(
                "The stored NotebookLM session is invalid or expired. Use "
                "'Login…' to sign in again.")
        if NotebookNotFoundError and isinstance(exc, NotebookNotFoundError):
            return NotebookSelectionError(
                "The configured notebook was not found. Set another one with the "
                "'Notebook…' button.")
        if NetworkError and isinstance(exc, NetworkError):
            return NotebookLMError(f"Network problem talking to NotebookLM:\n{exc}")
        if isinstance(exc, NotebookLMError):
            return exc
        return NotebookLMError(f"{type(exc).__name__}: {exc}")
