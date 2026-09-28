"""CWatM Academy - the floating "Torus" guide: a small companion callout that
points at a specific spot in the *real* GUI (not just inside the Academy
dialog) and explains what just happened there, stepping through a short
sequence via Back/Next/Got it!. First used right after Level 1's Confirm
(pointing at the MaskMap line, then the Gauges line - see
academy_outlet_map._show_written_lines), and meant to be reused by later
levels for the same "look, right there" moments, not a one-off.

TorusGuideBubble is a frameless, always-on-top top-level widget (Qt.Tool, not
a QDialog - it must float over the main window without blocking or being
blocked by it, and without its own taskbar entry) with a translucent
background so a custom paintEvent can draw a proper comic-speech-bubble
shape: a rounded card plus a triangular tail pointing at the target, and a
soft coloured halo around the whole thing. The Torus mascot sits *inside* the
card, on whichever side is away from the tail - a free-floating mascot
positioned right at the tail was tried first and dropped: it ended up
sitting on top of the exact point being pointed at, defeating the tail's
whole job of pointing precisely at it.

The halo is hand-painted (several wide, low-alpha strokes along the card's
own outline, fading out) rather than a QGraphicsDropShadowEffect on the
whole widget - a widget-level effect blurs everything it contains, buttons
included, which read as doubled/ghosted outlines once blurred. Painting the
glow directly in paintEvent keeps it behind the child widgets (buttons/text
paint on top, as normal Qt child z-order) and crisp.

Positioned next to a target point on screen - a callable returning either a
global QPoint, or a ``(QPoint, forced_side)`` pair when the target itself
knows which side is genuinely clear to open into (see _reposition) -
evaluated lazily as each step is shown (not all up front), so a target that
first needs to scroll something into view (e.g. a settings-editor line) can
do that scroll and then report where it landed.

A step is normally a ``(target, html_text)`` pair; it can also be a
``(target, html_text, gate)`` triple, where ``gate`` is a zero-argument
callable (generic "Waiting for this ..." / "Ready" wording), a ``(check,
waiting_text, ready_text)`` triple for wording that names the actual
condition, or a ``(check, waiting_text, ready_text, blocking)`` quadruple
that also controls whether the condition actually blocks Next/Got it!
(default True) or is shown/polled purely as a status line (``blocking=
False`` - see _normalize_gate). A blocking gate that reads False disables
Next/Got it!; a status line polls the gate every 500ms either way (QTimer,
stopped the moment the step changes or the bubble closes - see
_update_gate_state/_poll_gate); as soon as it reads True the status line
flips to the ready text (and, if blocking, Next enables itself), with no
click needed to re-check. First used by Level 2's walkthrough (see
academy_window.AcademyWindow._start_level2_tour): the PathOut step is gated
on the folder existing, the RUN CWATM step on the run that was just started
actually finishing.

Always styled Mikhail amber-on-black, like the rest of Academy - this widget
has its own local stylesheet/painting rather than inheriting one, since
(unlike OutletMapWidget) it is never a child of AcademyWindow's widget tree.

TorusPrompt is the other floating piece here: the same halo'd card, but
centred on screen with no tail and a big Torus + big text, for a general
instruction rather than something pointing at a specific spot - used for
Level 1's real first step (load a settings file before there is anything to
pick an outlet on - see academy_window._show_load_settings_prompt), and,
with ``button_text`` set, for the "you finished this level" celebration
every level ends with (see show_level_celebration below) - the same "big
centred message" look for both, just with a Continue button added for the
celebration instead of the caller driving it via set_text.

goto_settings_key/settings_line_point are the settings-editor line lookup +
TorusGuideBubble-target-point helpers, shared between Level 1's outlet map
(academy_outlet_map._show_written_lines, pointing at MaskMap/Gauges) and
Level 2's run walkthrough (academy_window._start_level2_tour, pointing at
PathOut/StepStart/SpinUp/StepEnd) - both want "point at the real settings
file line", not two copies of the same cursor-and-geometry code.

Each level now ends with a graded Field Test, not just a teaching guide -
"proof of skill" (a real task, verified against the real GUI state) rather
than a multiple-choice quiz, in keeping with Academy's "learn by doing"
approach throughout. show_mission_briefing shows the "will you accept this
mission" beat between a level's teaching content and its Field Test (a
centred TorusPrompt with an Accept Mission button, text from
academy_content.field_test_for); show_level_celebration shows the "you
passed" beat afterward (Continue button, text from
academy_content.celebration_for). Both are the one place their moment is
shown, instead of each level building its own popup - used by
academy_outlet_map (Level 1: teaching guide -> mission briefing -> the Nile
Field Test in academy_field_test.NileFieldTestWindow -> celebration) and
academy_window (Level 2: teaching tour -> mission briefing -> a second,
gated TorusGuideBubble tour for the Field Test itself -> celebration).
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, QPoint, QRect, QTimer, Signal
from PySide6.QtGui import (
    QPixmap, QPainter, QPainterPath, QColor, QPen, QPolygon, QGuiApplication,
    QTextCursor,
)

from src.gui.utils import theme
from src.gui.utils.assets import asset_path
from src.gui.utils.gui_log import get_logger

log = get_logger("academy_guide")

_C = theme.theme_colors("mikhail")

_BUBBLE_WIDTH = 380
_TAIL_SIZE = 14          # px, the speech-bubble tail's half-width (thickness)
# Distance the card is inset from this (top-level, frameless) widget's own
# edges on EVERY side, always - never flush against an edge, even on the
# tail side (the tail extends from the card out to the edge, exactly this
# far) - otherwise the halo has nowhere to fade into and clips hard.
_HALO_INSET = 26
# Extra breathing room between the card's own border and its text/buttons,
# on top of _HALO_INSET - without this the text touched the painted border.
_CARD_PADDING = 14
_MASCOT_SIZE = 56        # px, the Torus avatar
_MARGIN = 18             # gap kept from the target point / screen edges

_DEFAULT_WAITING_TEXT = "Waiting for this …"
_DEFAULT_READY_TEXT = "✓ Ready"


def _normalize_gate(gate):
    """A step's gate (the optional third ``start()`` tuple element) is a
    plain zero-arg callable, a ``(check, waiting_text, ready_text)``
    triple, or a ``(check, waiting_text, ready_text, blocking)`` quadruple -
    returns the normalized ``(check, waiting_text, ready_text, blocking)``
    quadruple, or None for no gate.

    A callable alone gets generic "Waiting for this ..." / "Ready" wording
    and blocks Next (the default, ``blocking=True`` - the RUN CWATM step's
    condition really does have to be true before moving on). The triple
    swaps in wording that names the actual condition (e.g. "Folder not
    found yet ..." / "Folder found" for a PathOut step), still blocking.
    The quadruple additionally sets ``blocking=False`` for a status line
    that's purely informative - shown and polled exactly the same way, but
    never disables Next/Got it!. Used for the *first*, purely explanatory
    PathOut step (Level 2's settings-file pass): showing "Folder not found
    yet .../Folder found" there answers "is my output folder already set
    up" right where PathOut is introduced, without trapping the learner on
    that one step before they've even seen StepStart/SpinUp/StepEnd - the
    *second* PathOut step (the left-panel edit pass, where the folder is
    actually created) is where it blocks."""
    if gate is None:
        return None
    if callable(gate):
        return (gate, _DEFAULT_WAITING_TEXT, _DEFAULT_READY_TEXT, True)
    if len(gate) == 3:
        check, waiting_text, ready_text = gate
        blocking = True
    else:
        check, waiting_text, ready_text, blocking = gate
    return (check, waiting_text, ready_text, blocking)


def goto_settings_key(main_window, key):
    """Put ``main_window``'s settings editor cursor on the line defining
    ``key`` (e.g. 'MaskMap') and make it visible - same key->line lookup
    Check Data's double-click-to-jump uses (check_data_window.py
    _on_row_double_clicked): walk the editor's current text for an
    unindented, uncommented 'key = ...' line. Returns True if found."""
    editor = getattr(main_window, "text_area", None)
    if editor is None:
        return False
    want = key.strip().lower()
    for row, line in enumerate(editor.toPlainText().split('\n')):
        s = line.strip()
        if not s or s[0] in '#;[':
            continue
        eq = s.find('=')
        if eq > 0 and s[:eq].strip().lower() == want:
            block = editor.document().findBlockByNumber(row)
            if block.isValid():
                editor.setTextCursor(QTextCursor(block))
                try:
                    editor.reveal_cursor()
                except Exception:
                    log.debug("goto_settings_key: reveal_cursor failed", exc_info=True)
                editor.ensureCursorVisible()
                return True
    return False


def read_settings_value(main_window, key):
    """The current right-hand-side value of ``key = ...`` in the *live
    editor text* (inline comment stripped, whitespace trimmed), or None if
    the key isn't present - same key/line convention as goto_settings_key.

    Reads the editor, not a left-panel widget: unlike MaskMap/Gauges/
    PathOut, the run-period dates have no widget<->editor sync of their own
    (main_window._live_content() only ever substitutes MaskMap/Gauges/
    PathOut, never the dates), so a direct edit to a date line is only ever
    visible here, in the text itself - see
    academy_window._level2_dates_match_mission, which reads a Field Test's
    StepStart/SpinUp/StepEnd this way instead of through
    date_manager's QDateEdit widgets."""
    editor = getattr(main_window, "text_area", None)
    if editor is None:
        return None
    want = key.strip().lower()
    for line in editor.toPlainText().split('\n'):
        s = line.strip()
        if not s or s[0] in '#;[':
            continue
        eq = s.find('=')
        if eq > 0 and s[:eq].strip().lower() == want:
            value = s[eq + 1:]
            for marker in ('#', ';'):
                cpos = value.find(marker)
                if cpos >= 0:
                    value = value[:cpos]
            return value.strip()
    return None


def settings_line_point(main_window, key):
    """A zero-arg TorusGuideBubble target: jumps ``main_window``'s editor to
    ``key``'s line (scrolling it into view) and returns that line's *global
    screen* point - evaluated lazily, when the guide actually shows this
    step, not before.

    Points at the very start of the line's own text (where e.g. 'MaskMap'
    itself begins), not its midpoint - the guide prefers floating to the
    LEFT of its target, so a midpoint target had the bubble land with its
    right portion overlapping the first half of the line, hiding the very
    key it was pointing at. Targeting the start means the preferred (left)
    position sits entirely before the line begins, tail reaching across to
    touch its first character, never covering any of it."""
    def _target():
        editor = getattr(main_window, "text_area", None)
        if editor is None or not goto_settings_key(main_window, key):
            return None
        cursor = editor.textCursor()
        cursor.movePosition(QTextCursor.StartOfBlock)
        rect = editor.cursorRect(cursor)
        local_point = QPoint(rect.left(), (rect.top() + rect.bottom()) // 2)
        return editor.viewport().mapToGlobal(local_point)
    return _target


def show_level_celebration(level_id, on_continue):
    """Float a centred, halo'd TorusPrompt congratulating the learner on
    finishing ``level_id`` (bold title + plain-weight body + mascot image,
    all from academy_content.celebration_for) with a single Continue
    button, then call ``on_continue()`` once they dismiss it. The one place
    a level's completion is celebrated, instead of each level building its
    own popup - see the module docstring. Returns the TorusPrompt; the
    caller must keep a reference to it alive (e.g. ``self._celebration =
    ...``) or it would be garbage-collected out from under its own
    window."""
    from src.gui.utils.academy_content import celebration_for
    image, title, body = celebration_for(level_id)
    prompt = TorusPrompt(title, body_text=body, image_asset=image, button_text="Continue")

    def _done():
        prompt.close()
        on_continue()

    prompt.continued.connect(_done)
    prompt.start()
    return prompt


def show_mission_briefing(level_id, on_accept):
    """Float a centred, halo'd TorusPrompt briefing the learner on
    ``level_id``'s Field Test (title/body/mascot image from
    academy_content.field_test_for) with an "Accept Mission" button, then
    call ``on_accept()`` once they take it. The deliberate beat between
    finishing a level's teaching content and actually being dropped into
    its graded check - "will you accept this mission" is a genre
    convention for a reason: it marks the shift from lesson to test before
    the test starts, rather than the check just appearing. Same
    TorusPrompt/pattern as show_level_celebration, just a different button
    and a different text source; see its docstring for why the caller must
    keep the returned TorusPrompt referenced."""
    from src.gui.utils.academy_content import field_test_for
    image, title, body = field_test_for(level_id)
    prompt = TorusPrompt(title, body_text=body, image_asset=image,
                          button_text="Accept Mission")

    def _done():
        prompt.close()
        on_accept()

    prompt.continued.connect(_done)
    prompt.start()
    return prompt


class TorusGuideBubble(QWidget):
    """A companion speech bubble + Back/Next/Got it! step sequence.
    Call ``start(steps)`` with a list of ``(target, html_text)`` pairs, where
    ``target`` is a zero-argument callable returning a global ``QPoint`` -
    typically something that first scrolls/reveals the spot it's pointing at,
    then reports where it ended up (see
    academy_outlet_map.OutletMapWidget._settings_line_point). Emits
    ``finished`` once the last step's "Got it!" is clicked."""

    finished = Signal()

    def __init__(self):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint |
                          Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._steps = []
        self._index = 0
        self._tail_side = "left"     # which edge of the bubble the tail is on
        self._tail_anchor_y = 0      # local y of the tail's centre on that edge
        self._current_gate = None    # this step's gate callable, if any
        self._gate_timer = None      # polls _current_gate while it's False
        self._build_ui()

    # ------------------------------------------------------------------ ui

    def _build_ui(self):
        outer = QVBoxLayout(self)
        # Room for the halo/tail (_HALO_INSET) plus a further buffer so the
        # text/buttons never touch the painted card's border (_CARD_PADDING).
        pad = _HALO_INSET + _CARD_PADDING
        outer.setContentsMargins(pad, pad, pad, pad)
        outer.setSpacing(10)

        self._row = QHBoxLayout()
        self._row.setSpacing(12)
        outer.addLayout(self._row)

        self.mascot_label = QLabel()
        pixmap = QPixmap(asset_path("academy_torus.png"))
        if not pixmap.isNull():
            dpr = self.devicePixelRatioF()
            scaled = pixmap.scaled(
                round(_MASCOT_SIZE * dpr), round(_MASCOT_SIZE * dpr),
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            self.mascot_label.setPixmap(scaled)
        self.mascot_label.setFixedSize(_MASCOT_SIZE, _MASCOT_SIZE)
        self.mascot_label.setAlignment(Qt.AlignCenter)
        # Centred top-to-bottom on the row (which grows with the text), not
        # pinned to its top edge.
        self._row.addWidget(self.mascot_label, 0, Qt.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setSpacing(8)
        self._row.addLayout(text_col, 1)

        self.text_label = QLabel()
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.text_label.setStyleSheet(f"color: {_C['text']}; font-size: 13px;")
        text_col.addWidget(self.text_label)

        self.gate_label = QLabel("")
        self.gate_label.setWordWrap(True)
        self.gate_label.setStyleSheet(
            f"color: {_C['accent']}; font-size: 12px; font-weight: 600;")
        self.gate_label.hide()
        text_col.addWidget(self.gate_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)
        self.step_label = QLabel("")
        self.step_label.setStyleSheet(f"color: {_C['text_gray']}; font-size: 11px;")
        btn_row.addWidget(self.step_label)
        self.back_button = QPushButton("Back")
        self.back_button.setStyleSheet(self._secondary_button_css())
        self.back_button.clicked.connect(self._on_back_clicked)
        btn_row.addWidget(self.back_button)
        self.next_button = QPushButton("Next")
        self.next_button.setStyleSheet(self._primary_button_css())
        self.next_button.clicked.connect(self._on_next_clicked)
        btn_row.addWidget(self.next_button)
        text_col.addLayout(btn_row)

        self.setFixedWidth(_BUBBLE_WIDTH)

    def _primary_button_css(self):
        return (f"QPushButton {{ background-color: {_C['btn_top']}; "
                f"color: {_C['btn_text']}; border: 1px solid {_C['btn_border']}; "
                "border-radius: 4px; padding: 5px 14px; }"
                f"QPushButton:hover {{ background-color: {_C['btn_hover_top']}; }}")

    def _secondary_button_css(self):
        return (f"QPushButton {{ background-color: transparent; "
                f"color: {_C['text_muted']}; border: 1px solid {_C['border']}; "
                "border-radius: 4px; padding: 5px 12px; }"
                f"QPushButton:hover {{ color: {_C['text']}; "
                f"background-color: {_C['btn_hover_top']}; }}"
                f"QPushButton:disabled {{ color: {_C['text_gray']}; "
                "background-color: transparent; }")

    # --------------------------------------------------------------- steps

    def start(self, steps):
        """``steps``: list of ``(target_callable, html_text)`` pairs, each
        optionally extended with a third ``gate`` element - see the module
        docstring for both the ``target`` and ``gate`` shapes."""
        if not steps:
            return
        self._steps = list(steps)
        self._index = 0
        self._show_step()
        self.show()
        self.raise_()

    def _show_step(self):
        step = self._steps[self._index]
        target, text = step[0], step[1]
        self._current_gate = _normalize_gate(step[2] if len(step) > 2 else None)
        self.text_label.setText(text)
        last = self._index == len(self._steps) - 1
        self.next_button.setText("Got it!" if last else "Next")
        self.back_button.setEnabled(self._index > 0)
        self.step_label.setText(f"{self._index + 1} / {len(self._steps)}")
        point, forced_side = None, None
        try:
            result = target()
        except Exception:
            log.debug("guide step target() failed", exc_info=True)
            result = None
        if result is not None:
            if isinstance(result, tuple):
                point, forced_side = result
            else:
                point = result
        self._update_gate_state()
        self.adjustSize()
        if point is not None:
            self._reposition(point, forced_side)
        self.update()

    def _update_gate_state(self):
        """(Re-)evaluate this step's gate, right when it's shown and again
        every time _poll_gate ticks. No gate -> Next is always enabled and no
        status line shows. A gate that already reads True needs no polling -
        e.g. the PathOut folder may already exist when this step first
        appears. A non-blocking gate (``blocking=False`` - see
        _normalize_gate) shows/polls the same status line but never
        disables Next/Got it!, for a step that wants to *report* a
        condition without requiring it before moving on."""
        if self._gate_timer is not None:
            self._gate_timer.stop()
        gate = self._current_gate
        if gate is None:
            self.gate_label.hide()
            self.next_button.setEnabled(True)
            return
        check, waiting_text, ready_text, blocking = gate
        ready = self._eval_gate(check)
        self.gate_label.show()
        self.gate_label.setText(ready_text if ready else waiting_text)
        self.next_button.setEnabled(True if not blocking else ready)
        if not ready:
            if self._gate_timer is None:
                self._gate_timer = QTimer(self)
                self._gate_timer.setInterval(500)
                self._gate_timer.timeout.connect(self._poll_gate)
            self._gate_timer.start()

    def _eval_gate(self, check):
        try:
            return bool(check())
        except Exception:
            log.debug("guide gate check failed", exc_info=True)
            return False

    def _poll_gate(self):
        gate = self._current_gate
        if gate is None:
            if self._gate_timer is not None:
                self._gate_timer.stop()
            return
        check, waiting_text, ready_text, blocking = gate
        if self._eval_gate(check):
            self._gate_timer.stop()
            self.gate_label.setText(ready_text)
            if blocking:
                self.next_button.setEnabled(True)

    def _on_next_clicked(self):
        if self._index >= len(self._steps) - 1:
            self._close_and_finish()
            return
        self._index += 1
        self._show_step()

    def _on_back_clicked(self):
        if self._index <= 0:
            return
        self._index -= 1
        self._show_step()

    def _close_and_finish(self):
        if self._gate_timer is not None:
            self._gate_timer.stop()
        self.hide()
        self.finished.emit()

    def closeEvent(self, event):
        if self._gate_timer is not None:
            self._gate_timer.stop()
        self.finished.emit()
        super().closeEvent(event)

    # ---------------------------------------------------------- positioning

    def _screen_geometry(self, point):
        screen = self.screen()
        try:
            found = QGuiApplication.screenAt(point)
            if found is not None:
                screen = found
        except Exception:
            log.debug("_screen_geometry: screenAt failed", exc_info=True)
        return screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

    def _reposition(self, target_point, forced_side=None):
        """Place the bubble beside ``target_point`` (a global QPoint), tail
        pointing back at it - preferring its left (so it doesn't sit on top
        of whatever it's pointing at, e.g. the settings editor, which
        extends to the right of a target line), falling back to its right
        if there isn't room; vertically centred on it and clamped to the
        screen.

        ``forced_side`` ('left'/'right'/None), when given, skips that
        "is there room" heuristic entirely and always opens on that side.
        The heuristic only looks at ``target_point.x()`` versus the screen
        edge - true empty space for an editor line (where the target is the
        line's own start, so "room to its left" really is empty gutter),
        but not for a *wide* left-panel widget (the PathOut box, the date
        timeline) anchored on its own right edge: that edge can sit far
        enough right on screen for the heuristic to say "room to the left",
        when what's actually there, to the left of that edge, is the widget
        itself - the bubble would open right on top of it. A target that
        knows its own clear side (academy_window._widget_point's
        ``from_right=True``) returns ``forced_side='right'`` for exactly
        that reason; a target with no such preference (a settings-editor
        line) returns a bare QPoint and keeps the automatic heuristic."""
        avail = self._screen_geometry(target_point)
        w, h = self.width(), self.height()

        if forced_side == "right":
            fits_left = False
        elif forced_side == "left":
            fits_left = True
        else:
            fits_left = target_point.x() - _MARGIN - w >= avail.left()
        if fits_left:
            self._tail_side = "right"
            x = target_point.x() - _MARGIN - w
        else:
            self._tail_side = "left"
            x = target_point.x() + _MARGIN

        y = target_point.y() - h // 2
        y = max(avail.top(), min(y, avail.bottom() - h))
        x = max(avail.left(), min(x, avail.right() - w))

        # Where the tail sits on that edge, in this widget's own coordinates -
        # the target's y position, clamped inside the card's rounded corners.
        local_y = target_point.y() - y
        self._tail_anchor_y = max(24, min(local_y, h - 24))

        self._apply_mascot_side()
        self.move(x, y)

    def _apply_mascot_side(self):
        """Keep the Torus on the side AWAY from the tail - the near side
        would sit right on top of the exact point the tail is pointing at,
        which is the one thing this bubble has to stay precise about."""
        self._row.removeWidget(self.mascot_label)
        if self._tail_side == "right":
            # Tail on the right (pointing right, at the target) -> mascot
            # goes on the left, the far side.
            self._row.insertWidget(0, self.mascot_label, 0, Qt.AlignVCenter)
        else:
            # Tail on the left -> mascot goes on the right.
            self._row.addWidget(self.mascot_label, 0, Qt.AlignVCenter)

    # -------------------------------------------------------------- paint

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        inset = _HALO_INSET
        card = QRect(inset, inset, self.width() - 2 * inset,
                     self.height() - 2 * inset)

        card_path = QPainterPath()
        card_path.addRoundedRect(card, 14, 14)

        tail_y = self._tail_anchor_y
        if self._tail_side == "left":
            tip_x = 0
            base_x = card.left()
        else:
            tip_x = self.width()
            base_x = card.right()
        tail = QPolygon([
            QPoint(tip_x, tail_y),
            QPoint(base_x, tail_y - _TAIL_SIZE),
            QPoint(base_x, tail_y + _TAIL_SIZE),
        ])
        tail_path = QPainterPath()
        tail_path.addPolygon(tail)
        path = card_path.united(tail_path)

        # Hand-painted glow: several wide, translucent strokes along the same
        # outline, each fainter and slightly wider than the last, painted
        # BEFORE the crisp fill/border below (so it sits behind everything,
        # including the child buttons/text, unlike a widget-level graphics
        # effect - see the module docstring for why that was dropped).
        #
        # Stroked along ``card_path`` only, NOT the tail - a thin triangle's
        # sharp point breaks up into a messy, layered outline once several
        # different-width strokes are traced along it (each layer's corner
        # miters differently at a sharp angle), which read as a "funny"/
        # broken-up halo right around the tail. The tail itself still gets a
        # normal crisp fill + thin border below, from the unioned ``path`` -
        # it just isn't traced by the wide glow strokes.
        accent = QColor(_C["accent"])
        painter.setBrush(Qt.NoBrush)
        layers = 6
        for i in range(layers, 0, -1):
            glow = QColor(accent)
            glow.setAlpha(int(65 * (i / layers) ** 2))
            pen = QPen(glow)
            pen.setWidth(i * 4)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(card_path)

        painter.setPen(QColor(_C["border"]))
        painter.setBrush(QColor(_C["panel_bg"]))
        painter.drawPath(path)


class TorusPrompt(QWidget):
    """A big, centred, halo'd Torus message with no tail/pointer - unlike
    TorusGuideBubble, which always points at something specific, this is a
    general instruction with nothing to point at yet. First use: Level 1's
    real first step, asking the learner to load a settings file before
    anything else can happen (see
    academy_window.AcademyWindow._show_load_settings_prompt). There are no
    buttons to click here - the caller drives it via ``set_text`` as the
    moment moves on (e.g. "Settings file loaded" -> "Loading Earth..."),
    and closes it once done (that window also owns hiding/showing itself
    around this, since the prompt deliberately doesn't touch anything but
    its own window).

    Also accepts a settings file dropped directly onto IT (not just onto
    the main window behind it) - it sits on top and always-on-top, so a
    drop aimed at the editor underneath can easily land on the prompt
    instead; ``fileDropped`` mirrors SettingsEditor.fileDropped (same
    .ini/.txt-from-the-first-url check) so the caller can wire it to the
    exact same load path.

    ``image_asset`` swaps the mascot image (see academy_content.
    celebration_for - a level's own celebration image, once one exists;
    every level uses the same academy_torus.png today). ``body_text``, if
    given, is a second line below the (bold) title, in a plain, non-bold
    weight - the load-settings prompt's short single-line messages ("Drag
    in a settings file...", "Settings file loaded") have no body and stay
    exactly as they were, but a level-completion celebration reads as one
    bold headline ("Level 1 complete.") followed by a few sentences of
    plain-weight detail, not a wall of bold text. ``button_text`` adds a
    Continue button below everything and a ``continued`` signal fired on
    click - used by show_level_celebration; the load-settings prompt (no
    button_text) stays driven externally via set_text/close, as before."""

    _MASCOT_SIZE = 120
    _WIDTH = 480

    fileDropped = Signal(str)
    continued = Signal()

    def __init__(self, html_text, body_text="", image_asset="academy_torus.png",
                 button_text=None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint |
                          Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAcceptDrops(True)

        outer = QVBoxLayout(self)
        pad = _HALO_INSET + _CARD_PADDING
        outer.setContentsMargins(pad, pad, pad, pad)
        outer.setSpacing(16)

        mascot = QLabel()
        pixmap = QPixmap(asset_path(image_asset))
        if not pixmap.isNull():
            dpr = self.devicePixelRatioF()
            scaled = pixmap.scaled(
                round(self._MASCOT_SIZE * dpr), round(self._MASCOT_SIZE * dpr),
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            mascot.setPixmap(scaled)
        mascot.setAlignment(Qt.AlignCenter)
        outer.addWidget(mascot, 0, Qt.AlignCenter)

        self.label = QLabel(html_text)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setStyleSheet(
            f"color: {_C['text']}; font-size: 22px; font-weight: 800;")
        outer.addWidget(self.label)

        self.body_label = QLabel(body_text)
        self.body_label.setAlignment(Qt.AlignCenter)
        self.body_label.setWordWrap(True)
        self.body_label.setStyleSheet(
            f"color: {_C['text']}; font-size: 15px; font-weight: 400;")
        self.body_label.setVisible(bool(body_text))
        outer.addWidget(self.body_label)

        self.continue_button = None
        if button_text:
            self.continue_button = QPushButton(button_text)
            self.continue_button.setStyleSheet(self._button_css())
            self.continue_button.clicked.connect(self.continued.emit)
            outer.addWidget(self.continue_button, 0, Qt.AlignCenter)

        self.setFixedWidth(self._WIDTH)

    def _button_css(self):
        return (f"QPushButton {{ background-color: {_C['btn_top']}; "
                f"color: {_C['btn_text']}; border: 1px solid {_C['btn_border']}; "
                "border-radius: 5px; padding: 7px 22px; font-size: 14px; }"
                f"QPushButton:hover {{ background-color: {_C['btn_hover_top']}; }}")

    def start(self):
        self.adjustSize()
        self._center()
        self.show()
        self.raise_()

    def set_text(self, html_text, body_text=""):
        """Update the message in place (the moment moves on - e.g. "Settings
        file loaded" -> "Loading Earth...") - re-centres since the new text
        may need a different height."""
        self.label.setText(html_text)
        self.body_label.setText(body_text)
        self.body_label.setVisible(bool(body_text))
        self.adjustSize()
        self._center()

    def _center(self):
        screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        x = geo.center().x() - self.width() // 2
        y = geo.center().y() - self.height() // 2
        self.move(x, y)

    def _dropped_settings_path(self, event):
        """Same check as SettingsEditor._dropped_settings_path - the local
        .ini/.txt file path carried by a drag/drop event's mime data, or
        None."""
        mime = event.mimeData()
        if not mime.hasUrls():
            return None
        urls = mime.urls()
        if not urls:
            return None
        path = urls[0].toLocalFile()
        if path and path.lower().endswith(('.ini', '.txt')):
            return path
        return None

    def dragEnterEvent(self, event):
        if self._dropped_settings_path(event):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event):
        if self._dropped_settings_path(event):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event):
        path = self._dropped_settings_path(event)
        if path:
            event.acceptProposedAction()
            self.fileDropped.emit(path)
            return
        event.ignore()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        inset = _HALO_INSET
        card = QRect(inset, inset, self.width() - 2 * inset,
                     self.height() - 2 * inset)
        path = QPainterPath()
        path.addRoundedRect(card, 18, 18)

        # Same hand-painted glow technique as TorusGuideBubble - see its
        # paintEvent for why this isn't a QGraphicsDropShadowEffect.
        accent = QColor(_C["accent"])
        painter.setBrush(Qt.NoBrush)
        layers = 6
        for i in range(layers, 0, -1):
            glow = QColor(accent)
            glow.setAlpha(int(70 * (i / layers) ** 2))
            pen = QPen(glow)
            pen.setWidth(i * 5)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.drawPath(path)

        painter.setPen(QColor(_C["border"]))
        painter.setBrush(QColor(_C["panel_bg"]))
        painter.drawPath(path)
