"""
Flow-diagram analysis widget for the CWatM GUI.

Opens a CWatM ``WaterCycle_areasum_monthtot.csv`` result file (the same file the
Watercycle sunburst uses) and shows the overall water balance as a Plotly
**Sankey** flow diagram inside a window. The header (settings-file Title +
station lon/lat) and the two-handle month **range slider** are identical to the
Watercycle window (reused from ``analysis_watercycle.py``); only the figure
differs -- a Sankey instead of a sunburst.

The Sankey computation (nodes / links / colour helpers / ``build_sankey``) is
ported from the stand-alone ``sankey_waterbalance_month.py`` template. All link
values are long-term averages in mm/yr over the basin area, computed over the
slider-selected month window.
"""

import os
import re
import sys
import json
import tempfile
import colorsys
from calendar import monthrange
from collections import Counter, defaultdict

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtGui import QIcon

from src.gui.utils.window_geometry import GeometryMemoryMixin
from src.gui.utils import theme
from src.gui.widgets.analysis_timeseries import resolved_pathout_dir

# Optional dependencies: Plotly for the figure, QtWebEngine to render it, pandas/numpy.
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    import plotly.graph_objects as go
    import plotly.colors as pc
    import numpy as np
    import pandas as pd
    # RangeSlider + the csv parsing helpers are reused from the Watercycle widget.
    from src.gui.widgets.analysis_watercycle import RangeSlider, WatercycleWindow
    _FD_AVAILABLE = True
    _FD_IMPORT_ERROR = ""
except Exception as _fd_err:  # pragma: no cover - import guard
    _FD_AVAILABLE = False
    _FD_IMPORT_ERROR = f"{type(_fd_err).__name__}: {_fd_err}"
    print(f"Flow-diagram analysis unavailable: {_FD_IMPORT_ERROR}", file=sys.stderr)


def open_flowdiagram(parent=None):
    """Prompt for a WaterCycle result .csv file and open the Sankey window."""
    if not _FD_AVAILABLE:
        QMessageBox.warning(
            parent, "Flow Diagram",
            "Plotly / QtWebEngine / pandas are not available.\n\n" + _FD_IMPORT_ERROR
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
        win = FlowDiagramWindow(path, parent)
        win.exec()
    except Exception as e:
        import traceback
        traceback.print_exc()
        QMessageBox.warning(parent, "Flow Diagram", f"Could not open the file:\n{e}")


# ---------------------------------------------------------------------------
# Sankey colour helpers + builder (ported from sankey_waterbalance_month.py)
# ---------------------------------------------------------------------------

HUE_DELTA = 0.033   # ~12 deg hue spread between links sharing a source->target pair


def _css_to_rgb01(hex_color):
    r, g, b = pc.hex_to_rgb(hex_color)
    return r / 255, g / 255, b / 255


def _to_hex(r, g, b):
    return "#{:02x}{:02x}{:02x}".format(int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5))


def _to_rgba(r, g, b, a=0.65):
    return f"rgba({int(r * 255)},{int(g * 255)},{int(b * 255)},{a})"


def _adjust_color(hex_color, delta_h=0.0, delta_l=0.0):
    """Shift hue and/or lightness in HLS space (both deltas in 0..1 units)."""
    r, g, b = pc.hex_to_rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    h = (h + delta_h) % 1.0
    l = max(0.0, min(1.0, l + delta_l))
    r2, g2, b2 = colorsys.hls_to_rgb(h, l, s)
    return _to_hex(r2, g2, b2)


# SVG linearGradient injection: Plotly cannot draw per-link source->target gradients,
# so each path.sankey-link gets one via JS in the exported HTML. Fill must be set via
# path.style.fill (Plotly's inline style overrides attribute fill).
_GRADIENT_JS = """
<script>
(function() {
  var GRAD = %GRAD%;
  function applyGradients(gd) {
    var svg = gd.querySelector('svg.main-svg');
    if (!svg) return;
    var defs = svg.querySelector('defs');
    if (!defs) {
      defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
      svg.insertBefore(defs, svg.firstChild);
    }
    var paths = Array.from(gd.querySelectorAll('path.sankey-link'));
    paths.forEach(function(path, i) {
      if (i >= GRAD.length) return;
      var id = 'sk-grad-' + i;
      var old = defs.querySelector('#' + id);
      if (old) defs.removeChild(old);
      var grad = document.createElementNS('http://www.w3.org/2000/svg', 'linearGradient');
      grad.setAttribute('id', id);
      grad.setAttribute('gradientUnits', 'objectBoundingBox');
      grad.setAttribute('x1', '0'); grad.setAttribute('y1', '0.5');
      grad.setAttribute('x2', '1'); grad.setAttribute('y2', '0.5');
      [[0, GRAD[i][0]], [1, GRAD[i][1]]].forEach(function(d) {
        var stop = document.createElementNS('http://www.w3.org/2000/svg', 'stop');
        stop.setAttribute('offset', d[0]);
        stop.setAttribute('stop-color', d[1]);
        stop.setAttribute('stop-opacity', '0.65');
        grad.appendChild(stop);
      });
      defs.appendChild(grad);
      path.style.fill = 'url(#' + id + ')';
      path.style.fillOpacity = '1';
    });
  }
  function hookAll() {
    document.querySelectorAll('.js-plotly-plot').forEach(function(gd) {
      applyGradients(gd);
      gd.on('plotly_afterplot', function() { applyGradients(gd); });
    });
  }
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', function() { setTimeout(hookAll, 400); });
  else
    setTimeout(hookAll, 400);
})();
</script>
"""


def build_sankey(nodes, links, valueformat=".1f", lightness_override=None):
    """Build the Sankey figure and the per-link gradient stop pairs.

    Returns ``(fig, grad_pairs)`` -- ``grad_pairs`` is injected as SVG gradients
    into the exported HTML by ``_GRADIENT_JS``. No plot title: the window already
    shows it in the header label above the plot."""
    lightness_override = lightness_override or {}

    node_names  = [n["name"]  for n in nodes]
    node_colors = [n["color"] for n in nodes]
    node_index  = {n["name"]: i for i, n in enumerate(nodes)}
    node_x      = {n["name"]: n["x"] for n in nodes}

    names    = [l[0] for l in links]
    sources  = [l[1] for l in links]
    targets  = [l[2] for l in links]
    values   = [l[3] for l in links]
    override = [l[4] if len(l) > 4 else None for l in links]

    # node totals: incoming sum; outgoing sum for pure sources
    incoming = {n: 0.0 for n in node_names}
    outgoing = {n: 0.0 for n in node_names}
    for s, t, v in zip(sources, targets, values):
        outgoing[s] += v
        incoming[t] += v
    node_total = {n: incoming[n] if incoming[n] > 0 else outgoing[n] for n in node_names}

    node_labels    = [f"{n}<br>{node_total[n]:.0f}" for n in node_names]
    node_hovertext = [f"{n}: {node_total[n]:.0f} mm" for n in node_names]

    # per-link gradient stops from node colors; duplicates of a pair get spread hues
    pair_counts = Counter((s, t) for s, t, ov in zip(sources, targets, override) if ov is None)
    pair_seen   = defaultdict(int)
    link_src_hex, link_tgt_hex = [], []
    for name, s, t, ov in zip(names, sources, targets, override):
        if ov is not None:
            link_src_hex.append(ov)
            link_tgt_hex.append(_adjust_color(ov, delta_l=-0.06))
            continue
        n_pair = pair_counts[(s, t)]
        idx = pair_seen[(s, t)]
        pair_seen[(s, t)] += 1
        dh = (idx - (n_pair - 1) / 2) * HUE_DELTA if n_pair > 1 else 0.0
        dl = lightness_override.get(name, 0.0)
        link_src_hex.append(_adjust_color(node_colors[node_index[s]], delta_h=dh, delta_l=dl))
        link_tgt_hex.append(_adjust_color(node_colors[node_index[t]], delta_h=dh, delta_l=dl))

    # solid blended fallback (shown before the JS fires) + gradient stop pairs
    link_solid, grad_pairs = [], []
    for i, (s, t) in enumerate(zip(sources, targets)):
        sr, sg, sb = _css_to_rgb01(link_src_hex[i])
        tr, tg, tb = _css_to_rgb01(link_tgt_hex[i])
        link_solid.append(_to_rgba((sr + tr) / 2, (sg + tg) / 2, (sb + tb) / 2, 0.5))
        if node_x[s] > node_x[t]:   # backward link: swap stops so gradient reads source->target
            grad_pairs.append([link_tgt_hex[i], link_src_hex[i]])
        else:
            grad_pairs.append([link_src_hex[i], link_tgt_hex[i]])

    fig = go.Figure(go.Sankey(
        orientation="h",
        arrangement="fixed",
        valueformat=valueformat,
        valuesuffix=" mm",
        textfont=dict(family="Helvetica, Arial, sans-serif", size=9, color=theme.c('text')),
        node=dict(
            label=node_labels,
            color=node_colors,
            x=[n["x"] for n in nodes],
            y=[n["y"] for n in nodes],
            pad=13,
            thickness=12,
            line=dict(color="rgba(80,80,80,0.4)", width=0.6),
            customdata=node_hovertext,
            hovertemplate="%{customdata}<extra></extra>",
        ),
        link=dict(
            source=[node_index[s] for s in sources],
            target=[node_index[t] for t in targets],
            value=values,
            label=names,
            color=link_solid,
            line=dict(width=0),
            customdata=[[s, t] for s, t in zip(sources, targets)],
            hovertemplate=("%{label}: %{value:" + valueformat + "} mm"
                           "<br>%{customdata[0]} → %{customdata[1]}<extra></extra>"),
        ),
    ))

    fig.update_layout(
        template=theme.plotly_template(),
        font=dict(family="Helvetica, Arial, sans-serif", size=9),
        autosize=True,
        margin=dict(l=8, r=8, t=28, b=8),
        hoverlabel=dict(align="left"),
    )
    _ov = theme.plotly_layout_overrides()
    if _ov:
        fig.update_layout(**_ov)
    return fig, grad_pairs


def _build_balance_links(b):
    """Nodes + links for the water-balance Sankey (cells 05-07 of the template).

    ``b`` maps variable name -> long-term average mm/yr (missing keys read as 0)."""
    nodes = [
        {"name": "Precipitation",      "color": "#87CEEB", "x": 0.01, "y": 0.28},
        {"name": "Rain",               "color": "#6AAFE0", "x": 0.17, "y": 0.30},
        {"name": "Glacier",            "color": "#c4eded", "x": 0.01, "y": 0.70},
        {"name": "Interception",       "color": "#98D898", "x": 0.30, "y": 0.35},
        {"name": "Snow",               "color": "#A8E8E8", "x": 0.20, "y": 0.60},
        {"name": "Soil",               "color": "#C8A478", "x": 0.40, "y": 0.38},
        {"name": "Evapotranspiration", "color": "#52B788", "x": 0.90, "y": 0.14},
        {"name": "Groundwater",        "color": "#7B9EB8", "x": 0.60, "y": 0.50},
        {"name": "Runoff",             "color": "#4A86C8", "x": 0.75, "y": 0.75},
        {"name": "Waterbodies",        "color": "#4A86C8", "x": 0.81, "y": 0.75},
        {"name": "Discharge",          "color": "#1E5A9C", "x": 0.90, "y": 0.80},
        {"name": "Withdrawal",         "color": "#E05252", "x": 0.73, "y": 0.40},
        {"name": "Consumption",        "color": "#B83232", "x": 0.90, "y": 0.40},
        {"name": "Other Source",       "color": "#8B6347", "x": 0.65, "y": 0.40},
    ]

    # derived quantities (cell 06) -- guard the division so an empty basin is safe
    rain = b["Rain_areasum_m3"] - b["sum_interceptEvap_areasum_m3"] - b["sum_openWaterEvap_areasum_m3"]
    snow = b["Snow_areasum_m3"] - b["snowEvap_areasum_m3"]
    rain_qu = rain / (rain + snow) if (rain + snow) else 0.0

    b["sum_runoff_areasum_m3"] = b["runoff_areasum_m3"] - b["baseflow_areasum_m3"]
    b["rain_runoff"] = rain_qu * b["sum_runoff_areasum_m3"]
    b["rain_soil"]   = rain - b["rain_runoff"]
    b["snow_runoff"] = (1 - rain_qu) * b["sum_runoff_areasum_m3"]
    b["snow_soil"]   = snow - b["snow_runoff"]

    # glacier variables are optional -- absent from some watercycle CSVs (default 0).
    # When there is no glacier the node/link is dropped entirely so "Glacier" is not
    # drawn as a (zero) label; only add the tiny epsilon when it is actually shown.
    glacier_val = b.get("GlacierMelt_sum_m3", 0.0) + b.get("GlacierRain_sum_m3", 0.0)
    show_glacier = glacier_val > 0
    b["glacier"] = glacier_val + (0.001 if show_glacier else 0.0)
    b["addtoevapotrans_areasum_m3"] = 0.0001
    b["runoff"] = b["snow_runoff"] + b["rain_runoff"] + b["baseflow_areasum_m3"] + b["glacier"]

    links = [
        ["Rain",               "Precipitation", "Rain",               b["Rain_areasum_m3"]],
        ["Rain on soil",       "Rain",          "Soil",               b["rain_soil"]],
        ["Evap. Interception", "Rain",          "Interception",       b["sum_interceptEvap_areasum_m3"]],
        ["Evap. Open water",   "Rain",          "Evapotranspiration", b["sum_openWaterEvap_areasum_m3"]],
        ["Evap. Interception", "Interception",  "Evapotranspiration", b["sum_interceptEvap_areasum_m3"]],
        ["Snow",               "Precipitation", "Snow",               b["Snow_areasum_m3"]],
        ["Evap. Snow",         "Snow",          "Evapotranspiration", b["snowEvap_areasum_m3"]],
        ["Snow on soil",       "Snow",          "Soil",               b["snow_soil"]],
        ["Glacier Input",      "Glacier",       "Runoff",             b["glacier"]],
        ["Transp. Forest",     "Soil",          "Evapotranspiration", b["actTransTotal_forest_areasum_m3"]],
        ["Transp. Other",      "Soil",          "Evapotranspiration", b["actTransTotal_grasslands_areasum_m3"]],
        ["Transp. Paddy",      "Soil",          "Evapotranspiration", b["actTransTotal_paddy_areasum_m3"]],
        ["Transp. Irrigation", "Soil",          "Evapotranspiration", b["actTransTotal_nonpaddy_areasum_m3"]],
        ["Evap. bare soil",    "Soil",          "Evapotranspiration", b["sum_actBareSoilEvap_areasum_m3"]],
        ["Percolation GW",     "Soil",          "Groundwater",        b["perc3toGW_GW_areasum_m3"]],
        ["Pref. flow",         "Soil",          "Groundwater",        b["sum_gwRecharge_areasum_m3"] - b["perc3toGW_GW_areasum_m3"]],
        ["Capilar Rise",       "Groundwater",   "Soil",               b["sum_capRiseFromGW_areasum_m3"]],
        ["Baseflow",           "Groundwater",   "Runoff",             b["baseflow_areasum_m3"]],
        ["Surface Rain",       "Rain",          "Runoff",             b["rain_runoff"]],
        ["Surface Snow",       "Snow",          "Runoff",             b["snow_runoff"]],
        ["Discharge",          "Runoff",        "Waterbodies",        b["runoff"]],
        ["Evapo Waterbody",    "Waterbodies",   "Evapotranspiration", b["EvapWaterBodyM_areasum_m3"]],
        ["Discharge",          "Waterbodies",   "Discharge",          b["runoff"] - b["EvapWaterBodyM_areasum_m3"] - b["act_SurfaceWaterAbstract_areasum_m3"]],
        ["Withdrawal Surface", "Waterbodies",   "Withdrawal",         b["act_SurfaceWaterAbstract_areasum_m3"]],
        ["Withdrawal GW",      "Groundwater",   "Withdrawal",         b["nonFossilGroundwaterAbs_areasum_m3"]],
        ["Withdrawal Fossil GW", "Other Source", "Withdrawal",        b["pot_GroundwaterAbstract_areasum_m3"] - b["nonFossilGroundwaterAbs_areasum_m3"] - b["unmet_lost_areasum_m3"]],
        ["Return flow",        "Withdrawal",    "Discharge",          b["returnFlow_areasum_m3"] - b["unmet_lost_areasum_m3"]],
        ["Evap. Withdrawal",   "Withdrawal",    "Evapotranspiration", b["addtoevapotrans_areasum_m3"]],
        ["Consumption",        "Withdrawal",    "Consumption",        b["act_nonIrrConsumption_areasum_m3"] + b["act_totalIrrConsumption_areasum_m3"]],
    ]
    if not show_glacier:
        nodes = [n for n in nodes if n["name"] != "Glacier"]
        links = [l for l in links if l[0] != "Glacier Input"]
    return nodes, links


class FlowDiagramWindow(GeometryMemoryMixin, QDialog):
    """Window showing the overall water balance of a WaterCycle csv as a Sankey.

    Reuses the Watercycle window's csv parsing (station coords, settings Title,
    monthly-totals loading) and its two-handle month range slider; only the
    figure differs."""

    # Reuse the Watercycle csv-parsing helpers verbatim (identical csv layout).
    # (Accessing a @staticmethod on the class already yields the plain function.)
    _fmt3 = staticmethod(WatercycleWindow._fmt3)
    _read_station = staticmethod(WatercycleWindow._read_station)
    _title_from_settings_content = WatercycleWindow._title_from_settings_content
    _read_settings_title = WatercycleWindow._read_settings_title
    _load_data = WatercycleWindow._load_data
    _fmt_month = WatercycleWindow._fmt_month
    _date_range_text = WatercycleWindow._date_range_text
    # Multi-station support (identical csv layout) — reused verbatim; _refresh_figure
    # is overridden below so navigation rebuilds the Sankey instead of the sunburst.
    _select_station = WatercycleWindow._select_station
    _station_label = WatercycleWindow._station_label
    _goto_station = WatercycleWindow._goto_station
    _prev_station = WatercycleWindow._prev_station
    _next_station = WatercycleWindow._next_station
    _update_station_nav = WatercycleWindow._update_station_nav

    def __init__(self, csv_path, parent=None):
        super().__init__(parent)
        self.csv_path = csv_path
        self.settings_title = self._read_settings_title(csv_path)

        # Read the monthly data once; the Sankey is recomputed for the selected
        # [start, end] month window (defaults to the full span). Multiple stations
        # are parsed and the first selected (sets self.lon/self.lat/self._df).
        self._load_data(csv_path)

        title = self.settings_title or os.path.basename(str(csv_path))
        self.setWindowTitle(f"\U0001F30A Flow Diagram: {title}")
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)

        # Key bumped ("...2") so a geometry saved by the earlier, larger default is
        # ignored and the new compact default below takes effect.
        self._geometry_was_restored = self._init_geometry_memory("flowdiagram2")
        if not self._geometry_was_restored:
            self.resize(780, 500)
        try:
            icon_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                'assets', 'cwatm.ico')
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass

        self._temp_html = None
        # Debounce heavy figure rebuilds while dragging the range slider.
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(200)
        self._rebuild_timer.timeout.connect(self._show_sankey)
        self._build_ui()
        self._show_sankey()

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

        # Date-range slider (above the diagram): two handles select the start/end month.
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

        # Plot area
        self.web_view = QWebEngineView()
        layout.addWidget(self.web_view, 1)

        # Save HTML button (same style/behaviour as the Watercycle window)
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
        btn_row.addStretch()
        btn_row.addWidget(self.prev_button)
        btn_row.addWidget(self.next_button)
        btn_row.addStretch()
        btn_row.addWidget(self.save_html_button)
        layout.addLayout(btn_row)
        self._update_station_nav()

    def _refresh_figure(self):
        """Station navigation rebuilds the Sankey (not the Watercycle sunburst)."""
        self._show_sankey()

    def _save_html(self):
        """Save the currently rendered plot HTML to a user-chosen file."""
        if not self._temp_html or not os.path.exists(self._temp_html):
            QMessageBox.information(self, "Save HTML", "Nothing to save yet.")
            return
        base = os.path.splitext(os.path.basename(str(self.csv_path)))[0] or "flowdiagram"
        base = re.sub(r'[^\w\-.]+', '_', base).strip('_') + "_sankey"
        default = os.path.join(resolved_pathout_dir(self), base + ".html")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save plot as HTML", default, "HTML files (*.html)")
        if not path:
            return
        try:
            import shutil
            shutil.copyfile(self._temp_html, path)
        except Exception as e:
            QMessageBox.warning(self, "Save HTML", f"Could not save the file:\n{e}")

    def _on_range_changed(self, low, high):
        """Slider moved: update the selected window + labels live, debounce a rebuild."""
        self._start_idx = int(low)
        self._end_idx = int(high)
        self.start_lbl.setText(self._fmt_month(self._start_idx))
        self.end_lbl.setText(self._fmt_month(self._end_idx))
        self.sub_label.setText(
            f"{self._station_label()}lon: {self.lon}, lat: {self.lat}"
            f"\n{self._date_range_text()}")
        self._rebuild_timer.start()

    # -------------------------------------------------------- Sankey computation
    def _show_sankey(self):
        fig, grad_pairs = self._build_figure()
        self.sub_label.setText(
            f"{self._station_label()}lon: {self.lon}, lat: {self.lat}"
            f"\n{self._date_range_text()}")
        html = fig.to_html(include_plotlyjs=True, full_html=True,
                           config={"responsive": True})
        # Fill the whole page so the plot always matches the web view height.
        fill = ("<style>html,body{height:100%;margin:0;padding:0;overflow:hidden;}"
                ".plotly-graph-div{height:100vh!important;width:100%!important;}</style>")
        html = html.replace("<head>", "<head>" + fill, 1)
        # Inject the per-link SVG gradients (source-node -> target-node colour).
        grad_js = _GRADIENT_JS.replace("%GRAD%", json.dumps(grad_pairs))
        html = html.replace("</body>", grad_js + "</body>", 1)
        html = theme.themed_plot_page(html)
        tmp = tempfile.NamedTemporaryFile(
            prefix="cwatm_fd_", suffix=".html", delete=False, mode="w", encoding="utf-8")
        tmp.write(html)
        tmp.close()
        self._temp_html = tmp.name
        self.web_view.load(QUrl.fromLocalFile(tmp.name))

    def _build_figure(self):
        """Compute the water-balance Sankey over the selected month window.

        Link values are long-term averages in mm/yr over the basin area (ported
        from ``sankey_waterbalance_month.py``, cells 03-08)."""
        df = self._df
        cell_area = self._cellAreaSum   # already divided by days_in_month[0]

        start_idx = self._start_idx
        end_idx = self._end_idx
        nyears = (end_idx - start_idx + 1) / 12.0
        if nyears <= 0:
            raise ValueError("Select a window of at least one year.")

        # `bal`: variable name -> long-term average mm/yr over the window.
        # Missing columns read as 0 so an incomplete watercycle csv still renders.
        bal = defaultdict(float)
        for col in df.columns[1:]:
            series = pd.to_numeric(df[col], errors="coerce")
            bal[col] = series.iloc[start_idx:end_idx + 1].sum() / cell_area * 1000 / nyears
        # discharge comes as m3/s -- convert to the same mm/yr basis
        bal["discharge_m3s-1"] *= 86400.0
        bal["avgdischarge_m3s-1"] *= 86400.0

        nodes, links = _build_balance_links(bal)
        return build_sankey(
            nodes, links,
            valueformat=".1f",
            lightness_override={"Percolation GW": -0.10},
        )
