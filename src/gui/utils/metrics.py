"""
Goodness-of-fit metrics for observed-vs-simulated discharge (Analyse ▸ Timeseries).

Standard hydrological skill scores computed on the overlap of a simulated and an
observed series (already aligned to matching dates by the caller). All functions
take two equal-length sequences and ignore any pair where either value is None /
NaN. They return None when there are too few valid pairs.
"""

import math


def _clean_pairs(sim, obs):
    """Zip sim/obs, dropping any pair where either side is missing (None/NaN)."""
    out = []
    for s, o in zip(sim, obs):
        if s is None or o is None:
            continue
        try:
            s = float(s)
            o = float(o)
        except (TypeError, ValueError):
            continue
        if math.isnan(s) or math.isnan(o):
            continue
        out.append((s, o))
    return out


def _mean(xs):
    return sum(xs) / len(xs)


def nse(sim, obs):
    """Nash-Sutcliffe Efficiency (1 = perfect, 0 = as good as the observed mean)."""
    pairs = _clean_pairs(sim, obs)
    if len(pairs) < 2:
        return None
    o = [p[1] for p in pairs]
    obar = _mean(o)
    denom = sum((oi - obar) ** 2 for oi in o)
    if denom == 0:
        return None
    num = sum((s - oi) ** 2 for s, oi in pairs)
    return 1.0 - num / denom


def kge(sim, obs):
    """Kling-Gupta Efficiency (2009 formulation; 1 = perfect)."""
    pairs = _clean_pairs(sim, obs)
    if len(pairs) < 2:
        return None
    s = [p[0] for p in pairs]
    o = [p[1] for p in pairs]
    sbar, obar = _mean(s), _mean(o)
    if obar == 0:
        return None
    ss = math.sqrt(sum((x - sbar) ** 2 for x in s) / len(s))
    so = math.sqrt(sum((x - obar) ** 2 for x in o) / len(o))
    if so == 0 or sbar == 0:
        return None
    # Pearson correlation
    cov = sum((si - sbar) * (oi - obar) for si, oi in pairs) / len(pairs)
    if ss == 0:
        return None
    r = cov / (ss * so)
    alpha = ss / so          # variability ratio
    beta = sbar / obar       # bias ratio
    return 1.0 - math.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)


def pbias(sim, obs):
    """Percent bias (%). Positive = model overestimates."""
    pairs = _clean_pairs(sim, obs)
    if not pairs:
        return None
    denom = sum(o for _, o in pairs)
    if denom == 0:
        return None
    return 100.0 * sum(s - o for s, o in pairs) / denom


def rmse(sim, obs):
    """Root-mean-square error (same unit as the series)."""
    pairs = _clean_pairs(sim, obs)
    if not pairs:
        return None
    return math.sqrt(sum((s - o) ** 2 for s, o in pairs) / len(pairs))


def compute_all(sim, obs):
    """Return {'KGE','NSE','PBIAS','RMSE','n'} for the aligned sim/obs series."""
    return {
        "KGE": kge(sim, obs),
        "NSE": nse(sim, obs),
        "PBIAS": pbias(sim, obs),
        "RMSE": rmse(sim, obs),
        "n": len(_clean_pairs(sim, obs)),
    }
