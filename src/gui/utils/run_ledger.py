"""
Run ledger for the CWatM GUI: a small persistent log of completed model runs.

One JSON row per run (main run, Hidden Run, or a Batch scenario) recording when it
ran, the settings file, the settings ``Title``, the resolved PathOut, the duration,
whether it succeeded, and the last discharge. Viewed via **RUN CWATM ▸ Run Ledger**;
each row is clickable to reopen its results (Output Explorer on its PathOut) or reload
its settings file.

Storage location and retention are user-configurable (Configure menu):
- **folder** (`history/folder`, default ``%LOCALAPPDATA%/CWatM_GUI``) - a general
  folder holding ``run_ledger.json``;
- **retention** (`history/retention_days`, default 60; 0 = keep forever) - entries
  older than this many days are pruned on write.
"""

import os
import re
import json
import time
import uuid
import shutil
import tempfile

from PySide6.QtCore import QSettings

from src.gui.utils.gui_log import get_logger

log = get_logger("run_ledger")

_ORG, _APP = "IIASA", "CWatM_GUI"
_KEY_FOLDER = "history/folder"
_KEY_RETENTION = "history/retention_days"
_DEFAULT_RETENTION_DAYS = 60
_LEDGER_NAME = "run_ledger.json"
_MAX_ENTRIES = 2000  # hard cap so the file cannot grow without bound


def _settings():
    return QSettings(_ORG, _APP)


def default_history_dir():
    """The default general history folder: ``%LOCALAPPDATA%/CWatM_GUI`` (else temp)."""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return os.path.join(base, _APP)


def history_dir():
    """The configured history folder (default :func:`default_history_dir`)."""
    v = _settings().value(_KEY_FOLDER, "")
    return v if v else default_history_dir()


def set_history_dir(path):
    s = _settings()
    s.setValue(_KEY_FOLDER, path or "")
    s.sync()


def retention_days():
    """How many days of entries to keep (0 = keep forever). Default 60."""
    try:
        return int(_settings().value(_KEY_RETENTION, _DEFAULT_RETENTION_DAYS))
    except (TypeError, ValueError):
        return _DEFAULT_RETENTION_DAYS


def set_retention_days(days):
    s = _settings()
    s.setValue(_KEY_RETENTION, int(days))
    s.sync()


def ledger_path():
    return os.path.join(history_dir(), _LEDGER_NAME)


def _snapshots_dir():
    return os.path.join(history_dir(), "snapshots")


def _write_snapshot(content, settings_path, ts):
    """Save the run-time settings content to a timestamped file under
    ``<history>/snapshots/`` and return its path (so Compare settings can diff exactly
    what a run used, not the file as it is on disk now). Best-effort → None on failure."""
    if not content:
        return None
    try:
        folder = _snapshots_dir()
        os.makedirs(folder, exist_ok=True)
        base = os.path.splitext(os.path.basename(settings_path or "settings"))[0]
        safe = re.sub(r"[^\w\-.]+", "_", base).strip("_") or "settings"
        stem = time.strftime("%Y%m%d_%H%M%S", time.localtime(ts)) + f"_{safe}"
        # Ensure a unique name: several runs (e.g. a parallel batch) can finish within
        # the same second, which would otherwise overwrite each other's snapshot.
        path = os.path.join(folder, stem + ".ini")
        i = 1
        while os.path.exists(path):
            path = os.path.join(folder, f"{stem}_{i}.ini")
            i += 1
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path
    except Exception:
        log.warning("could not write settings snapshot", exc_info=True)
        return None


def load_entries():
    """All ledger entries, newest first. Never raises (returns [] on any problem)."""
    path = ledger_path()
    try:
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data  # stored oldest-first; the window sorts for display
    except Exception:
        log.warning("could not read run ledger", exc_info=True)
    return []


def _prune(entries):
    """Drop entries older than the retention window and cap the count, deleting the
    settings snapshot files of any dropped entry."""
    keep, drop = entries, []
    days = retention_days()
    if days and days > 0:
        cutoff = time.time() - days * 86400
        keep = [e for e in entries if float(e.get("ts", 0)) >= cutoff]
        drop = [e for e in entries if float(e.get("ts", 0)) < cutoff]
    if len(keep) > _MAX_ENTRIES:
        drop += keep[:len(keep) - _MAX_ENTRIES]
        keep = keep[-_MAX_ENTRIES:]
    for e in drop:
        snap = e.get("snapshot")
        if snap and os.path.exists(snap):
            try:
                os.remove(snap)
            except Exception:
                log.debug("_prune: ignored", exc_info=True)
    return keep


# Called with every entry add_entry() records - the one place all three run paths
# (main run, Windowed Run, Batch scenario) meet. The CWatM account (account_ui.py)
# listens here to award points for full runs.
_listeners = []


def add_listener(fn):
    """Call ``fn(entry)`` for every run recorded from now on (GUI thread)."""
    if fn not in _listeners:
        _listeners.append(fn)


def remove_listener(fn):
    if fn in _listeners:
        _listeners.remove(fn)


def add_entry(entry):
    """Append one run record (a dict) and persist, pruning old entries. Best-effort:
    a failure is logged but never propagated (logging a run must not break a run).
    The listeners are told even if the journal could not be written."""
    _write_entry(entry)
    for fn in list(_listeners):
        try:
            fn(dict(entry))
        except Exception:
            log.warning("run-ledger listener failed", exc_info=True)


def _write_entry(entry):
    try:
        os.makedirs(history_dir(), exist_ok=True)
        path = ledger_path()
        entries = []
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    entries = json.load(f)
                if not isinstance(entries, list):
                    entries = []
            except Exception:
                entries = []
        entry = dict(entry)
        entry.setdefault("ts", time.time())
        entries.append(entry)
        entries = _prune(entries)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=1)
        os.replace(tmp, path)
    except Exception:
        log.warning("could not write run ledger entry", exc_info=True)


def clear():
    """Delete the ledger file and all settings snapshots."""
    try:
        p = ledger_path()
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        log.warning("could not clear run ledger", exc_info=True)
    try:
        folder = _snapshots_dir()
        if os.path.isdir(folder):
            shutil.rmtree(folder, ignore_errors=True)
    except Exception:
        log.warning("could not clear settings snapshots", exc_info=True)


def _entry_key(entry):
    """What identifies a journal entry across a reload (the window works on copies).

    New entries carry a unique ``uid`` (see :func:`make_entry`), which is what this
    returns. Entries written before that existed - and any hand-edited row - fall back
    to (timestamp, settings, pathout). That fallback can collide: two runs of the same
    settings file into the same PathOut finishing within the same millisecond are
    indistinguishable, so deleting one deletes both and a note lands on both. The uid
    removes the ambiguity going forward without invalidating an existing journal.
    """
    uid = entry.get("uid")
    if uid:
        return ("uid", uid)
    try:
        ts = round(float(entry.get("ts", 0)), 3)
    except (TypeError, ValueError):
        ts = 0.0
    return ts, entry.get("settings", ""), entry.get("pathout", "")


def set_note(entry, note):
    """Attach a free-text note to one entry ("calibration attempt 3").

    Titles come from the settings file and repeat endlessly, so a note is what makes a
    months-old journal navigable. Returns True when something was written."""
    try:
        key = _entry_key(entry)
        entries = load_entries()
        changed = False
        for e in entries:
            if _entry_key(e) == key:
                if (note or "").strip():
                    e["note"] = note.strip()
                else:
                    e.pop("note", None)
                changed = True
        if not changed:
            return False
        path = ledger_path()
        tmp = path + ".tmp"
        os.makedirs(history_dir(), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=1)
        os.replace(tmp, path)
        return True
    except Exception:
        log.warning("could not store the run note", exc_info=True)
        return False


def remove_entries(victims):
    """Delete these entries from the journal (and their settings snapshots).

    Matched on the ``ts`` + ``settings`` + ``pathout`` triple rather than object
    identity: the window works on copies loaded from the file. Returns how many were
    removed."""
    try:
        keys = {_entry_key(e) for e in (victims or [])}
        if not keys:
            return 0
        entries = load_entries()
        keep, drop = [], []
        for e in entries:
            (drop if _entry_key(e) in keys else keep).append(e)
        if not drop:
            return 0
        for e in drop:
            snap = e.get("snapshot")
            if snap and os.path.exists(snap):
                try:
                    os.remove(snap)
                except Exception:
                    log.debug("remove_entries: ignored", exc_info=True)
        path = ledger_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(keep, f, indent=1)
        os.replace(tmp, path)
        return len(drop)
    except Exception:
        log.warning("could not remove journal entries", exc_info=True)
        return 0


def _parse_step(value):
    """A StepStart/StepEnd value the way CWatM reads it (timestep.py Calendar): a
    number, or a day-first date with '/', '.' or '-' and a 2- or 4-digit year.
    Returns an int, a datetime.date, or None."""
    import datetime
    value = (value or "").strip()
    if not value:
        return None
    if re.fullmatch(r"[+-]?\d+(\.\d*)?", value):       # a timestep count
        return int(float(value))
    d = value.replace(".", "/").replace("-", "/")
    fmt = "%d/%m/%Y" if len(d.split("/")[-1]) == 4 else "%d/%m/%y"
    try:
        return datetime.datetime.strptime(d, fmt).date()
    except ValueError:
        return None


def settings_timesteps(content):
    """Number of (daily) timesteps a settings file simulates, StepStart..StepEnd
    inclusive - or None when it cannot be told (missing or unparseable values).

    Mirrors CWatM: StepEnd is a date or a timestep **count**; a key given twice counts
    by its last value (CWatM's flat binding dict). Pure - tested."""
    if not content:
        return None
    values = {}
    for line in content.splitlines():
        s = line.split("#", 1)[0].strip()
        if "=" not in s or s.startswith(("[", ";")):
            continue
        key, value = s.split("=", 1)
        key = key.strip().lower()
        if key in ("stepstart", "stepend"):
            values[key] = value.strip()
    start = _parse_step(values.get("stepstart"))
    end = _parse_step(values.get("stepend"))
    if end is None:
        return None
    if isinstance(end, int):
        return end if end > 0 else None
    if start is None or isinstance(start, int):
        return None
    days = (end - start).days + 1
    return days if days > 0 else None


# Keys that do not change what CWatM computes: the run's name, where the results go,
# and which results are written. A setup differing only in these is the SAME setup
# for the "one point per setup" rule (otherwise renaming Title would earn a point).
_FINGERPRINT_IGNORED = ("title", "pathout")
_FINGERPRINT_IGNORED_PREFIX = "out_"


def settings_fingerprint(content):
    """One-way SHA-256 fingerprint of a model setup (hex), or None without content.

    Read the way CWatM reads the file: comments ('#' / ';'), blank lines, spacing,
    section headers, line order and key case do not matter, a key given twice counts
    by its last value (the flat binding dict). Title, PathOut and every OUT_* key are
    left out - they do not change the simulation. The CWatM account sends only this
    hash, never the settings, to award one point per distinct setup. Pure - tested."""
    import hashlib
    if not content:
        return None
    values = {}
    for line in content.splitlines():
        s = line.split("#", 1)[0].strip()
        if not s or s.startswith((";", "[")) or "=" not in s:
            continue
        key, value = s.split("=", 1)
        key = key.strip().lower()
        if key in _FINGERPRINT_IGNORED or key.startswith(_FINGERPRINT_IGNORED_PREFIX):
            continue
        values[key] = " ".join(value.split())
    if not values:
        return None
    canon = "\n".join(f"{k}={v}" for k, v in sorted(values.items()))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def make_entry(settings_path, title, pathout, started_at, success, last_dis,
               kind="run", content=None, log_path=None, batch_id=None):
    """Build a ledger entry dict from the common run facts. When ``content`` (the
    settings content the run actually used) is given, it is snapshotted to a file and
    the entry gets a ``snapshot`` path (so Compare settings diffs the run-time content,
    not the file as it is on disk now)."""
    now = time.time()
    dur = max(0.0, now - started_at) if started_at else 0.0
    entry = {
        # Identifies this row for delete/note across a reload. Parallel runs (Batch
        # Run, several Windowed Runs) can finish in the same millisecond with the same
        # settings file, which the old (ts, settings, pathout) key could not tell
        # apart - see _entry_key.
        "uid": uuid.uuid4().hex,
        "ts": now,
        "kind": kind,                         # run | hidden | batch | stopped
        "settings": settings_path or "",
        "title": title or "",
        "pathout": pathout or "",
        "duration_s": round(dur, 1),
        "success": bool(success),
        "last_dis": last_dis,
    }
    # Length of the simulated period, from the settings the run actually used
    # (the CWatM account counts only runs of at least game_config.min_timesteps).
    steps = settings_timesteps(content)
    if steps is not None:
        entry["timesteps"] = steps
    # Which model setup it was (one-way hash; the account's one-point-per-setup rule).
    fingerprint = settings_fingerprint(content)
    if fingerprint:
        entry["settings_hash"] = fingerprint
    # Where this run's output was written, so the journal can show *why* it failed
    # instead of only *that* it failed.
    if log_path:
        entry["log"] = log_path
    # Scenarios of one Batch Run share this, so the journal can fold them into a
    # single row instead of 30 unrelated ones.
    if batch_id:
        entry["batch_id"] = batch_id
    snap = _write_snapshot(content, settings_path, now)
    if snap:
        entry["snapshot"] = snap
    return entry
