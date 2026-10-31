"""
Mean-weekly-fluxes analysis widget for the CWatM GUI (Analyse ▸ Mean Weekly Fluxes) - a TEST.

The mean seasonal cycle of a **daily** WaterCycle or WaterBalance csv: for every week of
the year the mean over all years of the slider window, over the basin, one filled panel
per entry of ``PANELS`` with a shared Jan-Dec axis - fluxes in mm/week, storages in mm.
Header, station navigation, month range slider, Save HTML / Save CSV are inherited from
``FlowDiagramWindow``. The gear button (top right) chooses the panels; the choice is kept
in QSettings ``meanfluxes/shown_panels``.

To remove it again: delete this file and the "Mean Weekly Fluxes" block (+ its entry in
``_beginner_hidden_actions``) in ``src/gui/components/menu_builder.py``.
"""

import os
import sys

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QGridLayout, QLabel, QMessageBox, QToolButton, QVBoxLayout,
)
from PySide6.QtCore import QPoint, QSettings, Qt

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

# (name, remark, csv columns summed, ticked by default, colour). A panel needs ALL its
# columns in the csv, otherwise the gear window greys it out. Columns: output.py watercycle.
PANELS = [
    ("Precipitation", "Rain + Snow", ["precipitation_sn_areasum_m3"], True, "#5a7d9a"),
    ("Rain", "", ["Rain_areasum_m3"], True, "#8ecae6"),
    ("Snow", "", ["Snow_areasum_m3"], True, "#b3c6e8"),
    ("Snowmelt", "Snow + icemelt", ["SnowMelt_areasum_m3", "IceMelt_areasum_m3"], True, "#2c7fb8"),
    ("Glacier melt", "Glacier melt and rain", ["GlacierMelt_sum_m3", "GlacierRain_sum_m3"], True, "#253494"),
    ("Glacier melt only", "", ["GlacierMelt_sum_m3"], False, "#3f51a8"),
    ("Glacier rain only", "", ["GlacierRain_sum_m3"], False, "#6272c0"),
    ("Runoff", "", ["runoff_areasum_m3"], True, "#2a9d8f"),
    ("Baseflow", "", ["baseflow_areasum_m3"], False, "#57b8ab"),
    ("Actual ET", "", ["totalET_areasum_m3"], True, "#d4c26a"),
    ("Transpiration", "", ["sum_actTransTotal_areasum_m3"], False, "#7ba84f"),
    ("Bare soil evaporation", "", ["sum_actBareSoilEvap_areasum_m3"], False, "#b08d57"),
    ("Interception evaporation", "", ["sum_interceptEvap_areasum_m3"], False, "#a3b86c"),
    ("Open water evaporation", "", ["sum_openWaterEvap_areasum_m3"], False, "#c9b458"),
    ("Snow evaporation", "Sublimation", ["snowEvap_areasum_m3"], False, "#c4bd97"),
    ("Channel evaporation", "", ["EvapoChannel_areasum_m3"], False, "#bfa23f"),
    ("Waterbody evaporation", "", ["EvapWaterBodyM_areasum_m3"], False, "#a88f35"),
    ("Small lake evaporation", "", ["smallevapWaterBody_areasum_m3"], False, "#927c2e"),
    ("Water use evaporation", "", ["addtoevapotrans_areasum_m3"], False, "#7d6a27"),
    ("Total Water Storage", "", ["tws_areasum_m3"], False, "#4a5a6a"),
    ("Snow Storage", "", ["SnowCover_areasum_m3"], False, "#8fa8cf"),
    ("Interception Storage", "", ["sum_interceptStor_areasum_m3"], False, "#7f9f6a"),
    ("Soil Storage", "", ["sum_soil_areasum_m3"], False, "#8a6d4b"),
    ("Groundwater Storage", "", ["storGroundwater_areasum_m3"], False, "#5b6f8f"),
    ("Channel Storage", "", ["channelStorage_sum_m3"], False, "#4c8fb0"),
    ("Grid storage", "", ["gridcell_storage_areasum_m3"], False, "#6d8f99"),
    ("Lake Reservoir storage", "", ["lakeResStorage_sum_m3"], False, "#3b7ea1"),
    ("Small lake storage", "", ["smalllakeStorage_sum_m3"], False, "#5c9dbd"),
    ("Discharge", "", ["discharge_m3s-1"], True, "#aa4499"),
    ("Groundwater recharge", "", ["sum_gwRecharge_areasum_m3"], False, "#4f7cac"),
    ("Percolation to GW", "", ["perc3toGW_GW_areasum_m3"], False, "#6b93bd"),
    ("Preferential flow", "", ["prefFlow_GW_areasum_m3"], False, "#87aacc"),
    ("Total Withdrawal", "", ["act_irrWithdrawal_areasum_m3", "act_nonIrrWithdrawal_areasum_m3"], False, "#8b1e4f"),
    ("Irrigation Withdrawal", "", ["act_irrWithdrawal_areasum_m3"], False, "#a23263"),
    ("Nonirrigation withdrawal", "", ["act_nonIrrWithdrawal_areasum_m3"], False, "#b34a78"),
    ("Domestic withdrawal", "", ["act_domWithdrawal_areasum_m3"], False, "#c2628c"),
    ("Industry withdrawal", "", ["act_indWithdrawal_areasum_m3"], False, "#cf7aa0"),
    ("Livestock withdrawal", "", ["act_livWithdrawal_areasum_m3"], False, "#db92b3"),
    ("Total consumption", "", ["act_nonIrrConsumption_areasum_m3", "act_totalIrrConsumption_areasum_m3"], False, "#b5482a"),
    ("Non irrigation consumption", "", ["act_nonIrrConsumption_areasum_m3"], False, "#c25a3c"),
    ("Irrigation consumption", "", ["act_totalIrrConsumption_areasum_m3"], False, "#cc6c4f"),
    ("Nonpaddy consumption", "", ["act_nonpaddyConsumption_areasum_m3"], False, "#d57e62"),
    ("Paddy consumption", "", ["act_paddyConsumption_areasum_m3"], False, "#dc8f75"),
    ("Domestic consumption", "", ["act_domConsumption_areasum_m3"], False, "#e2a088"),
    ("Industry consumption", "", ["act_indConsumption_areasum_m3"], False, "#e7b09b"),
    ("Livestock consumption", "", ["act_livConsumption_areasum_m3"], False, "#ecc0ae"),
    ("Return flow", "", ["returnFlow_areasum_m3"], False, "#6a4c93"),
]
WEEKS = 52          # day 365 / 366 count to the last week
VSPACE = 0.05       # largest vertical gap between two panels (paper units)
PANEL_MIN_PX = 90   # below this height per panel the page scrolls
DIALOG_ROWS = 16    # tick boxes per column of the gear window
SHOWN_KEY = "meanfluxes/shown_panels"

# Click a legend entry: its whole panel (axes + title) goes and the other panels
# share the height; click it again to bring it back. Trace i = panel i = subplot
# title annotation i; the last annotation is the "mm/week" axis label.
# A hidden panel keeps its opaque plot background, which plotly draws over any panel that
# overlaps its domain, so its domain shrinks to a sliver below one pixel (plotly resets a
# domain thinner than 1/4096 to the full height).
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
        if (!on) {
          upd[ax('yaxis', i) + '.domain'] = [0, 0.0003];
          continue;
        }
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
        parent, "Open daily WaterCycle or WaterBalance result CSV", start_dir,
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


def _settings():
    return QSettings("IIASA", "CWatM_GUI")


def default_panels():
    return {p[0] for p in PANELS if p[3]}


def shown_panels():
    """The panel names ticked in the gear window (the defaults until one was changed)."""
    raw = _settings().value(SHOWN_KEY)
    if raw is None:
        return default_panels()
    return {n for n in str(raw).split(",") if n}


def set_panel_shown(name, shown):
    names = shown_panels()
    if shown:
        names.add(name)
    else:
        names.discard(name)
    _settings().setValue(SHOWN_KEY, ",".join(sorted(names)))


def panel_label(name, remark):
    return f"{name} ({remark})" if remark else name


def _is_storage(name):
    """Storages are a state in mm: the weekly mean, not a sum over the week."""
    return name.lower().endswith("storage")


def _panel_letter(i):
    """a, b ... z, aa, ab ..."""
    letters = "abcdefghijklmnopqrstuvwxyz"
    return letters[i] if i < 26 else letters[i // 26 - 1] + letters[i % 26]


def panel_gap(n):
    """Gap between panels: room for the title line however many panels there are."""
    return min(VSPACE, 0.25 / n)


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

    def _build_ui(self):
        super()._build_ui()
        self.panels_button = QToolButton(self)
        self.panels_button.setText("\u2699")
        self.panels_button.setToolTip("Choose the panels to show")
        self.panels_button.setCursor(Qt.PointingHandCursor)
        self.panels_button.setStyleSheet(
            f"QToolButton {{ font-size: 26pt; color: {theme.c('text')}; border: none;"
            " background: transparent; }"
            f"QToolButton:hover {{ color: {theme.c('accent')}; }}")
        self.panels_button.clicked.connect(self._choose_panels)
        # same grid cell as the title, so the title stays centred on the window
        layout = self.layout()
        index = layout.indexOf(self.header_label)
        layout.removeWidget(self.header_label)
        header = QGridLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addWidget(self.header_label, 0, 0)
        header.addWidget(self.panels_button, 0, 0, Qt.AlignRight | Qt.AlignVCenter)
        layout.insertLayout(index, header)

    def _choose_panels(self):
        """The gear window: every tick applies at once and is stored."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Panels")
        box = QVBoxLayout(dlg)
        box.addWidget(QLabel("Untick a panel to remove it from the display.\n"
                             "The choice is remembered."))
        shown = shown_panels()
        boxes = []
        grid = QGridLayout()
        box.addLayout(grid)

        def keep_last_panel():
            on = [c for c in boxes if c.isChecked()]
            for c in boxes:
                c.setEnabled(not (len(on) == 1 and c is on[0]))

        def toggled(name, checked):
            set_panel_shown(name, checked)
            keep_last_panel()
            self._rebuild_timer.start()

        for i, (name, remark, cols, _default, _color) in enumerate(PANELS):
            cb = QCheckBox(panel_label(name, remark))
            cb.setChecked(name in shown)
            if self._daily_mm(cols) is None:
                cb.setEnabled(False)
                cb.setToolTip("Not in this csv")
            else:
                boxes.append(cb)
                cb.toggled.connect(lambda checked, n=name: toggled(n, checked))
            grid.addWidget(cb, i % DIALOG_ROWS, i // DIALOG_ROWS)
        keep_last_panel()
        dlg.adjustSize()
        pos = (self.panels_button.mapToGlobal(self.panels_button.rect().bottomRight())
               - QPoint(dlg.width(), 0))
        dlg.move(max(pos.x(), self.screen().availableGeometry().left()), pos.y())
        dlg.exec()

    def _daily_mm(self, cols):
        """mm per day over the basin of the summed columns (None when one is not in the csv)."""
        df = self._df.iloc[self._start_idx:self._end_idx + 1]
        if any(c not in df.columns for c in cols):
            return None
        v = sum(pd.to_numeric(df[c], errors="coerce").fillna(0.0).to_numpy(dtype=float)
                for c in cols)
        if cols[0].endswith("_m3s-1"):
            v = v * 86400.0
        return v / self._cellAreaSum * 1000.0

    def _build_figure(self):
        if self._rows_per_year != 365.25:
            raise ValueError("Mean Weekly Fluxes needs a daily WaterCycle or WaterBalance csv "
                             "(OUT_TSS_AreaSum_Daily = WaterCycle).")
        self._period_text = (f"from {self._fmt_month(self._start_idx)} "
                             f"to {self._fmt_month(self._end_idx)}")
        dates = pd.DatetimeIndex(self._month_dates[self._start_idx:self._end_idx + 1])
        week = np.minimum((dates.dayofyear.to_numpy() - 1) // 7, WEEKS - 1)

        # mean per day of the days of each week of the year: x 7 = mm/week, storages in mm
        available = []
        for name, remark, cols, default, color in PANELS:
            v = self._daily_mm(cols)
            if v is not None:
                available.append((name, remark, default, color, v))
        if not available:
            raise ValueError("None of the fluxes is in this csv.")
        # another csv may hold none of the chosen panels: then its defaults, not nothing
        chosen = shown_panels()
        shown = ([a for a in available if a[0] in chosen]
                 or [a for a in available if a[2]] or available[:1])
        panels = []
        for name, remark, _default, color, v in shown:
            mean = pd.Series(v).groupby(week).mean().reindex(range(WEEKS))
            if not _is_storage(name):
                mean = mean * 7.0
            panels.append((name, color, mean.to_numpy(), remark))
        any_storage = any(_is_storage(p[0]) for p in panels)
        unit_text = "mm/week (storage: mm)" if any_storage else "mm/week"

        # x: the middle of each week in a non-leap year (only month names are shown)
        x = pd.Timestamp("2001-01-01") + pd.to_timedelta(np.arange(WEEKS) * 7 + 3.5, unit="D")
        n = len(panels)
        titles = []
        for i, p in enumerate(panels):
            unit = " [mm]" if _is_storage(p[0]) else ""
            titles.append(f"{_panel_letter(i)}) {panel_label(p[0], p[3])}{unit}")
        fig = make_subplots(rows=n, cols=1, shared_xaxes=True, vertical_spacing=panel_gap(n),
                            subplot_titles=titles)
        for i, (name, color, y, _remark) in enumerate(panels):
            unit = "mm" if _is_storage(name) else "mm/week"
            fig.add_trace(go.Scatter(
                x=x, y=y, name=name, mode="lines", fill="tozeroy",
                fillcolor=_rgba(color, 0.55), line=dict(color=color, width=1.6),
                hovertemplate=f"{name}: %{{y:.2f}} {unit}<br>%{{x|%d %b}}<extra></extra>"),
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
        fig.add_annotation(text=unit_text, textangle=-90, x=0, xshift=-58, xanchor="right",
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
             ("Period", self._period_text), ("Unit", unit_text)],
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
        # many panels: the page scrolls instead of squeezing them
        n = len(fig.data)
        fill = ("<style>html{height:100%;overflow-y:auto;}body{height:100%;margin:0;padding:0;}"
                f".plotly-graph-div{{height:max(100vh,{n * PANEL_MIN_PX}px)!important;"
                "width:100%!important;}</style>")
        html = html.replace("<head>", "<head>" + fill, 1)
        html = html.replace("</body>", _PANEL_JS.replace("%GAP%", str(panel_gap(n))) + "</body>", 1)
        html = theme.themed_plot_page(html)
        self._load_temp_page(html, "cwatm_mf_")
