"""
Flow regime curve window (Analyse ▸ NetCDF ▸ Action ▸ Flow regime, and the gauge
right-click menu's Flow regime).

Only ever plots ONE point (the last one clicked on the map). Each calendar YEAR
present in the series gets its own thin curve (seasonal pattern for that year
alone), and the multi-year average is overlaid as a single black curve on top - by
calendar day (skipping 29 Feb, so a leap year never shifts the axis) when the
series is daily, or by calendar month when it is monthly. Resolution is detected
from the median gap between timesteps (``compute_regime``); anything else (e.g. an
annual series) is refused with a clear message rather than plotting something
misleading.

Two toggle buttons: **Remove single years** hides the per-year curves (average
only); **Show Percentile bands** overlays the cross-year 0-100% and 40-60%
percentile spread at each calendar day/month, in two shades of gray. **Save as csv**
exports the underlying table - rows = calendar day (or month), one column per
calendar year.
"""

import os
import re
from datetime import datetime

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from src.gui.utils import theme
from src.gui.utils.window_geometry import scaled_default_size
from src.gui.widgets.analysis_plot_base import PlotlyWindowBase, resolved_pathout_dir

from src.gui.utils.gui_log import get_logger

log = get_logger("analysis_flow_regime")

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    import plotly.graph_objects as go
    _FR_AVAILABLE = True
except Exception:  # pragma: no cover - import guard
    _FR_AVAILABLE = False

# Trace colours for the individual years; the multi-year average is always black.
_YEAR_COLORS = ["#2c7fb8", "#e67e22", "#27ae60", "#8e44ad", "#c0392b",
                "#16a085", "#d35400", "#7f8c8d", "#2ecc71", "#f1c40f"]


def compute_regime(dates, values):
    """(year_series, avg_x, avg_y, resolution, bands) for one gauge's regime curve.

    ``dates`` are 'YYYY-MM-DD' strings (or anything ``pandas.to_datetime`` parses),
    ``values`` the matching value|None list - same convention as the rest of the
    NetCDF viewer.

    ``year_series`` is ``[(year, x_dates, y_values), ...]`` - one entry per calendar
    year present in the data, that year's OWN calendar-day/month values (not
    averaged with any other year). ``avg_x``/``avg_y`` is the multi-year average -
    the mean value per calendar day/month across every year. ``bands`` is
    ``{"x", "p0", "p40", "p60", "p100"}`` - the cross-year min/40th/60th/max
    percentile at each calendar day/month, aligned to ``bands["x"]``. ``resolution``
    is ``'daily'`` or ``'monthly'``; every x value is placed in a fixed, non-leap
    reference year (2001) purely so Plotly renders a normal month axis - only the
    month/day (or month) is ever used.

    Raises ``ValueError`` when there is not enough data, or the series is neither
    daily nor monthly (its median timestep gap is used to tell them apart)."""
    import pandas as pd
    import numpy as np

    n = min(len(dates), len(values))
    ts = pd.to_datetime(pd.Series(list(dates)[:n]), errors="coerce")
    have_value = pd.Series([v is not None for v in list(values)[:n]])
    mask = ts.notna() & have_value
    ts = ts[mask]
    vals = np.asarray([v for v, m in zip(values, mask) if m], dtype="float64")
    if len(ts) < 2:
        raise ValueError("Not enough data to compute a flow regime.")

    diffs = ts.sort_values().diff().dropna().dt.days
    if diffs.empty:
        raise ValueError("Not enough data to compute a flow regime.")
    median_gap = float(diffs.median())

    df = pd.DataFrame({"date": ts.values, "value": vals})
    daily = median_gap <= 3
    monthly = 25 <= median_gap <= 35
    if not (daily or monthly):
        raise ValueError(
            "Flow regime needs a daily or monthly time series (this file's "
            f"typical time step is about {median_gap:.0f} days).")
    resolution = "daily" if daily else "monthly"
    if daily:
        # Skip the leap day entirely rather than folding it into a neighbour -
        # every other calendar day then averages over the same number of years.
        df = df[~((df["date"].dt.month == 2) & (df["date"].dt.day == 29))]

    def _key_of(frame):
        return ([frame["date"].dt.month, frame["date"].dt.day] if daily
                else [frame["date"].dt.month])

    def _grouped_xy(frame):
        grouped = frame.groupby(_key_of(frame))["value"].mean()
        if daily:
            x = [datetime(2001, int(m), int(d)) for (m, d) in grouped.index]
        else:
            x = [datetime(2001, int(m), 15) for m in grouped.index]
        return x, list(grouped.values)

    year_series = []
    for year, g in df.groupby(df["date"].dt.year):
        x, y = _grouped_xy(g)
        year_series.append((int(year), x, y))
    avg_x, avg_y = _grouped_xy(df)

    # Cross-year percentile bands: one row per calendar day/month, one column per
    # year, then percentiles taken across the year columns.
    df = df.copy()
    df["key"] = list(zip(df["date"].dt.month, df["date"].dt.day)) if daily \
        else list(df["date"].dt.month)
    pivot = df.pivot_table(index="key", columns=df["date"].dt.year,
                           values="value", aggfunc="mean").sort_index()
    if daily:
        band_x = [datetime(2001, int(m), int(d)) for (m, d) in pivot.index]
    else:
        band_x = [datetime(2001, int(m), 15) for m in pivot.index]
    arr = pivot.to_numpy(dtype="float64")
    bands = dict(
        x=band_x,
        p0=list(np.nanmin(arr, axis=1)) if arr.size else [],
        p40=list(np.nanpercentile(arr, 40, axis=1)) if arr.size else [],
        p60=list(np.nanpercentile(arr, 60, axis=1)) if arr.size else [],
        p100=list(np.nanmax(arr, axis=1)) if arr.size else [],
    )
    return year_series, avg_x, avg_y, resolution, bands


class FlowRegimeWindow(PlotlyWindowBase):
    """One point's seasonal flow regime: every year as its own curve, plus the
    multi-year average in black; single years and percentile bands are toggleable."""

    _save_fallback = "flow_regime"
    _save_suffix = "_flowregime"

    def __init__(self, dates, values, gauge_label, varname, unit, long_name,
                settings_title, source_path, parent=None):
        super().__init__(parent)
        self.varname = varname
        self.unit = unit
        self.long_name = long_name or varname
        self.settings_title = settings_title
        # _save_html (PlotlyWindowBase) suggests a file name from this.
        self.csv_path = source_path
        # May raise ValueError (unsupported resolution / not enough data) - the
        # caller (analysis_netcdf.py) catches it before the window is ever shown.
        self._year_series, self._avg_x, self._avg_y, self._resolution, self._bands = \
            compute_regime(dates, values)
        self._gauge_label = gauge_label
        self._show_years = True
        self._show_bands = False

        title = f"Flow regime - {gauge_label}"
        if self.settings_title:
            title += f" - {self.settings_title}"
        self._title_text = title
        self.setWindowTitle(f"\U0001F4C8 {title}")
        self.setModal(False)
        self.setWindowFlags(Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        if not self._init_geometry_memory("flow_regime"):
            self.resize(*scaled_default_size(self, 780, 540))
        try:
            icon_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                'assets', 'cwatm.ico')
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            log.debug("__init__: ignored", exc_info=True)

        self._temp_html = None
        self._build_ui()
        self._show_figure()

    # ----------------------------------------------------------------------- UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.header_label = QLabel(self._title_text)
        self.header_label.setAlignment(Qt.AlignCenter)
        self.header_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 14px; font-weight: 600; "
            f"color: {theme.c('text')}; padding: 4px;")
        layout.addWidget(self.header_label)

        self.web_view = QWebEngineView()
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
        """
        self.years_button = QPushButton("Remove single years")
        self.years_button.setStyleSheet(btn_style)
        self.years_button.setToolTip("Removes the single years - only average is shown")
        self.years_button.clicked.connect(self._toggle_years)

        self.bands_button = QPushButton("Show Percentile bands")
        self.bands_button.setStyleSheet(btn_style)
        self.bands_button.setToolTip(
            "Shows the cross-year 0-100% and 40-60% percentile bands")
        self.bands_button.clicked.connect(self._toggle_bands)

        self.save_csv_button = QPushButton("Save as csv")
        self.save_csv_button.setStyleSheet(btn_style)
        self.save_csv_button.setToolTip(
            "Save the regime table as a csv - rows = day (or month), one column per "
            "calendar year")
        self.save_csv_button.clicked.connect(self._save_csv)

        self.save_html_button = QPushButton("Save HTML")
        self.save_html_button.setStyleSheet(btn_style)
        self.save_html_button.setToolTip(
            "Save the plot as a self-contained HTML file (opens in any browser)")
        self.save_html_button.clicked.connect(self._save_html)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.years_button)
        btn_row.addWidget(self.bands_button)
        btn_row.addStretch()
        btn_row.addWidget(self.save_csv_button)
        btn_row.addWidget(self.save_html_button)
        layout.addLayout(btn_row)

    # _save_html is inherited from PlotlyWindowBase.

    def _toggle_years(self):
        self._show_years = not self._show_years
        self.years_button.setText(
            "Show single years" if not self._show_years else "Remove single years")
        self._show_figure()

    def _toggle_bands(self):
        self._show_bands = not self._show_bands
        self.bands_button.setText(
            "Hide Percentile bands" if self._show_bands else "Show Percentile bands")
        self._show_figure()

    # --------------------------------------------------------------- save as csv
    def _regime_table(self):
        """One row per calendar day (or month), one column per calendar year -
        the same values the per-year curves plot, as a pandas DataFrame."""
        import pandas as pd
        label = (lambda d: d.strftime("%m-%d")) if self._resolution == "daily" \
            else (lambda d: d.strftime("%m"))
        cols = {}
        for year, x, y in self._year_series:
            cols[str(year)] = pd.Series(y, index=[label(d) for d in x])
        df = pd.DataFrame(cols)
        order = [label(d) for d in self._avg_x]
        return df.reindex(order)

    def _save_csv(self):
        df = self._regime_table()
        if df.empty:
            QMessageBox.information(self, "Save as csv", "Nothing to save yet.")
            return
        base = re.sub(r'[^\w\-.]+', '_', self._gauge_label).strip('_') or "flow_regime"
        default = os.path.join(resolved_pathout_dir(self), base + "_flowregime.csv")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save flow regime as CSV", default, "CSV files (*.csv)")
        if not path:
            return
        try:
            df.to_csv(path, index_label="Day" if self._resolution == "daily" else "Month")
        except Exception as e:
            QMessageBox.warning(self, "Save as csv", f"Could not save the file:\n{e}")

    # ------------------------------------------------------------------ figure
    @staticmethod
    def _band_trace(x, lo, hi, fillcolor, name):
        return go.Scatter(
            x=list(x) + list(x)[::-1], y=list(hi) + list(lo)[::-1],
            fill="toself", fillcolor=fillcolor, line=dict(color="rgba(0,0,0,0)"),
            hoverinfo="skip", name=name, showlegend=True)

    def _show_figure(self):
        fig = go.Figure()
        if self._show_bands and self._bands.get("x"):
            b = self._bands
            fig.add_trace(self._band_trace(
                b["x"], b["p0"], b["p100"], "rgba(120,120,120,0.12)", "0-100%"))
            fig.add_trace(self._band_trace(
                b["x"], b["p40"], b["p60"], "rgba(120,120,120,0.30)", "40-60%"))
        if self._show_years:
            for i, (year, x, y) in enumerate(self._year_series):
                fig.add_trace(go.Scatter(
                    x=x, y=y, mode="lines", name=str(year),
                    line=dict(width=1.5, color=_YEAR_COLORS[i % len(_YEAR_COLORS)]),
                    opacity=0.6))
        # Average last, always on top.
        fig.add_trace(go.Scatter(
            x=self._avg_x, y=self._avg_y, mode="lines", name="Average",
            line=dict(width=1.5, color="black")))

        yaxis_title = f"{self.long_name} [{self.unit}]" if self.unit else self.long_name
        xaxis_title = "Day of year" if self._resolution == "daily" else "Month"
        fig.update_layout(
            title=self._title_text,
            xaxis_title=xaxis_title,
            yaxis_title=yaxis_title,
            xaxis=dict(tickformat="%b", dtick="M1"),
            margin=dict(l=60, r=20, t=60, b=50),
            template=theme.plotly_template(),
            hovermode="x unified",
            showlegend=True,
            legend=dict(x=0.99, xanchor="right", y=0.99, yanchor="top",
                        bgcolor=theme.plotly_legend_bg(),
                        bordercolor=theme.c("border"), borderwidth=1),
        )
        _ov = theme.plotly_layout_overrides()
        if _ov:
            fig.update_layout(**_ov)

        html = theme.themed_plot_page(fig.to_html(include_plotlyjs=True, full_html=True))
        self._load_temp_page(html, "cwatm_fr_")
