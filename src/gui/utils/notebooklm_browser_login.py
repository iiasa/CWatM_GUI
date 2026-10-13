"""CWatM AI login in the user's installed **Edge / Chrome** (child process, no Qt).

Playwright starts the *installed* browser (Chromium channels ``msedge`` / ``chrome``)
in a **fresh private session** - the user's everyday profile, cookies and passwords are never opened or read - and
opens Google's sign-in page, which continues to NotebookLM. The login is detected by
Google's **sign-in cookies** appearing in that session (``SID`` /
``__Secure-1PSID``), not by the tab's URL: after signing in Google may leave the tab
on an account or NotebookLM start page, and a URL wait would never finish.
The session is then stored as notebooklm's ``storage_state.json``, with notebooklm's
own cookie allowlist and atomic writer (the same file ``notebooklm login`` writes).

Run as ``python <this file> <browser>`` (source) or ``CWatM_GUI.exe
--notebooklm-browser-login <browser>`` (frozen); ``<browser>`` is ``msedge`` or
``chrome``. Output lines the window reacts to: ``<Label> not
found.``, ``The browser window was closed during login.``, ``Login not detected
within 5 minutes.``; exit code 0 = session stored.
"""

import asyncio
import logging
import os
import re
import sys
import time

log = logging.getLogger(__name__)

# key -> (label, Playwright channel, the exe below a Windows install root)
BROWSERS = {
    "msedge": ("Microsoft Edge", "msedge", r"Microsoft\Edge\Application\msedge.exe"),
    "chrome": ("Google Chrome", "chrome", r"Google\Chrome\Application\chrome.exe"),
}
CLOSED = "The browser window was closed during login."
TIMEOUT = "Login not detected within 5 minutes."
_WAIT_S = 300
_POLL_S = 1.0
# Google's session cookies - present once the user has signed in.
_SIGNIN_COOKIES = ("SID", "__Secure-1PSID")
_MARKUP = re.compile(r"\[/?[a-z ]+\]")


class _IO:
    """The LoginIO sink notebooklm's account-metadata helper expects."""

    def emit(self, *args, **kwargs):
        print(_MARKUP.sub("", " ".join(str(a) for a in args)), flush=True)

    def fail(self, code):
        sys.exit(code)

    def run_async(self, coro):
        return asyncio.run(coro)


def signed_in(cookies):
    """True when Google's sign-in cookies are in a Playwright cookie list."""
    return any(c.get("name") in _SIGNIN_COOKIES
               and str(c.get("domain", "")).lstrip(".").startswith("google.")
               for c in cookies)


def browser_executable(key):
    """The installed exe of a BROWSERS key, or None - looked up where Playwright's
    channel looks (%LOCALAPPDATA%, %PROGRAMFILES%, %PROGRAMFILES(X86)%). Used by
    the login window to show which browsers can be chosen. Off Windows: None."""
    if key not in BROWSERS or sys.platform != "win32":
        return None
    for root in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        base = os.environ.get(root)
        if base:
            path = os.path.join(base, BROWSERS[key][2])
            if os.path.isfile(path):
                return path
    return None


def _launch(p, key):
    channel = BROWSERS[key][1]
    # chromium_sandbox=True: Playwright's default adds --no-sandbox, which Chrome
    # shows as an "unsupported command-line flag" warning bar. The automation flags
    # are dropped as notebooklm's own login does (Google refuses sign-in in a browser
    # that reports itself as automated).
    return p.chromium.launch(
        channel=channel, headless=False, chromium_sandbox=True,
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"])


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    key = argv[0] if argv else ""
    io = _IO()
    if key not in BROWSERS:
        io.emit(f"Unknown browser '{key}' - use one of {', '.join(BROWSERS)}.")
        return 2
    label = BROWSERS[key][0]
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        io.emit("Playwright not installed.")
        return 1
    from notebooklm.config import get_base_url
    from notebooklm.io import atomic_write_json
    from notebooklm.paths import get_storage_path
    from notebooklm.cli.services.playwright_login import (
        GOOGLE_ACCOUNTS_URL, filter_storage_state_cookies_by_domain_policy,
        repair_playwright_account_metadata, windows_playwright_event_loop)

    storage_path = get_storage_path()
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    base = get_base_url()

    page_html = None
    with windows_playwright_event_loop(), sync_playwright() as p:
        try:
            browser = _launch(p, key)
        except PlaywrightError as exc:
            low = str(exc).lower()
            if any(m in low for m in ("is not found", "executable doesn't exist",
                                      "no such file", "failed to launch")):
                io.emit(f"{label} not found.")
                return 1
            raise
        try:
            context = browser.new_context()
            page = context.new_page()
            io.emit(f"Opening {label} for Google login...")
            page.goto(f"{GOOGLE_ACCOUNTS_URL}ServiceLogin?continue={base}/",
                      wait_until="commit", timeout=30_000)
            io.emit(f"Sign in to Google in the {label} window - the login is saved "
                    "automatically.")
            deadline = time.monotonic() + _WAIT_S
            while True:
                if not browser.is_connected() or not context.pages:
                    io.emit(CLOSED)
                    return 1
                if signed_in(context.cookies()):
                    break
                if time.monotonic() > deadline:
                    io.emit(TIMEOUT)
                    return 1
                # Let Playwright process events while waiting (a bare sleep would
                # not), on whichever tab is still open.
                context.pages[-1].wait_for_timeout(_POLL_S * 1000)
            io.emit("Login detected.")
            page = context.pages[-1]
            # Open NotebookLM (sets its cookies) and pin the .google.com cookies
            # (regional users land on .google.co.uk), as notebooklm's login does.
            for url in (GOOGLE_ACCOUNTS_URL, f"{base}/"):
                try:
                    page.goto(url, wait_until="commit", timeout=30_000)
                except PlaywrightError:
                    log.debug("navigation to %s interrupted", url, exc_info=True)
            try:
                page.wait_for_timeout(1500)
                page_html = page.content()
            except PlaywrightError:
                page_html = None
            state = filter_storage_state_cookies_by_domain_policy(
                dict(context.storage_state()))
            atomic_write_json(storage_path, state)
        except PlaywrightError as exc:
            if not browser.is_connected() or "has been closed" in str(exc):
                io.emit(CLOSED)
                return 1
            raise
        finally:
            try:
                browser.close()
            except Exception:
                # the window may already be gone; nothing left to close
                log.debug("closing the login browser failed", exc_info=True)
    repair_playwright_account_metadata(storage_path, io, page_html=page_html)
    io.emit(f"Authentication saved to: {storage_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
