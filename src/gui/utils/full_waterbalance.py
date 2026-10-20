"""Analyse ▸ Full Waterbalance - the computation behind the window (no Qt).

Ported from ``develop/Toolkit/check_waterbalance/watercycle.ipynb`` (cells no 02-22):
reads a CWatM ``WaterBalance_areasum_daily.csv`` (output ``OUT_TSS_AreaSum_Daily =
WaterBalance``; the smaller ``WaterCycle`` csv works too, without the interception /
soil-layer / soil-per-land-cover parts), detects the stations (rows 2/3) and the options
of the settings file named in row 1, and builds

* the **summary table** of cell no 07: every circle's In / Out / dS / balance error
  in mm/year (``error / In`` above ``tol`` is flagged) plus the 2nd list (circles that
  are not a balance, circles not drawn), and
* **every sunburst below it** (cells no 09-22): Total, Interception and soil, Soil
  layers, Soil per land cover, Groundwater and runoff concentration, MODFLOW layers,
  Evapotranspiration, Potential vs actual ET, Storage change, Snow and glacier, Lakes /
  channels / routing, Lakes and reservoirs, Water demand and use, Demand / supply / use.

Storages are states at the end of the day: the day before the first flux day is the
baseline. Values in mm over the catchment of the station. Keep this in sync with the
notebook when the CWatM water-balance variables change (like ``Watercycles1.py`` for
Analyse ▸ Watercycle).
"""

import csv
import os

import numpy as np
import pandas as pd
import plotly.graph_objects as go


# options with an effect on the water balance: (option, effect, columns which have to be
# in the csv if on)
OPTIONS = [
    ("modflow_coupling", "groundwater by MODFLOW: aquifer + coupling buffer, river/lake/canal leakage, pumping",
     ["Pumping_daily", "modflow_buffer", "capillarUsed"]),
    ("modflow_seepage", "MODFLOW seepage scheme: seepage pond, capillary rise from the aquifer",
     ["sum_seepage", "sum_capRiseFromAquifer"]),
    ("CapillarRise", "capillary rise from groundwater into the soil", ["sum_capRiseFromGW"]),
    ("preferentialFlow", "preferential flow (part of the percolation)", ["prefFlow_GW"]),
    ("includeGlaciers", "glacier melt and rain: input into the routing", ["GlacierMelt", "GlacierRain"]),
    ("usepySnowClim", "snow by pySnowClim (rain on snow, sublimation, ...)", ["packwater"]),
    ("includeRunoffConcentration", "runoff concentration storage", ["gridcell_storage"]),
    ("includeRouting", "river routing: channel storage and evaporation, discharge", []),
    ("inflow", "inflow from outside the basin: input into the routing", ["inflowDay"]),
    ("includeWaterBodies", "lakes and reservoirs", ["lakeResStorage", "lakeResInflowM"]),
    ("useSmallLakes", "small lakes (storage, evaporation)", ["smalllakeStorage", "smallevapWaterBody"]),
    ("includeWaterDemand", "water demand: abstraction, consumption, return flow", ["act_irrWithdrawal", "returnFlow"]),
    ("includeIrrigation", "irrigation: input into the soil, irrigation losses (ET)", ["act_totalIrrConsumption"]),
    ("sectorSourceAbstractionFractions", "abstraction per source (lake, reservoir, channel, groundwater) x sector",
     ["Lake_Irrigation", "Channel_Irrigation", "GW_Irrigation", "Res_Irrigation"]),
    ("limitAbstraction", "True: unmet demand stays unmet; False: unmet demand from fossil groundwater (input)", []),
    ("using_reservoir_command_areas", "reservoir water to command areas (also outside the catchment), canal leakage", []),
    ("reservoir_transfers", "water transfers between reservoirs (not in the WaterCycle csv)", []),
    ("includeWastewater", "wastewater treatment (not in the WaterCycle csv)", []),
    ("includeDesalination", "desalinated water: extra input (not in the WaterCycle csv)", []),
    ("includePitLatrine", "pit latrines -> groundwater (not in the WaterCycle csv)", []),
]
# an option only has an effect if its parent option is on
PARENT = {"modflow_seepage": "modflow_coupling", "useSmallLakes": "includeWaterBodies",
          "reservoir_transfers": "includeWaterBodies",
          "includeIrrigation": "includeWaterDemand", "limitAbstraction": "includeWaterDemand",
          "sectorSourceAbstractionFractions": "includeWaterDemand",
          "using_reservoir_command_areas": "includeWaterDemand", "includeWastewater": "includeWaterDemand",
          "includeDesalination": "includeWaterDemand", "includePitLatrine": "includeWaterDemand"}

# [columns], label, kind, parent (cell no 04) - kind: flux = m3 per day (summed),
# store = m3 state (end - baseline)
VARS = [
    [["Rain"], "Rain", "flux", "Inputs"],
    [["Rain_on_snow"], "Rain on snow", "flux", "Inputs"],
    [["Snow"], "Snow", "flux", "Inputs"],
    [["glacier"], "Glacier", "flux", "Inputs"],
    [["inflowDay"], "Inflow", "flux", "Inputs"],
    [["fossil"], "Fossil groundwater", "flux", "Inputs"],
    [["gw_lateral"], "Lateral groundwater flow", "flux", "Inputs"],
    [["gw_rechargeMoved"], "Recharge moved by the grid", "flux", "Inputs"],
    [["res_transferIn"], "Reservoir transfer in", "flux", "Inputs"],
    [["res_transferOut"], "Reservoir transfer out", "flux", "Outputs"],
    [["Q_m3"], "River discharge at outlet", "flux", "Outputs"],
    [["act_nonIrrConsumption"], "non-Irrigation consumption", "flux", "Outputs"],
    [["unmet_lost"], "Unmet demand lost", "flux", "Outputs"],
    [["leakage_lost"], "Canal leakage lost", "flux", "Outputs"],
    [["ET_all"], "Evapotranspiration", "flux", "Outputs"],
    [["lakeAbstOutside"], "Lake water for users outside the catchment", "flux", "Outputs"],
    [["liftOutside"], "Lift water for users outside the catchment", "flux", "Outputs"],
    [["canalLeakOutside"], "Canal leakage outside the catchment", "flux", "Outputs"],
    [["wwtEvap"], "Wastewater evaporation", "flux", "Outputs"],
    [["wwtSewerExported"], "Wastewater exported", "flux", "Outputs"],
    [["wwtInTreatment"], "Wastewater in treatment", "store", "Storage"],
    [["sum_interceptStor"], "Interception storage", "store", "Storage"],
    [["channelStorage"], "Channel storage", "store", "Storage"],
    [["lakeResStorage"], "Lake/reservoir storage", "store", "Storage"],
    [["smalllakeStorage"], "Small lake storage", "store", "Storage"],
    [["gridcell_storage"], "Runoff concentration storage", "store", "Storage"],
    [["lakeInflowTransit"], "Lake inflow in transit", "store", "Storage"],
    [["storGroundwater"], "Groundwater storage", "store", "Storage"],
    [["modflow_buffer"], "MODFLOW buffer", "store", "Storage"],
    [["sum_soil"], "Soil storage", "store", "Storage"],
    [["pond"], "Seepage pond", "store", "Storage"],
    [["SnowCover"], "Snow storage", "store", "Storage"],
    [["sum_actTransTotal"], "Transpiration", "flux", "Evapotranspiration"],
    [["sum_actBareSoilEvap"], "Bare soil evapo", "flux", "Evapotranspiration"],
    [["sum_interceptEvap"], "Interception evapo", "flux", "Evapotranspiration"],
    [["sum_openWaterEvap"], "Open water evapo", "flux", "Evapotranspiration"],
    [["snowEvap"], "Snow evapo", "flux", "Evapotranspiration"],
    [["addtoevapotrans"], "Irrigation losses", "flux", "Evapotranspiration"],
    [["EvapoChannel"], "Channel evaporation", "flux", "Evapotranspiration"],
    [["EvapWaterBodyM"], "Water bodies evaporation", "flux", "Evapotranspiration"],
    [["smallevapWaterBody"], "Small lakes evaporation", "flux", "Evapotranspiration"],
    [["actTransTotal_forest"], "Forest", "flux", "Transpiration"],
    [["actTransTotal_grasslands"], "Others", "flux", "Transpiration"],
    [["actTransTotal_paddy"], "Paddy", "flux", "Transpiration"],
    [["actTransTotal_nonpaddy"], "non-Paddy", "flux", "Transpiration"],
]

# sunburst colours (cell no 08)
COL = {"In": "#6fa8dc", "Out": "#d2691e", "S+": "#00CC96", "S-": "#7fd8b5", "Balance": "#ffffff"}
TERMCOL = {"Rain": "#60C4DE", "Snow": "#8fd1d1", "Snowfall": "#8fd1d1", "Snow melt": "#8fd1d1", "Inflow": "#1f5fa8",
           "Glacier": "#ADD8E6", "Discharge": "#a0522d", "Evapotranspiration": "#669C53", "Transpiration": "#669C53",
           "Percolation": "#b08d57", "Baseflow": "#8b6f47", "Capillary rise": "#c9a26b",
           "Capillary rise from groundwater": "#c9a26b", "Capillary rise from groundwater (MODFLOW)": "#c9a26b",
           "Runoff": "#4a90c2", "Pumping": "#9b59b6", "Irrigation": "#9b59b6"}
# storage increased = water goes into it (output side); decreased = comes out of it (input side)
RING1 = {"In": "Inputs", "Out": "Outputs", "S+": "Storage (in)", "S-": "Storage (out)"}

# why a circle is not in the 1st list of the summary (cell no 07)
REASON = {"potential": "no balance: potential vs actual, the difference is the deficit (water stress), not an error",
          "storage": "no balance: storage change split into decrease (In) and increase (Out), dS = Out - In by definition",
          "implied storage": "no balance: CWatM has no glacier storage, the difference is the implied glacier change "
                             "(error 0 by definition)"}

SUMMARY_COLUMNS = ["circle", "In mm/yr", "Out mm/yr", "dS mm/yr", "error mm/yr", "error / In", "terms"]
OTHERS_COLUMNS = ["circle", "kind", "why not in the 1st list", "info"]


def _pct(v, total):
    return 100. * v / total if total else 0.


def read_waterbalance_csv(csv_file):
    """Read the csv once: header rows, stations, settings file of row 1 and all values.

    Row 1: header text (with ``settingsfile: <path>``), row 2: xloc, row 3: yloc,
    row 4: column names, row 5+: daily values. Every station is a block of columns
    with the same xloc / yloc."""
    with open(csv_file, encoding="utf-8", errors="ignore", newline="") as f:
        raw = [row for _, row in zip(range(4), csv.reader(f))]
    if len(raw) < 4:
        raise ValueError("Not a CWatM WaterBalance csv (needs 4 header rows).")
    names_all = [c.strip() for c in raw[3][1:]]
    xy = list(zip([c.strip() for c in raw[1][1:]], [c.strip() for c in raw[2][1:]]))
    if not names_all or not xy:
        raise ValueError("Not a CWatM WaterBalance csv (no columns).")
    starts = [i for i in range(len(xy)) if i == 0 or xy[i] != xy[i - 1]]
    nstations = len(starts)
    block = len(names_all) // nstations
    if not all(s == k * block for k, s in enumerate(starts)):
        raise ValueError("The stations of the csv have different numbers of columns.")
    short = [n.replace("_areasum_m3", "").replace("_sum_m3", "").replace("_m3s-1", "")
             for n in names_all[:block]]
    if "cellArea" not in short:
        raise ValueError("The csv has no cellArea column - is it a WaterBalance / WaterCycle csv?")
    full = pd.read_csv(csv_file, skiprows=4, header=None)
    ia = short.index("cellArea")
    stations = [(float(xy[k * block][0]), float(xy[k * block][1]),
                 float(full.iloc[0, 1 + k * block + ia]) / 1e6) for k in range(nstations)]
    settings_file = next((c.split(":", 1)[1].strip() for c in raw[0]
                          if c.strip().lower().startswith("settingsfile:")), "")
    return dict(csv_file=csv_file, short=short, block=block, full=full,
                stations=stations, settings_file=settings_file)


def outlet_station(data):
    """Index of the station with the largest catchment (the outlet)."""
    areas = [s[2] for s in data["stations"]]
    return int(np.argmax(areas))


def compute(data, station=None, min_share=0.0005, tol=1e-3, centre_color="white",
            start_date=None, end_date=None, template=None, layout_overrides=None):
    """Summary table + all part sunbursts for one station.

    Returns a dict: title, period, area_km2, nyears, lon, lat, station, settings_file,
    summary (DataFrame, cell no 07 1st list), others (DataFrame, 2nd list), notes
    (lines printed by cell no 07), figures [(key, fig, notes)] in the notebook order."""
    csv_file = data["csv_file"]
    short, block, full = data["short"], data["block"], data["full"]
    if station is None:
        station = outlet_station(data)
    lon, lat, _ = data["stations"][station]

    c0 = station * block
    df = full.iloc[:, [0] + list(range(1 + c0, 1 + c0 + block))].copy()
    df.columns = ["Date"] + short
    df = df.loc[:, ~df.columns.duplicated()]
    df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y")
    df = df.set_index("Date")
    i_base = 0 if start_date is None else max(
        df.index.get_loc(pd.to_datetime(start_date, format="%d/%m/%Y")) - 1, 0)
    i_end = len(df) - 1 if end_date is None else df.index.get_loc(
        pd.to_datetime(end_date, format="%d/%m/%Y"))
    df = df.iloc[i_base:i_end + 1].copy()
    if len(df) < 2:
        raise ValueError("The csv needs at least two days (a baseline day and one flux day).")
    area = df["cellArea"].iloc[0]
    days = df.index[1:]
    nyears = len(days) / 365.25
    period = f"{days[0]:%d/%m/%Y} to {days[-1]:%d/%m/%Y}"

    # settings file of row 1: all True/False options (any section) and the title
    settings_file = data["settings_file"]
    opts, title = {}, os.path.basename(csv_file)
    notes = []
    if not os.path.isfile(settings_file):
        notes.append(f"settings file of row 1 not found: '{settings_file}' -> options from the csv columns only")
    else:
        with open(settings_file, encoding="utf-8", errors="ignore") as f:
            for line in f:
                s = line.split("#")[0].strip()
                if "=" in s:
                    k, v = [x.strip() for x in s.split("=", 1)]
                    if v.lower() in ("true", "false"):
                        opts[k] = v.lower() == "true"
                    if k.lower() == "title":
                        title = v

    on = {}
    for k, effect, cols in OPTIONS:
        in_csv = all(c in df.columns for c in cols) if cols else None
        val = opts.get(k)
        if val is None:
            val = bool(in_csv) if cols else (k == "includeRouting")
        if k in PARENT and not on[PARENT[k]]:
            on[k] = False
            continue
        if cols and val and not in_csv:
            notes.append(f"{k} is ON but missing in the csv (old CWatM?): "
                         + ", ".join(c for c in cols if c not in df.columns))
        elif cols and not val and in_csv:
            val = True
        on[k] = val
    on["CapillarRise"] = on["CapillarRise"] or on["modflow_coupling"]
    modflow = on["modflow_coupling"]

    # ---- cell no 03: derived series (m3 per day, storages m3)
    def z(name):
        return df[name] if name in df.columns else pd.Series(0., index=df.index)

    if "groundwater_storage_total" in df.columns:
        df["storGroundwater"] = df["groundwater_storage_total"]
    df["Q_m3"] = z("avgdischarge") * 86400.
    if on["includeGlaciers"]:
        df["glacier"] = z("GlacierMelt") + z("GlacierRain")
    if not on["includeRouting"]:
        df["Q_m3"] = (z("runoff_m3") if "runoff_m3" in df.columns else z("runoff")) + z("glacier") + z("returnFlow")
    if on["includeWaterDemand"] and not opts.get("limitAbstraction", False):
        df["fossil"] = z("unmetDemand")
    if on["includeWaterDemand"] and not modflow:
        df["leakage_lost"] = z("leakage")
    if on["includeWaterDemand"] and modflow:
        df["canalLeakOutside"] = z("leakage") - z("leakageIntoGw") - z("leakageIntoRunoff")
    df["landRunoff"] = (z("runoff") + z("gridcell_storage").diff().fillna(0.) - z("baseflow")
                        - z("leakageIntoRunoff") - z("rejected_recharge_interflow"))
    if on["CapillarRise"]:
        if modflow:
            df["capGW"] = z("capillarUsed") if "capillarUsed" in df.columns else \
                z("sum_capRiseFromGW") + z("sum_seepage") - z("sum_capRiseFromAquifer")
        else:
            df["capGW"] = z("sum_capRiseFromGW")
    if on["modflow_seepage"]:
        df["capAq"] = z("sum_capRiseFromAquifer")
        landSto = z("totalSto") if "totalSto" in df.columns else \
            z("SnowCover") + z("sum_interceptStor") + z("sum_soil")
        df["pond"] = landSto - z("SnowCover") - z("sum_interceptStor") - z("sum_soil")
    df["percolation"] = (z("sum_gwRecharge") + z("capAq") - z("riverbedExchangeM") - z("lakebedExchangeM")
                         - z("leakageIntoGw") + (0. if modflow else z("sum_capRiseFromGW")))
    if on["includeWaterDemand"]:
        df["gwAbs"] = z("Pumping_daily") if modflow else z("nonFossilGroundwaterAbs")
        df["channelAbs"] = z("act_SurfaceWaterAbstract") - z("act_bigLakeResAbst") - z("act_bigLakeResAbst_wwt")
    if "act_channelAbstract_Lift" in df.columns:
        df["liftOutside"] = z("act_channelAbstract_Lift") - sum(
            z("Lift_" + s) for s in ["Irrigation", "Domestic", "Industry", "Livestock"])
    if "lakeResAbstOutlet" in df.columns:
        df["lakeAbstOutside"] = (z("lakeResAbstOutlet") - z("act_bigLakeResAbst") - z("act_bigLakeResAbst_wwt")
                                 - z("leakage"))
    df["ET_all"] = z("totalET") + z("EvapWaterBodyM") + z("EvapoChannel") + z("smallevapWaterBody")

    to_mm = 1000. / area

    def flux(col):
        return z(col).iloc[1:].sum() * to_mm

    def change(col):
        s = z(col)
        return (s.iloc[-1] - s.iloc[0]) * to_mm

    # ---- cells no 04/05: components of the overall water cycle (1st row of the summary)
    comp = []
    for cols, label, kind, parent in VARS:
        if not all(c in df.columns for c in cols):
            continue
        if kind == "store":
            v = sum(df[c].iloc[-1] - df[c].iloc[0] for c in cols)
        else:
            v = sum(df[c].iloc[1:].sum() for c in cols)
        if v != 0:
            comp.append([label, parent, kind, v])
    comp = pd.DataFrame(comp, columns=["label", "parent", "kind", "m3"])
    total_input = comp.loc[comp.parent == "Inputs", "m3"].sum()
    total_output = comp.loc[comp.parent == "Outputs", "m3"].sum()
    dstorage = comp.loc[comp.parent == "Storage", "m3"].sum()
    balance = total_input - total_output - dstorage

    # ---- cell no 07: definition of the parts
    gwname = "Groundwater" + (" (MODFLOW + coupling)" if modflow else "")
    PARTS = {
        "Total": dict(
            In=[("Rain", "Rain"), ("Rain on snow", "Rain_on_snow"), ("Snow", "Snow"), ("Glacier", "glacier"),
                ("Inflow", "inflowDay"), ("Fossil groundwater", "fossil"),
                ("Lateral groundwater flow", "gw_lateral"), ("Recharge moved by the grid", "gw_rechargeMoved"),
                ("Reservoir transfer in", "res_transferIn")],
            Out=[("Evapotranspiration", "ET_all"), ("Discharge", "Q_m3"),
                 ("Non-irrigation consumption", "act_nonIrrConsumption"),
                 ("Unmet lost", "unmet_lost"), ("Canal leakage lost", "leakage_lost"),
                 ("Canal leakage outside the catchment", "canalLeakOutside"), ("Reservoir transfer out", "res_transferOut")],
            S=[("Snow cover", "SnowCover"), ("Interception", "sum_interceptStor"), ("Soil moisture", "sum_soil"),
               ("Seepage pond", "pond"), ("Groundwater", "storGroundwater"), ("MODFLOW buffer", "modflow_buffer"),
               ("Runoff concentration", "gridcell_storage"), ("Channels", "channelStorage"),
               ("Lakes/reservoirs", "lakeResStorage"),
               ("Small lakes", "smalllakeStorage"), ("Lake inflow in transit", "lakeInflowTransit")]),
        "Soil (+interception, pond)": dict(
            In=[("Rain", "Rain"), ("Snow melt", "SnowMelt"), ("Ice melt", "IceMelt"),
                ("Irrigation", "act_totalIrrConsumption"),
                ("Capillary rise from groundwater" + (" (MODFLOW)" if modflow else ""), "capGW"),
                ("Capillary rise from aquifer", "capAq")],
            Out=[("Transpiration", "sum_actTransTotal"), ("Bare soil evaporation", "sum_actBareSoilEvap"),
                 ("Interception evaporation", "sum_interceptEvap"),
                 ("Open water + pond evaporation", "sum_openWaterEvap"),
                 ("Runoff", "landRunoff"), ("Percolation", "percolation")],
            S=[("Interception", "sum_interceptStor"), ("Soil moisture", "sum_soil"), ("Seepage pond", "pond")]),
        gwname: dict(
            In=[("Percolation", "percolation"), ("River leakage", "riverbedExchangeM"),
                ("Lake leakage", "lakebedExchangeM"),
                ("Canal leakage", "leakageIntoGw"), ("Lateral groundwater flow", "gw_lateral"),
                ("Recharge moved by the grid", "gw_rechargeMoved")],
            Out=[("Baseflow", "baseflow"), ("Capillary rise", "capGW"), ("Capillary rise from aquifer", "capAq"),
                 ("Rejected recharge", "rejected_recharge_interflow"), ("Pumping", "gwAbs"),
                 ("Exported recharge", "gwRechargeExported_day")],
            S=[("Aquifer", "storGroundwater"), ("MODFLOW buffer", "modflow_buffer")]),
        "Snow": dict(
            In=[("Snowfall", "Snow"), ("Rain on snow", "Rain_on_snow")],
            Out=[("Snow melt", "SnowMelt"), ("Ice melt", "IceMelt"), ("Snow evaporation", "snowEvap")],
            S=[("Snow cover", "SnowCover")]),
        "Lakes/reservoirs": dict(
            In=[("Lake inflow", "lakeResInflowM"), ("Transfer in", "res_transferIn")],
            Out=[("Lake outflow", "lakeResOutflowM"), ("Evaporation", "EvapWaterBodyM"),
                 ("Abstraction", "act_bigLakeResAbst"),
                 ("Canal leakage", "leakage"), ("Lake leakage", "lakebedExchangeM"), ("Transfer out", "res_transferOut")],
            S=[("Lakes/reservoirs", "lakeResStorage")]),
        "Channels (+small lakes)": dict(
            In=[("Runoff", "runoff"), ("Glacier", "glacier"), ("Return flow", "returnFlow"),
                ("Lake outflow", "lakeResOutflowM"), ("Inflow", "inflowDay")],
            Out=[("Discharge", "Q_m3"), ("Channel evaporation", "EvapoChannel"),
                 ("Small lake evaporation", "smallevapWaterBody"),
                 ("Channel abstraction", "channelAbs"), ("River leakage", "riverbedExchangeM"),
                 ("Lake inflow", "lakeResInflowM")],
            S=[("Channels", "channelStorage"), ("Small lakes", "smalllakeStorage"),
               ("Lake inflow in transit", "lakeInflowTransit")]),
        "Routing (channels + lakes)": dict(
            In=[("Runoff", "runoff"), ("Glacier", "glacier"), ("Return flow", "returnFlow"), ("Inflow", "inflowDay"),
                ("Reservoir transfer in", "res_transferIn")],
            Out=[("Discharge", "Q_m3"), ("Channel evaporation", "EvapoChannel"), ("Lake evaporation", "EvapWaterBodyM"),
                 ("Small lake evaporation", "smallevapWaterBody"),
                 ("Surface water abstraction", "act_SurfaceWaterAbstract"),
                 ("Canal leakage", "leakage"), ("River leakage", "riverbedExchangeM"),
                 ("Lake leakage", "lakebedExchangeM"), ("Reservoir transfer out", "res_transferOut")],
            S=[("Channels", "channelStorage"), ("Lakes/reservoirs", "lakeResStorage"),
               ("Small lakes", "smalllakeStorage"), ("Lake inflow in transit", "lakeInflowTransit")]),
        "Water demand": dict(
            In=[("Surface water", "act_SurfaceWaterAbstract"), ("Groundwater", "gwAbs"),
                ("Fossil groundwater", "fossil")],
            Out=[("Irrigation consumption", "act_totalIrrConsumption"),
                 ("Non-irrigation consumption", "act_nonIrrConsumption"),
                 ("Irrigation losses (ET)", "addtoevapotrans"), ("Return flow", "returnFlow"),
                 ("Unmet lost", "unmet_lost")],
            S=[]),
    }
    NEEDS = {"Lakes/reservoirs": "includeWaterBodies", "Channels (+small lakes)": "includeRouting",
             "Routing (channels + lakes)": "includeRouting", "Water demand": "includeWaterDemand"}
    parts = {k: v for k, v in PARTS.items() if on.get(NEEDS.get(k), True)}

    NEWPARTS = {
        "Interception": dict(
            In=[("Rain", "Rain")],
            Out=[("Interception evaporation", "sum_interceptEvap"), ("Throughfall", "sum_throughfall")],
            S=[("Interception", "sum_interceptStor")]),
        "Soil layer 1": dict(
            In=[("Infiltration", "sum_infiltration"), ("Capillary rise from layer 2", "sum_capRise2to1")],
            Out=[("Transpiration", "sum_ta1"), ("Bare soil evaporation", "sum_actBareSoilEvap"),
                 ("Percolation to layer 2", "sum_perc1to2"),
                 ("Infiltration excess to layer 2", "sum_excess1to2"),
                 ("Capillary rise overflow to runoff", "sum_capOverflowRunoff")],
            S=[("Layer 1", "sum_w1")]),
        "Soil layer 2": dict(
            In=[("Percolation from layer 1", "sum_perc1to2"), ("Infiltration excess from layer 1", "sum_excess1to2"),
                ("Capillary rise from layer 3", "sum_capRise3to2"), ("Seepage pond overflow", "pond2soil2")],
            Out=[("Capillary rise to layer 1", "sum_capRise2to1"), ("Transpiration", "sum_ta2"),
                 ("Percolation to layer 3", "sum_perc2to3")],
            S=[("Layer 2", "sum_w2")]),
        "Soil layer 3": dict(
            In=[("Percolation from layer 2", "sum_perc2to3"),
                ("Capillary rise from groundwater" + (" (MODFLOW)" if modflow else ""), "sum_capRiseFromGW"),
                ("Seepage pond overflow", "pond2soil3")],
            Out=[("Capillary rise to layer 2", "sum_capRise3to2"), ("Transpiration", "sum_ta3"),
                 ("Percolation to groundwater", "sum_perc3toGW")],
            S=[("Layer 3", "sum_w3")]),
    }
    SOILLC = []
    for cov, lab in [("forest", "forest"), ("grassland", "grassland"), ("irrPaddy", "paddy"),
                     ("irrNonPaddy", "non-paddy")]:
        if cov + "_inWater" in df.columns and flux(cov + "_inWater") > 0.01:
            SOILLC.append("Soil " + lab)
            NEWPARTS["Soil " + lab] = dict(
                In=[("Throughfall + snow melt", cov + "_inWater"), ("Irrigation", cov + "_irrigation"),
                    ("Capillary rise from groundwater", cov + "_capRise"), ("Seepage into the pond", cov + "_seepage")],
                Out=[("Transpiration", cov + "_transp"), ("Bare soil evaporation", cov + "_bareSoilEvap"),
                     ("Open water + pond evaporation", cov + "_openWaterEvap"),
                     ("Direct runoff", cov + "_directRunoff"),
                     ("Percolation", cov + "_perc3toGW"), ("Preferential flow", cov + "_prefFlow")],
                S=[("Soil" + (" + paddy water" if cov == "irrPaddy" else "")
                    + (" + pond" if on["modflow_seepage"] else ""), cov + "_soilStor")])
    parts.update({k: v for k, v in NEWPARTS.items() if v["S"][0][1] in df.columns})

    if "sum_directRunoff" in df.columns:
        parts["Runoff concentration"] = dict(
            In=[("Direct runoff", "sum_directRunoff"), ("Interflow", "sum_interflow"), ("Baseflow", "baseflow"),
                ("Canal leakage", "leakageIntoRunoff")],
            Out=[("Runoff to the river", "runoff")],
            S=[("Runoff concentration", "gridcell_storage")])
    if on["usepySnowClim"] and "snowSWE" in df.columns:
        df["condensationGain"] = -z("condensation")
        df["depositionGain"] = -z("deposition")
        parts["Snow pack (pySnowClim)"] = dict(
            In=[("Snowfall", "Snow"), ("Rain on snow", "Rain_on_snow"), ("Condensation", "condensationGain"),
                ("Deposition", "depositionGain")],
            Out=[("Melt water out of the pack", "SnowMelt"), ("Sublimation", "sublimation"),
                 ("Evaporation of pack water", "snowwaterevaporation"), ("Snow reset", "snowReset")],
            S=[("Snow (SWE)", "snowSWE"), ("Pack water", "packwater")])
    snowname = "Snow pack (pySnowClim)" if "Snow pack (pySnowClim)" in parts else "Snow"
    if on["includeGlaciers"] and "glacierAreaSnow" in df.columns:
        gl_in = z("glacierAreaSnow") + z("glacierAreaRain")
        gl_out = z("GlacierMelt") + z("GlacierRain")
        df["glacierImplied"] = (gl_in - gl_out).where(df.index > df.index[0], 0.).cumsum()
        parts["Glacier"] = dict(
            In=[("Snowfall on glacier", "glacierAreaSnow"), ("Rain on glacier", "glacierAreaRain")],
            Out=[("Glacier melt", "GlacierMelt"), ("Rain on glacier to the routing", "GlacierRain")],
            S=[("Glacier change (implied)", "glacierImplied")])
    for wb, nm in [("lake", "Lakes"), ("res", "Reservoirs")]:
        if wb + "_storage" in df.columns:
            parts[nm] = dict(
                In=[("Inflow", wb + "_inflow"), ("Transfer in", wb + "_transferIn")],
                Out=[("Outflow", wb + "_outflow"), ("Evaporation", wb + "_evap"), ("Abstraction", wb + "_abstraction"),
                     ("Canal leakage", wb + "_leakage"), ("Lakebed leakage", wb + "_bedExchange"),
                     ("Transfer out", wb + "_transferOut")],
                S=[(nm, wb + "_storage")])
    GWLAYERS = []
    n = 1
    while f"gwlayer{n}_storage" in df.columns:
        L = f"gwlayer{n}_"
        GWLAYERS.append(f"Aquifer layer {n}")
        parts[f"Aquifer layer {n}"] = dict(
            In=([("Recharge", "gwlayer1_recharge")] if n == 1 else []) + [
                ("Lateral inflow", L + "lateral"), ("From the layer above", L + "fromAbove"),
                ("From the layer below", L + "fromBelow")],
            Out=([("Drains (baseflow + capillary rise)", "gwlayer1_drain")] if n == 1 else [])
            + [("Pumping", L + "pumping")],
            S=[(f"Layer {n}", L + "storage")])
        n += 1
    if "totalWaterDemand" in df.columns:
        df["unmetNotSupplied"] = z("unmetDemand") if opts.get("limitAbstraction", False) else 0.
        parts["Demand vs supply"] = dict(
            In=[("Irrigation paddy demand", "irrPaddyDemand"), ("Irrigation non-paddy demand", "irrNonpaddyDemand"),
                ("Domestic demand", "domesticDemand"), ("Industry demand", "industryDemand"),
                ("Livestock demand", "livestockDemand")],
            Out=[("Irrigation withdrawal", "act_irrWithdrawal"), ("Domestic withdrawal", "act_domWithdrawal"),
                 ("Industry withdrawal", "act_indWithdrawal"), ("Livestock withdrawal", "act_livWithdrawal"),
                 ("Not supplied (unmet)", "unmetNotSupplied")],
            S=[])
        parts["Irrigation use"] = dict(
            In=[("Paddy withdrawal", "act_irrPaddyWithdrawal"), ("Non-paddy withdrawal", "act_irrNonpaddyWithdrawal")],
            Out=[("Paddy consumption", "act_paddyConsumption"), ("Non-paddy consumption", "act_nonpaddyConsumption"),
                 ("Return flow", "returnflowIrr"), ("Losses to ET", "addtoevapotrans"),
                 ("Lost (fossil water)", "unmet_lostirr")],
            S=[])
        parts["Non-irrigation use"] = dict(
            In=[("Domestic withdrawal", "act_domWithdrawal"), ("Industry withdrawal", "act_indWithdrawal"),
                ("Livestock withdrawal", "act_livWithdrawal")],
            Out=[("Domestic consumption", "act_domConsumption"), ("Industry consumption", "act_indConsumption"),
                 ("Livestock consumption", "act_livConsumption"), ("Return flow", "returnflowNonIrr"),
                 ("Lost (fossil water)", "unmet_lostNonirr"), ("Pit latrines (to groundwater)", "pitLatrinToGW")],
            S=[])
    DEMANDPARTS = [n for n in ["Demand vs supply", "Irrigation use", "Non-irrigation use"] if n in parts]
    note_ca = on["using_reservoir_command_areas"] and station != outlet_station(data)

    if "lakeResAbstOutlet" in df.columns:
        for name, pre in [("Lakes/reservoirs", None), ("Lakes", "lake"), ("Reservoirs", "res")]:
            if name in parts:
                old = {"act_bigLakeResAbst", "leakage"} if pre is None else {pre + "_abstraction", pre + "_leakage"}
                parts[name]["Out"] = [t for t in parts[name]["Out"] if t[1] not in old] + [
                    ("Abstraction (taken from the lakes)", "lakeResAbstOutlet" if pre is None else pre + "_abstOutlet")]
        for name in ["Routing (channels + lakes)", "Total"]:
            if name in parts:
                parts[name]["Out"] = parts[name]["Out"] + [("Lake water for users outside the catchment",
                                                            "lakeAbstOutside")]
    if "liftOutside" in df.columns:
        for name in ["Water demand", "Total"]:
            if name in parts:
                parts[name]["Out"] = parts[name]["Out"] + [("Lift water for users outside the catchment",
                                                            "liftOutside")]
    if "wwtSewerCollection" in df.columns:
        parts["Wastewater"] = dict(
            In=[("Sewer collection", "wwtSewerCollection")],
            Out=[("Overflow + treated to the river", "wwtOverflowOut"), ("Treated to reservoirs", "wwtSentToRes"),
                 ("Evaporation", "wwtEvap"), ("Exported", "wwtSewerExported")],
            S=[("In treatment", "wwtInTreatment")])
        reuse = [] if "lakeResAbstOutlet" in df.columns else [("Wastewater reuse", "act_bigLakeResAbst_wwt")]
        add = {"Total": dict(Out=[("Wastewater evaporation", "wwtEvap"), ("Wastewater exported", "wwtSewerExported")],
                             S=[("Wastewater in treatment", "wwtInTreatment")]),
               "Soil (+interception, pond)": dict(Out=[("Urban runoff to the sewer", "wwtUrbanLeakage")]),
               "Water demand": dict(Out=[("Collected to the sewer", "wwtSewerCollectedBySoruce")]),
               "Non-irrigation use": dict(Out=[("Collected to the sewer", "wwtSewerCollectedBySoruce")]),
               "Lakes/reservoirs": dict(In=[("Treated wastewater", "wwtSentToRes")], Out=list(reuse)),
               "Reservoirs": dict(In=[("Treated wastewater", "wwtSentToRes")], Out=list(reuse)),
               "Routing (channels + lakes)": dict(In=[("Treated wastewater to reservoirs", "wwtSentToRes")])}
        for name, terms in add.items():
            if name in parts:
                for side, lst in terms.items():
                    parts[name][side] = parts[name][side] + lst

    def part_terms(p):
        # (side, label, value mm): side In / Out / S+ (into storage) / S- (out of storage)
        terms = []
        for side, other, lst in (("In", "Out", p["In"]), ("Out", "In", p["Out"])):
            for label, col in lst:
                if col not in df.columns:
                    continue
                v = flux(col)
                terms.append((side, label, v) if v >= 0 else (other, label + " (neg.)", -v))
        for label, col in p["S"]:
            if col in df.columns:
                v = change(col)
                terms.append(("S+", label, v) if v >= 0 else ("S-", label, -v))
        return terms

    excluded = [[k, "option off: " + NEEDS[k]] for k in PARTS if k not in parts]
    for k in [k for k in parts if k != "Total" and all(abs(v) < 1e-9 for _, _, v in part_terms(parts[k]))]:
        del parts[k]
        excluded.append([k, "all terms 0 over the period (not in this catchment)"])
    GWLAYERS = [n for n in GWLAYERS if n in parts]
    DEMANDPARTS = [n for n in DEMANDPARTS if n in parts]
    SOILLC = [n for n in SOILLC if n in parts]

    ET = {"Land": [("Transpiration forest", "actTransTotal_forest"),
                   ("Transpiration grassland", "actTransTotal_grasslands"),
                   ("Transpiration paddy", "actTransTotal_paddy"), ("Transpiration non-paddy", "actTransTotal_nonpaddy"),
                   ("Bare soil", "sum_actBareSoilEvap"), ("Interception", "sum_interceptEvap"),
                   ("Open water + pond", "sum_openWaterEvap"), ("Snow", "snowEvap"),
                   ("Irrigation losses", "addtoevapotrans")],
          "Water bodies": [("Lakes/reservoirs", "EvapWaterBodyM"), ("Small lakes", "smallevapWaterBody"),
                           ("Channels", "EvapoChannel")]}
    ETPOT = "sum_totalPotET" in df.columns
    if ETPOT:
        et_land = [(l, c) for l, c in ET["Land"] if not l.startswith("Transpiration ")]
        et_land.insert(0, ("Transpiration", "sum_actTransTotal"))
        etpot = {"Actual ET": [(l, flux(c)) for l, c in et_land],
                 "Deficit": [("ET deficit", flux("sum_totalPotET") - flux("totalET"))]}
        trpot = {"Actual transpiration": [(l, flux(c)) for l, c in ET["Land"] if l.startswith("Transpiration ")],
                 "Deficit": [("Transpiration deficit", flux("sum_potTranspiration") - flux("sum_actTransTotal"))]}
    GLACIER = [("Glacier melt", "GlacierMelt"), ("Rain on glacier", "GlacierRain")]
    SOURCES = [("Lake", "Lake"), ("Reservoir", "Res"), ("Channel", "Channel"), ("Groundwater", "GW"),
               ("Desalination", "Desal"), ("Lift area", "Lift"), ("Wastewater reuse", "wwt")]
    SECTORS = ["Irrigation", "Domestic", "Industry", "Livestock"]
    use = {(src, sec): flux(f"{c}_{sec}") for src, c in SOURCES for sec in SECTORS
           if on["sectorSourceAbstractionFractions"] and f"{c}_{sec}" in df.columns}
    withdrawal = flux("act_irrWithdrawal") + flux("act_nonIrrWithdrawal")

    def part_row(name, p):
        t = part_terms(p)
        s = {k: sum(v for side, _, v in t if side == k) for k in ("In", "Out", "S+", "S-")}
        return [name, "balance", s["In"], s["Out"], s["S+"] - s["S-"], s["In"] + s["S-"] - s["Out"] - s["S+"],
                ", ".join(l for l, c in p["In"] + p["Out"] + p["S"] if c in df.columns)]

    rows = [["Water cycle (overall, GUI)", "balance", total_input * to_mm, total_output * to_mm,
             dstorage * to_mm, balance * to_mm,
             ", ".join(comp.loc[comp.parent.isin(["Inputs", "Outputs", "Storage"]), "label"])]]
    for name in ["Total", "Interception", "Soil (+interception, pond)", "Soil layer 1", "Soil layer 2",
                 "Soil layer 3"] + SOILLC + [gwname] + GWLAYERS + ["Runoff concentration"]:
        if name in parts:
            rows.append(part_row(name, parts[name]))
    et_terms = [(l, c) for lst in ET.values() for l, c in lst if c in df.columns and flux(c) > 0]
    et_tot, et_sum = flux("ET_all"), sum(flux(c) for _, c in et_terms)
    rows.append(["Evapotranspiration", "composition", et_tot, et_sum, 0., et_tot - et_sum,
                 ", ".join(l for l, _ in et_terms)])
    if ETPOT:
        for nm, pot, act in [("ET: potential vs actual (land)", "sum_totalPotET", "totalET"),
                             ("Transpiration: potential vs actual", "sum_potTranspiration", "sum_actTransTotal")]:
            fp, fa = flux(pot), flux(act)
            rows.append([nm, "potential", fp, fa, np.nan, np.nan,
                         f"deficit {fp - fa:.2f} mm = {100 * (1 - fa / fp) if fp else 0.:.1f} % of the potential"])
    st_terms = [(l, change(c)) for l, c in parts["Total"]["S"] if c in df.columns]
    st_inc, st_dec = sum(v for _, v in st_terms if v > 0), -sum(v for _, v in st_terms if v < 0)
    rows.append(["Storage change (increase vs decrease)", "storage", st_dec, st_inc, st_inc - st_dec, np.nan,
                 ", ".join(f"{l} {v:+.2f}" for l, v in st_terms)])
    if snowname in parts:
        rows.append(part_row(snowname, parts[snowname]))
    if "Glacier" in parts:
        r = part_row("Glacier", parts["Glacier"])
        r[1] = "implied storage"
        rows.append(r)
    elif on["includeGlaciers"]:
        gl = [(l, flux(c)) for l, c in GLACIER]
        rows.append(["Glacier", "composition", flux("glacier"), sum(v for _, v in gl), 0.,
                     flux("glacier") - sum(v for _, v in gl), ", ".join(f"{l} {v:.2f}" for l, v in gl)])
    for name in ["Lakes/reservoirs", "Lakes", "Reservoirs", "Channels (+small lakes)", "Routing (channels + lakes)",
                 "Water demand"] + DEMANDPARTS + ["Wastewater"]:
        if name in parts:
            rows.append(part_row(name, parts[name]))
    if use:
        rows.append(["Water use: source x sector", "composition", withdrawal, sum(use.values()), 0.,
                     withdrawal - sum(use.values()),
                     ", ".join(sorted({src for src, _ in use})) + " x " + ", ".join(SECTORS)])
    summary = pd.DataFrame(rows, columns=["circle", "kind", "In mm", "Out mm", "dS mm", "balance error mm",
                                          "terms"]).set_index("circle")
    with np.errstate(divide="ignore", invalid="ignore"):
        summary.insert(5, "error / In", summary["balance error mm"] / summary["In mm"].replace(0., np.nan))
    nobal = summary["kind"].isin(list(REASON))
    others = pd.DataFrame(
        [[c, k, REASON[k], t] for c, k, t in zip(summary.index[nobal], summary["kind"][nobal], summary["terms"][nobal])]
        + [[c, "not drawn", r, ""] for c, r in excluded],
        columns=OTHERS_COLUMNS).set_index("circle")
    summary = summary[~nobal]
    summary = pd.concat([(summary[["In mm", "Out mm", "dS mm", "balance error mm"]] / nyears).set_axis(
        ["In mm/yr", "Out mm/yr", "dS mm/yr", "error mm/yr"], axis=1), summary[["error / In", "terms"]]], axis=1)

    notes += [
        "interception / soil layers / soil per land cover: " + (
            "in the csv" if "Soil layer 1" in parts
            else "not in this csv (WaterCycle csv: use OUT_TSS_AreaSum_Daily = WaterBalance)"),
        "In / Out: balance = fluxes; composition = total / sum of the parts (Evapotranspiration, Glacier, "
        "Water use: withdrawal / sum of source x sector); Storage = decrease / increase"]
    if note_ca:
        notes.append("using_reservoir_command_areas: Total, Lakes and Routing of a sub-catchment may not close")
    notes.append(f"values in mm per year (period {period}, {nyears:.2f} years)")
    notes.append(f"threshold |error / In| = {tol:g}: {int((summary['error / In'].abs() > tol).sum())} "
                 "circle(s) above it (red)")

    # ---- cell no 08: sunburst functions
    subtitle = f"{title} | {area / 1e6:.0f} km2 | {period}"

    # heights small enough that one whole sunburst fits in the window on a laptop
    def finish(fig, text, height=460):
        fig.update_layout(title=dict(text=text, x=0.5), height=height,
                          margin=dict(l=10, r=10, t=64, b=8))
        if template:
            fig.update_layout(template=template)
        if layout_overrides:
            fig.update_layout(**layout_overrides)
        return fig

    def sunburst(name, terms, centre_note=""):
        total_in = sum(v for side, _, v in terms if side in ("In", "S-"))
        total_out = sum(v for side, _, v in terms if side in ("Out", "S+"))
        err = total_in - total_out
        centre = f"<b>{name}</b>"
        labels, parents, values, colors, hover = [centre], [""], [0.], [centre_color], [""]
        ids = [centre]
        for side in ("In", "S-", "Out", "S+"):
            kids = [(l, v) for s, l, v in terms if s == side and v > min_share * max(total_in, 1e-12)]
            sv = sum(v for s, _, v in terms if s == side)
            if sv <= 0:
                continue
            sid = f"{name}/{side}"
            ids.append(sid); labels.append(RING1[side]); parents.append(centre); values.append(sv)
            colors.append(COL[side])
            hover.append(f"{sv:.2f} mm<br>{sv / nyears:.1f} mm/yr<br>{_pct(sv, total_in):.2f} % of inputs")
            rest = sv - sum(v for _, v in kids)
            if rest > 0 and kids:
                kids.append(("other (small)", rest))
            for l, v in kids:
                ids.append(f"{sid}/{l}"); labels.append(l); parents.append(sid); values.append(v)
                colors.append(TERMCOL.get(l.replace(" (neg.)", ""), COL[side]))
                hover.append(f"{v:.3f} mm<br>{v / nyears:.1f} mm/yr<br>{_pct(v, total_in):.2f} % of inputs")
        if abs(err) > 0:
            ids.append(f"{name}/err"); labels.append("Balance error"); parents.append(centre); values.append(abs(err))
            colors.append(COL["Balance"])
            hover.append(f"{err:+.4f} mm ({err / total_in if total_in else 0.:+.1e} of inputs)")
        values[0] = sum(v for v, p in zip(values, parents) if p == centre)
        hover[0] = (f"inputs {total_in:.2f} mm ({total_in / nyears:.0f} mm/yr)<br>"
                    f"balance error {err:+.4f} mm{centre_note}")
        fig = go.Figure(go.Sunburst(ids=ids, labels=labels, parents=parents, values=values, branchvalues="total",
                                    marker=dict(colors=colors, line=dict(color="#888", width=0.5)), customdata=hover,
                                    hovertemplate="<b>%{label}</b><br>%{customdata}<extra></extra>",
                                    insidetextorientation="radial"))
        return finish(fig, f"{name}<br><sup>{subtitle}</sup>")

    def composition(name, groups, colors_grp, unit_total=None):
        total = sum(v for lst in groups.values() for _, v in lst)
        centre = f"<b>{name}</b>"
        ids, labels, parents, values = [centre], [centre], [""], [total]
        colors = [centre_color]
        hover = [f"{total:.2f} mm, {total / nyears:.1f} mm/yr" + (f"<br>{unit_total}" if unit_total else "")]
        for grp, lst in groups.items():
            lst = [(l, v) for l, v in lst if v > 0]
            gv = sum(v for _, v in lst)
            if gv <= 0:
                continue
            ids.append(f"{name}/{grp}"); labels.append(grp); parents.append(centre); values.append(gv)
            colors.append(colors_grp.get(grp, "#b0c4de"))
            hover.append(f"{gv:.3f} mm, {gv / nyears:.1f} mm/yr, {_pct(gv, total):.1f} %")
            for l, v in lst:
                ids.append(f"{name}/{grp}/{l}"); labels.append(l); parents.append(f"{name}/{grp}"); values.append(v)
                colors.append(colors_grp.get(l, colors_grp.get(grp, "#b0c4de")))
                hover.append(f"{v:.3f} mm, {v / nyears:.2f} mm/yr, {_pct(v, total):.1f} %")
        values[0] = sum(v for v, p in zip(values, parents) if p == centre)
        fig = go.Figure(go.Sunburst(ids=ids, labels=labels, parents=parents, values=values, branchvalues="total",
                                    marker=dict(colors=colors, line=dict(color="#888", width=0.5)), customdata=hover,
                                    hovertemplate="<b>%{label}</b><br>%{customdata}<extra></extra>",
                                    insidetextorientation="radial"))
        return finish(fig, f"{name}<br><sup>{subtitle}</sup>")

    def side_by_side(flist, key):
        n_ = len(flist)
        fig = go.Figure()
        ann = []
        for i, f in enumerate(flist):
            tr = f.data[0]
            tr.domain = dict(x=[i / n_ + 0.01, (i + 1) / n_ - 0.01], y=[0., 0.92])
            fig.add_trace(tr)
            ann.append(dict(text=f"<b>{f.layout.title.text.split('<br>')[0]}</b>", x=(i + 0.5) / n_, y=1.0,
                            xref="paper", yref="paper", showarrow=False, font=dict(size=14)))
        fig.update_layout(annotations=ann)
        return finish(fig, f"{key}<br><sup>{subtitle}</sup>", height=440)

    def simple_sunburst(key, ids, labels, parents, values, colors, hover, text):
        fig = go.Figure(go.Sunburst(ids=ids, labels=labels, parents=parents, values=values, branchvalues="total",
                                    marker=dict(colors=colors, line=dict(color="#888", width=0.5)), customdata=hover,
                                    hovertemplate="<b>%{label}</b><br>%{customdata}<extra></extra>",
                                    insidetextorientation="radial"))
        return finish(fig, text)

    figures = []        # (key, figure or None, notes), in the order of the notebook

    def add(key, fig, fnotes=None):
        figures.append((key, fig, list(fnotes or [])))

    def sb(name):
        return sunburst(name, part_terms(parts[name]))

    # cell no 09: Total
    add("Total", sb("Total"))
    # cell no 10: Interception and soil
    names = [n for n in ["Interception", "Soil (+interception, pond)"] if n in parts]
    if names:
        add("Interception and soil", side_by_side([sb(n) for n in names], "Interception and soil"))
    # cell no 11: soil layers
    names = [n for n in ["Soil layer 1", "Soil layer 2", "Soil layer 3"] if n in parts]
    if names:
        add("Soil layers", side_by_side([sb(n) for n in names], "Soil layers"))
    else:
        add("Soil layers", None, ["soil layers: not in this csv (WaterCycle csv: use WaterBalance)"])
    # cell no 12: soil per land cover
    if SOILLC:
        add("Soil per land cover", side_by_side([sb(n) for n in SOILLC], "Soil per land cover"))
    else:
        add("Soil per land cover", None, ["soil per land cover: not in this csv (WaterCycle csv: use WaterBalance)"])
    # cell no 13: groundwater and runoff concentration
    names = [n for n in [gwname, "Runoff concentration"] if n in parts]
    fn = [] if "Runoff concentration" in parts else [
        "runoff concentration: not in this csv (WaterCycle csv: use WaterBalance)"]
    if names:
        add("Groundwater and runoff concentration",
            side_by_side([sb(n) for n in names], "Groundwater and runoff concentration"), fn)
    # cell no 14: MODFLOW layers
    if GWLAYERS:
        add("MODFLOW layers", side_by_side([sb(n) for n in GWLAYERS], "MODFLOW layers"),
            [f"lateral groundwater flow into the catchment (all layers): {flux('gw_lateral'):+.4f} mm"])
    else:
        add("MODFLOW layers", None, ["MODFLOW layers: no MODFLOW or not in this csv (WaterCycle csv: use WaterBalance)"])
    # cell no 15: Evapotranspiration - composition
    ETCOL = {"Land": "#669C53", "Water bodies": "#60C4DE"}
    etsum = flux("ET_all")
    centre = "<b>Evapotranspiration</b>"
    ids, labels, parents, values = [centre], [centre], [""], [etsum]
    colors, hover = [centre_color], [f"{etsum:.1f} mm, {etsum / nyears:.0f} mm/yr"]
    for grp, lst in ET.items():
        vals = [(l, flux(c)) for l, c in lst if c in df.columns and flux(c) > 0]
        gv = sum(v for _, v in vals)
        if gv <= 0:
            continue
        ids.append(grp); labels.append(grp); parents.append(centre); values.append(gv); colors.append(ETCOL[grp])
        hover.append(f"{gv:.2f} mm, {gv / nyears:.0f} mm/yr, {_pct(gv, etsum):.1f} %")
        for l, v in vals:
            ids.append(f"{grp}/{l}"); labels.append(l); parents.append(grp); values.append(v)
            colors.append(ETCOL[grp])
            hover.append(f"{v:.2f} mm, {v / nyears:.1f} mm/yr, {_pct(v, etsum):.1f} %")
    values[0] = sum(v for v, p in zip(values, parents) if p == centre)
    add("Evapotranspiration",
        simple_sunburst("Evapotranspiration", ids, labels, parents, values, colors, hover,
                        f"Evapotranspiration<br><sup>{title} | {period}</sup>"),
        [f"ET total {etsum:.2f} mm ({etsum / nyears:.0f} mm/yr), sum of the parts {values[0]:.2f} mm"])
    # cell no 16: potential vs actual
    if ETPOT:
        POTCOL = {"Actual ET": "#669C53", "Actual transpiration": "#669C53", "Deficit": "#e8a33d",
                  "ET deficit": "#e8a33d", "Transpiration deficit": "#e8a33d"}
        pot = pd.DataFrame([[flux("ETRef"), flux("EWRef"), flux("sum_totalPotET"), flux("totalET"),
                             flux("sum_potTranspiration"), flux("sum_actTransTotal")]], index=["mm"],
                           columns=["ETRef", "EWRef", "potential ET", "actual ET (land)", "potential transp.",
                                    "actual transp."]).round(2)
        add("Potential vs actual evapotranspiration", side_by_side(
            [composition("ET: potential vs actual", etpot, POTCOL,
                         unit_total=f"potential ET; reference ET (crops) {flux('ETRef'):.1f} mm"),
             composition("Transpiration: potential vs actual", trpot, POTCOL, unit_total="potential transpiration")],
            "Potential vs actual evapotranspiration"), [pot.to_string()])
    else:
        add("Potential vs actual evapotranspiration", None,
            ["potential ET: not in this csv (WaterCycle csv: use WaterBalance)"])
    # cell no 17: storage change - increase vs decrease
    terms = [(side, l, v) for side, l, v in part_terms(parts["Total"]) if side in ("S+", "S-")]
    inc = sum(v for s, _, v in terms if s == "S+")
    dec = sum(v for s, _, v in terms if s == "S-")
    centre = "<b>Storage change</b>"
    ids, labels, parents, values = [centre], [centre], [""], [inc + dec]
    colors, hover = [centre_color], [f"net {inc - dec:+.2f} mm ({(inc - dec) / nyears:+.0f} mm/yr)"]
    for side, name_, col in (("S+", "Increase", "#00CC96"), ("S-", "Decrease", "#e8a33d")):
        sv = inc if side == "S+" else dec
        if sv <= 0:
            continue
        ids.append(name_); labels.append(name_); parents.append(centre); values.append(sv); colors.append(col)
        hover.append(f"{sv:.2f} mm")
        for s, l, v in terms:
            if s == side and v > 0:
                ids.append(f"{name_}/{l}"); labels.append(l); parents.append(name_); values.append(v)
                colors.append(col)
                hover.append(f"{'+' if side == 'S+' else '-'}{v:.3f} mm")
    values[0] = sum(v for v, p in zip(values, parents) if p == centre)
    add("Storage change",
        simple_sunburst("Storage change", ids, labels, parents, values, colors, hover,
                        f"Storage change: increase vs decrease<br><sup>{title} | {period}</sup>"),
        [f"storage increase {inc:.2f} mm, decrease {dec:.2f} mm, net {inc - dec:+.2f} mm"])
    # cell no 18: snow and glacier
    flist = [sb(snowname)] if snowname in parts else []
    fn = []
    if snowname != "Snow":
        fn.append(f"pySnowClim inside the pack: refrozen {flux('refrozen'):.2f} mm (pack water -> SWE), "
                  f"melt {flux('snowmelt1'):.2f} mm (SWE -> pack water)")
    if "Glacier" in parts:
        flist.append(sb("Glacier"))
        fn.append(f"glacier: implied change {change('glacierImplied'):+.2f} mm over the catchment "
                  "(precipitation on the glacier area - melt - rain to the routing; CWatM has no glacier storage)")
    elif on["includeGlaciers"]:
        flist.append(composition("Glacier", {"Into the routing": [(l, flux(c)) for l, c in GLACIER]},
                                 {"Into the routing": "#ADD8E6", "Rain on glacier": "#60C4DE"},
                                 unit_total=f"glacier area {z('areaGlacier').iloc[-1] / 1e6:.1f} km2"
                                 if "areaGlacier" in df.columns else None))
    else:
        fn.append("Glacier: includeGlaciers off -> not drawn")
    add("Snow and glacier", side_by_side(flist, "Snow and glacier") if flist else None, fn)
    # cell no 19: lakes, channels and routing
    group = ["Lakes/reservoirs", "Channels (+small lakes)", "Routing (channels + lakes)"]
    names = [n for n in group if n in parts]
    missing = [n for n in group if n not in parts]
    add("Lakes, channels and routing",
        side_by_side([sb(n) for n in names], "Lakes, channels and routing") if names else None,
        [f"not drawn (see the 2nd list of the table): {', '.join(missing)}"] if missing else [])
    # cell no 20: lakes and reservoirs separately
    names = [n for n in ["Lakes", "Reservoirs"] if n in parts]
    if names:
        add("Lakes and reservoirs", side_by_side([sb(n) for n in names], "Lakes and reservoirs"))
    else:
        add("Lakes and reservoirs", None, ["lakes / reservoirs separately: includeWaterBodies off or not in this csv "
                                           "(WaterCycle csv: use WaterBalance)"])
    # cell no 21: water demand and water use by source x sector
    if "Water demand" not in parts:
        add("Water demand and water use", None, ["Water demand: not drawn (see the 2nd list of the table)"])
    else:
        flist = [sb("Water demand")]
        fn = []
        if use:
            SRCCOL = {"Lake": "#60C4DE", "Reservoir": "#1f5fa8", "Channel": "#4a90c2", "Groundwater": "#8b6f47",
                      "Desalination": "#2ca02c", "Lift area": "#17becf", "Wastewater reuse": "#8c564b",
                      "Irrigation": "#9b59b6", "Domestic": "#d2691e", "Industry": "#7f7f7f", "Livestock": "#b5a642"}
            srcs = list(dict.fromkeys(src for src, _ in use))
            flist.append(composition("Use by source -> sector",
                                     {src: [(sec, use.get((src, sec), 0.)) for sec in SECTORS] for src in srcs},
                                     SRCCOL, unit_total=f"withdrawal {withdrawal:.2f} mm"))
            flist.append(composition("Use by sector -> source",
                                     {sec: [(src, use.get((src, sec), 0.)) for src in srcs] for sec in SECTORS},
                                     SRCCOL, unit_total=f"withdrawal {withdrawal:.2f} mm"))
            fn.append(f"withdrawal {withdrawal:.3f} mm, sum source x sector {sum(use.values()):.3f} mm, "
                      f"difference {withdrawal - sum(use.values()):+.4f} mm")
            fn.append(pd.DataFrame({sec: {src: use.get((src, sec), 0.) for src in srcs}
                                    for sec in SECTORS}).round(3).to_string())
        else:
            fn.append("source x sector: sectorSourceAbstractionFractions off -> not drawn")
        add("Water demand and water use", side_by_side(flist, "Water demand and water use"), fn)
    # cell no 22: demand vs supply, irrigation use and non-irrigation use
    if DEMANDPARTS:
        add("Demand, supply and use", side_by_side([sb(n) for n in DEMANDPARTS], "Demand, supply and use"),
            ["unmetDemand: " + ("not supplied (limitAbstraction = True)" if opts.get("limitAbstraction", False)
                                else "fossil groundwater, part of the withdrawal (limitAbstraction = False) "
                                     "-> demand = withdrawal")])
    else:
        add("Demand, supply and use", None, ["demand vs supply: includeWaterDemand off or not in this csv "
                                             "(WaterCycle csv: use WaterBalance)"])

    return dict(title=title, period=period, area_km2=area / 1e6, nyears=nyears, lon=lon, lat=lat,
                station=station, settings_file=settings_file, summary=summary, others=others,
                notes=notes, figures=figures, tol=tol)
