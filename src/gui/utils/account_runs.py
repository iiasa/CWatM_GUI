"""Which CWatM runs earn account points, what is sent for them, and the offline queue.

Pure logic + one small JSON file - no Qt, no network (``account_ui`` does the
sending through the worker). The server has the last word (``award_run`` checks
the minimum timesteps, the daily cap and duplicates); this module only decides what
is worth sending and remembers what could not be sent.

**A full run** = the Journal-of-Runs entry says ``success`` and it is a main run,
a Windowed Run or a Batch scenario (a stopped run is ``success=False``).

**Only non-identifying facts leave the machine** (``run_meta``): GUI version, run
kind, number of timesteps, duration, and a one-way fingerprint of the setup
(``run_ledger.settings_fingerprint``) so the server awards one point per distinct
setup. Never paths, titles or the settings themselves.

**Offline queue** (``account_pending.json`` next to ``run_ledger.json``): a full run
finished while the account could not be reached is kept, **tagged with the user it
belongs to**, and sent at that user's next login - never credited to someone else
who logs in on the same computer. Runs made while logged out are not queued (they
do not count). Capped at ``_MAX_PENDING`` entries and ``_MAX_AGE_DAYS`` days.
"""

import json
import os
import time

from src.gui.utils import run_ledger
from src.gui.utils.gui_log import get_logger

log = get_logger("account_runs")

_PENDING_NAME = "account_pending.json"
_MAX_PENDING = 100
_MAX_AGE_DAYS = 30

COUNTED_KINDS = ("run", "hidden", "batch")


def qualifies(entry):
    """True when a Journal-of-Runs entry is a full run worth sending."""
    return (bool(entry.get("success"))
            and entry.get("kind") in COUNTED_KINDS
            and bool(entry.get("uid")))


def run_meta(entry, gui_version):
    """The facts sent with a run - the whitelist the server also enforces."""
    meta = {"gui_version": str(gui_version)[:20], "kind": entry.get("kind")}
    if entry.get("timesteps"):
        meta["timesteps"] = int(entry["timesteps"])
    if entry.get("duration_s") is not None:
        meta["duration_s"] = round(float(entry["duration_s"]), 1)
    if entry.get("settings_hash"):
        # one-way fingerprint of the setup: the server awards one point per setup
        meta["settings_hash"] = entry["settings_hash"]
    return meta


def location_of(entry):
    """The (lon, lat) to report for a qualifying run, or None (no/invalid gauge)."""
    gauge = entry.get("gauge")
    if not gauge or len(gauge) != 2:
        return None
    try:
        lon, lat = float(gauge[0]), float(gauge[1])
    except (TypeError, ValueError):
        return None
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    return (lon, lat)


def user_key(username):
    return (username or "").strip().lower()


# ---- offline queue ----------------------------------------------------------------

def pending_path():
    return os.path.join(run_ledger.history_dir(), _PENDING_NAME)


def load_pending():
    """All queued awards (list of {uid, meta, user, ts}); expired ones dropped."""
    try:
        with open(pending_path(), encoding="utf-8") as f:
            items = json.load(f)
    except FileNotFoundError:
        return []
    except Exception:
        log.warning("could not read the pending account awards", exc_info=True)
        return []
    if not isinstance(items, list):
        return []
    cutoff = time.time() - _MAX_AGE_DAYS * 86400
    return [i for i in items
            if isinstance(i, dict) and i.get("uid") and i.get("ts", 0) >= cutoff]


def _save_pending(items):
    try:
        os.makedirs(run_ledger.history_dir(), exist_ok=True)
        path = pending_path()
        if not items:
            if os.path.exists(path):
                os.remove(path)
            return
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(items[-_MAX_PENDING:], f, indent=1)
        os.replace(tmp, path)
    except Exception:
        log.warning("could not write the pending account awards", exc_info=True)


def add_pending(uid, meta, username, gauge=None):
    """Keep a run for ``username`` to send later (idempotent per uid). ``gauge``
    stays local until the run is awarded (then it is reported, anonymously)."""
    if not uid or not user_key(username):
        return
    items = [i for i in load_pending() if i.get("uid") != uid]
    item = {"uid": uid, "meta": meta, "user": user_key(username), "ts": time.time()}
    if gauge:
        item["gauge"] = list(gauge)
    items.append(item)
    _save_pending(items)


def pending_for(username):
    """The queued runs of this user, oldest first."""
    key = user_key(username)
    return [i for i in load_pending() if i.get("user") == key]


def remove_pending(uid):
    items = load_pending()
    kept = [i for i in items if i.get("uid") != uid]
    if len(kept) != len(items):
        _save_pending(kept)
