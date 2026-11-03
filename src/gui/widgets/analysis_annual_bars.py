"""
Annual-bars analysis widget for the CWatM GUI (Analyse ▸ Watercycle ▸ Annual bars).

The components of a **daily** WaterCycle or WaterBalance csv summed per **complete
year** (every day of the year inside the slider window) over the basin, one stacked
column per year, in mm/year. Storages are a state, so for them the annual **mean** in
mm is stacked instead of a sum.

Everything else is the Mean Weekly Fluxes window (``MeanFluxesWindow``): header,
station navigation, month range slider, Save HTML / Save CSV, the colours of
``PANELS`` and the gear window - whose choice is stored separately here, in QSettings
``annualbars/shown_panels`` (defaults: Surface Runoff, Interflow, Baseflow).
"""

import os
import sys

from PySide6.QtWidgets import QFileDialog, QMessageBox

from src.gui.utils import theme
from src.gui.utils.window_geometry import scaled_default_size
from src.gui.widgets.analysis_mean_fluxes import (
    MeanFluxesWindow, PANELS, _FD_AVAILABLE, _FD_IMPORT_ERROR, _is_storage, panel_label,
)

try:
    import numpy as np
    import pandas as pd
    import plotly.graph_objects as go
except Exception as _ab_err:  # pragma: no cover - import guard
    print(f"Annual bars analysis unavailable: {type(_ab_err).__name__}: {_ab_err}",
          file=sys.stderr)

SHOWN_KEY = "annualbars/shown_panels"
DEFAULT_PANELS = {"Surface Runoff", "Interflow", "Baseflow"}
WINDOW_TITLE = "Annual bars"


def open_annual_bars(parent=None):
    """Prompt for a daily WaterCycle .csv file and open the Annual bars window."""
    if not _FD_AVAILABLE:
        QMessageBox.warning(
            parent, WINDOW_TITLE,
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
        win = AnnualBarsWindow(path, parent)
        win.exec()
    except Exception as e:
        import traceback
        traceback.print_exc()
        QMessageBox.warning(parent, WINDOW_TITLE, f"Could not open the file:\n{e}")


def complete_years(dates):
    """Year of each date, and the set of years whose every day is in ``dates``."""
    dates = pd.DatetimeIndex(dates)
    years = dates.year.to_numpy()
    counts = pd.Series(1, index=dates.normalize()).groupby(level=0).size()
    per_year = pd.Series(counts.index.year).value_counts()
    full = {int(y) for y, n in per_year.items()
            if n == (366 if pd.Timestamp(year=int(y), month=1, day=1).is_leap_year else 365)}
    return years, full


class AnnualBarsWindow(MeanFluxesWindow):
    """Mean Weekly Fluxes window showing annual stacked bars instead of weekly panels."""

    _save_fallback = "annualbars"
    _save_suffix = "_annualbars"
    _csv_name = "annualbars.csv"
    _shown_key = SHOWN_KEY
    _default_names = DEFAULT_PANELS

    def __init__(self, csv_path, parent=None):
        super().__init__(csv_path, parent)
        title = self.settings_title or os.path.basename(str(csv_path))
        self.setWindowTitle(f"\U0001F30A {WINDOW_TITLE}: {title}")
        if not self._geometry_was_restored:
            self.resize(*scaled_default_size(self, 1000, 700))
        self.panels_button.setToolTip("Choose the components to show")

    def _init_geometry_memory(self, key):
        # skip MeanFluxesWindow's key: own size/position
        return super(MeanFluxesWindow, self)._init_geometry_memory("annualbars")

    def _build_figure(self):
        if self._rows_per_year != 365.25:
            raise ValueError("Annual bars needs a daily WaterCycle or WaterBalance csv "
                             "(OUT_TSS_AreaSum_Daily = WaterCycle).")
        self._period_text = (f"from {self._fmt_month(self._start_idx)} "
                             f"to {self._fmt_month(self._end_idx)}")
        dates = self._month_dates[self._start_idx:self._end_idx + 1]
        years, full = complete_years(dates)
        if not full:
            raise ValueError("The selected period holds no complete year - "
                             "widen the time window.")
        keep = np.isin(years, sorted(full))
        year_list = sorted(full)

        available = []
        for name, remark, cols, default, color in PANELS:
            v = self._daily_mm(cols)
            if v is not None:
                available.append((name, remark, color, v))
        if not available:
            raise ValueError("None of the components is in this csv.")
        # another csv may hold none of the chosen components: then the defaults
        chosen = self._shown()
        shown = ([a for a in available if a[0] in chosen]
                 or [a for a in available if a[0] in DEFAULT_PANELS] or available[:1])

        bars = []
        for name, remark, color, v in shown:
            s = pd.Series(v[keep]).groupby(years[keep])
            per_year = (s.mean() if _is_storage(name) else s.sum()).reindex(year_list)
            bars.append((name, remark, color, per_year.to_numpy(dtype=float)))
        any_storage = any(_is_storage(b[0]) for b in bars)
        unit_text = "mm/year (storage: mm, annual mean)" if any_storage else "mm/year"

        fig = go.Figure()
        x = [str(y) for y in year_list]
        for name, remark, color, y in bars:
            unit = "mm" if _is_storage(name) else "mm/year"
            fig.add_trace(go.Bar(
                x=x, y=y, name=panel_label(name, remark), marker_color=color,
                hovertemplate=f"{name}: %{{y:.1f}} {unit}<br>%{{x}}<extra></extra>"))
        total = np.nansum([b[3] for b in bars], axis=0)
        fig.add_trace(go.Scatter(
            x=x, y=total, mode="markers", name="Total", showlegend=False,
            marker=dict(size=0.1, opacity=0),
            hovertemplate="Total: %{y:.1f}<extra></extra>"))
        fig.update_layout(
            barmode="relative",
            template=theme.plotly_template(),
            font=dict(family="Helvetica, Arial, sans-serif", size=11),
            autosize=True, margin=dict(l=70, r=10, t=24, b=40),
            legend=dict(x=1.02, y=1, xanchor="left", yanchor="top"),
            hovermode="x unified", hoverlabel=dict(align="left"),
            yaxis=dict(title=unit_text, showline=True, mirror=True,
                       linecolor=theme.c("text"), ticks="outside"),
            xaxis=dict(type="category", showline=True, mirror=True,
                       linecolor=theme.c("text")))
        _ov = theme.plotly_layout_overrides()
        if _ov:
            fig.update_layout(**{k: v for k, v in _ov.items() if k not in ("xaxis", "yaxis")})

        # Save CSV: one row per complete year
        name = self.settings_title or os.path.basename(str(self.csv_path))
        self._csv_data = (
            [("Basin", name), ("lon", self.lon), ("lat", self.lat),
             ("Period", self._period_text), ("Unit", unit_text)],
            ["Year"] + [b[0] for b in bars] + ["Total"],
            [[y] + [None if np.isnan(b[3][i]) else round(float(b[3][i]), 4) for b in bars]
             + [round(float(total[i]), 4)]
             for i, y in enumerate(year_list)])
        self._n_years = len(year_list)
        return fig

    def _show_sankey(self):
        fig = self._build_figure()
        self.sub_label.setText(
            self._station_text()
            + f"\n{self._period_text}  |  {self._n_years} complete year(s), stacked per year")
        html = fig.to_html(include_plotlyjs=True, full_html=True,
                           config={"responsive": True, "displaylogo": False})
        fill = ("<style>html,body{height:100%;margin:0;padding:0;}"
                ".plotly-graph-div{height:100vh!important;width:100%!important;}</style>")
        html = html.replace("<head>", "<head>" + fill, 1)
        html = theme.themed_plot_page(html)
        self._load_temp_page(html, "cwatm_ab_")
