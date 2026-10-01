"""Input rules for the CWatM account forms - pure, no network, no supabase import.

The login/register dialogs check input with these before anything is sent, so the
user gets a precise message instead of a server error. The username rule is the
same as the ``profiles.username`` check constraint in
``supabase/migrations/..._gamification_schema.sql`` - keep the two in step.

Each ``*_problem`` function returns ``None`` when the value is fine, else a short
English message.
"""

import math
import re

USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,29}$")
# Deliberately loose: the server (and the confirmation email) is the real check.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PASSWORD_MIN = 8          # = Authentication > Email > minimum password length
PASSWORD_MAX_BYTES = 72   # bcrypt limit - Supabase Auth rejects longer passwords

# Optional profile fields: same limits as the profiles table.
OPTIONAL_LIMITS = {"full_name": 100, "country": 60, "institute": 150}


def is_email(identifier):
    """A login identifier is an email when it contains '@' - a username never can."""
    return "@" in (identifier or "")


def username_problem(name):
    name = (name or "").strip()
    if not name:
        return "Please enter a username."
    if len(name) < 3 or len(name) > 30:
        return "The username must be 3 to 30 characters long."
    if not USERNAME_RE.match(name):
        return ("The username may contain only letters, digits and _ . - "
                "and must start with a letter or digit.")
    return None


def email_problem(email):
    email = (email or "").strip()
    if not email:
        return "Please enter an email address."
    if not EMAIL_RE.match(email):
        return "This does not look like an email address."
    return None


def password_problem(password, repeat=None):
    password = password or ""
    if len(password) < PASSWORD_MIN:
        return f"The password must have at least {PASSWORD_MIN} characters."
    if len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        return "The password is too long (at most 72 bytes)."
    if repeat is not None and repeat != password:
        return "The two passwords do not match."
    return None


def code_problem(code):
    """The 6-digit code from a confirmation / password-reset email."""
    code = (code or "").strip()
    if not re.fullmatch(r"\d{6,10}", code):
        return "Please enter the code from the email (digits only)."
    return None


def _coord(text):
    text = (text or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return "bad"


def location_problem(lat_text, lon_text):
    """The optional own location: both empty, or both numbers in range."""
    lat, lon = _coord(lat_text), _coord(lon_text)
    if lat is None and lon is None:
        return None
    if lat is None or lon is None:
        return "Please enter both latitude and longitude (or leave both empty)."
    if lat == "bad" or lon == "bad":
        return "Latitude and longitude must be numbers, e.g. 48.067 and 16.357."
    if not -90 <= lat <= 90:
        return "The latitude must be between -90 and 90."
    if not -180 <= lon <= 180:
        return "The longitude must be between -180 and 180."
    return None


# The own location is kept only to the nearest half degree (~50 km) - in the GUI
# and on the server (profiles trigger, migration ..._user_location_half_degree.sql).
LOCATION_STEP = 0.5


def round_location(value):
    """A coordinate rounded to the nearest LOCATION_STEP degree: 48.067 -> 48.0.
    Halves round away from zero, like the server's numeric round() (48.25 -> 48.5),
    so the GUI and the stored value always agree."""
    steps = abs(float(value)) / LOCATION_STEP
    return math.copysign(math.floor(steps + 0.5) * LOCATION_STEP, float(value)) + 0.0


def parse_location(lat_text, lon_text):
    """(lat, lon) rounded to 0.5 degree, or (None, None) - call after
    location_problem() returned None."""
    lat, lon = _coord(lat_text), _coord(lon_text)
    if lat is None or lon is None or "bad" in (lat, lon):
        return None, None
    return round_location(lat), round_location(lon)


def format_coord(value):
    """A stored coordinate for a text field ('' when unset): 48.5, 16."""
    if value is None or value == "":
        return ""
    return f"{float(value):.3f}".rstrip("0").rstrip(".")


def clean_optional(field, value):
    """Trim an optional profile field; '' becomes None. Too-long values are cut to the
    table's limit rather than rejected - these fields are free text."""
    value = (value or "").strip()
    if not value:
        return None
    return value[:OPTIONAL_LIMITS.get(field, 100)]
