"""
Full-waterbalance analysis widget for the CWatM GUI (Analyse ▸ Full Waterbalance).

Opens a CWatM ``WaterBalance_areasum_daily.csv`` (output ``OUT_TSS_AreaSum_Daily =
WaterBalance``, added by Tools ▸ Add output WaterBalance) and shows, in one scrolling
page, the **summary table** of every water-cycle circle (In / Out / dS / balance error
in mm/year, ``|error / In|`` above the threshold in red, plus the circles that are not a
balance or not drawn) followed by **all the sunbursts of the parts** of the water cycle.

The computation is ported from ``develop/Toolkit/check_waterbalance/watercycle.ipynb``
(cells no 07-22) and lives in ``src/gui/utils/full_waterbalance.py``; this module is
only the window around it.
"""

import html
import os
import sys

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QProgressDialog,
)
from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtGui import QIcon

from src.gui.utils import theme
from src.gui.utils.assets import asset_path
from src.gui.utils.window_geometry import scaled_default_size
from src.gui.widgets.analysis_plot_base import PlotlyWindowBase

from src.gui.utils.gui_log import get_logger

log = get_logger("analysis_full_waterbalance")

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    import pandas as pd
    import plotly.offline
    from src.gui.utils import full_waterbalance as fwb
    _FWB_AVAILABLE = True
    _FWB_IMPORT_ERROR = ""
except Exception as _fwb_err:  # pragma: no cover - import guard
    _FWB_AVAILABLE = False
    _FWB_IMPORT_ERROR = f"{type(_fwb_err).__name__}: {_fwb_err}"
    print(f"Full waterbalance analysis unavailable: {_FWB_IMPORT_ERROR}", file=sys.stderr)


def open_full_waterbalance(parent=None):
    """Prompt for a WaterBalance result .csv file and open the window."""
    if not _FWB_AVAILABLE:
        QMessageBox.warning(
            parent, "Full Waterbalance",
            "Plotly / QtWebEngine / pandas are not available.\n\n" + _FWB_IMPORT_ERROR
            + "\n\nInstall with:  pip install plotly pandas")
        return
    start_dir = ""
    try:
        if parent is not None and hasattr(parent, "_resolved_pathout_dir"):
            start_dir = parent._resolved_pathout_dir() or ""
    except Exception:
        start_dir = ""
    path, _ = QFileDialog.getOpenFileName(
        parent, "Open WaterBalance result CSV (WaterBalance_areasum_daily.csv)",
        start_dir, "WaterBalance csv (WaterBalance*.csv);;CSV result files (*.csv)")
    if not path:
        return
    # A WaterBalance csv of a long run is hundreds of MB (all variables, daily) - read
    # it in a worker thread behind a busy dialog so the GUI does not look hung.
    worker = _ReadWorker(path)
    busy = QProgressDialog(
        f"Reading {os.path.basename(path)} ...\n(a WaterBalance csv can be large)",
        None, 0, 0, parent)
    busy.setWindowTitle("Full Waterbalance")
    busy.setWindowModality(Qt.WindowModal)
    busy.setMinimumDuration(0)
    worker.finished.connect(busy.accept)
    worker.start()
    busy.exec()
    worker.wait()
    if worker.error:
        QMessageBox.warning(parent, "Full Waterbalance", f"Could not read the file:\n{worker.error}")
        return
    try:
        win = FullWaterbalanceWindow(path, parent, data=worker.data)
        win.exec()
    except Exception as e:
        import traceback
        traceback.print_exc()
        QMessageBox.warning(parent, "Full Waterbalance", f"Could not open the file:\n{e}")


class _ReadWorker(QThread):
    """Reads the csv off the GUI thread; ``data`` / ``error`` are set before
    ``finished`` fires."""

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.data = None
        self.error = ""

    def run(self):
        try:
            self.data = fwb.read_waterbalance_csv(self.path)
        except Exception as e:
            log.debug("_ReadWorker: read failed", exc_info=True)
            self.error = f"{type(e).__name__}: {e}"


def _num(v, spec):
    """Table cell text: formatted number, '' for NaN."""
    try:
        if pd.isna(v):
            return ""
        return format(float(v), spec)
    except (TypeError, ValueError):
        return html.escape(str(v))


class FullWaterbalanceWindow(PlotlyWindowBase):
    """Summary table + every part sunburst of a WaterBalance csv, for one station."""

    _save_fallback = "waterbalance"
    _save_suffix = "_full"
    _csv_name = "full_waterbalance.csv"

    # number formats of the summary table (as in the notebook's Styler)
    _FORMATS = {"In mm/yr": ".2f", "Out mm/yr": ".2f", "dS mm/yr": ".3f",
                "error mm/yr": ".5f", "error / In": ".1e"}

    def __init__(self, csv_path, parent=None, data=None):
        super().__init__(parent)
        self.csv_path = csv_path
        # read once; every station is computed from it (station switches are fast)
        self._data = data if data is not None else fwb.read_waterbalance_csv(csv_path)
        self._nstations = len(self._data["stations"])
        self._station_idx = fwb.outlet_station(self._data)
        self._result = None
        self._init_months()
        # the slider rebuilds the page (all sunbursts) - debounced like Watercycle's
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(400)
        self._rebuild_timer.timeout.connect(self._rebuild_keep_scroll)

        self.setWindowTitle(f"\U0001F30A Full Waterbalance: {os.path.basename(str(csv_path))}")
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        if not self._init_geometry_memory("full_waterbalance"):
            self.resize(*scaled_default_size(self, 1200, 850))
        try:
            icon = asset_path("cwatm.ico")
            if icon and os.path.exists(icon):
                self.setWindowIcon(QIcon(icon))
        except Exception:
            log.debug("__init__: icon ignored", exc_info=True)

        self._temp_html = None
        self._build_ui()
        self._show_page()

    # ----------------------------------------------------------------------- UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.header_label = QLabel("")
        self.header_label.setAlignment(Qt.AlignCenter)
        self.header_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 15px; font-weight: 600; "
            f"color: {theme.c('text')}; padding: 4px;")
        layout.addWidget(self.header_label)

        self.sub_label = QLabel("")
        self.sub_label.setAlignment(Qt.AlignCenter)
        self.sub_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 12px; "
            f"color: {theme.c('text_muted')}; padding: 2px 8px;")
        layout.addWidget(self.sub_label)

        # Month slider (as in Watercycle): selects the analysed period. It sits above
        # the web view, so it stays on top while the page scrolls.
        from src.gui.widgets.analysis_watercycle import RangeSlider
        lbl_style = ("font-family: 'Segoe UI', sans-serif; font-size: 11px; "
                     f"color: {theme.c('text_muted')};")
        n = len(self._months)
        self.range_slider = RangeSlider(0, max(n - 1, 1), self._start_m, self._end_m)
        self.range_slider.rangeChanged.connect(self._on_range_changed)
        self.start_lbl = QLabel(self._fmt_month(self._start_m))
        self.start_lbl.setStyleSheet(lbl_style)
        self.end_lbl = QLabel(self._fmt_month(self._end_m))
        self.end_lbl.setStyleSheet(lbl_style)
        slider_row = QHBoxLayout()
        slider_row.setSpacing(8)
        slider_row.addWidget(self.start_lbl)
        slider_row.addWidget(self.range_slider, 1)
        slider_row.addWidget(self.end_lbl)
        for w in (self.start_lbl, self.range_slider, self.end_lbl):
            w.setVisible(n >= 3)          # the slider needs a few months to choose from
        layout.addLayout(slider_row)

        self.web_view = QWebEngineView()
        self.web_view.loadFinished.connect(self._restore_scroll)
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
            "Save the table and all sunbursts as a self-contained HTML file (opens in any browser)")
        self.save_html_button.clicked.connect(self._save_html)

        self.prev_button = QPushButton("◀ Backward")
        self.prev_button.setStyleSheet(btn_style)
        self.prev_button.setToolTip("Show the previous station")
        self.prev_button.clicked.connect(lambda: self._goto_station(self._station_idx - 1))
        self.next_button = QPushButton("Forward ▶")
        self.next_button.setStyleSheet(btn_style)
        self.next_button.setToolTip("Show the next station")
        self.next_button.clicked.connect(lambda: self._goto_station(self._station_idx + 1))
        multi = self._nstations > 1
        self.prev_button.setVisible(multi)
        self.next_button.setVisible(multi)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._make_save_csv_button(btn_style))
        btn_row.addStretch()
        btn_row.addWidget(self.prev_button)
        btn_row.addWidget(self.next_button)
        btn_row.addStretch()
        btn_row.addWidget(self.save_html_button)
        layout.addLayout(btn_row)

    def _goto_station(self, idx):
        if 0 <= idx < self._nstations and idx != self._station_idx:
            self._station_idx = idx
            self._show_page()

    def _update_station_nav(self):
        self.prev_button.setEnabled(self._station_idx > 0)
        self.next_button.setEnabled(self._station_idx < self._nstations - 1)

    # ------------------------------------------------------------- month slider
    def _init_months(self):
        """Months of the daily csv: (first day, last day) present in each month."""
        dates = pd.to_datetime(self._data["full"].iloc[:, 0], format="%d/%m/%Y")
        grouped = dates.groupby(dates.dt.to_period("M"))
        self._months = list(zip(grouped.min(), grouped.max()))
        self._start_m, self._end_m = 0, max(len(self._months) - 1, 0)

    def _fmt_month(self, idx):
        d = self._months[idx][0]
        return f"{d.month}/{d.year}"

    def _on_range_changed(self, low, high):
        self._start_m, self._end_m = int(low), int(high)
        self.start_lbl.setText(self._fmt_month(self._start_m))
        self.end_lbl.setText(self._fmt_month(self._end_m))
        self._rebuild_timer.start()

    def _rebuild_keep_scroll(self):
        """Rebuild for the new period, back at the place the page was scrolled to."""
        self.web_view.page().runJavaScript(
            "window.scrollY", 0, lambda y: self._show_page(scroll=y or 0))

    def _restore_scroll(self, ok):
        y = int(getattr(self, "_scroll", 0) or 0)
        if ok and y > 0:
            self.web_view.page().runJavaScript(f"window.scrollTo(0, {y});")

    def _period_dates(self):
        """start_date / end_date for fwb.compute; None = the csv's own ends. The day
        before start_date is the storage baseline (the csv's first day at the start)."""
        if not self._months:
            return None, None
        start = None if self._start_m == 0 else f"{self._months[self._start_m][0]:%d/%m/%Y}"
        end = (None if self._end_m == len(self._months) - 1
               else f"{self._months[self._end_m][1]:%d/%m/%Y}")
        return start, end

    # --------------------------------------------------------------------- page
    def _show_page(self, scroll=0):
        overrides = theme.plotly_layout_overrides()
        # sunbursts have no axes - keep only the colours
        overrides = {k: v for k, v in overrides.items() if k not in ("xaxis", "yaxis")}
        start, end = self._period_dates()
        try:
            res = fwb.compute(self._data, station=self._station_idx,
                              centre_color=theme.c("panel_bg"), start_date=start, end_date=end,
                              template=theme.plotly_template(), layout_overrides=overrides)
        except ValueError as e:
            if self._result is None:
                raise
            self.sub_label.setText(str(e))
            return
        self._result = res
        self._scroll = scroll

        self.header_label.setText(res["title"])
        station = (f"Station {res['station'] + 1}/{self._nstations}: "
                   if self._nstations > 1 else "Station: ")
        self.sub_label.setText(
            f"{station}lon: {res['lon']:.4f}, lat: {res['lat']:.4f}  |  "
            f"{res['area_km2']:.1f} km²  |  {res['period']} ({res['nyears']:.2f} years)")
        self._update_station_nav()

        summary = res["summary"]
        self._csv_data = (
            [("Basin", res["title"]), ("lon", res["lon"]), ("lat", res["lat"]),
             ("Period", res["period"]), ("Unit", "mm/year")],
            list(fwb.SUMMARY_COLUMNS),
            [[name] + [None if pd.isna(r[c]) else round(float(r[c]), 6)
                       for c in fwb.SUMMARY_COLUMNS[1:-1]] + [r["terms"]]
             for name, r in summary.iterrows()])

        self._load_temp_page(self._page_html(res), "cwatm_fwb_")

    def _table_html(self, df, index_name, formats=None, red_col=None, tol=None):
        formats = formats or {}
        head = "".join(f"<th>{html.escape(c)}</th>" for c in [index_name] + list(df.columns))
        body = []
        for name, r in df.iterrows():
            cells = [f"<td class='name'>{html.escape(str(name))}</td>"]
            for c in df.columns:
                v = r[c]
                if c in formats:
                    txt = _num(v, formats[c])
                    cls = "num"
                    if c == red_col and tol is not None and not pd.isna(v) and abs(v) > tol:
                        cls += " bad"
                else:
                    txt = html.escape("" if (not isinstance(v, str) and pd.isna(v)) else str(v))
                    cls = "text"
                cells.append(f"<td class='{cls}'>{txt}</td>")
            body.append("<tr>" + "".join(cells) + "</tr>")
        return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"

    def _page_html(self, res):
        css = f"""
        body {{ background: {theme.c('panel_bg')}; color: {theme.c('text')};
               font-family: 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 13px;
               margin: 12px; }}
        h2 {{ font-size: 16px; margin: 18px 0 6px 0; }}
        table {{ border-collapse: collapse; margin: 6px 0 12px 0; font-size: 12px; }}
        th, td {{ border: 1px solid {theme.c('border')}; padding: 3px 7px; vertical-align: top; }}
        th {{ background: {theme.c('surface_bg')}; text-align: left; }}
        td.num {{ text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }}
        td.name {{ white-space: nowrap; font-weight: 600; }}
        td.text {{ color: {theme.c('text_muted')}; }}
        td.bad {{ color: {theme.c('warn_color')}; font-weight: bold; }}
        pre {{ color: {theme.c('text_muted')}; font-size: 12px; margin: 4px 0 10px 0;
               white-space: pre-wrap; }}
        .fig {{ margin: 8px auto 4px auto; }}
        .single {{ max-width: 560px; }}
        .missing {{ color: {theme.c('text_muted')}; font-style: italic; }}
        """
        parts = ["<!DOCTYPE html><html><head><meta charset='utf-8'>",
                 "<title>Full Waterbalance</title>",
                 f"<style>{css}</style>",
                 f"<script type='text/javascript'>{plotly.offline.get_plotlyjs()}</script>",
                 "</head><body>"]
        parts.append(f"<h2>Water balance of all circles (mm/year)</h2>")
        parts.append(f"<pre>{html.escape(chr(10).join(res['notes']))}</pre>")
        parts.append(self._table_html(res["summary"], "circle", self._FORMATS,
                                      red_col="error / In", tol=res["tol"]))
        parts.append("<h2>Circles not in the list above</h2>")
        parts.append(self._table_html(res["others"], "circle"))
        parts.append("<h2>Water cycle of the parts</h2>")
        parts.append(
            "<pre>Each balance sunburst: centre = part, 1st ring = Inputs | Outputs | Storage (in) | "
            "Storage (out) | Balance error,\n2nd ring = the single terms. A storage which increased counts on "
            "the output side, a storage which decreased on the input side.\nA negative term is moved to the "
            "other side. Only the parts and terms of the options which are on are drawn.</pre>")
        single = {"Total", "Evapotranspiration", "Storage change"}
        for key, fig, fnotes in res["figures"]:
            if fig is None:
                parts.append(f"<h2>{html.escape(key)}</h2>")
                parts.append(f"<p class='missing'>{html.escape(' '.join(fnotes))}</p>")
                continue
            cls = "fig single" if key in single else "fig"
            div = fig.to_html(full_html=False, include_plotlyjs=False,
                              config={"responsive": True, "displaylogo": False})
            parts.append(f"<div class='{cls}'>{div}</div>")
            if fnotes:
                parts.append(f"<pre>{html.escape(chr(10).join(fnotes))}</pre>")
        parts.append("</body></html>")
        return "".join(parts)
