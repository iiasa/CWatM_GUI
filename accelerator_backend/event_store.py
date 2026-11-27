"""The immutable event log: one tiny file per event under the service's read-write
folder (Accelerator saves that folder when the app stops).

Layout (see ``ledger_paths``): ``<root>/ledger/<uid>/runs/<date>-<settings_hash>.json`` and
``<root>/ledger/<uid>/badges/<code>.json``. A file is created once and never changed:
the filename (date + setup fingerprint) is the dedup key, so writing the same event twice is refused instead of
overwriting. The logic only ever reads **filenames**, never contents - a half-written
file (an abrupt stop) therefore cannot corrupt anything.
"""

import json
import os

import ledger_paths


class EventStore:
    def __init__(self, root):
        self.root = root

    def _dir(self, relative):
        return os.path.join(self.root, *relative.split("/"))

    @staticmethod
    def _uid(uid):
        if isinstance(uid, bool) or not isinstance(uid, int) or uid <= 0:
            raise ValueError("uid must be a positive integer")
        return uid

    def _list(self, directory):
        try:
            return sorted(os.listdir(directory))
        except FileNotFoundError:
            return []

    def _create(self, directory, filename, content):
        """Create the file exclusively; False when it already exists."""
        os.makedirs(directory, exist_ok=True)
        try:
            with open(os.path.join(directory, filename), "x", encoding="utf-8") as fh:
                json.dump(content, fh, sort_keys=True)
        except FileExistsError:
            return False
        return True

    # ---- runs ----------------------------------------------------------------------
    def run_filenames(self, uid):
        return self._list(self._dir(ledger_paths.run_events_dir(self._uid(uid))))

    def write_run(self, uid, settings_hash, date, event):
        directory = self._dir(ledger_paths.run_events_dir(self._uid(uid)))
        return self._create(directory, ledger_paths.run_event_filename(settings_hash, date), event)

    # ---- badges --------------------------------------------------------------------
    def _badge_dir(self, uid):
        return self._dir(f"ledger/{self._uid(uid)}/badges")

    def badge_codes(self, uid):
        return {name[:-5] for name in self._list(self._badge_dir(uid)) if name.endswith(".json")}

    def write_badge(self, uid, badge, recorded_at):
        return self._create(self._badge_dir(uid), f"{badge['code']}.json",
                            {**badge, "recorded_at": recorded_at})
