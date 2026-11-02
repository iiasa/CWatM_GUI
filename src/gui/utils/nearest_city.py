"""Nearest city to a station - an offline label for the Analyse windows.

The city list is GeoNames ``cities15000`` (every place with more than 15,000
people; CC BY 4.0, credited in Info > About CWatM), cut down to
``name / lat / lon / country`` in ``assets/geonames_cities15000.tsv``. Nothing is
fetched from the internet.

``city_label(lon, lat)`` gives ``"12 km from Vienna (AT)"``, or ``""`` when the
coordinates are not a lon/lat pair (a projected x/y station, e.g. UTM metres), are
unreadable, or the list cannot be read. The list is read once, on the first call
(numpy imported then, not at module import - keeps the fast-startup rule).
"""

import math

from .assets import asset_path

CITY_FILE = "geonames_cities15000.tsv"
EARTH_RADIUS_KM = 6371.0088          # mean Earth radius (IUGG)

_cities = None                        # (names, countries, lat_rad, lon_rad) once read
_load_failed = False


def as_lonlat(lon, lat):
    """``(lon, lat)`` as floats if they can be geographic degrees, else ``None``.

    A projected station (x/y in metres) has values far outside the lon/lat ranges,
    so this is what decides "no city name" for it."""
    try:
        lon_f = float(str(lon).strip())
        lat_f = float(str(lat).strip())
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lon_f) and math.isfinite(lat_f)):
        return None
    if not (-180.0 <= lon_f <= 360.0 and -90.0 <= lat_f <= 90.0):
        return None
    if lon_f > 180.0:                 # 0..360 longitudes
        lon_f -= 360.0
    return lon_f, lat_f


def _load():
    """Read the city list once; ``None`` if it cannot be read (logged)."""
    global _cities, _load_failed
    if _cities is not None or _load_failed:
        return _cities
    try:
        import numpy as np
        names, countries, lats, lons = [], [], [], []
        with open(asset_path(CITY_FILE), encoding="utf-8") as fh:
            next(fh)                  # header: name, lat, lon, country
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 4:
                    continue
                names.append(parts[0])
                lats.append(float(parts[1]))
                lons.append(float(parts[2]))
                countries.append(parts[3])
        _cities = (names, countries,
                   np.radians(np.asarray(lats, dtype=float)),
                   np.radians(np.asarray(lons, dtype=float)))
    except Exception:
        from .gui_log import get_logger
        get_logger(__name__).exception("could not read the city list %s", CITY_FILE)
        _load_failed = True
        _cities = None
    return _cities


def nearest_city(lon, lat):
    """``(name, country, distance_km)`` of the nearest city, or ``None``.

    Great-circle (haversine) distance from the station to the city's point."""
    ll = as_lonlat(lon, lat)
    if ll is None:
        return None
    data = _load()
    if not data or not data[0]:
        return None
    import numpy as np
    names, countries, lat_r, lon_r = data
    lat0, lon0 = math.radians(ll[1]), math.radians(ll[0])
    a = (np.sin((lat_r - lat0) / 2.0) ** 2
         + math.cos(lat0) * np.cos(lat_r) * np.sin((lon_r - lon0) / 2.0) ** 2)
    i = int(np.argmin(a))
    dist = 2.0 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, float(a[i]))))
    return names[i], countries[i], dist


def format_label(name, country, dist_km):
    """``"12 km from Vienna (AT)"`` - under 1 km reads ``"< 1 km from …"``."""
    where = f"{name} ({country})" if country else name
    if dist_km < 1.0:
        return f"< 1 km from {where}"
    return f"{dist_km:.0f} km from {where}"


def city_label(lon, lat):
    """The label for a station, or ``""`` (not lon/lat, or no city list)."""
    found = nearest_city(lon, lat)
    if found is None:
        return ""
    return format_label(*found)
