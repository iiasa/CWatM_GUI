# Watercycles
# Watercycles are composed of all the daily flows and transformations of water through a certain
# space and time. Watercycles are a tool to visualise CWatM outputs, illustrating the balance of
# inflows, outflows, and storage changes as experienced through a specific space and time.
#
# This tool is suggested for simulations where (cells x days) < 50 million

# %% Load Libraries
import plotly.graph_objects as go

import numpy as np
import datetime
from calendar import monthrange
import pandas as pd

# -----------------------------

# The folder path holding CWatM simulations
#output_folder = "P:/watmodel/CWATM/Regions/Danube_1min/Salzach_pysnowclim/out_wo"
output_folder = "C:/work/Danube_1min/Morava/out_emo-1v3"
name = "Morava"
name ='<b>' + name + '</b>'
csvfile = output_folder + "/WaterCycle_areasum_monthtot.csv"
startyear = 1990
endyear   = 1999

convert = 1_000_000_000
unit = "km3"
startdate = datetime.datetime(startyear, 1, 1, 0, 0)
enddate = datetime.datetime(endyear, 12, 31, 0, 0)

# --------------------- read .csv
df = pd.read_csv(csvfile, skiprows=3)
df.iloc[:, 0] = pd.to_datetime(df.iloc[:, 0], format='%d/%m/%Y')
len_simulation = len(df)
print(len_simulation)

#-------------------------------
month_dates = df.iloc[:, 0].tolist()
startid = 0
endid = len(month_dates)
days_in_month = np.array([monthrange(d.year, d.month)[1] for d in month_dates])

cellAreaSum = df['cellArea_sum_m3'][0] / days_in_month[0]


def month_index(year, month):
    for i, d in enumerate(month_dates):
        if d.year == year and d.month == month:
            return i
    raise ValueError(f"{year}-{month:02d} is outside the data in {csvfile}")

# row positions (inclusive) of the selected start/end month within month_dates
start_idx = month_index(startdate.year, startdate.month)
end_idx = month_index(enddate.year, enddate.month)
if start_idx > end_idx:
    raise ValueError("startdate must not be after enddate")

if start_idx > 0:
    baseline_idx = start_idx - 1
    flux_start = start_idx
else:
    baseline_idx = start_idx
    flux_start = start_idx + 1
if flux_start > end_idx:
    raise ValueError("Select a longer period (at least two months from the start of the csv).")

daysmonth =days_in_month[flux_start:end_idx+1]
#lenyears = len(daysmonth)/12
#-----------------------------------------

Vars = None
WB = None

Vars = [
   # General Water Balance
    [['Rain'], 'Rain', ['M'],'flux', 'Input','All'],
    [['Snow'], 'Snow', ['M'], 'flux', 'Input', 'All'],
    [['avgdischarge'], 'River discharge at outlet', ['M3/S'],'flux', 'Output','All'],
    [['act_nonIrrConsumption'], 'non-Irrigation consumption', 'M', 'flux','Output','All'],
    [['totalET', 'EvapWaterBodyM', 'EvapoChannel'], 'Evapotranspiration', ['M', 'M', 'M'], 'flux', 'Output', 'All'],
    ###[['totalET', 'EvapWaterBodyM', 'smallevapWaterBody', 'EvapoChannel','unmet_lost'], 'Evapotranspiration', ['M', 'M', 'M', 'M3','M'], 'flux', 'Output', 'All'],
    [['sum_interceptStor'], 'Interception storage', ['M'], 'store', 'Storage', 'All'],
    [['channelStorage'], 'Channel storage', ['M3'], 'store', 'Storage', 'All'],

    [['lakeResStorage'], 'Lake_reservoir_storage', ['M3'], 'store', 'Storage', 'All'],
    [['gridcell_storage'], 'gridcell_water_storage', ['M'], 'store', 'Storage', 'All'],
    [['storGroundwater'], 'GW_storage', ['M'], 'store', 'Storage', 'All'],
    [['sum_soil'], 'Soil_storage', ['M'], 'store', 'Storage', 'All'],
    [['SnowCover'], 'Snow_storage', ['M'], 'store', 'Storage', 'All'],
]

# only include glacier melt/rain if this simulation's csv actually has those columns
if {'GlacierMelt_sum_m3', 'GlacierRain_sum_m3'}.issubset(df.columns):
    Vars.append([['GlacierMelt', 'GlacierRain'], 'Glacier', ['M3', 'M3'], 'flux', 'Input', 'All'])

Vars.extend([
    [['sum_actTransTotal'], 'Transpiration', ['M'], 'flux', 'Evapotranspiration', 'All'],
    [['sum_actBareSoilEvap'], 'Bare soil evapo', ['M'], 'flux', 'Evapotranspiration', 'All'],
    [['sum_interceptEvap'], 'Interception evapo', ['M'],'flux', 'Evapotranspiration','All'],
    [['sum_openWaterEvap'], 'Open water evapo', ['M'],'flux', 'Evapotranspiration','All'],
    [['snowEvap'], 'Snow evapo', ['M'],'flux', 'Evapotranspiration','All'],
    [['EvapoChannel'], 'Channel evaporation', ['M'],'flux', 'Evapotranspiration','All'],
    [['EvapWaterBodyM'], 'Water bodies evaporation', ['M'],'flux', 'Evapotranspiration','All'],

    [['actTransTotal_forest'],    'Forest',         ['M'],'flux',    'Transpiration', 'All'],
    [['actTransTotal_grasslands'],'Others',     ['M'],'flux',    'Transpiration', 'All'],
    [['actTransTotal_paddy'],     'Paddy',          ['M'],'flux',    'Transpiration', 'All'],
    [['actTransTotal_nonpaddy'],  'non-Paddy',      ['M'],'flux',    'Transpiration', 'All']
    ])

#-------------------------------------------------------------------
print ("Set up")

keys = [i[4] for i in Vars]
WB = {key: [] for key in keys}
storeall = 0.0

for i, var in enumerate(Vars):
    temp = 0.
    for ii in range(len(var[0])):
        if var[2][ii] == 'M':
            suffix = '_areasum_m3'
        if var[2][ii] == 'M3':
            suffix = '_sum_m3'
        if var[2][ii] == 'M3/S':
            temp = df[var[0][ii] + '_m3s-1'].to_numpy()[flux_start:end_idx]
            discharge= np.mean(temp)
            temp = np.sum(temp * 86400)
        else:
            if var[3] == 'store':
                temp = temp + (df[var[0][ii] + suffix].to_numpy()[end_idx]
                               - df[var[0][ii] + suffix].to_numpy()[startid])
            else:
                temp1 = df[var[0][ii] + suffix].to_numpy()[flux_start:end_idx]
                temp = temp + np.sum(temp1)

    if var[3] == 'store':
        storeall = storeall + temp
    else:
        WB[var[4]].append([var[1], temp, var[3]])

WB['Storage'].append(["", storeall, "Storage"])


# %% Calculate sunburst
# -------------------------------------------------------------------------
print ("calculate")
Title = 'Overall Water Balance'
labels_out, parents_out = [], []

# storage is one aggregate wedge (storeall, computed above) rather than a per-variable
VARS = [[WB['Input'], 'Inputs'],
        [WB['Output'], 'Outputs'],
        [WB['Storage'], 'Storage'],
        [WB['Evapotranspiration'], 'Evapotranspiration'],
        [WB['Transpiration'], 'Transpiration'],
       ]

labels_out, parents_out, values = [], [], []
Total_input, Total_output, Total_store = [], [], []
balance = 0

for VAR in VARS:
    for Var in VAR[0]:
        Y = abs(Var[1])
        if VAR[1] == 'Storage':  Total_store.append(Y)
        if VAR[1] == 'Inputs':   Total_input.append(Y)
        if VAR[1] == 'Outputs':  Total_output.append(Y)
        values.append(Y)
        labels_out.append(Var[0])
        parents_out.append(VAR[1])

total_input = np.sum(Total_input)
total_output = np.sum(Total_output)
total_store = np.sum(Total_store)

discharge_label = 'River discharge at outlet'
balance = 0.
if storeall < 0:
    missq = (total_input + total_store) - total_output
    values[labels_out.index(discharge_label)] += missq
    total_output += missq
    storetext = "Storage (out)"
else:
    balance = total_input - (total_output + total_store)
    storetext = "Storage (into)"

total_total = total_input + total_output + total_store + abs(balance)
values_out = [total_total, total_input, total_output, abs(balance), total_store] + values

# express everything as a per-year average over the selected period
noyears = (end_idx - flux_start + 1) / 12.0
#values_out = [v / noyears for v in values_out]
labels_1st = ['Water balance', 'Inputs', 'Outputs', 'Balance', storetext]
parents_1st = ['', 'Water balance', 'Water balance', 'Water balance', 'Water balance']

labels = labels_1st + labels_out
parents = parents_1st + parents_out

#--------------------------------------------------------------------------
# coloring, hover text and layout follow watercycle_figure_month.py: a per-label
# color lookup, percent-of-parent-group hover text, and an extra discharge/area annotation
# (name-based, not positional, so an optional var like Glacier can shift the label
# order without breaking anything)

label_color = {
    'Water balance': 'white', 'Inputs': '#b0c4de', 'Outputs': '#d2691e', 'Balance': 'white',
    'Rain': '#60C4DE', 'Snow': '#8fd1d1', 'Glacier': '#ADD8E6',
    'River discharge at outlet': 'chocolate', 'non-Irrigation consumption': 'chocolate',
    'Evapotranspiration': '#669C53', 'Transpiration': '#669C53',
    'Bare soil evapo': '#699C4F', 'Interception evapo': '#265312',
    'Open water evapo': '#60C4DE', 'Snow evapo': '#8fd1d1', 'Channel evaporation': '#60C4DE',
    'Forest': '#265312', 'Others': '#81c066', 'Paddy': '#B66934', 'non-Paddy': '#B66934',
}
storage_color = '#00CC96'
colors = [storage_color if lab == storetext else label_color.get(lab, '#b0c4de' if par == 'Inputs' else 'chocolate')
          for lab, par in zip(labels, parents)]

inputs_idx  = {i for i, p in enumerate(parents) if p == 'Inputs'} | {labels.index('Inputs')}
outputs_idx = {i for i, p in enumerate(parents) if p in ('Outputs', 'Evapotranspiration', 'Transpiration')} | {labels.index('Outputs')}
discharge_idx = labels.index(discharge_label)


volume   = []
fraction = []
otherunit = []
for part, v in enumerate(values_out):
    if part == 0:
        fra1 = 1.
    elif part in inputs_idx:
        fra1 = v / values_out[1]
    elif part in outputs_idx:
        fra1 = v / values_out[2]
    else:
        fra1 = v / (values_out[0] / 2)

    prec = 1
    if fra1 < 0.1:   prec = 2
    if fra1 < 0.01:  prec = 3
    if fra1 < 0.001: prec = 4
    prec1 = 2
    if v < 0.1:   prec = 3
    if v < 0.01:  prec = 4
    if v < 0.001: prec = 5

    fraction.append("Percent: {:.{prec}%}".format(fra1, prec=prec))
    volume.append("Volume: {:.{prec1}} km<sup>3</sup>".format(v / convert,prec1=prec1))

    if part == discharge_idx:
        otherunit.append("Discharge: {:.2f} m<sup>3</sup>s".format(discharge))
    else:
        otherunit.append("mm/year: {:.0f} mm".format(v/cellAreaSum*1000/noyears))  #lenyears

fraction  = np.array(fraction)
fraction[0] = " "
volume    = np.array(volume)
otherunit = np.array(otherunit)

date_range_str = f"from {month_dates[start_idx].month}/{month_dates[start_idx].year} to {month_dates[end_idx].month}/{month_dates[end_idx].year}"
area_km2 = cellAreaSum / 1_000_000
addinfo = np.full(len(values_out), '', dtype='<U100')
addinfo[0] = "Basin: Morava<br>Area: " + f"{area_km2:.0f}" + " km<sup>2</sup><br>" + date_range_str

customdata = np.stack([fraction, otherunit, volume, addinfo], axis=-1)

hovertemplate = [
    "<b>%{label}</b><br>%{customdata[3]} <extra></extra>" if p == ''
    else ("<b>%{label}</b><br>%{customdata[2]}<br>%{customdata[1]}<br>"
          "%{customdata[0]}<extra><b>%{parent}</b><br>Percent: %{percentParent:.1%} </extra>")
    for p in parents
]

# %% Make figure
#--single sunburst for the selected period--------------
fig = go.Figure(
    go.Sunburst(
        customdata=customdata,
        labels=labels,
        parents=parents,
        values=values_out,
        branchvalues='total',
        marker=dict(colors=colors),
        maxdepth=4,
        hovertemplate=hovertemplate,
    )
)

fig.update_layout(
    title_text=  "CWatM:  " + name + " - " + date_range_str,
    template="presentation",
    height=800,
    hoverlabel=dict(align='left'),
)

# Save the sunburst figure as a standalone HTML file
#html_path = "C:/work/Danube_1min/Morava/watercycles/sunburst.html"
#fig.write_html(html_path, include_plotlyjs="cdn")
#print("Saved sunburst to", html_path)

fig.show()
