"""The CWatM account windows: the login dialog and the account window.

``LoginDialog`` - tabs *Log in* / *Register* / *Forgot password*. Register and Forgot
password have a second step where the 6-digit code from the email is entered (the
emails carry a code, not a link - a desktop app cannot receive a link).

``AccountWindow`` - the logged-in user's points, badges and profile, plus Log out,
Export my data and Delete account.

Both talk to the server only through the main window's ``AccountWorker``
(``mw.account_worker()``): a request is ``submit``-ted, the buttons are disabled
until the answer for *that* operation arrives (``_pending``), and answers for other
operations - e.g. the main window's own re-login - are ignored. The main window's
``AccountMixin`` receives the same answers and keeps the menu-bar button and the
login state up to date, so these windows never set that state themselves.

Built fresh on every open (theme tokens read at construction, like every secondary
window).
"""

import json

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                               QLabel, QLineEdit, QPushButton, QCheckBox, QTabWidget,
                               QStackedWidget, QProgressBar, QFrame, QMessageBox,
                               QInputDialog, QFileDialog, QTableWidget,
                               QTableWidgetItem, QHeaderView, QAbstractItemView,
                               QGridLayout)

from src.gui.utils import theme, account_config, i18n, account_validation as V
from src.gui.utils.gui_log import get_logger
from src.gui.utils.window_geometry import scaled_default_size

log = get_logger("account_dialogs")

PRIVACY_TEXT = (
    "Stored on the CWatM account server (Supabase, in the EU - Frankfurt): your "
    "username, email address and the optional name, country and institute; for every "
    "counted run only the day and a one-way fingerprint of the settings (one point "
    "per distinct setup); for a CWatM Academy level only which level it was. "
    "No file paths, settings files or model data. You can export or delete all "
    "your data at any time in the account window.")

LOCATION_TEXT = (
    "For every run that earns a badge point, the location of its first gauge (rounded to about "
    "100 m) is counted anonymously - stored without your name or account, only as "
    "'a run at this place in this month'. It shows IIASA where CWatM is used. "
    "Can be switched off later in the account window.")


class _ClickableLabel(QLabel):
    """A QLabel that reports a left click (the badge image)."""
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def _medal_label(parent, code, size, faded=False, label_cls=QLabel):
    """The round medal (or a large 🏅 without an image) in a size x size label."""
    from src.gui.utils.badge_images import badge_pixmap
    img = label_cls()
    img.setAlignment(Qt.AlignCenter)
    img.setFixedSize(size, size)
    pix = badge_pixmap(code, size, faded=faded, dpr=parent.devicePixelRatioF())
    if pix is not None:
        img.setPixmap(pix)
    else:
        img.setText("🏅")
        img.setStyleSheet(f"font-size: {int(size * 0.6)}px;")
        if faded:
            # a colour emoji ignores the text colour - fade the whole label instead
            from PySide6.QtWidgets import QGraphicsOpacityEffect
            effect = QGraphicsOpacityEffect(img)
            effect.setOpacity(0.3)
            img.setGraphicsEffect(effect)
    return img


def badge_tile(parent, code, name, size, faded=False, caption=None, on_click=None):
    """One badge: the round medal image (or a large 🏅 when there is no image), its
    name below, and an optional caption (e.g. the points still needed). With
    ``on_click`` the medal is clickable (hand cursor) - used to enlarge it."""
    tile = QWidget(parent)
    lay = QVBoxLayout(tile)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(2)
    img = _medal_label(parent, code, size, faded,
                       _ClickableLabel if on_click else QLabel)
    tip = name if not caption else f"{name} ({caption})"
    if on_click:
        img.setCursor(Qt.PointingHandCursor)
        img.clicked.connect(on_click)
        tip += " - click to enlarge"
    img.setToolTip(tip)
    lay.addWidget(img, 0, Qt.AlignHCenter)
    lbl = QLabel(name)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setStyleSheet(f"font-weight: 600; color: "
                      f"{theme.c('text_gray') if faded else theme.c('text')};")
    lay.addWidget(lbl)
    if caption:
        cap = QLabel(caption)
        cap.setAlignment(Qt.AlignCenter)
        cap.setObjectName("accNote")
        lay.addWidget(cap)
    tile.setFixedWidth(max(size, 96))
    return tile


class BadgeViewer(QDialog):
    """An earned badge, large: the medal at BIG px, its name, when it was earned and
    how many points it needed. A click anywhere or Esc closes it."""

    BIG = 320            # px - the source pictures are 350 px, so it stays sharp

    def __init__(self, parent, code, name, awarded_at=None, points_required=None):
        super().__init__(parent)
        self.setWindowTitle(name)
        self.setAttribute(Qt.WA_DeleteOnClose)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(8)
        self.code = code
        self.medal = _medal_label(self, code, self.BIG)
        lay.addWidget(self.medal, 0, Qt.AlignHCenter)
        title = QLabel(name)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"color: {theme.c('accent')}; font-size: 22px; "
                            "font-weight: 700;")
        lay.addWidget(title)
        when = _format_date(awarded_at)
        if when:
            note = QLabel(f"Earned on {when}")
            note.setAlignment(Qt.AlignCenter)
            note.setStyleSheet(f"color: {theme.c('text_gray')};")
            lay.addWidget(note)
        # the points the badge needed - filled later when the ladder arrives
        self.points_note = QLabel("")
        self.points_note.setAlignment(Qt.AlignCenter)
        self.points_note.setStyleSheet(f"color: {theme.c('text_gray')};")
        lay.addWidget(self.points_note)
        self.set_points(points_required)
        self.setToolTip("Click to close")

    def set_points(self, points_required):
        """Show '<n> points needed for this badge' (hidden while unknown)."""
        if points_required is None:
            self.points_note.setVisible(False)
            return
        n = int(points_required)
        self.points_note.setText(
            f"{n} point{'s' if n != 1 else ''} needed for this badge")
        self.points_note.setVisible(True)

    def mousePressEvent(self, event):
        self.accept()


def _format_date(value):
    """'2026-09-28T11:03:12.5+00:00' -> '28 September 2026' ('' when missing)."""
    if not value:
        return ""
    import datetime
    try:
        d = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)[:10]
    return f"{d.day} {d.strftime('%B %Y')}"


class _AccountDialogBase(QDialog):
    """Shared plumbing: worker hookup, the pending operation, the status line."""

    def __init__(self, mw, title):
        super().__init__(mw)
        self.mw = mw
        self.setWindowTitle(title)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._pending = None
        self._action_buttons = []
        self.worker = mw.account_worker()
        self.worker.succeeded.connect(self._on_succeeded)
        self.worker.failed.connect(self._on_failed)

        self.status = QLabel("")
        self.status.setObjectName("accStatus")
        self.status.setWordWrap(True)

    # ---- requests ----------------------------------------------------------------
    def _run(self, op, *args, **kwargs):
        self._pending = op
        self._set_busy(True)
        self._say("Please wait…", "text_gray")
        self.worker.submit(op, *args, **kwargs)

    def _set_busy(self, busy):
        for b in self._action_buttons:
            b.setEnabled(not busy)

    def _say(self, text, token="text_gray"):
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {theme.c(token)};")

    def _problem(self, message):
        """Local input check failed: show it, send nothing."""
        self._say(message, "warn_color")

    def _on_succeeded(self, op, result):
        if op != self._pending:
            return
        self._pending = None
        self._set_busy(False)
        self._say("")
        self.handle_result(op, result)

    def _on_failed(self, op, code, message):
        if op != self._pending:
            return
        self._pending = None
        self._set_busy(False)
        self._say(message, "warn_color")
        self.handle_error(op, code, message)

    def handle_result(self, op, result):
        """Subclasses: an answer for the pending operation arrived."""

    def handle_error(self, op, code, message):
        """Subclasses: the pending operation failed (message already shown)."""

    # ---- building blocks ---------------------------------------------------------
    def _button(self, text, slot):
        # No default/auto-default button: Enter is handled by the fields'
        # returnPressed - a default button as well would submit the request twice.
        b = QPushButton(text)
        b.clicked.connect(slot)
        b.setDefault(False)
        b.setAutoDefault(False)
        self._action_buttons.append(b)
        return b

    @staticmethod
    def _password_edit():
        e = QLineEdit()
        e.setEchoMode(QLineEdit.Password)
        return e

    def _apply_style(self):
        self.setStyleSheet(f"""
            QLabel#accHead {{
                color: {theme.c('accent')};
                font-size: 18px;
                font-weight: 700;
            }}
            QLabel#accNote {{ color: {theme.c('text_gray')}; }}
            QLabel#accBadges {{ font-size: 14px; }}
            QFrame#accLine {{ color: {theme.c('border')}; }}
        """)

    def _fit(self, base_w, base_h):
        """The screen-scaled default size, but never smaller than the content - on a
        small screen the scaled default cut off the register form."""
        w, h = scaled_default_size(self, base_w, base_h)
        hint = self.sizeHint()
        self.resize(max(w, hint.width()), max(h, hint.height()))

    def _line(self):
        f = QFrame()
        f.setObjectName("accLine")
        f.setFrameShape(QFrame.HLine)
        return f

    def _note(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("accNote")
        lbl.setWordWrap(True)
        return lbl

    def _privacy_link(self):
        """'Read the full privacy notice' - opens it in the Help viewer."""
        # rich text (a link) is not reached by the language filter - translate here;
        # the window is built fresh on every open, so this follows a language switch
        lbl = QLabel(f'<a href="privacy" style="color: {theme.c("link_color")};">'
                     f'{i18n.tr("Read the full privacy notice")}</a>')
        lbl.setTextInteractionFlags(Qt.LinksAccessibleByMouse
                                    | Qt.LinksAccessibleByKeyboard)
        lbl.linkActivated.connect(lambda _href: self._show_privacy())
        return lbl

    def _show_privacy(self):
        try:
            self.mw.show_account_privacy()
        except Exception:
            log.warning("could not open the privacy notice", exc_info=True)

    def _logged_in_message(self, result):
        name = (result.get("profile") or {}).get("username", "")
        try:
            self.mw.status_bar.showMessage(f"Logged in to the CWatM account as {name}",
                                           6000)
        except Exception:
            log.debug("status bar message failed", exc_info=True)


class LoginDialog(_AccountDialogBase):
    """Log in / Register / Forgot password (see the module docstring)."""

    def __init__(self, mw):
        super().__init__(mw, "CWatM account")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 12)
        head = QLabel("CWatM account")
        head.setObjectName("accHead")
        outer.addWidget(head)
        outer.addWidget(self._note(
            "Optional: logged in, every full CWatM run earns a point, and points earn "
            "river badges - from the Breg to the Amazonas."))

        self.tabs = QTabWidget()
        # tab titles are not reached by the language filter - translate here
        self.tabs.addTab(self._tab_login(), i18n.tr("Log in"))
        self.tabs.addTab(self._tab_register(), i18n.tr("Register"))
        self.tabs.addTab(self._tab_forgot(), i18n.tr("Forgot password"))
        self.tabs.currentChanged.connect(lambda _i: self._say(""))
        outer.addWidget(self.tabs, 1)
        outer.addWidget(self.status)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        close_row.addWidget(close)
        outer.addLayout(close_row)
        self._apply_style()
        self._fit(480, 600)
        self.ed_identifier.setFocus()

    # ---- tabs ----------------------------------------------------------------------
    def _tab_login(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        form = QFormLayout()
        self.ed_identifier = QLineEdit()
        self.ed_identifier.setPlaceholderText("username or email address")
        self.ed_password = self._password_edit()
        self.ed_identifier.returnPressed.connect(self.ed_password.setFocus)
        self.ed_password.returnPressed.connect(self._do_login)
        form.addRow("Username or email:", self.ed_identifier)
        form.addRow("Password:", self.ed_password)
        lay.addLayout(form)
        self.cb_remember = QCheckBox("Stay logged in on this computer")
        self.cb_remember.setChecked(self.mw.account_remember())
        self.cb_remember.setToolTip(
            "Log in automatically when CWatM GUI starts (the login is kept in the "
            "Windows Credential Manager). Also in Preferences ▸ Account.")
        lay.addWidget(self.cb_remember)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._button("Log in", self._do_login))
        lay.addLayout(row)
        lay.addStretch(1)
        return w

    def _tab_register(self):
        self.reg_stack = QStackedWidget()

        # step 1: the form
        w = QWidget()
        lay = QVBoxLayout(w)
        form = QFormLayout()
        self.reg_username = QLineEdit()
        self.reg_username.setPlaceholderText("3-30 letters, digits, _ . -")
        self.reg_email = QLineEdit()
        self.reg_password = self._password_edit()
        self.reg_password.setPlaceholderText(f"at least {V.PASSWORD_MIN} characters")
        self.reg_repeat = self._password_edit()
        form.addRow("Username *:", self.reg_username)
        form.addRow("Email *:", self.reg_email)
        form.addRow("Password *:", self.reg_password)
        form.addRow("Repeat password *:", self.reg_repeat)
        lay.addLayout(form)
        lay.addWidget(self._line())
        lay.addWidget(self._note("Optional:"))
        opt = QFormLayout()
        self.reg_name = QLineEdit()
        self.reg_country = QLineEdit()
        self.reg_institute = QLineEdit()
        self.reg_lat = QLineEdit()
        self.reg_lat.setPlaceholderText("e.g. 48.067")
        self.reg_lon = QLineEdit()
        self.reg_lon.setPlaceholderText("e.g. 16.357")
        opt.addRow("Name:", self.reg_name)
        opt.addRow("Country:", self.reg_country)
        opt.addRow("Institute:", self.reg_institute)
        opt.addRow("Your location - latitude:", self.reg_lat)
        opt.addRow("Your location - longitude:", self.reg_lon)
        lay.addLayout(opt)
        lay.addWidget(self._line())
        lay.addWidget(self._note(PRIVACY_TEXT))
        lay.addWidget(self._privacy_link())
        self.reg_agree = QCheckBox("I agree that these data are stored "
                                   "(privacy notice)")
        lay.addWidget(self.reg_agree)
        # The three choices below are OPTIONAL and start UNTICKED: consent must be
        # freely given (not a condition of the account, GDPR Art. 7(4)) and a
        # pre-ticked box is not consent (CJEU Planet49) - security.md, finding 4.
        lay.addWidget(self._note("Optional - you can change these later in your "
                                 "account window:"))
        self.reg_locations = QCheckBox(
            "Record the location of my runs anonymously (first gauge, ~100 m)")
        self.reg_locations.setToolTip(LOCATION_TEXT)
        lay.addWidget(self.reg_locations)
        self.reg_leaderboard = QCheckBox(
            "Show me on the leaderboard (username, country and points only)")
        lay.addWidget(self.reg_leaderboard)
        self.reg_map = QCheckBox(
            "Show my location on the world map (without my name, ~50 km)")
        self.reg_map.setToolTip(
            "Only if you enter your location above. Other users see a point on "
            "Info ▸ World Map ▸ User location - no name, rounded to 0.5°.")
        lay.addWidget(self.reg_map)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._button("Register", self._do_register))
        lay.addLayout(row)
        lay.addStretch(1)
        self.reg_stack.addWidget(w)

        # step 2: the code
        w2 = QWidget()
        lay2 = QVBoxLayout(w2)
        self.reg_code_note = self._note("")
        lay2.addWidget(self.reg_code_note)
        form2 = QFormLayout()
        self.reg_code = QLineEdit()
        self.reg_code.setPlaceholderText("6-digit code")
        self.reg_code.setMaxLength(10)
        self.reg_code.returnPressed.connect(self._do_confirm)
        form2.addRow("Code:", self.reg_code)
        lay2.addLayout(form2)
        row2 = QHBoxLayout()
        row2.addWidget(self._button("Back", lambda: self.reg_stack.setCurrentIndex(0)))
        row2.addWidget(self._button("Send the code again", self._do_resend))
        row2.addStretch(1)
        row2.addWidget(self._button("Confirm", self._do_confirm))
        lay2.addLayout(row2)
        lay2.addStretch(1)
        self.reg_stack.addWidget(w2)
        return self.reg_stack

    def _tab_forgot(self):
        self.fg_stack = QStackedWidget()

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addWidget(self._note(
            "Enter the email address of your account. We send you a code to set a "
            "new password."))
        form = QFormLayout()
        self.fg_email = QLineEdit()
        self.fg_email.returnPressed.connect(self._do_forgot)
        form.addRow("Email:", self.fg_email)
        lay.addLayout(form)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._button("Send code", self._do_forgot))
        lay.addLayout(row)
        lay.addStretch(1)
        self.fg_stack.addWidget(w)

        w2 = QWidget()
        lay2 = QVBoxLayout(w2)
        self.fg_code_note = self._note("")
        lay2.addWidget(self.fg_code_note)
        form2 = QFormLayout()
        self.fg_code = QLineEdit()
        self.fg_code.setPlaceholderText("6-digit code")
        self.fg_code.setMaxLength(10)
        self.fg_password = self._password_edit()
        self.fg_repeat = self._password_edit()
        self.fg_repeat.returnPressed.connect(self._do_reset)
        form2.addRow("Code:", self.fg_code)
        form2.addRow("New password:", self.fg_password)
        form2.addRow("Repeat password:", self.fg_repeat)
        lay2.addLayout(form2)
        row2 = QHBoxLayout()
        row2.addWidget(self._button("Back", lambda: self.fg_stack.setCurrentIndex(0)))
        row2.addWidget(self._button("Send the code again", self._do_forgot))
        row2.addStretch(1)
        row2.addWidget(self._button("Set new password", self._do_reset))
        lay2.addLayout(row2)
        lay2.addStretch(1)
        self.fg_stack.addWidget(w2)
        return self.fg_stack

    # ---- actions -------------------------------------------------------------------
    def _do_login(self):
        ident = self.ed_identifier.text().strip()
        pw = self.ed_password.text()
        if not ident or not pw:
            return self._problem("Please enter your username or email and password.")
        if self.cb_remember.isChecked() != self.mw.account_remember():
            self.mw._set_account_remember(self.cb_remember.isChecked())
        self._run("login", ident, pw)

    def _do_register(self):
        email = self.reg_email.text().strip()
        problem = (V.username_problem(self.reg_username.text())
                   or V.email_problem(email)
                   or V.password_problem(self.reg_password.text(),
                                         self.reg_repeat.text())
                   or V.location_problem(self.reg_lat.text(), self.reg_lon.text()))
        if problem:
            return self._problem(problem)
        if not self.reg_agree.isChecked():
            return self._problem("Please agree to the storage of your data "
                                 "(tick the box above).")
        self._run("register", email, self.reg_password.text(),
                  self.reg_username.text().strip(),
                  full_name=self.reg_name.text(), country=self.reg_country.text(),
                  institute=self.reg_institute.text(),
                  privacy_version=account_config.PRIVACY_VERSION,
                  share_locations=self.reg_locations.isChecked(),
                  show_on_leaderboard=self.reg_leaderboard.isChecked(),
                  show_location_on_map=self.reg_map.isChecked(),
                  **dict(zip(("location_lat", "location_lon"),
                             V.parse_location(self.reg_lat.text(),
                                              self.reg_lon.text()))))

    def _show_confirm_step(self, email, note=None):
        self._confirm_email = email
        self.reg_code_note.setText(note or (
            f"We sent a code to {email}. Enter it here to confirm your email address "
            "(check the spam folder too)."))
        self.reg_code.clear()
        self.tabs.setCurrentIndex(1)
        self.reg_stack.setCurrentIndex(1)
        self.reg_code.setFocus()

    def _do_confirm(self):
        problem = V.code_problem(self.reg_code.text())
        if problem:
            return self._problem(problem)
        self._run("confirm_signup", self._confirm_email, self.reg_code.text().strip())

    def _do_resend(self):
        self._run("resend_confirmation", self._confirm_email)

    def _do_forgot(self):
        email = self.fg_email.text().strip()
        problem = V.email_problem(email)
        if problem:
            return self._problem(problem)
        self._run("request_password_reset", email)

    def _do_reset(self):
        problem = (V.code_problem(self.fg_code.text())
                   or V.password_problem(self.fg_password.text(), self.fg_repeat.text()))
        if problem:
            return self._problem(problem)
        self._run("reset_password", self.fg_email.text().strip(),
                  self.fg_code.text().strip(), self.fg_password.text())

    # ---- answers -------------------------------------------------------------------
    def handle_result(self, op, result):
        result = result or {}
        if "profile" in result:                    # login / confirm / reset / register
            self._logged_in_message(result)
            self.accept()
        elif op == "register":                     # -> enter the code
            self._show_confirm_step(result.get("email", self.reg_email.text().strip()))
        elif op == "resend_confirmation":
            self._say(f"A new code was sent to {result.get('email', '')}.", "ok_color")
        elif op == "request_password_reset":
            self.fg_code_note.setText(
                f"If {result.get('email', '')} belongs to an account, we sent a code "
                "to it. Enter it with your new password (check the spam folder too).")
            self.fg_code.clear()
            self.fg_stack.setCurrentIndex(1)
            self.fg_code.setFocus()

    def handle_error(self, op, code, message):
        if op == "login" and code == "email_not_confirmed":
            ident = self.ed_identifier.text().strip()
            if V.is_email(ident):
                self._show_confirm_step(
                    ident, f"Your email address is not confirmed yet. Enter the code "
                           f"from the confirmation email sent to {ident}, or send it "
                           "again.")
            else:
                self._say("Your email address is not confirmed yet. Log in with your "
                          "email address to enter the confirmation code.", "warn_color")


class AccountWindow(_AccountDialogBase):
    """Points, badges and profile of the logged-in user (see the module docstring)."""

    def __init__(self, mw):
        super().__init__(mw, "CWatM account")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 12)

        self.lbl_name = QLabel("")
        self.lbl_name.setObjectName("accHead")
        self.lbl_email = self._note("")
        outer.addWidget(self.lbl_name)
        outer.addWidget(self.lbl_email)

        self.lbl_points = QLabel("")
        outer.addWidget(self.lbl_points)
        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        outer.addWidget(self.progress)
        # point decay: the rule, and the last decay if there was one
        self.lbl_decay = self._note("")
        outer.addWidget(self.lbl_decay)
        self.lbl_badges = QLabel("")
        self.lbl_badges.setObjectName("accBadges")
        self.lbl_badges.setWordWrap(True)
        outer.addWidget(self.lbl_badges)
        # the earned badges as medal images (+ the next one, faded)
        self.badge_host = QWidget()
        self.badge_grid = QGridLayout(self.badge_host)
        self.badge_grid.setContentsMargins(0, 0, 0, 0)
        self.badge_grid.setHorizontalSpacing(10)
        self.badge_grid.setVerticalSpacing(8)
        self.badge_grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        outer.addWidget(self.badge_host)
        outer.addWidget(self._line())

        form = QFormLayout()
        self.ed_username = QLineEdit()
        self.ed_full_name = QLineEdit()
        self.ed_country = QLineEdit()
        self.ed_institute = QLineEdit()
        self.ed_lat = QLineEdit()
        self.ed_lat.setPlaceholderText("e.g. 48.067")
        self.ed_lon = QLineEdit()
        self.ed_lon.setPlaceholderText("e.g. 16.357")
        form.addRow("Username:", self.ed_username)
        form.addRow("Name:", self.ed_full_name)
        form.addRow("Country:", self.ed_country)
        form.addRow("Institute:", self.ed_institute)
        form.addRow("Your location - latitude:", self.ed_lat)
        form.addRow("Your location - longitude:", self.ed_lon)
        outer.addLayout(form)
        self.cb_leaderboard = QCheckBox(
            "Show me on the leaderboard (username, country and points only)")
        outer.addWidget(self.cb_leaderboard)
        self.cb_locations = QCheckBox(
            "Record the location of my runs anonymously (first gauge, ~100 m)")
        self.cb_locations.setToolTip(LOCATION_TEXT)
        outer.addWidget(self.cb_locations)
        self.cb_map = QCheckBox(
            "Show my location on the world map (without name, ~50 km)")
        self.cb_map.setToolTip(
            "Info ▸ World Map ▸ User location shows the locations of the users who "
            "ticked this - as points without names, rounded to about 50 km. Needs "
            "your location (latitude/longitude) above.")
        outer.addWidget(self.cb_map)
        save_row = QHBoxLayout()
        save_row.addStretch(1)
        save_row.addWidget(self._button("Save changes", self._do_save))
        outer.addLayout(save_row)
        outer.addWidget(self._line())

        outer.addWidget(self.status)
        outer.addStretch(1)
        outer.addWidget(self._privacy_link())
        row = QHBoxLayout()
        row.addWidget(self._button("Export my data…", self._do_export))
        row.addWidget(self._button("Delete account…", self._do_delete))
        row.addStretch(1)
        row.addWidget(self._button("Log out", self._do_logout))
        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        row.addWidget(close)
        outer.addLayout(row)
        self._apply_style()
        self._fit(520, 600)

        self._fill(mw.account_status() or {})
        self._run("get_status")                   # refresh from the server

    def _fill(self, status):
        self._status = status
        profile = status.get("profile") or {}
        from src.gui.utils import account_shop
        # badges and the next-badge bar follow the EARNED points; the label shows
        # the actual points (what the Shop spends) next to them
        points = account_shop.earned(status)
        balance = account_shop.balance(status)
        self.lbl_name.setText(profile.get("username", ""))
        self.lbl_email.setText(status.get("email", ""))
        self.lbl_points.setText(f"Points: {balance}" if balance == points else
                                f"Points: {balance}  ·  earned in total: {points}")
        from src.gui.components.account_ui import DECAY_RULE
        decay = DECAY_RULE
        last = status.get("last_decay") or {}
        if last.get("points"):
            weeks = int(last.get("weeks") or 0)
            decay += (f"\nLast decay: -{last['points']} points on "
                      f"{_format_date(last.get('decayed_at'))} ({weeks} week"
                      f"{'s' if weeks != 1 else ''} without use).")
        self.lbl_decay.setText(decay)
        nxt = status.get("next_badge")
        if nxt:
            need = max(1, nxt.get("points_required", 1))
            self.progress.setRange(0, need)
            self.progress.setValue(min(points, need))
            # a progress-bar text is not reached by the language filter
            self.progress.setFormat(i18n.tr(f"{points} / {need} points to the "
                                            f"{nxt.get('name')} badge"))
            self.progress.setVisible(True)
        else:
            self.progress.setVisible(False)
        badges = status.get("badges") or []
        self.lbl_badges.setText(
            "Badges" if badges
            else "Badges: none yet - every run that earns a point brings you closer "
                 "to the first one")
        self._fill_badges(badges, nxt, points)
        self.ed_username.setText(profile.get("username") or "")
        self.ed_full_name.setText(profile.get("full_name") or "")
        self.ed_country.setText(profile.get("country") or "")
        self.ed_institute.setText(profile.get("institute") or "")
        self.cb_leaderboard.setChecked(bool(profile.get("show_on_leaderboard")))
        self.cb_locations.setChecked(bool(profile.get("share_locations")))
        self.cb_map.setChecked(bool(profile.get("show_location_on_map")))
        self.ed_lat.setText(V.format_coord(profile.get("location_lat")))
        self.ed_lon.setText(V.format_coord(profile.get("location_lon")))

    BADGE_SIZE = 88          # px - the medal images (the old 🏅 emoji was ~14 px)
    BADGES_PER_ROW = 5

    def _fill_badges(self, badges, nxt, points):
        """The earned badges as medals, then the next one faded with its goal."""
        while self.badge_grid.count():
            item = self.badge_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        tiles = [badge_tile(self, b.get("code"), b.get("name", ""), self.BADGE_SIZE,
                            on_click=lambda b=b: self._enlarge(b))
                 for b in badges]
        if nxt:
            need = max(0, nxt.get("points_required", 0) - points)
            tiles.append(badge_tile(
                self, nxt.get("code"), nxt.get("name", ""), self.BADGE_SIZE,
                faded=True, caption=f"next - {need} more point{'s' if need != 1 else ''}"))
        for i, tile in enumerate(tiles):
            self.badge_grid.addWidget(tile, i // self.BADGES_PER_ROW,
                                      i % self.BADGES_PER_ROW)
        self.badge_host.setVisible(bool(tiles))

    def _enlarge(self, badge):
        """An earned badge was clicked: show it large, with the points it needed.
        The earned badges in the status carry no points, so the ladder is fetched
        (once per window) and the viewer filled in when it arrives."""
        ladder = getattr(self, "_badge_points", None) or {}
        points = badge.get("points_required", ladder.get(badge.get("code")))
        viewer = BadgeViewer(self, badge.get("code"), badge.get("name", ""),
                             badge.get("awarded_at"), points)
        self._badge_viewer = viewer
        viewer.show()
        if points is None and not ladder:
            self._run("get_badges")
        return viewer

    def _on_badge_ladder(self, ladder):
        self._badge_points = {b.get("code"): b.get("points_required")
                              for b in ladder or [] if b.get("code")}
        viewer = getattr(self, "_badge_viewer", None)
        if viewer is None:
            return
        try:
            viewer.set_points(self._badge_points.get(viewer.code))
        except RuntimeError:                  # the viewer was closed meanwhile
            self._badge_viewer = None

    def _changes(self):
        profile = (self._status or {}).get("profile") or {}
        new = {"username": self.ed_username.text().strip(),
               "full_name": self.ed_full_name.text().strip(),
               "country": self.ed_country.text().strip(),
               "institute": self.ed_institute.text().strip(),
               "show_on_leaderboard": self.cb_leaderboard.isChecked(),
               "share_locations": self.cb_locations.isChecked(),
               "show_location_on_map": self.cb_map.isChecked()}
        flags = ("show_on_leaderboard", "share_locations", "show_location_on_map")
        old = {k: (bool(profile.get(k)) if k in flags else (profile.get(k) or ""))
               for k in new}
        changes = {k: v for k, v in new.items() if v != old[k]}
        # the own location: compared as the fields show it, sent as a pair
        lat, lon = V.parse_location(self.ed_lat.text(), self.ed_lon.text())
        shown = (V.format_coord(lat), V.format_coord(lon))
        stored = (V.format_coord(profile.get("location_lat")),
                  V.format_coord(profile.get("location_lon")))
        if shown != stored:
            changes["location_lat"], changes["location_lon"] = lat, lon
        return changes

    def _do_save(self):
        problem = V.location_problem(self.ed_lat.text(), self.ed_lon.text())
        if problem:
            return self._problem(problem)
        changes = self._changes()
        if not changes:
            return self._say("Nothing changed.", "text_gray")
        if "username" in changes:
            problem = V.username_problem(changes["username"])
            if problem:
                return self._problem(problem)
        self._run("update_profile", **changes)

    def _do_logout(self):
        self._run("logout")

    def _do_export(self):
        self._run("export_data")

    def _do_delete(self):
        name = (self._status.get("profile") or {}).get("username", "")
        if QMessageBox.warning(
                self, "Delete account",
                f"Permanently delete the account '{name}' with all its points and "
                "badges?\n\nThis cannot be undone.",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel) != QMessageBox.Yes:
            return
        password, ok = QInputDialog.getText(
            self, "Delete account", "Enter your password to confirm:",
            QLineEdit.Password)
        if ok and password:
            self._run("delete_account", password)

    def handle_result(self, op, result):
        if op in ("get_status", "update_profile") and isinstance(result, dict):
            self._fill(result)
            if op == "update_profile":
                self._say("Saved.", "ok_color")
        elif op == "logout":
            self.accept()
        elif op == "delete_account":
            QMessageBox.information(self, "Delete account",
                                    "Your account and all its data were deleted.")
            self.accept()
        elif op == "export_data":
            self._save_export(result or {})
        elif op == "get_badges":
            self._on_badge_ladder(result)

    def handle_error(self, op, code, message):
        if code in ("session_expired", "not_logged_in"):
            QMessageBox.information(self, "CWatM account", message)
            self.reject()

    def _save_export(self, data):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export my data", "cwatm_account_data.json", "JSON (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            self._say(f"Saved to {path}", "ok_color")
        except OSError as e:
            self._say(f"Could not save: {e}", "warn_color")


class LeaderboardWindow(_AccountDialogBase):
    """Info ▸ Leaderboard: the users who opted in, ranked by points, with their
    highest badge; the viewer's own row highlighted."""

    COLUMNS = ["#", "User", "Country", "Highest badge", "Points"]
    ICON = 32                # px - the badge medal in the table

    def __init__(self, mw):
        super().__init__(mw, "CWatM leaderboard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 12)
        head = QLabel("CWatM leaderboard")
        head.setObjectName("accHead")
        outer.addWidget(head)
        outer.addWidget(self._note(
            "Points for full CWatM runs - one per distinct model setup. Only users "
            "who switched on 'Show me on the leaderboard' in their account window "
            "are listed."))
        self.lbl_me = self._note("")
        outer.addWidget(self.lbl_me)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setIconSize(QSize(self.ICON, self.ICON))
        self.table.verticalHeader().setDefaultSectionSize(self.ICON + 6)
        self._badge_codes = {}                 # badge name -> code (image file name)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        outer.addWidget(self.table, 1)
        outer.addWidget(self.status)

        row = QHBoxLayout()
        row.addWidget(self._button("Refresh", self._refresh))
        row.addStretch(1)
        close = QPushButton("Close")
        close.setAutoDefault(False)
        close.clicked.connect(self.reject)
        row.addWidget(close)
        outer.addLayout(row)
        self._apply_style()
        self._fit(560, 520)
        self._refresh()

    def _my_name(self):
        status = self.mw.account_status() or {}
        return ((status.get("profile") or {}).get("username") or "").lower()

    def _refresh(self):
        # the leaderboard names each user's top badge; its image is filed under the
        # badge's code, so the ladder (name -> code) is fetched once first
        if self._badge_codes:
            self._run("get_leaderboard", 100)
        else:
            self._run("get_badges")

    def handle_result(self, op, result):
        if op == "get_badges":
            self._badge_codes = {b.get("name"): b.get("code") for b in result or []}
            self._run("get_leaderboard", 100)
        elif op == "get_leaderboard":
            self._fill(result or [])

    def _badge_item(self, name):
        from src.gui.utils.badge_images import badge_pixmap
        if not name:
            return QTableWidgetItem("")
        pix = badge_pixmap(self._badge_codes.get(name), self.ICON,
                           dpr=self.devicePixelRatioF())
        if pix is None:
            return QTableWidgetItem(f"🏅 {name}")
        item = QTableWidgetItem(QIcon(pix), name)
        return item

    def _fill(self, rows):
        me = self._my_name()
        self.table.setRowCount(len(rows))
        mine = None
        bold = QFont()
        bold.setBold(True)
        for r, entry in enumerate(rows):
            values = [entry.get("rank", ""), entry.get("username", ""),
                      entry.get("country") or "", entry.get("top_badge"),
                      entry.get("total_points", 0)]
            is_me = bool(me) and (entry.get("username") or "").lower() == me
            if is_me:
                mine = entry
            for c, value in enumerate(values):
                item = (self._badge_item(value) if c == 3
                        else QTableWidgetItem(str(value)))
                if c in (0, 4):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if is_me:
                    item.setFont(bold)
                    item.setBackground(QColor(theme.c("changed_line")))
                self.table.setItem(r, c, item)
        if mine is not None:
            self.lbl_me.setText(f"You are number {mine.get('rank')} with "
                                f"{mine.get('total_points')} point(s).")
        else:
            self.lbl_me.setText(
                "You are not listed - switch on 'Show me on the leaderboard' in your "
                "account window (click your name in the menu bar) to take part.")
        if not rows:
            self._say("Nobody is listed yet.", "text_gray")


def _open_single(mw, attr, cls):
    """Open ``cls`` once - a second click raises the window already open."""
    win = getattr(mw, attr, None)
    try:
        if win is not None and win.isVisible():
            win.raise_()
            win.activateWindow()
            return win
    except RuntimeError:                          # deleted (WA_DeleteOnClose)
        log.debug("previous account window gone", exc_info=True)
    win = cls(mw)
    setattr(mw, attr, win)
    win.show()
    return win


def open_login_dialog(mw):
    return _open_single(mw, "_account_login_dialog", LoginDialog)


def open_account_window(mw):
    return _open_single(mw, "_account_window", AccountWindow)


def open_leaderboard(mw):
    return _open_single(mw, "_leaderboard_window", LeaderboardWindow)
