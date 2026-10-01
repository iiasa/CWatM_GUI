"""Links in rich-text views (Help viewer, CWatM AI transcript) and AI answers
(sast.md step 4). A link must never start a program: QTextBrowser's own
setOpenExternalLinks(True) would hand file:///…/x.exe to the desktop, which runs it.
AI answers come from outside, so their raw HTML is shown as text."""

import os

import pytest

pytestmark = pytest.mark.qt

from PySide6.QtCore import QUrl  # noqa: E402

from src.gui.utils import open_path as O  # noqa: E402


@pytest.fixture
def opened(monkeypatch):
    calls = []
    monkeypatch.setattr(O.os, "startfile", lambda p: calls.append(("file", p)),
                        raising=False)
    monkeypatch.setattr(O.QDesktopServices, "openUrl", staticmethod(
        lambda url: calls.append(("url", url.toString())) or True))
    return calls


def test_web_and_mail_links_open(opened):
    assert O.open_link("https://cwatm.iiasa.ac.at/")
    assert O.open_link("mailto:someone@example.org")
    assert [c[0] for c in opened] == ["url", "url"]


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://x/y",
                                 "smb://server/share/x.exe", "data:text/html,x"])
def test_other_schemes_are_ignored(opened, url):
    assert O.open_link(url) is False and opened == []


def test_a_link_to_a_program_opens_its_folder_never_the_program(opened, tmp_path):
    exe = tmp_path / "evil.exe"
    exe.write_text("stub")
    O.open_link(QUrl.fromLocalFile(str(exe)))
    assert opened and os.path.normcase(opened[0][1].rstrip("/\\")) == \
        os.path.normcase(str(tmp_path))


def test_a_link_to_a_network_share_is_refused(opened):
    assert O.open_link(QUrl.fromLocalFile(r"\\server\share\x.bat")) is False
    assert opened == []


def test_an_anchor_scrolls_the_view(qapp, opened):
    from PySide6.QtWidgets import QTextBrowser
    b = QTextBrowser()
    O.make_links_safe(b)
    b.setHtml('<a name="part2"></a>text')  # html-safe: test constant
    assert O.open_link(QUrl("#part2"), b) and opened == []
    assert not b.openExternalLinks() and not b.openLinks()


def test_ai_answers_show_raw_html_as_text():
    from src.gui.widgets.notebooklm_window import NotebookLMWindow
    html = NotebookLMWindow._render_markdown(
        'Hi <script>alert(1)</script> <img src="x" onerror="y"> **bold**')
    assert "<script>" not in html and "<img" not in html
    assert "&lt;script&gt;" in html and "<strong>bold</strong>" in html


def test_the_transcript_routes_links_through_open_link(qapp):
    from src.gui.widgets import notebooklm_window as N
    src = open(N.__file__, encoding="utf-8").read()
    assert "make_links_safe(self.transcript)" in src
    assert "setOpenExternalLinks(True)" not in src


class _Settings:
    def __init__(self):
        self.d = {}

    def value(self, key, default=None, type=None):
        return self.d.get(key, default)

    def setValue(self, key, value):
        self.d[key] = value


def test_cookie_login_asks_once_and_explains(monkeypatch):
    # security.md #5: reading browser cookies + storing a Google session needs a
    # clear, informed yes first - asked once, "No" is the default and stops it
    from types import SimpleNamespace
    from PySide6.QtWidgets import QMessageBox
    from src.gui.widgets.notebooklm_window import NotebookLMWindow as N
    asked = []
    answer = [QMessageBox.No]
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda parent, title, text, buttons, default:
        asked.append((text, default)) or answer[0]))
    host = SimpleNamespace(_settings=_Settings(),
                           _COOKIE_CONSENT_KEY=N._COOKIE_CONSENT_KEY,
                           cookie_login_text=N.cookie_login_text)
    assert N._cookie_login_agreed(host) is False             # declined: no login
    text, default = asked[-1]
    assert "READS the Google login cookies" in text and "storage_state" in text
    assert default == QMessageBox.No
    answer[0] = QMessageBox.Yes
    assert N._cookie_login_agreed(host) is True
    asked.clear()
    assert N._cookie_login_agreed(host) is True and asked == []   # asked only once
