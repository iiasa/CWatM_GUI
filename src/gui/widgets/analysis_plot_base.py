"""Shared base for the Analyse windows that render a Plotly figure to a temp page.

`TimeseriesWindow`, `WatercycleWindow` and `FlowDiagramWindow` all work the same way:
build a figure -> `theme.themed_plot_page(fig.to_html(...))` -> write it to a temp file
(`TempPageMixin._load_temp_page`) -> point a `QWebEngineView` at it, and **Save HTML**
copies that same self-contained file to wherever the user asks. Only the figure and the
suggested file name differ, so everything else lives here. **Save CSV** (Watercycle and
Flow Diagram, bottom-left) writes the numbers behind the plot: the window sets
``_csv_data`` = (meta, header, rows) whenever it rebuilds the figure, and ``_csv_name``
is the suggested file name.

Subclasses set two class attributes and inherit the rest::

    class WatercycleWindow(PlotlyWindowBase):
        _save_fallback = "watercycle"   # used when the csv name yields nothing
        _save_suffix = ""               # appended to the stem ("_sankey" for Sankey)

**Analyse > NetCDF deliberately does not use this.** Its page is served through the
app's `osmtile://` scheme rather than a temp file, and its Save HTML writes the page
*string* (`_page_html`) with its own caveat about basemap tiles not resolving outside
the app - a different shape that would only be obscured by forcing it in here.
"""

import os
import re

from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from src.gui.utils.temp_page import TempPageMixin
from src.gui.utils.window_geometry import GeometryMemoryMixin
from src.gui.utils.gui_log import get_logger

log = get_logger("analysis_plot_base")


def resolved_pathout_dir(widget):
    """Resolved PathOut directory from the main window (found by walking up the
    widget's parent chain), or "". Used as the suggested folder for Save HTML.

    Defined here rather than in `analysis_timeseries` (where it used to live) so this
    module does not have to import that one; `analysis_timeseries` re-exports it, so
    `from ...analysis_timeseries import resolved_pathout_dir` keeps working.
    """
    w = widget.parent() if widget is not None else None
    while w is not None:
        try:
            if hasattr(w, "_resolved_pathout_dir"):
                return w._resolved_pathout_dir() or ""
            w = w.parent()
        except Exception:
            return ""
    return ""


def write_table_csv(path, meta, header, rows):
    """Write a Save-CSV file: ``meta`` (key, value) lines first - basin, station,
    period, like the header rows of a CWatM csv - then a blank line, then the table
    (``header`` + ``rows``). Pure, so it is tested without a window."""
    import csv
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        for key, value in meta:
            writer.writerow([key, value])
        if meta:
            writer.writerow([])
        writer.writerow(header)
        writer.writerows(rows)


class PlotlyWindowBase(TempPageMixin, GeometryMemoryMixin, QDialog):
    """Temp-page lifetime + Save HTML for the Plotly Analyse windows.

    `TempPageMixin` comes first so its `done()` runs before the geometry save, the
    same order the three windows had before they shared a base.
    """

    #: Stem used when the csv's own name yields nothing usable.
    _save_fallback = "plot"
    #: Appended to the stem (e.g. "_sankey" so a Sankey does not overwrite a sunburst).
    _save_suffix = ""
    #: File name Save CSV suggests (in PathOut); the user can change it.
    _csv_name = "plot.csv"
    #: (meta, header, rows) behind the plot on screen - set by the window each time
    #: it rebuilds the figure, so Save CSV always matches the current station and
    #: month window.
    _csv_data = None

    def _make_save_csv_button(self, style):
        """The Save CSV button - same look as Save HTML; the caller places it."""
        from PySide6.QtWidgets import QPushButton
        btn = QPushButton("Save CSV")
        btn.setStyleSheet(style)
        btn.setToolTip("Save the values of this plot as a CSV file "
                       "(for the selected station and period)")
        btn.clicked.connect(self._save_csv)
        self.save_csv_button = btn
        return btn

    def _save_csv(self):
        """Save the table behind the current plot to a user-chosen .csv file."""
        if not self._csv_data:
            QMessageBox.information(self, "Save CSV", "Nothing to save yet.")
            return
        default = os.path.join(resolved_pathout_dir(self), self._csv_name)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save as CSV", default, "CSV files (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        meta, header, rows = self._csv_data
        try:
            write_table_csv(path, meta, header, rows)
        except Exception as e:
            QMessageBox.warning(self, "Save CSV", f"Could not save the file:\n{e}")

    def _save_html(self):
        """Save the currently rendered plot HTML to a user-chosen file."""
        if not self._temp_html or not os.path.exists(self._temp_html):
            QMessageBox.information(self, "Save HTML", "Nothing to save yet.")
            return
        base = os.path.splitext(os.path.basename(str(self.csv_path)))[0]
        base = base or self._save_fallback
        # Point labels contain "@" and "," - keep the suggested name a valid file name.
        base = re.sub(r'[^\w\-.]+', '_', base).strip('_') + self._save_suffix
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
