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
    QPlainTextEdit, QMessageBox, QInputDialog, QButtonGroup, QFrame, QToolButton,
)
from PySide6.QtCore import Qt, QSettings, QProcess, QThread, Signal, QSize
from PySide6.QtGui import QIcon

from src.gui.utils import theme
from src.gui.utils.window_geometry import GeometryMemoryMixin, scaled_default_size
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


class BrowserPickerDialog(QDialog):
    """'Sign in to NotebookLM': one card per browser, with the browser's own icon
    (read from its installed exe); a browser that is not installed is shown
    greyed out. Click a card to choose it (``choice`` = its key)."""

    def __init__(self, browsers, last, parent=None):
        super().__init__(parent)
        from src.gui.utils.notebooklm_browser_login import browser_executable
        self.choice = None
        self.setWindowTitle("Sign in to NotebookLM")
        self.setModal(True)
        c = theme.c
        mix = NotebookLMWindow._mix
        font = "font-family: 'Segoe UI', sans-serif;"
        self.setStyleSheet(f"""
            QDialog {{ background-color: {c('window_bg')}; }}
            QLabel#title {{ {font} font-size: 17px; font-weight: 700; color: {c('text')}; }}
            QLabel#text {{ {font} font-size: 12px; color: {c('text_muted')}; }}
            QLabel#note {{ {font} font-size: 11px; color: {c('text_gray')}; }}
            QToolButton#card {{
                {font} font-size: 9pt; font-weight: 600; color: {c('text')};
                background-color: {c('panel_bg')};
                border: 1px solid {c('border')}; border-radius: 14px;
                padding: 14px 10px 10px 10px;
            }}
            QToolButton#card:hover {{
                border: 2px solid {c('accent')};
                background-color: {mix('panel_bg', 'accent', 0.06)};
            }}
            QToolButton#card:focus {{ border: 2px solid {c('accent')}; }}
            QToolButton#card:disabled {{
                color: {c('text_gray')}; background-color: {c('surface_bg')};
            }}
            QPushButton#ghost {{
                {font} font-size: 12px; color: {c('text_muted')};
                background: transparent; border: none; border-radius: 8px;
                padding: 6px 14px;
            }}
            QPushButton#ghost:hover {{
                background-color: {mix('window_bg', 'accent', 0.12)}; color: {c('text')};
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 16)
        lay.setSpacing(10)
        title = QLabel("Sign in to NotebookLM")
        title.setObjectName("title")
        lay.addWidget(title)
        text = QLabel("Choose the browser for Google's sign-in page. A separate window "
                      "opens - sign in there and it closes by itself.")
        text.setObjectName("text")
        text.setWordWrap(True)
        lay.addWidget(text)

        row = QHBoxLayout()
        row.setSpacing(14)
        first = None
        for key, (name, _label) in browsers.items():
            exe = browser_executable(key)
            btn = QToolButton()
            btn.setObjectName("card")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            btn.setIconSize(QSize(48, 48))
            btn.setMinimumSize(170, 120)
            if exe:
                from PySide6.QtWidgets import QFileIconProvider
                from PySide6.QtCore import QFileInfo
                btn.setIcon(QFileIconProvider().icon(QFileInfo(exe)))
                btn.setText(name)
                btn.clicked.connect(lambda _c=False, k=key: self._pick(k))
                if first is None or key == last:   # focus the last choice
                    first = btn
            else:
                btn.setText(f"{name}\nnot installed")
                btn.setEnabled(False)
            row.addWidget(btn)
        lay.addLayout(row)

        note = QLabel("🔒  Your everyday browser windows, cookies and passwords are not "
                      "touched. Your password goes only to Google.")
        note.setObjectName("note")
        note.setWordWrap(True)
        lay.addWidget(note)
        foot = QHBoxLayout()
        foot.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setObjectName("ghost")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        foot.addWidget(cancel)
        lay.addLayout(foot)
        if first is not None:
            first.setFocus()

    def _pick(self, key):
        self.choice = key
        self.accept()


class NotebookLMWindow(GeometryMemoryMixin, QDialog):
    """Non-modal Gemini/NotebookLM chat window (v1: ask → answer)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._settings = QSettings("IIASA", "CWatM_GUI")
        from src.gui.utils.notebooklm_client import saved_notebook
        self._notebook_id = saved_notebook(self._settings)
        self._worker = None
        self._login_proc = None
        self._login_browser = None    # key of LOGIN_BROWSERS the running login uses
        self._thinking = False        # a question is in flight (Send → Stop thinking)
        # Answer length ("short"/"long"); persisted. A stored "medium" (an older
        # choice) or anything unknown falls back to short.
        self._length_key = self._settings.value(
            "notebooklm/response_length", "short", type=str)
        if self._length_key not in ("short", "long"):
            self._length_key = "short"
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
            self.resize(*scaled_default_size(self, 720, 640))
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
            log.debug("_set_window_icon: ignored", exc_info=True)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # ---- Header card: icon + title/notebook, status pill, Login/Logout
        self.header_card = QFrame()
        self.header_card.setObjectName("aiCard")
        head = QHBoxLayout(self.header_card)
        head.setContentsMargins(14, 10, 12, 10)
        head.setSpacing(12)
        self.logo_label = QLabel()
        try:
            from src.gui.utils.assets import asset_path
            pix = QIcon(asset_path("cwatm.ico")).pixmap(36, 36)
            if not pix.isNull():
                self.logo_label.setPixmap(pix)
        except Exception:
            log.debug("CWatM AI logo not loaded", exc_info=True)
        head.addWidget(self.logo_label, 0, Qt.AlignVCenter)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.header_label = QLabel("CWatM AI")
        self.sub_label = QLabel(self._notebook_subtitle())
        titles.addWidget(self.header_label)
        titles.addWidget(self.sub_label)
        head.addLayout(titles, 1)
        # Login-state pill - clearly states whether you are signed in; colour set
        # in _refresh_login_state().
        self.status_label = QLabel("")
        head.addWidget(self.status_label, 0, Qt.AlignVCenter)
        self.login_button = QPushButton("Login")
        self.login_button.setCursor(Qt.PointingHandCursor)
        self.login_button.setToolTip(
            "Choose a browser (Edge / Chrome) - Google's sign-in page opens in it; "
            "sign in there")
        self.login_button.clicked.connect(self._on_login)
        head.addWidget(self.login_button, 0, Qt.AlignVCenter)
        layout.addWidget(self.header_card)

        # ---- Transcript (read-only, rich text: questions / answers / status)
        self.transcript = QTextBrowser()
        self.transcript.setObjectName("aiTranscript")
        # Links in AI answers come from outside: never straight to the desktop (a
        # file:// link to a program would run it) - open_link() decides (sast.md #4)
        from src.gui.utils.open_path import make_links_safe
        make_links_safe(self.transcript, intercept=self._on_followup_link)
        # Tighter paragraph/list spacing than Qt's 12 px default inside answers.
        self.transcript.document().setDefaultStyleSheet(
            "p { margin-top: 2px; margin-bottom: 6px; } "
            "ul, ol { margin-top: 2px; margin-bottom: 4px; }")
        layout.addWidget(self.transcript, 1)

        # ---- Tools row: explain chip, answer-length segmented control, Notebook/Clear
        self.explain_line_button = QPushButton("Explain current line")
        self.explain_line_button.setObjectName("chip")
        self.explain_line_button.setCursor(Qt.PointingHandCursor)
        self.explain_line_button.setToolTip(
            "Ask NotebookLM to explain the line the cursor is on in the settings file")
        self.explain_line_button.clicked.connect(self._cmd_explain_line)

        self.length_caption = QLabel("Answer length")
        self.length_group = QButtonGroup(self)
        self.length_group.setExclusive(True)
        self._length_buttons = {}
        segment = QHBoxLayout()
        segment.setSpacing(0)
        keys = (("short", "Short"), ("long", "Long"))
        for i, (key, label) in enumerate(keys):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(key == self._length_key)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setObjectName("segFirst" if i == 0 else
                             "segLast" if i == len(keys) - 1 else "segMid")
            btn.setToolTip(f"Ask NotebookLM for a {label.lower()} answer")
            btn.clicked.connect(lambda _c=False, k=key: self._on_length_selected(k))
            self.length_group.addButton(btn)
            self._length_buttons[key] = btn
            segment.addWidget(btn)

        self.notebook_button = QPushButton("Notebook…")
        self.notebook_button.setObjectName("ghost")
        self.notebook_button.setCursor(Qt.PointingHandCursor)
        self.notebook_button.setToolTip(
            "Set which NotebookLM notebook (or its URL) to ask")
        self.notebook_button.clicked.connect(self._on_set_notebook)
        self.clear_button = QPushButton("Clear")
        self.clear_button.setObjectName("ghost")
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.setToolTip("Clear the conversation")
        self.clear_button.clicked.connect(self._on_clear)

        tools_row = QHBoxLayout()
        tools_row.setSpacing(8)
        tools_row.addWidget(self.explain_line_button)
        tools_row.addSpacing(10)
        tools_row.addWidget(self.length_caption)
        tools_row.addLayout(segment)
        tools_row.addStretch()
        tools_row.addWidget(self.notebook_button)
        tools_row.addWidget(self.clear_button)
        layout.addLayout(tools_row)

        # ---- Composer: multi-line box with Send inside (Enter sends, Shift+Enter
        # = newline)
        self.composer = QFrame()
        self.composer.setObjectName("composer")
        comp = QHBoxLayout(self.composer)
        comp.setContentsMargins(10, 6, 6, 6)
        comp.setSpacing(8)
        self.input_box = QPlainTextEdit()
        self.input_box.setPlaceholderText(
            "Ask about CWatM…  (Enter to send, Shift+Enter for a new line)")
        self.input_box.setFixedHeight(58)
        self.input_box.installEventFilter(self)
        self.send_button = QPushButton("Send")
        self.send_button.setObjectName("primary")
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.clicked.connect(self._on_send)
        comp.addWidget(self.input_box, 1)
        comp.addWidget(self.send_button, 0, Qt.AlignBottom)
        layout.addWidget(self.composer)

    # ------------------------------------------------------------------ styling
    @staticmethod
    def _mix(token_a, token_b, t):
        """Blend two theme colours (t = share of b) - for hover / tint shades, so
        every colour still comes from the active theme."""
        from PySide6.QtGui import QColor
        a, b = QColor(theme.c(token_a)), QColor(theme.c(token_b))
        return QColor(round(a.red() + (b.red() - a.red()) * t),
                      round(a.green() + (b.green() - a.green()) * t),
                      round(a.blue() + (b.blue() - a.blue()) * t)).name()

    def _apply_theme(self):
        """Theme the window at construction time (like the other secondary
        windows) - every colour from a theme token, flat and rounded."""
        c, mix = theme.c, self._mix
        font = "font-family: 'Segoe UI', sans-serif;"
        self.setStyleSheet(f"""
            QDialog {{ background-color: {c('window_bg')}; }}
            QFrame#aiCard {{
                background-color: {c('panel_bg')};
                border: 1px solid {c('border')}; border-radius: 12px;
            }}
            QFrame#composer {{
                background-color: {c('panel_bg')};
                border: 1px solid {c('border')}; border-radius: 14px;
            }}
            QFrame#composer QPlainTextEdit {{
                background: transparent; border: none; color: {c('text')};
                {font} font-size: 13px; padding: 4px 2px;
            }}
            QPushButton#primary {{
                {font} font-size: 12px; font-weight: 600;
                color: {c('menu_sel_text')}; background-color: {c('accent')};
                border: none; border-radius: 10px; padding: 8px 18px; min-height: 22px;
            }}
            QPushButton#primary:hover {{ background-color: {mix('accent', 'panel_bg', 0.18)}; }}
            QPushButton#primary:pressed {{ background-color: {mix('accent', 'text', 0.2)}; }}
            QPushButton#primary:disabled {{
                background-color: {c('border')}; color: {c('text_gray')};
            }}
            QPushButton#secondary {{
                {font} font-size: 12px; font-weight: 600; color: {c('text')};
                background-color: {c('panel_bg')};
                border: 1px solid {c('border')}; border-radius: 10px;
                padding: 7px 16px; min-height: 22px;
            }}
            QPushButton#secondary:hover {{
                border-color: {c('accent')}; background-color: {c('surface_bg')};
            }}
            QPushButton#secondary:disabled {{ color: {c('text_gray')}; }}
            QPushButton#ghost {{
                {font} font-size: 12px; color: {c('text_muted')};
                background: transparent; border: none; border-radius: 8px;
                padding: 5px 10px;
            }}
            QPushButton#ghost:hover {{
                background-color: {mix('window_bg', 'accent', 0.12)}; color: {c('text')};
            }}
            QPushButton#chip {{
                {font} font-size: 12px; color: {c('accent')};
                background-color: {mix('panel_bg', 'accent', 0.08)};
                border: 1px solid {mix('panel_bg', 'accent', 0.35)};
                border-radius: 11px; padding: 3px 12px; min-height: 18px;
            }}
            QPushButton#chip:hover {{ background-color: {mix('panel_bg', 'accent', 0.18)}; }}
            QPushButton#segFirst, QPushButton#segMid, QPushButton#segLast {{
                {font} font-size: 11px; color: {c('text_muted')};
                background-color: {c('panel_bg')};
                border: 1px solid {c('border')}; padding: 4px 12px; min-height: 18px;
            }}
            QPushButton#segFirst {{
                border-top-left-radius: 13px; border-bottom-left-radius: 13px;
            }}
            QPushButton#segMid {{ border-left: none; }}
            QPushButton#segLast {{
                border-left: none;
                border-top-right-radius: 13px; border-bottom-right-radius: 13px;
            }}
            QPushButton#segFirst:hover, QPushButton#segMid:hover,
            QPushButton#segLast:hover {{ background-color: {c('surface_bg')}; }}
            QPushButton#segFirst:checked, QPushButton#segMid:checked,
            QPushButton#segLast:checked {{
                background-color: {c('accent')}; color: {c('menu_sel_text')};
                border-color: {c('accent')}; font-weight: 600;
            }}
        """)
        self.header_label.setStyleSheet(
            f"{font} font-size: 17px; font-weight: 700; color: {c('text')};")
        self.sub_label.setStyleSheet(
            f"{font} font-size: 11px; color: {c('text_gray')};")
        self.length_caption.setStyleSheet(
            f"{font} font-size: 11px; color: {c('text_gray')};")
        # Transcript: a flat card with the thin rounded accent scrollbar used by the
        # settings editor. One triple-quoted f-string (do NOT concatenate f-strings
        # with plain strings: a plain-string "}}" stays two braces and corrupts QSS).
        self.transcript.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {c('panel_bg')}; color: {c('text')};
                border: 1px solid {c('border')}; border-radius: 12px;
                padding: 10px 12px; {font} font-size: 13px;
                selection-background-color: {c('sel_bg')};
                selection-color: {c('sel_text')};
            }}
            QScrollBar:vertical {{
                background: transparent; width: 10px; margin: 6px 2px;
            }}
            QScrollBar::handle:vertical {{
                background-color: {mix('panel_bg', 'accent', 0.45)};
                border-radius: 4px; min-height: 28px;
            }}
            QScrollBar::handle:vertical:hover {{ background-color: {c('accent')}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
            QScrollBar:horizontal {{
                background: transparent; height: 10px; margin: 2px 6px;
            }}
            QScrollBar::handle:horizontal {{
                background-color: {mix('panel_bg', 'accent', 0.45)};
                border-radius: 4px; min-width: 28px;
            }}
            QScrollBar::handle:horizontal:hover {{ background-color: {c('accent')}; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}
        """)
        self._on_busy(self._thinking)
        # The login button + pill follow the sign-in state.
        self._refresh_login_state()

    def _style_length_buttons(self):
        """The segmented control styles itself through :checked - keep the checked
        button in step with the chosen length."""
        for key, btn in self._length_buttons.items():
            btn.setChecked(key == self._length_key)

    # ------------------------------------------------------------ login state UI
    def _refresh_login_state(self):
        """Set the Login button + status pill by the **verified** sign-in state.
        A stored session file alone only counts once confirmed valid; an
        expired/invalid session shows like being logged out."""
        has_file = self._is_authenticated()

        # The button has three faces: "Checking…" while a stored session is being
        # verified (disabled), "Logout" once it is confirmed, "Login" otherwise.
        if (has_file and self._auth_verified is None
                and not getattr(self, "_auth_unverifiable", False)):
            self.login_button.setText("Checking…")
            self.login_button.setToolTip("Verifying your NotebookLM session…")
            self.login_button.setObjectName("secondary")
            self.login_button.setEnabled(False)
            pill, colour = "Checking session…", "accent"
        elif self._auth_verified is True:
            self.login_button.setText("Logout")
            self.login_button.setToolTip(
                "Logged in to NotebookLM - click to log out (removes the stored "
                "Google session from this computer)")
            self.login_button.setObjectName("secondary")
            self.login_button.setEnabled(self._login_proc is None)
            pill, colour = "Logged in", "ok_color"
        else:
            # No session file, or a stored session that failed verification (expired).
            expired = has_file and self._auth_verified is False
            self.login_button.setText("Login")
            self.login_button.setToolTip(
                "Your NotebookLM session has expired - click to log in again."
                if expired else "Not logged in - click to sign in to NotebookLM.")
            self.login_button.setObjectName("primary")
            self.login_button.setEnabled(self._login_proc is None)
            pill, colour = (("Session expired", "out_error") if expired
                            else ("Not logged in", "text_gray"))
        # objectName changed -> re-polish so the stylesheet rule applies
        self.login_button.style().unpolish(self.login_button)
        self.login_button.style().polish(self.login_button)
        self.status_label.setText(f"●  {pill}")
        self.status_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 11px; font-weight: 600; "
            f"color: {theme.c(colour)}; "
            f"background-color: {self._mix('panel_bg', colour, 0.12)}; "
            "border-radius: 9px; padding: 3px 10px; min-height: 16px;")

    # -------------------------------------------------------- auth verification
    def _start_auth_check(self):
        """Verify the stored session against NotebookLM in the background."""
        if not self._is_authenticated():
            return                      # nothing to verify (no session file)
        if self._auth_checker is not None:
            return                      # already running
        self._auth_verified = None
        self._auth_unverifiable = False
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
        else:  # "error" - network/proxy issue; state unknown - note it and leave
            # "Checking…" (the button offers Login again).
            self._auth_unverifiable = True
            self._refresh_login_state()
            self._append_status(message)

    def _prompt_reauth(self):
        """Offer to log in again after detecting an expired session."""
        self._offer_login(
            "Your NotebookLM session has expired. Log in again now?")

    def _offer_login(self, text=None):
        """Ask whether to log in now (Google's sign-in page in a chosen browser)."""
        if self._login_proc is not None:
            return
        if text is None:
            text = ("You are not logged in to NotebookLM. CWatM AI needs a "
                    "Google login to answer questions.\n\nLog in now?")
        resp = QMessageBox.question(
            self, "NotebookLM login",
            text + "\n\nGoogle's sign-in page opens in a browser you choose.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if resp == QMessageBox.Yes:
            self._choose_browser_and_login()

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
                self.transcript.setHtml(html)  # html-safe: our own transcript (escaped / html=False markdown); links via open_link
                sb = self.transcript.verticalScrollBar()
                sb.setValue(sb.maximum())
                restored = True
                self._exchange_done = True   # set the first new question apart
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
    def _append_html(self, html, transient=False):
        """Append to the transcript. A ``transient`` line (the worker's
        "Connecting…" / "Thinking…" progress notes) is removed again as soon as
        anything else is appended - e.g. the answer."""
        self._drop_transient()
        doc = self.transcript.document()
        start = doc.characterCount() - 1
        if transient:
            self._transient_from = start
        self.transcript.append(html)  # html-safe: callers escape (_esc) or render markdown with html=False
        self._squash_spacer_blocks(start)
        sb = self.transcript.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _squash_spacer_blocks(self, start):
        """append() of a table leaves an empty paragraph before and after it, each a
        full text line high - that read as blank lines between every message. Make
        those empty (non-table) blocks 2 px high so only the blocks' own margins
        separate the messages."""
        from PySide6.QtGui import QTextBlockFormat, QTextCursor
        block = self.transcript.document().findBlock(max(0, start))
        while block.isValid():
            cur = QTextCursor(block)
            if not block.text() and cur.currentTable() is None:
                fmt = block.blockFormat()
                fmt.setTopMargin(0)
                fmt.setBottomMargin(0)
                fmt.setLineHeight(
                    0, QTextBlockFormat.LineHeightTypes.FixedHeight.value)
                cur.setBlockFormat(fmt)
                cf = cur.blockCharFormat()
                cf.setFontPointSize(1)
                cur.setBlockCharFormat(cf)
            block = block.next()

    def _drop_transient(self):
        """Remove the transient progress lines appended since the last real one."""
        start = getattr(self, "_transient_from", None)
        self._transient_from = None
        if start is None:
            return
        from PySide6.QtGui import QTextCursor
        cur = QTextCursor(self.transcript.document())
        cur.setPosition(max(0, start))
        cur.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
        cur.removeSelectedText()

    # The worker's progress notes - shown while waiting, removed with the answer.
    _TRANSIENT_STATUS = {"Connecting to NotebookLM…", "Connected.", "Ready.",
                         "Thinking…"}

    def _on_worker_status(self, text):
        if text in self._TRANSIENT_STATUS:
            self._append_status(text, transient=True)
        else:
            self._append_status(text)
            if text == "Stopped.":            # a stopped question ends the exchange too
                self._exchange_done = True

    def _exchange_separator(self):
        """A bold accent line before a new question / explain request, once an
        answer (or error) closed the previous exchange - so each question + answer
        is clearly set apart."""
        if not getattr(self, "_exchange_done", False):
            return
        self._exchange_done = False
        self._append_html(
            f'<table width="100%" cellspacing="0" cellpadding="0" '
            f'style="margin-top:16px; margin-bottom:4px;"><tr>'
            f'<td bgcolor="{theme.c("accent")}" style="font-size:3px;">&nbsp;</td>'
            f'</tr></table>')

    # Chat blocks. Qt rich text knows tables + cell colours but no border-radius, so
    # a message is a one-row table: a tinted block for your question (right), a
    # thin accent bar + soft block for the answer, small centred status lines.
    def _block(self, body, bar, bg, label, label_colour, indent=0):
        left = f'<td width="{indent}%"></td>' if indent else ""
        bar_td = f'<td width="3" bgcolor="{bar}"></td>' if bar else ""
        return (f'<table width="100%" cellspacing="0" cellpadding="0" '
                f'style="margin-top:10px;"><tr>{left}{bar_td}'
                f'<td bgcolor="{bg}" style="padding:8px 12px;">'
                f'<p style="margin-top:0; margin-bottom:4px; font-size:11px; '
                f'font-weight:600; color:{label_colour};">'
                f'{label}</p>{body}</td></tr></table>')

    def _append_status(self, text, transient=False):
        # a table cell: a bare <p align="center"> loses its alignment in append()
        self._append_html(
            f'<table width="100%" cellspacing="0" cellpadding="0" '
            f'style="margin-top:2px;"><tr><td align="center" style="font-size:11px; '
            f'color:{theme.c("text_gray")};">{self._esc(text)}</td></tr></table>',
            transient=transient)

    def _append_error(self, text):
        c = theme.c
        self._append_html(self._block(
            self._esc(text), c("out_error"), self._mix("panel_bg", "out_error", 0.08),
            "Error", c("out_error")))
        self._exchange_done = True

    def _append_label_line(self, label, text=""):
        """A notice with a bold accent label and the body text - e.g. 'Explaining
        settings line: <line>'."""
        body = ""
        if text:
            body = (f' <span style="color:{theme.c("text")}; font-family:Consolas,'
                    f'monospace;">{self._esc(text)}</span>')
        self._exchange_separator()
        self._append_html(
            f'<p style="margin-top:10px;"><b style="color:{theme.c("accent")};">'
            f'{self._esc(label)}</b>{body}</p>')

    def _append_question(self, text):
        c = theme.c
        self._exchange_separator()
        self._append_html(self._block(
            self._esc(text), None, self._mix("panel_bg", "accent", 0.10),
            "You", c("accent"), indent=18))

    def _append_answer(self, text):
        # NotebookLM answers are markdown - render them so bold/lists/tables/code show.
        c = theme.c
        body_text, followup, icon = self._split_followup_icon(text)
        body = self._render_markdown(body_text)
        if followup:
            body += self._followup_html(followup, icon)
        self._append_html(self._block(
            body, c("accent"), c("surface_bg"), "CWatM AI", c("text_gray")))
        self._exchange_done = True

    # ------------------------------------------------- follow-up offer (clickable)
    _FOLLOWUP_SCHEME = "cwatmai"

    @classmethod
    def _split_followup(cls, text):
        """NotebookLM often ends an answer with an offer such as "💡 Would you like
        to review how to set up the SpinUp?". Return (rest, question) when the last
        sentence is such a question, else (text, None)."""
        rest, question, _icon = cls._split_followup_icon(text)
        return rest, question

    _DEFAULT_FOLLOWUP_ICON = "💬"

    @staticmethod
    def _split_followup_icon(text):
        """Like ``_split_followup`` plus the pictogram NotebookLM put in front of
        the question (or None) - (rest, question, icon)."""
        text = (text or "").replace("\r\n", "\n").rstrip()
        # The offer is the LAST sentence of the answer - often at the end of the
        # last paragraph, not a paragraph of its own. Citation marks ([1], [2, 3])
        # and markdown emphasis may follow or wrap it.
        m = re.search(
            r"(?:^|(?<=[.!?:)\]])\s+|\n)"              # sentence / line start
            r"([^\w\n]*"                # pictogram, emphasis / list / quote marks
            r"((?:would|do|shall|should|can|could|are|is|want|may|if you|let me)"
            r"\b[^\n?]{3,300}\?)"                      # the question itself
            r"[*_\s]*(?:\[\d+(?:\s*[,-]\s*\d+)*\][*_\s]*)*)$",
            text, re.I)
        if not m:
            return text, None, None
        question = re.sub(r"\s*\[\d+(?:\s*[,-]\s*\d+)*\]", "", m.group(2))
        question = question.strip().strip("*_").strip()
        # The answer's own pictogram (anything but markdown marks and spaces).
        prefix = text[m.start(1):m.start(2)]
        icon = re.sub(r"[\s*_>#\-]", "", prefix) or None
        rest = text[:m.start(1)].rstrip()
        return rest, question, icon

    def _followup_html(self, question, icon=None):
        """The follow-up offer: a clickable pictogram (the answer's own, else 💬)
        + the question as plain text. The pictogram asks it
        (``_on_followup_link``; the question travels in the URL, so a restored
        transcript keeps working)."""
        from urllib.parse import quote
        href = f"{self._FOLLOWUP_SCHEME}:ask?q={quote(question, safe='')}"
        icon = self._esc(icon or self._DEFAULT_FOLLOWUP_ICON)
        return (f'<p style="margin-top:6px; margin-bottom:0;">'
                f'<a href="{href}" style="text-decoration:none; font-size:15px;">'
                f'{icon}</a>&nbsp;{self._esc(question)}</p>')

    def _on_followup_link(self, url):
        """A click on a follow-up offer: ask it. Other links -> False (open_link)."""
        if url.scheme().lower() != self._FOLLOWUP_SCHEME:
            return False
        from urllib.parse import parse_qs
        q = (parse_qs(url.query()).get("q") or [""])[0].strip()
        if q and not self._thinking:
            self._submit_question(f"Yes, please. {q}", echo=True)
        return True

    @staticmethod
    def _render_markdown(text):
        """Render markdown answer text to HTML (GitHub-flavoured: bold, lists,
        tables, code). Falls back to escaped text if markdown-it is unavailable."""
        text = text or ""
        try:
            from markdown_it import MarkdownIt
            # html=False: raw HTML in an answer is shown as text, never rendered -
            # the answer comes from outside (the preset would otherwise allow it)
            md = MarkdownIt("gfm-like", {"breaks": True, "linkify": False,
                                         "html": False})
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
        # Known to be logged out (no session file, or one that failed
        # verification): guide to the login instead of a cryptic server error.
        if not self._is_authenticated() or self._auth_verified is False:
            self._append_error(
                "You are not logged in to NotebookLM - log in first (Login button), "
                "then ask again.")
            self._offer_login()
            return
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
        self._worker.status.connect(self._on_worker_status)
        self._worker.reply.connect(self._on_reply)
        self._worker.error.connect(self._on_worker_error)
        self._worker.busy.connect(self._on_busy)
        self._worker.start()

    def _warm_worker(self):
        """Pre-connect the NotebookLM worker in the background (once the session is
        confirmed valid) so the first question skips the connect round-trips.
        No-op while a question is in flight or a login is running."""
        if self._thinking or self._login_proc is not None:
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
        # If the failure is an expired/invalid session, flip to the logged-out (red)
        # state and offer to re-authenticate.
        try:
            from src.gui.utils.notebooklm_client import is_auth_error
            auth = is_auth_error(msg)
        except Exception:
            log.debug("auth-error detection failed", exc_info=True)
            auth = False
        self._append_error(
            "You are not logged in to NotebookLM (the stored session is invalid or "
            "expired) - log in again with the Login button." if auth else msg)
        try:
            if auth:
                self._auth_verified = False
                self._refresh_login_state()
                self._reset_worker()          # drop the dead session
                self._prompt_reauth()
        except Exception:
            log.debug("auth-error detection failed", exc_info=True)

    def _on_busy(self, busy):
        """While a question is in flight the Send button becomes an outlined **Stop
        thinking** button (still clickable) that cancels the request; otherwise it is
        the accent **Send** button."""
        self._thinking = busy
        if not busy:
            self._drop_transient()    # a finished question never leaves "Thinking…"
        self.send_button.setEnabled(True)
        self.send_button.setText("Stop thinking" if busy else "Send")
        self.send_button.setObjectName("secondary" if busy else "primary")
        self.send_button.style().unpolish(self.send_button)
        self.send_button.style().polish(self.send_button)

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
            "Notebook id or URL (leave empty for the default CWatM notebook):",
            text=self._notebook_id or "")
        if not ok:
            return
        from src.gui.utils.notebooklm_client import NOTEBOOK_SETTINGS_KEY
        self._settings.setValue(NOTEBOOK_SETTINGS_KEY, (text or "").strip())
        self.set_notebook(text)

    def set_notebook(self, text):
        """Switch to another notebook (link or id; empty = the default) - also
        called by Preferences > Editor & Dates > NotebookLM while this window is open."""
        from src.gui.utils.notebooklm_client import DEFAULT_NOTEBOOK
        new = (text or "").strip() or DEFAULT_NOTEBOOK
        if new == self._notebook_id:
            return
        self._notebook_id = new
        self.sub_label.setText(self._notebook_subtitle())
        self._reset_worker()
        self._append_status("Notebook updated - the next question will reconnect.")

    def _notebook_subtitle(self):
        if self._notebook_id:
            from src.gui.utils.notebooklm_client import _extract_notebook_id
            return f"Notebook: {_extract_notebook_id(self._notebook_id)}"
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
        """True if the Playwright package can be imported - it drives the browser
        window of the Google login. Not bundled in the frozen build."""
        try:
            import importlib.util
            return importlib.util.find_spec("playwright") is not None
        except Exception:
            return False

    # The browsers the Google login can open in: key -> (button text, label used
    # in the login script's "<label> not found." message). Both are driven by
    # src/gui/utils/notebooklm_browser_login.py (the keys are its BROWSERS keys).
    # Each is the INSTALLED browser in a fresh private session - nothing is
    # downloaded, and no browser's cookies or data are ever read.
    LOGIN_BROWSERS = {
        "msedge": ("Microsoft Edge", "Microsoft Edge"),
        "chrome": ("Google Chrome", "Google Chrome"),
    }
    _LOGIN_BROWSER_KEY = "notebooklm/login_browser"

    def _on_login(self):
        """The Login / Logout button: logged in (verified) → log out; otherwise
        choose a browser and sign in on Google's page in it."""
        if self._login_proc is not None:
            QMessageBox.information(self, "Login", "A login is already running.")
            return
        if self._auth_verified is True:
            self._logout()
            return
        # Not verified as working: a session file alone proves nothing (it may be
        # stale or unverifiable), so the Login button always starts the login.
        self._choose_browser_and_login()

    def _logout(self):
        """Logout: ask, then remove the stored Google session (notebooklm's own
        logout - session file, login-window profile, context cache)."""
        resp = QMessageBox.question(
            self, "Logout",
            "Log out of NotebookLM?\n\nThe stored Google session is removed from "
            "this computer; you will need to sign in again to ask questions.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if resp != QMessageBox.Yes:
            return
        self._reset_worker()          # the worker holds the old session
        from src.gui.utils.notebooklm_client import logout
        error = logout()
        self._auth_verified = None
        self._auth_unverifiable = False
        self._refresh_login_state()
        if error:
            self._append_error(f"Logout failed: {error}")
        else:
            self._append_status("Logged out of NotebookLM.")

    def _choose_browser_and_login(self):
        if not self._playwright_available():
            self._append_error(
                "The Google login needs the 'playwright' package, which is not "
                "installed. Install it once with:\n"
                "    pip install playwright\n"
                "then try Login again.")
            return
        if not self._window_login_agreed():
            return
        browser = self._ask_login_browser()
        if browser:
            self._start_window_login(browser)

    def _ask_login_browser(self):
        """The browser picker (``BrowserPickerDialog``); returns a LOGIN_BROWSERS
        key or None (cancel). The last choice is pre-selected."""
        last = self._settings.value(self._LOGIN_BROWSER_KEY, "msedge", type=str)
        dlg = BrowserPickerDialog(self.LOGIN_BROWSERS, last, self)
        key = dlg.choice if dlg.exec() == QDialog.Accepted else None
        if key:
            self._settings.setValue(self._LOGIN_BROWSER_KEY, key)
        return key

    # ------------------------------------------------- what a login stores (once)
    @staticmethod
    def session_file_text():
        """Where the Google session is kept, for the user (security.md #5)."""
        try:
            from notebooklm.paths import get_storage_path
            return str(get_storage_path())
        except Exception:
            return r"%USERPROFILE%\.notebooklm\profiles\…\storage_state.json"

    _WINDOW_CONSENT_KEY = "notebooklm/window_login_agreed"

    @classmethod
    def window_login_text(cls):
        return ("CWatM AI logs in to NotebookLM through Google's own sign-in page:\n\n"
                "• You choose a browser (Edge or Chrome); a separate window "
                "of it opens on Google's sign-in page - sign in there, it closes by "
                "itself. Your password goes only to Google.\n"
                "• None of your browsers' cookies or data are read.\n"
                "• It STORES the Google session in a file on this computer:\n"
                f"   {cls.session_file_text()}\n"
                "  Anyone - or any program - with access to your Windows account could "
                "use that file to act as your Google account. Delete the file (or the "
                ".notebooklm folder) to remove it.\n"
                "• The session is used only to ask NotebookLM; it is never sent to the "
                "CWatM account server or anywhere else.")

    def _window_login_agreed(self):
        """Ask once, before the first login; the answer is remembered."""
        if self._settings.value(self._WINDOW_CONSENT_KEY, False, type=bool):
            return True
        resp = QMessageBox.question(
            self, "Login to NotebookLM",
            self.window_login_text() + "\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if resp != QMessageBox.Yes:
            return False
        self._settings.setValue(self._WINDOW_CONSENT_KEY, True)
        return True

    # ------------------------------------------------------------ the login run
    def _start_window_login(self, browser):
        label = self.LOGIN_BROWSERS[browser][1]
        self._login_browser = browser
        self._append_status(
            f"Opening Google's sign-in page in {label} - sign in there, then "
            "return here…")
        self._run_login_process(browser)

    def _run_login_process(self, browser):
        """Run the login in a child process (it opens the browser window and
        writes the session file, then exits - the GUI stays responsive):
        ``<python> -u notebooklm_browser_login.py <browser>``, or frozen
        ``CWatM_GUI.exe --notebooklm-browser-login <browser>`` (see cwatm_gui.py)."""
        self.login_button.setEnabled(False)
        self._login_output = ""
        proc = QProcess(self)
        self._login_proc = proc
        proc.setProcessChannelMode(QProcess.MergedChannels)
        proc.readyReadStandardOutput.connect(
            lambda p=proc: self._on_login_output(
                bytes(p.readAllStandardOutput()).decode(errors="ignore")))
        proc.finished.connect(
            lambda code, status: self._on_login_finished(int(code)))
        if _IS_FROZEN:
            argv = ["--notebooklm-browser-login", browser]
        else:
            from src.gui.utils import notebooklm_browser_login
            argv = ["-u", notebooklm_browser_login.__file__, browser]
        proc.start(sys.executable, argv)

    def _on_login_output(self, chunk):
        self._login_output += chunk
        # one status line per printed line - no blank lines in the transcript
        text = "\n".join(ln.strip() for ln in chunk.splitlines() if ln.strip())
        if text:
            self._append_status(text)

    def _on_login_finished(self, exit_code):
        self._login_proc = None
        self.login_button.setEnabled(True)
        out = getattr(self, "_login_output", "")
        low = out.lower()
        browser, self._login_browser = self._login_browser, None
        label = self.LOGIN_BROWSERS.get(browser, ("", "the browser"))[1]
        self._refresh_login_state()   # recolour Login blue/red by the new state

        if exit_code == 0 and self._is_authenticated():
            self._append_status("Logged in. Verifying the session…")
            self._auth_verified = None
            self._reset_worker()      # reconnect with the fresh session
            self._start_auth_check()  # confirm the new session really works (blue)
            return
        if "playwright not installed" in low or "no module named 'playwright'" in low:
            self._append_error(
                "The Google login needs the 'playwright' package, which is not "
                "installed. Install it once with:\n"
                "    pip install playwright\n"
                "then try Login again.")
            return
        if "browser window was closed" in low:
            self._append_status("Login cancelled - the login window was closed.")
            return
        if f"{label} not found".lower() in low:
            self._append_error(f"{label} is not installed on this computer.")
            resp = QMessageBox.question(
                self, "Login",
                f"{label} is not installed on this computer.\n\n"
                "Choose another browser?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if resp == QMessageBox.Yes:
                self._choose_browser_and_login()
            return
        if "login not detected" in low:
            self._append_error("No login within 5 minutes - press Login to try again.")
            return
        if self._is_authenticated():
            # The command reported an error but a usable session already exists.
            self._append_status(
                "The login did not finish, but an existing NotebookLM session is "
                "still available - you can ask questions.")
            self._reset_worker()
        else:
            self._append_error(
                f"The login in {label} did not produce a session. Press Login to "
                "try again, or choose another browser.")

    # -------------------------------------------------------------------- misc
    def _on_clear(self):
        self.transcript.clear()
        self._transient_from = None
        self._exchange_done = False

    def _stop_auth_check(self):
        for attr in ("_auth_checker",):
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
