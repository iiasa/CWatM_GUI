"""Shared base for the Analyse windows that render a Plotly figure to a temp page.

`TimeseriesWindow`, `WatercycleWindow` and `FlowDiagramWindow` all work the same way:
build a figure -> `theme.themed_plot_page(fig.to_html(...))` -> write it to a temp file
(`TempPageMixin._load_temp_page`) -> point a `QWebEngineView` at it, and **Save HTML**
copies that same self-contained file to wherever the user asks. Only the figure and the
suggested file name differ, so everything else lives here.

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


class PlotlyWindowBase(TempPageMixin, GeometryMemoryMixin, QDialog):
    """Temp-page lifetime + Save HTML for the Plotly Analyse windows.

    `TempPageMixin` comes first so its `done()` runs before the geometry save, the
    same order the three windows had before they shared a base.
    """

    #: Stem used when the csv's own name yields nothing usable.
    _save_fallback = "plot"
    #: Appended to the stem (e.g. "_sankey" so a Sankey does not overwrite a sunburst).
    _save_suffix = ""

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
