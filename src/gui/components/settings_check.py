"""Settings > Check settingsfile (F4) - the whole validation pass.

Walks the **editor content** (never the file on disk) and reports two kinds of problem:

* **file existence** - every value that names a file or directory, with placeholders
  resolved; leniently for data files (glob, missing `.nc`, date suffixes), strictly for
  `path*` keys. Missing files in a section or key that its `[OPTIONS]` switch turns off
  are dimmed instead of flagged, and MODFLOW input is soft.
* **semantics** (`_semantic_settings_problems`) - date ordering, option dependencies,
  the `out_*` keyword grammar and variable names, array indices, and whether the run
  window fits inside the meteo-forcing time coverage.

Mixed into `CWatMMainWindow`; the marks it sets live on the active tab's
`SettingsEditor` (`set_error_rows` / `set_inactive_rows` / `set_wrongext_rows` +
check-owned bookmarks), and the summary goes to the output box.
"""

import os
import re

from PySide6.QtCore import QDate

from src.gui.utils.gui_log import get_logger

log = get_logger("settings_check")


class SettingsCheckMixin:
    """The Check settingsfile pass of `CWatMMainWindow` (see the module docstring)."""

    def check_settingsfile(self):
        """Settings ▸ Check settingsfile: walk the settings as shown in the editor and
        check every value that can be identified as a filename/path. Lines whose file
        does not exist are marked **red** and **bookmarked** (F2 jumps between them)."""
        import configparser
        import glob as _glob
        try:
            content = self.text_area.toPlainText()
        except Exception:
            return
        if not content.strip():
            self.status_bar.showMessage("Nothing to check - load a settings file first")
            return

        # ConfigParser (no interpolation) for resolving $(section:key) placeholders.
        config = None
        try:
            config = configparser.ConfigParser(interpolation=None, strict=False)
            config.read_string(content)
        except Exception:
            config = None
        from src.gui.widgets.basin_viewer import _resolve_settings_placeholders

        # Relative paths resolve against the working directory (the settings file's
        # folder unless File > Change Working Dir overrode it).
        base_dir = self.working_dir()

        _EXT = (r'\.(nc|nc4|tif|tiff|map|txt|csv|xlsx?|geojson|json|asc|img|bil|'
                r'hdf5?|h5|pcr|ldd|dat|bin)(\*|"|\b|$)')

        def looks_like_path(v):
            v = v.strip().strip('"')
            if not v:
                return False
            if '$(' in v:                         # a settings placeholder -> path ref
                return True
            if re.search(_EXT, v, re.I):          # a known data-file extension
                return True
            if re.match(r'^[A-Za-z]:[\\/]', v) or v.startswith('\\\\'):  # absolute path
                return True
            return False

        def path_exists(p, strict=False):
            """Whether the resolved path exists. ``strict`` (used for keys starting with
            'path', i.e. directory paths) checks existence exactly - no NetCDF
            without-extension / date-suffix glob fallbacks."""
            p = p.strip().strip('"')
            if not p:
                return True
            if not os.path.isabs(p) and base_dir:
                p = os.path.join(base_dir, p)
            try:
                if any(c in p for c in '*?'):
                    return bool(_glob.glob(p))
                if os.path.exists(p):
                    return True
                if strict:
                    return False
                # CWatM often stores NetCDFs without .nc or with a date suffix
                if _glob.glob(p + '*'):
                    return True
                return os.path.exists(p + '.nc')
            except Exception:
                return True   # never flag on a lookup error

        # Interchangeable raster extensions in CWatM: a map named .map/.tif/.nc may
        # actually be on disk under one of the others.
        _ALT_EXTS = ('.nc', '.nc4', '.tif', '.tiff', '.map')

        def wrong_extension_alt(p):
            """If the exact file p is missing but the SAME base name exists with a
            different known raster extension (e.g. .map written, .nc on disk), return
            that existing alternative path; else None. Best-effort, never raises."""
            p = p.strip().strip('"')
            if not p or any(c in p for c in '*?'):
                return None
            if not os.path.isabs(p) and base_dir:
                p = os.path.join(base_dir, p)
            root, ext = os.path.splitext(p)
            if not ext or ext.lower() not in _ALT_EXTS:
                return None
            try:
                for alt in _ALT_EXTS:
                    if alt == ext.lower():
                        continue
                    cand = root + alt
                    if os.path.exists(cand) or _glob.glob(cand + '*'):
                        return cand
            except Exception:
                return None
            return None

        # Fresh run: drop any red/bookmarks from a previous check first.
        self.text_area.clear_checking()

        # Sections whose keys CWatM only reads when their [OPTIONS] switch is on
        # (mirrored from the checkOption(...) guards in cwatm/, read-only - e.g.
        # run_cwatm.py:65 modflow, readmeteo.py glaciers, water_demand.py:423,
        # lakes_reservoirs.py:303, cwatm_dynamic.py:229/255, inflow.py:129,
        # environflow.py:67). A missing FILE in such a section while the option is
        # explicitly off is dimmed, not flagged. Unresolved placeholders and out_*
        # keys stay global: CWatM resolves/collects those for EVERY section at
        # parse time (ExtParser Error 116, configuration.py:272) - option off or not.
        _SECTION_GATED_BY = {
            'GROUNDWATER_MODFLOW': 'modflow_coupling',
            'GLACIER': 'includeGlaciers',
            'WATERDEMAND': 'includeWaterDemand',
            'LAKES_RESERVOIRS': 'includeWaterBodies',
            'RUNOFF_CONCENTRATION': 'includeRunoffConcentration',
            'INFLOW': 'inflow',
            'ENVIRONMENTALFLOW': 'calc_environflow',
            'ROUTING': 'includeRouting',
        }
        # Finer, KEY-level gating: an individual file key CWatM only reads when an
        # [OPTIONS] switch is on (regardless of which section it sits in), mirrored
        # read-only from the returnBool(...)/checkOption(...) guards in cwatm/. Maps
        # the .ini key (lowercase) -> its gating option. All entries here are DIRECT
        # (key active only when the option is on); if a future one is inverted,
        # handle it explicitly. Refs:
        #   initLoad             <- load_initial            (initcondition.py:453-455)
        #   initSave             <- save_initial            (initcondition.py:463-466)
        #   albedoMaps           <- albedo                  (evaporationPot.py:310)
        #   initLoad_pySnowClim  <- load_initial_pySnowClim (snow_frost.py:260-261)
        #   initSave_pySnowClim  <- save_initial_pySnowClim (snow_frost.py:269-271)
        #   smallLakesRes        <- useSmallLakes           (lakes_res_small.py:110-119)
        #   smallwaterBodyDis    <- useSmallLakes           (lakes_res_small.py:137)
        #   EnvironmentalFlowFile<- use_environflow         (environmental_need.py:69-90;
        #                           a separate option from the [OPTIONS] calc_environflow)
        #   irrNonPaddy_fracVegCover <- static_irrigation_map (landcoverType.py:708-709)
        _KEY_GATED_BY = {
            'initload': 'load_initial',
            'initsave': 'save_initial',
            'albedomaps': 'albedo',
            'initload_pysnowclim': 'load_initial_pySnowClim',
            'initsave_pysnowclim': 'save_initial_pySnowClim',
            'smalllakesres': 'useSmallLakes',
            'smallwaterbodydis': 'useSmallLakes',
            'environmentalflowfile': 'use_environflow',
            'irrnonpaddy_fracvegcover': 'static_irrigation_map',
        }
        # Prefix gates: every key starting with the prefix is gated by the option -
        # covers all downscale_wordclim_<var> (prec/tavg/tmin/tmax/...) at once
        # (readmeteo.py:162-179; NOT meteomapssamescale - that only rescales maps).
        _KEY_GATED_BY_PREFIX = {
            'downscale_wordclim': 'usemeteodownscaling',
        }
        # VALUE gates: a file key CWatM reads only when another key's NUMERIC value
        # meets a condition (not a boolean on/off). Mirrors, read-only:
        #   averageBaseflow / averageDischarge  <- swAbstractionFrac < 0
        #     (water_demand.py:719-724: loadmap only inside `if swAbstractionFrac<0`;
        #      with swAbstractionFrac >= 0 a fixed fraction is used and the files are
        #      never read). key (lower) -> (gate key, condition).
        _KEY_GATED_BY_VALUE = {
            'averagebaseflow': ('swAbstractionFrac', 'neg'),
            'averagedischarge': ('swAbstractionFrac', 'neg'),
        }
        disabled = {}                # SECTION (upper) -> gating option name
        # Gating-switch lookup, flattened across ALL sections (key lower -> raw value,
        # later sections win). CWatM reads these switches by key name from its flat
        # dicts - checkOption() from [OPTIONS], but returnBool() from `binding`, and
        # most fine gating switches (load_initial, albedo, useSmallLakes,
        # use_environflow, usemeteodownscaling, ...) live OUTSIDE [OPTIONS]
        # (e.g. [INITITIAL CONDITIONS]/[EVAPORATION]/[LAKES_RESERVOIRS]/[WATERDEMAND]),
        # so scanning only [OPTIONS] would miss them.
        opts = {}
        if config is not None:
            for sec in config.sections():
                try:
                    for k, v in config.items(sec):
                        opts[k.lower()] = v
                except Exception:
                    # best effort: one unreadable section must not stop the check
                    log.debug("gating lookup: section %s skipped", sec, exc_info=True)
                    continue

        def _explicitly_off(opt_name):
            """True only when a gating switch is present and set false/0/no/off.
            A missing switch is treated as active (conservative - never hides a real
            missing-file error), same rule as the section gating."""
            v = (opts.get(opt_name.lower()) or "").strip().lower()
            return v in ('false', '0', 'no', 'off')

        def _value_gate_phrase(key_lower):
            """For a VALUE-gated key, return a short summary phrase when its gate is
            NOT met (so the file is not read), else None. Conservative: an unparseable
            or missing gate value counts as active (flag a real miss)."""
            entry = _KEY_GATED_BY_VALUE.get(key_lower)
            if not entry:
                return None
            gate_key, cond = entry
            raw = (opts.get(gate_key.lower()) or "").strip()
            if cond == 'neg':          # read only when gate value < 0
                try:
                    val = float(raw)
                except (TypeError, ValueError):
                    return None
                if val >= 0:
                    return f"{gate_key} = {raw} >= 0 (read only when < 0)"
            return None

        def _is_modflow_input(key_lower, raw_value):
            """True for a groundwater-MODFLOW input path/file: a PathGroundwaterModflow*
            key itself, or any value routed through a $(PathGroundwaterModflow...)
            placeholder (modflow_basin/topo_modflow/chanRatio/cwatm_modflow_indices/...).
            MODFLOW input is normally preprocessed/optional, so a missing one is soft
            (light orange, no bookmark) rather than a hard red error - but only while
            the GROUNDWATER_MODFLOW section is active (an off section is already dimmed)."""
            if key_lower.startswith('pathgroundwatermodflow'):
                return True
            return 'pathgroundwatermodflow' in (raw_value or '').lower()

        for sec_u, opt in _SECTION_GATED_BY.items():
            if _explicitly_off(opt):
                disabled[sec_u] = opt

        checked = 0
        missing = []
        missing_info = []            # (row, key, value, resolved)
        wrongext_info = []           # (row, key, value, resolved, alt_path)
        bad_placeholders = []        # (row, key, value, [placeholder, ...])
        inactive_info = []           # (row, kind, name, gate); kind = section|key|valuekey|modflow
        options_rows = {}            # [OPTIONS] key (lower) -> its line row
        gated_active_problem = set() # gated SECTION (upper) that is ON and has a red row
        cur_section = ""
        for r, line in enumerate(content.split('\n')):
            s = line.strip()
            if not s or s[0] in '#;':
                continue
            if s[0] == '[':
                cur_section = s.strip('[]').strip()
                continue
            eq = s.find('=')
            if eq <= 0:
                continue
            key = s[:eq].strip()
            value = s[eq + 1:].strip()
            # Remember where each [OPTIONS] switch line sits, so a problem inside an
            # enabled feature's section can be rolled up onto its option line below.
            if cur_section.strip().upper() == 'OPTIONS':
                options_rows[key.lower()] = r
            # Keys starting with 'path' (PathRoot/PathOut/PathMaps/...) are directory
            # paths: always checked, and only for plain existence (strict).
            is_path_key = key[:4].lower() == "path"
            if not is_path_key and not looks_like_path(value):
                continue
            resolved = value
            if config is not None:
                try:
                    resolved = _resolve_settings_placeholders(value, config)
                except Exception:
                    resolved = value
            if not resolved.strip():
                continue
            if '$(' in resolved:
                # Placeholder(s) whose referenced key/section does not exist in the
                # settings file (e.g. $(PathRoot) with no PathRoot entry, or a typo'd
                # $(FILE_PATHS:PathRoot)): a real error - CWatM would fail on it too.
                # Only flaggable when the content parsed (config is not None);
                # otherwise resolution never ran, so skip as before.
                if config is not None:
                    bad = sorted(set(re.findall(r'\$\(([^)]+)\)', resolved)))
                    bad_placeholders.append((r, key, value, bad))
                    # A red row inside an ENABLED gated feature's section rolls up.
                    sec_u = cur_section.upper()
                    if sec_u in _SECTION_GATED_BY and sec_u not in disabled:
                        gated_active_problem.add(sec_u)
                continue
            checked += 1
            if not path_exists(resolved, strict=is_path_key):
                gate = disabled.get(cur_section.upper())
                key_gate = _KEY_GATED_BY.get(key.lower())
                if key_gate is None:
                    kl = key.lower()
                    for _pref, _opt in _KEY_GATED_BY_PREFIX.items():
                        if kl.startswith(_pref):
                            key_gate = _opt
                            break
                alt = None if is_path_key else wrong_extension_alt(resolved)
                vphrase = _value_gate_phrase(key.lower())
                if gate:
                    # Section's option is off - not important: dim, don't flag.
                    inactive_info.append((r, 'section', cur_section, gate))
                elif key_gate and _explicitly_off(key_gate):
                    # This individual key's option is off - not read: dim, don't flag.
                    inactive_info.append((r, 'key', key, key_gate))
                elif vphrase is not None:
                    # Value-gated key whose gate is not met (e.g. averageDischarge with
                    # swAbstractionFrac >= 0): not read - dim, don't flag.
                    inactive_info.append((r, 'valuekey', key, vphrase))
                elif _is_modflow_input(key.lower(), value):
                    # Groundwater-MODFLOW input path/file: preprocessed/optional - dim,
                    # don't flag (separate rule from the section gate).
                    inactive_info.append((
                        r, 'modflow', key,
                        'groundwater MODFLOW input (preprocessed/optional)'))
                elif alt is not None:
                    # The file exists but with a different known raster extension
                    # (likely a wrong-extension typo): orange, NO bookmark.
                    wrongext_info.append((r, key, value, resolved, alt))
                else:
                    missing.append(r)
                    missing_info.append((r, key, value, resolved))
                    # A missing file inside an ENABLED gated feature's section rolls
                    # up onto that feature's [OPTIONS] switch line too.
                    sec_u = cur_section.upper()
                    if sec_u in _SECTION_GATED_BY and sec_u not in disabled:
                        gated_active_problem.add(sec_u)

        # Semantic checks (date ordering, ...) - mark their rows too.
        semantic = self._semantic_settings_problems(content, config, base_dir)
        semantic_rows = [r for r, _ in semantic if r is not None]

        placeholder_rows = [r for r, _k, _v, _b in bad_placeholders]
        # Roll-up: an ENABLED feature whose section has a red row gets its [OPTIONS]
        # switch line marked red + bookmarked too (points the user at the culprit
        # option). Only when the option line actually exists in the file.
        rollup = []                  # (option_row, option_name, section_upper)
        for sec_u in sorted(gated_active_problem):
            opt = _SECTION_GATED_BY.get(sec_u)
            orow = options_rows.get(opt.lower()) if opt else None
            if orow is not None:
                rollup.append((orow, opt, sec_u))
        rollup_rows = [orow for orow, _o, _s in rollup]
        mark_rows = missing + placeholder_rows + semantic_rows + rollup_rows
        self.text_area.set_error_rows(mark_rows)
        # Missing files in disabled sections / behind an off key-option:
        # dimmed orange, NO bookmark.
        self.text_area.set_inactive_rows([r for r, _k, _n, _g in inactive_info])
        # Wrong-extension (file exists under another raster extension):
        # clear orange, NO bookmark.
        self.text_area.set_wrongext_rows([r for r, _k, _v, _res, _alt in wrongext_info])
        if mark_rows:
            self.text_area.bookmark_rows(mark_rows)

        # Summary to the output box. When Configure ▸ 'Write output box' is on (and
        # a run is not already writing the log), mirror this whole summary into the
        # output-box file too - append_to_cwatminfo writes to the open handle.
        _own_output_file = False
        if getattr(self, "_write_output_enabled", False):
            _own_output_file = self._open_output_file_note("Check settingsfile")
        try:
            self._write_check_summary(
                checked, missing_info, inactive_info, wrongext_info,
                bad_placeholders, semantic, rollup)
        finally:
            if _own_output_file:
                self._finalize_output_file()
        skip_note = (f", {len(inactive_info)} dimmed (option off)"
                     if inactive_info else "")
        rollup_note = f", {len(rollup)} enabled option(s) flagged" if rollup else ""
        self.status_bar.showMessage(
            f"Check settingsfile: {len(missing)} missing file(s), "
            f"{len(bad_placeholders)} unresolved placeholder(s), "
            f"{len(semantic)} settings problem(s){skip_note}{rollup_note} "
            "- see the output box")

    def _write_check_summary(self, checked, missing_info, inactive_info,
                             wrongext_info, bad_placeholders, semantic, rollup):
        """Emit the Check settingsfile summary via append_to_cwatminfo (output box +,
        when opened by the caller, the output-box log file)."""
        self.append_to_cwatminfo("==== Check settingsfile ====")
        if not missing_info:
            extra = " (except disabled sections/keys, see below)" if inactive_info else ""
            self.append_to_cwatminfo(
                f"Checked {checked} filename value(s) - all files exist{extra}.")
        else:
            self.append_to_cwatminfo(
                f"{len(missing_info)} of {checked} file value(s) missing "
                "(marked red + bookmarked; F2/Shift+F2 to jump):")
            # Only the problem lines - one compact line each (resolved path appended
            # when it differs from the written value).
            for r, key, value, resolved in missing_info:
                extra = f"   ->  {resolved}" if resolved.strip() != value.strip() else ""
                self.append_to_cwatminfo(
                    f"  line {r + 1}: {key} = {value}{extra}", is_error=True)
        # Missing files whose gating option is off: one quiet note per section/key
        # (the lines are dimmed orange in the editor, not red/bookmarked).
        if inactive_info:
            per = {}
            for _r, kind, name, gate in inactive_info:
                per[(kind, name, gate)] = per.get((kind, name, gate), 0) + 1
            for (kind, name, gate), n in per.items():
                if kind in ('valuekey', 'modflow'):
                    # gate is already a full phrase (e.g. "swAbstractionFrac = 0.8 >= 0 …"
                    # or "groundwater MODFLOW input …").
                    self.append_to_cwatminfo(
                        f"skipped {name} - {gate} "
                        f"({n} missing file value(s) dimmed, not flagged)")
                    continue
                label = f"[{name}]" if kind == 'section' else name
                self.append_to_cwatminfo(
                    f"skipped {label} - {gate} = False "
                    f"({n} missing file value(s) dimmed, not flagged)")
        # Wrong-extension: the file exists under a different raster extension
        # (marked orange, NOT bookmarked - a likely typo, not a hard miss).
        if wrongext_info:
            self.append_to_cwatminfo(
                f"{len(wrongext_info)} wrong extension (file exists as another "
                "type; marked orange, not bookmarked):")
            for r, key, value, resolved, alt in wrongext_info:
                self.append_to_cwatminfo(
                    f"  line {r + 1}: {key} = {value}   ->  exists as "
                    f"{os.path.basename(alt)}")
        # Unresolvable placeholders (marked red + bookmarked, like missing files).
        if bad_placeholders:
            self.append_to_cwatminfo(
                f"{len(bad_placeholders)} unresolved placeholder(s) - the referenced "
                "key does not exist in the settings file:")
            for r, key, value, bad in bad_placeholders:
                names = ', '.join(f'$({b})' for b in bad)
                self.append_to_cwatminfo(
                    f"  line {r + 1}: {key} = {value}   ->  {names} not defined",
                    is_error=True)
        # Semantic problems (marked red + bookmarked, like missing files).
        if semantic:
            self.append_to_cwatminfo(
                f"{len(semantic)} settings problem(s):")
            for r, msg in semantic:
                where = f"line {r + 1}: " if r is not None else ""
                self.append_to_cwatminfo(f"  {where}{msg}", is_error=True)
        elif not missing_info:
            self.append_to_cwatminfo("Date order (StepStart/SpinUp/StepEnd) OK.")
        # Enabled options flagged because their feature's section has a problem.
        if rollup:
            self.append_to_cwatminfo(
                f"{len(rollup)} enabled option(s) flagged - a problem exists in the "
                "section they switch on (marked red + bookmarked):")
            for orow, opt, sec_u in rollup:
                self.append_to_cwatminfo(
                    f"  line {orow + 1}: {opt} = True   ->  see the red line(s) "
                    f"in [{sec_u}]", is_error=True)

    def _semantic_settings_problems(self, content, config=None, base_dir=""):
        """Semantic (not just file-existence) checks on the settings content. Returns a
        list of (row_index_or_None, message) problems:
        - simulation date ordering StepStart ≤ SpinUp ≤ StepEnd (comparing only values
          that are real dates; SpinUp/StepEnd may legitimately be an integer number of
          timesteps);
        - the run window inside the **meteo forcing** NetCDF time coverage (the most
          common "crashes hours into a run" error) - needs ``config``/``base_dir`` to
          resolve and read the forcing files."""
        from datetime import datetime

        def _find(key):
            """(row_index, value) of the first uncommented ``key = value`` line, or
            (None, None)."""
            for i, line in enumerate(content.split('\n')):
                s = line.strip()
                if not s or s[0] in '#;[':
                    continue
                eq = s.find('=')
                if eq <= 0:
                    continue
                if s[:eq].strip().lower() == key.lower():
                    return i, s[eq + 1:].strip()
            return None, None

        def _as_date(v):
            if v is None:
                return None
            for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
                try:
                    return datetime.strptime(v.strip(), fmt)
                except ValueError:
                    continue
            return None

        problems = []
        rs, vs = _find("StepStart")
        rp, vp = _find("SpinUp")
        re_, ve = _find("StepEnd")
        d_start, d_spin, d_end = _as_date(vs), _as_date(vp), _as_date(ve)

        # StepStart must be a date (CWatM requires it)
        if vs is not None and d_start is None:
            problems.append((rs, f"StepStart = {vs} is not a valid date (dd/mm/yyyy)."))
        if d_start and d_spin and d_spin < d_start:
            problems.append(
                (rp, f"SpinUp ({vp}) is before StepStart ({vs}) - spin-up must be "
                 "on/after the start."))
        if d_start and d_end and d_end < d_start:
            problems.append(
                (re_, f"StepEnd ({ve}) is before StepStart ({vs}) - the run would be "
                 "empty."))
        if d_spin and d_end and d_end < d_spin:
            problems.append(
                (re_, f"StepEnd ({ve}) is before SpinUp ({vp}) - no output would be "
                 "written."))

        # Option dependencies: an option switched ON but missing its required keys, OR a
        # required key that is a PATH which does not exist on disk. Either way the
        # **option's own line** is flagged (so a bad dependency is visible on the option
        # too, not only on the path line). The key may be defined in any section (CWatM
        # flattens them); a commented/absent/empty key counts as "not set".
        _OPTION_REQUIRES = {
            "modflow_coupling": ["path_mf6dll", "PathGroundwaterModflow",
                                 "nameModflowModel", "Modflow_resolution"],
        }
        # Required keys checked only for "is it set" (NOT "does the path exist"):
        # the MODFLOW input dir is preprocessed/optional (same separate rule as
        # _is_modflow_input), so a set-but-missing PathGroundwaterModflow must not
        # flag its option red. path_mf6dll (the solver DLL) still must exist.
        _REQUIRE_SET_ONLY = {"pathgroundwatermodflow"}
        from src.gui.widgets.basin_viewer import _resolve_settings_placeholders

        def _looks_path(v):
            return bool(v) and (v.startswith("$(") or "\\" in v or "/" in v
                                or bool(re.match(r"^[A-Za-z]:", v)))

        def _path_missing(v):
            """(missing, resolved) for a path value (placeholders resolved). An
            unresolvable placeholder is treated as present (not flagged)."""
            try:
                resolved = _resolve_settings_placeholders(v, config) if config else v
            except Exception:
                resolved = v
            resolved = (resolved or "").strip().strip('"')
            if not resolved or "$(" in resolved:
                return False, resolved
            p = resolved
            if not os.path.isabs(p) and base_dir:
                p = os.path.join(base_dir, p)
            return (not os.path.exists(p)), resolved

        for opt, required in _OPTION_REQUIRES.items():
            r_opt, v_opt = _find(opt)
            if (v_opt or "").strip().lower() not in ("true", "1", "yes", "on"):
                continue
            issues = []
            for k in required:
                vk = (_find(k)[1] or "").strip()
                if not vk:
                    issues.append(f"{k} (not set)")
                elif _looks_path(vk) and k.lower() not in _REQUIRE_SET_ONLY:
                    miss, resolved = _path_missing(vk)
                    if miss:
                        extra = f" -> {resolved}" if resolved != vk else ""
                        issues.append(f"{k}{extra} (missing)")
            if issues:
                problems.append((r_opt, f"{opt} = True but: {'; '.join(issues)}."))

        # Output keywords: every `out_*` key (outside [OPTIONS]) must follow CWatM's
        # output grammar, mirrored from cwatm/management_modules/ (do not edit there):
        #   configuration.py: `out_*` = output key; `out_*_dir` = output directory;
        #     `out_tss_*` = timeseries; anything else = map;
        #   globals.py: outputTypMap / outputTypTss / outputTypTss2 (the valid types);
        #   output.py appendinfo: maps only match `out_map_<type>` exactly - a bad map
        #     key (e.g. OUT_MAP_AreaSum_MonthTot: AreaSum is TSS-only) is **silently
        #     ignored** by CWatM, so F4 is the only place the user learns about it.
        _TSS_TYPES = ('daily', 'monthtot', 'monthavg', 'monthend', 'annualtot',
                      'annualavg', 'annualend', 'totaltot', 'totalavg')
        _MAP_TYPES = _TSS_TYPES + ('monthmid', 'totalend', 'once', '12month')
        _AGG = ('areasum', 'areaavg')

        def _out_key_problem(key):
            """Error message for an invalid `out_*` key, or None if it is valid."""
            k = key.lower()
            if k.endswith('_dir'):
                return None                      # out_*_dir = output directory, valid
            rest = k[4:]                          # after 'out_'
            if rest.startswith('tss_'):
                parts = rest[4:].split('_')
                if parts[-1] not in _TSS_TYPES:
                    return (f"'{parts[-1]}' is not a valid TSS time step - use one "
                            f"of: {', '.join(_TSS_TYPES)}.")
                if len(parts) == 1:
                    return None                   # out_tss_<type>
                if len(parts) == 2 and parts[0] in _AGG:
                    return None                   # out_tss_<areasum|areaavg>_<type>
                return (f"'{'_'.join(parts[:-1])}' is not a valid TSS aggregation - "
                        "use OUT_TSS_<type> (point value), or "
                        "OUT_TSS_AreaSum_<type> / OUT_TSS_AreaAvg_<type>.")
            if rest.startswith('map_'):
                parts = rest[4:].split('_')
                if parts[0] in _AGG:
                    return (f"'{parts[0]}' is only available for timeseries "
                            "(OUT_TSS_AreaSum_... / OUT_TSS_AreaAvg_...), not for "
                            "maps - CWatM silently ignores this key.")
                if len(parts) == 1 and parts[0] in _MAP_TYPES:
                    return None                   # out_map_<type>
                return (f"'{rest[4:]}' is not a valid map time step - use "
                        f"OUT_MAP_<type> with one of: {', '.join(_MAP_TYPES)}.")
            return ("output keys must be OUT_TSS_..., OUT_MAP_... or OUT_..._Dir - "
                    "CWatM silently ignores this key.")

        # Output values: each comma-separated variable name of a (valid) out_* key is
        # checked against the metaNetcdf.xml catalogue (cached in meta_netcdf.py).
        # Mirrors CWatM's runtime check (output.py checkifvariableexists, Error 132):
        # case-sensitive, `[index]` stripped, the special 'WaterCycle' allowed; a
        # first item of "None" (or empty) means "output disabled" (configuration.py
        # splitout) and is skipped. Best-effort: if the xml is unreadable, or a token
        # is not a plain identifier, nothing is flagged.
        import difflib
        from src.gui.utils.meta_netcdf import all_varnames
        _known = all_varnames()
        _known_lower = {k.lower(): k for k in _known}

        # Multi-dimensional model variables that need an index in an output value
        # (e.g. actualET -> actualET[1]). The sets and the check live in
        # src/gui/utils/var_dims.py - Tools ▸ Add output variables uses the same
        # knowledge to OFFER the valid indices by name, so it must not be duplicated.
        from src.gui.utils.var_dims import dim_problem as _dim_problem

        def _out_value_problems(value):
            """List of messages for unknown output-variable names in ``value``."""
            if not _known:
                return []
            items = [v.strip() for v in value.split(',')]
            if not items or items[0] in ("", "None"):
                return []
            msgs = []
            for it in items:
                m = re.match(r'^([A-Za-z_]\w*)((?:\[[^\]]*\])*)$', it)
                if not m:
                    continue
                base = m.group(1)
                idx = re.findall(r'\[([^\]]*)\]', m.group(2))
                if base == 'WaterCycle':
                    continue
                if base not in _known:
                    hit = _known_lower.get(base.lower()) or (
                        'WaterCycle' if base.lower() == 'watercycle' else None)
                    if hit:
                        msgs.append(f"'{base}' has the wrong case - CWatM is "
                                    f"case-sensitive, use '{hit}'.")
                    else:
                        closest = difflib.get_close_matches(base, _known, n=1)
                        extra = f" (closest: '{closest[0]}')" if closest else ""
                        msgs.append(f"variable '{base}' is not in "
                                    f"cwatm/metaNetcdf.xml{extra}.")
                    continue
                dmsg = _dim_problem(base, idx)
                if dmsg:
                    msgs.append(dmsg)
            return msgs

        section = ""
        for i, line in enumerate(content.split('\n')):
            s = line.strip()
            if not s or s[0] in '#;':
                continue
            if s.startswith('['):
                section = s.strip('[]').strip().upper()
                continue
            eq = s.find('=')
            if eq <= 0:
                continue
            key = s[:eq].strip()
            if section == "OPTIONS" or key.lower()[:4] != "out_":
                continue
            msg = _out_key_problem(key)
            if msg:
                problems.append((i, f"{key}: {msg}"))
            elif not key.lower().endswith('_dir'):
                for vmsg in _out_value_problems(s[eq + 1:].strip()):
                    problems.append((i, f"{key}: {vmsg}"))

        # Output entries CWatM refuses at start (Error 135, parseoutvar) - the same
        # rule run_guard uses to stop a run early, so F4 shows the lines it names.
        from src.gui.utils.run_guard import output_problems as _entry_problems
        for row, key, entry, reason in _entry_problems(content):
            if row is not None:
                problems.append(
                    (row, f"{key}: '{entry}' - {reason}. CWatM refuses it at start "
                          "(Error 135): use a variable name, optionally with whole-"
                          "number indices, e.g. discharge or actualET[1]."))

        # Forcing coverage: is [StepStart..StepEnd] inside the meteo forcing time axis?
        # Only when StepStart is a real date; StepEnd checked only if it is a date too.
        if d_start is not None:
            rng = self._forcing_time_range(content, config, base_dir)
            if rng is not None:
                key, fkey_row, tmin, tmax = rng
                fmt = lambda d: d.strftime("%d/%m/%Y")
                if d_start < tmin:
                    problems.append(
                        (rs, f"StepStart ({vs}) is before the forcing data starts "
                         f"({fmt(tmin)}, from {key}) - no forcing for the first steps."))
                if d_end is not None and d_end > tmax:
                    problems.append(
                        (re_, f"StepEnd ({ve}) is after the forcing data ends "
                         f"({fmt(tmax)}, from {key}) - the run will fail when it runs "
                         "out of forcing."))
        return problems

    def _forcing_time_range(self, content, config, base_dir):
        """Time coverage of the meteo forcing: (key, key_row, tmin, tmax) for the first
        forcing entry whose NetCDF files can be read, else None. Reads only the first &
        last (name-sorted) file of the glob, so it is cheap even for many yearly files.
        Best-effort - any read error just returns None (never breaks the F4 check)."""
        if config is None:
            return None
        import glob as _glob
        from datetime import datetime
        from src.gui.widgets.basin_viewer import _resolve_settings_placeholders

        def _key(name):
            for i, line in enumerate(content.split('\n')):
                s = line.strip()
                if not s or s[0] in '#;[' or '=' not in s:
                    continue
                k, v = s.split('=', 1)
                if k.strip().lower() == name.lower():
                    return i, v.strip().strip('"')
            return None, None

        def _natkey(path):
            # Numeric-aware key so pr_2.nc sorts before pr_10.nc (a plain lexical
            # sort would put pr_10/pr_12 before pr_2/pr_9 and pick the wrong first/
            # last file, giving a bogus forcing time range for non-zero-padded names).
            return [int(tok) if tok.isdigit() else tok.lower()
                    for tok in re.split(r'(\d+)', path)]

        def _files(value):
            try:
                resolved = _resolve_settings_placeholders(value, config)
            except Exception:
                resolved = value
            resolved = (resolved or "").strip().strip('"')
            if not resolved or '$(' in resolved:
                return []
            if not os.path.isabs(resolved) and base_dir:
                resolved = os.path.join(base_dir, resolved)
            pats = [resolved] if any(c in resolved for c in '*?') \
                else [resolved, resolved + '*', resolved + '.nc']
            for pat in pats:
                fs = sorted((f for f in _glob.glob(pat)
                             if f.lower().endswith('.nc') and os.path.isfile(f)),
                            key=_natkey)
                if fs:
                    return fs
            return []

        def _to_dt(v):
            try:
                import pandas as pd
                return pd.Timestamp(v).to_pydatetime()
            except Exception:
                try:
                    return datetime(int(v.year), int(v.month), int(v.day))
                except Exception:
                    return None

        def _range(path):
            try:
                import xarray as xr
                with xr.open_dataset(path, decode_times=True) as ds:
                    tname = next((d for d in ds.dims if 'time' in str(d).lower()), None)
                    if not tname or tname not in ds.coords:
                        return None, None
                    t = ds[tname].values
                    if len(t) == 0:
                        return None, None
                    return _to_dt(t[0]), _to_dt(t[-1])
            except Exception:
                log.debug("forcing time read failed: %s", path, exc_info=True)
                return None, None

        # Precipitation first (canonical), then temperature / evaporation.
        for name in ("PrecipitationMaps", "TavgMaps", "E0Maps", "ETMaps"):
            row, value = _key(name)
            if not value:
                continue
            files = _files(value)
            if not files:
                continue
            tmin, _ = _range(files[0])
            _, tmax = _range(files[-1]) if len(files) > 1 else (None, tmin)
            if len(files) == 1:
                tmin, tmax = _range(files[0])
            if tmin is not None and tmax is not None and tmin <= tmax:
                return name, row, tmin, tmax
        return None

    def _forcing_range_for_calendar(self):
        """(QDate, QDate) meteo-forcing coverage for the Start/Spin/End calendar
        popups (CWatMCalendar dims days outside it), or None when unknown. Uses the
        same _forcing_time_range as the F4 semantic check; called lazily by the
        DateManager cache the first time a popup opens after a file load."""
        try:
            import configparser
            content = self.text_area.toPlainText()
            if not content.strip():
                return None
            config = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                config.read_string(content)
            except Exception:
                return None
            rng = self._forcing_time_range(content, config, self.working_dir())
            if rng is None:
                return None
            _key, _row, tmin, tmax = rng
            return (QDate(tmin.year, tmin.month, tmin.day),
                    QDate(tmax.year, tmax.month, tmax.day))
        except Exception:
            log.debug("forcing range for calendar failed", exc_info=True)
            return None

    def clear_checking(self):
        """Remove the red marks and the check-owned bookmarks that Check settingsfile
        added (leaves the user's own bookmarks). Reached via the Check settingsfile
        toggle (F4 a second time); see toggle_check_settings."""
        try:
            self.text_area.clear_checking()
        except Exception:
            log.debug("clear_checking failed", exc_info=True)
        self.append_to_cwatminfo("==== Clear checking: removed Check settingsfile marks ====")
        self.status_bar.showMessage("Cleared Check settingsfile marks and bookmarks")

    def _checking_active(self):
        """True when Check settingsfile marks (red / dimmed-orange rows) are currently
        shown in the editor - i.e. there is something for Clear checking to remove."""
        ed = getattr(self, "text_area", None)
        if ed is None:
            return False
        try:
            return bool(getattr(ed, "_error_rows", None)
                        or getattr(ed, "_inactive_rows", None)
                        or getattr(ed, "_wrongext_rows", None))
        except Exception:
            return False

    def _refresh_check_settings_label(self):
        """Flip the single Check/Clear toggle action's label + tooltip to match the
        current state (marks shown -> 'Clear checking', else -> 'Check settingsfile')."""
        act = getattr(self, "check_settings_action", None)
        if act is None:
            return
        try:
            if self._checking_active():
                act.setText("Clear checking")
                act.setToolTip("Remove the red marks and bookmarks set by Check "
                               "settingsfile. Press again (F4) to re-check.")
            else:
                act.setText("Check settingsfile")
                act.setToolTip("Check every filename value in the settings; mark + "
                               "bookmark lines whose file does not exist. Press again "
                               "(F4) to clear the marks.")
        except RuntimeError:
            log.debug("_refresh_check_settings_label: ignored", exc_info=True)  # the QAction's C++ object was deleted

    def toggle_check_settings(self):
        """Settings ▸ Check settingsfile (F4): a single toggle. When no check marks are
        shown, run the check; when they are, clear them - then relabel the menu item."""
        if self._checking_active():
            self.clear_checking()
        else:
            self.check_settingsfile()
        self._refresh_check_settings_label()
