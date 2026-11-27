"""Pure path building/parsing for the event log's file layout.

Run events: ``ledger/<uid>/runs/<date>-<settings_hash>.json`` - the UTC date prefix
(``YYYY-MM-DD``) lets one folder listing give both the "already counted" set and the
daily cap. The daily cap is "today's UTC calendar date", a deliberate simplification of
a rolling 24 hours - a friendly rate limit, not exact fairness.
"""

import re

_RUN_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-([0-9a-f]{64})\.json$")


def run_events_dir(uid):
    return f"ledger/{uid}/runs"


def run_event_filename(settings_hash, date):
    """``date`` is a ``YYYY-MM-DD`` string (UTC)."""
    return f"{date}-{settings_hash}.json"


def parse_run_filename(filename):
    """``(date, settings_hash)`` for a run-event filename, else ``None`` (stray files)."""
    m = _RUN_FILENAME_RE.match(filename)
    return (m.group(1), m.group(2)) if m else None


def badge_path(uid, badge_code):
    return f"ledger/{uid}/badges/{badge_code}.json"
