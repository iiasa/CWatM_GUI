"""Which CWatM model variables are arrays, and what index an output value needs.

``OUT_MAP_Daily = actualET`` is not a valid output: ``actualET`` is allocated per land
cover, so it has to be written ``actualET[1]``. This module holds that knowledge once,
for the two places that need it:

* **Settings ▸ Check settingsfile** (`main_window`) - flags a missing/extra/invalid
  index in an existing output line (`dim_problem`);
* **Tools ▸ Add output variables** (`output_variables_window`) - offers the valid
  indices by **name** ("1 - grassland") instead of leaving the user to guess
  (`index_options`).

The sets are **mirrored read-only** from the allocation lists in
``cwatm/hydrological_modules/`` (the hard rule forbids editing them):

===========  ================================================  ==================
set          source                                            shape
===========  ================================================  ==================
``DIM6``     ``landcoverType.py`` landcoverAll + landcoverVars  ``(6, cells)``
``DIM4``     ``landcoverType.py`` landcoverVarsSoil + w1/w2/w3  ``(4, cells)``
``DIM3X4``   ``landcoverType.py`` soilVars                      ``(3, 4, cells)``
``DIM3``     ``soil.py`` soilDepthLayer                         ``(3, cells)``
``DIMCROP``  ``evaporation.py`` crop lists                      ``(len(Crops), cells)``
===========  ================================================  ==================

A variable that is **not** in any of these sets is never flagged - other modules
allocate 2-D variables this module does not track.
"""

DIM6 = frozenset((
    'fracVegCover', 'interceptStor', 'availWaterInfiltration', 'interceptEvap',
    'directRunoff', 'openWaterEvap', 'irrTypeFracOverIrr', 'fractionArea',
    'totAvlWater', 'cropKC', 'cropKC_landCover', 'effSatAt50',
    'effPoreSizeBetaAt50', 'rootZoneWaterStorageMin',
    'rootZoneWaterStorageRange', 'totalPotET', 'potTranspiration',
    'soilWaterStorage', 'infiltration', 'actBareSoilEvap', 'landSurfaceRunoff',
    'actTransTotal', 'gwRecharge', 'gwRecharge2', 'interflow', 'actualET',
    'pot_irrConsumption', 'act_irrConsumption', 'irrDemand', 'topWaterLayer',
    'perc3toGW', 'capRiseFromGW', 'netPercUpper', 'netPerc', 'prefFlow'))
DIM4 = frozenset((
    'arnoBeta', 'rootZoneWaterStorageCap', 'rootZoneWaterStorageCap12',
    'perc1to2', 'perc2to3', 'theta1', 'theta2', 'theta3', 'w1', 'w2', 'w3'))
DIM3X4 = frozenset(('adjRoot', 'perc', 'capRise', 'rootDepth', 'storCap'))
DIM3 = frozenset(('soildepth',))
DIMCROP = frozenset((
    'irrM3_Paddy_month_segment', 'irr_Paddy_month', 'irr_crop',
    'irr_crop_month', 'irrM3_crop_month_segment', 'ratio_a_p_nonIrr',
    'ratio_a_p_Irr', 'fracCrops_IrrLandDemand', 'fracCrops_Irr',
    'areaCrops_Irr_segment', 'areaCrops_nonIrr_segment',
    'fracCrops_nonIrrLandDemand', 'fracCrops_nonIrr', 'activatedCrops',
    'monthCounter', 'currentKC', 'totalPotET_month', 'PET_cropIrr_m3',
    'actTransTotal_month_Irr', 'actTransTotal_month_nonIrr', 'currentKY',
    'Yield_Irr', 'Yield_nonIrr', 'actTransTotal_crops_Irr',
    'actTransTotal_crops_nonIrr', 'PotET_crop', 'PotETaverage_crop_segments',
    'totalPotET_month_segment', 'ET_crop_nonIrr', 'ET_crop_Irr',
    'ratio_a_p_nonIrr_daily', 'ratio_a_p_Irr_daily'))

# The land-cover order CWatM allocates in (landcoverType.py landcoverAll).
LANDCOVER = ('forest', 'grassland', 'irrPaddy', 'irrNonPaddy', 'sealed', 'water')
SOIL_LAYERS = ('top soil layer', 'middle soil layer', 'bottom soil layer')

HINT6 = "0..5 = forest, grassland, irrPaddy, irrNonPaddy, sealed, water"
HINT4 = "0..3 = forest, grassland, irrPaddy, irrNonPaddy"
HINT3 = "0..2 = soil layer"

# How many crop indices the picker offers before falling back to "Other…" (the crop
# list is user-defined in the settings Excel sheet, so there is no upper bound).
_CROP_OFFERED = 10


def kind_of(base):
    """``'landcover6' | 'landcover4' | 'soil3' | 'soil3x4' | 'crop' | None``."""
    if base in DIM6:
        return 'landcover6'
    if base in DIM4:
        return 'landcover4'
    if base in DIM3:
        return 'soil3'
    if base in DIM3X4:
        return 'soil3x4'
    if base in DIMCROP:
        return 'crop'
    return None


def needs_index(base):
    """True when an output value of ``base`` is invalid without an index."""
    return kind_of(base) is not None


def hint_of(base):
    """One line saying what the index means (''), for a tooltip."""
    kind = kind_of(base)
    if kind == 'landcover6':
        return HINT6
    if kind == 'landcover4':
        return HINT4
    if kind == 'soil3':
        return HINT3
    if kind == 'soil3x4':
        return f"two indices: [soil layer][land cover] - {HINT3}, {HINT4}"
    if kind == 'crop':
        return "one index: the crop number from the settings crop table"
    return ""


def index_options(base):
    """The indices ``base`` can take, as ``[(suffix, label, tooltip)]``.

    ``suffix`` is what to append to the variable name (``'[1]'``, ``'[0][2]'``); a
    suffix of **None** means "ask the user for a number" (per-crop variables, whose
    count comes from the settings crop table). Empty list = no index needed."""
    kind = kind_of(base)
    if kind in ('landcover6', 'landcover4'):
        n = 6 if kind == 'landcover6' else 4
        return [(f"[{i}]", f"{i} - {LANDCOVER[i]}", f"{base}[{i}] = {LANDCOVER[i]}")
                for i in range(n)]
    if kind == 'soil3':
        return [(f"[{i}]", f"{i} - {SOIL_LAYERS[i]}", f"{base}[{i}] = {SOIL_LAYERS[i]}")
                for i in range(3)]
    if kind == 'soil3x4':
        return [(f"[{layer}][{cover}]",
                 f"{layer},{cover} - {SOIL_LAYERS[layer]}, {LANDCOVER[cover]}",
                 f"{base}[{layer}][{cover}]")
                for layer in range(3) for cover in range(4)]
    if kind == 'crop':
        opts = [(f"[{i}]", f"crop {i}", f"{base}[{i}]") for i in range(_CROP_OFFERED)]
        opts.append((None, "other crop number…",
                     "Type a crop index - the crop list is defined in the settings "
                     "Excel sheet, so it has no fixed length"))
        return opts
    return []


def _num(s):
    try:
        return int(str(s).strip())
    except ValueError:
        return None


def dim_problem(base, idx):
    """Message when the index/indices of ``base`` don't match its dimension, or None.

    Unknown variables with an index are **not** flagged (other modules allocate 2-D
    variables this module does not track)."""
    if base in DIM6 or base in DIM4 or base in DIM3:
        n, hint = ((6, HINT6) if base in DIM6 else
                   (4, HINT4) if base in DIM4 else (3, HINT3))
        kind = "per-soil-layer" if base in DIM3 else "per-land-cover"
        if len(idx) != 1:
            return (f"'{base}' is a {kind} array - it needs one index, "
                    f"e.g. '{base}[1]' ({hint}).")
        i = _num(idx[0])
        if i is None or not 0 <= i < n:
            return f"index '[{idx[0]}]' is invalid for '{base}' - use {hint}."
    elif base in DIM3X4:
        if len(idx) != 2:
            return (f"'{base}' is a (soil layer x land cover) array - it "
                    f"needs two indices, e.g. '{base}[0][1]'.")
        i0, i1 = _num(idx[0]), _num(idx[1])
        if i0 is None or not 0 <= i0 < 3:
            return f"first index '[{idx[0]}]' is invalid for '{base}' ({HINT3})."
        if i1 is None or not 0 <= i1 < 4:
            return f"second index '[{idx[1]}]' is invalid for '{base}' ({HINT4})."
    elif base in DIMCROP:
        if len(idx) != 1 or _num(idx[0]) is None or _num(idx[0]) < 0:
            return (f"'{base}' is a per-crop array - it needs a crop index, "
                    f"e.g. '{base}[0]'.")
    return None
