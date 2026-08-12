"""What the `[OPTIONS]` switches do — the tooltips of Tools ▸ Change Options.

The window lists the switches by name only, and a name like ``gridSizeUserDefined``
says nothing about what it does or what True and False mean. ``text(option)`` returns
the explanation for one switch (case-insensitive), wrapped for a tooltip; options that
are not in the table simply get none.

Adding one is a single entry in ``_HELP`` — keep the shape used here: a first line
saying what the switch controls, then one line per aspect / per True-False meaning.
"""

import textwrap

_WIDTH = 92          # tooltips get unreadable much beyond this

#: option name (lower-case) -> explanation. Written as paragraphs; the blank-line
#: layout below is what the tooltip shows.
_HELP = {
    "temperatureinkelvin": """
This parameter determines how the model interprets the temperature values provided in your input map stacks (such as TavgMaps, TminMaps, and TmaxMaps).
False: Tells the model that input temperature data is in degrees Celsius (°C).
True: Tells the model that input temperature data is in Kelvin (K).
""",

    "gridsizeuserdefined": """
Precalculated Cell Area: This option determines whether the model uses a precalculated, user-defined map to specify the physical area of each grid cell (in m²) rather than calculating it internally.
Necessity for Lat/Lon Grids: In latitude/longitude coordinate systems, the area of a grid cell is not constant — it becomes smaller as you move from the Equator toward the poles.
Link to Topography Maps: When this is set to True, the model requires a corresponding map defined by the CellArea parameter in the [TOPOP] section (e.g. CellArea = .../cellarea.nc) to account for this variability.
""",

    "calc_evaporation": """
Dynamic Calculation (True): When set to True, CWatM calculates potential evaporation (PET) at each time step using meteorological input data (such as temperature, radiation, wind speed, and humidity). The specific method used for this calculation is determined by the PET_modus setting (e.g. Penman-Monteith, Priestley-Taylor, or Modified Thornthwaite).
Using Pre-calculated Data (False): When set to False, the model bypasses these calculations and instead reads daily reference evaporation data from existing files. In this case, you must provide the file paths for them.
""",

    "includeirrigation": """
Module Activation: This parameter toggles the explicit hydrological simulation for two specific land cover types: "Irrigated land" and "Paddy irrigated land".
Effect of True: The model calculates crop water requirements, agricultural water demand, and withdrawals separately for these areas based on soil moisture and plant phenology.
Effect of False: The area fractions for both paddy and non-paddy irrigated land are automatically merged into the "grassland" category. In this mode, the model does not differentiate irrigation-specific water demands or human influences for these regions.
""",

    "includewaterdemand": """
This switch determines whether human water demand and management processes are incorporated into the hydrological simulation.
Sectoral Coverage: When set to True, the model explicitly calculates and tracks water requirements for four main sectors: irrigation, industry, domestic (households), and livestock.
Integration with the Water Cycle: Enabling this option triggers the model to simulate water withdrawals from various sources, including rivers, lakes, reservoirs, and groundwater storage.
Return Flows: The model will also account for return flows — the portion of withdrawn water that is not consumed and is returned to the river network or groundwater system.
Data Requirements: If enabled, the model will require additional input data paths (such as NetCDF monthly spatial maps for industry and population) typically defined in the [WATERDEMAND] section.
""",

    "usingallocsegments": """
This parameter determines whether the model calculates and compares water demand and water availability for specific regions by aggregating grid cells.
Regional Comparison: When enabled, the model evaluates how much water is available versus how much is needed within defined geographic segments rather than just at the individual grid cell level.
Link to Allocation Map: If set to True, the model requires an allocation map (defined by the allocSegments parameter in the [WATERDEMAND] section) to know how to group these areas for aggregation.
""",

    "limitabstraction": """
This switch governs the source and extent of groundwater abstractions used to satisfy water demands (such as irrigation, industry, or domestic needs).
Renewable vs. Non-renewable: Setting this to True restricts water abstraction to the available renewable groundwater storage.
Including Fossil Groundwater: Setting this to False (the default in some examples) allows the model to satisfy unmet water demands by tapping into non-renewable "fossil" groundwater storage if renewable sources are exhausted.
Unmet Demand Tracking: This setting is closely related to the tracking of unmetDemand, which represents the volume of water needed that cannot be satisfied by available renewable resources.
""",

    "sectorsourceabstractionfractions": """
This parameter determines whether the model uses detailed, sector-specific, and source-specific fractions to satisfy water demand.
Detailed Water Mix: When set to True, the model allows you to define exactly what percentage of a sector's demand (Domestic, Industry, Livestock, or Irrigation) is met by a specific water source (Groundwater, Channels/Rivers, Lakes, or Reservoirs).
Source Restrictions: This is pivotal for modeling complex management scenarios, such as defining a specific "water mix" for a region or restricting certain sectors from using specific sources (for example, forbidding households from using treated wastewater).
Link to Water Demand Section: Enabling this flag tells CWatM to look for specific variables in the [WATERDEMAND] section, such as gwAbstractionFraction_Domestic or swAbstractionFraction_Res_Irrigation, to calculate how abstractions are distributed.
""",

    "calc_environflow": """
This parameter acts as a master switch to enable or disable the internal modules for calculating environmental flow (EF) requirements and indicators.
When set to True: The model will process the parameters defined in the [ENVIRONMENTALFLOW] section. This allows for the calculation of various flow indices, such as MAF (Mean Annual Flow), Q90 (the 90th percentile of flow, often used as a low-flow indicator) and EF_VMF (Variable Monthly Flow requirements).
Interaction with Output: If this is enabled, the model can generate specific maps or time series for these environmental flow requirements as part of the simulation results.
Relationship to Demand: Note that this is distinct from use_environflow (in the [WATERDEMAND] section), which controls whether environmental flow is treated as a component of total water demand during the simulation.
""",

    "modflow_coupling": """
The modflow_coupling switch determines whether CWatM integrates with the MODFLOW groundwater flow model to simulate detailed lateral flows and explicit water table levels.
Setting it to True activates the MODFLOW interface for complex groundwater modelling, whereas False (the default) restricts the model to a simpler linear reservoir approach.
""",

    "use_complex_solver_for_modflow": """
The use_complex_solver_for_modflow parameter is a configuration flag used when CWatM is coupled with the MODFLOW groundwater model. It determines the type of numerical solver used to process groundwater flow calculations during the simulation.
Enabling this option allows the model to utilise a more sophisticated mathematical approach for solving transient groundwater flow equations.
""",

    "includerunoffconcentration": """
This option determines whether the model simulates the process of concentrating runoff from different land cover classes to the edge of a grid cell using topographic and land cover characteristics.
It accounts for variable lag times and temporal diffusion using triangular weighting functions for surface runoff, interflow, and baseflow.
""",

    "includewaterbodies": """
This parameter controls the inclusion of water bodies like lakes and reservoirs in the hydrological simulation.
When enabled, the model differentiates between "big" water bodies connected to the river network and "small" ones that are part of the grid cell's internal runoff concentration.
""",

    "includerouting": """
This switch toggles the kinematic wave routing process, which calculates the movement of water through the river channel network.
If disabled, no downstream river routing is performed across the simulation grid.
""",

    "reservoir_add_info_in_excel": """
This setting controls whether the model reads additional descriptive information for reservoirs and lakes from an external Excel file.
When active, the model utilises the data defined in the Excel_settings_file path.
""",

    "reservoir_releases_in_excel_settings": """
This option determines if specific reservoir release rules or release time series are read from the provided Excel settings file.
It allows for more complex, user-defined management scenarios compared to the standard internal operation schemes.
""",

    "reservoir_transfers": """
This parameter enables or disables the simulation of water transfers between specific reservoirs, such as giving and receiving reservoir pairs.
It is used to model inter-reservoir management and regional water distribution systems.
""",

    "inflow": """
This toggle controls the addition of water discharge from outside the modelled area into specific river locations within the grid.
When enabled, the model requires a directory for inflow files and specified inflow points where external time series data are added to the simulation.
""",

    "writenetcdfstack": """
This reporting option determines whether the spatial output maps are saved as temporal "stacks" within NetCDF files.
This format allows for efficient storage and management of spatiotemporal data over the simulation period.
""",

    "reportmap": """
This switch controls whether the model generates spatial distribution maps of simulated variables as output.
These maps show the value of a variable for every grid cell in the modelling area.
""",

    "reporttss": """
This parameter determines if the model produces time series output for specified gauge points or stations.
The results are typically stored as .csv or .tss files for analysis of variable fluctuations over time at fixed coordinates.
""",

    "calcwaterbalance": """
This debugging option toggles internal calculations to verify the water balance at each time step.
It is used to ensure the conservation of mass within the model by checking that inputs minus outputs equal the change in storage.
""",

    "sumwaterbalance": """
This setting controls whether the model calculates and reports a summation of the overall water balance across the entire simulation duration.
Like calcWaterBalance, it serves as a tool for developers and users to debug and verify model stability.
""",

    "includecrops": """
This parameter determines whether the model explicitly simulates the phenology and water requirements of specific crop types.
When active, it allows for more detailed irrigation demand calculations based on crop-specific growth stages and calendars.
""",

    "use_generalcropnonirr": """
This setting determines if a generally representative crop is used for the non-irrigated land cover class when specific crop distribution data is unavailable.
It serves as a fallback to ensure evapotranspiration and soil moisture processes are still simulated for those areas.
""",

    "use_generalcropirr": """
This option controls the use of a generally representative crop for the irrigated land cover class.
It allows the model to estimate irrigation water demand even if a detailed map of specific irrigated crops is not provided.
""",

    "activate_fallow": """
This toggle switches on the simulation of fallow periods for agricultural land.
When active, it allows the model to represent periods when land is left unplanted, which affects transpiration and water demand.
""",

    "automaticfallowingirr": """
This parameter determines if the model automatically identifies and simulates fallow periods for irrigated land based on regional water availability or seasonal triggers.
It helps represent adaptive agricultural management in response to water scarcity.
""",

    "moveirrfallowtononirr": """
This setting controls whether areas of irrigated land that are currently fallow are treated as non-irrigated (rainfed) grassland.
This shift affects the simulation of soil moisture and actual evapotranspiration for those specific fractions.
""",

    "leftoverirrigatedcropisrainfed": """
This option determines if an irrigated crop is simulated as a rainfed crop for the remainder of its growth cycle if irrigation water demands cannot be met.
This prevents the model from assuming crop failure and instead accounts for continued, though limited, growth using available precipitation.
""",

    "static_irrigation_map": """
This flag determines whether the model uses a constant, fixed map for irrigated areas throughout the entire simulation.
If set to False, the model can utilise dynamic, annual land cover maps to represent changes in agricultural expansion or contraction over time.
""",

    "preferentialflow": """
This parameter determines whether the model will simulate preferential bypass flow, which is the rapid movement of water through macropores that avoids the main soil layers.
Direct Drainage: When enabled, a portion of the water available for infiltration bypasses the soil matrix and drains directly into the groundwater storage.
Soil Saturation Link: The amount of bypass flow is calculated as a function of the relative saturation of the topsoil; as the soil gets wetter, the preferential flow component becomes increasingly important.
Exclusions: This process is specifically not applied to paddy irrigated land (irrPaddy).
Related Parameters: If this switch is True, the model relies on a corresponding empirical shape parameter — often calibrated using the preferentialFlowConstant — to define the exact relationship between soil moisture and the volume of bypassed water.
""",

    "capillarrise": """
Process Inclusion: It acts as an on/off switch for the simulation of upward water movement from groundwater into the soil layers via capillary action.
Hydrological Mechanism: When enabled, CWatM simulates this upward flux, which typically occurs when the groundwater level is close to the surface, specifically within 0 to 5 metres.
Calculation Method: The model estimates the fraction of a grid cell where capillary rise can happen and calculates the flux based on unsaturated conductivity and field capacity.
Interactions: This process is automatically interrupted if the soil is frozen (governed by the FrostIndex threshold).
""",

    "includeglaciers": """
This parameter determines whether glaciers are explicitly included in the hydrological simulation.
OGGM Coupling: When set to True, it activates the coupling between CWatM and the Open Global Glacier Model (OGGM). This allows the model to use dynamic glacier-sourced runoff data — specifically melt and rainfall on glaciers — rather than relying on CWatM's internal, more simplistic snow redistribution method.
Glacierized vs. Non-glacierized Areas: In this mode, OGGM handles the glacier-covered portions of the simulation domain while CWatM handles the non-glacierized portions.
Data Requirement: Enabling this option requires you to define specific input maps in the [GLACIER] section, such as MeltGlacierMaps, PrecGlacierMaps, and fractionGlaciercover.
""",
}


#: Topic groups for Tools ▸ Change Options: related switches are scattered through
#: the file, but people think about them by subject. Order matters (it is the order
#: the groups are shown in); anything not listed lands in "Other".
GROUPS = [
    ("Meteo & evaporation", [
        "TemperatureInKelvin", "calc_evaporation", "usemeteodownscaling",
        "meteomapssamescale", "albedo",
    ]),
    ("Grid & soil", [
        "gridSizeUserDefined", "preferentialFlow", "CapillarRise",
        "includeRunoffConcentration",
    ]),
    ("Snow & glaciers", ["includeGlaciers", "pySnowClim"]),
    ("Water demand", [
        "includeWaterDemand", "includeIrrigation", "usingAllocSegments",
        "limitAbstraction", "sectorSourceAbstractionFractions", "use_environflow",
    ]),
    ("Crops", [
        "includeCrops", "use_GeneralCropnonIrr", "use_GeneralCropIrr",
        "activate_fallow", "automaticFallowingIrr", "moveIrrFallowToNonIrr",
        "leftoverIrrigatedCropIsRainfed", "static_irrigation_map",
    ]),
    ("Groundwater & MODFLOW", [
        "modflow_coupling", "use_complex_solver_for_modflow",
    ]),
    ("Water bodies & routing", [
        "includeRouting", "includeWaterBodies", "useSmallLakes",
        "reservoir_add_info_in_Excel", "reservoir_releases_in_Excel_settings",
        "reservoir_transfers", "inflow", "calc_environflow",
    ]),
    ("Initial conditions", ["load_initial", "save_initial",
                            "load_initial_pySnowClim", "save_initial_pySnowClim"]),
    ("Output & reporting", [
        "reportMap", "reportTss", "writeNetcdfStack",
    ]),
    ("Water balance (debug)", ["calcWaterBalance", "sumWaterBalance"]),
]

#: Every switch this module knows about, in group order - the list "Add option"
#: offers for a settings file that does not define one yet.
KNOWN = [name for _title, names in GROUPS for name in names]

_GROUP_OF = {name.lower(): title for title, names in GROUPS for name in names}


def group_of(option):
    """The topic group of a switch ("Other" when it is not in the table)."""
    return _GROUP_OF.get((option or "").strip().lower(), "Other")


def has(option):
    """Is there an explanation for this switch?"""
    return (option or "").strip().lower() in _HELP


def text(option):
    """The explanation for one switch, wrapped for a tooltip ("" when unknown).

    The option's **name is not repeated** - the tooltip hangs off that very option, so
    it would only push the answer one line further down. Each source paragraph is
    wrapped on its own, so the "False: …" / "True: …" lines and the labelled aspects
    stay separate lines instead of running together."""
    raw = _HELP.get((option or "").strip().lower())
    if not raw:
        return ""
    paragraphs = [p.strip() for p in raw.strip().split("\n") if p.strip()]
    return "\n\n".join(textwrap.fill(p, _WIDTH) for p in paragraphs)
