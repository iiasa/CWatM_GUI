"""Temp-file lifetime for the Plotly viewer windows.

The Analyse plot windows (Timeseries, Watercycle, Flow Diagram) render by writing a
**self-contained** HTML page - `plotly.js` is inlined, so one page is several MB - to a
temporary file and pointing their `QWebEngineView` at it via `file://`.

That page is rebuilt on **every** redraw: a station change, a colour/scale toggle, and
in particular each tick of the debounced month/range slider. Writing the new file
without removing the old one left one multi-MB orphan per redraw in the user's temp
directory, for the lifetime of the machine.

`TempPageMixin` owns that lifetime: `_load_temp_page()` deletes the page it replaces
before writing the next one, and the window discards its last page when it closes. Mix
it in **before** `GeometryMemoryMixin`/`QDialog` so `done()` chains through to both:

    class TimeseriesWindow(TempPageMixin, GeometryMemoryMixin, QDialog):
        ...
        self._load_temp_page(html, "cwatm_ts_")

Cleanup hangs off `done()` rather than `closeEvent()` because that is the funnel a
QDialog always passes through - the window's X button reaches it via
`QDialog::closeEvent` -> `reject()`, and the Escape key reaches it directly, without
ever raising a close event.
"""

import os
import tempfile

from PySide6.QtCore import QUrl

from src.gui.utils.gui_log import get_logger

log = get_logger("temp_page")


class TempPageMixin:
    """Write rendered HTML to a temp file, keeping at most one alive per window."""

    _temp_html = None

    def _load_temp_page(self, html, prefix):
        """Write ``html`` to a fresh temp file and load it into ``self.web_view``.

        The page this one replaces is deleted first. Returns the new file's path.
        """
        previous = self._temp_html
        tmp = tempfile.NamedTemporaryFile(
            prefix=prefix, suffix=".html", delete=False, mode="w", encoding="utf-8")
        try:
            tmp.write(html)
        finally:
            tmp.close()
        self._temp_html = tmp.name
        # Only after the replacement exists - a failed write must not leave the
        # window with neither page.
        _remove_page(previous)
        self.web_view.load(QUrl.fromLocalFile(tmp.name))
        return tmp.name

    def _discard_temp_page(self):
        """Delete the window's current temp page, if any."""
        _remove_page(self._temp_html)
        self._temp_html = None

    def done(self, result):
        self._discard_temp_page()
        super().done(result)


def _remove_page(path):
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        # A page still held open by the render process is not worth a dialog; the
        # OS reclaims it with the temp directory.
        log.debug("temp page not removed: %s", path, exc_info=True)
