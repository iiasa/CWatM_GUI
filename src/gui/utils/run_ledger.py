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
                pass
    return keep


def add_entry(entry):
    """Append one run record (a dict) and persist, pruning old entries. Best-effort:
    a failure is logged but never propagated (logging a run must not break a run)."""
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


def make_entry(settings_path, title, pathout, started_at, success, last_dis,
               kind="run", content=None):
    """Build a ledger entry dict from the common run facts. When ``content`` (the
    settings content the run actually used) is given, it is snapshotted to a file and
    the entry gets a ``snapshot`` path (so Compare settings diffs the run-time content,
    not the file as it is on disk now)."""
    now = time.time()
    dur = max(0.0, now - started_at) if started_at else 0.0
    entry = {
        "ts": now,
        "kind": kind,                         # run | hidden | batch | stopped
        "settings": settings_path or "",
        "title": title or "",
        "pathout": pathout or "",
        "duration_s": round(dur, 1),
        "success": bool(success),
        "last_dis": last_dis,
    }
    snap = _write_snapshot(content, settings_path, now)
    if snap:
        entry["snapshot"] = snap
    return entry
