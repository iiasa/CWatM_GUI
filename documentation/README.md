# Graphical User Interface for CWatM

A desktop GUI for the Community Water Model (CWatM) by the International Institute for
Applied Systems Analysis (IIASA). Load, parse, edit and manage CWatM settings (`.ini`)
files, run the model directly, and visualise/validate its inputs and results — without
the command line.

> **Full manual:** see **[CWatM_GUI_Documentation.md](CWatM_GUI_Documentation.md)**.
> **Feature & usage tour:** **[CWatM_GUI_Features.md](CWatM_GUI_Features.md)**.
> **Common questions:** **[CWatM_GUI_FAQ.md](CWatM_GUI_FAQ.md)**.
> Developer reference is **[CLAUDE.md](../CLAUDE.md)** (menu bar, invariants,
> architecture, build) with per-feature deep dives in
> **[CWatM_GUI_Internals.md](CWatM_GUI_Internals.md)**.

## Key benefits

- **Menu-driven** interface (File · Settings · Tools · RUN CWATM · Configure · Analyse ·
  CWatM AI · Help · Info).
- Live settings editing with syntax highlighting, collapsible sections and tabs for
  several settings files at once.
- Integrated model execution with a progress clock, live discharge sparkline and
  real-time output — in the main window, in separate windows, or as a parallel batch.
- Built-in validation: **Check settingsfile** (missing files, date ordering, option
  dependencies, output-keyword grammar, forcing coverage), gauges-in-basin and PathOut
  checks, and **Check Data**.
- Result analysis without leaving the GUI: basin map, NetCDF maps, timeseries,
  water-balance sunburst and Sankey flow diagram.

**Target audience:** researchers, hydrologists, water-resource managers and students
working with the CWatM hydrological model.

## Quick start

```bash
pip install -r ../requirements.txt
python cwatm_gui.py
```

Installing the pinned `requirements.txt` matters: beyond the scientific stack
(NumPy/pandas/SciPy/xarray/netCDF4/rasterio) the GUI needs **PySide6 Addons**
(QtWebEngine), **folium** and **plotly** for the map and plot windows, **requests** for
OSM tiles and **openpyxl** for the Excel settings sheets. A partial install leaves those
windows blank rather than failing loudly.

1. **File ▸ Load .ini** (Ctrl+O) — load a settings file (parses automatically).
2. Edit **Start/Spin/End Date, PathOut, MaskMap, Gauges** — changes auto-apply to the
   content in memory; **Save / Save As** turn blue to show unsaved changes.
   *(What changed in this and earlier releases: [CHANGELOG.md](CHANGELOG.md).)*
3. **File ▸ Save .ini** (Ctrl+S) — write to disk.
4. **RUN CWATM ▸ Run CWATM** (Ctrl+R) — run the model (select again to stop).

## Interface at a glance

```
[banner: CWatM GUI · "The Community Water Model User Interface" · IIASA]
[menu bar: File Settings Tools RUN CWATM Configure │ Analyse │ CWatM AI  Help Info  ⋮]
┌ left control panel ─────────────┬ right editor panel ───────────────┐
│ Loaded: <file>          Title   │ Save  Save As  Fold All  Unfold    │
│ Start / Spin / End Date         │ All  Top  Down  Font+ Font- Level  │
│ date timeline                   ├ tab bar (one per settings file) ───┤
│ PathOut / MaskMap / Gauges      │ syntax-highlighted settings text   │
│ RUN CWatM  + warning label      │ with foldable sections + gutter    │
│ output box                      │                                    │
│ progress clock · sparkline      │                                    │
└─────────────────────────────────┴────────────────────────────────────┘
```

The GUI is menu-driven: the former **Load Text, Actualize, Options, Show Basin, Check
Data** buttons and the **Write output** checkbox were moved into menus (Actualize was
removed — field changes now auto-apply). **Save / Save As / Fold All / Unfold All /
Top / Down** and **RUN CWatM** remain as buttons *and* menu items.

## Menus (summary)

| Menu | Items (shortcuts) |
|------|-------------------|
| **File** | Load .ini (Ctrl+O), Reload (Ctrl+L), Save .ini (Ctrl+S), Save As (Ctrl+Alt+S), Change Working Dir, recent files, Exit |
| **Settings** | Fold All (Alt+0), Unfold All (Alt+Shift+0), Top (Alt+T), Down (Alt+D), Find (Ctrl+F), Find next/previous (F3 / Shift+F3), Replace (Ctrl+H), Undo (Ctrl+Z), Redo (Ctrl+Y), Bookmarks (Ctrl+F2, F2, Shift+F2, Ctrl+Shift+F2), Goto last change (F5), Check settingsfile (F4), Compare settings, Compare Tab (F8, Expert only) |
| **Tools** | Show Basin, Set max Gauge · Create PathOut Folder, Add output Watercycle, Add output variables · Change Options, Excel Crops/Reservoirs, Check Data, Restore settingsfile |
| **RUN CWATM** | Run CWATM (Ctrl+R), Journal of Runs, Windowed Run CWatM, Batch Run… |
| **Configure** | Preferences… (Ctrl+, — every GUI setting; also the ⋮ button in the menu bar's right corner) |
| **Analyse** | Open PathOut Folder, Output Explorer, Timeseries, NetCDF, Watercycle, Flow Diagram |
| **CWatM AI** | (a button, not a dropdown) chat about CWatM, answered by Google NotebookLM |
| **Help** | CWatM GUI Documentation, CWatM GUI Features, FAQ, CWatM Homepage |
| **Info** | About CWatM |

Some entries are hidden at lower **skill levels** (Preferences ▸ Editor & Dates ▸ Skill
of user): a Beginner does not see the advanced Tools/RUN/Analyse entries, and *Compare
Tab* is Expert-only.

## Features

- **Settings editing** — auto-parse on load; syntax highlighting, bold section headers
  with fold markers, a line-number gutter, hover tooltips for CWatM variable names,
  bookmarks and changed-line highlighting; whitespace preserved (what you save is
  exactly the editor text).
- **Tabs** — one tab per settings file above the editor (Expert level, *Preferences ▸
  Editor & Dates ▸ Use Tabs*); the active tab is what every window works on, each tab
  keeps its own undo/bookmarks/folds, and a tab's right-click offers *Delete / Copy /
  Run CWatM / Link scrolling*.
- **Fields** — Start/Spin/End Date (chronological validation; integer SpinUp/StepEnd
  interpreted as `StepStart + (N−1)` days), PathOut, MaskMap, and **Gauges** (linked to
  the settings `Gauges` entry). Edits **auto-apply in memory** (debounced); disk writes
  happen only on Save. A three-handle **date timeline** and calendar popups show the
  meteo-forcing coverage.
- **Unsaved-changes indicator** — Save / Save As turn blue; **Exit** prompts to save
  (once per dirty tab).
- **Gauge / PathOut checks** — the Gauges text is blue if all gauges are inside the
  basin, red otherwise; a red warning appears next to RUN CWatM. Works for file-based
  and coordinate-based MaskMaps (basin generated internally, cached). PathOut existence
  is checked with placeholder resolution.
- **Check settingsfile (F4)** — marks every value that names a file which does not
  exist, plus semantic checks: date ordering, `[OPTIONS]` dependencies, output-keyword
  grammar and variable names, array indices, and whether the run window fits inside the
  meteo-forcing time coverage. A summary goes to the output box; F4 again clears it.
- **Helper tools** — **Set max Gauge** (largest upstream cell inside the mask),
  **Create PathOut Folder**, **Add output Watercycle**, **Add output variables**
  (a filterable, topic-grouped picker of the metaNetcdf variables that fit the current
  options).
- **Model execution** — runs in a separate OS process (real Stop, crash isolation);
  live progress clock, discharge sparkline and a selectable/copyable output box, errors
  in dark red. Also **Windowed Run** (several in parallel), **Batch Run** (scenario
  table, N in parallel) and the **Journal of Runs**.
- **Output logging** — **Preferences ▸ Output ▸ Write output box** appends to
  `<PathOut>/cwatm_out.txt` (or a custom file via the **Output box file** field on the
  same page), with a dated header per run.
- **Analysis** — basin viewer (Leaflet/OSM), NetCDF map viewer, Timeseries plots with
  goodness-of-fit scores, water-balance **sunburst** and **Sankey** diagram, and the
  Output Explorer that dispatches each result file to the right viewer.
- **Themes** — Normal / Dark / Mikhail, switchable live (Preferences ▸ Display ▸ Mode).

## Project structure

```
cwatm_gui.py                            entry point (splash, app icon, exception handling)
src/gui/components/
    main_window.py                      main window: fields, checks, load/save, window openers
    menu_builder.py                     the menu bar and its persisted state
    run_controller.py                   start/stop the run, progress, run log
    output_box.py                       the CWatM output box
    tab_manager.py                      settings-file tabs (one editor per tab)
    config_parser.py                    INI parsing / date & settings extraction / updates
src/gui/managers/                       date widgets, file I/O, text display
src/gui/widgets/
    settings_editor.py                  the plain-text settings editor + highlighting + folding
    line_number_gutter.py               gutter (line numbers, fold markers, bookmarks)
    preferences_window.py               Configure > Preferences…
    options_window.py                   [OPTIONS] boolean editor
    check_data_window.py                Check Data / NetCDF comparison
    excel_sheet_window.py               Excel Crops/Reservoirs sheet editor
    output_variables_window.py          Add output variables picker
    compare_settings_window.py          Compare settings (side-by-side diff)
    restore_settings_window.py          Restore settingsfile from a result NetCDF
    hidden_run_window.py                Windowed Run CWatM
    batch_runner_window.py              Batch Run
    run_ledger_window.py                Journal of Runs
    output_explorer.py                  PathOut result tree
    basin_viewer.py / basin_viewer2.py  basin data helpers + the Leaflet basin map
    analysis_timeseries.py              Timeseries plot
    analysis_netcdf_base.py / _netcdf.py  NetCDF data layer + map viewer
    analysis_watercycle.py              water-balance sunburst
    analysis_flowdiagram.py             water-balance Sankey
    notebooklm_window.py                CWatM AI chat
    discharge_sparkline.py              live discharge trace next to the clock
src/gui/utils/                          theme, assets, geometry, logging, metrics,
                                        run ledger, worker processes, progress clock
```

## Requirements

Python **3.12** (the reference venv; 3.10+ is required for the CWatM AI window),
PySide6 + PySide6-Addons, NumPy, pandas, SciPy, xarray, netCDF4, rasterio, folium,
plotly, requests, openpyxl. Exact pins are in **`requirements.txt`** at the repo root.

Running on **Linux** from source is supported — see **`cwatm_gui_linux.md`** at the repo
root for system packages, the venv, `gui.sh` and remote X displays.

## Building the executable

The project venv is **`venv/`**. `cwatm_gui_dir.spec` is the one-folder build; it also
produces `CWatM_model.exe`, the lightweight child process used for every model run.

```powershell
venv\Scripts\Activate.ps1
python -m PyInstaller cwatm_gui_dir.spec --noconfirm
```

In practice a release is built with **`build_release.ps1`**, which mirrors the project to
a local disk first (PyInstaller over a network share is the dominant cost) and can also
compile the per-user installer with Inno Setup. See the *Building on the local disk*
section of [CLAUDE.md](../CLAUDE.md).

## Tests

```bash
pip install -r ../requirements.txt -r ../requirements_dev.txt
pytest
```

The suite covers the pure logic — cell formulas and autofill, goodness-of-fit metrics,
output-variable indices, the Copy Tab naming rule, the temp-page lifetime, the run
ledger, and the Check settingsfile semantic pass. No display is needed. Three standalone
checks run alongside it (and in CI): `tools/check_invariants.py`,
`tools/check_requirements.py` and `tools/import_all.py`.

## License & contact

See the `LICENSE` file. Developed by IIASA — info@iiasa.ac.at ·
[CWatM on GitHub](https://github.com/iiasa/CWatM).
