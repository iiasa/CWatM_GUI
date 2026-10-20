"""
Chord-diagram analysis widget for the CWatM GUI (Analyse ▸ Chord Analysis) - a TEST.

The same window as Analyse ▸ Flow Diagram (header, station navigation, month range
slider, Save HTML / Save CSV - all inherited from ``FlowDiagramWindow``) and the same
actors and flows (``_build_balance_links``), drawn as a **chord diagram**: every actor
is an arc on a circle, every flow a ribbon from the source's arc to the target's.
Plotly has no chord trace, so arcs and ribbons are filled ``Scatter`` polygons.

To remove it again: delete this file and the "Chord Analysis" block (+ its entry in
``_beginner_hidden_actions``) in ``src/gui/components/menu_builder.py``.
"""

import math
import sys

from PySide6.QtWidgets import QFileDialog, QMessageBox
from PySide6.QtCore import Qt

from src.gui.utils import theme
from src.gui.utils.gui_log import get_logger

log = get_logger("analysis_chord")

try:
    import plotly.graph_objects as go
    from src.gui.widgets.analysis_flowdiagram import FlowDiagramWindow, _FD_AVAILABLE, _FD_IMPORT_ERROR
except Exception as _ch_err:  # pragma: no cover - import guard
    _FD_AVAILABLE = False
    _FD_IMPORT_ERROR = f"{type(_ch_err).__name__}: {_ch_err}"
    print(f"Chord analysis unavailable: {_FD_IMPORT_ERROR}", file=sys.stderr)
    FlowDiagramWindow = object

GAP = math.radians(2.0)     # gap between two actors' arcs
R_IN, R_OUT = 1.0, 1.08     # ribbon radius / outer radius of the arcs
STEPS = 40                  # polygon points per arc / bezier
DROPPED = {"Precipitation"}             # its flows = Rain + Snow, already actors
MERGED = {"Runoff": "Waterbodies"}      # Rain/Snow/Baseflow/Glacier go straight there


# Click an actor: 1st click = it, its flows in and out and the actors at their other
# end stay, everything else is hidden; 2nd click = only the flows coming in; 3rd
# click = only the flows going out; 4th click (or a click on a flow / the
# background) = all again. Clicking another actor starts at the 1st step.
# Traces carry meta = [actor] (arc) or [source, target] (ribbon).
_FOCUS_JS = """<script>
(function () {
  var FADE = 0;
  function setup(gd) {
    var focus = null, step = 0, hit = false;      // step 1 in+out, 2 in, 3 out
    function shownFlow(k) {
      if (step === 2) return k[1] === focus;
      if (step === 3) return k[0] === focus;
      return k[0] === focus || k[1] === focus;
    }
    function apply() {
      var op = gd.data.map(function (tr) {
        var m = tr.meta || [];
        if (focus === null) return 1;
        if (m.length === 2) return shownFlow(m) ? 1 : FADE;
        var linked = gd.data.some(function (r) {
          var k = r.meta || [];
          return k.length === 2 && shownFlow(k) && (k[0] === m[0] || k[1] === m[0]);
        });
        return (m[0] === focus || linked) ? 1 : FADE;
      });
      // a hidden shape gets no hover / click either
      Plotly.restyle(gd, {opacity: op, hoverinfo: op.map(function (o) {
        return o > 0 ? 'text' : 'skip'; })});
      // the label of a hidden actor goes too (annotation name = actor)
      var shown = {}, upd = {};
      gd.data.forEach(function (tr, i) {
        var m = tr.meta || [];
        if (m.length === 1) shown[m[0]] = op[i] > 0;
      });
      var status = focus === null ? 'All'
        : focus + ['', ' In and Out', ' In', ' Out'][step];
      (gd.layout.annotations || []).forEach(function (a, i) {
        if (a.name === '__status__') upd['annotations[' + i + '].text'] = status;
        else upd['annotations[' + i + '].visible'] = shown[a.name] !== false;
      });
      Plotly.relayout(gd, upd);
    }
    gd.on('plotly_click', function (ev) {
      hit = true;
      var p = ev && ev.points && ev.points[0];
      var m = p ? (gd.data[p.curveNumber].meta || []) : [];
      if (m.length !== 1) { focus = null; step = 0; }
      else if (m[0] !== focus) { focus = m[0]; step = 1; }
      else { step = (step + 1) % 4; if (step === 0) focus = null; }
      apply();
    });
    // a click beside the shapes (no plotly_click) shows everything again
    gd.addEventListener('click', function () {
      setTimeout(function () {
        if (!hit && focus !== null) { focus = null; step = 0; apply(); }
        hit = false;
      }, 0);
    });
  }
  function wait() {
    var gd = document.querySelector('.plotly-graph-div');
    if (gd && gd.on && gd.data) setup(gd); else setTimeout(wait, 50);
  }
  wait();
})();
</script>"""


def open_chord(parent=None):
    """Prompt for a WaterCycle result .csv file and open the chord window."""
    if not _FD_AVAILABLE:
        QMessageBox.warning(
            parent, "Chord Analysis",
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
        parent, "Open WaterCycle result CSV", start_dir,
        "Water csv (Water*.csv);;CSV result files (*.csv)")
    if not path:
        return
    try:
        win = ChordWindow(path, parent)
        win.exec()
    except Exception as e:
        import traceback
        traceback.print_exc()
        QMessageBox.warning(parent, "Chord Analysis", f"Could not open the file:\n{e}")


def _arc(a0, a1, r):
    return [(r * math.cos(a0 + (a1 - a0) * k / STEPS), r * math.sin(a0 + (a1 - a0) * k / STEPS))
            for k in range(STEPS + 1)]


def _bezier(p0, p1):
    """Quadratic bezier from p0 to p1 with the circle's centre as control point."""
    return [((1 - t) ** 2 * p0[0] + t * t * p1[0], (1 - t) ** 2 * p0[1] + t * t * p1[1])
            for t in (k / STEPS for k in range(STEPS + 1))]


def _rgba(hex_color, alpha):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def build_chord(nodes, links):
    """Chord figure of the balance nodes/links (values mm/yr; <= 0 left out)."""
    # actors left out: the flows from a DROPPED one are left out, the flows of a
    # MERGED one go to / come from the actor it is merged into (a flow between the
    # two disappears)
    links = [[lk[0], MERGED.get(lk[1], lk[1]), MERGED.get(lk[2], lk[2]), lk[3]]
             for lk in links if lk[3] > 0 and lk[1] not in DROPPED and lk[2] not in DROPPED]
    links = [lk for lk in links if lk[1] != lk[2]]
    used = {lk[1] for lk in links} | {lk[2] for lk in links}
    # around the circle in the flow order of the Sankey (left to right, top to bottom)
    nodes = sorted((n for n in nodes if n["name"] in used), key=lambda n: (n["x"], n["y"]))
    color = {n["name"]: n["color"] for n in nodes}
    # an arc carries every flow leaving and arriving at the actor
    size = {n["name"]: 0.0 for n in nodes}
    for _name, s, t, v in (lk[:4] for lk in links):
        size[s] += v
        size[t] += v
    total = sum(size.values())
    fig = go.Figure()
    if not total:
        return fig
    scale = (2 * math.pi - GAP * len(nodes)) / total

    # arc of each actor; its outgoing flows first, then the incoming ones
    start, pos = {}, {}
    a = math.pi / 2                                   # start at the top, clockwise
    for n in nodes:
        start[n["name"]] = a
        pos[n["name"]] = a
        a -= size[n["name"]] * scale + GAP
    order = [n["name"] for n in nodes]
    seg = {}
    for i, lk in sorted(enumerate(links), key=lambda e: order.index(e[1][2])):
        s = lk[1]
        seg[(i, "s")] = (pos[s], pos[s] - lk[3] * scale)
        pos[s] -= lk[3] * scale
    for i, lk in sorted(enumerate(links), key=lambda e: order.index(e[1][1])):
        t = lk[2]
        seg[(i, "t")] = (pos[t], pos[t] - lk[3] * scale)
        pos[t] -= lk[3] * scale

    # ribbons (drawn first, the arcs on top)
    for i, (name, s, t, v) in enumerate(lk[:4] for lk in links):
        a0, a1 = seg[(i, "s")]
        b0, b1 = seg[(i, "t")]
        pts = (_arc(a0, a1, R_IN) + _bezier(_arc(a1, a1, R_IN)[0], _arc(b0, b0, R_IN)[0])
               + _arc(b0, b1, R_IN) + _bezier(_arc(b1, b1, R_IN)[0], _arc(a0, a0, R_IN)[0]))
        fig.add_trace(go.Scatter(
            x=[p[0] for p in pts], y=[p[1] for p in pts], mode="lines", fill="toself",
            fillcolor=_rgba(color[s], 0.55), line=dict(color=_rgba(color[s], 0.8), width=0.5),
            hoveron="fills", hoverinfo="text", meta=[s, t],
            text=f"{name}: {v:.1f} mm<br>{s} → {t}", showlegend=False))

    # arcs + labels
    ann = []
    for n in nodes:
        nm = n["name"]
        a0 = start[nm]
        a1 = a0 - size[nm] * scale
        pts = _arc(a0, a1, R_IN + 0.01) + _arc(a1, a0, R_OUT)
        out_v = sum(lk[3] for lk in links if lk[1] == nm)
        in_v = sum(lk[3] for lk in links if lk[2] == nm)
        fig.add_trace(go.Scatter(
            x=[p[0] for p in pts], y=[p[1] for p in pts], mode="lines", fill="toself",
            fillcolor=n["color"], line=dict(color="rgba(80,80,80,0.5)", width=0.6),
            hoveron="fills", hoverinfo="text", meta=[nm],
            text=f"{nm}<br>in {in_v:.1f} mm, out {out_v:.1f} mm", showlegend=False))
        mid = (a0 + a1) / 2
        cx, cy = math.cos(mid), math.sin(mid)
        ann.append(dict(name=nm, x=1.13 * cx, y=1.13 * cy, text=f"{nm}<br>{max(in_v, out_v):.0f}",
                        showarrow=False, font=dict(size=9, color=theme.c("text")),
                        xanchor="left" if cx > 0.15 else "right" if cx < -0.15 else "center",
                        yanchor="bottom" if cy > 0.15 else "top" if cy < -0.15 else "middle"))

    # top left: what is shown - set by the click script (_FOCUS_JS)
    ann.append(dict(name="__status__", text="All", x=0, y=1, xref="paper", yref="paper",
                    xanchor="left", yanchor="top", showarrow=False,
                    font=dict(size=18, color=theme.c("text"), weight="bold")))
    axis = dict(visible=False, range=[-1.55, 1.55])
    fig.update_layout(
        template=theme.plotly_template(),
        font=dict(family="Helvetica, Arial, sans-serif", size=9),
        autosize=True, margin=dict(l=8, r=8, t=8, b=8), hoverlabel=dict(align="left"),
        xaxis=axis, yaxis=dict(axis, scaleanchor="x", scaleratio=1),
        annotations=ann, showlegend=False)
    _ov = theme.plotly_layout_overrides()
    if _ov:
        fig.update_layout(**{k: v for k, v in _ov.items() if k not in ("xaxis", "yaxis")})
    return fig


class ChordWindow(FlowDiagramWindow):
    """Flow Diagram window with a chord diagram instead of the Sankey."""

    _save_fallback = "chord"
    _save_suffix = "_chord"
    _csv_name = "chord.csv"

    def __init__(self, csv_path, parent=None):
        super().__init__(csv_path, parent)
        title = self.settings_title or str(csv_path)
        self.setWindowTitle(f"\U0001F30A Chord Analysis: {title}")
        # the Sankey's right-click hit test does not know the chord shapes
        self.web_view.setContextMenuPolicy(Qt.NoContextMenu)

    def _init_geometry_memory(self, key):
        return super()._init_geometry_memory("chord")

    def _make_figure(self, nodes, links):
        return build_chord(nodes, links)

    def _show_sankey(self):
        fig = self._build_figure()
        self.sub_label.setText(
            f"{self._station_label()}lon: {self.lon}, lat: {self.lat}"
            f"\n{self._period_text}")
        html = fig.to_html(include_plotlyjs=True, full_html=True,
                           config={"responsive": True, "displaylogo": False})
        fill = ("<style>html,body{height:100%;margin:0;padding:0;overflow:hidden;}"
                ".plotly-graph-div{height:100vh!important;width:100%!important;}</style>")
        html = html.replace("<head>", "<head>" + fill, 1)
        html = html.replace("</body>", _FOCUS_JS + "</body>", 1)
        html = theme.themed_plot_page(html)
        self._load_temp_page(html, "cwatm_chord_")
