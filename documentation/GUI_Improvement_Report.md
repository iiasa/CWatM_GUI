# CWatM GUI — Analysis & Improvement Report

*Date: 2026-07-02*

*Scope: UI code only (`cwatm_gui.py`, `src/gui/**`, specs). CWatM submodule (`cwatm/`)
read for context, not touched. Codebase: ~9,100 lines across 16 modules; frozen
build: 705 MB, 343 DLLs, Python 3.8.10.*

---

## 1. Code-quality issues worth fixing (correctness / maintenance)

> **STATUS: all of §1 (1.1–1.8) was implemented on 2026-07-02.** Notes per item:
> 1.1 dead duplicates deleted · 1.2 split into `menu_builder.py` /
> `run_controller.py` / `output_box.py` mixins (main_window.py: 3050 → ~2360 lines)
> · 1.3 `src/gui/utils/gui_log.py` logs to `%LOCALAPPDATA%/CWatM_GUI/gui.log`;
> excepthook + silent excepts routed through it · 1.4 run-log handle opened once
> per run, flushed on the 150 ms throttle · 1.5 all five `processEvents()` removed
> (scroll restore now via `QTimer.singleShot(0, …)`) · 1.6 output box is a read-only
> `QPlainTextEdit`, 5000-line scrollback, `\r` overwrite kept, errors dark red ·
> 1.7 `cwatm_subprocess_runner.py` deleted · 1.8 `requirements.txt` re-encoded
> UTF-8 + build tools split into `requirements_build.txt` (GDAL removed).
> **Bonus fix found by the smoke test:** `_cleanup_general_files` used to close
> *every* open file in the interpreter — including `sys.stdout`/`stderr` and the
> log streams; it now skips protected streams (`_protected_file_objects`), and a
> dead second `except` block in the same area was removed.

**1.1 Duplicate method definitions in `main_window.py` — dead code that will bite.**
- `show_basin` is defined twice: `main_window.py:2111` and `main_window.py:2789`.
  Python silently keeps the *second* one, so the first is dead — but it's the one a
  future edit will likely land in. Notably, the dead one does **not** pass
  `default_basemap`, so if the definitions ever get reordered, the Configure ▸
  basemap feature silently breaks again (the TODO.txt history shows exactly this
  class of bug happened before).
- `open_check_data_window` likewise: `main_window.py:2139` (dead) vs
  `main_window.py:2848` (live). The two versions even use different content sources
  (`file_manager.current_file_content` vs `text_display.get_content()`), i.e. they'd
  behave differently.
- Recommendation: delete the dead pair; add a trivial CI/dev check (`grep`/flake8
  F811 catches redefinitions).

**1.2 `main_window.py` is a 3,000-line god class.** It builds the banner, menus,
both panels, runs CWatM, manages dirty state, warnings, output box, section folding,
and HTML formatting. Natural split, without changing behaviour:
- `menu_builder.py` (lines ~1159–1390),
- `run_controller.py` (run/stop/progress/output-file, ~1876–2340),
- `output_box.py` (the cwatminfo buffer/throttle/HTML, ~2950–3043),
- keep `CWatMMainWindow` as the thin orchestrator it's documented to be.

This directly reduces the "edited the wrong duplicate" risk above.

**1.3 Silent exception swallowing.** Dozens of `except Exception: pass` blocks plus
a global excepthook. The app never crashes — good for scientists — but faults become
invisible. Recommendation: route *all* of these through Python `logging` to a
rotating file (e.g. `%LOCALAPPDATA%/CWatM_GUI/gui.log`), keep the UI behaviour
identical. Cost: an afternoon. Payoff: every "it just did nothing" support case
becomes diagnosable.

**1.4 Blocking per-line file I/O during a run.** `append_to_cwatminfo`
(`main_window.py:2982-2989`) opens, writes and flushes the log file **for every
printed line**, on the GUI thread, and this project lives on an SMB share. With
per-timestep progress prints this is a real slowdown when "Write output box" is on.
Recommendation: keep the file handle open for the run (there is already
`_finalize_output_file`), or buffer lines and flush on the existing 150 ms display
timer.

**1.5 `QApplication.processEvents()` (5 call sites).** E.g. in `on_cwatm_progress`
(`main_window.py:2109`) — it's called from a queued signal on the GUI thread, so the
event loop is already running; `processEvents()` there only invites re-entrancy (a
second click handled mid-handler). All five are removable.

**1.6 Output box widget choice.** The output area is a QLabel inside a QScrollArea
whose full HTML is rebuilt on every refresh, and the buffer is capped at 100 lines.
A read-only `QPlainTextEdit` with `maximumBlockCount(5000)` gives you: appends
instead of full re-renders (O(1) vs O(n)), 50× more scrollback for free, native
selection/copy (the context menu is currently hand-rolled), and the same
`\r`-overwrite trick via cursor ops. This is the highest-value pure-UI refactor in
the file.

**1.7 Dead module: `src/gui/utils/cwatm_subprocess_runner.py`** is referenced by
nothing (verified by grep). Either delete it, or — better — see §3.1, because it's
actually the skeleton of the right architecture.

**1.8 Requirements hygiene.**
- `requirements.txt` is saved as **UTF-16** — `pip install -r requirements.txt`
  fails on many pip versions with a decode error. Re-save as UTF-8.
- It also mixes runtime deps with build-only tools (`pyinstaller`, `pefile`,
  `altgraph`).
- `requirements_build.txt` lists `GDAL>=3.0.0`, but `cwtmexe.md` / the spec notes
  say rasterio ships its own GDAL and the wheel is *not* needed — one confused
  rebuild away from a broken env. Split cleanly: `requirements.txt` (runtime,
  pinned, UTF-8) and `requirements_build.txt` (pyinstaller only).

---

## 2. What can be added (feature suggestions)

> **STATUS (2026-07-02): 2.1–2.4, 2.6, 2.8–2.10 implemented; 2.5 and 2.7 deliberately
> skipped.** Notes: 2.1 elapsed/remaining shown inside the progress-clock face
> (moved from a label under the clock on 2026-07-03; `ProgressClock.set_time_lines`) ·
> 2.2 implemented as **Tools ▸ Open PathOut Folder** · 2.3 blue changed-fields hint
> right of RUN CWATM · 2.4 drag & drop + `CWatM_GUI.exe <settings.ini>` ·
> 2.6 Settings ▸ Replace (Ctrl+H) + line-number gutter
> (`line_number_gutter.py`; numbers are display lines) · 2.8 geometry memory via
> `window_geometry.py` (QSettings `geometry/*`) · 2.9 "Save HTML" buttons in both
> Analyse windows · 2.10 hover tooltips from a cached metaNetcdf.xml lookup
> (`meta_netcdf.py`).
>
> **Testing feedback on §2, fixed 2026-07-03:**
> - *Elapsed always 0 / remaining never shown*: the model-side progress hook called
>   `gui_window.progress_clock.setValue()` directly (cross-thread), so the worker's
>   `progress` signal — which feeds the time label — never fired past 0. The worker
>   now passes a proxy (`_GuiWindowProxy`/`_ProgressClockProxy` in
>   `cwatm_worker.py`) that re-emits the value as the signal, and a 1-second QTimer
>   keeps "elapsed" ticking between timesteps. No cwatm code touched.
> - *Save HTML* now suggests the resolved **PathOut** directory as the save location
>   (both Analyse windows).
> - *Show Basin*: the OSM marker tooltips (gauge / mask start / clicked point) now
>   also show the **ups.nc value** (upstream area km²) of their cell.
> - **Open PathOut Folder** moved from Tools to **Analyse** (first item).

Ordered roughly by value-to-effort for the target users:

1. **Elapsed time / ETA next to the progress clock.** `intStart/intEnd/curr` per
   timestep already exist — showing "12:34 elapsed · ~08:10 remaining" is nearly
   free and is the single most-requested thing in long model runs.
2. **"Open PathOut folder" action** (Tools or a small button near the warning
   label) — `os.startfile(resolved_pathout)`. Users finish a run and immediately
   want the files.
3. **Changed-fields hint next to RUN CWATM** — already in TODO.txt (2026-07-01):
   show "MaskMap/Gauges changed" so users know the run uses new values. The
   dirty-tracking machinery (`_set_save_dirty`) already knows.
4. **Drag & drop a `.ini` onto the window** to load it, and accept a settings file
   as a **command-line argument** (`CWatM_GUI.exe settings.ini`) — enables Windows
   file association and "Open with".
5. **Save-time backup / dated diff history.** Also in TODO.txt. Cheap version: on
   every save, copy the previous file to `<name>.ini.bak` (or
   `<name>_YYYYMMDD_HHMM.ini` in a `.history/` subfolder). The diff-based version
   can come later; the backup alone prevents the worst-case data loss.
6. **Search & Replace in the editor** (Find/Find-next exist; Replace is the natural
   third), plus a **line-number gutter** — both trivial if the editor moves to
   `QPlainTextEdit` (§1.6/§3.2).
7. **Run queue / batch mode**: select several `.ini` files, run them sequentially,
   one log per run. Falls out almost for free once runs are subprocess-based (§3.1).
8. **Remember window geometry** of the analyse/basin windows in `QSettings`
   (basemap + decimals are already persisted — same pattern).
9. **Export buttons in the Analyse windows** — Plotly's modebar already does PNG;
   add "Save as HTML" (self-contained, shareable with colleagues) — it's just
   writing the temp HTML already generated to a user-chosen path.
10. **Tooltips on settings keys** in the editor, looked up from `metaNetcdf.xml`
    (already parsed for the Analyse windows) — hover `discharge` → its
    long_name/description.

---

## 3. Streamlining / making it more effective

> **STATUS: §3.1 implemented on 2026-07-03** (default ON; Configure ▸ "Run model in
> separate process" toggles back to the in-process worker). Design: child process
> (`src/gui/utils/cwatm_model_runner.py`, spawned via QProcess by
> `cwatm_process_worker.py`) streams model output live over the stdout pipe and
> reuses the existing model-side progress hook through `@@CWATM_GUI:...@@` marker
> lines — the exact opposite of the earlier failed attempt
> (`cwatm_subprocess_runner.py`), which buffered everything into a JSON file
> written only at run end (no live output, no progress) and passed `None` as the
> GUI object. Stop is now a real kill (measured instant); a model crash cannot
> take down the GUI. Frozen build: the spec now produces a second lightweight
> `CWatM_model.exe` (console subsystem, spawned with CREATE_NO_WINDOW), with
> `CWatM_GUI.exe --run-cwatm` as fallback — **the frozen path needs one rebuild to
> be tested**. Verified from source: full 5-step Morava run end-to-end through the
> real main window (output box, progress clock, elapsed label, result), kill test,
> missing-file error path, and the in-process fallback.

**3.1 The big one: run CWatM in a subprocess, not in-process.**
Today the model runs in a `QThread` in the GUI's interpreter. Consequences already
being paid for:
- `_fresh_cwatm()` must purge `sys.modules` of the whole `cwatm.*` tree every run to
  fight stale module state (`cwatm_worker.py:27-42`);
- Stop is *cooperative* (`should_stop`) — a run hung inside C code (netCDF read on a
  dead share) cannot be stopped;
- `_cleanup_worker_files` walks **every object in the interpreter** via
  `gc.get_objects()` to find open netCDF handles;
- the global excepthook must intercept `SystemExit` because CWatM may call
  `sys.exit()` deep inside (`cwatm_gui.py:125-132`);
- a hard crash (segfault in a C extension) takes the whole GUI down.

`cwatm_subprocess_runner.py` shows this was already considered. Running the model
via `QProcess` (stream stdout live into the output box — QProcess gives that
natively) eliminates all four hacks at once, makes Stop a real `kill()`, keeps GUI
memory flat between runs, and enables the run queue (§2.7). This is the
highest-leverage architectural change available. The progress-clock hook in
`cwatm/management_modules/output.py` would need a protocol replacement — the model
already prints per-timestep `\r date discharge` lines, which the GUI side can parse
for progress; no cwatm edit needed.

> **STATUS: §3.2 implemented on 2026-07-03.** `src/gui/widgets/settings_editor.py`
> (`SettingsEditor`, a `QPlainTextEdit` + `IniHighlighter`) replaced the HTML
> pipeline: the document IS the settings file at all times, saving is
> `toPlainText()`, dirty tracking is the native `modificationChanged`. Folding
> hides a section's blocks (`QTextBlock.setVisible(False)`) without removing them
> — folded sections are saved/searched normally. The gutter now shows **file**
> line numbers plus ▾/▸ fold markers (click to toggle); double-clicking a
> `[SECTION]` header folds it too. `generate_clean_settings_content` /
> `reconstruct_content_from_sections`, the `[-]`/`[+]` indicator text, the
> `collapsed_sections`/`temp_content_storage` state and the dead
> `run_configuration` were deleted (~450 lines net). Find/Replace/jump auto-unfold
> a hit inside a folded section (`reveal_cursor`). Verified offscreen against the
> real main window: load → fold all → edit → save-while-folded is byte-identical
> to the editor content (no indicator leakage), fold state survives save.

**3.2 Editor: replace the HTML-in-QTextEdit pipeline with `QSyntaxHighlighter`.**
The current design formats the INI into HTML, then needs
`generate_clean_settings_content` / `parse_content_into_sections` /
`reconstruct_content_from_sections` (~200 lines) to *undo* the formatting before
saving, plus `_suppress_dirty` guards around every re-render. A `QPlainTextEdit` +
`QSyntaxHighlighter` keeps the document as **plain text at all times** — saving is
`toPlainText()`, dirty tracking is the document's native `modificationChanged`, and
the whole clean/reconstruct pipeline (a standing source of "saved file differs from
screen" bugs) disappears. Folding is the one feature to re-implement (custom
block-hiding is well-trodden in Qt). Big refactor, big simplification.

> **STATUS: §3.3 implemented on 2026-07-03.** Both Analyse windows now use the
> process-wide cached lookup in `src/gui/utils/meta_netcdf.py` (`get_meta`; parsed
> once per process); their private `_meta_xml_path`/regex-scan copies were removed.

**3.3 Cache `metaNetcdf.xml` parsing** — both analyse windows regex-scan the file
per open; parse once into a dict at first use.

> **STATUS: §3.4 implemented on 2026-07-03.** Frames are built one timestep at a
> time from the lazily-read dataset as float32, with `zmin`/`zmax` tracked
> incrementally (no full-array concatenate), and the Python-side frame list is
> released after the HTML is rendered (`self.frames = None` in `_show_map`).
> "Display timeserie" re-reads the clicked cell lazily from the file
> (`_point_series` via the remembered `_point_source` selection).

**3.4 NetCDF window memory** — `_load` materialises every timestep into
`self.frames` up-front. For big daily outputs that's hundreds of MB. xarray is lazy
by nature; extract frames on demand (subsampling with `_MAX_FRAMES` already exists,
so the animation-frame HTML wouldn't change).

---

## 4. PyInstaller / .exe — faster **startup** (the part users feel)

The build settings are already right (onedir, `upx=False`, warm cache, splash,
network-share copy fix). The remaining wins are all about *what happens at launch*:

> **STATUS: §4.1 implemented on 2026-07-03.** `main_window.py` no longer imports
> `basin_viewer` (numpy/xarray/rasterio/QtWebEngine) or `check_data_window`
> (→ `cwatm.run_cwatm` → scipy/pandas/netCDF4) at module level — both are
> imported lazily at their call sites (`show_basin`, the mask/gauge/PathOut
> checks, `open_check_data_window`); `check_data_window.py` itself now imports
> `run_cwatm`/`netCDF4` inside its methods, and `cwatm_worker.py`'s module-level
> cwatm preload was removed. `cwatm_gui.py` warms `cwatm.run_cwatm` + `xarray` +
> `rasterio` up in a daemon thread ~0.5 s after the window shows. **Measured
> (source, network share): `main_window` import 58 s → 1.5 s**; window up in
> ~5 s total instead of ~60 s.

**4.1 The startup cost is the import cascade — defer it. (Biggest exe-speed win, no
build change.)**
`cwatm_gui.py:33` imports `main_window`, which at module level imports
`basin_viewer` (→ **xarray + rasterio**, `basin_viewer.py:24-25`), `cwatm.run_cwatm`
(→ **scipy, pandas, netCDF4**, `main_window.py:43`), and `cwatm_worker` (which
deliberately preloads cwatm again). So the splash sits there while the entire
scientific stack initialises before the window can appear. Fix pattern:
- import only PySide6 + stdlib at startup; show the window;
- lazy-import `basin_viewer` inside `show_basin` (the *dead* copy at line 2111
  already did this!), lazy-import `find_largest_ups_gauge` / `build_mask_context`
  etc. at call time;
- warm up `cwatm.run_cwatm` in a background thread *after* the window is up (keeps
  "first Run is responsive" without paying for it at launch).

Expected effect: window visible in a small fraction of the current cold-start time;
heavy libs load while the user is already reading their INI file. This beats any
packaging tool change, including Nuitka.

> **STATUS: §4.2 implemented on 2026-07-03.** The spec's `datas` now ship only
> `cwatm/metaNetcdf.xml` (+ assets and the Help markdown); the `cwatm/` and
> `src/` trees are no longer bundled as datas (their code is in the PYZ —
> `collect_submodules('cwatm')` + new `collect_submodules('src')`, needed since
> the datas tree no longer doubles as an import fallback). The `t5.*` routing
> libraries now land at `cwatm/hydrological_modules/routing_reservoirs/` — the
> path `globals.py` actually resolves from `__file__` (the old copies at the
> bundle root were never found; the tree-as-datas had been masking that).

**4.2 Stop bundling the `cwatm` and `src` source trees twice.**
The spec ships `cwatm/` and `src/` wholesale as `datas`
(`cwatm_gui_dir.spec:111-113`) *and* compiles them into the PYZ via
`collect_submodules('cwatm')`. Every `.py` (plus every `__pycache__/*.pyc`) is
therefore in the bundle twice, and stray working files ride along. Include only the
**non-code data** cwatm needs at runtime (`metaNetcdf.xml`, `t5*.dll/.so`, any
`.txt/.xml` resources) instead of the whole tree. Smaller folder → faster first
launch (fewer files for the OS/AV to touch) and faster COLLECT on the SMB share.

**4.3 Antivirus is a hidden startup tax.** 343 DLLs on first launch get individually
scanned by Defender; on a network share this dominates cold start. Two mitigations:
ship/install to a **local** disk (also echoes the TODO note — build locally,
robocopy back), and **code-sign** the exe (also kills the SmartScreen warning users
see).

> **STATUS: §4.4 checked on 2026-07-03 — NOT applied, the premise is wrong.**
> `openpyxl` IS used at runtime: cwatm reads xlsx settings sheets via
> `pd.read_excel` (`cwatm/hydrological_modules/initcondition.py`,
> `lakes_reservoirs.py` — crops, reservoirs, wastewater, desalination). Excluding
> it would break model runs that use those options. A note in the spec's
> `excludes` documents this so it is not re-attempted.

**4.4 Trim what is verifiably unused.** `openpyxl` / `et_xmlfile` are in the venv
but referenced nowhere in GUI code (pandas pulls them in only for Excel I/O) — add
to `excludes` after a smoke test. Don't chase scipy (cwatm uses it).

> **STATUS: §4.5 implemented on 2026-07-03.** The splash now shows "Loading
> Qt ..." → "Loading user interface ..." between the import stages and is closed
> only **after** `window.show()` (before, it closed at import time and the user
> stared at nothing until the window appeared). With §4.1 the whole covered span
> is a few seconds.

**4.5 Splash polish (free):** `pyi_splash.update_text()` currently runs only once,
*after* all imports finish (`cwatm_gui.py:93-98`). If any heavy top-level imports
remain, interleave `update_text("loading rasterio…")` calls between them so the
splash shows progress instead of appearing frozen. (With §4.1 done, this matters
less.)

> **STATUS: §4.6 done on 2026-07-03.** System Python and the project `venv/` are
> on Python 3.12.10 (PySide6 6.11.1, numpy 2.5, pandas 3.0, PyInstaller 6.21).
> §4.3 remains **operational** (no code): install/ship the exe folder to a local
> disk, and code-sign the exe when a certificate is available.

**4.6 Upgrade Python 3.8 → 3.11/3.12 (also a *runtime* win).**
Python 3.8.10 is EOL (Oct 2024). Python 3.11 is ~25–60 % faster on pure-Python code
— and the CWatM model loop *is* pure Python, so **model runs launched from the GUI
get faster**, plus faster GUI logic, newer PySide6/PyInstaller (better hooks,
smaller bundles), and current numpy/pandas. This delivers most of what the Nuitka
plan promises with far less risk; do this **before** attempting Nuitka. (Nuitka
remains valid per `nuitka_plan.md`, but as the plan itself notes, it costs long
C-compile builds and won't speed numpy/rasterio work.)

**4.7 Keep as-is:** onedir over onefile (onefile would re-unpack 705 MB per launch —
never), `upx=False`, no `--clean`, `console=False`, the SMB copyfile patch,
`--disable-gpu` (reliability over speed; optionally allow an env-var override for
machines with good GPUs).

---

## 5. Priority shortlist

| # | Action | Effort | Payoff |
|---|--------|--------|--------|
| 1 | Defer heavy imports; window first, libs later (§4.1) | Low | Cold-start feels several times faster |
| 2 | Delete duplicate `show_basin`/`open_check_data_window` (§1.1) | Trivial | Removes a live foot-gun |
| 3 | Fix `requirements.txt` encoding + split build deps (§1.8) | Trivial | Reproducible envs |
| 4 | Output box → `QPlainTextEdit`, keep log file open per run (§1.6, §1.4) | Low | Smoother runs, 50× scrollback |
| 5 | ETA/elapsed + "Open PathOut" + drag-drop/CLI arg (§2.1–2.4) | Low | Daily-use quality of life |
| 6 | Python 3.11/3.12 migration (§4.6) | Medium | Faster model runs *and* GUI; supported stack |
| 7 | Subprocess-based model execution (§3.1) | Medium–High | Real Stop, crash isolation, batch runs |
| 8 | Editor → QSyntaxHighlighter architecture (§3.2) | High | Eliminates a whole bug class |
| 9 | Spec: stop double-bundling cwatm/src; code-sign (§4.2–4.3) | Low–Medium | Smaller, faster, trusted exe |

---

*No code was changed as part of this analysis. All line numbers refer to the state
of the repository on 2026-07-02.*
