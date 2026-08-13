# Water Balance Sankey — CWatM Danube 1 min
#
# Builds a Sankey diagrams per station from  CWatM `*_watercycle.csv` output:
#
# 1. Water balance — precipitation -> rain/snow -> soil/groundwater/runoff -> discharge
#    ({station}_sankey.html)
# All values are long-term averages in mm per year over the basin area (36 years).
#
# This script covers the notebook cells 01 through 08 (the water balance diagram).

# cell 01 — imports
import json
import colorsys
import datetime
from calendar import monthrange
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
import plotly.colors as pc
import plotly.graph_objects as go
from IPython.display import display, HTML


# cell 02 — select station and load data
# available stations are derived from qgis_645_Danube1.csv as "G{no}_{Station}"
root = "C:/work/Danube_1min/Morava/sankey/"

#stations_df = pd.read_csv(root + "qgis_645_Danube1.csv", dtype=str).dropna(subset=["no", "Station"])
#stations = ["G" + str(no).zfill(3) + "_" + str(st).strip()
#            for no, st in zip(stations_df["no"], stations_df["Station"])]
#print(f"{len(stations)} stations available, e.g. {stations[:5]}")

stationname = "Morava"
#file = root + stationname + "_watercycle.csv"
file = root + "WaterCycle_areasum_monthtot.csv"

df = pd.read_csv(file, header=None, skiprows=3, dtype=str)


# cell 03 — build balance dict `bal`: long-term average mm/yr per variable
# file row 4: variable names; rows 5..end: daily values in m3
# mm/yr = sum(daily m3) / cellArea_m2 * 1000 / 36 years

var_names   = df.iloc[0, 1:].tolist()
month_dates = pd.to_datetime(df.iloc[1:, 0], format="%d/%m/%Y").reset_index(drop=True)
data        = df.iloc[1:, 1:].apply(pd.to_numeric, errors="coerce").reset_index(drop=True)
cell_area   = float(data.iloc[0, var_names.index("cellArea_sum_m3")])

# if this is monthly the cell_area is summed up by the number of days for this month
is_monthly = month_dates.diff().dropna().dt.days.median() > 20
if is_monthly:
    days_in_month = np.array([monthrange(d.year, d.month)[1] for d in month_dates])
    cell_area = cell_area / days_in_month[0]

# period to average over (instead of the hardcoded 36 years)
startyear = 1990
endyear   = 1999
startdate = datetime.datetime(startyear, 1, 1, 0, 0)
enddate   = datetime.datetime(endyear, 12, 31, 0, 0)

# indexes of start/end within the file's date range (inclusive)
sel       = np.where((month_dates >= startdate) & (month_dates <= enddate))[0]
start_idx = int(sel[0])
end_idx   = int(sel[-1])
nyears    = endyear - startyear + 1

bal = {}
for i, name in enumerate(var_names):
    if isinstance(name, str) and name.strip():
        bal[name.strip()] = data.iloc[start_idx:end_idx + 1, i].sum() / cell_area * 1000 / nyears


# discharge comes as m3/s — convert to same mm/yr basis (× seconds per day)
bal["discharge_m3s-1"] *= 86400.0
bal["avgdischarge_m3s-1"] *= 86400.0

b = bal   # shorthand used in the link definitions below
print(f"{len(bal)} variables loaded — avg discharge {bal['avgdischarge_m3s-1']:.1f} mm/yr")


# cell 04 — color helpers + shared sankey builder (used by both diagrams)
#
# links: [name, source, target, value]                 → gradient source-node → target-node color
#        [name, source, target, value, "#hexcolor"]    → flat link color (e.g. sector colors)
# Links sharing the same source→target pair are spread in hue by HUE_DELTA per step.

HUE_DELTA = 0.033   # ~12° hue spread between links sharing a source→target pair


def css_to_rgb01(hex_color):
    r, g, b = pc.hex_to_rgb(hex_color)
    return r / 255, g / 255, b / 255


def to_hex(r, g, b):
    return "#{:02x}{:02x}{:02x}".format(int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5))


def to_rgba(r, g, b, a=0.65):
    return f"rgba({int(r * 255)},{int(g * 255)},{int(b * 255)},{a})"


def adjust_color(hex_color, delta_h=0.0, delta_l=0.0):
    """Shift hue and/or lightness in HLS space (both deltas in 0..1 units)."""
    r, g, b = pc.hex_to_rgb(hex_color)
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    h = (h + delta_h) % 1.0
    l = max(0.0, min(1.0, l + delta_l))
    r2, g2, b2 = colorsys.hls_to_rgb(h, l, s)
    return to_hex(r2, g2, b2)


# SVG linearGradient injection: Plotly cannot draw per-link source→target gradients,
# so each path.sankey-link gets one via JS in the exported HTML.
# Fill must be set via path.style.fill (Plotly's inline style overrides attribute fill).
GRADIENT_JS = """
<script>
(function() {
  var GRAD = %GRAD%;
  function applyGradients(gd) {
    var svg = gd.querySelector('svg.main-svg');
    if (!svg) return;
    var defs = svg.querySelector('defs');
    if (!defs) {
      defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
      svg.insertBefore(defs, svg.firstChild);
    }
    var paths = Array.from(gd.querySelectorAll('path.sankey-link'));
    paths.forEach(function(path, i) {
      if (i >= GRAD.length) return;
      var id = 'sk-grad-' + i;
      var old = defs.querySelector('#' + id);
      if (old) defs.removeChild(old);
      var grad = document.createElementNS('http://www.w3.org/2000/svg', 'linearGradient');
      grad.setAttribute('id', id);
      grad.setAttribute('gradientUnits', 'objectBoundingBox');
      grad.setAttribute('x1', '0'); grad.setAttribute('y1', '0.5');
      grad.setAttribute('x2', '1'); grad.setAttribute('y2', '0.5');
      [[0, GRAD[i][0]], [1, GRAD[i][1]]].forEach(function(d) {
        var stop = document.createElementNS('http://www.w3.org/2000/svg', 'stop');
        stop.setAttribute('offset', d[0]);
        stop.setAttribute('stop-color', d[1]);
        stop.setAttribute('stop-opacity', '0.65');
        grad.appendChild(stop);
      });
      defs.appendChild(grad);
      path.style.fill = 'url(#' + id + ')';
      path.style.fillOpacity = '1';
    });
  }
  function hookAll() {
    document.querySelectorAll('.js-plotly-plot').forEach(function(gd) {
      applyGradients(gd);
      gd.on('plotly_afterplot', function() { applyGradients(gd); });
    });
  }
  if (document.readyState === 'loading')
    document.addEventListener('DOMContentLoaded', function() { setTimeout(hookAll, 400); });
  else
    setTimeout(hookAll, 400);
})();
</script>
"""


def build_sankey(nodes, links, title, filename, valueformat=".1f",
                 lightness_override=None, width=1050, height=600):
    """Render one sankey diagram, write it to `filename` and display it inline."""
    lightness_override = lightness_override or {}

    node_names  = [n["name"]  for n in nodes]
    node_colors = [n["color"] for n in nodes]
    node_index  = {n["name"]: i for i, n in enumerate(nodes)}
    node_x      = {n["name"]: n["x"] for n in nodes}

    names    = [l[0] for l in links]
    sources  = [l[1] for l in links]
    targets  = [l[2] for l in links]
    values   = [l[3] for l in links]
    override = [l[4] if len(l) > 4 else None for l in links]

    # node totals: incoming sum; outgoing sum for pure sources
    incoming = {n: 0.0 for n in node_names}
    outgoing = {n: 0.0 for n in node_names}
    for s, t, v in zip(sources, targets, values):
        outgoing[s] += v
        incoming[t] += v
    node_total = {n: incoming[n] if incoming[n] > 0 else outgoing[n] for n in node_names}

    # static label: name + integer value (<br>, since \\n is ignored in SVG text)
    node_labels    = [f"{n}<br>{node_total[n]:.0f}" for n in node_names]
    node_hovertext = [f"{n}: {node_total[n]:.0f} mm" for n in node_names]

    # per-link gradient stops from node colors; duplicates of a pair get spread hues
    pair_counts = Counter((s, t) for s, t, ov in zip(sources, targets, override) if ov is None)
    pair_seen   = defaultdict(int)
    link_src_hex, link_tgt_hex = [], []
    for name, s, t, ov in zip(names, sources, targets, override):
        if ov is not None:
            link_src_hex.append(ov)
            link_tgt_hex.append(adjust_color(ov, delta_l=-0.06))
            continue
        n_pair = pair_counts[(s, t)]
        idx = pair_seen[(s, t)]
        pair_seen[(s, t)] += 1
        dh = (idx - (n_pair - 1) / 2) * HUE_DELTA if n_pair > 1 else 0.0
        dl = lightness_override.get(name, 0.0)
        link_src_hex.append(adjust_color(node_colors[node_index[s]], delta_h=dh, delta_l=dl))
        link_tgt_hex.append(adjust_color(node_colors[node_index[t]], delta_h=dh, delta_l=dl))

    # solid blended fallback (shown before the JS fires) + gradient stop pairs
    link_solid, grad_pairs = [], []
    for i, (s, t) in enumerate(zip(sources, targets)):
        sr, sg, sb = css_to_rgb01(link_src_hex[i])
        tr, tg, tb = css_to_rgb01(link_tgt_hex[i])
        link_solid.append(to_rgba((sr + tr) / 2, (sg + tg) / 2, (sb + tb) / 2, 0.5))
        if node_x[s] > node_x[t]:   # backward link: swap stops so gradient reads source→target
            grad_pairs.append([link_tgt_hex[i], link_src_hex[i]])
        else:
            grad_pairs.append([link_src_hex[i], link_tgt_hex[i]])

    fig = go.Figure(go.Sankey(
        orientation="h",
        arrangement="fixed",
        valueformat=valueformat,
        valuesuffix=" mm",
        node=dict(
            label=node_labels,
            color=node_colors,
            x=[n["x"] for n in nodes],
            y=[n["y"] for n in nodes],
            pad=22,
            thickness=18,
            line=dict(color="rgba(80,80,80,0.4)", width=0.8),
            customdata=node_hovertext,
            hovertemplate="%{customdata}<extra></extra>",
        ),
        link=dict(
            source=[node_index[s] for s in sources],
            target=[node_index[t] for t in targets],
            value=values,
            label=names,
            color=link_solid,
            line=dict(width=0),
            customdata=[[s, t] for s, t in zip(sources, targets)],
            hovertemplate=("%{label}: %{value:" + valueformat + "} mm"
                           "<br>%{customdata[0]} → %{customdata[1]}<extra></extra>"),
        ),
        textfont=dict(family="Helvetica, Arial, sans-serif", size=13, color="#222222"),
    ))

    fig.update_layout(
        title=dict(
            text=title,
            x=0.5,
            pad=dict(b=30),
            font=dict(size=20, family="Helvetica, Arial, sans-serif", color="#222222"),
        ),
        font=dict(family="Helvetica, Arial, sans-serif", size=13, color="#333333"),
        hoverlabel=dict(bgcolor="white", bordercolor="#cccccc",
                        font=dict(family="Helvetica, Arial, sans-serif", size=13, color="#333333")),
        paper_bgcolor="white",
        plot_bgcolor="white",
        width=width,
        height=height,
        margin=dict(l=10, r=10, t=100, b=10),
    )

    fig.show()
    return fig


# ---------------------------------------------------------------------------
# Water Balance
# ---------------------------------------------------------------------------

# cell 05 — water balance nodes: name, color, explicit position
# x: 0=left … 1=right   y: 0=top … 1=bottom  (honoured by arrangement="fixed")
# Source-node y also controls where a link enters its target (larger y = lower).
nodes = [
    {"name": "Precipitation",      "color": "#87CEEB", "x": 0.01, "y": 0.28},  # light blue
    {"name": "Rain",               "color": "#6AAFE0", "x": 0.17, "y": 0.30},  # deeper blue
    {"name": "Glacier",            "color": "#c4eded", "x": 0.01, "y": 0.70},  # bluish white
    {"name": "Interception",       "color": "#98D898", "x": 0.30, "y": 0.35},  # light green
    {"name": "Snow",               "color": "#A8E8E8", "x": 0.20, "y": 0.60},  # light turquoise
    {"name": "Soil",               "color": "#C8A478", "x": 0.40, "y": 0.38},  # light brown
    {"name": "Evapotranspiration", "color": "#52B788", "x": 0.90, "y": 0.14},  # medium green
    {"name": "Groundwater",        "color": "#7B9EB8", "x": 0.60, "y": 0.50},  # bluish gray
    {"name": "Runoff",             "color": "#4A86C8", "x": 0.75, "y": 0.75},  # blue
    {"name": "Waterbodies",        "color": "#4A86C8", "x": 0.81, "y": 0.75},  # blue
    {"name": "Discharge",          "color": "#1E5A9C", "x": 0.90, "y": 0.80},  # darker blue
    {"name": "Withdrawal",         "color": "#E05252", "x": 0.73, "y": 0.40},  # soft red
    {"name": "Consumption",        "color": "#B83232", "x": 0.90, "y": 0.40},  # darker red
    {"name": "Other Source",       "color": "#8B6347", "x": 0.65, "y": 0.40},  # warm brown
]


# cell 06 — derived quantities
# split total surface runoff into a rain and a snow share (proportional to net input)
rain = b["Rain_areasum_m3"] - b["sum_interceptEvap_areasum_m3"] - b["sum_openWaterEvap_areasum_m3"]
snow = b["Snow_areasum_m3"] - b["snowEvap_areasum_m3"]
rain_qu = rain / (rain + snow)

# NEW because sum_runoff ist not in watercycle
b["sum_runoff_areasum_m3"] = b["runoff_areasum_m3"] - b["baseflow_areasum_m3"]

b["rain_runoff"] = rain_qu * b["sum_runoff_areasum_m3"]
b["rain_soil"]   = rain - b["rain_runoff"]
b["snow_runoff"] = (1 - rain_qu) * b["sum_runoff_areasum_m3"]
b["snow_soil"]   = snow - b["snow_runoff"]

# tiny epsilons keep zero-valued links visible without distorting the layout
# glacier variables are optional — absent from some watercycle CSVs (default 0)
b["glacier"] = b.get("GlacierMelt_sum_m3", 0.0) + b.get("GlacierRain_sum_m3", 0.0) + 0.001
b["addtoevapotrans_areasum_m3"] = 0.0001

b["runoff"] = b["snow_runoff"] + b["rain_runoff"] + b["baseflow_areasum_m3"] + b["glacier"]


# cell 07 — water balance links: [name, source, target, value (mm/yr)]
links = [
    # precipitation partitioning
    ["Rain",               "Precipitation", "Rain",               b["Rain_areasum_m3"]],
    ["Rain on soil",       "Rain",          "Soil",               b["rain_soil"]],
    ["Evap. Interception", "Rain",          "Interception",       b["sum_interceptEvap_areasum_m3"]],
    ["Evap. Open water",   "Rain",          "Evapotranspiration", b["sum_openWaterEvap_areasum_m3"]],
    ["Evap. Interception", "Interception",  "Evapotranspiration", b["sum_interceptEvap_areasum_m3"]],
    ["Snow",               "Precipitation", "Snow",               b["Snow_areasum_m3"]],
    ["Evap. Snow",         "Snow",          "Evapotranspiration", b["snowEvap_areasum_m3"]],
    ["Snow on soil",       "Snow",          "Soil",               b["snow_soil"]],
    ["Glacier Input",      "Glacier",       "Runoff",             b["glacier"]],
    # soil
    ["Transp. Forest",     "Soil",          "Evapotranspiration", b["actTransTotal_forest_areasum_m3"]],
    ["Transp. Other",      "Soil",          "Evapotranspiration", b["actTransTotal_grasslands_areasum_m3"]],
    ["Transp. Paddy",      "Soil",          "Evapotranspiration", b["actTransTotal_paddy_areasum_m3"]],
    ["Transp. Irrigation", "Soil",          "Evapotranspiration", b["actTransTotal_nonpaddy_areasum_m3"]],
    ["Evap. bare soil",    "Soil",          "Evapotranspiration", b["sum_actBareSoilEvap_areasum_m3"]],
    #["Percolation GW",     "Soil",          "Groundwater",        b["sum_perc3toGW_areasum_m3"]],
    #["Pref. flow",         "Soil",          "Groundwater",        b["sum_gwRecharge_areasum_m3"] - b["sum_perc3toGW_areasum_m3"]],
    ["Percolation GW",     "Soil",          "Groundwater",        b["perc3toGW_GW_areasum_m3"]],
    ["Pref. flow",         "Soil",          "Groundwater",        b["sum_gwRecharge_areasum_m3"] - b["perc3toGW_GW_areasum_m3"]],

    # groundwater & runoff
    ["Capilar Rise",       "Groundwater",   "Soil",               b["sum_capRiseFromGW_areasum_m3"]],
    ["Baseflow",           "Groundwater",   "Runoff",             b["baseflow_areasum_m3"]],
    ["Surface Rain",       "Rain",          "Runoff",             b["rain_runoff"]],
    ["Surface Snow",       "Snow",          "Runoff",             b["snow_runoff"]],
    # waterbodies & discharge
    ["Discharge",          "Runoff",        "Waterbodies",        b["runoff"]],
    ["Evapo Waterbody",    "Waterbodies",   "Evapotranspiration", b["EvapWaterBodyM_areasum_m3"]],
    ["Discharge",          "Waterbodies",   "Discharge",          b["runoff"] - b["EvapWaterBodyM_areasum_m3"] - b["act_SurfaceWaterAbstract_areasum_m3"]],
    # withdrawal
    ["Withdrawal Surface", "Waterbodies",   "Withdrawal",         b["act_SurfaceWaterAbstract_areasum_m3"]],
    ["Withdrawal GW",      "Groundwater",   "Withdrawal",         b["nonFossilGroundwaterAbs_areasum_m3"]],
    ["Withdrawal Fossil GW", "Other Source", "Withdrawal",        b["pot_GroundwaterAbstract_areasum_m3"] - b["nonFossilGroundwaterAbs_areasum_m3"] - b["unmet_lost_areasum_m3"]],
    ["Return flow",        "Withdrawal",    "Discharge",          b["returnFlow_areasum_m3"] - b["unmet_lost_areasum_m3"]],
    ["Evap. Withdrawal",   "Withdrawal",    "Evapotranspiration", b["addtoevapotrans_areasum_m3"]],
    ["Consumption",        "Withdrawal",    "Consumption",        b["act_nonIrrConsumption_areasum_m3"] + b["act_totalIrrConsumption_areasum_m3"]],
]


# cell 08 — render → {station}_sankey.html
fig = build_sankey(
    nodes, links,
    title="Water balance — " + stationname.replace("_", " "),
    filename=stationname + "_sankey.html",
    valueformat=".1f",
    lightness_override={"Percolation GW": -0.10},   # darker than Pref. flow
)
