"""
Flow duration curve window (Analyse ▸ NetCDF ▸ Action ▸ Flow duration).

Only ever plots ONE point (the last one clicked on the map, like Total Timeseries -
except this never accumulates several). Its full-resolution series is broken into
one flow duration curve per calendar YEAR (ranked within that year alone), plus the
all-years curve overlaid as a single black "average" line - the classic flow
duration curve, x-axis = exceedance probability (0% = highest flow, 100% = lowest /
low flow), y-axis = the variable, in its own unit.

Two toggle buttons: **Remove single years** hides the per-year curves (average
only); **Show Percentile bands** overlays the cross-year 0-100% and 40-60%
percentile spread at each probability level, in two shades of gray (each year's
curve is interpolated onto a common probability grid first, since years generally
have a different number of valid values). **Save as csv** exports that same
interpolated table - rows = exceedance probability (0-100%, 1% steps), one column
per calendar year.
"""

import os
import re

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from src.gui.utils import theme
from src.gui.utils.window_geometry import scaled_default_size
from src.gui.widgets.analysis_plot_base import PlotlyWindowBase, resolved_pathout_dir

from src.gui.utils.gui_log import get_logger

log = get_logger("analysis_flow_duration")

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    import plotly.graph_objects as go
    _FD_AVAILABLE = True
except Exception:  # pragma: no cover - import guard
    _FD_AVAILABLE = False

# Trace colours for the individual years; the all-years average is always black.
_YEAR_COLORS = ["#2c7fb8", "#e67e22", "#27ae60", "#8e44ad", "#c0392b",
                "#16a085", "#d35400", "#7f8c8d", "#2ecc71", "#f1c40f"]


def flow_duration_points(values):
    """(probabilities, sorted_values) for one series - Weibull plotting position,
    ranked descending (rank 1 = highest value), probabilities ascending. ``None``/
    non-finite entries are dropped first. Empty when nothing usable is left."""
    finite = [float(v) for v in values if v is not None]
    n = len(finite)
    if n == 0:
        return [], []
    finite.sort(reverse=True)
    probs = [100.0 * m / (n + 1) for m in range(1, n + 1)]
    return probs, finite


def compute_flow_duration(dates, values):
    """(year_curves, avg_probs, avg_values, bands) for one point.

    ``year_curves`` is ``[(year, probs, sorted_values), ...]`` - the flow duration
    curve computed from just that ONE calendar year's values (ranked within the
    year, not mixed with any other year). ``avg_probs``/``avg_values`` is the flow
    duration curve from every year pooled together (the classic single curve).
    ``bands`` is ``{"x", "p0", "p40", "p60", "p100"}`` - each year's curve
    interpolated onto a common 0-100% probability grid, then the cross-year min/
    40th/60th/max percentile at each grid point. All empty when there is nothing
    usable."""
    import pandas as pd
    import numpy as np

    n = min(len(dates), len(values))
    ts = pd.to_datetime(pd.Series(list(dates)[:n]), errors="coerce")
    have_value = pd.Series([v is not None for v in list(values)[:n]])
    mask = ts.notna() & have_value
    df = pd.DataFrame({"year": ts[mask].dt.year.values,
                       "value": [v for v, m in zip(values, mask) if m]})
    empty_bands = dict(x=[], p0=[], p40=[], p60=[], p100=[])
    if df.empty:
        return [], [], [], empty_bands

    year_curves = []
    for year, g in df.groupby("year"):
        probs, sorted_vals = flow_duration_points(list(g["value"]))
        if probs:
            year_curves.append((int(year), probs, sorted_vals))
    avg_probs, avg_vals = flow_duration_points(list(df["value"]))

    if not year_curves:
        return year_curves, avg_probs, avg_vals, empty_bands
    grid = np.linspace(0, 100, 101)
    per_year = np.array([np.interp(grid, probs, vals)
                         for _year, probs, vals in year_curves])
    bands = dict(
        x=list(grid),
        p0=list(np.nanmin(per_year, axis=0)),
        p40=list(np.nanpercentile(per_year, 40, axis=0)),
        p60=list(np.nanpercentile(per_year, 60, axis=0)),
        p100=list(np.nanmax(per_year, axis=0)),
    )
    return year_curves, avg_probs, avg_vals, bands


class FlowDurationWindow(PlotlyWindowBase):
    """One point's flow duration curve, per calendar year, plus the all-years
    average in black; single years and percentile bands are toggleable."""

    _save_fallback = "flow_duration"
    _save_suffix = "_flowduration"

    def __init__(self, series, varname, unit, long_name, settings_title,
                source_path, parent=None):
        super().__init__(parent)
        # series: [(label, dates, [value|None, ...])] - one entry (the point that
        # was clicked); kept as a list for symmetry with how it is built.
        self._series = series
        self.varname = varname
        self.unit = unit
        self.long_name = long_name or varname
        self.settings_title = settings_title
        # _save_html (PlotlyWindowBase) suggests a file name from this.
        self.csv_path = source_path
        self._show_years = True
        self._show_bands = False

        title = "Flow duration curve"
        if self.settings_title:
            title += f" - {self.settings_title}"
        self._title_text = title
        self.setWindowTitle(f"\U0001F4C9 {title}")
        self.setModal(False)
        self.setWindowFlags(Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        if not self._init_geometry_memory("flow_duration"):
            self.resize(*scaled_default_size(self, 820, 560))
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
            "Save the duration table as a csv - rows = exceedance probability, one "
            "column per calendar year")
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

    def set_series(self, series):
        """New data for the open window - the Timeseries window's displayed period
        changed (its range slider). Same shape as the constructor's ``series``;
        the years/bands toggles are kept."""
        self._series = series
        self._show_figure()

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
    def _duration_table(self):
        """One row per exceedance probability (0-100%, 1% steps), one column per
        calendar year (per gauge too, when there is more than one) - each year's
        curve interpolated onto that common probability grid, as a pandas
        DataFrame."""
        import numpy as np
        import pandas as pd
        grid = np.linspace(0, 100, 101)
        multi = len(self._series) > 1
        cols = {}
        for label, dates, values in self._series:
            year_curves, _avg_probs, _avg_vals, _bands = compute_flow_duration(dates, values)
            for year, probs, vals in year_curves:
                name = f"{label} {year}" if multi else str(year)
                cols[name] = np.interp(grid, probs, vals)
        return pd.DataFrame(cols, index=grid)

    def _save_csv(self):
        df = self._duration_table()
        if df.empty:
            QMessageBox.information(self, "Save as csv", "Nothing to save yet.")
            return
        label = self._series[0][0] if self._series else "flow_duration"
        base = re.sub(r'[^\w\-.]+', '_', label).strip('_') or "flow_duration"
        default = os.path.join(resolved_pathout_dir(self), base + "_flowduration.csv")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save flow duration as CSV", default, "CSV files (*.csv)")
        if not path:
            return
        try:
            df.to_csv(path, index_label="Exceedance probability [%]")
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
        multi = len(self._series) > 1
        any_points = False
        for label, dates, values in self._series:
            year_curves, avg_probs, avg_vals, bands = compute_flow_duration(dates, values)
            if self._show_bands and bands.get("x"):
                b = bands
                any_points = True
                fig.add_trace(self._band_trace(
                    b["x"], b["p0"], b["p100"], "rgba(120,120,120,0.12)", "0-100%"))
                fig.add_trace(self._band_trace(
                    b["x"], b["p40"], b["p60"], "rgba(120,120,120,0.30)", "40-60%"))
            if self._show_years:
                for i, (year, probs, sorted_vals) in enumerate(year_curves):
                    any_points = True
                    name = f"{label} {year}" if multi else str(year)
                    fig.add_trace(go.Scatter(
                        x=probs, y=sorted_vals, mode="lines", name=name,
                        line=dict(width=1.5, color=_YEAR_COLORS[i % len(_YEAR_COLORS)]),
                        opacity=0.6))
            if avg_probs:
                any_points = True
                avg_name = f"{label} average" if multi else "Average"
                fig.add_trace(go.Scatter(
                    x=avg_probs, y=avg_vals, mode="lines", name=avg_name,
                    line=dict(width=1.5, color="black")))

        yaxis_title = f"{self.long_name} [{self.unit}]" if self.unit else self.long_name
        fig.update_layout(
            title=self._title_text,
            xaxis_title="Exceedance probability [%]",
            yaxis_title=yaxis_title,
            xaxis=dict(range=[0, 100]),
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
        if not any_points:
            fig.add_annotation(text="No data", showarrow=False,
                               xref="paper", yref="paper", x=0.5, y=0.5)

        html = theme.themed_plot_page(fig.to_html(include_plotlyjs=True, full_html=True))
        self._load_temp_page(html, "cwatm_fdc_")
