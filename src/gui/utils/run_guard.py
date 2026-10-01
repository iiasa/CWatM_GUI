"""Early check of the output entries of a settings file - CWatM's own rule, before
the model starts (security.md #1).

History: CWatM used to run ``eval("self.var." + entry)`` on every ``OUT_MAP_*`` /
``OUT_TSS_*`` entry and ``exec`` on NetCDF attributes, so a crafted settings or
forcing file could run code. The CWatM in ``cwatm/`` no longer does (2026-10-01):
``data_handling.parseoutvar`` accepts an entry only when it fully matches
``[A-Za-z_]\\w*`` + optional integer indices ``[n]`` / ``[-n]`` and otherwise stops
with **Error 135**; values are read with ``getattr`` / ``setattr``. The NetCDF check
the GUI had for the old ``exec`` was therefore removed.

What stays is this check: it gives **the same verdict as CWatM's Error 135**, before
every run (main run, Windowed Run, Batch Run, Create batch), naming the line - so a
bad entry is fixed in the editor instead of a model start failing. It mirrors
CWatM's parsing exactly (configparser, case-sensitive keys, ``OUT_`` keys in every
section except ``[OPTIONS]``, ``*_Dir`` keys excluded, values split on commas and
stripped, an empty FIRST entry means "no output" (``splitout``), every entry except
``None`` parsed). It looks at the raw value, so a ``$(...)`` placeholder in an
output entry is refused too - CWatM would see whatever it expands to.

Pure Python; Qt is imported only inside ``confirm_safe_to_run``.
"""

import configparser
import re

# = cwatm/management_modules/data_handling.py _OUTVARNAME (used with fullmatch)
OUTVARNAME = re.compile(r"([A-Za-z_]\w*)((?:\[-?\d+\])*)")


def _parse(content):
    cfg = configparser.ConfigParser(interpolation=None, strict=False)
    cfg.optionxform = str                      # CWatM: case-sensitive keys
    cfg.read_string(content)
    return cfg


def _key_rows(content):
    """(section, key) -> 0-based line number of the key, for marking the editor."""
    rows, section = {}, None
    for i, line in enumerate(content.split("\n")):
        s = line.strip()
        m = re.match(r"^\[([^\]]+)\]", s)
        if m:
            section = m.group(1).strip()
            continue
        m = re.match(r"^([^=:#;\s][^=:]*?)\s*[=:]", line)
        if m and section is not None:
            rows.setdefault((section, m.group(1).strip()), i)
    return rows


def _entries(value):
    """configuration.splitout: split on commas, strip; an empty FIRST entry = None."""
    out = [e.strip() for e in value.split(",")]
    if out[0] == "":
        out[0] = "None"
    return out


def output_problems(content):
    """Output entries CWatM would refuse (Error 135): [(row, key, entry, reason)].
    Empty = CWatM accepts them all. An unreadable file yields nothing here (CWatM
    reports that itself)."""
    try:
        cfg = _parse(content)
    except configparser.Error:
        return []
    rows = _key_rows(content)
    problems = []
    for sec in cfg.sections():
        if sec == "OPTIONS":
            continue
        for key in cfg.options(sec):
            low = key.lower()
            if not low.startswith("out_") or low.endswith("_dir"):
                continue
            for entry in _entries(cfg.get(sec, key, raw=True)):
                if entry == "None" or OUTVARNAME.fullmatch(entry):
                    continue
                if entry == "":
                    reason = "empty entry (a comma too many?)"
                elif "$(" in entry:
                    reason = "placeholder in an output name"
                elif "[" in entry:
                    reason = "index is not a whole number"
                else:
                    reason = "not a plain variable name"
                problems.append((rows.get((sec, key)), key, entry, reason))
    return problems


def check(content):
    """Readable lines for every entry CWatM would refuse (empty = all fine)."""
    return [f"line {row + 1 if row is not None else '?'}: {key} = {entry!r} "
            f"({reason})" for row, key, entry, reason in output_problems(content)]


def _bullets(items, limit=12):
    text = "\n".join(f"• {i}" for i in items[:limit])
    if len(items) > limit:
        text += f"\n• … and {len(items) - limit} more"
    return text


def confirm_safe_to_run(parent, content, title="Run CWatM", what="run"):
    """The Qt side, used by every run path: True when the run may start. A bad
    output entry stops it here with the line named - CWatM would stop with
    Error 135 anyway, only later and less clearly."""
    problems = check(content)
    if not problems:
        return True
    from PySide6.QtWidgets import QMessageBox
    QMessageBox.warning(
        parent, title,
        "CWatM would refuse these output entries (Error 135) - each must be a "
        "variable name, optionally with whole-number indices, e.g. discharge or "
        "actualET[1]:\n\n" + _bullets(problems) +
        "\n\nCheck settingsfile (F4) marks these lines.\n\n"
        f"Nothing was started ({what}).")
    return False
