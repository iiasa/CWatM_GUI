"""CWatM AI - a chat window backed by Google **NotebookLM** (``notebooklm-py``).

Ask questions about CWatM; they are answered by Gemini through a NotebookLM
notebook whose source is a predefined PDF (e.g. ``CWATM_shorter.pdf``). v1 only
asks/answers - no settings-file interaction yet (see ``ai.md`` for later phases).

Styled like the other secondary windows (NetCDF / Watercycle): ``QDialog`` +
``GeometryMemoryMixin``, every colour from ``theme.c(token)``, window icon, geometry
remembered under the ``cwatm_ai`` key. All ``notebooklm`` contact happens on a
``NotebookLMWorker`` QThread - the UI never blocks.
"""

import os
import re
import sys

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextBrowser,
    QPlainTextEdit, QMessageBox, QInputDialog, QButtonGroup,
)
from PySide6.QtCore import Qt, QSettings, QProcess, QThread, Signal
from PySide6.QtGui import QIcon

from src.gui.utils import theme
from src.gui.utils.window_geometry import GeometryMemoryMixin
from src.gui.utils.gui_log import get_logger

log = get_logger("notebooklm_window")

_IS_FROZEN = getattr(sys, "frozen", False)


class _AuthCheckWorker(QThread):
    """Verify the stored NotebookLM session against the server off the GUI thread.

    Emits ``result(status, message)`` where status is one of
    ``ok`` / ``auth`` / ``no_session`` / ``error`` (see
    ``notebooklm_client.check_connection``)."""

    result = Signal(str, str)

    def run(self):
        try:
            from src.gui.utils.notebooklm_client import check_connection
            status, message = check_connection()
        except Exception as e:  # noqa: BLE001 - never crash the GUI
            log.debug("auth check worker failed", exc_info=True)
            status, message = "error", f"Could not verify login: {e}"
        self.result.emit(status, message)


def open_cwatm_ai(parent=None):
    """Open (or reuse) the CWatM AI chat window on ``parent``."""
    win = getattr(parent, "_cwatm_ai_window", None)
    try:
        if win is not None and win.isVisible():
            win.raise_()
            win.activateWindow()
            return win
    except RuntimeError:
        win = None  # C++ object gone
    win = NotebookLMWindow(parent)
    if parent is not None:
        parent._cwatm_ai_window = win
    win.show()
    win.raise_()
    win.activateWindow()
    return win


class NotebookLMWindow(GeometryMemoryMixin, QDialog):
    """Non-modal Gemini/NotebookLM chat window (v1: ask → answer)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings("IIASA", "CWatM_GUI")
        self._notebook_id = self._settings.value("notebooklm/notebook_id", "", type=str)
        self._worker = None
        self._login_proc = None
        # One-click auto-detect login state: walk a browser list, verify each
        # session, stop at the first that actually works (see _start_auto_login).
        self._auto_login_active = False
        self._auto_browsers = []
        self._auto_index = 0
        self._auto_saw_decrypt = False
        self._auto_verifier = None
        self._thinking = False        # a question is in flight (Send → Stop thinking)
        # Answer length ("short"/"medium"/"long"); persisted. Medium = NotebookLM
        # default verbosity.
        self._length_key = self._settings.value(
            "notebooklm/response_length", "medium", type=str)
        if self._length_key not in ("short", "medium", "long"):
            self._length_key = "medium"
        # Question history for Up/Down recall (oldest -> newest); persisted.
        self._history = []
        self._hist_pos = None        # None = editing the live draft
        self._hist_draft = ""

        self.setWindowTitle("\U0001F916 CWatM AI")
        # Non-modal so the user keeps working in the editor while waiting.
        self.setModal(False)
        self.setWindowFlags(
            Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        if not self._init_geometry_memory("cwatm_ai"):
            self.resize(720, 640)
        self._set_window_icon()

        # Verified auth state: None = unknown/checking, True = confirmed connected,
        # False = expired/invalid (a stored session file that no longer works).
        self._auth_verified = None
        self._auth_checker = None

        self._build_ui()
        self._apply_theme()
        # Restore the previous session's transcript + question history, then greet.
        restored = self._restore_state()
        self._greet(restored)
        self._refresh_login_state()
        # A storage file existing does NOT mean the session is still valid, so verify
        # it against NotebookLM in the background and update the state when it returns.
        self._start_auth_check()

    def _greet(self, restored):
        """Opening message. When a previous transcript was restored, add a subtle
        separator instead of repeating the full intro."""
        if restored:
            self._append_status("— New session —")
            return
        self._append_status(
            "Ask a question about CWatM. Answers come from Google NotebookLM "
            "(CWatM documentation).")

    # ------------------------------------------------------------------- set-up
    def _set_window_icon(self):
        try:
            root = os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(__file__))))
            icon_path = os.path.join(root, "assets", "cwatm.ico")
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Header
        self.header_label = QLabel("CWatM AI — Gemini NotebookLM assistant")
        self.header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.header_label)

        self.sub_label = QLabel(self._notebook_subtitle())
        self.sub_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.sub_label)

        # Login-state line (like the NetCDF window's info label) - clearly states
        # whether you are signed in; colour set in _refresh_login_state().
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        # Transcript (read-only, rich text so we can colour Q/A/status/error)
        self.transcript = QTextBrowser()
        self.transcript.setOpenExternalLinks(True)
        layout.addWidget(self.transcript, 1)

        # Settings-bridge action: explain the settings editor's current line.
        # (Also triggerable by typing "explain this line".)
        self.explain_line_button = QPushButton("Explain current line")
        self.explain_line_button.setToolTip(
            "Ask NotebookLM to explain the line the cursor is on in the settings file")
        self.explain_line_button.clicked.connect(self._cmd_explain_line)
        tools_row = QHBoxLayout()
        tools_row.setSpacing(8)
        tools_row.addWidget(self.explain_line_button)
        tools_row.addStretch()
        layout.addLayout(tools_row)

        # Input row: multi-line box + Send (Enter sends, Shift+Enter = newline)
        self.input_box = QPlainTextEdit()
        self.input_box.setPlaceholderText(
            "Ask about CWatM…  (Enter to send, Shift+Enter for a new line)")
        self.input_box.setFixedHeight(64)
        self.input_box.installEventFilter(self)
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self._on_send)
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        input_row.addWidget(self.input_box, 1)
        input_row.addWidget(self.send_button)
        layout.addLayout(input_row)

        # Bottom button row
        self.login_button = QPushButton("Login…")
        self.login_button.setToolTip(
            "One click: finds the browser you are signed in to Google with "
            "(Firefox / Chrome / Edge / Opera) and stores its session")
        self.login_button.clicked.connect(self._on_login)
        # Fallback: pick a specific browser / the Google login window by hand.
        self.browser_button = QPushButton("Choose browser…")
        self.browser_button.setToolTip(
            "Pick a specific browser to read Google cookies from, or open the "
            "Google login window (if available)")
        self.browser_button.clicked.connect(self._on_choose_browser)
        self.notebook_button = QPushButton("Notebook…")
        self.notebook_button.setToolTip(
            "Set which NotebookLM notebook (or its URL) to ask")
        self.notebook_button.clicked.connect(self._on_set_notebook)
        self.clear_button = QPushButton("Clear")
        self.clear_button.clicked.connect(self._on_clear)
        self.exit_button = QPushButton("Exit")
        self.exit_button.clicked.connect(self.close)

        # Answer-length selector (Short / Medium / Long) - compact exclusive toggle
        # buttons placed right of Notebook…
        self.length_caption = QLabel("Length:")
        self.length_group = QButtonGroup(self)
        self.length_group.setExclusive(True)
        self._length_buttons = {}
        for key, label in (("short", "Short"), ("medium", "Medium"), ("long", "Long")):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == self._length_key)
            btn.setMaximumWidth(56)
            btn.setToolTip(f"Ask NotebookLM for a {label.lower()} answer")
            btn.clicked.connect(lambda _c=False, k=key: self._on_length_selected(k))
            self.length_group.addButton(btn)
            self._length_buttons[key] = btn

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addWidget(self.login_button)
        btn_row.addWidget(self.browser_button)
        btn_row.addWidget(self.notebook_button)
        btn_row.addSpacing(6)
        btn_row.addWidget(self.length_caption)
        for key in ("short", "medium", "long"):
            btn_row.addWidget(self._length_buttons[key])
        btn_row.addStretch()
        btn_row.addWidget(self.clear_button)
        btn_row.addWidget(self.exit_button)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------ styling
    def _apply_theme(self):
        """Theme the window at construction time (like the other secondary
        windows) - every colour from a theme token."""
        self.setStyleSheet(
            f"QDialog {{ background-color: {theme.c('window_bg')}; }}")
        # Header 14px/600 + muted sub-label - matches the NetCDF window.
        self.header_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 14px; font-weight: 600; "
            f"color: {theme.c('text')}; padding: 4px;")
        self.sub_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 12px; "
            f"color: {theme.c('text_muted')}; padding: 2px 8px;")
        # One triple-quoted f-string (do NOT concatenate f-strings with plain strings:
        # a plain-string "}}" stays two braces and corrupts the QSS). Blue, round-edged
        # scrollbar matching the main-window settings editor (accent handle, surface_bg
        # groove) — vertical and horizontal.
        self.transcript.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {theme.c('out_bg')};
                color: {theme.c('out_text')};
                border: 1px solid {theme.c('out_border')};
                border-radius: 8px;
                padding: 8px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 13px;
            }}
            QScrollBar:vertical {{
                background-color: {theme.c('surface_bg')};
                width: 18px;
                border-radius: 7px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {theme.c('accent')};
                border-radius: 7px;
                min-height: 28px;
            }}
            QScrollBar::handle:vertical:hover {{
                background-color: {theme.c('menu_sel_bg')};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
            QScrollBar:horizontal {{
                background-color: {theme.c('surface_bg')};
                height: 18px;
                border-radius: 7px;
                margin: 2px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {theme.c('accent')};
                border-radius: 7px;
                min-width: 28px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background-color: {theme.c('menu_sel_bg')};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}
        """)
        self.input_box.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {theme.c('field_bg')}; "
            f"color: {theme.c('field_text')}; border: 1px solid {theme.c('field_border')}; "
            "border-radius: 6px; padding: 6px; "
            "font-family: 'Segoe UI', sans-serif; font-size: 13px; }}")
        # Blue gradient action buttons like the NetCDF window (Send stands out); a
        # lighter blue variant is used while a question is in flight ("Stop thinking").
        blue = self._button_style(
            "#5dade2", "#3498db", "#85c1e9", "#5dade2", "#3498db", "white")
        self._send_style = blue
        self._stop_style = self._button_style(
            "#aed6f1", "#85c1e9", "#d4e6f1", "#aed6f1", "#5dade2", "white")
        self.send_button.setStyleSheet(self._stop_style if self._thinking else blue)
        # Neutral (grey) buttons: Notebook / Clear / Exit.
        grey = self._button_style(
            theme.c('btn_top'), theme.c('btn_bottom'), theme.c('btn_hover_top'),
            theme.c('btn_hover_bottom'), theme.c('btn_border'), theme.c('btn_text'))
        for b in (self.browser_button, self.notebook_button, self.clear_button,
                  self.exit_button, self.explain_line_button):
            b.setStyleSheet(grey)
        self.length_caption.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 12px; "
            f"color: {theme.c('text_muted')};")
        self._style_length_buttons()
        # The login button is coloured by sign-in state (blue = in, red = out).
        self._refresh_login_state()

    @staticmethod
    def _compact_button_style(top, bottom, htop, hbottom, border, text):
        """A smaller variant of _button_style for the length selector."""
        return f"""
            QPushButton {{
                font-family: 'Segoe UI', sans-serif; font-size: 11px; font-weight: 500;
                color: {text}; border: 1px solid {border}; border-radius: 5px;
                padding: 2px 6px; min-height: 18px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {top}, stop:1 {bottom});
            }}
            QPushButton:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {htop}, stop:1 {hbottom}); }}
        """

    def _style_length_buttons(self):
        """Selected length button = blue, the others grey (compact)."""
        blue = self._compact_button_style(
            "#5dade2", "#3498db", "#85c1e9", "#5dade2", "#3498db", "white")
        grey = self._compact_button_style(
            theme.c('btn_top'), theme.c('btn_bottom'), theme.c('btn_hover_top'),
            theme.c('btn_hover_bottom'), theme.c('btn_border'), theme.c('btn_text'))
        for key, btn in self._length_buttons.items():
            btn.setStyleSheet(blue if key == self._length_key else grey)

    @staticmethod
    def _button_style(top, bottom, htop, hbottom, border, text):
        return f"""
            QPushButton {{
                font-family: 'Segoe UI', sans-serif; font-size: 12px; font-weight: 500;
                color: {text}; border: 1px solid {border}; border-radius: 6px;
                padding: 6px 14px; min-height: 24px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 {top}, stop:1 {bottom});
            }}
            QPushButton:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 {htop}, stop:1 {hbottom}); }}
            QPushButton:disabled {{ background: #d3d3d3; color: #a9a9a9; }}
        """

    # ------------------------------------------------------------ login state UI
    def _refresh_login_state(self):
        """Colour the Login button + status label by the **verified** sign-in state.
        A stored session file alone only counts once confirmed valid (blue); an
        expired/invalid session shows **red** like being logged out."""
        blue = ("#5dade2", "#3498db", "#85c1e9", "#5dade2", "#3498db", "white")
        red = ("#ec7063", "#e74c3c", "#f1948a", "#ec7063", "#c0392b", "white")
        has_file = self._is_authenticated()

        if has_file and self._auth_verified is None:
            # File exists but not yet verified - neutral "checking" (blue-ish).
            self.login_button.setText("Checking…")
            self.login_button.setToolTip("Verifying your NotebookLM session…")
            self.login_button.setStyleSheet(self._button_style(*blue))
            self.status_label.setText("● Checking NotebookLM session…")
            colour = "#2e86c1"
        elif self._auth_verified is True:
            self.login_button.setText("✓ Logged in")
            self.login_button.setToolTip(
                "Logged in to NotebookLM. Click to sign in again if needed.")
            self.login_button.setStyleSheet(self._button_style(*blue))
            self.status_label.setText("● Logged in to NotebookLM")
            colour = "#2e86c1"
        else:
            # No session file, or a stored session that failed verification (expired).
            expired = has_file and self._auth_verified is False
            self.login_button.setText("Login required" if expired else "Login…")
            self.login_button.setToolTip(
                "Your NotebookLM session has expired - click to log in again."
                if expired else "Not logged in - click to sign in to NotebookLM.")
            self.login_button.setStyleSheet(self._button_style(*red))
            self.status_label.setText(
                "● Session expired — press 'Login required'" if expired
                else "● Not logged in — press 'Login…'")
            colour = "#c0392b"
        self.status_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 12px; font-weight: 600; "
            f"color: {colour}; padding: 2px;")

    # -------------------------------------------------------- auth verification
    def _start_auth_check(self):
        """Verify the stored session against NotebookLM in the background."""
        if not self._is_authenticated():
            return                      # nothing to verify (no session file)
        if self._auth_checker is not None:
            return                      # already running
        self._auth_verified = None
        self._refresh_login_state()
        self._auth_checker = _AuthCheckWorker(parent=self)
        self._auth_checker.result.connect(self._on_auth_result)
        self._auth_checker.finished.connect(self._on_auth_checker_done)
        self._auth_checker.start()

    def _on_auth_checker_done(self):
        self._auth_checker = None

    def _on_auth_result(self, status, message):
        if status == "ok":
            self._auth_verified = True
            self._refresh_login_state()
            self._warm_worker()   # pre-connect so the first question is faster
        elif status == "auth":
            # Stored session is expired/invalid - show logged-out (red) and offer
            # to re-authenticate right away.
            self._auth_verified = False
            self._refresh_login_state()
            self._append_error(
                message + " (NotebookLM redirected to a Google sign-in.)")
            self._prompt_reauth()
        elif status == "no_session":
            self._auth_verified = None
            self._refresh_login_state()
        else:  # "error" - network/proxy issue; leave state unknown, just note it.
            self._append_status(message)

    def _prompt_reauth(self):
        """Offer to log in again after detecting an expired session."""
        if _IS_FROZEN:
            self._append_error(
                "Log in again from a terminal:  notebooklm login  (or "
                "notebooklm login --browser-cookies firefox), then reopen this window.")
            return
        resp = QMessageBox.question(
            self, "NotebookLM login",
            "Your NotebookLM session has expired. Log in again now?\n\n"
            "This opens a Google sign-in window in your browser.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if resp == QMessageBox.Yes:
            self._start_google_login()

    # ------------------------------------------------------- state persistence
    def _restore_state(self):
        """Load the previous session's transcript + question history. Returns True
        if a non-empty transcript was restored."""
        try:
            hist = self._settings.value("notebooklm/history", [])
            if isinstance(hist, str):
                hist = [hist]
            self._history = [str(h) for h in (hist or [])]
        except Exception:
            self._history = []
        restored = False
        try:
            html = self._settings.value("notebooklm/transcript_html", "", type=str)
            if html and html.strip():
                self.transcript.setHtml(html)
                sb = self.transcript.verticalScrollBar()
                sb.setValue(sb.maximum())
                restored = True
        except Exception:
            log.debug("transcript restore failed", exc_info=True)
        return restored

    def _save_state(self):
        """Persist the transcript + question history for the next open."""
        try:
            self._settings.setValue(
                "notebooklm/transcript_html", self.transcript.toHtml())
            self._settings.setValue("notebooklm/history", self._history[-200:])
        except Exception:
            log.debug("state save failed", exc_info=True)

    # ---------------------------------------------------------------- transcript
    def _append_html(self, html):
        self.transcript.append(html)
        sb = self.transcript.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _append_status(self, text):
        self._append_html(
            f'<div style="color:{theme.c("text_muted")};"><i>{self._esc(text)}</i></div>')

    def _append_error(self, text):
        self._append_html(
            f'<div style="color:{theme.c("out_error")};"><b>Error:</b> '
            f'{self._esc(text)}</div>')

    def _append_label_line(self, label, text=""):
        """A notice with a **bold blue label** and normal-weight body text (in the
        regular text colour) - e.g. 'Explaining settings line: <line>'."""
        body = ""
        if text:
            body = (f' <span style="color:{theme.c("out_text")}; '
                    f'font-weight:normal;">{self._esc(text)}</span>')
        self._append_html(
            f'<div style="margin-top:6px;"><b style="color:{theme.c("link_color")};">'
            f'{self._esc(label)}</b>{body}</div>')

    def _append_question(self, text):
        self._append_html(
            f'<div style="margin-top:6px;"><b style="color:{theme.c("link_color")};">'
            f'You:</b> {self._esc(text)}</div>')

    def _append_answer(self, text):
        # NotebookLM answers are markdown - render them so bold/lists/tables/code show.
        body = self._render_markdown(text)
        self._append_html(
            f'<div><b style="color:{theme.c("ok_color")};">Gemini:</b></div>'
            f'<div>{body}</div>')
        self._append_separator()

    def _append_separator(self):
        """One carriage return + a horizontal rule between an answer and the next
        question (no extra blank line)."""
        self._append_html(
            f'<hr style="height:1px; border:none; background-color:{theme.c("border")};">')

    @staticmethod
    def _render_markdown(text):
        """Render markdown answer text to HTML (GitHub-flavoured: bold, lists,
        tables, code). Falls back to escaped text if markdown-it is unavailable."""
        text = text or ""
        try:
            from markdown_it import MarkdownIt
            md = MarkdownIt("gfm-like", {"breaks": True, "linkify": False})
            html = md.render(text).strip()
            # Unwrap a single top-level <p>…</p> so a short answer doesn't carry the
            # paragraph's extra top/bottom margin (keeps it to one carriage return).
            m = re.fullmatch(r"<p>(.*)</p>", html, re.S)
            if m and "<p>" not in m.group(1):
                html = m.group(1)
            return html
        except Exception:
            esc = (text.replace("&", "&amp;").replace("<", "&lt;")
                   .replace(">", "&gt;").replace("\n", "<br>"))
            return f'<div>{esc}</div>'

    @staticmethod
    def _esc(text):
        return (str(text).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace("\n", "<br>"))

    # -------------------------------------------------------------------- events
    def eventFilter(self, obj, event):
        """Enter sends; Shift+Enter = newline; Up/Down recall older/newer questions
        (only when the cursor is on the first/last line, so multi-line editing still
        works)."""
        from PySide6.QtCore import QEvent
        if obj is self.input_box and event.type() == QEvent.KeyPress:
            key = event.key()
            mods = event.modifiers()
            if key in (Qt.Key_Return, Qt.Key_Enter) and not (mods & Qt.ShiftModifier):
                self._on_send()
                return True
            if key == Qt.Key_Up and not mods and self._at_first_line():
                self._history_prev()
                return True
            if key == Qt.Key_Down and not mods and self._at_last_line():
                self._history_next()
                return True
        return super().eventFilter(obj, event)

    # -------------------------------------------------------- question history
    def _at_first_line(self):
        return self.input_box.textCursor().blockNumber() == 0

    def _at_last_line(self):
        return self.input_box.textCursor().blockNumber() == \
            self.input_box.document().blockCount() - 1

    def _set_input_text(self, text):
        from PySide6.QtGui import QTextCursor
        self.input_box.setPlainText(text)
        cur = self.input_box.textCursor()
        cur.movePosition(QTextCursor.End)
        self.input_box.setTextCursor(cur)

    def _history_prev(self):
        """Up: move to an older question."""
        if not self._history:
            return
        if self._hist_pos is None:
            self._hist_draft = self.input_box.toPlainText()
            self._hist_pos = len(self._history) - 1
        elif self._hist_pos > 0:
            self._hist_pos -= 1
        self._set_input_text(self._history[self._hist_pos])

    def _history_next(self):
        """Down: move to a newer question, back to the live draft past the newest."""
        if self._hist_pos is None:
            return
        if self._hist_pos < len(self._history) - 1:
            self._hist_pos += 1
            self._set_input_text(self._history[self._hist_pos])
        else:
            self._hist_pos = None
            self._set_input_text(self._hist_draft)

    def _push_history(self, question):
        """Record a sent question and reset the recall cursor."""
        if not self._history or self._history[-1] != question:
            self._history.append(question)
        self._hist_pos = None
        self._hist_draft = ""

    # ------------------------------------------------------------ answer length
    def _on_length_selected(self, key):
        if key == self._length_key:
            return
        self._length_key = key
        self._settings.setValue("notebooklm/response_length", key)
        # Keep the checked state consistent (exclusive group unchecks the others).
        self._length_buttons[key].setChecked(True)
        self._style_length_buttons()
        if self._worker is not None:
            self._worker.set_response_length(key)
        self._append_status(
            f"Answer length set to {key.capitalize()} (applies to the next question).")

    # ---------------------------------------------------------------- ask / send
    def _on_send(self):
        # While a question is in flight the button is "Stop thinking": cancel instead.
        if self._thinking:
            self._stop_thinking()
            return
        if not self.send_button.isEnabled():
            return
        text = self.input_box.toPlainText().strip()
        if not text:
            return
        # Local commands (settings insert / explain line) intercept before the
        # question is sent to NotebookLM.
        if self._maybe_handle_command(text):
            self.input_box.clear()
            self._push_history(text)
            return
        self.input_box.clear()
        self._push_history(text)
        self._submit_question(text, echo=True)

    def _submit_question(self, question, echo=True):
        """Send a question to the NotebookLM worker (echo it as 'You:' unless the
        caller already showed context)."""
        if not question:
            return
        if echo:
            self._append_question(question)
        self._ensure_worker()
        self._worker.ask(question)

    # ------------------------------------------------- settings-bridge commands
    # Exact phrases (normalised) that trigger the local 'explain this line' action.
    _EXPLAIN_CMDS = {
        "explain this line", "explain me this line", "explain this",
        "explain me this", "explain the current line", "explain current line",
        "explain the line", "explain this settings line",
        "explain this settingsfile line", "explain me this settings line",
        "what does this line do", "what does this line mean",
        "what is this line", "explain this setting",
    }

    def _maybe_handle_command(self, text):
        """Return True (and act) if ``text`` is one of the local settings commands."""
        norm = re.sub(r"\s+", " ", text.strip().lower()).rstrip(".!?")
        if norm in self._EXPLAIN_CMDS:
            self._append_question(text)
            self._cmd_explain_line()
            return True
        return False

    def _main_window(self):
        """Walk up to the main window (the object exposing the settings bridge)."""
        w = self.parent()
        while w is not None and not hasattr(w, "ai_current_settings_line"):
            w = w.parent() if hasattr(w, "parent") else None
        return w

    def _cmd_explain_line(self):
        mw = self._main_window()
        if mw is None:
            self._append_error("The settings editor is not available.")
            return
        try:
            line = mw.ai_current_settings_line()
        except Exception:
            line = ""
        if not line:
            self._append_status(
                "Place the cursor on a line in the settings file, then use "
                "'Explain current line' or say 'explain this line'.")
            return
        question = (
            f"Explain this line from a CWatM settings (.ini) file: `{line}`. "
            "What does this option/parameter control, and what values are valid?")
        self._append_label_line("Explaining settings line:", line)
        self._submit_question(question, echo=False)

    def _ensure_worker(self):
        if self._worker is not None:
            return
        from src.gui.utils.notebooklm_worker import NotebookLMWorker
        self._worker = NotebookLMWorker(
            notebook_id=self._notebook_id or None,
            response_length=self._length_key, parent=self)
        self._worker.status.connect(self._append_status)
        self._worker.reply.connect(self._on_reply)
        self._worker.error.connect(self._on_worker_error)
        self._worker.busy.connect(self._on_busy)
        self._worker.start()

    def _warm_worker(self):
        """Pre-connect the NotebookLM worker in the background (once the session is
        confirmed valid) so the first question skips the connect round-trips.
        No-op while a question is in flight or an auto-login is running."""
        if self._thinking or self._auto_login_active:
            return
        try:
            self._ensure_worker()
            self._worker.warm()
        except Exception:
            log.debug("worker warm-up failed", exc_info=True)

    def _reset_worker(self):
        """Drop the worker so the next question reconnects (after login/notebook
        change). Safe to call when there is no worker."""
        w, self._worker = self._worker, None
        if w is not None:
            try:
                w.stop()
                w.wait(4000)
            except Exception:
                log.debug("worker stop failed", exc_info=True)

    def _on_reply(self, question, answer):
        self._append_answer(answer or "(no answer returned)")

    def _on_worker_error(self, msg):
        self._append_error(msg)
        # If the failure is an expired/invalid session, flip to the logged-out (red)
        # state and offer to re-authenticate.
        try:
            from src.gui.utils.notebooklm_client import is_auth_error
            if is_auth_error(msg):
                self._auth_verified = False
                self._refresh_login_state()
                self._reset_worker()          # drop the dead session
                self._prompt_reauth()
        except Exception:
            log.debug("auth-error detection failed", exc_info=True)

    def _on_busy(self, busy):
        """While a question is in flight the Send button becomes a light-blue **Stop
        thinking** button (still clickable) that cancels the request; otherwise it is
        the blue **Send** button."""
        self._thinking = busy
        self.send_button.setEnabled(True)
        self.send_button.setText("Stop thinking" if busy else "Send")
        style = getattr(self, "_stop_style" if busy else "_send_style", None)
        if style:
            self.send_button.setStyleSheet(style)

    def _stop_thinking(self):
        """Stop the in-flight NotebookLM question. The worker cancels its async call
        and emits busy(False), which flips the button back to Send."""
        if self._worker is not None:
            self._worker.cancel()
        self.send_button.setText("Stopping…")
        self.send_button.setEnabled(False)

    # ------------------------------------------------------------------ notebook
    def _on_set_notebook(self):
        text, ok = QInputDialog.getText(
            self, "NotebookLM notebook",
            "Notebook id or URL (leave empty to auto-pick a CWatM notebook):",
            text=self._notebook_id or "")
        if not ok:
            return
        self._notebook_id = (text or "").strip()
        self._settings.setValue("notebooklm/notebook_id", self._notebook_id)
        self.sub_label.setText(self._notebook_subtitle())
        self._reset_worker()
        self._append_status("Notebook updated - the next question will reconnect.")

    def _notebook_subtitle(self):
        if self._notebook_id:
            return f"Notebook: {self._notebook_id}"
        return "Notebook: auto (a notebook whose title contains 'CWatM')"

    # --------------------------------------------------------------------- login
    def _is_authenticated(self):
        try:
            from src.gui.utils.notebooklm_client import is_authenticated
            return is_authenticated()
        except Exception:
            return False

    @staticmethod
    def _playwright_available():
        """True if the Playwright package can be imported (needed for the
        interactive Google login window). Not bundled in the frozen build, so this
        is normally only true from source."""
        try:
            import importlib.util
            return importlib.util.find_spec("playwright") is not None
        except Exception:
            return False

    def _on_login(self):
        """One-click login: auto-detect the browser you are signed in to Google
        with. Tries Firefox → Chrome → Edge → Opera, verifying each session, and
        stops at the first that actually works. The old per-browser picker is the
        'Choose browser…' fallback (``_on_choose_browser``)."""
        if self._login_proc is not None or self._auto_login_active:
            QMessageBox.information(self, "Login", "A login is already running.")
            return
        # Already signed in? Re-login is unnecessary - offer to skip it.
        if self._is_authenticated() and self._auth_verified is not False:
            resp = QMessageBox.question(
                self, "Login",
                "You already have a working NotebookLM session - you can ask "
                "questions without logging in again.\n\nRe-login anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if resp != QMessageBox.Yes:
                return
        self._start_auto_login()

    # ------------------------------------------------------ auto-detect login
    def _start_auto_login(self):
        """Begin the one-click browser auto-detect sequence."""
        self._auto_login_active = True
        self._auto_saw_decrypt = False
        # Firefox first: its cookie store is readable without elevation, so it is
        # the most likely to succeed on Windows. Chromium browsers follow.
        self._auto_browsers = ["firefox", "chrome", "edge", "opera"]
        self._auto_index = 0
        self._append_status("Looking for a signed-in Google session in your browsers…")
        self._auto_try_next()

    def _auto_try_next(self):
        """Attempt the next browser in the list, or finish if none are left."""
        if self._auto_index >= len(self._auto_browsers):
            self._auto_login_failed()
            return
        browser = self._auto_browsers[self._auto_index]
        self._append_status(f"Trying {browser.capitalize()}…")
        self._run_login_process(["login", "--browser-cookies", browser])

    def _auto_after_login(self, exit_code, out):
        """Handle a browser-cookie login process that finished during auto-detect."""
        browser = self._auto_browsers[self._auto_index].capitalize()
        low = out.lower()
        # rookiepy missing is fatal for *every* browser path - stop the whole run.
        if "rookiepy is not installed" in out or "no module named 'rookiepy'" in low:
            self._auto_login_active = False
            self._append_error(
                "Reading browser cookies needs the 'rookiepy' package, which is "
                "not installed. Install it once with:\n"
                "    pip install rookiepy\n"
                "(or  pip install \"notebooklm-py[cookies]\" ), then try Login again.")
            self._refresh_login_state()
            return
        # Windows Chrome/Edge/Opera app-bound cookie encryption - note it so the
        # final message can point at 'Run as administrator' / Firefox.
        if ("could not decrypt" in low or "decrypt" in low or "app-bound" in low
                or "appbound" in low or "as admin" in low):
            self._auto_saw_decrypt = True
        # This browser produced a session file - verify it really works before
        # declaring success (cookies may exist but not authenticate NotebookLM).
        if exit_code == 0 and self._is_authenticated():
            self._append_status(f"Found a {browser} session — verifying…")
            self._auto_verify()
            return
        # No usable session from this browser - move on.
        self._auto_index += 1
        self._auto_try_next()

    def _auto_verify(self):
        """Verify the just-stored session against NotebookLM (off the GUI thread)."""
        self._auto_verifier = _AuthCheckWorker(parent=self)
        self._auto_verifier.result.connect(self._auto_on_verify)
        self._auto_verifier.finished.connect(
            lambda: setattr(self, "_auto_verifier", None))
        self._auto_verifier.start()

    def _auto_on_verify(self, status, message):
        browser = self._auto_browsers[self._auto_index].capitalize()
        if status == "ok":
            self._auto_login_active = False
            self._append_status(f"Logged in via {browser}.")
            self._auth_verified = True
            self._refresh_login_state()
            self._reset_worker()      # drop any stale worker…
            self._warm_worker()       # …and pre-connect with the fresh session
            return
        if status == "error":
            # Reached the server but it failed (network/proxy) - trying other
            # browsers cannot help, so stop and report it.
            self._auto_login_active = False
            self._append_error(message)
            self._refresh_login_state()
            return
        # "auth" / "no_session": these cookies don't authenticate - try the next.
        self._append_status(f"{browser}: no valid NotebookLM session.")
        self._auto_index += 1
        self._auto_try_next()

    def _auto_login_failed(self):
        """No browser yielded a working session - explain and offer the picker."""
        self._auto_login_active = False
        self._refresh_login_state()
        if self._auto_saw_decrypt:
            self._append_error(
                "Found Chrome / Edge / Opera but Windows encrypts their cookie "
                "store (app-bound encryption), so CWatM cannot read it. Either "
                "right-click CWatM and 'Run as administrator' and try Login again, "
                "or sign in to Google in Firefox (its cookies are readable without "
                "elevation).")
        else:
            self._append_error(
                "Could not find a signed-in Google session in Firefox, Chrome, "
                "Edge or Opera. Sign in to Google in one of them, then click Login "
                "again.")
        # Offer the manual picker (individual browsers / Google login window).
        resp = QMessageBox.question(
            self, "Login",
            "Automatic login could not find a working session.\n\n"
            "Choose a browser or the Google login window manually?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if resp == QMessageBox.Yes:
            self._on_choose_browser()

    # ---------------------------------------------------- manual browser picker
    def _on_choose_browser(self):
        """The explicit per-browser login dialog (Login…'s 'Choose browser…'
        fallback): pick a specific browser to read cookies from, or open the
        interactive Google login window."""
        if self._login_proc is not None or self._auto_login_active:
            QMessageBox.information(self, "Login", "A login is already running.")
            return
        # The interactive Google window needs Playwright (source only). The
        # browser-cookie options only need rookiepy, which IS bundled, so they work
        # from the frozen exe too (the login command runs via the exe's own
        # --notebooklm-login self-dispatch).
        has_google = self._playwright_available()
        box = QMessageBox(self)
        box.setWindowTitle("Login to NotebookLM")
        text = "Store a Google session for NotebookLM.\n\n"
        if has_google:
            text += ("• 'Google login window' opens a browser to sign in "
                     "(most reliable).\n")
        text += ("• The browser options read the Google cookies from a browser you "
                 "are already signed in to. Firefox works normally; on Windows the "
                 "Chromium browsers (Chrome / Edge / Opera) encrypt their cookie "
                 "store (app-bound encryption), so those can only be read when "
                 "CWatM is run as Administrator.")
        if not has_google:
            text += ("\n\nEasiest: sign in to Google in Firefox, then 'From "
                     "Firefox'. For Chrome / Edge / Opera, run CWatM as "
                     "Administrator first.")
        box.setText(text)
        google = (box.addButton("Google login window", QMessageBox.AcceptRole)
                  if has_google else None)
        firefox = box.addButton("From Firefox", QMessageBox.AcceptRole)
        chrome = box.addButton("From Chrome", QMessageBox.AcceptRole)
        edge = box.addButton("From Edge", QMessageBox.AcceptRole)
        opera = box.addButton("From Opera", QMessageBox.AcceptRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if google is not None and clicked is google:
            self._start_google_login()
        elif clicked is firefox:
            self._start_login("firefox")
        elif clicked is chrome:
            self._start_login("chrome")
        elif clicked is edge:
            self._start_login("edge")
        elif clicked is opera:
            self._start_login("opera")

    def _start_login(self, browser):
        self._append_status(f"Logging in (reading cookies from {browser})…")
        self._run_login_process(["login", "--browser-cookies", browser])

    def _start_google_login(self, force_chromium=False):
        """Login via the interactive Google window. Prefer the user's installed
        Google Chrome (``--browser chrome``, no download); fall back to the bundled
        Playwright Chromium (one-time ~150 MB download) if Chrome cannot be used."""
        if not force_chromium:
            self._google_login_stage = "chrome"
            self._append_status(
                "Opening the Google login window in Chrome - sign in there, then "
                "return here…")
            self._run_login_process(["login", "--browser", "chrome"])
            return
        # Fallback path: bundled Chromium (download it first if missing).
        self._google_login_stage = "chromium"
        if not self._chromium_installed():
            self._append_status("Downloading Chromium for the login window…")
            self._pending_google_login = True
            self._run_login_process(["install", "chromium"], module="playwright",
                                    is_chromium_install=True)
            return
        self._append_status(
            "Opening the Google login window - sign in there, then return here…")
        self._run_login_process(["login"])

    @staticmethod
    def _chromium_installed():
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                return os.path.exists(p.chromium.executable_path)
        except Exception:
            return False

    def _run_login_process(self, cli_args, module="notebooklm", is_chromium_install=False):
        """Run a CLI module (``notebooklm`` or ``playwright``) in a child process.

        From source: ``<python> -m <module> <cli_args>``. Frozen: there is no
        ``python -m`` inside the exe, so the **notebooklm** CLI is run by
        re-invoking THIS executable with the ``--notebooklm-login`` self-dispatch
        (see cwatm_gui.py). ``playwright`` has no such path when frozen (it is not
        bundled) - that only matters for the optional Google-window Chromium
        fallback, which is offered from source only."""
        self.login_button.setEnabled(False)
        self._login_output = ""
        self._login_is_chromium_install = is_chromium_install
        proc = QProcess(self)
        self._login_proc = proc
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(
            lambda p=proc: self._on_login_output(
                bytes(p.readAllStandardOutput()).decode(errors="ignore")))
        proc.finished.connect(
            lambda code, status: self._on_login_finished(int(code)))
        if _IS_FROZEN and module == "notebooklm":
            program, argv = sys.executable, ["--notebooklm-login"] + list(cli_args)
        else:
            program, argv = sys.executable, ["-m", module] + list(cli_args)
        proc.start(program, argv)

    def _on_login_output(self, chunk):
        self._login_output += chunk
        self._append_status(chunk.rstrip())

    def _on_login_finished(self, exit_code):
        self._login_proc = None
        self.login_button.setEnabled(True)
        out = getattr(self, "_login_output", "")

        # One-click auto-detect: this is one browser in the sequence - hand it to
        # the auto handler (which chains to the next browser or verifies success).
        if self._auto_login_active:
            self._auto_after_login(exit_code, out)
            return

        self._refresh_login_state()   # recolour Login blue/red by the new state

        # Step 1 of the Google-login path: a Chromium download just finished.
        if getattr(self, "_login_is_chromium_install", False):
            self._login_is_chromium_install = False
            if getattr(self, "_pending_google_login", False):
                self._pending_google_login = False
                if exit_code == 0 and self._chromium_installed():
                    self._append_status(
                        "Chromium ready. Opening the Google login window…")
                    self._run_login_process(["login"])
                else:
                    self._append_error(
                        "Chromium download failed. Try 'From Firefox' instead, or "
                        "run  python -m playwright install chromium  in a terminal.")
            return

        # The browser-cookie path needs rookiepy; surface a precise hint for that.
        if "rookiepy is not installed" in out or "No module named 'rookiepy'" in out:
            self._append_error(
                "Reading browser cookies needs the 'rookiepy' package, which is "
                "not installed. Install it once with:\n"
                "    pip install rookiepy\n"
                "(or  pip install \"notebooklm-py[cookies]\" ), then try Login again.")
            return
        # The Google-login window needs Playwright.
        if "playwright not installed" in out.lower() or \
                "no module named 'playwright'" in out.lower():
            self._append_error(
                "The Google login window needs the 'playwright' package, which is "
                "not installed. Install it once with:\n"
                "    pip install playwright\n"
                "then try Login again (or use 'From Firefox').")
            return

        if exit_code == 0 and self._is_authenticated():
            self._google_login_stage = None
            self._append_status("Logged in. Verifying the session…")
            self._auth_verified = None
            self._reset_worker()      # reconnect with the fresh session
            self._start_auth_check()  # confirm the new session really works (blue)
            return

        # The system-Chrome Google-login window failed (e.g. Chrome not found or
        # crashed) - offer the bundled Chromium instead.
        if getattr(self, "_google_login_stage", None) == "chrome":
            self._google_login_stage = None
            resp = QMessageBox.question(
                self, "Login",
                "Could not open the login window with your system Chrome.\n\n"
                "Try the bundled browser instead? (a one-time ~150 MB download "
                "may be needed)",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if resp == QMessageBox.Yes:
                self._start_google_login(force_chromium=True)
            return

        # Windows Chrome/Edge/Opera encrypt their cookie store (app-bound
        # encryption), so rookiepy can only read it when the process is elevated
        # ("... can be decrypted only when running as admin ...") - point the user
        # to the two working paths.
        if ("decrypt" in out.lower() or "could not decrypt" in out.lower()
                or "appbound" in out.lower() or "app-bound" in out.lower()
                or "as admin" in out.lower()):
            msg = ("On Windows, Chrome / Edge / Opera encrypt their cookie store "
                   "(app-bound encryption), so their cookies can only be read when "
                   "CWatM runs elevated. Either right-click CWatM and 'Run as "
                   "administrator', then try that browser again - or use 'From "
                   "Firefox' (Firefox cookies are readable without elevation).")
            if self._is_authenticated():
                self._append_status(
                    "The login command failed, but an existing NotebookLM session "
                    "is still available - you can ask questions. (" + msg + ")")
                self._reset_worker()
            else:
                self._append_error(msg)
            return

        if self._is_authenticated():
            # The command reported an error but a usable session already exists.
            self._append_status(
                "The login command failed, but an existing NotebookLM session is "
                "still available - you can ask questions.")
            self._reset_worker()
        else:
            self._append_error(
                "Login did not produce a session. Make sure you are signed in to "
                "Google in that browser, or use the Google login window.")

    # -------------------------------------------------------------------- misc
    def _on_clear(self):
        self.transcript.clear()

    def _stop_auth_check(self):
        for attr in ("_auth_checker", "_auto_verifier"):
            w = getattr(self, attr, None)
            setattr(self, attr, None)
            if w is not None:
                try:
                    w.wait(3000)
                except Exception:
                    log.debug("auth checker wait failed", exc_info=True)

    def closeEvent(self, event):
        self._save_state()      # keep transcript + history for next open
        self._stop_auth_check()
        self._reset_worker()
        super().closeEvent(event)

    def done(self, result):
        # Esc / accept / reject route through done(), not closeEvent - persist here
        # too (GeometryMemoryMixin.done then saves the geometry).
        self._save_state()
        self._stop_auth_check()
        self._reset_worker()
        super().done(result)
