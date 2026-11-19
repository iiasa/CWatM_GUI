"""Save PNG for the Analyse windows (Preferences ▸ Editor & Dates ▸ PNG dpi).

Plotly windows (Timeseries, Watercycle, Flow Diagram, Chord, Mean Weekly Fluxes,
Annual bars, Flow duration / regime - not Full Waterbalance, by choice): the page
draws every Plotly figure with ``Plotly.toImage`` at ``scale = dpi / 96`` - plotly.js
is inlined in every page, so this works offline and needs no extra package (kaleido
is not bundled). Several figures on one page would be stacked into one image. ``QWebEnginePage.runJavaScript`` cannot wait for a promise, so the page puts
the result into ``window.__cwatmPng`` and Python polls for it - first its length,
then the data URL in 1 MB pieces, because a result of several MB comes back from
``runJavaScript`` as an empty string.

Map windows (NetCDF): Leaflet, not Plotly - the map view is saved as it is on screen
(``save_widget_png``); the dpi only goes into the file's metadata there.

The PNG always carries the dpi in its header, so a word processor places it at the
intended size.
"""

import base64

from src.gui.utils import display_format
from src.gui.utils.gui_log import get_logger

log = get_logger("png_export")

SCREEN_DPI = 96            # what Plotly draws one CSS pixel as
_POLL_MS = 150
_POLL_TRIES = 400          # 60 s - a big Full Waterbalance at high dpi takes a while
_MAX_SIDE = 32000          # Chromium's canvas limit per side (32767), with a margin
NO_FIGURE = "no Plotly figure on this page"
_START_TRIES = 20          # page still loading: try again for up to ~10 s
_RESTART_MS = 500
_CHUNK = 1_000_000         # characters of the data URL per runJavaScript answer


def scale_for(dpi):
    """Plotly toImage scale for a target dpi (150 dpi -> 1.5625)."""
    return max(0.1, float(dpi) / SCREEN_DPI)


def export_js(scale):
    """JavaScript that renders the page's Plotly figure(s) to one PNG data URL in
    ``window.__cwatmPng`` (or ``'ERR:<reason>'``)."""
    return """
(function (scale) {
  window.__cwatmPng = null;
  var fail = function (m) { window.__cwatmPng = 'ERR:' + m; };
  try {
    if (!window.Plotly) { fail('no Plotly figure on this page'); return 'started'; }
    var gds = Array.prototype.slice.call(document.querySelectorAll('.js-plotly-plot'))
      .filter(function (g) { return g.offsetWidth > 0 && g.offsetHeight > 0; });
    if (!gds.length) { fail('no Plotly figure on this page'); return 'started'; }
    Promise.all(gds.map(function (g) {
      return Plotly.toImage(g, {format: 'png', width: g.offsetWidth,
                                height: g.offsetHeight, scale: scale});
    })).then(function (urls) {
      if (urls.length === 1) { window.__cwatmPng = urls[0]; return; }
      var imgs = urls.map(function (u) { var i = new Image(); i.src = u; return i; });
      Promise.all(imgs.map(function (i) {
        return new Promise(function (r) {
          if (i.complete) { r(); } else { i.onload = r; i.onerror = r; }
        });
      })).then(function () {
        var w = Math.max.apply(null, imgs.map(function (i) { return i.naturalWidth; }));
        var h = imgs.reduce(function (s, i) { return s + i.naturalHeight; }, 0);
        if (w > %(max)d || h > %(max)d) {
          fail('the image would be ' + w + ' x ' + h + ' pixels - too large; ' +
               'lower PNG dpi in Preferences > Editor & Dates');
          return;
        }
        var c = document.createElement('canvas');
        c.width = w; c.height = h;
        var ctx = c.getContext('2d');
        var bg = getComputedStyle(document.body).backgroundColor;
        ctx.fillStyle = (!bg || bg === 'transparent' || bg === 'rgba(0, 0, 0, 0)')
          ? '#ffffff' : bg;
        ctx.fillRect(0, 0, w, h);
        var y = 0;
        imgs.forEach(function (i) { ctx.drawImage(i, 0, y); y += i.naturalHeight; });
        window.__cwatmPng = c.toDataURL('image/png');
      });
    }).catch(function (e) { fail(String(e)); });
  } catch (e) { fail(String(e)); }
  return 'started';
})(%(scale)r);
""" % {"scale": float(scale), "max": _MAX_SIDE}


def decode_data_url(data_url):
    """PNG bytes of a ``data:image/png;base64,...`` URL (ValueError if it is not)."""
    prefix = "data:image/png;base64,"
    if not isinstance(data_url, str) or not data_url.startswith(prefix):
        raise ValueError("not a PNG data URL")
    return base64.b64decode(data_url[len(prefix):])


def _write_png(image, path, dpi):
    """Save a QImage as PNG with the dpi in its header. Returns an error text or ''."""
    dpm = int(round(float(dpi) / 0.0254))         # dots per metre
    image.setDotsPerMeterX(dpm)
    image.setDotsPerMeterY(dpm)
    if not image.save(path, "PNG"):
        return f"Could not write {path}"
    return ""


def save_png_bytes(png, path, dpi):
    """Write PNG bytes (from the page) to ``path`` with the dpi in the header."""
    from PySide6.QtGui import QImage
    image = QImage.fromData(png, "PNG")
    if image.isNull():
        return "The page returned no readable image."
    return _write_png(image, path, dpi)


def save_widget_png(widget, path, dpi=None):
    """Save what ``widget`` shows (e.g. a map view) as PNG; '' on success."""
    dpi = dpi or display_format.get_png_dpi()
    image = widget.grab().toImage()
    if image.isNull():
        return "Nothing to save."
    return _write_png(image, path, dpi)


def export_plotly_page(web_view, path, on_done, dpi=None):
    """Render the Plotly figure(s) of ``web_view`` at ``dpi`` (default: the PNG dpi
    setting) and write them to ``path``. ``on_done(error_text)`` is called once -
    '' on success."""
    from PySide6.QtCore import QTimer
    dpi = dpi or display_format.get_png_dpi()
    page = web_view.page()
    state = {"tries": 0, "done": False, "starts": 0}

    def finish(err):
        if not state["done"]:
            state["done"] = True
            on_done(err)

    def got(result):
        """Poll answer: None = still rendering, 'ERR:…', or 'LEN:<n>' = ready."""
        if state["done"]:
            return
        if result is None:
            state["tries"] += 1
            if state["tries"] > _POLL_TRIES:
                finish("The figure took too long to render.")
            else:
                QTimer.singleShot(_POLL_MS, poll)
            return
        if isinstance(result, str) and result.startswith("ERR:"):
            if NO_FIGURE in result and state["starts"] < _START_TRIES:
                # the page is still (re)loading - a resize or a slider move redraws it
                QTimer.singleShot(_RESTART_MS, start)
                return
            finish(result[4:])
            return
        try:
            total = int(str(result)[4:])
        except ValueError:
            finish(f"Unexpected answer from the page: {str(result)[:60]}")
            return
        state["parts"], state["total"] = [], total
        fetch(0)

    def fetch(offset):
        """Read the data URL in pieces - runJavaScript returns an empty result for a
        string of several MB (the stacked Full Waterbalance image)."""
        if offset >= state["total"]:
            data_url = "".join(state["parts"])
            try:
                finish(save_png_bytes(decode_data_url(data_url), path, dpi))
            except Exception as e:
                log.debug("png export failed: %r", data_url[:80], exc_info=True)
                finish(str(e))
            return

        def piece(text):
            if state["done"]:
                return
            if not isinstance(text, str) or not text:
                finish("The image could not be read from the page.")
                return
            state["parts"].append(text)
            fetch(offset + len(text))
        try:
            page.runJavaScript("window.__cwatmPng.substr(%d, %d)" % (offset, _CHUNK),
                               0, piece)
        except RuntimeError:
            finish("The window was closed.")

    def poll():
        try:
            page.runJavaScript(
                "(function (v) { return v === null || v === undefined ? null : "
                "(v.indexOf('ERR:') === 0 ? v : 'LEN:' + v.length); })"
                "(window.__cwatmPng)", 0, got)
        except RuntimeError:           # the window closed meanwhile
            finish("The window was closed.")

    def start():
        state["starts"] += 1
        state["tries"] = 0
        try:
            page.runJavaScript(export_js(scale_for(dpi)), 0,
                               lambda _r: QTimer.singleShot(_POLL_MS, poll))
        except RuntimeError:
            finish("The window was closed.")

    start()
