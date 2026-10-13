"""CWatM AI login script (src/gui/utils/notebooklm_browser_login.py) - pure parts."""

from src.gui.utils import notebooklm_browser_login as L


def test_signed_in_needs_googles_session_cookie():
    # the login is detected by Google's sign-in cookies, wherever the tab ended up
    assert not L.signed_in([])
    assert not L.signed_in([{"name": "NID", "domain": ".google.com"}])      # not signed in
    assert not L.signed_in([{"name": "SID", "domain": ".example.com"}])     # wrong site
    assert L.signed_in([{"name": "SID", "domain": ".google.com"}])
    assert L.signed_in([{"name": "__Secure-1PSID", "domain": ".google.co.uk"}])


def test_browser_keys_match_the_window():
    from src.gui.widgets.notebooklm_window import NotebookLMWindow
    assert set(NotebookLMWindow.LOGIN_BROWSERS) == set(L.BROWSERS)
    # the window recognises "<label> not found." by the same label
    for key, (_text, label) in NotebookLMWindow.LOGIN_BROWSERS.items():
        assert L.BROWSERS[key][0] == label


def test_unknown_browser_is_refused(capsys):
    assert L.main(["firefox"]) == 2
    assert "Unknown browser" in capsys.readouterr().out


def test_browser_executable_looks_where_playwright_looks(tmp_path, monkeypatch):
    import sys
    if sys.platform != "win32":
        assert L.browser_executable("chrome") is None
        return
    exe = tmp_path / "Google" / "Chrome" / "Application" / "chrome.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    for root in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        monkeypatch.setenv(root, str(tmp_path / "nowhere"))
    assert L.browser_executable("chrome") is None
    monkeypatch.setenv("PROGRAMFILES", str(tmp_path))
    assert L.browser_executable("chrome") == str(exe)
    assert L.browser_executable("msedge") is None      # not installed there
    assert L.browser_executable("firefox") is None     # not offered
