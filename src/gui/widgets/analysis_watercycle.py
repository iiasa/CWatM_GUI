"""
Watercycle analysis widget for the CWatM GUI.

Opens a CWatM ``WaterCycle_areasum_monthtot.csv`` result file and shows the
overall water balance as a Plotly **sunburst** diagram inside a window (same
style as the Timeseries window). The sunburst computation is ported from the
stand-alone ``Watercycles1.py`` template.

CWatM WaterCycle csv layout (same header convention as the other result files):
    row 1: "Timeseries, settingsfile: ..., Running date: ..., CWATM: ..."
    row 2: "xloc, <lon>"          <- station longitude (subtitle)
    row 3: "yloc, <lat>"          <- station latitude  (subtitle)
    row 4: "Date, cellArea_sum_m3, Rain_areasum_m3, ..."  <- column names
    row 5+: "<dd/mm/yyyy>, <value>, ..."                   <- monthly totals

The window title is the settings-file ``Title``; the subtitle shows the station
lon/lat. A "Save HTML" button stores the self-contained Plotly plot, exactly like
the Timeseries window.
"""

import os
import sys
import csv
import datetime
from calendar import monthrange

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QWidget, QSizePolicy,
)
from PySide6.QtCore import Qt, QTimer, QPointF, Signal
from PySide6.QtGui import QIcon, QPainter, QColor, QPen, QBrush

from src.gui.utils import theme
from src.gui.utils.window_geometry import scaled_default_size
from src.gui.widgets.analysis_plot_base import PlotlyWindowBase

from src.gui.utils.gui_log import get_logger

log = get_logger("analysis_watercycle")

# Optional dependencies: Plotly for the figure, QtWebEngine to render it, pandas/numpy.
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    import plotly.graph_objects as go
    import numpy as np
    import pandas as pd
    _WC_AVAILABLE = True
    _WC_IMPORT_ERROR = ""
except Exception as _wc_err:  # pragma: no cover - import guard
    _WC_AVAILABLE = False
    _WC_IMPORT_ERROR = f"{type(_wc_err).__name__}: {_wc_err}"
    print(f"Watercycle analysis unavailable: {_WC_IMPORT_ERROR}", file=sys.stderr)


# Runs after the sunburst is drawn: remembers the wedge under the mouse, so the
# Qt-native right-click menu (WatercycleWindow._on_web_context_menu) knows which
# sector was clicked. Plotly replaces {plot_id} with the div id.
_HOVER_JS = """
var gd = document.getElementById('{plot_id}');
window._wcHover = null;
gd.on('plotly_hover', function (e) {
    var p = e && e.points && e.points[0];
    window._wcHover = p ? {label: p.label, parent: p.parent || ''} : null;
});
gd.on('plotly_unhover', function () { window._wcHover = null; });
"""


def open_watercycle(parent=None):
    """Prompt for a WaterCycle result .csv file and open the sunburst window.

    Records the opened window on ``parent._last_watercycle_window`` right
    before showing it - reached only once a real file was picked and the
    window built without error (a cancelled file dialog returns before this
    point) - so CWatM Academy's Level 2 walkthrough can gate its own
    completion on this actually having happened, instead of just trusting
    the learner clicked through the menu (see
    academy_window.AcademyWindow._watercycle_opened)."""
    if not _WC_AVAILABLE:
        QMessageBox.warning(
            parent, "Watercycle",
            "Plotly / QtWebEngine / pandas are not available.\n\n" + _WC_IMPORT_ERROR
            + "\n\nInstall with:  pip install plotly pandas")
        return
    start_dir = ""
    try:
        if parent is not None and hasattr(parent, "_resolved_pathout_dir"):
            start_dir = parent._resolved_pathout_dir() or ""
    except Exception:
        start_dir = ""
    path, _ = QFileDialog.getOpenFileName(
        parent, "Open WaterCycle result CSV", start_dir, "CSV result files (*.csv)")
    if not path:
        return
    try:
        win = WatercycleWindow(path, parent)
        if parent is not None:
            try:
                parent._last_watercycle_window = win
            except Exception:
                log.debug("open_watercycle: could not record _last_watercycle_window",
                          exc_info=True)
        win.exec()
    except Exception as e:
        import traceback
        traceback.print_exc()
        QMessageBox.warning(parent, "Watercycle", f"Could not open the file:\n{e}")


class RangeSlider(QWidget):
    """A minimal two-handle range slider over integer indices ``[minimum, maximum]``.

    Both handles are draggable; the low handle is kept at least ``_min_gap`` (1) below
    the high handle - **except** when the low handle sits at the very start of the
    range (``low == minimum``), where the high handle is kept at least 2 below
    instead. That is not cosmetic: Watercycle's sunburst measures storage *change*
    over the window, which needs one month *before* the window to serve as the
    baseline (``baseline_idx = start_idx - 1``); when the window starts at month 0
    there is no month before it, so month 0 itself is sacrificed as the baseline and
    the flux data actually starts one month later (``flux_start = 1``, see
    ``WatercycleWindow._build_figure``). A 1-month gap at the very start would then
    describe a **zero**-month flux window instead of one month like everywhere else
    on the slider - requiring a 2-month gap there keeps "N months selected" meaning
    the same thing regardless of where the window starts. Flow Diagram shares this
    widget and does not need the extra month itself (no storage-change baseline), but
    gets the same slider behaviour for consistency. Emits ``rangeChanged(low, high)``
    on every move."""

    rangeChanged = Signal(int, int)

    def __init__(self, minimum=0, maximum=1, low=0, high=1, parent=None):
        super().__init__(parent)
        self._min = int(minimum)
        self._max = int(maximum)
        self._low = int(low)
        self._high = int(high)
        self._min_gap = 1
        self._active = None          # 'low' | 'high' | None
        self._handle_r = 8
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)

    def low(self):
        return self._low

    def high(self):
        return self._high

    def setLow(self, v):
        v = max(self._min, min(int(v), self._high - self._min_gap))
        if v != self._low:
            self._low = v
            self.update()
            self.rangeChanged.emit(self._low, self._high)

    def setHigh(self, v):
        # See the class docstring: the low handle being pinned at the very start of
        # the range needs an extra month's gap (the baseline-shift edge case).
        gap = self._min_gap + 1 if self._low == self._min else self._min_gap
        v = min(self._max, max(int(v), self._low + gap))
        if v != self._high:
            self._high = v
            self.update()
            self.rangeChanged.emit(self._low, self._high)

    # ---- geometry helpers ----
    def _groove(self):
        m = self._handle_r + 2
        return m, self.width() - m, self.height() // 2

    def _val_to_x(self, val):
        x0, x1, _ = self._groove()
        if self._max == self._min:
            return x0
        return x0 + (x1 - x0) * (val - self._min) / (self._max - self._min)

    def _x_to_val(self, x):
        x0, x1, _ = self._groove()
        if x1 == x0:
            return self._min
        frac = max(0.0, min(1.0, (x - x0) / (x1 - x0)))
        return int(round(self._min + frac * (self._max - self._min)))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        x0, x1, y = self._groove()
        xl, xh = self._val_to_x(self._low), self._val_to_x(self._high)
        # groove
        p.setPen(QPen(QColor(theme.c('border')), 3))
        p.drawLine(x0, y, x1, y)
        # selected span
        p.setPen(QPen(QColor('#3498db'), 4))
        p.drawLine(int(xl), y, int(xh), y)
        # handles
        p.setPen(QPen(QColor('#2980b9'), 1))
        p.setBrush(QBrush(QColor('#5dade2')))
        for xv in (xl, xh):
            p.drawEllipse(QPointF(xv, y), self._handle_r, self._handle_r)
        p.end()

    def mousePressEvent(self, event):
        x = event.position().x()
        xl, xh = self._val_to_x(self._low), self._val_to_x(self._high)
        if x < xl:
            self._active = 'low'
        elif x > xh:
            self._active = 'high'
        else:
            self._active = 'low' if abs(x - xl) <= abs(x - xh) else 'high'
        self._move_to(x)

    def mouseMoveEvent(self, event):
        if self._active:
            self._move_to(event.position().x())

    def mouseReleaseEvent(self, event):
        self._active = None

    def _move_to(self, x):
        val = self._x_to_val(x)
        if self._active == 'low':
            self.setLow(val)
        elif self._active == 'high':
            self.setHigh(val)


class WatercycleWindow(PlotlyWindowBase):
    """Window showing the overall water balance of a WaterCycle csv as a sunburst."""

    _save_fallback = "watercycle"
    _csv_name = "watercycle.csv"

    def __init__(self, csv_path, parent=None):
        super().__init__(parent)
        self.csv_path = csv_path
        # Window/plot title = the settings-file "Title".
        self.settings_title = self._read_settings_title(csv_path)

        # Read the monthly data once; the sunburst is recomputed for the selected
        # [start, end] month window (defaults to the full span). A WaterCycle csv can
        # hold several stations side by side (fixed-width variable blocks after the
        # Date column); _load_data parses them all and selects the first, which sets
        # self.lon / self.lat / self._df / self._cellAreaSum.
        self._load_data(csv_path)

        title = self.settings_title or os.path.basename(str(csv_path))
        self.setWindowTitle(f"\U0001F300 Watercycle: {title}")
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)

        # Key bumped ("...4") so a geometry saved by an earlier, differently-sized
        # default is ignored and the new compact default below takes effect. Height is
        # trimmed to just fit the (now page-filling) sunburst plus the header, slider
        # and Save-HTML button, with no scrollbar.
        self._geometry_was_restored = self._init_geometry_memory("watercycle4")
        if not self._geometry_was_restored:
            self.resize(*scaled_default_size(self, 540, 560))
        try:
            icon_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                'assets', 'cwatm.ico')
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            log.debug("__init__: ignored", exc_info=True)

        self._temp_html = None
        # Debounce heavy figure rebuilds while dragging the range slider.
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(200)
        self._rebuild_timer.timeout.connect(self._show_sunburst)
        self._build_ui()
        self._show_sunburst()

    # ------------------------------------------------------------------ parsing
    @staticmethod
    def _fmt3(value):
        """Format a coordinate string to 3 decimals (raw string if not numeric)."""
        try:
            return f"{float(value):.3f}"
        except (TypeError, ValueError):
            return value

    @staticmethod
    def _read_station(csv_path):
        """(lon, lat) of the FIRST station: row 2 col 2 and row 3 col 2, as strings."""
        lon = lat = ""
        try:
            with open(csv_path, encoding="utf-8", errors="ignore", newline="") as f:
                rows = list(csv.reader(f))
            if len(rows) > 1 and len(rows[1]) > 1:
                lon = rows[1][1].strip()
            if len(rows) > 2 and len(rows[2]) > 1:
                lat = rows[2][1].strip()
        except Exception:
            log.debug("_read_station: ignored", exc_info=True)
        return lon, lat

    def _title_from_settings_content(self, content):
        for line in (content or "").split("\n"):
            s = line.strip()
            if s.startswith("#") or s.startswith(";") or "=" not in s:
                continue
            key, value = s.split("=", 1)
            if key.strip().lower() == "title":
                return value.strip()
        return ""

    def _read_settings_title(self, csv_path):
        """The settings-file 'Title': from the settings file named in the CSV header
        (row 1), else the title currently loaded in the main window."""
        try:
            with open(csv_path, encoding="utf-8", errors="ignore", newline="") as f:
                first = f.readline()
            for cell in first.split(","):
                c = cell.strip()
                if c.lower().startswith("settingsfile:"):
                    path = c.split(":", 1)[1].strip()
                    if path and os.path.exists(path):
                        with open(path, encoding="utf-8", errors="ignore") as _f:
                            content = _f.read()
                        t = self._title_from_settings_content(content)
                        if t:
                            return t
                    break
        except Exception:
            log.debug("_read_settings_title: ignored", exc_info=True)
        try:
            mw = self.parent()
            if mw is not None and hasattr(mw, "original_content"):
                t = self._title_from_settings_content(mw.original_content or "")
                if t:
                    return t
        except Exception:
            log.debug("_read_settings_title: ignored", exc_info=True)
        return ""

    def _load_data(self, csv_path):
        """Read the monthly totals once and cache them, plus the selected window.

        A WaterCycle csv can contain several stations laid out side by side: after
        the Date column, each station occupies a **fixed-width block** of variable
        columns (the same set of ``<var>_<unit>`` names is repeated per station, and
        the station's lon/lat is repeated across its block in rows 2/3). The block
        width is detected from the first repeat of the leading variable name, so a
        single-station csv (no repeat) behaves exactly as before.
        """
        # Raw header rows via csv.reader (row 2 = xloc, row 3 = yloc, row 4 = names).
        with open(csv_path, encoding="utf-8", errors="ignore", newline="") as f:
            raw = list(csv.reader(f))
        names_all = [c.strip() for c in raw[3][1:]] if len(raw) > 3 else []
        xrow = [c.strip() for c in raw[1][1:]] if len(raw) > 1 else []
        yrow = [c.strip() for c in raw[2][1:]] if len(raw) > 2 else []
        # Block width = index of the first repeat of the leading column name.
        block = len(names_all)
        if names_all:
            first = names_all[0]
            for j in range(1, len(names_all)):
                if names_all[j] == first:
                    block = j
                    break
        if block <= 0:
            block = len(names_all) or 1
        nstations = max(1, len(names_all) // block) if names_all else 1
        self._block_size = block
        self._nstations = nstations
        self._station_names = names_all[:block]
        # Per-station lon/lat = the first column of each block (repeated across it).
        self._station_coords = []
        for s in range(nstations):
            c = s * block
            lon = xrow[c] if c < len(xrow) else ""
            lat = yrow[c] if c < len(yrow) else ""
            self._station_coords.append((lon, lat))

        # Numeric data: row 4 is the column-name header, so skip 4 rows and read
        # headerless (repeated names would otherwise be de-duplicated by pandas).
        full = pd.read_csv(csv_path, skiprows=4, header=None)
        self._full = full
        # Parse the date column (column 0) separately.
        month_dates = pd.to_datetime(full.iloc[:, 0], format='%d/%m/%Y').tolist()
        if len(month_dates) < 2:
            raise ValueError("The WaterCycle csv needs at least two months of data.")
        self._month_dates = month_dates
        self._days_in_month = np.array(
            [monthrange(d.year, d.month)[1] for d in month_dates])
        self._n = len(month_dates)
        # Selected window: full span by default (indices into month_dates).
        self._start_idx = 0
        self._end_idx = self._n - 1
        # Select the first station (sets self._df / self._cellAreaSum / lon / lat).
        self._select_station(0)

    def _select_station(self, idx):
        """Slice the current station's block into self._df with canonical column
        names and refresh self._cellAreaSum / self.lon / self.lat."""
        idx = max(0, min(int(idx), self._nstations - 1))
        self._station_idx = idx
        block = self._block_size
        start = 1 + idx * block                       # +1 for the leading Date column
        cols = [0] + list(range(start, start + block))
        sub = self._full.iloc[:, cols].copy()
        # A variable name can legitimately repeat WITHIN a block (CWatM's watercycle
        # list holds e.g. act_livConsumption twice). Mangle repeats to "name.1" like
        # pandas' header reader used to, so df[name] stays a Series (the first
        # occurrence) and the balance computations behave as before.
        seen = {}
        names = []
        for name in self._station_names:
            k = seen.get(name, 0)
            seen[name] = k + 1
            names.append(name if k == 0 else f"{name}.{k}")
        sub.columns = ['Date'] + names
        self._df = sub
        self._cellAreaSum = sub['cellArea_sum_m3'].to_numpy()[0] / self._days_in_month[0]
        lon, lat = self._station_coords[idx]
        self.lon = self._fmt3(lon)
        self.lat = self._fmt3(lat)

    def _station_label(self):
        """Subtitle prefix — includes the station number when there are several."""
        if getattr(self, "_nstations", 1) > 1:
            return f"Station {self._station_idx + 1}/{self._nstations}: "
        return "Station: "

    def _refresh_figure(self):
        """Rebuild the plot (sunburst here; overridden to the Sankey in FlowDiagram)."""
        self._show_sunburst()

    def _goto_station(self, idx):
        """Switch to another station and rebuild the figure."""
        if not (0 <= idx < self._nstations) or idx == self._station_idx:
            return
        self._select_station(idx)
        self._update_station_nav()
        self.sub_label.setText(
            f"{self._station_label()}lon: {self.lon}, lat: {self.lat}"
            f"\n{self._date_range_text()}")
        self._refresh_figure()

    def _prev_station(self):
        self._goto_station(self._station_idx - 1)

    def _next_station(self):
        self._goto_station(self._station_idx + 1)

    def _update_station_nav(self):
        """Enable/disable the Backward/Forward buttons for the current station."""
        prev = getattr(self, "prev_button", None)
        nxt = getattr(self, "next_button", None)
        if prev is not None:
            prev.setEnabled(self._station_idx > 0)
        if nxt is not None:
            nxt.setEnabled(self._station_idx < self._nstations - 1)

    def _fmt_month(self, idx):
        d = self._month_dates[idx]
        return f"{d.month}/{d.year}"

    def _date_range_text(self):
        return (f"from {self._fmt_month(self._start_idx)} "
                f"to {self._fmt_month(self._end_idx)}")

    # ----------------------------------------------------------------------- UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Title = settings-file Title.
        self.header_label = QLabel(self.settings_title or os.path.basename(str(self.csv_path)))
        self.header_label.setAlignment(Qt.AlignCenter)
        self.header_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 15px; font-weight: 600; "
            f"color: {theme.c('text')}; padding: 4px;")
        layout.addWidget(self.header_label)

        # Subtitle: "Station: lon: x, lat: y" (with "k/N" when several stations)
        self.sub_label = QLabel(f"{self._station_label()}lon: {self.lon}, lat: {self.lat}")
        self.sub_label.setAlignment(Qt.AlignCenter)
        self.sub_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 12px; "
            f"color: {theme.c('text_muted')}; padding: 2px 8px;")
        layout.addWidget(self.sub_label)

        # Date-range slider (above the sunburst): two handles select the start/end
        # month; start stays >= csv min and <= end-1, end <= csv max.
        self.range_slider = RangeSlider(0, self._n - 1, self._start_idx, self._end_idx)
        self.range_slider.rangeChanged.connect(self._on_range_changed)
        lbl_style = ("font-family: 'Segoe UI', sans-serif; font-size: 11px; "
                     f"color: {theme.c('text_muted')};")
        self.start_lbl = QLabel(self._fmt_month(self._start_idx))
        self.start_lbl.setStyleSheet(lbl_style)
        self.end_lbl = QLabel(self._fmt_month(self._end_idx))
        self.end_lbl.setStyleSheet(lbl_style)
        slider_row = QHBoxLayout()
        slider_row.setSpacing(8)
        slider_row.addWidget(self.start_lbl)
        slider_row.addWidget(self.range_slider, 1)
        slider_row.addWidget(self.end_lbl)
        layout.addLayout(slider_row)

        # Plot area. Right-click is Qt-native (like the NetCDF map): the page only
        # remembers the wedge under the mouse (_HOVER_JS), _on_web_context_menu asks
        # for it and offers its Timeseries.
        self.web_view = QWebEngineView()
        self.web_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.web_view.customContextMenuRequested.connect(self._on_web_context_menu)
        self._ts_windows = []
        layout.addWidget(self.web_view, 1)

        btn_style = """
            QPushButton {
                font-family: 'Segoe UI', sans-serif; font-size: 12px; font-weight: 500;
                color: white; border: none; border-radius: 6px; padding: 6px 16px;
                min-height: 26px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #5dade2, stop:1 #3498db);
            }
            QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #85c1e9, stop:1 #5dade2); }
            QPushButton:disabled { background: #d3d3d3; color: #a9a9a9; }
        """
        self.save_html_button = QPushButton("Save HTML")
        self.save_html_button.setStyleSheet(btn_style)
        self.save_html_button.setToolTip(
            "Save the plot as a self-contained HTML file (opens in any browser)")
        self.save_html_button.clicked.connect(self._save_html)

        # Station navigation (Backward / Forward) — same styling as the Timeseries
        # window; only shown when the csv holds more than one station.
        self.prev_button = QPushButton("◀ Backward")
        self.prev_button.setStyleSheet(btn_style)
        self.prev_button.setToolTip("Show the previous station")
        self.prev_button.clicked.connect(self._prev_station)
        self.next_button = QPushButton("Forward ▶")
        self.next_button.setStyleSheet(btn_style)
        self.next_button.setToolTip("Show the next station")
        self.next_button.clicked.connect(self._next_station)
        multi = self._nstations > 1
        self.prev_button.setVisible(multi)
        self.next_button.setVisible(multi)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._make_save_csv_button(btn_style))   # lower left
        btn_row.addStretch()
        btn_row.addWidget(self.prev_button)
        btn_row.addWidget(self.next_button)
        btn_row.addStretch()
        btn_row.addWidget(self.save_html_button)
        layout.addLayout(btn_row)
        self._update_station_nav()

    # _save_html / _save_csv are inherited from PlotlyWindowBase.

    def _on_range_changed(self, low, high):
        """Slider moved: update the selected window + labels live, debounce a rebuild."""
        self._start_idx = int(low)
        self._end_idx = int(high)
        self.start_lbl.setText(self._fmt_month(self._start_idx))
        self.end_lbl.setText(self._fmt_month(self._end_idx))
        # Live subtitle feedback (the heavy sunburst rebuild is debounced).
        self.sub_label.setText(
            f"{self._station_label()}lon: {self.lon}, lat: {self.lat}"
            f"\n{self._date_range_text()}")
        self._rebuild_timer.start()

    # ------------------------------------------------- right-click ▸ Timeseries
    def _on_web_context_menu(self, pos):
        """Right-click on the sunburst: ask the page which wedge is under the mouse,
        then show the menu (asynchronous - runJavaScript answers via a callback)."""
        global_pos = self.web_view.mapToGlobal(pos)
        self.web_view.page().runJavaScript(
            "JSON.stringify(window._wcHover || null)", 0,
            lambda res: self._show_sector_menu(res, global_pos))

    def _show_sector_menu(self, result, global_pos):
        import json
        try:
            hit = json.loads(result) if result else None
        except (TypeError, ValueError):
            hit = None
        label = hit.get("label") if isinstance(hit, dict) else None
        sector = None
        if label is not None and hit.get("parent"):      # the root wedge has no parent
            if label in getattr(self, "_sectors", {}):
                sector = label
        self._sector_menu(sector, global_pos)

    def _sector_menu(self, sector, global_pos):
        """The right-click menu (Timeseries / Add to timeseries) for ``sector``, or
        both greyed out when ``sector`` is None. Shared with the Flow Diagram, which
        supplies its own sectors, _sector_name and _sector_series."""
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        act = menu.addAction("Timeseries", lambda: self._open_sector_timeseries(sector))
        if sector is None:
            act.setEnabled(False)
            act.setToolTip("Right-click on a sector (e.g. Rain) to see its timeseries")
        else:
            act.setToolTip(f"Monthly timeseries of '{self._sector_name(sector)}'")
        target = self._ts_windows[-1] if self._ts_windows else None
        add = menu.addAction("Add to timeseries",
                             lambda: self._add_sector_timeseries(sector, target))
        if target is None:
            add.setEnabled(False)
            add.setToolTip("Open a Timeseries of a sector first")
        elif sector is None:
            add.setEnabled(False)
            add.setToolTip("Right-click on a sector (e.g. Rain) to add it")
        elif self._sector_key(sector) in target._wc_keys:
            add.setEnabled(False)
            add.setToolTip(f"'{self._sector_name(sector)}' is already in the timeseries")
        else:
            add.setToolTip(f"Add '{self._sector_name(sector)}' to the last opened "
                           "Timeseries window")
        menu.setToolTipsVisible(True)
        menu.exec(global_pos)

    def _sector_name(self, sector):
        """Legend name of a sector; with several stations it names the station too,
        so the same sector of two stations can be compared."""
        name = "Storage" if sector == "" else sector
        if getattr(self, "_nstations", 1) > 1:
            name += f" (station {self._station_idx + 1})"
        return name

    def _sector_key(self, sector):
        """Identity of a plotted sector: the same wedge of another station is a
        different series."""
        return (self._station_idx, sector)

    def _sector_series(self, sector, discharge_mm=False):
        """(values, unit) - the monthly series behind a sunburst wedge over every
        month of the csv: fluxes in mm per month, storage as the stored water in mm
        at the end of the month, the discharge leaf as the monthly mean m³/s (or,
        with ``discharge_mm``, in mm per month like the fluxes), and Balance =
        inputs - outputs - storage change (mm per month)."""
        df = self._df
        days = self._days_in_month.astype(float)
        to_mm = 1000.0 / self._cellAreaSum if self._cellAreaSum else 0.0
        n = len(df)

        def total(comps, kinds):
            out = np.zeros(n)
            for col, kind in comps:
                if kind not in kinds:
                    continue
                v = df[col].to_numpy(dtype=float)
                # Discharge is a monthly total of daily m³/s -> m³, as in the sunburst.
                out = out + (v * 86400.0 if kind == 'dis' else v)
            return out * to_mm

        spec = self._sectors[sector]
        if spec == 'balance':
            store = total(self._sectors.get("", []), ('store',))
            dstore = np.diff(store, prepend=np.nan)
            values = (total(self._sectors.get('Inputs', []), ('flux', 'dis'))
                      - total(self._sectors.get('Outputs', []), ('flux', 'dis'))
                      - dstore)
            return values, "mm/month"
        kinds = {kind for _col, kind in spec}
        if kinds == {'dis'} and not discharge_mm:
            values = sum(df[col].to_numpy(dtype=float) for col, _k in spec) / days
            return values, "m3/s"
        if kinds == {'store'}:
            return total(spec, ('store',)), "mm"
        return total(spec, ('flux', 'dis')), "mm/month"

    def _open_sector_timeseries(self, sector):
        if sector is None:
            return
        try:
            from src.gui.widgets.analysis_timeseries import TimeseriesWindow
            values, unit = self._sector_series(sector)
            name = self._sector_name(sector)
            stem = os.path.splitext(os.path.basename(str(self.csv_path)))[0]
            preloaded = dict(
                label=f"{stem}_{name}",
                dates=self._month_strings(),
                series=[(name, self._as_list(values))],
                xlocs=[self.lon], ylocs=[self.lat],
                varname=name, unit=unit, long_name=name, main_legend=name,
                settings_title=self.settings_title or "",
            )
            win = TimeseriesWindow(None, parent=self, preloaded=preloaded)
        except Exception as e:
            log.debug("_open_sector_timeseries failed", exc_info=True)
            QMessageBox.warning(self, "Timeseries",
                                f"Could not build the timeseries:\n{type(e).__name__}: {e}")
            return
        # What "Add to timeseries" needs: the sectors shown (no duplicates), and the
        # main sector + its station so a lone m³/s discharge can be redone in mm.
        win._wc_keys = [self._sector_key(sector)]
        win._wc_names = [name]
        win._wc_main = (self._station_idx, sector)
        win.setModal(False)
        win.setAttribute(Qt.WA_DeleteOnClose)
        self._ts_windows.append(win)
        win.finished.connect(lambda _r, w=win: self._ts_windows.remove(w)
                             if w in self._ts_windows else None)
        win.show()
        win.raise_()

    def _month_strings(self):
        return [d.strftime("%d/%m/%Y") for d in self._month_dates]

    @staticmethod
    def _as_list(values):
        return [None if not np.isfinite(v) else float(v) for v in values]

    def _add_sector_timeseries(self, sector, win):
        """Right-click ▸ Add to timeseries: overlay another sector on the last opened
        sector Timeseries window. A sector already shown is refused. Discharge is
        shown in m³/s only while it is alone: added to a window, or a window it
        started gets a second sector, it is converted to mm/month like the rest."""
        if sector is None or win is None or win not in self._ts_windows:
            return
        key = self._sector_key(sector)
        if key in win._wc_keys:
            return
        try:
            name = self._sector_name(sector)
            if win.unit == "m3/s":
                # The window started with discharge alone: redo it in mm/month.
                cur = self._station_idx
                main_station, main_sector = win._wc_main
                try:
                    self._select_station(main_station)
                    main_vals, _u = self._sector_series(main_sector, discharge_mm=True)
                finally:
                    self._select_station(cur)
                main_name = win.series[0][0]
                win.series = [(main_name, self._as_list(main_vals))]
                win.unit = "mm/month"
            values, _unit = self._sector_series(sector, discharge_mm=True)
            win.compare.append({
                "name": name,
                "label": name,
                "x": win._parse_dates(self._month_strings()),
                "series": [(name, self._as_list(values))],
            })
            win._wc_keys.append(key)
            win._wc_names.append(name)
            win.long_name = ", ".join(win._wc_names)
            win._show_current()
        except Exception as e:
            log.debug("_add_sector_timeseries failed", exc_info=True)
            QMessageBox.warning(self, "Add to timeseries",
                                f"Could not add the sector:\n{type(e).__name__}: {e}")
            return
        win.raise_()

    # ------------------------------------------------------ sunburst computation
    def _show_sunburst(self):
        fig = self._build_figure()
        # 3rd title line: the date range covered by the csv (after the Station line).
        if getattr(self, "_date_range_str", ""):
            self.sub_label.setText(
                f"{self._station_label()}lon: {self.lon}, lat: {self.lat}"
                f"\n{self._date_range_str}")
        html = fig.to_html(include_plotlyjs=True, full_html=True,
                           config={"responsive": True}, post_script=_HOVER_JS)
        # Make the plot fill the whole page so it always matches the web view height
        # exactly (no internal scrollbar, no empty band under the sunburst).
        fill = ("<style>html,body{height:100%;margin:0;padding:0;overflow:hidden;}"
                ".plotly-graph-div{height:100vh!important;width:100%!important;}</style>")
        html = html.replace("<head>", "<head>" + fill, 1)
        html = theme.themed_plot_page(html)
        # Rebuilt on every station change and every tick of the month slider, so the
        # page this one replaces is deleted (_load_temp_page) rather than orphaned.
        self._load_temp_page(html, "cwatm_wc_")

    def _build_figure(self):
        """Compute the overall water-balance sunburst (ported from Watercycles1.py).

        Uses the whole time span present in the csv; the basin name / plot title is
        the settings-file Title."""
        convert = 1_000_000_000  # m3 -> km3
        name = self.settings_title or os.path.basename(str(self.csv_path))

        df = self._df
        month_dates = self._month_dates
        cellAreaSum = self._cellAreaSum

        # Selected window (indices into month_dates). Storage change is measured over
        # the same window as the fluxes: baseline_idx = the month before the start
        # (or the first month when the window starts at index 0), so the full-span
        # default reproduces the original result.
        start_idx = self._start_idx
        end_idx = self._end_idx
        baseline_idx = start_idx - 1 if start_idx > 0 else start_idx
        flux_start = baseline_idx + 1 if start_idx > 0 else baseline_idx
        if flux_start > end_idx:
            raise ValueError("Select a window of at least two months.")

        Vars = [
            [['Rain'], 'Rain', ['M'], 'flux', 'Input', 'All'],
            [['Snow'], 'Snow', ['M'], 'flux', 'Input', 'All'],
            [['avgdischarge'], 'River discharge at outlet', ['M3/S'], 'flux', 'Output', 'All'],
            [['act_nonIrrConsumption'], 'non-Irrigation consumption', ['M'], 'flux', 'Output', 'All'],
            [['totalET', 'EvapWaterBodyM', 'EvapoChannel'], 'Evapotranspiration', ['M', 'M', 'M'], 'flux', 'Output', 'All'],
            [['sum_interceptStor'], 'Interception storage', ['M'], 'store', 'Storage', 'All'],
            [['channelStorage'], 'Channel storage', ['M3'], 'store', 'Storage', 'All'],
            [['lakeResStorage'], 'Lake_reservoir_storage', ['M3'], 'store', 'Storage', 'All'],
            [['gridcell_storage'], 'gridcell_water_storage', ['M'], 'store', 'Storage', 'All'],
            [['storGroundwater'], 'GW_storage', ['M'], 'store', 'Storage', 'All'],
            [['sum_soil'], 'Soil_storage', ['M'], 'store', 'Storage', 'All'],
            [['SnowCover'], 'Snow_storage', ['M'], 'store', 'Storage', 'All'],
        ]
        if {'GlacierMelt_sum_m3', 'GlacierRain_sum_m3'}.issubset(df.columns):
            Vars.append([['GlacierMelt', 'GlacierRain'], 'Glacier', ['M3', 'M3'], 'flux', 'Input', 'All'])
        Vars.extend([
            [['sum_actTransTotal'], 'Transpiration', ['M'], 'flux', 'Evapotranspiration', 'All'],
            [['sum_actBareSoilEvap'], 'Bare soil evapo', ['M'], 'flux', 'Evapotranspiration', 'All'],
            [['sum_interceptEvap'], 'Interception evapo', ['M'], 'flux', 'Evapotranspiration', 'All'],
            [['sum_openWaterEvap'], 'Open water evapo', ['M'], 'flux', 'Evapotranspiration', 'All'],
            [['snowEvap'], 'Snow evapo', ['M'], 'flux', 'Evapotranspiration', 'All'],
            [['EvapoChannel'], 'Channel evaporation', ['M'], 'flux', 'Evapotranspiration', 'All'],
            [['EvapWaterBodyM'], 'Water bodies evaporation', ['M'], 'flux', 'Evapotranspiration', 'All'],
            [['actTransTotal_forest'], 'Forest', ['M'], 'flux', 'Transpiration', 'All'],
            [['actTransTotal_grasslands'], 'Others', ['M'], 'flux', 'Transpiration', 'All'],
            [['actTransTotal_paddy'], 'Paddy', ['M'], 'flux', 'Transpiration', 'All'],
            [['actTransTotal_nonpaddy'], 'non-Paddy', ['M'], 'flux', 'Transpiration', 'All'],
        ])

        keys = [i[4] for i in Vars]
        WB = {key: [] for key in keys}
        storeall = 0.0
        discharge = 0.0
        # Right-click ▸ Timeseries: the csv columns behind each wedge, as
        # [(column, kind)] with kind 'flux' / 'store' / 'dis' (see _sector_series).
        sectors = {'Inputs': [], 'Outputs': []}
        store_comps = []

        for var in Vars:
            temp = 0.
            missing = False
            comps = []
            for ii in range(len(var[0])):
                unit = var[2][ii]
                if unit == 'M':
                    suffix = '_areasum_m3'
                elif unit == 'M3':
                    suffix = '_sum_m3'
                else:
                    suffix = None  # M3/S handled below

                if unit == 'M3/S':
                    col = var[0][ii] + '_m3s-1'
                    if col not in df.columns:
                        missing = True
                        break
                    comps.append((col, 'dis'))
                    tmp = df[col].to_numpy()[flux_start:end_idx + 1]
                    discharge = np.mean(tmp)
                    temp = np.sum(tmp * 86400)
                else:
                    col = var[0][ii] + suffix
                    if col not in df.columns:
                        missing = True
                        break
                    comps.append((col, var[3]))
                    if var[3] == 'store':
                        temp = temp +(df[col].to_numpy()[end_idx]
                                       - df[col].to_numpy()[baseline_idx])
                    else:
                        temp1 = df[col].to_numpy()[flux_start:end_idx + 1]
                        temp = temp + np.sum(temp1)
            if missing:
                continue

            if var[3] == 'store':
                storeall = storeall + temp
                store_comps.extend(comps)
            else:
                WB[var[4]].append([var[1], temp, var[3]])
                # A wedge that is also a parent ('Evapotranspiration', 'Transpiration')
                # keeps its own columns, exactly like its value in the sunburst.
                sectors[var[1]] = comps
                if var[4] in ('Input', 'Output'):
                    sectors[var[4] + 's'].extend(comps)

        WB['Storage'].append(["", storeall, "Storage"])

        # ---- sunburst assembly (Watercycles1.py) ----
        VARS = [[WB['Input'], 'Inputs'],
                [WB['Output'], 'Outputs'],
                [WB['Storage'], 'Storage'],
                [WB['Evapotranspiration'], 'Evapotranspiration'],
                [WB['Transpiration'], 'Transpiration']]

        labels_out, parents_out, values = [], [], []
        Total_input, Total_output, Total_store = [], [], []
        for VAR in VARS:
            for Var in VAR[0]:
                Y = abs(Var[1])
                if VAR[1] == 'Storage':
                    Total_store.append(Y)
                if VAR[1] == 'Inputs':
                    Total_input.append(Y)
                if VAR[1] == 'Outputs':
                    Total_output.append(Y)
                values.append(Y)
                labels_out.append(Var[0])
                parents_out.append(VAR[1])

        total_input = np.sum(Total_input)
        total_output = np.sum(Total_output)
        total_store = np.sum(Total_store)

        discharge_label = 'River discharge at outlet'
        balance = 0.
        if storeall < 0:
            missq = (total_input + total_store) - total_output
            if discharge_label in labels_out:
                values[labels_out.index(discharge_label)] += missq
            total_output += missq
            storetext = "Storage (out)"
        else:
            balance = total_input - (total_output + total_store)
            storetext = "Storage (into)"
        sectors[storetext] = store_comps
        sectors[""] = store_comps          # the storage leaf has no label
        sectors['Balance'] = 'balance'
        self._sectors = sectors

        total_total = total_input + total_output + total_store + abs(balance)
        values_out = [total_total, total_input, total_output, abs(balance), total_store] + values

        noyears = (end_idx - flux_start + 1) / 12.0
        # The sunburst centre (root wedge) shows the station lon/lat instead of the
        # generic "Water balance" text. Monospace so the "lon:"/"lat:" prefixes are the
        # same width and both values start at the same left distance.
        center_label = ("<span style='font-family:Consolas,monospace'>"
                        f"lon: {self.lon}<br>lat: {self.lat}</span>")
        labels_1st = [center_label, 'Inputs', 'Outputs', 'Balance', storetext]
        parents_1st = ['', center_label, center_label, center_label, center_label]

        labels = labels_1st + labels_out
        parents = parents_1st + parents_out

        # The root wedge and 'Balance' use the theme's panel colour (white in
        # Normal, matching the old hardcoded 'white') so the sunburst's centre
        # follows Dark Mode / Mikhail instead of always punching a white hole
        # through a dark chart.
        hub_color = theme.c('panel_bg')
        label_color = {
            'Water balance': hub_color, 'Inputs': '#b0c4de', 'Outputs': '#d2691e', 'Balance': hub_color,
            'Rain': '#60C4DE', 'Snow': '#8fd1d1', 'Glacier': '#ADD8E6',
            'River discharge at outlet': '#d2691e', 'non-Irrigation consumption': '#d2691e',
            'Evapotranspiration': '#669C53', 'Transpiration': '#669C53',
            'Bare soil evapo': '#699C4F', 'Interception evapo': '#265312',
            'Open water evapo': '#60C4DE', 'Snow evapo': '#8fd1d1', 'Channel evaporation': '#60C4DE',
            'Forest': '#265312', 'Others': '#81c066', 'Paddy': '#B66934', 'non-Paddy': '#B66934',
        }
        colors = [
            hub_color if par == ''          # root wedge (station lon/lat)
            else '#00CC96' if lab == storetext
            else label_color.get(lab, '#b0c4de' if par == 'Inputs' else '#d2691e')
            for lab, par in zip(labels, parents)]

        inputs_idx = {i for i, p in enumerate(parents) if p == 'Inputs'} | {labels.index('Inputs')}
        outputs_idx = ({i for i, p in enumerate(parents)
                        if p in ('Outputs', 'Evapotranspiration', 'Transpiration')}
                       | {labels.index('Outputs')})
        discharge_idx = labels.index(discharge_label) if discharge_label in labels else -1

        volume, fraction, otherunit = [], [], []
        csv_rows = []
        for part, v in enumerate(values_out):
            if part == 0:
                fra1 = 1.
            elif part in inputs_idx:
                fra1 = v / values_out[1] if values_out[1] else 0.
            elif part in outputs_idx:
                fra1 = v / values_out[2] if values_out[2] else 0.
            else:
                fra1 = v / (values_out[0] / 2) if values_out[0] else 0.

            prec = 1
            if fra1 < 0.1:
                prec = 2
            if fra1 < 0.01:
                prec = 3
            if fra1 < 0.001:
                prec = 4
            prec1 = 2
            fraction.append("Percent: {:.{prec}%}".format(fra1, prec=prec))
            volume.append("Volume: {:.{prec1}} km<sup>3</sup>".format(v / convert, prec1=prec1))

            mmyear = v / cellAreaSum * 1000 / noyears if cellAreaSum else 0.
            if part == discharge_idx:
                otherunit.append("Discharge: {:.2f} m<sup>3</sup>s".format(discharge))
            else:
                otherunit.append("mm/year: {:.0f} mm".format(mmyear))
            # Save CSV: the same numbers, unformatted (the root wedge's label is the
            # lon/lat HTML - named plainly here)
            csv_rows.append([
                parents[part] if part else "",
                labels[part] if part else "Water balance",
                round(v / convert, 6),
                round(mmyear, 3),
                round(fra1 * 100, 3),
                round(float(discharge), 3) if part == discharge_idx else ""])

        fraction = np.array(fraction)
        fraction[0] = " "
        volume = np.array(volume)
        otherunit = np.array(otherunit)

        date_range_str = self._date_range_text()
        self._date_range_str = date_range_str
        area_km2 = cellAreaSum / 1_000_000
        addinfo = np.full(len(values_out), '', dtype='<U100')
        addinfo[0] = (f"Basin: {name}<br>Area: {area_km2:.0f} km<sup>2</sup><br>"
                      + date_range_str)

        self._csv_data = (
            [("Basin", name), ("lon", self.lon), ("lat", self.lat),
             ("Period", date_range_str), ("Area_km2", round(area_km2, 3))],
            ["Group", "Component", "Volume_km3", "mm_per_year", "Percent",
             "Discharge_m3s"],
            csv_rows)

        customdata = np.stack([fraction, otherunit, volume, addinfo], axis=-1)

        hovertemplate = [
            "<b>%{label}</b><br>%{customdata[3]} <extra></extra>" if p == ''
            else ("<b>%{label}</b><br>%{customdata[2]}<br>%{customdata[1]}<br>"
                  "%{customdata[0]}<extra><b>%{parent}</b><br>"
                  "Percent: %{percentParent:.1%} </extra>")
            for p in parents
        ]

        sunburst_kwargs = dict(
            customdata=customdata,
            labels=labels,
            parents=parents,
            values=values_out,
            branchvalues='total',
            marker=dict(colors=colors),
            maxdepth=4,
            hovertemplate=hovertemplate,
        )
        if theme.is_dark():
            # Leave the wedge fill colours as-is (they're deliberately fixed,
            # theme-independent data colours - darkening them to chase text
            # contrast made the palette muddy and less distinct in testing).
            # Plotly instead auto-picks each wedge's inside-text as black or
            # white from that wedge's own fill brightness, which for the
            # lighter fills (Inputs, Rain, Snow, ...) picks black - fine on
            # Normal's white background, illegible-looking against a black
            # chart. Override it to the theme's text colour everywhere instead.
            sunburst_kwargs['insidetextfont'] = dict(color=theme.c('text'))
        fig = go.Figure(go.Sunburst(**sunburst_kwargs))
        fig.update_layout(
            template=theme.plotly_template(),
            autosize=True,  # fill the web view (no fixed height -> no scrollbar)
            hoverlabel=dict(align='left'),
            margin=dict(l=10, r=10, t=10, b=10),
        )
        _ov = theme.plotly_layout_overrides()
        if _ov:
            fig.update_layout(**_ov)
        return fig
