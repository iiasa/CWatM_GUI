"""
Date management for CWatM GUI.

Handles date validation and date widget management for the main window.
Provides functionality for creating date input widgets and validating
chronological order constraints.
"""

from PySide6.QtWidgets import (
    QDateEdit, QLabel, QHBoxLayout, QCalendarWidget, QWidget, QFrame,
    QVBoxLayout, QToolButton, QGraphicsDropShadowEffect, QAbstractSpinBox,
)
from PySide6.QtCore import QDate, Qt, QPoint, QPointF, QRectF, QSize
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QIcon


class CWatMCalendar(QCalendarWidget):
    """Custom-painted calendar popup for the Start/Spin/End date fields.

    Paint extras (all colours read from the theme at paint time):
    - the **selected day** as a filled accent circle (instead of Qt's square),
    - **today** as a thin accent ring,
    - the **other two date fields** as small coloured dots at the cell bottom
      (green = Start, orange = Spin, red = End), so e.g. Start and End are
      visible while picking the Spin date,
    - days **outside the meteo-forcing time coverage** dimmed - picking a day
      the forcing does not cover is the classic "crashes hours into the run"
      mistake (the coverage comes lazily from the main window via
      DateManager.refresh_forcing_range, cached until the next file load).
    """

    def __init__(self, key, manager, parent=None):
        super().__init__(parent)
        self._key = key      # 'start' | 'spin' | 'end'
        self._dm = manager
        self.setGridVisible(False)
        self.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)

    def showEvent(self, event):
        # Popup opening: make sure the forcing coverage is up to date (cheap when
        # cached; reads the first/last forcing NetCDF once per loaded file).
        try:
            self._dm.refresh_forcing_range()
        except Exception:
            pass
        super().showEvent(event)

    def paintCell(self, painter, rect, date):
        from src.gui.utils import theme
        sel = date == self.selectedDate()
        rng = self._dm.forcing_range()
        outside = rng is not None and (date < rng[0] or date > rng[1])
        painter.save()
        try:
            d = min(rect.width(), rect.height()) - 8
            cx, cy = rect.center().x(), rect.center().y()
            if sel:
                # Filled accent circle with contrasting day number
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(theme.c('menu_sel_bg')))
                painter.drawEllipse(cx - d // 2, cy - d // 2, d, d)
                painter.setPen(QColor(theme.c('menu_sel_text')))
                painter.drawText(rect, Qt.AlignCenter, str(date.day()))
            elif outside:
                # No forcing data on this day -> dimmed
                painter.setPen(QColor(theme.c('text_gray')))
                painter.drawText(rect, Qt.AlignCenter, str(date.day()))
            else:
                super().paintCell(painter, rect, date)
            if date == QDate.currentDate() and not sel:
                # Today: thin accent ring
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.setPen(QPen(QColor(theme.c('accent')), 1))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(cx - d // 2, cy - d // 2, d, d)
            # The OTHER two date fields as small dots at the cell bottom
            # (side by side when both fall on the same day, e.g. Spin == End)
            marks = [col for qd, col in self._dm.marker_dates(self._key)
                     if qd == date]
            for i, col in enumerate(marks):
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(col))
                r = 2
                off = int((i - (len(marks) - 1) / 2.0) * 6)
                painter.drawEllipse(cx - r + off, rect.bottom() - 2 * r - 2,
                                    2 * r, 2 * r)
        finally:
            painter.restore()


class _CalendarPopup(QWidget):
    """Web-style date-picker popup (option 3): a frameless, translucent window
    holding a rounded, drop-shadowed frame with a CWatMCalendar inside. Opened
    by the 📅 button next to a date field; Qt.Popup closes it on an outside
    click or Esc; clicking a day sets the field's date and closes."""

    def __init__(self, edit, key, manager):
        super().__init__(edit, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._edit = edit
        self._dm = manager
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 6, 14, 18)   # room for the drop shadow
        self._frame = QFrame()
        self._frame.setObjectName("calPopupFrame")
        flay = QVBoxLayout(self._frame)
        flay.setContentsMargins(8, 8, 8, 8)
        self._cal = CWatMCalendar(key, manager)
        self._cal.setMinimumSize(300, 220)
        flay.addWidget(self._cal)
        lay.addWidget(self._frame)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 5)
        shadow.setColor(QColor(0, 0, 0, 110))
        self._frame.setGraphicsEffect(shadow)
        self._cal.clicked.connect(self._pick)
        self._cal.activated.connect(self._pick)

    def _pick(self, qdate):
        self._edit.setDate(qdate)
        self.close()

    def open_for(self):
        """Style (current theme), sync to the field's date and show below the
        field (above when there is no room on the screen)."""
        from src.gui.utils import theme
        self._frame.setStyleSheet(
            f"QFrame#calPopupFrame {{ background-color: {theme.c('panel_bg')}; "
            f"border: 1px solid {theme.c('border')}; border-radius: 10px; }}")
        self._dm._style_calendar(self._cal)
        d = self._edit.date()
        self._cal.setSelectedDate(d)
        self._cal.setCurrentPage(d.year(), d.month())
        self.adjustSize()
        below = self._edit.mapToGlobal(QPoint(0, self._edit.height()))
        try:
            scr = self._edit.screen().availableGeometry()
            x = min(max(below.x() - 14, scr.left()), scr.right() - self.width())
            y = below.y()
            if y + self.height() > scr.bottom():
                y = self._edit.mapToGlobal(QPoint(0, 0)).y() - self.height()
        except Exception:
            x, y = below.x() - 14, below.y()
        self.move(x, y)
        self.show()
        self._cal.setFocus()


class DateTimeline(QWidget):
    """Three-handle date timeline (option 4), drawn below the Start/Spin/End
    fields. The fields stay the source of truth; the timeline mirrors them and
    dragging a handle writes the date back into its field (auto-apply as usual).

    Painted from theme tokens at paint time:
    - a thin axis track with the year at each end and a tick on "today",
    - the **meteo-forcing coverage** as a light band behind the track (days
      outside it have no band - the run cannot use them),
    - the Start→End run window as an accent bar,
    - three round handles: green = Start, orange = Spin, red = End (the same
      colours as the calendar marker dots).
    Dragging clamps each handle between its neighbours, so an invalid ordering
    (Spin before Start, End before Spin) is impossible by construction; the
    dragged handle shows its date above the track. Clicking the track jumps the
    nearest handle to the clicked day.
    """

    _GRAB = 10          # px hit radius for grabbing a handle
    _R = 6              # handle radius

    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self._dm = manager
        self._drag_key = None
        # Tall enough for the drag date label above the track (~24 px headroom)
        # plus the track, handles and the year labels below it.
        self.setMinimumHeight(48)
        self.setMouseTracking(True)
        self.setToolTip("Drag the handles to set Start (green), Spin (orange) "
                        "and End (red); the band shows the forcing coverage")

    # ------------------------------------------------------------ axis maths
    def _axis(self):
        """(lo, hi) QDates of the drawn axis: the three dates plus the forcing
        coverage, padded a little so handles never sit on the border."""
        dates = [w.date() for w in self._dm._edits().values() if w is not None]
        if not dates:
            today = QDate.currentDate()
            return today.addDays(-30), today.addDays(30)
        rng = self._dm.forcing_range()
        if rng is not None:
            dates += [rng[0], rng[1]]
        lo, hi = min(dates), max(dates)
        span = max(lo.daysTo(hi), 30)
        pad = max(span // 20, 5)
        return lo.addDays(-pad), hi.addDays(pad)

    def _track_rect(self):
        # y is fixed low enough that the drag date label (drawn 20 px above the
        # track) stays fully inside the widget, and high enough that the year
        # labels below (y+8 .. y+20) still fit.
        return 8, self.width() - 8, 26   # x0, x1, y

    def _x_of(self, qd, lo, hi, x0, x1):
        total = max(lo.daysTo(hi), 1)
        f = min(max(lo.daysTo(qd) / total, 0.0), 1.0)
        return int(round(x0 + f * (x1 - x0)))

    def _date_at(self, x, lo, hi, x0, x1):
        f = min(max((x - x0) / max(x1 - x0, 1), 0.0), 1.0)
        return lo.addDays(round(f * lo.daysTo(hi)))

    def _handles(self):
        """[(key, QDate, colour), ...] in draw order."""
        from src.gui.utils import theme
        cols = {'start': theme.c('ok_color'), 'spin': theme.c('bookmark'),
                'end': theme.c('warn_color')}
        out = []
        for key, w in self._dm._edits().items():
            if w is not None:
                out.append((key, w.date(), cols[key]))
        return out

    # --------------------------------------------------------------- painting
    def paintEvent(self, event):
        from src.gui.utils import theme
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            x0, x1, y = self._track_rect()
            lo, hi = self._axis()
            # Forcing coverage: light band behind the track
            rng = self._dm.forcing_range()
            if rng is not None:
                fx0 = self._x_of(rng[0], lo, hi, x0, x1)
                fx1 = self._x_of(rng[1], lo, hi, x0, x1)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(theme.c('changed_line')))
                painter.drawRect(fx0, y - 5, max(fx1 - fx0, 1), 10)
            # Axis track (plain solid line; the coverage band above shows the
            # meteo range)
            solid = QPen(QColor(theme.c('text_gray')), 1)
            painter.setPen(solid)
            painter.drawLine(x0, y, x1, y)
            # Today tick
            today = QDate.currentDate()
            if lo <= today <= hi:
                tx = self._x_of(today, lo, hi, x0, x1)
                painter.drawLine(tx, y - 6, tx, y + 6)
            # Start -> End run window as an accent bar
            edits = self._dm._edits()
            if edits['start'] is not None and edits['end'] is not None:
                sx = self._x_of(edits['start'].date(), lo, hi, x0, x1)
                ex = self._x_of(edits['end'].date(), lo, hi, x0, x1)
                painter.setPen(QPen(QColor(theme.c('accent')), 3))
                painter.drawLine(sx, y, ex, y)
            # Axis end labels (year of lo / hi)
            painter.setPen(QColor(theme.c('text_gray')))
            f = painter.font()
            f.setPointSize(7)
            painter.setFont(f)
            painter.drawText(x0, y + 8, 60, 12, Qt.AlignLeft | Qt.AlignTop,
                             str(lo.year()))
            painter.drawText(x1 - 60, y + 8, 60, 12, Qt.AlignRight | Qt.AlignTop,
                             str(hi.year()))
            # Handles (dragged one last = on top, with its date above the track)
            handles = self._handles()
            if self._drag_key:
                handles.sort(key=lambda h: h[0] == self._drag_key)
            for key, qd, col in handles:
                hx = self._x_of(qd, lo, hi, x0, x1)
                painter.setPen(QPen(QColor("#ffffff"), 2))
                painter.setBrush(QColor(col))
                painter.drawEllipse(QPoint(hx, y), self._R, self._R)
                if key == self._drag_key:
                    painter.setPen(QColor(theme.c('text')))
                    painter.drawText(min(max(hx - 40, x0 - 6), x1 - 74), y - 20,
                                     80, 12, Qt.AlignHCenter | Qt.AlignTop,
                                     qd.toString("dd/MM/yyyy"))
        except Exception:
            pass
        finally:
            painter.end()

    # ------------------------------------------------------------ interaction
    def _key_near(self, pos):
        """Handle key within grab distance of ``pos``, nearest first; None if far."""
        x0, x1, y = self._track_rect()
        lo, hi = self._axis()
        best, best_d = None, None
        for key, qd, _col in self._handles():
            hx = self._x_of(qd, lo, hi, x0, x1)
            d = (pos.x() - hx) ** 2 + (pos.y() - y) ** 2
            if best_d is None or d < best_d:
                best, best_d = key, d
        if best is not None and best_d is not None \
                and best_d <= self._GRAB * self._GRAB:
            return best
        return None

    def _clamp(self, key, qd):
        """Keep Start <= Spin <= End while dragging."""
        edits = self._dm._edits()
        if key == 'start' and edits['spin'] is not None:
            return min(qd, edits['spin'].date())
        if key == 'end' and edits['spin'] is not None:
            return max(qd, edits['spin'].date())
        if key == 'spin':
            if edits['start'] is not None:
                qd = max(qd, edits['start'].date())
            if edits['end'] is not None:
                qd = min(qd, edits['end'].date())
        return qd

    def _apply(self, key, qd):
        edit = self._dm._edits().get(key)
        if edit is not None:
            edit.setDate(self._clamp(key, qd))
        self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        # One-time (per loaded file) lazy read of the forcing coverage
        try:
            self._dm.refresh_forcing_range()
        except Exception:
            pass
        key = self._key_near(event.pos())
        x0, x1, y = self._track_rect()
        lo, hi = self._axis()
        if key is None:
            # Click on the track: jump the nearest handle to the clicked day
            qd = self._date_at(event.pos().x(), lo, hi, x0, x1)
            best, best_d = None, None
            for k, hd, _c in self._handles():
                d = abs(hd.daysTo(qd))
                if best_d is None or d < best_d:
                    best, best_d = k, d
            key = best
        if key is None:
            return
        self._drag_key = key
        self._apply(key, self._date_at(event.pos().x(), lo, hi, x0, x1))

    def mouseMoveEvent(self, event):
        if self._drag_key:
            x0, x1, _y = self._track_rect()
            lo, hi = self._axis()
            self._apply(self._drag_key,
                        self._date_at(event.pos().x(), lo, hi, x0, x1))
        else:
            self.setCursor(Qt.SizeHorCursor if self._key_near(event.pos())
                           else Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        self._drag_key = None
        self.update()


class DateManager:
    """Manages date input fields and validation.
    
    This class handles the creation and management of date input widgets
    for the CWatM GUI, including start date, spin-up date, and end date.
    Provides validation to ensure proper chronological ordering.
    
    Attributes
    ----------
    start_date_edit : QDateEdit or None
        Date input widget for simulation start date
    spin_date_edit : QDateEdit or None
        Date input widget for spin-up completion date
    end_date_edit : QDateEdit or None
        Date input widget for simulation end date
    """
    
    def __init__(self):
        """Initialize the date manager.
        
        Sets up empty references to date input widgets that will be
        created later by create_date_widgets().
        """
        self.start_date_edit = None
        self.spin_date_edit = None
        self.end_date_edit = None
        # Meteo-forcing time coverage for the calendar popups (CWatMCalendar):
        # provider set by the main window, result cached until the next file load
        self._forcing_provider = None
        self._forcing_range = None    # (QDate, QDate) or None
        self._forcing_dirty = True
        # Web-style picker (option 3): 📅 buttons + frameless popups; classic
        # QDateEdit drop-down restorable via Configure > Web-style date picker
        self._web_picker = False
        self._cal_buttons = {}        # key -> QToolButton (📅)
        self._popups = {}             # key -> _CalendarPopup (lazy)
        # Three-handle date timeline (option 4) below the date row
        self.timeline = None
        
    def create_date_widgets(self, parent_layout):
        """Create and setup date input widgets.
        
        Creates three date input widgets (start, spin, end) with calendar
        popups and validation callbacks. Widgets are styled and connected
        to validation methods.
        
        Parameters
        ----------
        parent_layout : QLayout
            The parent layout to add the date widgets to
        """
        date_layout = QHBoxLayout()
        date_layout.setContentsMargins(0, 0, 0, 0)

        # Start Date
        date_label = QLabel("Start Date:")
        self.start_date_edit = QDateEdit()
        self.start_date_edit.setDate(QDate.currentDate())
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setCalendarWidget(CWatMCalendar('start', self))
        # width set exactly to the date text in retheme()
        self.start_date_edit.setMinimumHeight(28)  # 2px tighter row
        self.start_date_edit.dateChanged.connect(self.validate_dates)
        date_layout.addWidget(date_label)
        date_layout.addWidget(self.start_date_edit)
        date_layout.addWidget(self._make_cal_button('start'))

        # Spin Date
        spin_date_label = QLabel("Spin Date:")
        self.spin_date_edit = QDateEdit()
        self.spin_date_edit.setDate(QDate.currentDate().addDays(0))
        self.spin_date_edit.setCalendarPopup(True)
        self.spin_date_edit.setCalendarWidget(CWatMCalendar('spin', self))
        self.spin_date_edit.setMinimumHeight(28)  # 2px tighter row
        self.spin_date_edit.dateChanged.connect(self.validate_dates)
        date_layout.addWidget(spin_date_label)
        date_layout.addWidget(self.spin_date_edit)
        date_layout.addWidget(self._make_cal_button('spin'))
        
        # End Date
        end_date_label = QLabel("End Date:")
        self.end_date_edit = QDateEdit()
        self.end_date_edit.setDate(QDate.currentDate().addDays(0))
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setCalendarWidget(CWatMCalendar('end', self))
        self.end_date_edit.setMinimumHeight(28)  # 2px tighter row
        self.end_date_edit.dateChanged.connect(self.validate_dates)
        date_layout.addWidget(end_date_label)
        date_layout.addWidget(self.end_date_edit)
        date_layout.addWidget(self._make_cal_button('end'))

        date_layout.addStretch()
        parent_layout.addLayout(date_layout)

        # Three-handle timeline below the fields (mirrors them, drag writes back);
        # left-aligned so the width sync with the output box keeps it flush left
        self.timeline = DateTimeline(self)
        parent_layout.addWidget(self.timeline, 0, Qt.AlignLeft)
        for w in self._edits().values():
            w.dateChanged.connect(lambda *_: self.timeline.update())

        self.retheme()

    def retheme(self):
        """(Re-)apply the theme's field colours to the three date widgets and
        restyle their calendar popups (flat, theme-token based: no grid, no
        week-number column, accent-coloured selection, uniform weekend colour)."""
        from PySide6.QtWidgets import QCalendarWidget
        from PySide6.QtGui import QTextCharFormat, QColor
        from src.gui.utils import theme

        style = (f"QDateEdit {{ background-color: {theme.c('field_bg')}; "
                 f"color: {theme.c('field_text')}; }}")
        # The "Pick a date" BUTTONS carry the handle colour (green = Start,
        # orange = Spin, red = End): background at 70% transparency, border +
        # icon in the full colour.
        _key_tokens = {'start': 'ok_color', 'spin': 'bookmark',
                       'end': 'warn_color'}

        def _tint(token):
            qc = QColor(theme.c(token))
            return f"rgba({qc.red()},{qc.green()},{qc.blue()},77)"
        cal_qss = f"""
            QCalendarWidget QWidget#qt_calendar_navigationbar {{
                background-color: {theme.c('surface_bg')};
                border: none;
            }}
            QCalendarWidget QToolButton {{
                background: transparent; border: none; border-radius: 6px;
                color: {theme.c('text')}; font-weight: 600;
                padding: 4px 8px; margin: 2px;
            }}
            QCalendarWidget QToolButton:hover {{
                background-color: {theme.c('btn_hover_bottom')};
            }}
            QCalendarWidget QToolButton:pressed {{
                background-color: {theme.c('btn_press_bottom')};
            }}
            QCalendarWidget QToolButton::menu-indicator {{ image: none; }}
            QCalendarWidget QMenu {{
                background-color: {theme.c('panel_bg')};
                color: {theme.c('text')};
                selection-background-color: {theme.c('menu_sel_bg')};
                selection-color: {theme.c('menu_sel_text')};
            }}
            QCalendarWidget QSpinBox {{
                background-color: {theme.c('field_bg')};
                color: {theme.c('field_text')};
                border: 1px solid {theme.c('field_border')};
                border-radius: 4px; padding: 2px;
            }}
            QCalendarWidget QAbstractItemView:enabled {{
                background-color: {theme.c('panel_bg')};
                color: {theme.c('text')};
                selection-background-color: {theme.c('menu_sel_bg')};
                selection-color: {theme.c('menu_sel_text')};
                outline: none;
            }}
            QCalendarWidget QAbstractItemView:disabled {{
                color: {theme.c('text_gray')};
            }}
        """
        self._cal_qss = cal_qss
        for key, w in self._edits().items():
            if w is None:
                continue
            w.setStyleSheet(style)
            # Exactly as wide as the widget needs for the date (Qt's own hint
            # covers text + frame + the classic drop-down arrow), not wider.
            w.setFixedWidth(w.sizeHint().width())
            btn = self._cal_buttons.get(key)
            if btn is not None:
                tok = _key_tokens[key]
                btn.setStyleSheet(
                    f"QToolButton {{ background-color: {_tint(tok)}; "
                    f"border: 1px solid {theme.c(tok)}; border-radius: 6px; }}"
                    f"QToolButton:hover {{ background-color: {theme.c(tok)}; }}"
                    f"QToolButton:pressed {{ background-color: {_tint(tok)}; }}")
                btn.setIcon(self._calendar_icon(theme.c(tok)))
            cal = w.calendarWidget()   # None while the web-style picker is on
            if cal is not None:
                self._style_calendar(cal)
        for pop in self._popups.values():
            self._style_calendar(pop._cal)
        if self.timeline is not None:
            self.timeline.update()   # reads theme tokens at paint time

    def _style_calendar(self, cal):
        """Apply the theme QSS + text formats to one calendar widget (drop-down
        or web-style popup): no grid / week numbers, muted day-name header,
        weekend cells in the normal text colour (default Qt red reads dated)."""
        from PySide6.QtGui import QTextCharFormat
        from src.gui.utils import theme
        cal.setGridVisible(False)
        cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        cal.setStyleSheet(getattr(self, "_cal_qss", ""))
        plain = QTextCharFormat()
        plain.setForeground(QColor(theme.c('text')))
        header = QTextCharFormat()
        header.setForeground(QColor(theme.c('text_gray')))
        cal.setHeaderTextFormat(header)
        for day in (Qt.Saturday, Qt.Sunday):
            cal.setWeekdayTextFormat(day, plain)
        
    # -------------------------------------------- web-style picker (option 3)
    def _edits(self):
        return {'start': self.start_date_edit, 'spin': self.spin_date_edit,
                'end': self.end_date_edit}

    def _make_cal_button(self, key):
        """Calendar button right of a date field (web-style picker mode only);
        its icon is painted in the theme accent colour (retheme) so it stays
        clearly visible in every mode."""
        btn = QToolButton()
        btn.setCursor(Qt.PointingHandCursor)
        btn.setToolTip("Pick a date")
        btn.setFixedSize(30, 28)
        btn.setIconSize(QSize(20, 20))
        btn.clicked.connect(lambda: self._open_popup(key))
        btn.setVisible(False)   # shown by set_web_picker(True)
        self._cal_buttons[key] = btn
        return btn

    @staticmethod
    def _calendar_icon(color=None):
        """Crisp calendar glyph painted in ``color`` (default: theme accent);
        20x20 logical, 2x pixmap: outlined body, filled header bar, two binder
        rings, day dots."""
        from src.gui.utils import theme
        accent = QColor(color or theme.c('accent'))
        pm = QPixmap(40, 40)
        pm.setDevicePixelRatio(2.0)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            p.setPen(QPen(accent, 1.6))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(2.5, 4.0, 15.0, 13.5), 2.5, 2.5)
            # header bar
            p.setPen(Qt.NoPen)
            p.setBrush(accent)
            p.drawRect(QRectF(3.3, 4.8, 13.4, 3.2))
            # binder rings
            p.setPen(QPen(accent, 1.6))
            p.drawLine(QPointF(6.5, 2.0), QPointF(6.5, 6.0))
            p.drawLine(QPointF(13.5, 2.0), QPointF(13.5, 6.0))
            # day dots
            p.setPen(Qt.NoPen)
            for gx in (6.0, 10.0, 14.0):
                for gy in (11.5, 15.0):
                    p.drawEllipse(QPointF(gx, gy), 1.15, 1.15)
        finally:
            p.end()
        return QIcon(pm)

    def _open_popup(self, key):
        edit = self._edits().get(key)
        if edit is None:
            return
        pop = self._popups.get(key)
        if pop is None:
            pop = _CalendarPopup(edit, key, self)
            self._popups[key] = pop
        pop.open_for()

    def set_web_picker(self, on):
        """Switch between the web-style picker (📅 button + frameless shadowed
        popup; the field's arrows step the date) and the classic QDateEdit
        drop-down calendar. Toggled by Configure ▸ Web-style date picker."""
        self._web_picker = bool(on)
        for key, edit in self._edits().items():
            btn = self._cal_buttons.get(key)
            if btn is not None:
                btn.setVisible(self._web_picker)
            if edit is None:
                continue
            if self._web_picker:
                edit.setCalendarPopup(False)
                # No spin arrows - the calendar button is the way to pick
                edit.setButtonSymbols(QAbstractSpinBox.NoButtons)
            else:
                # Going back: restore the drop-down with a fresh custom calendar
                # (setCalendarPopup(False) may have dropped the old one).
                edit.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
                edit.setCalendarPopup(True)
                edit.setCalendarWidget(CWatMCalendar(key, self))
        self.retheme()

    # ------------------------------------------- calendar-popup extras (option 2)
    def marker_dates(self, exclude_key):
        """[(QDate, colour), ...] of the OTHER two date fields for the calendar of
        ``exclude_key`` - green = Start, orange = Spin, red = End (theme tokens)."""
        from src.gui.utils import theme
        cols = {'start': theme.c('ok_color'), 'spin': theme.c('bookmark'),
                'end': theme.c('warn_color')}
        edits = {'start': self.start_date_edit, 'spin': self.spin_date_edit,
                 'end': self.end_date_edit}
        out = []
        for key, w in edits.items():
            if key != exclude_key and w is not None:
                out.append((w.date(), cols[key]))
        return out

    def set_forcing_provider(self, fn):
        """``fn()`` -> (QDate, QDate) meteo-forcing coverage or None; set by the
        main window. Called lazily (cached) when a calendar popup opens."""
        self._forcing_provider = fn
        self._forcing_dirty = True

    def invalidate_forcing_range(self):
        """Forget the cached forcing coverage (a new settings file was loaded)
        and schedule a deferred re-read, so the timeline shows the coverage band
        and dashed out-of-range segments without waiting for a click."""
        self._forcing_dirty = True
        from PySide6.QtCore import QTimer
        QTimer.singleShot(1200, self.refresh_forcing_range)

    def refresh_forcing_range(self):
        """Recompute the forcing coverage if it is stale (calendar showEvent,
        timeline click)."""
        if not self._forcing_dirty or self._forcing_provider is None:
            return
        self._forcing_dirty = False   # even a failed read: don't retry every open
        try:
            self._forcing_range = self._forcing_provider()
        except Exception:
            self._forcing_range = None
        if self.timeline is not None:
            self.timeline.update()    # show the new coverage band

    def set_timeline_visible(self, on):
        """Configure ▸ Date timeline: show/hide the three-handle timeline."""
        if self.timeline is not None:
            self.timeline.setVisible(bool(on))

    def forcing_range(self):
        """Cached (QDate, QDate) forcing coverage, or None when unknown."""
        return self._forcing_range

    def validate_dates(self):
        """Ensure chronological order of dates"""
        if not all([self.start_date_edit, self.spin_date_edit, self.end_date_edit]):
            return
            
        start_date = self.start_date_edit.date()
        spin_date = self.spin_date_edit.date()
        end_date = self.end_date_edit.date()
        
        # Ensure spin_date is not earlier than start_date
        if spin_date < start_date:
            self.spin_date_edit.setDate(start_date)
            
        # Ensure end_date is not earlier than spin_date
        spin_date = self.spin_date_edit.date()  # Get updated spin_date
        if end_date < spin_date:
            self.end_date_edit.setDate(spin_date)
    
    def _resolve_date_value(self, value, config_parser, start_date_obj):
        """Resolve a StepStart/SpinUp/StepEnd value to a QDate.

        In CWatM settings, SpinUp and StepEnd may be given either as a date or as a
        plain integer. The integer is a timestep number counted from StepStart, which
        is timestep 1 (see datetoInt in cwatm/management_modules/timestep.py). So an
        integer N corresponds to the date StepStart + (N - 1) days. Returns None if
        the value is neither a date nor an integer (or no start date is available to
        offset from).
        """
        if not value:
            return None

        # First try a real date string (dd/mm/yyyy, yyyy-mm-dd, ...)
        date_obj = config_parser.parse_date_value(value)
        if date_obj:
            return date_obj

        # Otherwise treat it as an integer offset of timesteps from StepStart
        try:
            n = int(float(str(value).strip()))
        except (ValueError, TypeError):
            return None
        if start_date_obj is None:
            return None
        return start_date_obj.addDays(n - 1)

    def set_dates_from_config(self, date_values, config_parser):
        """Update date fields from parsed configuration values"""
        if not all([self.start_date_edit, self.spin_date_edit, self.end_date_edit]):
            return
        # New settings content -> the forcing coverage may have changed
        self.invalidate_forcing_range()

        step_start = date_values.get('stepstart')
        spin_up = date_values.get('spinup')
        step_end = date_values.get('stepend')

        start_date_obj = None
        if step_start:
            start_date_obj = config_parser.parse_date_value(step_start)
            if start_date_obj:
                self.start_date_edit.setDate(start_date_obj)

        if spin_up:
            spin_date_obj = self._resolve_date_value(spin_up, config_parser, start_date_obj)
            if spin_date_obj:
                self.spin_date_edit.setDate(spin_date_obj)
            elif start_date_obj:
                # If SpinUp is neither a valid date nor an integer, use StepStart date
                self.spin_date_edit.setDate(start_date_obj)

        if step_end:
            end_date_obj = self._resolve_date_value(step_end, config_parser, start_date_obj)
            if end_date_obj:
                self.end_date_edit.setDate(end_date_obj)
            elif start_date_obj:
                # If StepEnd is neither a valid date nor an integer, fall back to StepStart
                self.end_date_edit.setDate(start_date_obj)
    
    def get_current_dates(self):
        """Get current date values from widgets"""
        if not all([self.start_date_edit, self.spin_date_edit, self.end_date_edit]):
            return None, None, None
            
        return (
            self.start_date_edit.date(),
            self.spin_date_edit.date(), 
            self.end_date_edit.date()
        )
    
    def dates_changed_from_config(self, current_config_dates):
        """Check if current widget dates differ from config file dates"""
        start_date, spin_date, end_date = self.get_current_dates()
        if not all([start_date, spin_date, end_date]):
            return False
            
        start_date_str = start_date.toString("dd/MM/yyyy")
        spin_date_str = spin_date.toString("dd/MM/yyyy")
        end_date_str = end_date.toString("dd/MM/yyyy")
        
        return (current_config_dates.get('stepstart') != start_date_str or 
                current_config_dates.get('spinup') != spin_date_str or 
                current_config_dates.get('stepend') != end_date_str)