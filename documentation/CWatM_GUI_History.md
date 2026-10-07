# CWatM GUI — developer history

The **why it is like this** record for developers: renames, removed features, and the
story behind fixes and regressions. `CLAUDE.md` states only what is true *now*; when a
rule there exists because of something that went wrong, the story lives here.
User-facing release notes are in [`CHANGELOG.md`](CHANGELOG.md).

> **Editing:** add an entry here (newest first inside each section) when you rename,
> remove or fix something whose history explains a current rule. Keep the rule itself
> in `CLAUDE.md` (or `CWatM_GUI_Internals.md`) and link back if useful.

## Renames (old name → current name)

Where an internal name kept the old spelling, it is noted — do **not** "fix" those, they
are persisted keys or file names.

| Old | Current | Kept under the old name |
|-----|---------|-------------------------|
| "Load Text" button | File ▸ Load .ini | — |
| Settings ▸ Compress All | Settings ▸ Fold All | — |
| Settings ▸ Expand All | Settings ▸ Unfold All | — |
| Top-level **Excel** menu | Tools ▸ Excel Crops/Reservoirs (Setup & Data, below Change Options) | — |
| Tools ▸ Run Ledger | RUN CWATM ▸ Journal of Runs | the window, `utils/run_ledger.py`, `run_ledger.json` |
| RUN CWATM ▸ Hidden Run CWatM | RUN CWATM ▸ Windowed Run CWatM | module `hidden_run_window.py`, geometry key `hidden_run`, journal `kind="hidden"` |
| Tools ▸ Show Basin2 | Tools ▸ Show Basin (`basin_viewer2.py`) | the module name |
| Analyse ▸ NetCDF2 (`analysis_netcdf2.py`) | Analyse ▸ NetCDF (`analysis_netcdf.py`) | — |
| `analysis_netcdf.py` (data layer + Plotly viewer) | `analysis_netcdf_base.py` (`NetcdfDataBase`, data layer only) | — |
| Check settingsfile + separate *Clear checking* (Shift+F4) | one F4 toggle item (`toggle_check_settings`) | — |
| Shop animals `fish` / `sailboat` | `trout` / `bottle` (migration `20261007120000_shop_animals_v2.sql`; purchases cascade, nobody lost an animal) | old emoji names map to the same codes in `account_shop.ANIMAL_CODES` |
| `t5*` routing libraries | `t6*` (`t6.dll`, `t6_linux.so`, `t6_mac_arm64.so`, `t6_mac_x86_64.so`) — since CWatM 1.07 | — |

## Removed features

- **Former side buttons** (Load Text, Actualize, Options, Show Basin, Check Data) and the
  **"Write output" checkbox** — removed from the code, not just hidden; their actions
  are in the menus. **Actualize** had also saved to disk; it was replaced by the
  debounced auto-apply of field changes (which never saves).
- **Classic native-canvas / Mercator basin viewer** (`BasinWindow`/`BasinCanvas` in
  `basin_viewer.py`) — replaced by the folium EPSG:4326 Show Basin.
- **Plotly heatmap NetCDF viewer** — replaced by the folium/Leaflet NetCDF viewer.
- **Restore settingsfile ▸ Show in Journal** and its Close button — removed outright.
- **🎤 Voice dictation** (CWatM AI) and its `speech_recognition`/`pyaudio` libraries.
- **Use Modflow pre-warm** setting — runs are child processes, so a GUI-side flopy
  import never helped them.
- **Run model in separate process** — no longer shown in the UI; the action is still
  created standalone (`_init_configure_state`, default ON, persisted `run/subprocess`).
- **Skill-level menu radios** — `_sync_level_menu` / `_level_menu_actions` are the
  leftover, now a guarded no-op kept for a future menu.
- **Single-file `cwatm_gui.spec`** — only the one-folder `cwatm_gui_dir.spec` remains.
- **`build_env/`** — a copied venv, deprecated; the project venv is `venv/`.
- **`cwatm`/`src` trees as PyInstaller datas** — code ships only in the PYZ (report §4.2).

## Fixes and regressions behind current rules

### Startup: `basin_viewer` pulled in the whole model during `__init__`
Rule in `CLAUDE.md`: *lazy-importing the module is not enough on its own.*
`basin_viewer.py` used to import `xarray`/`rasterio`/`cwatm.run_cwatm` at its own
**module top level**, and the module gets imported the instant *any* settings file is
loaded into a tab (the gauge-in-mask check, `main_window._rebuild_mask_cache` →
`basin_viewer.build_mask_context`) — which fires **during `CWatMMainWindow.__init__`**
for the construction-time empty first tab, not only when a user opens Show Basin. A
cProfile trace of `CWatMMainWindow()` construction caught this directly: it was the
single largest cost, pulling in xarray/rasterio **and the entire CWatM model tree**
(`cwatm.run_cwatm` → `cwatm_model`/`cwatm_initial`/`readmeteo`/…) even for a raster
MaskMap that never calls `mainwarm`. Fixed two ways, both in `basin_viewer.py`:
(1) `xarray`/`rasterio` are imported **inside** the three functions that call them
(`_load_netcdf_data`, `_load_mask_data`'s and `build_mask_context`'s raster branches);
(2) `import cwatm.run_cwatm` moved into the one branch that calls `mainwarm` (a
coordinate-based MaskMap). On top of that, `tab_manager.build_settings_tabs`'s
construction-time tab passes `defer_warnings=True` through
`add_settings_tab`/`switch_to_tab`/`_activate_tab`, scheduling that one check via
`QTimer.singleShot(0, …)` (`_deferred_warnings`). Verified: right after
`CWatMMainWindow()` returns, neither `basin_viewer` nor `xarray`/`rasterio`/
`cwatm.run_cwatm` are in `sys.modules`.

### Startup: window flash after the speedup
`_prewarm_webengine` (`cwatm_gui.py`) used to create its throw-away `QWebEngineView` as
a **child of the already-shown main window**. Embedding the first-ever
`QWebEngineView` into an already-native, visible top-level window is a known
Qt-on-Windows trigger for that ancestor's HWND to be destroyed and recreated —
invisible when construction took ~6 s, a visible flash (confirmed with
`IsWindowVisible`/`IsZoomed` polling at 20 ms) once construction dropped under 1 s.
Fixed by anchoring the pre-warm view to its **own never-shown top-level `QWidget`**
(`WA_DontShowOnScreen`). Re-polled after the fix: the main window's HWND appears once,
already maximized, and never changes again.

### Frozen NetCDF viewer: `dask.widgets` trimmed
*"Error loading NetCDF data: cannot import name 'get_template' from 'dask.widgets'"* —
an over-eager spec trim excluded `dask.widgets`, but `dask/array/core.py` imports
`get_template` from it at **module level**, so `dask.array` (needed for
`xr.open_dataset(..., chunks={})`) broke. `dask.widgets` is tiny (~10 files, ~10 KB) and
is now deliberately kept.

### Gauge-in-mask check wrong after Copy Mask / Copy Gauge (2026-07-03)
For a coordinate-based MaskMap, running `mainwarm -vgm` on the **on-disk** file gave
wrong "gauge not inside" results right after Copy Mask / Copy Gauge. The basin is now
generated from a temporary .ini holding the **live** content (`_live_content()`).

### MODFLOW child started a second model run
CWatM runs MODFLOW in a `multiprocessing` **spawn** child, which re-imports the main
script as `__mp_main__` with the parent's `sys.argv`. With `cwatm_gui.py`'s
`--run-cwatm` dispatch unguarded, it started a second model run inside the MODFLOW
child (*"start a new process before … bootstrapping phase"*). Now guarded by
`if __name__ == "__main__"`, plus `multiprocessing.freeze_support()`, and the source
child is `cwatm_model.py` (a few lines to re-import, not Qt + the GUI).

### Stray U+2029 in `main_window.py`
A literal paragraph separator put every line-based tool one line out of step
(`str.splitlines()` breaks on it, the tokenizer does not). It is written as an escape
now and `tools/check_invariants.py` rejects exotic line separators.

### Defects the test suite found (all fixed)
- Cell values like `1-2`, `10-2020`, `2026-08-13` were auto-detected as formulas, and
  the **computed number** was written into the workbook CWatM reads.
- `=$B$2` failed standalone — `$` is now stripped before `ast.parse`.
- Journal rows were keyed on (ts, settings, pathout), so deleting one of two parallel
  runs of the same file deleted both — now keyed on `uid` (old key kept as fallback).

### Smaller ones
- **Batch Run temp files** were keyed by sanitised scenario name; `run 1` and `run_1`
  sanitised alike and clobbered each other — now keyed by row number.
- **Drop on the settings editor** used to insert the path as text instead of loading
  the file — `SettingsEditor.fileDropped` now loads it.
- **Bandit `exclude_dirs: cwatm`** excluded the whole `cwatmpublic` repo (path-substring
  match) — explicit targets only now.
- **Shop migration** (`20261001130000_shop.sql`): accounts that existed when it was
  pushed were **granted** Advanced + Expert (price 0, `granted = true`).

## Report § cross-references
Older notes cite sections of the GUI review report: §3.1 subprocess run · §3.2
plain-text editor · §3.3 metaNetcdf hover tooltips · §4.1 fast startup / lazy imports ·
§4.2 code only in the PYZ · §4.4 openpyxl for xlsx settings sheets · §4.5 splash closes
after `window.show()`.
