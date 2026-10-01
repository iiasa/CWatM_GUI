"""Guard against code hidden in a settings file or a NetCDF input (security.md #1).

CWatM (the model in ``cwatm/``, which the GUI must not change) evaluates parts of
its inputs as Python code:

- **Output variable names** - ``output.py`` checks only the part of an
  ``OUT_MAP_*`` / ``OUT_TSS_*`` entry before ``[`` and then runs
  ``eval("self.var." + entry)``. An entry such as ``discharge[<any expression>]``
  passes CWatM's own check and the expression runs when the model writes output.
- **NetCDF metadata** - ``data_handling.py`` copies the attributes of the
  coordinate variables of the meteo forcing file (``PrecipitationMaps``, read by
  ``metaNetCDF``) with ``exec('longitude.<name>="<value>"')``: an attribute name
  that is not a plain identifier, or a value with a quote, backslash or line break,
  breaks out of that string and runs code.

So a shared model setup or a downloaded forcing file can carry a program. Before
every run (main run, Windowed Run, Batch Run, Create batch) the GUI checks:

- ``output_problems(content)`` - every output entry must be a plain name with
  only numeric indices (``discharge``, ``actualET[1]``, ``rootDepth[0][1]``). This
  mirrors CWatM's own parsing (configparser, case-sensitive keys, ``OUT_`` keys in
  every section except ``[OPTIONS]``, ``*_Dir`` keys excluded, values split on
  commas and stripped, ``$(...)`` placeholders expanded - so a placeholder in an
  output entry is refused too). **A problem blocks the run.**
- ``netcdf_problems(path)`` - the attributes of exactly the variables CWatM
  ``exec``s. **A problem is a warning** (default answer: do not run).

Pure Python; netCDF4 and Qt are imported only inside the functions that need them.
"""

import configparser
import glob
import os
import re

# a plain output entry: identifier + optional numeric indices, nothing else
_SAFE_ENTRY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[\d+\])*$")
_SAFE_ATTR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BAD_VALUE_CHARS = ('"', "\\", "\n", "\r")
# the variables whose attributes data_handling.py copies with exec()
EXEC_VARIABLES = ("x", "y", "X", "Y", "lon", "lat", "laea",
                  "lambert_azimuthal_equal_area")


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


def output_problems(content):
    """Output entries CWatM would evaluate as code: [(row, key, entry, reason)].
    Empty = safe. An unreadable file yields no problems here (CWatM refuses it)."""
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
            value = cfg.get(sec, key, raw=True)
            for entry in (e.strip() for e in value.split(",")):
                if entry in ("", "None") or _SAFE_ENTRY.match(entry):
                    continue
                if "$(" in entry:
                    reason = "placeholder in an output name"
                elif "[" in entry:
                    reason = "index is not a plain number"
                else:
                    reason = "not a plain variable name"
                problems.append((rows.get((sec, key)), key, entry, reason))
    return problems


def _resolve(value, cfg):
    try:
        from src.gui.widgets.basin_viewer import _resolve_settings_placeholders
        return _resolve_settings_placeholders(value, cfg)
    except Exception:
        return value


def forcing_metadata_file(content, base_dir):
    """The NetCDF CWatM reads its coordinate metadata from: the first file of
    ``PrecipitationMaps`` (``glob.glob(...)[0]``, like ``metaNetCDF``), relative
    paths against ``base_dir`` (the run's working directory). None if not found."""
    try:
        cfg = _parse(content)
    except configparser.Error:
        return None
    value = None
    for sec in cfg.sections():
        if cfg.has_option(sec, "PrecipitationMaps"):
            value = cfg.get(sec, "PrecipitationMaps", raw=True)   # last one wins
    if not value:
        return None
    path = (_resolve(value, cfg) or "").strip().strip('"')
    if not path or "$(" in path:
        return None
    if not os.path.isabs(path) and base_dir:
        path = os.path.join(base_dir, path)
    found = glob.glob(os.path.normpath(path))
    return found[0] if found else None


def netcdf_problems(path):
    """Attributes of the exec'd coordinate variables that would break out of
    CWatM's exec string: ['variable "lon": attribute ...']. Unreadable = []."""
    try:
        import netCDF4
        ds = netCDF4.Dataset(path)
    except Exception:
        return []
    problems = []
    try:
        for var in EXEC_VARIABLES:
            if var not in ds.variables:
                continue
            v = ds.variables[var]
            for name in v.ncattrs():
                if name == "_FillValue":
                    continue
                if not _SAFE_ATTR_NAME.match(name):
                    problems.append(f'variable "{var}": attribute name {name!r} is '
                                    'not a plain name')
                    continue
                text = str(v.getncattr(name))
                if any(c in text for c in _BAD_VALUE_CHARS):
                    problems.append(f'variable "{var}": attribute "{name}" contains a '
                                    'quote, backslash or line break')
    finally:
        ds.close()
    return problems


def check(content, base_dir):
    """(blocking, warnings, metadata_file) for one settings content."""
    blocking = [f"line {row + 1 if row is not None else '?'}: {key} = {entry} "
                f"({reason})" for row, key, entry, reason in output_problems(content)]
    nc = forcing_metadata_file(content, base_dir)
    warnings = netcdf_problems(nc) if nc else []
    return blocking, warnings, nc


def _bullets(items, limit=12):
    text = "\n".join(f"• {i}" for i in items[:limit])
    if len(items) > limit:
        text += f"\n• … and {len(items) - limit} more"
    return text


def confirm_safe_to_run(parent, content, base_dir, title="Run CWatM", what="run"):
    """The Qt side, used by every run path: True when the run may start. Blocks on
    unsafe output entries; asks (default No) on suspicious NetCDF metadata."""
    from PySide6.QtWidgets import QMessageBox
    blocking, warnings, nc = check(content, base_dir)
    if blocking:
        QMessageBox.critical(
            parent, title,
            "CWatM will not run this settings file.\n\n"
            "These output entries are not plain variable names. CWatM evaluates "
            "output names as Python code, so an entry like this could run any "
            "program on your computer - a settings file from someone else may have "
            "been manipulated:\n\n" + _bullets(blocking) +
            "\n\nAllowed are names with numeric indices only, e.g. discharge, "
            "actualET[1]. Check settingsfile (F4) marks these lines.\n\n"
            f"Nothing was started ({what}).")
        return False
    if warnings:
        return QMessageBox.question(
            parent, title,
            "The meteo forcing file has metadata that CWatM would execute as code:\n"
            f"{nc}\n\n" + _bullets(warnings) +
            "\n\nThis is not normal for a NetCDF file - it may have been "
            "manipulated. Only continue if you trust where this file comes from.\n\n"
            f"{what.capitalize()} anyway?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes
    return True
