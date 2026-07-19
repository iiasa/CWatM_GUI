"""
Timeseries analysis widget for the CWatM GUI.

Opens a CWatM result .csv file and shows the time series as a Plotly scatter plot
inside a window (similar in style to the basin viewer). If the file contains more
than one result column, the columns are shown one at a time with Forward / Backward
buttons instead of being crowded into a single plot.

CWatM result .csv layout (see e.g. discharge_daily.csv):
    row 1: "Timeseries, settingsfile: ..., Running date: ..., CWATM: ..."
    row 2: "xloc, <lon>"
    row 3: "yloc, <lat>"
    row 4: "Date, <name1>, <name2>, ..."   <- series names from column 2 onward
    row 5+: "<date>, <value1>, <value2>, ..."  <- column 1 = date (daily/monthly/yearly)
"""

import os
import re
import sys
import csv
import tempfile

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QMessageBox, QApplication
)
from PySide6.QtCore import Qt, QUrl, QTimer
from PySide6.QtGui import QIcon

from src.gui.utils.window_geometry import GeometryMemoryMixin
from src.gui.utils import theme

# Optional dependencies: Plotly for the figure, QtWebEngine to render it.
try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    import plotly.graph_objects as go
    _TS_AVAILABLE = True
    _TS_IMPORT_ERROR = ""
except Exception as _ts_err:  # pragma: no cover - import guard
    _TS_AVAILABLE = False
    _TS_IMPORT_ERROR = f"{type(_ts_err).__name__}: {_ts_err}"
    print(f"Timeseries analysis unavailable: {_TS_IMPORT_ERROR}", file=sys.stderr)


def resolved_pathout_dir(widget):
    """Resolved PathOut directory from the main window (found by walking up the
    widget's parent chain), or "". Used as the suggested folder for Save HTML."""
    w = widget.parent() if widget is not None else None
    while w is not None:
        try:
            if hasattr(w, "_resolved_pathout_dir"):
                return w._resolved_pathout_dir() or ""
            w = w.parent()
        except Exception:
            return ""
    return ""


def open_timeseries(parent=None):
    """Prompt for a result .csv file (CSV only) and open the timeseries window."""
    if not _TS_AVAILABLE:
        QMessageBox.warning(
            parent, "Timeseries",
            "Plotly / QtWebEngine are not available.\n\n" + _TS_IMPORT_ERROR
            + "\n\nInstall with:  pip install plotly")
        return
    # Start the dialog in the PathOut directory (placeholders resolved) when a
    # settings file is loaded, otherwise the last-used location.
    start_dir = ""
    try:
        if parent is not None and hasattr(parent, "_resolved_pathout_dir"):
            start_dir = parent._resolved_pathout_dir() or ""
    except Exception:
        start_dir = ""
    path, _ = QFileDialog.getOpenFileName(
        parent, "Open result CSV", start_dir, "CSV result files (*.csv)")
    if not path:
        return
    try:
        win = TimeseriesWindow(path, parent)
        win.exec()
    except Exception as e:
        import traceback
        traceback.print_exc()
        QMessageBox.warning(parent, "Timeseries", f"Could not open the file:\n{e}")


class TimeseriesWindow(GeometryMemoryMixin, QDialog):
    """Window showing a CWatM result .csv time series as a Plotly scatter plot."""

    def __init__(self, csv_path, parent=None, preloaded=None):
        super().__init__(parent)
        # When set (in-memory construction, e.g. a NetCDF grid point via from_point),
        # the figure shows a legend labelled with this name.
        self._legend_name = None
        if preloaded is not None:
            # Build directly from in-memory data instead of a CSV.
            self.csv_path = preloaded["label"]
            self.dates = preloaded["dates"]
            self.series = preloaded["series"]
            self.xlocs = preloaded.get("xlocs", [])
            self.ylocs = preloaded.get("ylocs", [])
            self.varname = preloaded["varname"]
            self.settings_title = preloaded.get("settings_title", "")
            self._legend_name = preloaded.get("legend_name")
        else:
            self.csv_path = csv_path
            # series: [(name, [values])]; xlocs/ylocs: per-column station coords
            self.dates, self.series, self.xlocs, self.ylocs = self._parse_csv(csv_path)
            # Variable name = the part of the file name before the first "_"
            # (e.g. "discharge_daily.csv" -> "discharge").
            base = os.path.splitext(os.path.basename(csv_path))[0]
            self.varname = base.split("_")[0]
            # The settings-file "Title" (from the settings file named in the CSV header,
            # else the one currently loaded in the main window).
            self.settings_title = self._read_settings_title(csv_path)
        self.compare = []  # extra result CSVs overlaid via the Compare button
        self.observed = None  # loaded observed series (for goodness-of-fit metrics)
        if not self.series:
            raise ValueError("No result columns found (expected names in row 4, "
                             "column 2 onward).")
        self.index = 0

        # Unit / long name / description from cwatm/metaNetcdf.xml (axis + figure title).
        self.unit, self.long_name, self.description = self._lookup_meta(self.varname)

        self.setWindowTitle(f"\U0001F4C8 Timeseries: {os.path.basename(str(self.csv_path))}")
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)
        # Remembered geometry from the last session (point windows spawned by the
        # NetCDF map keep their own key; their default size/offset is applied by the
        # caller when nothing was restored).
        self._geometry_was_restored = self._init_geometry_memory(
            "timeseries_point" if preloaded is not None else "timeseries")
        if not self._geometry_was_restored:
            self.resize(1000, 680)
        try:
            icon_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
                'assets', 'cwatm.ico')
            if os.path.exists(icon_path):
                self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass

        self._temp_html = None
        self._build_ui()
        self._show_current()

    @classmethod
    def from_point(cls, dates, values, name, varname, settings_title,
                   lon, lat, parent=None):
        """Build a Timeseries window from an in-memory series (e.g. a NetCDF grid point)
        instead of a CSV, rendered exactly like a CSV time series but with a **legend**
        labelled with the point location ``name``."""
        preloaded = dict(
            label=f"{varname} @ {name}",
            dates=list(dates),
            series=[(name, list(values))],
            xlocs=[lon], ylocs=[lat],
            varname=varname,
            settings_title=settings_title or "",
            legend_name=name,
        )
        return cls(None, parent=parent, preloaded=preloaded)

    # ------------------------------------------------------------------ parsing
    def _parse_csv(self, path):
        """Return (dates, series, xlocs, ylocs) where dates is a list of date strings,
        series is a list of (name, [float|None values]) - one entry per result column -
        and xlocs/ylocs are the per-column station coordinates (row 2 / row 3)."""
        with open(path, encoding="utf-8", errors="ignore", newline="") as f:
            rows = list(csv.reader(f))
        if len(rows) < 5:
            raise ValueError("The CSV has too few rows to be a CWatM result file.")

        header = rows[3]                      # row 4: "Date, name1, name2, ..."
        names = [h.strip() for h in header[1:]]
        if not names:
            raise ValueError("No time-series names found in row 4.")

        # Station coordinates: row 2 "xloc, <lon1>, <lon2>, ..." and row 3
        # "yloc, <lat1>, <lat2>, ..." (one per result column, aligned with names).
        xlocs = [c.strip() for c in rows[1][1:]] if len(rows) > 1 else []
        ylocs = [c.strip() for c in rows[2][1:]] if len(rows) > 2 else []

        dates = []
        columns = [[] for _ in names]
        for r in rows[4:]:                    # row 5 onward: date, value1, value2, ...
            if not r or not r[0].strip():
                continue
            dates.append(r[0].strip())
            for i in range(len(names)):
                raw = r[i + 1].strip() if (i + 1) < len(r) else ""
                try:
                    columns[i].append(float(raw))
                except ValueError:
                    columns[i].append(None)

        series = [(names[i], columns[i]) for i in range(len(names))]
        return dates, series, xlocs, ylocs

    @staticmethod
    def _lookup_meta(varname):
        """(unit, long_name, description) for varname from the process-wide cached
        metaNetcdf.xml lookup (src/gui/utils/meta_netcdf.py - parsed once, not per
        window open). Missing values come back as empty strings."""
        from src.gui.utils.meta_netcdf import get_meta
        return get_meta(varname) or ("", "", "")

    def _title_from_settings_content(self, content):
        """Extract the 'Title' value from settings-file content, or '' if absent."""
        for line in (content or "").split("\n"):
            s = line.strip()
            if s.startswith("#") or s.startswith(";") or "=" not in s:
                continue
            key, value = s.split("=", 1)
            if key.strip().lower() == "title":
                return value.strip()
        return ""

    def _read_settings_title(self, csv_path):
        """The settings-file 'Title': read from the settings file named in the CSV
        header (row 1, 'settingsfile: <path>'); fall back to the title currently loaded
        in the main window. Empty string if neither is available."""
        # 1) Settings file referenced in the CSV header
        try:
            with open(csv_path, encoding="utf-8", errors="ignore", newline="") as f:
                first = f.readline()
            for cell in first.split(","):
                c = cell.strip()
                if c.lower().startswith("settingsfile:"):
                    path = c.split(":", 1)[1].strip()
                    if path and os.path.exists(path):
                        content = open(path, encoding="utf-8", errors="ignore").read()
                        t = self._title_from_settings_content(content)
                        if t:
                            return t
                    break
        except Exception:
            pass
        # 2) Fall back to the settings currently loaded in the main window
        try:
            mw = self.parent()
            if mw is not None and hasattr(mw, "original_content"):
                t = self._title_from_settings_content(mw.original_content or "")
                if t:
                    return t
        except Exception:
            pass
        return ""

    @staticmethod
    def _detect_dayfirst(dates):
        """Whether the date strings are day-first. CWatM result CSVs use dd/mm/yyyy
        (day-first); NetCDF/point series use ISO YYYY-MM-DD (not day-first). Detected
        per call so a day-first main series and an ISO compare series (or vice versa)
        each parse correctly."""
        for d in dates:
            s = str(d).strip()
            if not s:
                continue
            if re.match(r'^\d{4}-\d{1,2}-\d{1,2}', s):   # ISO 8601 (YYYY-MM-DD)
                return False
            if '/' in s:                                  # dd/mm/yyyy
                return True
            break
        return False

    def _parse_dates(self, dates):
        """Parse the date strings to datetimes for a proper time axis. Returns the
        original strings if parsing fails (Plotly then treats them as categories)."""
        try:
            import pandas as pd
            parsed = pd.to_datetime(dates, dayfirst=self._detect_dayfirst(dates),
                                    errors="coerce")
            if parsed.isna().all():
                return dates
            return list(parsed)
        except Exception:
            return dates

    # ----------------------------------------------------------------------- UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Header: file name + which series is shown
        self.header_label = QLabel("")
        self.header_label.setAlignment(Qt.AlignCenter)
        self.header_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 14px; font-weight: 600; "
            f"color: {theme.c('text')}; padding: 4px;")
        layout.addWidget(self.header_label)

        # Plot area
        self.web_view = QWebEngineView()
        layout.addWidget(self.web_view, 1)

        # Two-handle range slider below the plot: shrink the displayed period from
        # either end. The selected window also defines the period over which the
        # observed goodness-of-fit metrics (KGE / NSE / …) are computed.
        from src.gui.widgets.analysis_watercycle import RangeSlider
        n = len(self.dates)
        self._win_lo = 0
        self._win_hi = max(0, n - 1)
        self.range_label = QLabel("")
        self.range_label.setAlignment(Qt.AlignCenter)
        self.range_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 11px; "
            f"color: {theme.c('text_muted')}; padding: 0px 8px;")
        self.range_slider = RangeSlider(0, self._win_hi, 0, self._win_hi)
        self.range_slider.rangeChanged.connect(self._on_range_changed)
        _has_range = n > 2  # a slider only makes sense with several time steps
        self.range_label.setVisible(_has_range)
        self.range_slider.setVisible(_has_range)
        layout.addWidget(self.range_label)
        layout.addWidget(self.range_slider)
        self._update_range_label()
        # Debounce the (heavy) figure rebuild while a handle is being dragged.
        self._range_timer = QTimer(self)
        self._range_timer.setSingleShot(True)
        self._range_timer.setInterval(200)
        self._range_timer.timeout.connect(self._show_current)

        # Description (from metaNetcdf.xml, without the trailing "[Array]" marker)
        self.desc_label = QLabel(self.description)
        self.desc_label.setWordWrap(True)
        self.desc_label.setAlignment(Qt.AlignCenter)
        self.desc_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 12px; "
            f"color: {theme.c('text_muted')}; padding: 2px 8px;")
        self.desc_label.setVisible(bool(self.description))
        layout.addWidget(self.desc_label)

        # Goodness-of-fit read-out (shown only once an observed series is loaded)
        self.metrics_label = QLabel("")
        self.metrics_label.setWordWrap(True)
        self.metrics_label.setAlignment(Qt.AlignCenter)
        self.metrics_label.setStyleSheet(
            "font-family: 'Segoe UI', sans-serif; font-size: 12px; font-weight: 600; "
            f"color: {theme.c('text')}; padding: 2px 8px;")
        self.metrics_label.setVisible(False)
        layout.addWidget(self.metrics_label)

        # Navigation buttons (only useful with more than one series)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
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
        self.prev_button = QPushButton("◀ Backward")
        self.prev_button.setStyleSheet(btn_style)
        self.prev_button.clicked.connect(self._prev)
        self.next_button = QPushButton("Forward ▶")
        self.next_button.setStyleSheet(btn_style)
        self.next_button.clicked.connect(self._next)

        # Compare: overlay another result CSV on the current plot (bottom-left)
        compare_style = """
            QPushButton {
                font-family: 'Segoe UI', sans-serif; font-size: 12px; font-weight: 600;
                color: white; border: none; border-radius: 6px; padding: 6px 16px;
                min-height: 26px; background: #2980b9;
            }
            QPushButton:hover { background: #3498db; }
            QPushButton:pressed { background: #21618c; }
        """
        self.compare_button = QPushButton("Compare")
        self.compare_button.setStyleSheet(compare_style)
        self.compare_button.setToolTip(
            "Open another result .csv and overlay its time series on this plot")
        self.compare_button.clicked.connect(self._compare)

        # Load an observed series and show KGE / NSE / PBIAS / RMSE vs. the current series
        self.observed_button = QPushButton("Load observed")
        self.observed_button.setStyleSheet(compare_style)
        self.observed_button.setToolTip(
            "Overlay an observed series (a CWatM result .csv or a simple date,value .csv) "
            "and show KGE / NSE / PBIAS / RMSE against the current series")
        self.observed_button.clicked.connect(self._toggle_observed)

        # Save the series as a CWatM result .csv (discharge_daily.csv format)
        self.save_csv_button = QPushButton("Save as csv")
        self.save_csv_button.setStyleSheet(btn_style)
        self.save_csv_button.setToolTip(
            "Save the time series as a CWatM result .csv (discharge_daily.csv format)")
        self.save_csv_button.clicked.connect(self._save_csv)

        # Save the current self-contained plot HTML (shareable, opens in any browser)
        self.save_html_button = QPushButton("Save HTML")
        self.save_html_button.setStyleSheet(btn_style)
        self.save_html_button.setToolTip(
            "Save the plot as a self-contained HTML file (opens in any browser)")
        self.save_html_button.clicked.connect(self._save_html)

        btn_row.addWidget(self.compare_button)
        btn_row.addWidget(self.observed_button)
        btn_row.addStretch()
        btn_row.addWidget(self.prev_button)
        btn_row.addWidget(self.next_button)
        btn_row.addStretch()
        btn_row.addWidget(self.save_csv_button)
        btn_row.addWidget(self.save_html_button)

        # The buttons only make sense with more than one result column
        multi = len(self.series) > 1
        self.prev_button.setVisible(multi)
        self.next_button.setVisible(multi)
        layout.addLayout(btn_row)

    def _save_html(self):
        """Save the currently rendered plot HTML to a user-chosen file."""
        if not self._temp_html or not os.path.exists(self._temp_html):
            QMessageBox.information(self, "Save HTML", "Nothing to save yet.")
            return
        base = os.path.splitext(os.path.basename(str(self.csv_path)))[0] or "timeseries"
        base = re.sub(r'[^\w\-.]+', '_', base).strip('_')  # point labels contain "@ ,"
        # Suggest saving into the resolved PathOut (output) directory
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

    # ------------------------------------------------------------- save as csv
    @staticmethod
    def _loc_str(v):
        """Format a station coordinate the way CWatM writes xloc/yloc (``%#.4f``)."""
        if v is None or v == "":
            return ""
        try:
            return "%#.4f" % float(v)
        except Exception:
            return str(v).strip()

    @staticmethod
    def _lonlat_from_name(name):
        """Pull (lon, lat) out of a point label like ``lon 16.6084, lat 48.9083``."""
        s = (name or "").strip().lower()
        if s.startswith("lon"):
            m = re.findall(r'-?\d+\.?\d*', s)
            if len(m) >= 2:
                return m[0], m[1]
        return None, None

    def _dates_ddmmyyyy(self, dates):
        """Reformat the date axis to ``DD/MM/YYYY`` (CWatM's timeseries date format);
        an unparseable entry is written verbatim."""
        try:
            import pandas as pd
            parsed = pd.to_datetime(dates, dayfirst=self._detect_dayfirst(dates),
                                    errors="coerce")
            out = []
            for orig, p in zip(dates, parsed):
                out.append(p.strftime("%d/%m/%Y") if not pd.isna(p) else str(orig))
            return out
        except Exception:
            return [str(d) for d in dates]

    def _settings_file_path(self):
        """The main window's current settings file (walk the parent chain), or ""."""
        w = self.parent()
        while w is not None:
            try:
                fm = getattr(w, "file_manager", None)
                if fm is not None and hasattr(fm, "get_current_file_path"):
                    return fm.get_current_file_path() or ""
                w = w.parent()
            except Exception:
                break
        return ""

    def _save_csv(self):
        """Save the series (main + any overlaid point series) as a CWatM result .csv,
        byte-format-compatible with e.g. discharge_daily.csv."""
        import time as _time
        # Columns: (xloc, yloc, values) - main series first, then each overlay.
        cols = []
        for i, (_name, vals) in enumerate(self.series):
            cols.append((self._loc_str(self.xlocs[i] if i < len(self.xlocs) else None),
                         self._loc_str(self.ylocs[i] if i < len(self.ylocs) else None),
                         vals))
        for cmp in self.compare:
            lon, lat = self._lonlat_from_name(cmp.get("name", ""))
            for (_name, vals) in cmp.get("series", []):
                cols.append((self._loc_str(lon), self._loc_str(lat), vals))
        if not cols:
            QMessageBox.information(self, "Save as csv", "Nothing to save yet.")
            return

        date_strs = self._dates_ddmmyyyy(self.dates)
        base = os.path.splitext(os.path.basename(str(self.csv_path)))[0] or self.varname \
            or "timeseries"
        base = re.sub(r'[^\w\-.]+', '_', base).strip('_')  # point labels contain "@ ,"
        default = os.path.join(resolved_pathout_dir(self), base + ".csv")
        path, _ = QFileDialog.getSaveFileName(
            self, "Save time series as CSV", default, "CSV files (*.csv)")
        if not path:
            return
        try:
            lines = [
                "Timeseries,settingsfile: %s,Runnning date: %s,CWATM: CWatM GUI export"
                % (self._settings_file_path(), _time.ctime()),
                "xloc" + "".join("," + c[0] for c in cols),
                "yloc" + "".join("," + c[1] for c in cols),
                "Date" + "".join(",G%d" % (i + 1) for i in range(len(cols))),
            ]
            for r in range(len(date_strs)):
                row = date_strs[r]
                for c in cols:
                    vals = c[2]
                    v = vals[r] if r < len(vals) else None
                    row += "," if v is None else ",%13.10g" % v
                lines.append(row)
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write("\r\n".join(lines) + "\r\n")
        except Exception as e:
            QMessageBox.warning(self, "Save as csv", f"Could not save the file:\n{e}")

    # -------------------------------------------------------------- navigation
    def _prev(self):
        self.index = (self.index - 1) % len(self.series)
        self._show_current()

    def _next(self):
        self.index = (self.index + 1) % len(self.series)
        self._show_current()

    def _compare(self):
        """Open another result .csv and overlay its time series on the current plot.
        Both axes are then rescaled to the combined min/max and a legend is shown."""
        start_dir = os.path.dirname(self.csv_path)
        path, _ = QFileDialog.getOpenFileName(
            self, "Open result CSV to compare", start_dir, "CSV result files (*.csv)")
        if not path:
            return
        try:
            dates, series, xlocs, ylocs = self._parse_csv(path)
        except Exception as e:
            QMessageBox.warning(self, "Compare", f"Could not open the file:\n{e}")
            return
        if not series:
            QMessageBox.warning(self, "Compare", "No result columns found in the file.")
            return
        self.compare.append({
            "name": os.path.basename(path),
            "x": self._parse_dates(dates),
            "series": series,
        })
        self._show_current()

    # ------------------------------------------------------------- range slider
    def _on_range_changed(self, lo, hi):
        """Slider moved: remember the window, update the period label + metrics now,
        and debounce the (heavy) figure rebuild."""
        self._win_lo = lo
        self._win_hi = hi
        self._update_range_label()
        self._update_metrics_label()   # metrics follow the window immediately
        self._range_timer.start()

    def _update_range_label(self):
        """Show the currently displayed period next to the slider."""
        if not self.dates:
            return
        n = len(self.dates)
        lo = max(0, min(self._win_lo, n - 1))
        hi = max(0, min(self._win_hi, n - 1))
        full = lo == 0 and hi == n - 1
        suffix = "  (full)" if full else ""
        self.range_label.setText(
            f"Displayed period: {self.dates[lo]} – {self.dates[hi]}{suffix}")

    def _window_bounds(self):
        """Clamped (lo, hi) index window into ``self.dates`` for the current slider."""
        n = len(self.dates)
        if n == 0:
            return 0, -1
        lo = max(0, min(getattr(self, "_win_lo", 0), n - 1))
        hi = max(0, min(getattr(self, "_win_hi", n - 1), n - 1))
        if hi < lo:
            lo, hi = hi, lo
        return lo, hi

    # ----------------------------------------------------------- observed / GOF
    def _toggle_observed(self):
        """Load an observed series (first click) or clear it (when one is loaded)."""
        if self.observed is not None:
            self.observed = None
            self.observed_button.setText("Load observed")
            self._show_current()
            return
        start_dir = os.path.dirname(str(self.csv_path)) \
            if self.csv_path and os.path.exists(str(self.csv_path)) else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open observed CSV", start_dir, "CSV files (*.csv)")
        if not path:
            return
        try:
            dates, values, name = self._parse_observed(path)
        except Exception as e:
            QMessageBox.warning(self, "Load observed", f"Could not read the file:\n{e}")
            return
        self.observed = {
            "name": os.path.basename(path),
            "x": self._parse_dates(dates),
            "values": values,
        }
        self.observed_button.setText("Clear observed")
        self._show_current()

    def _parse_observed(self, path):
        """Return (dates, values, name) for an observed series. Accepts a CWatM result
        .csv (first result column) or a simple ``date,value`` two-column .csv."""
        # 1) CWatM result CSV layout (first result column)
        try:
            dates, series, _x, _y = self._parse_csv(path)
            if series:
                nm, vals = series[0]
                return dates, vals, (nm or "observed")
        except Exception:
            pass
        # 2) Simple date,value CSV (header rows whose 2nd cell is not numeric are skipped)
        dates, values = [], []
        with open(path, encoding="utf-8", errors="ignore", newline="") as f:
            for row in csv.reader(f):
                if len(row) < 2 or not row[0].strip():
                    continue
                try:
                    v = float(row[1].strip())
                except ValueError:
                    continue
                dates.append(row[0].strip())
                values.append(v)
        if not dates:
            raise ValueError(
                "No date,value rows found (expected a CWatM result .csv or a "
                "two-column date,value .csv).")
        return dates, values, "observed"

    @staticmethod
    def _date_key(d):
        """Normalise a date (Timestamp or string) to a day-resolution key for aligning
        the observed and simulated series."""
        try:
            import pandas as pd
            ts = d if hasattr(d, "normalize") else pd.Timestamp(d)
            return ts.normalize()
        except Exception:
            return str(d).strip()

    def _aligned_obs_sim(self):
        """(sim, obs) values aligned on matching dates for the currently shown series,
        restricted to the slider's displayed period, or None when no observed series is
        loaded."""
        if not self.observed:
            return None
        _name, sim_vals = self.series[self.index]
        sim_dates = self._parse_dates(self.dates)
        lo, hi = self._window_bounds()   # only the displayed period counts for the GOF
        obs_map = {}
        for d, v in zip(self.observed["x"], self.observed["values"]):
            obs_map[self._date_key(d)] = v
        sim_aligned, obs_aligned = [], []
        for i in range(lo, min(hi, len(sim_dates) - 1, len(sim_vals) - 1) + 1):
            k = self._date_key(sim_dates[i])
            if k in obs_map:
                sim_aligned.append(sim_vals[i])
                obs_aligned.append(obs_map[k])
        return sim_aligned, obs_aligned

    def _update_metrics_label(self):
        """Refresh the goodness-of-fit read-out for the current series vs. observed."""
        if not self.observed:
            self.metrics_label.setVisible(False)
            return
        pair = self._aligned_obs_sim()
        if not pair or not pair[0]:
            self.metrics_label.setText(
                f"Observed ({self.observed['name']}) loaded, but no overlapping "
                "dates with this series.")
            self.metrics_label.setVisible(True)
            return
        from src.gui.utils.metrics import compute_all
        m = compute_all(pair[0], pair[1])
        f = lambda x: "n/a" if x is None else f"{x:.3f}"
        self.metrics_label.setText(
            f"vs observed ({self.observed['name']}, n={m['n']}):   "
            f"KGE {f(m['KGE'])}    NSE {f(m['NSE'])}    "
            f"PBIAS {f(m['PBIAS'])}%    RMSE {f(m['RMSE'])} {self.unit}".strip())
        self.metrics_label.setVisible(True)

    def add_point_series(self, dates, values, name):
        """Overlay another in-memory point series (used by NetCDF ▸ Display timeserie for
        a second clicked point). Rendered like a Compare overlay, labelled in the legend
        with the point location ``name``. Axes rescale to include it."""
        self.compare.append({
            "name": name,
            "label": f"{self.varname} @ {name}",   # legend label, matching the main point
            "x": self._parse_dates(list(dates)),
            "series": [(name, list(values))],
        })
        self._show_current()

    # Trace colours: the main series is fixed blue, overlaid/compared series cycle
    # through _COMPARE_COLORS. (NetCDF ▸ Display timeserie colours the map point to match.)
    _MAIN_COLOR = "#2c7fb8"
    _COMPARE_COLORS = ["#e67e22", "#27ae60", "#8e44ad", "#c0392b",
                       "#16a085", "#d35400", "#7f8c8d", "#2ecc71"]

    def _show_current(self):
        name, values = self.series[self.index]
        n = len(self.series)
        comparing = bool(self.compare)
        if self._legend_name:
            # Point (NetCDF) window: header = the "<var> @ lon.., lat.." label, which is
            # also used verbatim as the legend entry for this series.
            head = str(self.csv_path)
        elif n > 1:
            head = f"{os.path.basename(self.csv_path)}  —  {name}  ({self.index + 1} / {n})"
        else:
            head = f"{os.path.basename(self.csv_path)}  —  {name}"
        if comparing and not self._legend_name:
            head += f"   +{len(self.compare)} compared"
        self.header_label.setText(head)
        self._update_metrics_label()

        x = self._parse_dates(self.dates)
        # Figure title, line 1: "<long_name> - <settings Title>"
        #              line 2 (CSV only): "Station: <name> - lon: <xloc> lat:<yloc>"
        # y-axis label:        "<long_name> [<unit>]"
        long_name = self.long_name or self.varname or name
        title = f"{long_name} - {self.settings_title}" if self.settings_title else long_name
        # CSV series add a 2nd title line (station + coords). Point (NetCDF) windows omit
        # it - the location is already in the header and the legend.
        if not self._legend_name:
            i = self.index
            lon = self.xlocs[i] if i < len(self.xlocs) else ""
            lat = self.ylocs[i] if i < len(self.ylocs) else ""
            station = f"Station: {name} - lon: {lon} lat:{lat}"
            _sub = theme.c('text_gray') if theme.is_dark() else '#555'
            title = f"{title}<br><span style='font-size:13px;color:{_sub}'>{station}</span>"
        yaxis_title = f"{long_name} [{self.unit}]" if self.unit else long_name

        fig = go.Figure()
        # Legend label for the main trace:
        #  - point (NetCDF) window: the "<var> @ lon.., lat.." header text (self.csv_path)
        #  - compared CSV window: "<file> - <col>"; otherwise just the column name.
        if self._legend_name:
            main_name = str(self.csv_path)
        elif comparing:
            main_name = f"{os.path.basename(self.csv_path)} - {name}"
        else:
            main_name = name
        fig.add_trace(go.Scatter(
            x=x, y=values, mode="lines", name=main_name,
            line=dict(width=1.5, color=self._MAIN_COLOR)))

        # Overlay each comparison file (matching column index, else its first column)
        all_x = [x]
        all_y = [values]
        for k, comp in enumerate(self.compare):
            cseries = comp["series"]
            j = self.index if self.index < len(cseries) else 0
            cname, cvals = cseries[j]
            color = self._COMPARE_COLORS[k % len(self._COMPARE_COLORS)]
            fig.add_trace(go.Scatter(
                x=comp["x"], y=cvals, mode="lines",
                name=comp.get("label") or comp["name"],   # only the part before " - "
                line=dict(width=1.5, color=color)))
            all_x.append(comp["x"])
            all_y.append(cvals)

        # Observed series (dashed, high-contrast) for the goodness-of-fit comparison
        if self.observed:
            fig.add_trace(go.Scatter(
                x=self.observed["x"], y=self.observed["values"], mode="lines",
                name=f"observed ({self.observed['name']})",
                line=dict(width=1.5, color=theme.c("text"), dash="dot")))
            all_x.append(self.observed["x"])
            all_y.append(self.observed["values"])

        show_legend = comparing or bool(self._legend_name) or bool(self.observed)
        fig.update_layout(
            title=title, xaxis_title="Date", yaxis_title=yaxis_title,
            margin=dict(l=60, r=20, t=80, b=50), template=theme.plotly_template(),
            hovermode="x unified", showlegend=show_legend,
            legend=dict(x=0.99, xanchor="right", y=0.99, yanchor="top",
                        bgcolor=theme.plotly_legend_bg(),
                        bordercolor=theme.c("border"), borderwidth=1))
        # Dark / Mikhail: paper, plot area, font and grid colours from the theme
        # (merged after the layout above so axis settings are kept).
        _ov = theme.plotly_layout_overrides()
        if _ov:
            fig.update_layout(**_ov)

        # Displayed period from the range slider (indices into the main series). Full
        # span when the slider is at its extremes.
        n_main = len(x)
        lo, hi = self._window_bounds()
        windowed = n_main > 0 and (lo > 0 or hi < n_main - 1)
        x_lo = x[lo] if n_main else None
        x_hi = x[hi] if n_main else None

        def _in_window(v):
            if not windowed or x_lo is None:
                return True
            try:
                return x_lo <= v <= x_hi
            except TypeError:
                return True  # non-comparable (category) axis - don't filter

        # Rescale the y-axis to the values visible within the displayed period,
        # across all overlaid series.
        yvals = [v for arr_x, col in zip(all_x, all_y)
                 for xv, v in zip(arr_x, col) if v is not None and _in_window(xv)]
        if yvals:
            ymin, ymax = min(yvals), max(yvals)
            pad = (ymax - ymin) * 0.03 or (abs(ymax) * 0.03) or 1.0
            fig.update_yaxes(range=[ymin - pad, ymax + pad])

        to_axis = lambda v: v.isoformat() if hasattr(v, "isoformat") else v
        if windowed and x_lo is not None:
            try:
                fig.update_xaxes(range=[to_axis(x_lo), to_axis(x_hi)])
            except TypeError:
                pass
        else:
            xvals = [v for arr in all_x for v in arr if v is not None]
            if xvals:
                try:
                    fig.update_xaxes(range=[to_axis(min(xvals)), to_axis(max(xvals))])
                except TypeError:
                    pass  # mixed date/category types - let Plotly auto-range

        # Inline plotly.js so no CDN is needed (the runtime environment may block it).
        html = theme.themed_plot_page(fig.to_html(include_plotlyjs=True, full_html=True))

        # Write to a temp file and load via file:// (the HTML is fully self-contained,
        # so there are no cross-origin subresource requests to worry about).
        tmp = tempfile.NamedTemporaryFile(
            prefix="cwatm_ts_", suffix=".html", delete=False, mode="w", encoding="utf-8")
        tmp.write(html)
        tmp.close()
        self._temp_html = tmp.name
        self.web_view.load(QUrl.fromLocalFile(tmp.name))
