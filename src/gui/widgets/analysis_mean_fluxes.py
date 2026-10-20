"""
Mean-weekly-fluxes analysis widget for the CWatM GUI (Analyse ▸ Mean Weekly Fluxes) - a TEST.

The mean seasonal cycle of the main fluxes of a **daily** WaterCycle csv: for every
week of the year the mean over all years of the slider window, in mm/week over the
basin, one filled panel per flux (Precipitation, Rain, Snow, Snowmelt, Glacier melt,
Actual ET, Discharge) with a shared Jan-Dec axis. Header, station navigation, month
range slider, Save HTML / Save CSV are inherited from ``FlowDiagramWindow``.

To remove it again: delete this file and the "Mean Weekly Fluxes" block (+ its entry in
``_beginner_hidden_actions``) in ``src/gui/components/menu_builder.py``.
"""

import os
import sys

from PySide6.QtWidgets import QFileDialog, QMessageBox
from PySide6.QtCore import Qt

from src.gui.utils import theme
from src.gui.utils.window_geometry import scaled_default_size
from src.gui.utils.gui_log import get_logger

log = get_logger("analysis_mean_fluxes")

try:
    import numpy as np
    import pandas as pd
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    from src.gui.widgets.analysis_flowdiagram import FlowDiagramWindow, _FD_AVAILABLE, _FD_IMPORT_ERROR
except Exception as _mf_err:  # pragma: no cover - import guard
    _FD_AVAILABLE = False
    _FD_IMPORT_ERROR = f"{type(_mf_err).__name__}: {_mf_err}"
    print(f"Mean Weekly Fluxes analysis unavailable: {_FD_IMPORT_ERROR}", file=sys.stderr)
    FlowDiagramWindow = object

# (panel name, csv columns summed, colour). Discharge is m3/s - see _daily_mm.
FLUXES = [
    ("Precipitation", ["precipitation_sn_areasum_m3"], "#5a7d9a"),
    ("Rain",          ["Rain_areasum_m3"], "#8ecae6"),
    ("Snow",          ["Snow_areasum_m3"], "#b3c6e8"),
    ("Snowmelt",      ["SnowMelt_areasum_m3", "IceMelt_areasum_m3"], "#2c7fb8"),
    ("Glacier melt",  ["GlacierMelt_sum_m3", "GlacierRain_sum_m3"], "#253494"),
    ("Actual ET",     ["totalET_areasum_m3"], "#d4c26a"),
    # irrigation withdrawal from all sources (lakes, channels, groundwater, reservoirs)
    ("Irrigation demand", ["Lake_Irrigation_areasum_m3", "Channel_Irrigation_areasum_m3",
                           "GW_Irrigation_areasum_m3", "Res_Irrigation_areasum_m3"], "#8b1e4f"),
    ("Discharge",     ["avgdischarge_m3s-1"], "#aa4499"),
]
WEEKS = 52          # day 365 / 366 count to the last week
VSPACE = 0.05       # vertical gap between two panels (paper units)

# Click a legend entry: its whole panel (axes + title) goes and the other panels
# share the height; click it again to bring it back. Trace i = panel i = subplot
# title annotation i; the last annotation is the "mm/week" axis label.
_PANEL_JS = """<script>
(function () {
  var GAP = %GAP%;
  function setup(gd) {
    var n = gd.data.length, hidden = gd.data.map(function () { return false; });
    function ax(kind, i) { return kind + (i === 0 ? '' : String(i + 1)); }
    function layout() {
      var vis = [], upd = {};
      for (var i = 0; i < n; i++) if (!hidden[i]) vis.push(i);
      var k = vis.length, h = k ? (1 - (k - 1) * GAP) / k : 1;
      for (var i = 0; i < n; i++) {
        var p = vis.indexOf(i), on = p >= 0;
        upd[ax('yaxis', i) + '.visible'] = on;
        upd[ax('xaxis', i) + '.visible'] = on;
        upd['annotations[' + i + '].visible'] = on;
        if (!on) continue;
        var top = 1 - p * (h + GAP);
        upd[ax('yaxis', i) + '.domain'] = [top - h, top];
        upd['annotations[' + i + '].y'] = top;
        // the month names under the lowest panel shown
        upd[ax('xaxis', i) + '.showticklabels'] = p === k - 1;
      }
      Plotly.relayout(gd, upd);
    }
    gd.on('plotly_legendclick', function (ev) {
      var i = ev.curveNumber;
      hidden[i] = !hidden[i];
      Plotly.restyle(gd, {visible: hidden[i] ? 'legendonly' : true}, [i]);
      layout();
      return false;
    });
    gd.on('plotly_legenddoubleclick', function () { return false; });
  }
  function wait() {
    var gd = document.querySelector('.plotly-graph-div');
    if (gd && gd.on && gd.data) setup(gd); else setTimeout(wait, 50);
  }
  wait();
})();
</script>"""


def open_mean_fluxes(parent=None):
    """Prompt for a daily WaterCycle .csv file and open the Mean Weekly Fluxes window."""
    if not _FD_AVAILABLE:
        QMessageBox.warning(
            parent, "Mean Weekly Fluxes",
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
        parent, "Open daily WaterCycle result CSV", start_dir,
        "Water csv (Water*.csv);;CSV result files (*.csv)")
    if not path:
        return
    try:
        win = MeanFluxesWindow(path, parent)
        win.exec()
    except Exception as e:
        import traceback
        traceback.print_exc()
        QMessageBox.warning(parent, "Mean Weekly Fluxes", f"Could not open the file:\n{e}")


def _rgba(hex_color, alpha):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


class MeanFluxesWindow(FlowDiagramWindow):
    """Flow Diagram window showing the mean weekly fluxes instead of the Sankey."""

    _save_fallback = "meanfluxes"
    _save_suffix = "_meanfluxes"
    _csv_name = "meanfluxes.csv"

    def __init__(self, csv_path, parent=None):
        super().__init__(csv_path, parent)
        title = self.settings_title or os.path.basename(str(csv_path))
        self.setWindowTitle(f"\U0001F30A Mean Weekly Fluxes: {title}")
        if not self._geometry_was_restored:
            self.resize(*scaled_default_size(self, 900, 900))
        # the Sankey's right-click hit test does not know these panels
        self.web_view.setContextMenuPolicy(Qt.NoContextMenu)

    def _init_geometry_memory(self, key):
        return super()._init_geometry_memory("meanfluxes")

    def _daily_mm(self, cols):
        """mm/day over the basin of the summed columns (None when none is in the csv)."""
        df = self._df.iloc[self._start_idx:self._end_idx + 1]
        cols = [c for c in cols if c in df.columns]
        if not cols:
            return None
        v = sum(pd.to_numeric(df[c], errors="coerce").fillna(0.0).to_numpy(dtype=float)
                for c in cols)
        if cols[0].endswith("_m3s-1"):
            v = v * 86400.0
        return v / self._cellAreaSum * 1000.0

    def _build_figure(self):
        if self._rows_per_year != 365.25:
            raise ValueError("Mean Weekly Fluxes needs a daily WaterCycle csv "
                             "(OUT_TSS_AreaSum_Daily = WaterCycle).")
        self._period_text = (f"from {self._fmt_month(self._start_idx)} "
                             f"to {self._fmt_month(self._end_idx)}")
        dates = pd.DatetimeIndex(self._month_dates[self._start_idx:self._end_idx + 1])
        week = np.minimum((dates.dayofyear.to_numpy() - 1) // 7, WEEKS - 1)

        # mean mm/day of the days of each week of the year, x 7 = mm/week
        panels = []
        for name, cols, color in FLUXES:
            v = self._daily_mm(cols)
            if v is None and name == "Precipitation":      # no own column: rain + snow
                v = self._daily_mm(["Rain_areasum_m3", "Snow_areasum_m3"])
            if v is None:
                continue
            mean = pd.Series(v).groupby(week).mean().reindex(range(WEEKS)) * 7.0
            panels.append((name, color, mean.to_numpy()))
        if not panels:
            raise ValueError("None of the fluxes is in this csv.")

        # x: the middle of each week in a non-leap year (only month names are shown)
        x = pd.Timestamp("2001-01-01") + pd.to_timedelta(np.arange(WEEKS) * 7 + 3.5, unit="D")
        n = len(panels)
        letters = "abcdefghijklmnopqrstuvwxyz"
        fig = make_subplots(rows=n, cols=1, shared_xaxes=True, vertical_spacing=VSPACE,
                            subplot_titles=[f"{letters[i]}) {p[0]}" for i, p in enumerate(panels)])
        for i, (name, color, y) in enumerate(panels):
            fig.add_trace(go.Scatter(
                x=x, y=y, name=name, mode="lines", fill="tozeroy",
                fillcolor=_rgba(color, 0.55), line=dict(color=color, width=1.6),
                hovertemplate=f"{name}: %{{y:.2f}} mm/week<br>%{{x|%d %b}}<extra></extra>"),
                row=i + 1, col=1)
            fig.update_yaxes(rangemode="tozero", showline=True, mirror=True, linecolor=theme.c("text"),
                             ticks="outside", row=i + 1, col=1)
            fig.update_xaxes(showline=True, mirror=True, linecolor=theme.c("text"),
                             row=i + 1, col=1)
        fig.update_xaxes(tickformat="%b", dtick="M1", ticklabelmode="period",
                         range=[pd.Timestamp("2001-01-01"), pd.Timestamp("2001-12-31")])
        for a in fig.layout.annotations:          # subplot titles top left, like "a) Rain"
            a.update(x=0, xanchor="left", font=dict(size=10, color=theme.c("text")))
        # a fixed pixel distance left of the plot, clear of the tick labels at any width
        fig.add_annotation(text="mm/week", textangle=-90, x=0, xshift=-58, xanchor="right",
                           y=0.5, xref="paper", yref="paper", showarrow=False,
                           font=dict(size=13, color=theme.c("text")))
        fig.update_layout(
            template=theme.plotly_template(),
            font=dict(family="Helvetica, Arial, sans-serif", size=10),
            autosize=True, margin=dict(l=85, r=10, t=24, b=24),
            legend=dict(x=1.02, y=1, xanchor="left", yanchor="top"),
            hoverlabel=dict(align="left"))
        _ov = theme.plotly_layout_overrides()
        if _ov:
            fig.update_layout(**{k: v for k, v in _ov.items() if k not in ("xaxis", "yaxis")})

        # Save CSV: the weekly table
        name = self.settings_title or os.path.basename(str(self.csv_path))
        self._csv_data = (
            [("Basin", name), ("lon", self.lon), ("lat", self.lat),
             ("Period", self._period_text), ("Unit", "mm/week")],
            ["Week"] + [p[0] for p in panels],
            [[w + 1] + [None if np.isnan(p[2][w]) else round(float(p[2][w]), 4) for p in panels]
             for w in range(WEEKS)])
        return fig

    def _show_sankey(self):
        fig = self._build_figure()
        self.sub_label.setText(
            f"{self._station_label()}lon: {self.lon}, lat: {self.lat}"
            f"\n{self._period_text}  |  mean of each week of the year")
        html = fig.to_html(include_plotlyjs=True, full_html=True,
                           config={"responsive": True, "displaylogo": False})
        fill = ("<style>html,body{height:100%;margin:0;padding:0;overflow:hidden;}"
                ".plotly-graph-div{height:100vh!important;width:100%!important;}</style>")
        html = html.replace("<head>", "<head>" + fill, 1)
        html = html.replace("</body>", _PANEL_JS.replace("%GAP%", str(VSPACE)) + "</body>", 1)
        html = theme.themed_plot_page(html)
        self._load_temp_page(html, "cwatm_mf_")
