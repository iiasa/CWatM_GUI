# CWatM GUI Application

> ## ⛔ HARD RULE — never modify the CWatM submodule
> **Never touch or change any code under `cwatm/`** (the CWatM model submodule).
> All work happens in the GUI code (`cwatm_gui.py`, `src/gui/**`, specs, docs, assets).
> If a problem appears to originate in `cwatm/`, diagnose and **explain** it, and fix it
> on the GUI side or work around it — do **not** edit CWatM source. Reading `cwatm/`
> files to understand behaviour is fine; editing them is not.

## Overview
This is a graphical user interface for the Community Water Model (CWatM) developed by IIASA. The application allows users to load, parse, edit, and manage CWatM configuration files with an intuitive GUI.

> **Three docs:** this file (`CLAUDE.md`) is the concise developer reference — menu bar,
> behavioral notes/invariants, architecture, requirements, build.
> [`documentation/CWatM_GUI_Internals.md`](documentation/CWatM_GUI_Internals.md) holds the
> **per-feature deep dives** (secondary windows + data-visualization viewers).
> [`documentation/CWatM_GUI_Features.md`](documentation/CWatM_GUI_Features.md) is the
> **user-facing** feature & usage tour.

## Contents

**Start here (the rules that keep the app working):** the ⛔ hard rule above · the
**fast-startup / lazy-import rule** and **theme-token rule** (Development Notes) ·
**CWatM Integration** (subprocess run model).

**In this file (CLAUDE.md):**
- **UI & behaviour** — [Menu Bar & Keyboard Shortcuts](#menu-bar--keyboard-shortcuts-current-ui) · [Preferences window](#preferences-window-configure--preferences) · [Behavioral notes](#behavioral-notes) · [Gauges, mask and PathOut checks](#gauges-mask-and-pathout-checks) · [Check settingsfile](#check-settingsfile-settings-menu) · [Output-box log file](#output-box-log-file-preferences--output)
- **Architecture** — [Core Modules](#core-modules) · [Module Dependencies](#module-dependencies) · [CWatM Integration](#cwatm-integration)
- **Build & deps** — [Technical Details / Requirements](#requirements) · [Installation](#installation) · [Virtual environment & building the executable](#virtual-environment--building-the-executable) · **[Building on the local disk — `build_release.ps1`](#building-on-the-local-disk--build_releaseps1)** (how a release is actually built) · [Watercycle template scripts](#watercycle-template-scripts-repo-root--canonical-balance-computation)
- **Development Notes** (fast-startup, thread-safety, styling rules)

**In [`documentation/CWatM_GUI_Internals.md`](documentation/CWatM_GUI_Internals.md)** (deep dives, kept out of the always-loaded reference):
- **Secondary windows** — Settings-file tabs · Excel sheet editor · Compare settings · Output Explorer · Windowed Run CWatM · Batch Run · Journal of Runs · Restore settingsfile · Change Options · Check Data · Add output variables · CWatM AI
- **Data visualization** — Basin viewer (infra + folium) · Timeseries · NetCDF · Watercycle · Flow Diagram

> **Editing the docs:** keep *always-true rules and invariants* in `CLAUDE.md`; put
> per-feature window/rendering detail in `CWatM_GUI_Internals.md`; put user-facing usage
> in `CWatM_GUI_Features.md`; put pure history (dated fixes, "report §" cross-refs) in
> commit messages, not inline. State a duplicated fact once and cross-reference.

## Menu Bar & Keyboard Shortcuts (current UI)

The GUI is now **menu-driven**. A banner (CWatM icon, title, the centered text
"The Community Water Model User Interface", and the IIASA logo) sits at the very
top, with the menu bar directly **below the banner**. Most former side buttons were
removed from view and their actions live in menus.

Menu bar (left → right, grouped by `│` separators into "run CWatM", "analyse
results", "Help & Info"): **File · Settings · Tools · RUN CWATM ·
Configure │ Analyse │ CWatM AI · Help · Info** (**CWatM AI** is a clickable
top-level action — a button, not a dropdown — placed left of Help), plus a **⋮**
button in the bar's **right corner** that opens the Preferences window.

| Menu | Item | Shortcut | Action |
|------|------|----------|--------|
| File | Load .ini | Ctrl+O | Load a settings file (was the "Load Text" button) |
| File | Reload | Ctrl+L | Reload the current file from disk (prompts if there are unsaved changes) |
| File | Save .ini | Ctrl+S | Save to current file |
| File | Save As | Ctrl+Alt+S | Save to a new file |
| File | Change Working Dir | — | Pick the directory relative settings paths resolve against (`_working_dir_override`, per tab) |
| File | 1. … 6. (recent files) | — | Up to 6 recent settings files listed **directly** in the File menu between Save As and Exit (persisted via `QSettings`); rebuilt on open |
| File | Exit | — | Quit (prompts Save/Discard/Cancel if there are unsaved changes) |
| Settings | _(section headers)_ | — | The Settings menu is grouped into **five titled sections** — **View** · **Find & Replace** · **Edit** · **Bookmarks & Changes** · **Check & Compare** — rendered as bold, disabled header rows via `menu_builder._add_menu_section` (same helper as the Tools sections; **not** `QMenu.addSection`). The rows below follow that order |
| Settings | Fold All | Alt+0 | Collapse all sections (was "Compress All") |
| Settings | Unfold All | Alt+Shift+0 | Expand all sections (was "Expand All") |
| Settings | Top | Alt+T | Jump to start of file |
| Settings | Down | Alt+D | Jump to end of file |
| Settings | Find | Ctrl+F | Combined non-modal **Find & Replace** window, opened on the **Find** tab: shared "Find:" box above the tabs, **Find Next / Count** (matches in the file, shown in the window's own status bar) **/ Close**; Enter = Find Next; opens 100 px left of centre |
| Settings | Find next | F3 | Repeat the last Find (wraps around; also works while the Find window has focus) |
| Settings | Find previous | Shift+F3 | Find the previous occurrence (backwards, wraps around) |
| Settings | Replace | Ctrl+H | The same Find & Replace window, opened on the **Replace** tab (Replace with box + Find next / Replace / Replace all / Close). **Replace all in selection** checkbox: disabled+unchecked without an editor selection; auto-ticked when the Replace tab is entered with a selection; a selection made while the window is open enables it (user toggles) |
| Settings | Undo | Ctrl+Z | Undo an editor change **or a left-window field change** (Date/PathOut/MaskMap/Gauges) |
| Settings | Redo | Ctrl+Y | Redo an editor change **or a left-window field change** |
| Settings | Toggle Bookmark | Ctrl+F2 | Toggle a bookmark on the editor's current line (orange dot in the gutter) |
| Settings | Next Bookmark | F2 | Jump to the next bookmarked line (wraps; unfolds if hidden) |
| Settings | Previous Bookmark | Shift+F2 | Jump to the previous bookmarked line (wraps) |
| Settings | Clear all Bookmarks | Ctrl+Shift+F2 | Remove every bookmark |
| Settings | Goto last change | F5 | Jump to the most recently changed line (after a separator; unfolds if hidden) |
| Settings | Check settingsfile / Clear checking | F4 | **One toggle item** (`toggle_check_settings`): when no marks are shown it scans the editor content — every value identified as a filename/path whose file does not exist gets its line **marked red + bookmarked** (F2 to jump), **plus semantic checks** (StepStart ≤ SpinUp ≤ StepEnd date ordering, **option dependencies** e.g. modflow-on-without-its-keys, and the run window inside the **meteo forcing** NetCDF time coverage), a summary is written to the output box, and the item **relabels to "Clear checking"**; pressing F4 again (now "Clear checking") removes the red marks + check-owned bookmarks (the user's own bookmarks are kept) and relabels back. The label is re-synced to the real state (`_error_rows`/`_inactive_rows`, via `_refresh_check_settings_label`) whenever the Settings menu opens — see Check settingsfile below |
| Settings | Compare settings | — | (last item, separator above) Side-by-side diff of two settings files — left = the **active tab**'s settings (preloaded), right has a **Load** button and, **with more than one tab open, is preloaded with the neighbouring tab** (the one left of the active tab, or right of it when the active tab is the first — `compare_partner_source`); files aligned with gray filler, differing lines **orange**, one synced scrollbar on the right, Next/Previous Diff, File/History/Settings menus — see `CWatM_GUI_Internals.md` |
| Settings | Compare Tab | F8 | _(last item, **Expert only** — `_expert_only_actions`, hidden **and disabled** for Beginner/Advanced so F8 does nothing there; it acts on the tabs, which are Expert-only themselves)_ **In-place** diff against the **neighbouring tab** (the same partner as Compare settings: the tab left of the active one, or right of it when the active tab is the first — `compare_partner_index`): every differing line is coloured **light green at 50 % opacity** in **both** tabs, so switching between them shows the differences from either side. A **toggle** — F8 again clears the colouring (`toggle_compare_tab` / `compare_marks_shown` / `clear_compare_tab`, rows from `diff_line_rows`; **no** alignment filler, the marks sit on the documents' own line numbers). Nothing is written; needs a second tab |
| Tools | Excel Crops/Reservoirs | — | _(Setup & Data, directly below Change Options — there is **no** top-level Excel menu any more)_ Open the settings `Excel_settings_file` (placeholders resolved) in an editable table reproducing the sheet's cell colours. **All** the workbook's sheets sit on an Excel-style **tab bar below the table**; works like Excel — formulas, Ctrl+C/X/V + Delete on blocks, a fill handle, a symbol toolbar and per-sheet undo/redo over cell edits *and* column/row inserts+deletes. Load / Reload / Save / Save As, and Reload / Load / **closing** ask Save-Discard-Cancel while a sheet holds edits — see `CWatM_GUI_Internals.md` |
| Tools | _(section headers)_ | — | The Tools menu is grouped into **three titled sections** — **Basin & Gauges** · **Outputs** · **Setup & Data** — rendered as bold, disabled header rows via `menu_builder._add_menu_section` (same helper as the Settings sections; **not** `QMenu.addSection`, whose title text the native windows11 style does not draw). The rows below are listed by section |
| Tools | Change Options | — | _(Setup & Data)_ Open the Options window (tooltip: "Display a popup with the settingsfile [Options]"); **Excel Crops/Reservoirs** is the row directly below it (see its own row above) |
| Tools | Show Basin | — | Open the basin viewer — the folium (Leaflet) **EPSG:4326** map (`basin_viewer2.py`); ups.nc/mask overlays in native lon/lat over an OSM WMS basemap. (This is the former "Show Basin2"; the classic native-canvas / Mercator viewer was removed.) **Projected (non lat/lon) grids** — x/y coordinates, e.g. Norway UTM33 (`grid_is_latlon` in `basin_viewer.py`) — are shown in Leaflet **CRS.Simple** on the raw x/y **without** an OSM basemap (basemap selector + OSM-transparency slider disabled, overlay fully opaque, read-outs labelled X/Y); everything else (mask, gauges, clicks, Copy Mask/Gauge) works unchanged |
| Tools | Set max Gauge | — | Set Gauges to the largest-upstream point inside the mask. (The menu label is **"Set max Gauge"**; the in-app gauge warning and `find_largest_ups_gauge`'s error still say "Set Gauge" — `main_window.py:1146, 2100`) |
| Tools | Add output Watercycle | — | Insert `OUT_TSS_AreaSum_MonthTot = WaterCycle` under `[OUTPUT]` if absent |
| Tools | Add output variables | — | (separator below) **Jumps the editor to the end of the file first** (`[OUTPUT]` is the last section, so the insert point is on screen), then opens a topic-grouped, filterable picker of the metaNetcdf variables that **fit the current `[OPTIONS]`**, marking with a **✓** what the file already writes. **Left-click** toggles the variable on the editor's current `OUT_TSS_…`/`OUT_MAP_…` line; **right-click** opens a type menu (TSS ▸ time step ▸ upstream `AreaSum`\|`AreaAvg`, or MAP ▸ time step) that builds the key and appends to it, creating it under `[OUTPUT]` if absent. Variables needing an index are marked `[index]` and both click styles ask which one, **by name** — see `CWatM_GUI_Internals.md` |
| Tools | Check Data | — | Open the Check Data window — runs CWatM's `-c` data analysis **in a worker thread** (the window is **non-modal**, the GUI stays usable, elapsed time shown) with **CWatM's output in the window's own log pane**; warns when the editor has unsaved changes (the check reads the file from **disk**); result table **sortable + filter box**, whole-row tint for a problem row, a **summary line** counting them, **Export CSV** of what is shown, and a **double-click jumps to that key** in the settings editor. **Run Check is disabled for a coordinate MaskMap** (with the reason in the tooltip), the csv defaults to `<PathOut>/check_cwatm1.csv`, and *Restore settings from discharge map* opens **Restore settingsfile** |
| Tools | Create PathOut Folder | — | _(Outputs, **first** item)_ Create the resolved PathOut directory if missing — CWatM does not create it |
| Tools | Restore settingsfile | — | Open a CWatM output NetCDF (`dis*.nc`) and show its stored run metadata (**summary card** + attribute table, all read in **one** file open). **Preview settingsfile** shows the stored `version_settingsfile` read-only (→ Save as / **Load into editor unsaved** / Compare), **Compare with current** diffs it against the loaded settings, **Restore settingsfile** writes + loads it (suggested `<title>_<date>.ini`), **Show Inputfiles** lists `version_inputfiles` **and checks** each file (still there? still the same version?), **Show in Journal** jumps to the run that wrote the file; Ctrl+C / right-click / **Export as CSV** on both tables. Buttons the file cannot serve are greyed with the reason — see `CWatM_GUI_Internals.md` |
| RUN CWATM | Run CWATM | Ctrl+R | Run / stop the CWatM model |
| RUN CWATM | Journal of Runs | — | _(2nd item; was Tools ▸ Run Ledger — the window, `utils/run_ledger.py` and `run_ledger.json` keep their names)_ Sortable, filterable table of past runs (time, Title, PathOut, duration, success, last discharge); per row: open results · show log · load settings · re-run · compare settings or results · delete. One batch's scenarios fold into one row (`batch_id`), runs **in progress** appear live at the top, and the last column is an editable **Note** stored in the journal — see `CWatM_GUI_Internals.md` |
| RUN CWATM | Windowed Run CWatM | — | _(was "Hidden Run CWatM"; tooltip "Run CWatM in a separate window". The module `hidden_run_window.py`, the geometry key `hidden_run` and the journal's `kind="hidden"` keep the old name)_ Open a **separate, non-modal window** that runs CWatM in its **own OS process**, independent of the main run and main GUI — several can run in parallel. `open_hidden_run(settings_path=None)` takes the file to preload (default: the current one), which is how the tab bar's right-click ▸ **Run CWatM** runs one tab's file — see `CWatM_GUI_Internals.md` |
| RUN CWATM | Batch Run… | — | Run many scenarios from the loaded settings file — a table where each row overrides a few keys + its own PathOut → a temp `.ini` run in its own process, **up to N in parallel** — see `CWatM_GUI_Internals.md` |
| Configure | Preferences… | Ctrl+, | **The only item in the menu.** Opens the **Preferences window** — every GUI setting, on five categorised pages, with OK / Cancel / Apply (see [Preferences window](#preferences-window-configure--preferences) below) |
| _(menu bar)_ | ⋮ | — | A `QToolButton` in the menu bar's **right corner** (`menu_bar.setCornerWidget(…, Qt.TopRightCorner)`, `self._preferences_button`) — a second way into the same Preferences window. Styled from theme tokens inside `_menu_bar_stylesheet` (`QMenuBar QToolButton`), so a Mode switch re-themes it with the bar |
| Analyse | Open PathOut Folder | — | Open the resolved PathOut directory in the file explorer (first item, above a separator) |
| Analyse | Output Explorer | — | Non-modal tree of the resolved PathOut; **double-click** a result opens the matching viewer — `*.nc`→NetCDF map, `*WaterCycle*.csv`→Watercycle sunburst, other `*.csv`→Timeseries, `*.html`/other→OS default — see `CWatM_GUI_Internals.md` |
| Analyse | Timeseries | — | Open a CWatM result `.csv` and plot it (Plotly line chart) — see `CWatM_GUI_Internals.md` |
| Analyse | NetCDF | — | Open a `.nc` file and show it as a Leaflet **ImageOverlay over an OSM WMS basemap** (EPSG:4326, like Show Basin) with an **OSM-transparency slider**, basemap selector, **Log scale** toggle, and clicked points shown as **numbered pin icons** coloured to match their Timeseries line — see `CWatM_GUI_Internals.md`. (The former Plotly heatmap "NetCDF" was removed; this folium viewer was "NetCDF2".) Like Show Basin, a **projected x/y grid** (e.g. UTM33) renders in **CRS.Simple without** the OSM basemap; x/y (or X/Y) NetCDF coordinates are handled and read-outs/point labels say X/Y |
| Analyse | Watercycle | — | Open a `WaterCycle_areasum_monthtot.csv` and show the overall water balance as a Plotly **sunburst** (multi-station csvs get **Backward / Forward** buttons) — see `CWatM_GUI_Internals.md` |
| Analyse | Flow Diagram | — | Open a `WaterCycle_areasum_monthtot.csv` (same file as Watercycle) and show the water balance as a Plotly **Sankey** flow diagram (multi-station csvs get **Backward / Forward** buttons) — see `CWatM_GUI_Internals.md` |
| CWatM AI | (button) | — | Open the **CWatM AI** chat window — questions about CWatM answered by Google **NotebookLM** (Gemini) over a predefined CWatM notebook/PDF — see `CWatM_GUI_Internals.md` |
| Help | CWatM GUI Documentation | — | Render `documentation/CWatM_GUI_Documentation.md` as markdown |
| Help | CWatM GUI Features | — | Render `documentation/CWatM_GUI_Features.md` (the user-facing feature tour) as markdown |
| Help | FAQ | — | Render `documentation/CWatM_GUI_FAQ.md` (common questions & troubleshooting) as markdown |
| Help | CWatM Homepage | — | Open the CWatM website in the desktop browser |
| Info | About CWatM | — | About dialog |

- **Save locked while CWatM runs**: during a run all functionality stays available
  (so you can analyse, chat with CWatM AI, etc.) — only **Save** is greyed out (the
  run uses the file on disk; **Save As** still works). `_set_tools_enabled(False)`
  greys just the Save button + File ▸ Save .ini action, re-enabled on
  finish/error/stop.
- **QAction/QMenu lifetime**: menus are kept referenced (`self._menus`) and the
  "Write output" state is mirrored to a plain bool so a stale QAction cannot crash a
  run; menu-touching code is guarded against `RuntimeError` (deleted C++ object).

### Preferences window (Configure ▸ Preferences…)
`src/gui/widgets/preferences_window.py` — `PreferencesWindow(QDialog)`, **modal**,
opened by **Configure ▸ Preferences…** (Ctrl+,) or the **⋮** button in the menu bar's
right corner (both call `main_window.open_preferences`). Layout: a **category list on
the left**, a **`QStackedWidget` page per category on the right**, **OK / Cancel /
Apply** below. Built fresh on every open, so it picks up the active theme (the usual
secondary-window rule); only the category list, the page frame and the headings are
styled from tokens (`_apply_style`) — the rest inherits the app palette so Normal keeps
its native look.

**Buffered apply — the invariant**: the controls hold a *copy* of the settings; nothing
changes until **Apply** or **OK**, and **Cancel** discards what has not been applied.
`_read_state()` reads the live values, `_from_widgets()` reads the dialled-in ones, and
`_apply()` pushes **only the keys that differ** from the last applied state (so a second
Apply does not re-fire a theme re-apply or a flopy warm-up). `_apply_one` routes every
key to the main window's **existing** handler (`_on_*_toggled`, `_set_theme_mode`,
`set_experience_level`, `_set_default_basemap`, `_set_animal`, `display_format.set_*`,
`run_ledger.set_*`) — **this window is a second face on the existing behaviour, never a
second implementation of it**. Adding a setting = one control + one `_read_state` /
`_to_widgets` / `_from_widgets` entry + one `_apply_one` branch.

| Page | Setting | Behaviour |
|------|---------|-----------|
| Output | Output box file | Custom output-box log file + **Browse…** (kept in memory, `_output_file_override`); empty = the default `<PathOut>/cwatm_out.txt`, shown as the field's placeholder |
| Output | Write output box | Writes the run log to that file (can slow down a run). Backed by the standalone `write_output_action` QAction — `run_controller` reads `.isChecked()` |
| Startup & Model | Load previous settings at start | Persisted `startup/load_previous`, default OFF; when ticked **every tab** of the last session is re-opened on the next startup (`tabs/files` + `tabs/active` → `open_files_in_tabs`; a pre-tabs session falls back to the most recently used file). Handled in `cwatm_gui.py main()` when no file is passed on the command line — a command-line file wins and opens a single tab |
| Startup & Model | Use Modflow | Persisted `modflow/enabled`, default OFF; ON **pre-imports flopy** (the CWatM↔MODFLOW library — heavy, pulls the matplotlib stack) so in-process MODFLOW use is ready; OFF never loads flopy, keeping startup fast (`src/gui/utils/modflow.py`, `_on_use_modflow_toggled`) |
| _(not exposed)_ | ~~Run model in separate process~~ | Not shown anywhere, but the functionality is kept: `run_subprocess_action` is created standalone in `_init_configure_state` (default ON, persisted `run/subprocess`) and still drives `_run_subprocess_enabled` (own OS process = real Stop, crash isolation). Add it to a Preferences page to expose it again |
| Display | Mode | Colour theme of the whole GUI: **Normal** (classic light) / **Dark Mode** / **Mikhail** (black + amber); switches live (the open dialog re-themes itself), persisted `display/theme` |
| Display | Show Header | Persisted `display/show_header`, default ON: show the top **banner** (CWatM icon + title + "The Community Water Model User Interface" + IIASA logo). Unticked hides it (`_banner_widget.setVisible(False)`) so everything below moves up (`_on_show_header_toggled`) |
| Display | Font of settingsfile | Family the **settings editor** renders with — a `QFontComboBox` filtered to the **monospaced** fonts (columns + the gutter's fixed-width digits), persisted `editor/font_family`. Empty (the default) = the built-in fallback chain of `_editor_style()` (`'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', 'Consolas', monospace` — Consolas on Windows), so an untouched install renders exactly as before; a chosen family is put **in front of** that chain (`main_window._editor_font_css`). The box opens on the family actually rendered (`main_window.editor_font_family()` → the persisted choice, else `fontInfo().family()`), and `_select_font` inserts that family if the monospaced filter does not list it, so the box can never show a different font than the editor uses |
| Display | Font size of settingsfile | Size of the settings editor in **px**, 6–32, persisted `editor/font_size` (default 13). The **same** setting as the **Font+ / Font-** buttons right of *Down* — both go through `main_window._set_editor_font_size`, and the dialog reads the live value when it opens, so the two can never drift |
| Display | Show decimals | How many decimals numeric values show throughout all displays (default 3, range 0–12), persisted `display/decimals` |
| Display | Initial map transparency | The **start** value (0–100 %) of the transparency slider the **NetCDF** and **Show Basin** viewers open with, default 100, persisted `display/transparency` |
| Display | Default openstreet map | Default basemap for **Show Basin** — its EPSG:4326 WMS layers (OSM / Topographic / Terrain / Dark), persisted `basin/default_basemap`. The list is `preferences_window.BASEMAPS`, kept in sync with `basin_viewer2._B2_PROVIDERS`; an old XYZ key migrates to `OSM-WMS` (`_saved_basemap`) |
| Display | Select animal | The cameo shown now and then on the live discharge sparkline: **Fish · Otter · Beaver · Sailboat**, persisted `display/animal` (default Fish); applied live via `discharge_sparkline.set_animal` (edit the `ANIMALS` registry to change the set) |
| Editor & Dates | Skill of user | **Beginner / Advanced / Expert** — how much of the settings file **and of the menus** is shown (hides the sections, and for Beginner the advanced menu entries, the level may not see). In sync with the colour-coded level button right of the editor's `Font-` button; persisted `editor/level`, default Expert (see the Skill of User behavioral note) |
| Editor & Dates | Web-style date picker | Persisted `display/date_picker_web`, default ON: Start/Spin/End dates picked via a 📅 button + frameless shadowed calendar popup; unticked = classic `QDateEdit` drop-down calendar (see the Date calendar popups behavioral note) |
| Editor & Dates | Date timeline | Persisted `display/date_timeline`, default ON: show the three-handle **Start/Spin/End timeline** below the date fields — drag a handle (or click the track to jump the nearest one) to set the date; the light band behind the track is the meteo-forcing coverage |
| Editor & Dates | Use Tabs | _(last item)_ Persisted `editor/use_tabs`, default ON: show the **settings-file tab bar**, so several settings files can be open at once. Only ever shown in the **Expert** level (`tabs_enabled` = the tick **and** Expert); unticking hides just the chrome, never the open tabs' content (`_on_use_tabs_toggled` → `update_tabs_visible`) — see the Settings-file tabs note |
| Editor & Dates | Bookmark Change | Persisted `editor/bookmark_change`; when ticked a changed settings line is **auto-bookmarked** — but skipped if a bookmark already sits 1 or 2 lines above/below it |
| Run History | Run history folder | The general folder where the **Journal of Runs** (`run_ledger.json`) is stored + **Browse…** (`history/folder`, default `%LOCALAPPDATA%/CWatM_GUI`); a path that is not an existing directory is ignored |
| Run History | Run history retention | How many days of runs to keep in the Journal of Runs, `history/retention_days`, default 60; **0 shows as "keep forever"** (`setSpecialValueText`) |

**Startup**: `menu_builder._init_configure_state()` (called while the menu bar is built)
restores the settings that need an action *before* the Preferences window is ever
opened — the two standalone QActions above, plus `_on_load_previous_toggled`,
`_on_use_modflow_toggled` (flopy warm-up) and `_on_bookmark_change_toggled` (applies to
the editor). The rest is already restored where it is used: the banner, date picker and
timeline in `create_gui`, decimals/transparency in `__init__`, the sparkline animal in
`discharge_sparkline` itself.

### Behavioral notes
- **Full view on start**: the main window always opens **maximized**
  (`Qt.WindowMaximized`) regardless of screen size — unless the environment variable
  **`CWATM_GUI_NO_MAXIMIZE`** is set, which starts it windowed. That exists for
  **remote X displays** (Xming/X2Go/VNC): a maximized window is a desktop-sized backing
  store on the X server, and when that server runs out the window simply disappears.
- **Load by drag & drop / command line**: dropping a `.ini`/`.txt` file onto the
  main window loads it; `CWatM_GUI.exe <settings.ini>` (or
  `python cwatm_gui.py <settings.ini>`) loads the file at startup — enables Windows
  file association / "Open with".
- **Elapsed / remaining time**: shown **inside the progress-clock face** below the
  percentage (`ProgressClock.set_time_lines`; clock diameter 110–220 px, sized
  with the run button / output box / sparkline from the screen height so the
  left column fits a laptop screen — see the vertical-budget note in
  `create_run_cwatm_button`) as two
  lines `elapsed h:mm:ss` / `remaining ~h:mm:ss` (linear estimate from the
  completed fraction), frozen as `run time` / `failed after` / `stopped after`
  when the run ends (`run_controller._update_run_time_label`). A 1-second QTimer keeps
  "elapsed" ticking between timesteps; progress reaches the GUI through the
  worker's `progress` signal — `cwatm_worker.py` hands the model a proxy
  (`_GuiWindowProxy` / `_ProgressClockProxy`) whose `progress_clock.setValue`
  re-emits that signal, so the model-side hook never touches a widget
  cross-thread.
- **Changed-fields hint**: a blue label right of RUN CWATM lists which fields
  (Start/Spin/End Date, PathOut, MaskMap, Gauges) differ from the loaded/saved file
  — a hint that the run uses the new values. Baseline captured on load/save
  (`_capture_field_baseline` via `_mark_clean`).
- **Settings-file tabs** (optional, **Expert only**): several settings files open at
  once, one per **tab** below the button row (`src/gui/components/tab_manager.py`,
  `SettingsTabsMixin`). Shown when **Preferences > Editor & Dates > Use Tabs** is ticked
  (persisted `editor/use_tabs`, **default ON**) **and** the level is **Expert**
  (`tabs_enabled()` / `update_tabs_visible()`). Hiding them hides **only the chrome** -
  open tabs keep their content, so switching the option off and on never loses work.
  Each tab owns its own editor page, so undo/bookmarks/folds/marks are per tab by
  construction. Three invariants:
  **(1) The active tab is the application state** - a switch re-points `text_area` /
  `file_manager.current_file_path` / `original_content` / `_clean_content` / the mask
  cache and refreshes the left panel the way a load does, so every feature that reads
  `file_manager.get_current_file_path()` (RUN CWATM, Compare, Excel, Check Data, Show
  Basin, Output Explorer) follows the active tab **without knowing tabs exist**.
  **(2) One file, one tab** (`guard_duplicate_file` / `same_file`): the same file in two
  tabs would mean two independent copies of the text, the second Save silently
  discarding the first tab's work - so a load of an already-open file switches to the
  tab that has it, and Save As onto another tab's file is refused.
  **(3) Global settings fan out to every tab** - theme (`_retheme`), editor font + size
  (`_restyle_all_editors`), the level's locked sections (`_apply_experience_level`) and
  Bookmark-Change.
  **Exit prompts once per dirty tab** (`confirm_all_tabs_saved`). The open files + the
  active one are persisted (`tabs/files`, `tabs/active`) and **Load previous settings at
  start reopens them all** (a file on the command line still wins and opens a single
  tab). The `+` tab, the hover close button, the right-click menu (*Delete Tab* / *Copy
  Tab* / *Run CWatM* / *Link scrolling*) and the switch-time flush rules are in
  `CWatM_GUI_Internals.md`
- **Plain-text editor (report §3.2)**: the settings editor is a `SettingsEditor`
  (`QPlainTextEdit` + `IniHighlighter` syntax highlighting —
  `src/gui/widgets/settings_editor.py`); the document **is** the settings file at
  all times, saving is `toPlainText()`. **Folding** hides a section's blocks
  (`QTextBlock.setVisible(False)`) without removing them — folded sections are
  still saved/searched, and Find/Replace/jump-to-bottom auto-unfold a hit inside
  a folded section (`reveal_cursor`). Fold a section by **double-clicking its
  `[SECTION]` header** or clicking the ▾/▸ marker in the gutter.
- **Skill of User / experience level (Beginner / Advanced / Expert)**: a
  **colour-coded button** right of the editor's `Font-` button cycles
  Beginner → Advanced → Expert → Beginner (`cycle_experience_level` /
  `set_experience_level`, persisted `editor/level`, default **Expert**). It is
  mirrored by **Preferences ▸ Editor & Dates ▸ Skill of user** (a combo box,
  tooltip "The skill of the user determines how much of the settingsfile is
  presented"); the dialog reads the level when it opens and applies it through
  `set_experience_level`, so the two cannot drift. (`_sync_level_menu` /
  `_level_menu_actions` are the leftover menu-radio sync — now a guarded no-op,
  kept for a future menu.) The button's background is the level colour at **50%
  opacity** (`_LEVEL_COLORS`, `_level_button_style`): Beginner light **green**,
  Advanced light **blue**, Expert **gray** (kept out of `_nav_buttons` so a
  theme switch does not overwrite it; re-applied in `_retheme`). Each level
  decides which `[SECTION]`s are **shown**; every other section is **fully
  hidden** — both the `[SECTION]` header line and its content blocks are made
  invisible (still saved via `toPlainText()` / searched, just not displayed) and
  **non-unfoldable** (double-click / gutter click / Find-reveal / Unfold All all
  skip it). **Beginner** shows `[FILE_PATHS]`, `[MASK_OUTLET]`,
  `[TIME-RELATED_CONSTANTS]`, `[OUTPUT]`; **Advanced** adds `[OPTIONS]`,
  `[INITITIAL CONDITIONS]`, `[METEO]`, `[EVAPORATION]`; **Expert** shows
  everything (the pre-existing behaviour).
  **The level also hides menu entries** (`menu_builder._beginner_hidden_actions` /
  `_apply_menu_level`, run when the menus are built and from `set_experience_level`):
  a **Beginner** does not see Tools ▸ *Add output Watercycle* · *Change Options* ·
  *Excel Crops/Reservoirs* · *Check Data* · *Restore settingsfile* · *Journal of Runs*,
  RUN CWATM ▸ *Windowed Run CWatM* · *Batch Run…*, Analyse ▸ *Watercycle* ·
  *Flow Diagram*; Advanced and Expert see those. The reverse list
  (`_expert_only_actions`) is shown to **Expert alone**: Settings ▸ *Compare Tab*,
  which works on the (Expert-only) settings-file tabs — hidden **and** disabled
  below Expert, since an invisible QAction would still answer its F8 shortcut. A **section header** whose
  items are all hidden is hidden with it (`_section_headers`, filled by
  `_add_menu_section`), so no title is left standing with nothing under it. Driven by
  `main_window._apply_experience_level` (`_LEVEL_ALLOWED`) →
  `SettingsEditor.set_locked_sections(names)` (hides locked sections;
  `apply_folds` / `unfold_all` / `set_content_preserving` all skip locked
  sections so `_folded` stays the user's own fold set); the locked set is
  **recomputed from the current section list after every file load**, so it
  stays correct across files.
- **Editor extras**: a **line-number gutter** showing **file line numbers**
  (numbers jump across a folded section) plus the ▾/▸ fold markers
  (`src/gui/widgets/line_number_gutter.py`; its font follows the editor's —
  `_gutter_font()` shrinks the **pixel** size, because the editor's font comes
  from a stylesheet in px and its `pointSizeF()` is therefore -1; capped at 16 px
  so a long line number cannot run into the fold marker in the fixed 62 px
  width), and **hover
  tooltips**: hovering a CWatM variable name (e.g. `discharge`) shows its
  long_name / unit / description from `cwatm/metaNetcdf.xml` (cached in
  `src/gui/utils/meta_netcdf.py`, shared with both Analyse windows — report §3.3).
- **Bookmarks**: Settings ▸ Toggle Bookmark (Ctrl+F2) — or **clicking a line's
  number in the gutter** (section-header rows keep their fold-toggle instead) —
  marks the editor's current line with an **orange dot** in the gutter; F2 /
  Shift+F2 jump to the next / previous bookmark (wrapping, auto-unfolding a hit
  inside a folded section); Ctrl+Shift+F2 clears all. Stored as
  `QTextBlockUserData` (`_BlockMarks` in `settings_editor.py`), so they
  survive same-line edits (including left-window field auto-apply); a
  line-count-changing programmatic replace or a file load clears them.
- **Changed-line highlight**: every line that differs from the last loaded/saved
  file content gets a **light-blue background** (`#dcecff`) — computed ~120 ms
  after an edit by difflib against the `_saved_text` baseline and applied as
  `ExtraSelection`s (FullWidthSelection). Cleared by Save/Save As
  (`mark_saved()`) and on load (`load_text()`); works for editor typing and
  left-window field changes alike.
- **Bookmark Change / Goto last change**: Preferences ▸ Editor & Dates ▸ **Bookmark Change** (persisted
  `editor/bookmark_change`) toggles `SettingsEditor._auto_bookmark_changed`; when on,
  `_recompute_change_highlights` (the same debounced diff that drives the blue
  highlight) auto-bookmarks each changed row via `_auto_bookmark_changed_rows`, which
  **skips a row if a bookmark already sits ±1 or ±2 lines away** (so adjacent changes
  collapse to one mark). Turning it on bookmarks the already-changed lines.
  Settings ▸ **Goto last change** (F5) → `SettingsEditor.goto_last_change`: jumps to
  the block of the most recent edit (tracked via the document's `contentsChange`
  signal, reset to "none" on load), falling back to the bottom-most line that differs
  from `_saved_text` when no edit has been recorded.
- **Duplicate-key highlight**: lines whose keyword appears more than once are
  drawn a **strong red** (`duplicate_line`, `#ff8f8f` in the normal theme — visibly
  stronger than the Check-settingsfile missing-file red so the two are
  distinguishable; wins over both the changed-line blue and the missing-file red).
  Matches CWatM's parsing (`configuration.py`): `out_*` keys are per-section
  (`outDir[sec]`/`outTss`), so those only count as duplicates **within the same
  section**; all other keys go into the flat `binding` dict, so a repeat
  **anywhere** silently overrides the earlier value and is flagged
  (`_duplicate_key_rows` in `settings_editor.py`). Note: the stock Morava
  settings legitimately shows the `PathSoil` pair red — it *is* a real override.
  Priority (later wins) in `_recompute_change_highlights`: changed-line blue <
  inactive-section/key missing file (`inactive_line`, dimmed orange — Check
  settingsfile, gating option off) <
  **wrong-extension** (`wrongext_line`, **light** orange — Check settingsfile: the file
  exists under a different raster extension; **no bookmark**, `set_wrongext_rows`) <
  Check-settingsfile missing (`error_line`, light red) < duplicate key
  (`duplicate_line`, strong red) < Compare-settings **diff** (`diff_line`, orange —
  `set_diff_rows`) < alignment **filler** (`filler_line`, light gray —
  `set_filler_rows`) < **current** jumped-to diff (`current_diff_line`, darker orange —
  `set_current_diff_rows`) < **Compare Tab** (`compare_line`, light green painted at
  **alpha 128** so the colour underneath still shows — `set_compare_rows`, Settings ▸
  Compare Tab / F8). The three `diff`/`filler`/`current_diff` levels are used only by
  the Compare settings window.
- **Date calendar popups**: the Start/Spin/End date fields use `CWatMCalendar`
  (`date_manager.py`, subclass of `QCalendarWidget` with a custom `paintCell`):
  selected day = filled accent circle, today = thin accent ring, the **other two
  date fields** shown as small dots (green = Start, orange = Spin, red = End;
  side by side when equal), and days **outside the meteo-forcing time coverage
  dimmed** — the coverage comes from `_forcing_time_range` (the same F4 semantic
  check) via `settings_check._forcing_range_for_calendar`, computed lazily on the
  first popup open and cached in `DateManager` until the next file load
  (`invalidate_forcing_range` in `set_dates_from_config`). All colours are theme
  tokens read at paint time; the popup chrome (nav bar, headers, no grid/week
  numbers) is styled by QSS in `DateManager.retheme()`. **Two picker styles**
  (Preferences ▸ Editor & Dates ▸ **Web-style date picker**, persisted `display/date_picker_web`,
  default ON): the fields are sized exactly to the date text
  (`setFixedWidth(sizeHint)` in `retheme`); *web-style* = a calendar button
  right of each field **carrying the field's handle colour** (background at 70%
  transparency, border + `_calendar_icon` glyph in the full colour —
  green/orange/red; the field's spin arrows are removed, `NoButtons`) opening a
  frameless, rounded, drop-shadowed popup (`_CalendarPopup`, `Qt.Popup` — closes
  on outside click/Esc; clicking a day sets the field); *classic* (unticked) =
  the normal `QDateEdit` drop-down (arrows restored). Both use
  the same `CWatMCalendar` cells; `set_web_picker` switches live. Below the
  date row sits the **`DateTimeline`** (option 4, Preferences ▸ Editor & Dates ▸ **Date timeline**,
  `display/date_timeline`): a custom-painted three-handle timeline — green =
  Start, orange = Spin, red = End on an axis covering the dates + forcing
  range, forcing coverage as a light band (`changed_line` token), Start→End as
  an accent bar, a tick on today, year labels at the axis ends. The **date row,
  output box and timeline share one width** — all end at the right edge of the
  date row's last element (`_cap_output_box_width`, re-synced on resize and on
  a picker-mode switch). Dragging a
  handle writes the date into its field (fields stay the source of truth;
  `dateChanged` repaints the timeline), **clamped between its neighbours** so
  Start ≤ Spin ≤ End can never be violated by dragging; clicking the track
  jumps the nearest handle; the dragged handle shows its date above the track.
  The lazy forcing-coverage read is shared with the calendars
  (`refresh_forcing_range`, triggered on popup open or first timeline click).
- **Window geometry memory**: the Timeseries, NetCDF and Basin windows remember
  their size/position across sessions (QSettings `geometry/<key>`, keys
  `timeseries`, `timeseries_point`, `netcdf`, `basin` —
  `src/gui/utils/window_geometry.py`); on first open they use the default
  placement (NetCDF left of centre, its point-timeseries right of centre).
- **Save HTML**: both Analyse windows have a **Save HTML** button that saves the
  current self-contained Plotly plot (plotly.js inlined) to a user-chosen `.html`;
  the dialog suggests the resolved **PathOut** directory
  (`analysis_timeseries.resolved_pathout_dir`, walks the widget parent chain to
  the main window).
- **Global display decimals**: `src/gui/utils/display_format.py` holds one setting
  (`get_decimals`/`set_decimals`/`fmt`/`spec`, default 3) driving how many decimals
  numeric values show across the GUI (live discharge, the basin viewer's click
  read-out **lat/lon + area** and marker-tooltip coordinates, and the NetCDF
  **cell-value and lon/lat hovers** + point labels). Set via **Preferences ▸ Display ▸
  Show Decimals**, restored from `QSettings` at startup. Coordinates written back
  into the settings file (gauge / mask copy) keep their fixed 4-decimal precision -
  that is data serialisation, not a display. Newly opened displays pick up the
  current value; on-the-fly read-outs update immediately.
- **Global initial transparency**: the same `display_format.py` also holds
  `get_transparency`/`set_transparency` (0–100, default 100) — the **start value** of
  the transparency slider in the **NetCDF** and **Show Basin** viewers (read in their
  `__init__`, so each newly opened window opens at that transparency; changing it later
  via the slider is per-window). Set via **Preferences ▸ Display ▸ Transparency**, restored from
  `QSettings` (`display/transparency`) at startup.
- **Analyse window placement**: the **NetCDF** window opens shifted a bit **left** of
  the screen centre; the **Timeseries** window spawned from *NetCDF ▸ Display
  timeserie* opens a bit **right** of centre (via `_position_offset` in
  `analysis_netcdf.py`) so the map and its point plot sit side by side.
- **Auto-apply of field changes**: changing Start/Spin/End Date, PathOut, or MaskMap
  updates the in-memory settings content (and the editor view) automatically after a
  ~500 ms debounce — **without saving to disk**. Save / Run flush any pending change
  first. The old **Actualize** action was removed (it had also saved to disk).
- **Undo / redo covers field changes too**: every programmatic edit
  (`SettingsEditor.set_content_preserving`) is a single undoable step — even a
  line-count-changing one (it uses a select-all + insert inside one edit block, never
  `setPlainText`, so the undo stack is preserved). `SettingsEditor` overrides
  `undo`/`redo` (and handles Ctrl+Z/Ctrl+Y in `keyPressEvent`, since QPlainTextEdit's
  built-in key handling bypasses the public slots) and emits `undoRedoPerformed`; the
  main window's `_sync_fields_from_editor` then re-derives the Date/PathOut/MaskMap/
  Gauges **widgets** from the reverted text (they would otherwise stay stale and
  re-poison `_live_content` / the next save), recomputes the Save-dirty colour vs the
  `_clean_content` snapshot (taken at load/save in `_mark_clean`), and re-runs the
  gauge-in-mask check. Loading/reloading a file still uses `setPlainText`, which
  intentionally clears the undo stack (no undo across a load).
- **Unsaved-changes indicator**: the **Save** and **Save As** buttons turn light blue
  when there are unsaved edits (editor text or field changes) and return to normal
  after a save or load (`_set_save_dirty`). The same dirty state drives the Exit prompt.
- **Title label**: the settings `Title` value is shown right of the "Loaded: …"
  label in the same colour (green on load, blue on Save As).
- **Output box**: the CWatM output area is a **read-only `QPlainTextEdit`**
  (appends are O(1); scrollback capped at **5000 lines** via `maximumBlockCount`),
  left-aligned with the progress clock centred/left **below** it. Its text is
  selectable and copyable (Ctrl+C, or right-click → standard menu + "Copy all
  output"). Errors appear in dark red; auto-scrolls only when already at the bottom.
  Its scrollbars are the **blue rounded** theme-token style (`accent` handle,
  `surface_bg` groove, radius 6) — the same look as the settings editor's, set in
  `_output_box_style` (vertical **and** horizontal).
- **Live progress line**: per-timestep "date + discharge" output (printed by CWatM
  with a leading `\r`) overwrites a single line in place instead of accumulating,
  mirroring the console.
- **Live discharge sparkline**: a small custom-painted widget
  (`src/gui/widgets/discharge_sparkline.py`, no Plotly/WebEngine — off the
  fast-startup budget) sits **right of the progress clock** and plots the discharge
  value as the run streams. Fed from the **same** `\r` progress line the output box
  overwrites — `output_box.append_to_cwatminfo` parses the `<timestep> <date>
  <discharge>` line (`parse_progress`: date `dd/mm/yyyy`, discharge = last token) and
  calls `discharge_sparkline.add_from_progress_line`; cleared at the start of every run
  (`run_controller.run_cwatm`). Shows a **rolling ~3-month window** (`_WINDOW`, 92 days
  by date; falls back to a point cap when dates are absent) and **fades out towards the
  left** — each segment's opacity is `255 * frac**_FADE_GAMMA` where `frac` is its
  **horizontal position** (0 = left edge → fully transparent, 1 = right = newest →
  opaque; `_FADE_GAMMA` 1.5 biases the fade so the trace dissolves before the clock
  rather than butting up against it). Bare trace + latest-point
  marker only (no frame, title, or corner read-outs); reads theme tokens at paint time
  (repainted by `_retheme`). The newest-point marker is usually a dot, but a slow random
  timer (`_tick_animal`, ~8%/0.6 s to appear, ~20%/tick to leave so it lingers ~3 s)
  occasionally turns it into a small **animal cameo** (`_draw_animal`, size 15) tilted to
  the local slope and facing forward in time — a playful touch, live sparkline only. The
  animal is chosen in **Preferences ▸ Display ▸ Select animal** (Fish/Otter/Beaver/Sailboat,
  `ANIMALS` registry + `display/animal`; `set_animal` applies it live).
- **Taskbar icon**: the app sets a Windows AppUserModelID and `assets/cwatm.ico` so
  the taskbar shows the CWatM icon (see `cwatm_gui.py`).
- **Colour themes (Preferences ▸ Display ▸ Mode)**: `src/gui/utils/theme.py` holds three token
  sets — **normal** (token values = the previously hardcoded colours, so Normal
  renders exactly like before), **dark**, **mikhail** (black + amber CRT). Every
  main-window/editor/gutter/clock/output-box stylesheet is built from
  `theme.c(token)`; a switch (`menu_builder._set_theme_mode`) applies Fusion
  style + a theme QPalette + small app QSS (Normal restores the platform style
  and default palette) and calls `main_window._retheme()`, which re-applies all
  widget styles live. Dynamic state colours are remembered and re-applied:
  `_filename_state` (none/loaded/saveas/error), `_gauges_state` (in/out mask),
  `_run_btn_state` (idle/ready/running), save-dirty flag. The highlighter,
  changed/duplicate line backgrounds, gutter, and progress clock read theme
  tokens at paint time. **Secondary windows are themed at construction time**
  (they are built fresh on every open, so they pick up the current mode; an
  already-open one keeps its colours until reopened): Options, Check Data
  (incl. the result table's True/False cell colours via `_cell_true_bg`/
  `_cell_false_bg`), Basin viewer (window/title/info/scrollbars; the native
  canvas and OSM map stay light — they are the data/map content), the About
  dialog, and both Analyse windows — their **Plotly figures** switch to
  `plotly_dark` + theme paper/plot/font/grid colours via
  `theme.plotly_template()/plotly_layout_overrides()/themed_plot_page()`
  (Normal keeps `plotly_white`, byte-identical output). Saturated branded
  buttons (RUN blue/red, basin blue/red/gray, Compare) are white-on-colour and
  intentionally theme-independent. **Rule: never hardcode a colour in GUI
  chrome — use a theme token.** Second rule from the same family: a **`QToolButton`
  stylesheet sizes its font in `pt`, not `px`** (the menu bar's ⋮, the tab bar's `+`,
  the Excel toolbar). A pixel size leaves the widget's `QFont` with
  `pointSize() == -1`, and a QToolButton is one of the widgets Qt's style asks for a
  *point* size — that is the source of the console line `QFont::setPointSize: Point
  size <= 0 (-1)`. Everything else (editor, labels, plain buttons) keeps px.
- **Asset paths**: never load assets with a relative path (`QPixmap("assets/...")`
  only worked when the CWD happened to contain an assets/ copy — in the frozen
  build assets live in `_internal/`, not next to the .exe). Always resolve through
  `src/gui/utils/assets.py: asset_path()` (checks `sys._MEIPASS`, the exe folder,
  then the source root).
- The former side buttons (Load Text, Actualize, Options, Show Basin, Check Data) and
  the "Write output" checkbox have been **removed from the code** (not just hidden);
  their actions are reached through the menus above.

### Gauges, mask and PathOut checks
- **Gauges field**: under MaskMap (see `create_gauges_controls`), linked to the
  settings `Gauges` entry; auto-applies like the other fields.
- **Gauge-in-mask check** (`basin_viewer.py`: `build_mask_context`, `gauges_inside`):
  works for a **file-based** MaskMap (raster) *and* a **coordinate-based** MaskMap (a
  basin is generated via CWatM's mask routine / `mainwarm -vgm`). The check is always
  based on the **current left-window boxes**, not the saved file: `_live_content()`
  substitutes the live **MaskMap / Gauges / PathOut** box values into the settings
  content, and `_update_warnings` calls `_rebuild_mask_cache()` first (which rebuilds
  the mask only when the MaskMap box value changed vs the cache key, so it is cheap but
  never stale). For a **coordinate-based** MaskMap the basin is generated from a
  **temporary .ini holding the live content** (written next to the settings file so
  placeholders/relative paths resolve identically, deleted afterwards) — running
  `mainwarm -vgm` on the on-disk file was the source of wrong "gauge not inside"
  results right after Copy Mask / Copy Gauge (fixed 2026-07-03). `save_file`
  re-syncs the date/PathOut/MaskMap/Gauges boxes from the saved content (editor-text
  edits to those lines would otherwise leave stale box values poisoning
  `_live_content()`). The Gauges field text is coloured **blue** if all gauges are
  inside the basin, **red** if any is outside.
- **Warning label** to the right of RUN CWATM shows problems in red:
  - "Gauge is not inside the basin! Change manually or use Tools/Set Gauge."
  - "PathOut does not exists! You can use Tools/Create PathOut Folder."
  The gauge check runs on load, on **Save / Save As** (forced rebuild), after field
  edits, and after the basin viewer's **Copy Mask / Copy Gauge**; the **PathOut** check
  (`basin_viewer.pathout_exists`, placeholders resolved) runs only on load/save.
- **Set Gauge** (`find_largest_ups_gauge`): sets Gauges to the cell centre with the
  largest upstream area (from ups.nc) that is inside the mask, formatted to 4 decimals.
- **Create PathOut Folder**: `os.makedirs` of the resolved PathOut, then clears the
  warning.

### Check settingsfile (Settings menu)
`SettingsCheckMixin.check_settingsfile` (`src/gui/components/settings_check.py`, mixed
into the main window) walks the **editor content** (not the saved file) line
by line. A value is treated as a **filename/path** if it contains a `$(…)` placeholder,
ends in a known data extension (`.nc/.tif/.map/.txt/.csv/.xlsx/…`), or is an absolute
path (`X:\`, `\\`); coordinate pairs, dates (`DD/MM/YYYY`) and plain numbers are skipped.
**Keys whose first 4 letters are `path` (case-insensitive — `PathRoot`/`PathOut`/
`PathMaps`/…) are directory paths**: they are **always** checked (regardless of the
value heuristic) and **strictly** — plain `os.path.exists` only, with **no** NetCDF
without-extension / date-suffix fallbacks. Placeholders are resolved with
`basin_viewer._resolve_settings_placeholders` against a
`ConfigParser(interpolation=None, strict=False)` of the same content; a value whose
placeholder stays **unresolvable** (the referenced key/section does not exist, e.g.
`$(PathRott)` or `$(FILE_PATHS:NoSuchKey)`) is **flagged as its own problem category**
("unresolved placeholder(s)" in the summary, line marked red + bookmarked) — only when
the content failed to parse (no ConfigParser) is it skipped. Relative paths resolve
against the settings-file directory. For non-`path` keys existence is lenient — `glob` for `*`/`?`,
plus fallbacks for a NetCDF stored without `.nc` or with a date suffix (`glob(p+'*')`,
`p+'.nc'`) — so it never
false-flags. **Wrong-extension (orange, no bookmark)**: before flagging a missing file
red, `wrong_extension_alt` tries the same base name with the other interchangeable
raster extensions (`.nc/.nc4/.tif/.tiff/.map`); if one of those **exists** (e.g. the
value says `cellarea.map` but `cellarea.nc` is on disk) the line is drawn a **light orange**
(`wrongext_line`, `set_wrongext_rows`) with **no bookmark** and a quiet
"exists as …" note in the summary — a likely wrong-extension typo, not a hard miss.
Only for non-`path` keys. **Disabled-section / disabled-key gating**: parts CWatM only reads when
an `[OPTIONS]` switch is on. Two granularities, both mirrored read-only from the
`checkOption(...)` / `returnBool(...)` guards in `cwatm/`:
- **Whole sections** (`_SECTION_GATED_BY`): `GROUNDWATER_MODFLOW` ←
  `modflow_coupling`, `GLACIER` ← `includeGlaciers`, `WATERDEMAND` ←
  `includeWaterDemand`, `LAKES_RESERVOIRS` ← `includeWaterBodies`,
  `RUNOFF_CONCENTRATION` ← `includeRunoffConcentration`, `INFLOW` ← `inflow`,
  `ENVIRONMENTALFLOW` ← `calc_environflow`, `ROUTING` ← `includeRouting`.
- **Individual keys** anywhere (`_KEY_GATED_BY`, finer than section): `initLoad` ←
  `load_initial`, `initSave` ← `save_initial`, `albedoMaps` ← `albedo`,
  `downscale_wordclim_*` (prefix rule → prec/tavg/tmin/tmax/… all covered) ←
  `usemeteodownscaling` (**not** `meteomapssamescale`, which only rescales — it gates
  no file), `initLoad_pySnowClim` ← `load_initial_pySnowClim`, `initSave_pySnowClim` ←
  `save_initial_pySnowClim`, `smallLakesRes` & `smallwaterBodyDis` ← `useSmallLakes`,
  `EnvironmentalFlowFile` ← `use_environflow` (a **separate** option from the
  `[OPTIONS]` `calc_environflow` section gate), `irrNonPaddy_fracVegCover` ←
  `static_irrigation_map`. All entries are **direct** (key active only when the
  option is on).
- **Value gates** (`_KEY_GATED_BY_VALUE`, `_value_gate_phrase`): a file key CWatM reads
  only when another key's **numeric** value meets a condition (not a boolean on/off).
  Currently `averageBaseflow` & `averageDischarge` ← `swAbstractionFrac < 0`
  (`water_demand.py:719-724`: `loadmap` runs only inside `if swAbstractionFrac < 0`; a
  `>= 0` value uses a fixed fraction and never reads the files). When the gate is **not
  met** the missing file is dimmed (same inactive treatment, no bookmark) with a note
  `skipped averageDischarge - swAbstractionFrac = 0.8 >= 0 (read only when < 0)`; an
  unparseable/missing gate value is conservative (treated as active → flag a real miss).
- **Groundwater-MODFLOW input is soft** (`_is_modflow_input`, a separate rule): a
  `PathGroundwaterModflow*` path key, or any file routed through a
  `$(PathGroundwaterModflow…)` placeholder (`modflow_basin`/`topo_modflow`/`chanRatio`/
  `cwatm_modflow_indices`/…), is **dimmed light orange, no bookmark** when missing
  instead of red — MODFLOW input is normally preprocessed/optional, not a hard error
  (applies whether or not the `GROUNDWATER_MODFLOW` section is active; an off section is
  already dimmed by the section gate). To stay consistent, the `_OPTION_REQUIRES`
  dependency check treats `PathGroundwaterModflow` as **set-only** (`_REQUIRE_SET_ONLY`)
  — a set-but-missing input dir no longer flags `modflow_coupling` red, though a missing
  `path_mf6dll` (the solver DLL) still does.

When the gating option is **explicitly** false (`false/0/no/off`; missing = active,
conservative — via `_explicitly_off`), a missing **file** in that section / for that
key is drawn **dimmed orange** (`inactive_line` token, `SettingsEditor.set_inactive_rows`)
with **no bookmark**, and the summary gets one quiet note per section/key
(`skipped [GLACIER] - includeGlaciers = False (…)` / `skipped albedoMaps - albedo = False (…)`).
**Option roll-up (the reverse)**: when a **section-gated** option is **on** (enabled)
and its section contains a red row (a missing file or an unresolved placeholder), the
feature's `[OPTIONS]` **switch line itself** is also marked red + bookmarked — pointing
the user at the option that pulled in the broken section (`gated_active_problem` →
`options_rows` row → `rollup`; summary `… includeGlaciers = True -> see the red line(s)
in [GLACIER]`). Only for the section-gated options (their switch lives in `[OPTIONS]`)
and only when the switch line actually exists in the file.
**Only file existence is gated** — unresolved placeholders and `out_*` key/value
checks stay global, because CWatM resolves placeholders (`ExtParser` Error 116)
and collects output keys (`configuration.py:272`) for *every* section at parse
time regardless of options. Every missing value's line is added to
`SettingsEditor._error_rows` (drawn
a **light red** — its own `error_line` token, distinct from the stronger `duplicate_line`
red so a missing file reads differently from a duplicate key — in
`_recompute_change_highlights`, above the changed-line blue) **and bookmarked**
(`bookmark_rows`, additive — F2/Shift+F2 jump between them). A **summary is written to the
output box** (`append_to_cwatminfo`) listing **only the problem lines**, one compact line
each: `line N: key = value` (+ `-> resolved` inline when it differs), in dark red.
`_error_rows` clears on file load.
- **Bookmarks added by the check are tagged check-owned** (`_BlockMarks.check`), and each
  run first calls `clear_checking` so re-running doesn't accumulate stale marks.
- **Clearing the check** (`settings_check.clear_checking` → `SettingsEditor.clear_checking`)
  clears `_error_rows` (removes the red) and unsets **only the check-owned** bookmarks —
  the user's own bookmarks survive — and logs a note to the output box. It is reached by
  pressing **F4 a second time**: Check settingsfile is a **single toggle** menu item
  (`toggle_check_settings`) that runs the check when nothing is marked (relabelling itself
  "Clear checking") and clears when marks are shown (relabelling back). There is no
  separate Clear-checking item / Shift+F4 shortcut any more.
- **Semantic checks** (`_semantic_settings_problems(content, config, base_dir)`, run after
  the file-existence pass): beyond "does the file exist", it validates
  - the **simulation date ordering** — `StepStart` must be a real date, and
    `StepStart ≤ SpinUp ≤ StepEnd` (comparing only values that are dates, since
    `SpinUp`/`StepEnd` may legitimately be an **integer** timestep count);
  - **option dependencies** (`_OPTION_REQUIRES` table) — an option switched **on** whose
    required keys are unset **or** whose required **path** key points to a non-existent
    location (resolved + `os.path.exists`); the **option's own line** is flagged (so a bad
    dependency shows on the option, not only on the path line). Example:
    `modflow_coupling = True` needing `path_mf6dll` / `PathGroundwaterModflow` /
    `nameModflowModel` / `Modflow_resolution`. Keys in `_REQUIRE_SET_ONLY` (e.g.
    `PathGroundwaterModflow`) are checked only for **being set**, not for existence (see
    the groundwater-MODFLOW soft rule above). Easy to extend with more options;
  - **output keywords** — every `out_*` key (outside `[OPTIONS]`) is validated against
    CWatM's output grammar (mirrored from `configuration.py` / `globals.py` /
    `output.py appendinfo`, read-only): `OUT_..._Dir`, `OUT_TSS_<type>`,
    `OUT_TSS_<AreaSum|AreaAvg>_<type>` (TSS types: daily, monthtot/avg/end,
    annualtot/avg/end, totaltot/avg) and `OUT_MAP_<type>` (adds monthmid, totalend,
    once, 12month; **no** AreaSum/AreaAvg for maps). Important because CWatM
    **silently ignores** an invalid map key (e.g. `OUT_MAP_AreaSum_MonthTot`) — no
    error, just no output; TSS typos at least raise Error 130/131 at run start.
    The **values** of valid output keys (comma-separated variable names) are checked
    against the `cwatm/metaNetcdf.xml` varname catalogue (`meta_netcdf.all_varnames`),
    mirroring CWatM's runtime Error 132 (`output.py checkifvariableexists`):
    case-sensitive (a case-insensitive hit gets a "wrong case — use 'X'" message),
    `[index]` stripped, the special `WaterCycle` allowed, first item `None`/empty =
    output disabled (skipped), unknown names get a difflib closest-match hint;
    best-effort — non-identifier tokens or an unreadable xml flag nothing.
    **Array dimensions** are checked too (`var_dims.dim_problem`, the module Tools ▸
    Add output variables uses to *offer* the same indices): multi-dim variables need
    an index (`actualET` → `actualET[1]`) — the sets are mirrored from the allocation
    lists in `cwatm/hydrological_modules/` (read-only): per-land-cover `(6, cells)`
    (`landcoverType.py landcoverAll+landcoverVars`, index 0..5 = forest, grassland,
    irrPaddy, irrNonPaddy, sealed, water), per-soil-land-cover `(4, cells)`
    (`landcoverVarsSoil` + `w1/w2/w3`, 0..3), `(soilLayers=3, 4, cells)` needing two
    indices (`soilVars` e.g. `rootDepth[0][1]`), `soildepth` `(3, cells)`, and the
    per-crop lists from `evaporation.py` (crop index, no upper bound). Flags a
    missing/extra/non-numeric/out-of-range index; an index on a variable *not* in
    these sets is never flagged (other modules allocate 2-D vars the GUI doesn't
    track);
  - the **run window inside the meteo-forcing time coverage** (`_forcing_time_range`) —
    resolves the first readable forcing entry (`PrecipitationMaps` → `TavgMaps` →
    `E0Maps` → `ETMaps`), globs its NetCDFs and reads the **first & last** (name-sorted)
    file's time axis (cheap even for many yearly files), and warns if `StepStart` is
    before the forcing starts or `StepEnd` (when a date) is after it ends — the most
    common "crashes hours into a run" error. Best-effort: any read error skips silently.

  Problem lines are marked red + bookmarked like missing files, and listed in the
  output-box summary (`N settings problem(s):`). Easy to extend (returns `(row, message)`
  tuples).

### Output-box log file (Preferences ▸ Output)
- Default location is `<PathOut>/cwatm_out.txt` (placeholders resolved); **Set output
  box file** overrides it with a custom path kept in memory. The **Write output box**
  tooltip shows the current effective path.
- The file is **appended**, not overwritten. Each run is delimited by a header written
  straight to the file (not shown in the box): a `====` line, the date/time, a `----`
  line; and a blank line is written after the run's content
  (`_finalize_output_file`).
- The file **handle is opened once per run and kept open** until finish/error/stop
  (`_close_output_file_handle`); lines are flushed by the ~150 ms display throttle,
  not per line (per-line open/append/flush was a real slowdown on network shares).
- **Check settingsfile → log file**: when **Write output box** is on, running
  **Check settingsfile** (F4) also writes its whole summary to the log file, not just
  the output box. The check opens the file for the duration of the summary
  (`_open_output_file_note("Check settingsfile")` — same `====`/date/`----` header
  block as a run, then `_finalize_output_file`); `append_to_cwatminfo` writes to the
  open handle, so the box and file get the same lines. No-op if a run is already
  writing the log (the summary just appends to that active run's log instead).

### Secondary-window internals → `documentation/CWatM_GUI_Internals.md`
The per-feature deep dives for the secondary windows live in
[`documentation/CWatM_GUI_Internals.md`](documentation/CWatM_GUI_Internals.md) (kept out
of this always-loaded reference to keep it lean): **Settings-file tabs · Excel sheet
editor · Compare settings · Output Explorer · Windowed Run CWatM · Batch Run · Journal of
Runs · Restore settingsfile · Change Options · Check Data · Add output variables ·
CWatM AI**. Their menu entries + one-line behaviour are in the Menu Bar table above; their
module files in [Core Modules](#core-modules) below.

## Architecture

The application is structured with a modular architecture for better maintainability.

### Core Modules

- **`cwatm_gui.py`**: Main entry point and application launcher with global exception handling
- **`src/gui/components/main_window.py`**: Main window class orchestrating all components (inherits the mixins below)
- **`src/gui/components/menu_builder.py`**: `MenuBuilderMixin` — builds the full menu bar and maintains the History menu
- **`src/gui/components/run_controller.py`**: `RunControllerMixin` — start/stop the threaded CWatM run, progress/finish/error handling, run-log file, menu locking, post-run cleanup
- **`src/gui/components/output_box.py`**: `OutputBoxMixin` — the CWatM output box (throttled appends, `\r` progress overwrite, copy actions)
- **`src/gui/components/tab_manager.py`**: `SettingsTabsMixin` + `SettingsTab` — the **settings-file tabs** (tab bar below the button row, one `SettingsEditor`/`LineNumberGutter`/`TextDisplayManager` page per tab in a `QStackedWidget`, the per-tab state the main window is re-pointed at on every switch, the Delete/Copy/Add-empty context menu, the `tabs/files` persistence and `open_files_in_tabs` used by *Load previous settings at start*), plus the pure `next_copy_path()` naming rule — see the Settings-file tabs behavioral note
- **`src/gui/components/settings_check.py`**: `SettingsCheckMixin` — the whole **Check settingsfile** (F4) pass: the file-existence walk over the editor content (placeholder resolution, the `path*`-key strict rule, the section/key/value gating tables, the MODFLOW-soft rule, wrong-extension detection), `_semantic_settings_problems` (date ordering, `_OPTION_REQUIRES` dependencies, `out_*` grammar + varname/index validation), `_forcing_time_range`, and the toggle/clear/label plumbing — see [Check settingsfile](#check-settingsfile-settings-menu)
- **`src/gui/components/find_replace.py`**: `FindReplaceMixin` — the combined non-modal **Find & Replace** window (shared Find box + Find/Replace tabs, Count, "Replace all in selection", its own status bar) plus `find_next`/`find_previous`/`_find_in_editor`; searches the **active tab's** editor through `self.text_area`
- **`src/gui/components/main_window_styles.py`**: `MainWindowStyleMixin` — the main window's stylesheet builders (left/right panel, field, output box, editor + font css, run button, modern/save-dirty buttons, level button, filename + gauges state colours). Pure presentation, every colour a `theme.c(token)`; owns `_LEVEL_COLORS`
- **`src/gui/components/config_parser.py`**: Configuration file parsing and formatting logic
- **`src/gui/managers/date_manager.py`**: Date input validation and management
- **`src/gui/managers/file_manager.py`**: File I/O operations and management
- **`src/gui/managers/text_display.py`**: Text area operations and cursor management (plain text only since §3.2)
- **`src/gui/widgets/settings_editor.py`**: `SettingsEditor` — the plain-text settings editor (`QPlainTextEdit` + `IniHighlighter` + section folding via block visibility; report §3.2)
- **`src/gui/widgets/preferences_window.py`**: Configure ▸ Preferences… (Ctrl+, / the ⋮ menu-bar button) — `PreferencesWindow`, the modal, categorised settings dialog (category list + stacked pages + OK/Cancel/Apply) that replaced the Configure menu's items; buffers edits and applies only the changed keys through the main window's existing handlers — see [Preferences window](#preferences-window-configure--preferences)
- **`src/gui/widgets/options_window.py`**: Tools ▸ Change Options — the `[OPTIONS]` switches as tick boxes, grouped by topic with an ⓘ explanation, a filter and *Revert all*. **Non-modal** (a tick applies at once). Invariant: the parse **strips an inline comment before the boolean test** and `_rewrite_value` **keeps what followed the value**, so `includeGlaciers = False  # …` neither disappears from the window nor loses its comment; the edit goes through `set_content_preserving`, so a tick is **one undo step** — see `CWatM_GUI_Internals.md`
- **`src/gui/utils/option_help.py`**: the text behind those ⓘ badges — `text(option)`, `has()`, plus `GROUPS`/`KNOWN`/`group_of()` for the grouping and the *Add option…* list. Adding a switch is one entry
- **`src/gui/widgets/check_data_window.py`**: Tools ▸ Check Data — `CheckDataWindow`, CWatM's `-c` data analysis. Three invariants: it runs in a **`QThread`** (it opens every input file — in the GUI thread it froze the app), the window is therefore **not modal**, and its output goes to the window's **own log pane** (`_LogTee`, filtered to the worker thread) rather than the main output box behind a dialog. Double-clicking a result row jumps to that settings key — see `CWatM_GUI_Internals.md`
- **`src/gui/utils/var_dims.py`**: which model variables are **arrays** and what index an output value needs (`DIM6`/`DIM4`/`DIM3X4`/`DIM3`/`DIMCROP`, mirrored read-only from the allocation lists in `cwatm/hydrological_modules/`). One copy, two users: `main_window`'s Check settingsfile calls **`dim_problem(base, idx)`** to flag a missing/extra/invalid index, and `output_variables_window` calls **`index_options(base)`** to offer the valid ones **by name** (`1 - grassland`, `0,2 - top soil layer, irrPaddy`; a suffix of `None` = "ask", for the open-ended per-crop lists) plus `needs_index`/`hint_of`/`kind_of`
- **`src/gui/widgets/output_variables_window.py`**: Tools ▸ Add output variables — `OutputVariablesWindow`, a topic-grouped, filterable picker of the metaNetcdf output variables that fit the current `[OPTIONS]`, marking what the settings file already writes and resolving an array variable's index **by name** through `var_dims.index_options`. Every insert goes through `set_content_preserving` (**one undo step**) — see `CWatM_GUI_Internals.md`
- **`src/gui/widgets/excel_sheet_window.py`**: `ExcelSheetWindow` — Tools ▸ Excel Crops/Reservoirs: an editable, lazy `QTableView` over a whole xlsx workbook (openpyxl), reproducing each sheet's colours, with formulas, clipboard blocks, a fill handle, per-sheet undo/redo and column/row insert+delete. Two rules that keep it usable: the workbook is **read in a `QThread`** (openpyxl takes tens of seconds for a cold file on a share), and **never measure or enumerate the whole sheet** — `resizeRowToContents`/`selectedIndexes()` walk every cell and froze the GUI for minutes on the 367×1021 sheet. **openpyxl is the right library here** (XlsxWriter cannot read an existing workbook; xlwings needs a real Excel) — see `CWatM_GUI_Internals.md`
- **`src/gui/utils/cell_formula.py`**: the Excel editor's formula engine — `is_formula` (leading `=`, or a bare expression whose every token is a number / cell ref / known function / operator) + `evaluate` over an **ast whitelist** (never `eval`), cell refs (`I3`), ranges (`A1:B3`), SUM/AVERAGE/MIN/MAX/COUNT/ABS/ROUND/SQRT/LOG/…, errors as `#DIV/0!`-style markers
- **`src/gui/utils/cell_fill.py`**: the Excel editor's autofill series — `extend_series(values, count)`: number series with a constant step, text+trailing number (`Crop1`→`Crop2`), weekday/month/quarter lists, else repeat the block (basic copy)
- **`src/gui/widgets/basin_viewer.py`**: Basin **data loader** (`BasinViewer`: ups.nc/mask loading, placeholder resolution), the `BasinDataHelpers` mixin (ups/mask RGBA, gauge/mask field readers, gauge-in-mask check — shared with Show Basin), the app-lifetime `osmtile://` scheme handler + `_get_tile_handler`, and the module-level gauge-in-mask & PathOut checks (`build_mask_context`, `gauges_inside`, `pathout_exists`, `find_largest_ups_gauge`). The classic native-canvas / Mercator `BasinWindow`/`BasinCanvas` were **removed**.
- **`src/gui/widgets/basin_viewer2.py`**: **Show Basin** — the folium (Leaflet) basin viewer in **EPSG:4326** (see the Basin Viewer section); `BasinWindow2(BasinDataHelpers, …)`
- **`src/gui/widgets/analysis_timeseries.py`**: Analyse ▸ Timeseries — Plotly line chart of a result `.csv`, with unit/long_name/description from `cwatm/metaNetcdf.xml`
- **`src/gui/widgets/analysis_netcdf_base.py`**: `NetcdfDataBase` — the **shared NetCDF data layer** (no UI): xarray file reading (`_load` → per-timestep grids), coordinate/variable guessing, settings-`Title` + `metaNetcdf.xml` lookups, and the lazy per-cell time-series re-read (`_point_series(..., full=)` — full = every timestep for **Total Timeseries**, else the strided map frames for **Fast Display Timeserie**); plus the colour-scale / play-speed tables. (This is the former `analysis_netcdf.py` with its Plotly viewer removed.)
- **`src/gui/widgets/analysis_netcdf.py`**: Analyse ▸ NetCDF — `NetcdfWindow(NetcdfDataBase)`: renders the `.nc` variable as a Leaflet **ImageOverlay** (RGBA data-URI PNG per timestep, `image-rendering:pixelated`) over an **OSM WMS** basemap in EPSG:4326 (folium page served same-origin through the shared `osmtile://` handler, WMS providers from `basin_viewer2`); Play/slider driven by a Qt `QTimer`, OSM-transparency slider, basemap + colour-scale selectors, Log-scale toggle, HTML colour-bar, click read-out, and clicked points as **numbered pin icons** (`L.divIcon`) coloured to match the Timeseries lines. (This is the former `analysis_netcdf2.py`; the plain Plotly `NetcdfWindow` was removed.)
- **`src/gui/widgets/analysis_watercycle.py`**: Analyse ▸ Watercycle — Plotly `Sunburst` of a `WaterCycle_areasum_monthtot.csv` water balance (computation ported from `Watercycles1.py`); title = settings Title, subtitle = station lon/lat (csv row 2/3 col 2), Save HTML like Timeseries
- **`src/gui/widgets/analysis_flowdiagram.py`**: Analyse ▸ Flow Diagram — Plotly `Sankey` of the same `WaterCycle_areasum_monthtot.csv` water balance (computation ported from `sankey_waterbalance_month.py`); reuses the Watercycle window's header, station lon/lat subtitle, month **range slider** and Save HTML (`RangeSlider`/`WatercycleWindow` csv-parsing helpers imported from `analysis_watercycle.py`)
- **`src/gui/utils/progress_clock.py`**: Circular progress indicator for CWatM execution
- **`src/gui/widgets/discharge_sparkline.py`**: `DischargeSparkline` — live custom-painted discharge-vs-timestep plot next to the progress clock (fed from the `\r` progress line; no Plotly/WebEngine)
- **`src/gui/widgets/output_explorer.py`**: Analyse ▸ Output Explorer — `OutputExplorerWindow`, a PathOut file tree whose double-click dispatches each result to the matching viewer
- **`src/gui/widgets/batch_runner_window.py`**: RUN CWATM ▸ Batch Run… — `BatchRunnerWindow`, a scenario table (base .ini + per-row key overrides → temp .ini) running up to N in parallel via `CWatMProcessWorker`. **A batch is expensive, so nothing starts before `_preflight`**: a missing/duplicate PathOut blocks, because silent result-mixing is the worst failure mode here. Each scenario gets its **own `output_sink`**, so parallel runs cannot interleave; temp files are keyed by **row number** (`run 1`/`run_1` sanitise alike and used to clobber each other) — see `CWatM_GUI_Internals.md`
- **`src/gui/widgets/run_ledger_window.py`**: RUN CWATM ▸ Journal of Runs — `RunLedgerWindow`, a table of past runs (open results / reload settings)
- **`src/gui/utils/run_ledger.py`**: Persistent run log (`run_ledger.json`) — `add_entry`/`load_entries`/`make_entry`/`remove_entries`/`set_note`, per-run **settings snapshots** (`snapshots/`, diffed by Compare settings), plus the configurable folder + retention (Preferences ▸ Run History). `make_entry` also records `log_path` (the run's output log, for the journal's *Show log*) and `batch_id` (shared by one Batch Run's scenarios, so the journal can fold them into one row)
- **`src/gui/utils/metrics.py`**: Goodness-of-fit scores (KGE / NSE / PBIAS / RMSE) for the Timeseries observed-vs-simulated comparison
- **`src/gui/utils/cwatm_process_worker.py`**: Subprocess CWatM worker (QProcess; default run mode — real Stop, crash isolation). Optional `output_sink(text, is_error)` ctor arg routes run output to a caller's box instead of the global `sys.stdout`/`sys.stderr` (used by the Hidden Run windows; default `None` = main-window behaviour)
- **`src/gui/widgets/hidden_run_window.py`**: RUN CWATM ▸ Windowed Run CWatM (the module keeps the older "hidden run" name) — `HiddenRunWindow`, a non-modal window running CWatM in its **own process** (`CWatMProcessWorker` + `output_sink`), so several run in parallel, independent of the main run. Own progress/elapsed, a pre-flight that creates the resolved PathOut, a Journal entry (`kind="hidden"`), geometry key `hidden_run` cascaded per open window, and a confirmation before closing while a run is in progress — see `CWatM_GUI_Internals.md`
- **`src/gui/utils/cwatm_model_runner.py`**: Child-process side of the subprocess run (no Qt; stdout marker protocol)
- **`cwatm_model.py`** (root): entry script of `CWatM_model.exe` (the frozen child process)
- **`src/gui/utils/cwatm_worker.py`**: Threaded CWatM execution worker (in-process fallback)
- **`src/gui/utils/display_format.py`**: Global display-decimals setting (Preferences ▸ Display ▸ Show decimals)
- **`src/gui/utils/modflow.py`**: Preferences ▸ Startup & Model ▸ Use Modflow toggle (`modflow/enabled`) — `is_enabled`/`set_enabled` + `warm_flopy` (background flopy pre-import); gates the heavy flopy/matplotlib import so a non-MODFLOW start stays fast
- **`src/gui/utils/theme.py`**: Colour themes (Preferences ▸ Display ▸ Mode: Normal / Dark / Mikhail) — token sets, app palette/QSS, persistence
- **`src/gui/utils/assets.py`**: `asset_path()` — absolute asset resolution (source, `_internal/`, exe folder)
- **`src/gui/utils/open_path.py`**: `open_path()` — show a file/folder in the desktop's handler, portably: `os.startfile` on Windows (unchanged behaviour), else `QDesktopServices`, else `xdg-open`/`open`/`gio`. **Use it instead of `os.startfile`**, which does not exist off Windows — it is what the three "open this" actions (Analyse ▸ Open PathOut Folder, Journal of Runs PathOut, Output Explorer's `.html`/`.txt` fallback) call; returns False instead of raising, so each caller shows its own message
- **`src/gui/utils/gui_log.py`**: Diagnostic logging — swallowed exceptions go to a rotating `%LOCALAPPDATA%/CWatM_GUI/gui.log` (UI behaviour unchanged)
- **`src/gui/utils/warning_filters.py`**: The third-party warnings the GUI silences — currently only rasterio 1.5.0 × numpy 2.5 ("Setting the shape on a NumPy array has been deprecated", raised inside `rasterio._io.read()` but **attributed to the caller**, i.e. `cwatm/management_modules/data_handling.py:317/654`, so it looks like a CWatM problem). Three nets, because a user's machine may enable DeprecationWarnings (`PYTHONWARNINGS`, IDE, older build): `apply()` installs the message-matched filter **and** exports `PYTHONWARNINGS` (called at the top of `cwatm_gui.py` and of `cwatm_model_runner.py`, before numpy/rasterio/cwatm are imported; `cwatm_process_worker.start()` also puts it in the child's `QProcessEnvironment`), and `LineSuppressor` drops the warning's lines on the way to the output box (`cwatm_process_worker._forward` for every child run — main/Hidden/Batch — and `print_redirector` for in-process prints). Delete the module + its call sites once a fixed rasterio ships
- **`src/gui/utils/window_geometry.py`**: `GeometryMemoryMixin` — persists window size/position of the Analyse/Basin windows via QSettings
- **`src/gui/utils/temp_page.py`**: `TempPageMixin` — temp-file lifetime for the Plotly viewers (Timeseries / Watercycle / Flow Diagram). `_load_temp_page(html, prefix)` writes the rendered page, **deletes the one it replaces** and loads it into `self.web_view`; the window drops its last page in `done()` (the funnel both the X button and Esc reach — a `closeEvent` override alone misses Esc). Those pages inline plotly.js, so each is several MB and each redraw — every tick of a debounced range slider — used to orphan one. Mix it in **before** `GeometryMemoryMixin`/`QDialog`
- **`src/gui/utils/meta_netcdf.py`**: Cached varname → (unit, long_name, description) lookup from `cwatm/metaNetcdf.xml` (editor hover tooltips); also `all_varnames()` (Check settingsfile output-name validation), `output_varnames(high_only=)` (Add output variables — data vars, excluding no-type / `_`-prefixed names, `list(...)` tables and Flag/Number/String scalar types; `high_only` keeps only `priority="high"`), and `dim_of()`/`priority_of()` (the metaNetcdf `dim`/`priority` attributes, parsed alongside the type)
- **`src/gui/widgets/line_number_gutter.py`**: Line-number gutter widget for the settings editor
- **`src/gui/widgets/notebooklm_window.py`**: CWatM AI — `NotebookLMWindow` (Gemini/NotebookLM chat: persistent transcript + question history, Up/Down recall, login-state colouring; see CWatM AI section)
- **`src/gui/utils/notebooklm_worker.py`**: `NotebookLMWorker(QThread)` — off-thread NotebookLM questions (queue, lazy connect, `status/reply/error/busy` signals)
- **`src/gui/utils/notebooklm_client.py`**: The **only** importer of `notebooklm` — `NotebookLMClientWrapper` (async→sync over one asyncio loop; `connect/ask/close`, `is_authenticated`, notebook auto-resolve)
- **`src/gui/widgets/compare_settings_window.py`**: Tools ▸ Compare settings — `CompareSettingsWindow` (two side-by-side `SettingsEditor` panes; left preloaded from the main window, right has a Load button; differing lines marked red via `diff_rows` + `set_error_rows`)
- **`src/gui/widgets/restore_settings_window.py`**: Tools ▸ Restore settingsfile — `RestoreSettingsWindow` (summary card + NetCDF metadata table + Preview / Compare / Restore / Show Inputfiles / Export, each enabled by what the file actually holds), `SettingsPreviewWindow` and `InputFilesWindow`. Invariant: `read_netcdf_attrs` reads **all** globals in **one** file open, and because CWatM records only an input file's **base name**, existence is resolved through the stored settings file's folders (`candidate_dirs`) — see `CWatM_GUI_Internals.md`

### Module Dependencies
```
cwatm_gui.py
    └── src/gui/components/main_window.py
            ├── src/gui/components/menu_builder.py    (mixin)
            ├── src/gui/components/run_controller.py  (mixin)
            ├── src/gui/components/output_box.py      (mixin)
            ├── src/gui/components/tab_manager.py     (mixin; owns the per-tab
            │       settings_editor.py + line_number_gutter.py + text_display.py)
            ├── src/gui/components/settings_check.py  (mixin; Check settingsfile)
            ├── src/gui/components/find_replace.py    (mixin; Find & Replace)
            ├── src/gui/components/main_window_styles.py (mixin; QSS builders)
            ├── src/gui/components/config_parser.py
            ├── src/gui/managers/date_manager.py
            ├── src/gui/managers/file_manager.py
            ├── src/gui/managers/text_display.py
            ├── src/gui/widgets/options_window.py
            ├── src/gui/widgets/check_data_window.py
            ├── src/gui/widgets/basin_viewer.py
            ├── src/gui/widgets/analysis_timeseries.py
            ├── src/gui/widgets/analysis_netcdf.py
            ├── src/gui/widgets/settings_editor.py
            ├── src/gui/widgets/line_number_gutter.py
            ├── src/gui/widgets/notebooklm_window.py  (lazy; → notebooklm_worker/_client)
            ├── src/gui/utils/progress_clock.py
            └── src/gui/utils/cwatm_worker.py
```

### CWatM Integration
- **Subprocess execution (default — report §3.1)**: `CWatMProcessWorker`
  (`src/gui/utils/cwatm_process_worker.py`) runs the model in a **separate OS
  process** via `QProcess`. Child side: `src/gui/utils/cwatm_model_runner.py`
  (no Qt imports) calls `run_cwatm.mainwarm(settings, ['-lg'], stub)` and talks
  back over stdout: model output streams through unchanged; the model-side
  progress hook fires the stub's `progress_clock.setValue`, emitted as
  `@@CWATM_GUI:PROGRESS:<pct>@@` lines; a final `@@CWATM_GUI:RESULT:...@@` carries
  (success, last_dis). The parent strips the markers and forwards the rest
  **one write per line** to `sys.stdout`/`sys.stderr` (so `PrintRedirector`, the
  `\r` overwrite and dark-red stderr behave exactly like in-process prints).
  Benefits: **Stop is a real `kill()`** (works when the model hangs in C code), a
  segfault cannot take the GUI down, fresh interpreter each run (no
  `sys.modules` purge, no `gc.get_objects()` cleanup). Child command: frozen →
  `_internal/CWatM_model.exe <ini>` (hidden inside `_internal/` so users only see
  `CWatM_GUI.exe`; root location checked for older builds; falls back to
  `CWatM_GUI.exe --run-cwatm <ini>`); source → `python cwatm_gui.py --run-cwatm
  <ini>` (dispatched at the very top of `cwatm_gui.py`, before any Qt import).
- **In-process fallback**: the "Run model in separate process" toggle unticked (the
  action still exists and persists `run/subprocess`, but is **not shown in the UI**
  — created standalone in `_init_configure_state`, default ON) → the old
  `CWatMWorker` `QThread` path (same signals
  `finished(bool, object)`,
  `error(str)`, `progress(int)`; cooperative stop + netCDF/file cleanup). The
  worker hands the model a proxy whose `progress_clock.setValue` re-emits the
  `progress` signal (no cross-thread widget calls).
- **Print Redirection System**: custom `PrintRedirector` class captures all stdout and redirects it to the cwatminfo display (immediate, per-print updates).
- **Progress clock**: updated each timestep by a **pre-existing GUI hook inside
  `cwatm/management_modules/output.py`** (model-side integration point — do not edit it,
  per the hard rule) using `dateVar['intStart']`, `dateVar['intEnd']`, `dateVar['curr']` —
  it calls `gui.progress_clock.setValue(pct)`, which both run modes intercept
  (marker line in the subprocess; signal proxy in-process).

## Technical Details

### Requirements
- Python 3.8+
- PySide6
- Qt framework components
- CWatM model components (for running configurations)
- NumPy / pandas (data processing)
- xarray (for NetCDF data handling in basin viewer)
- rasterio (mask data visualization + EPSG:3857 overlay warping)
- configparser (for INI file processing)
- netCDF4 (for reading NetCDF global attributes in settings restoration)
- **PySide6 QtWebEngine** (basin viewer OpenStreetMap view + Timeseries plot)
- **folium** (basin viewer OSM map) and **plotly** (Analyse ▸ Timeseries line chart)
- **requests** (fetching OSM tiles / downloading Leaflet through Python)
- **notebooklm-py[cookies]** (+ `rookiepy`) — CWatM AI / NotebookLM chat (needs
  Python ≥ 3.10)

### Key Components
- **CWatMMainWindow**: Main application window with split-panel layout
- **ConfigParser**: Handles INI file parsing, validation, and formatting
- **DateManager**: Manages date input widgets and validation
- **FileManager**: Handles all file operations (load, save, save as)
- **TextDisplayManager**: Manages text display area and cursor operations
- **PrintRedirector**: Custom stdout redirector for real-time output capture in cwatm_gui.py
- **OptionsWindow**: Dedicated window for managing boolean configuration options
- **ProgressClock**: Circular progress indicator showing CWatM execution progress
- **CWatMWorker**: Threaded worker for non-blocking CWatM model execution
- **BasinViewer**: Advanced NetCDF basin data visualization with coordinate display
- **CheckDataWindow**: Data validation window for checking CWatM configuration files with NetCDF comparison
- **CWatM Integration**: Direct access to CWatM model execution through `cwatm.run_cwatm`

### File Formats Supported
- INI configuration files (.ini)
- Text files (.txt)
- NetCDF files (.nc) for data validation and comparison
- CSV files (.csv) for check results output
- All file types (*)

## Installation
```bash
pip install -r requirements.txt          # runtime (pinned, UTF-8)
pip install -r requirements_build.txt    # + PyInstaller, only for building the exe
pip install -r requirements_dev.txt      # + pytest, only for running the tests
python cwatm_gui.py
```
Do **not** install the GDAL wheel — the rasterio wheel ships its **own** GDAL (in
`rasterio.libs/`). A GDAL-less rasterio borrowing its DLL from the `osgeo` wheel breaks
the moment GDAL is removed (`ImportError: DLL load failed while importing _base`); the
cure is `pip install --force-reinstall --no-deps rasterio`. Full note at the top of
`requirements.txt`.

The application starts in maximized window mode for optimal viewing of configuration files.

### Running on Linux (source run; the exe/installer are Windows-only)
**The complete guide is [`cwatm_gui_linux.md`](cwatm_gui_linux.md)** — system packages
per distro (including the no-root unpack path), the venv, `gui.sh`, remote displays
(Xming/VcXsrv/X2Go/VNC/WSLg) and a troubleshooting section for every error seen so far.
The invariants that belong here:
- **`gui.sh`** is the Linux counterpart of `gui.bat`/`gui.vbs`: interpreter order
  `$CWATM_GUI_PYTHON` → `$VIRTUAL_ENV` → `venv2/` → `venv/` → `python3` (a shared
  checkout's `venv/` is the **Windows** one — `Scripts/python.exe`, no `bin/python` —
  hence `venv2/`), a readable refusal when PySide6 or Qt's **system** libraries are
  missing (`ldd` on `libqxcb.so`; only a warning for the QtWebEngine set, since just the
  map/plot windows need it), and `--check` as the one-command diagnosis. It exports the
  **software-GL** environment (`QT_OPENGL=software`, `LIBGL_ALWAYS_SOFTWARE=1`,
  `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu --disable-gpu-compositing
  --disable-software-rasterizer --no-sandbox`) plus `QT_X11_NO_MITSHM` on a non-local
  `DISPLAY` — that is what makes a forwarded X11 session usable at all, because every
  map/plot window is QtWebEngine = Chromium. `QT_XCB_GL_INTEGRATION=none` is **opt-in**
  (`CWATM_GUI_XCB_NO_GL=1`): it is what produces *"Cannot create platform OpenGL
  context, neither GLX nor EGL are enabled"*.
- **`.gitattributes` pins `*.sh` to LF** — a CRLF shebang makes bash fail with
  `bad interpreter: …^M`.
- **Library clashes are the recurring Linux failure mode**: a wheel (rasterio bundles
  curl/krb5 in `rasterio.libs/`) or a conda env ships a second copy of a system library,
  and the loser of the load order cannot resolve a symbol — `ffi_type_uint32`
  (libwayland-server via QtWebEngine → the viewers die) and `krb5_ser_context_init`
  (libgssapi_krb5 via curl/GDAL → rasterio/netCDF4 die). `CWATM_GUI_PRELOAD_SYSLIBS=1`
  puts the distribution's copies first (`_CLASH_LIBS` in `gui.sh`), and `--check`
  test-imports the whole stack and names the fix.
- **Interpreter version**: the pins are resolved for 3.12, but nothing in the GUI or in
  `cwatm/` imports a stdlib module removed in 3.13 (checked against the full PEP 594
  removal list), so a newer Python only risks a *wheel* being missing — install with
  `--only-binary=:all:` and relax that one pin.
- **What differs on Linux**: `%LOCALAPPDATA%` does not exist, so `gui.log` and the run
  ledger fall back to the temp dir (`gui_log.py` / `run_ledger.py`) — point
  Preferences ▸ Run History at a permanent folder. Opening a file/folder goes through
  `src/gui/utils/open_path.py` (see Core Modules), never `os.startfile`. The frozen-exe
  child-process paths never apply: from source the model child is
  `sys.executable -u cwatm_gui.py --run-cwatm <ini>`, which is also the way to run the
  model **headless** with no Qt at all.

### Virtual environment & building the executable
- The project venv is **`venv/`** (run with `venv\Scripts\python.exe`; activate via `venv\Scripts\Activate.ps1`). An older `build_env/` was a copied venv and is deprecated.
- **Launchers (source run)**: **`gui.bat`** and **`gui.vbs`** start `cwatm_gui.py` with the
  venv's **`pythonw.exe`** (GUI subsystem → **no console window**); `gui.bat` uses
  `start ""` so its cmd window closes at once (brief flash), `gui.vbs` runs fully
  hidden (zero flash). Both resolve paths from the script's own folder (`%~dp0` /
  `ScriptFullName`) so they work from anywhere and forward args (a settings file).
  Because pythonw makes `sys.executable` = `pythonw.exe` (which has no std streams),
  the subprocess run worker forces the console **`python.exe`** for the model child
  (`cwatm_process_worker._console_python`) so run output still streams; QProcess's
  default `CREATE_NO_WINDOW` keeps that child from flashing a console.
- PyInstaller spec: **`cwatm_gui_dir.spec`** — the **one-folder** build (a directory is
  preferred over a single-file exe for faster startup and easier debugging; the old
  single-file `cwatm_gui.spec` was removed). It collects rasterio + xarray
  submodules/data and `copy_metadata('xarray')`, `collect_all` for
  folium/branca/xyzservices and **plotly/narwhals**, adds the QtWebEngine hidden
  imports, and sets `console=False`. **Code ships only in the PYZ**
  (`collect_submodules` for `cwatm` **and `src`**); the datas are just assets,
  `cwatm/metaNetcdf.xml` and the Help markdown — the `cwatm`/`src` trees are NOT
  bundled as datas any more (report §4.2), and the `t5.*` routing libraries land at
  `cwatm/hydrological_modules/routing_reservoirs/` (the path cwatm's `globals.py`
  resolves from `__file__`). **`openpyxl`** (`collect_submodules('openpyxl') +
  ['et_xmlfile']`) is collected explicitly for **both** exes (never excluded): the GUI
  **Tools ▸ Excel Crops/Reservoirs** (`excel_sheet_window.py`) and cwatm's xlsx settings-sheet reads
  (`pd.read_excel`, §4.4) import it lazily. **`requests`** (+ `certifi`/`urllib3`/
  `charset_normalizer`/`idna`) is added for the GUI's `osmtile://` tile/WMS fetching
  (Show Basin + NetCDF maps). **CWatM AI** is collected too (GUI exe only):
  `collect_all` for `notebooklm`, `httpx`/`httpcore`/`h11`/`anyio`/`sniffio`, `rich`,
  `markdown_it`/`mdurl`/`pygments`, `filelock`, `rookiepy` (+ `copy_metadata` for the
  version-reading ones), so asking questions with a stored session and markdown answer
  rendering work frozen. The **Login…** browser-cookie paths also work frozen (via the
  exe's `--notebooklm-login` self-dispatch + bundled `rookiepy`); the interactive
  Google-login **window** needs `playwright`, which is **not** bundled (source-run only,
  and the button is hidden when frozen). The former 🎤 **Voice dictation** feature and
  its `speech_recognition`/`pyaudio` libraries were **removed**. **MODFLOW coupling**
  (`flopy` + its `matplotlib` stack — `contourpy`/`kiwisolver`/`cycler`/`fontTools`/`PIL`)
  is `collect_all`-ed into **both** exes (`modflow_*` in the spec) and **`matplotlib` is
  no longer excluded**; the **model exe** needs it because cwatm imports `flopy` when
  `modflow_coupling` is on. `xmipy` + `bmipy` (also imported by `run_cwatm` under
  `modflow_coupling`; static analysis misses them) are added as hidden imports **only if
  `xmipy` is installed** (guarded by a real import in the spec). `black` (a `bmipy`
  dependency used only by its code-render CLI, never at model runtime — importing `bmipy`
  does not load it) is **excluded** from both exes to keep the bundle lean. Bundling is unconditional (so a MODFLOW
  run works frozen), but the GUI only *imports* flopy when **Preferences ▸ Startup & Model ▸ Use Modflow** is
  on, so a normal start is unaffected. It also builds a **second executable, `CWatM_model.exe`**:
  the lightweight child process the GUI spawns for every model run (no Qt — fast
  start; `console=True` for valid std pipes, but QProcess starts it with
  `CREATE_NO_WINDOW` so no console window appears). It is built with
  `contents_directory='.'` and **moved into `_internal/`** at the end of the spec
  (users see only `CWatM_GUI.exe` in the app folder; the bootloader finds all its
  dependencies next to itself there — never rename `_internal` or the model exe's
  bootstrap breaks). The GUI looks for it in `_internal/` first, then the folder
  root (older builds).
- Build: `python -m PyInstaller cwatm_gui_dir.spec --noconfirm` (UPX disabled for faster
  builds) — but **run it through `build_release.ps1`, not here**: see
  [Building on the local disk](#building-on-the-local-disk--build_releaseps1) below,
  which is the standard procedure for both the exe and the installer.
- Reference doc in this folder: **`cwatm_gui_linux.md`** (install & run on Linux, incl. remote X displays).

### Installer (per-user, no admin) — `installer/CWatM_GUI.iss`
An **Inno Setup 7** script packages the one-folder build into a single
**`CWatM_GUI_Setup.exe`** that installs **without admin rights**
(`PrivilegesRequired=lowest` → the `{auto*}` constants resolve to the current user's
locations: `{autopf}` = `%LOCALAPPDATA%\Programs`, `{autoprograms}` = user Start menu,
`{autodesktop}` = user desktop). A directory-picker page lets the user change the
install folder. It copies **`dist\CWatM_GUI\*`** verbatim
(`recursesubdirs createallsubdirs`) so `_internal\` (holding `CWatM_model.exe`) keeps
its exact name/layout — the CLAUDE.md invariant. Optional **[Tasks]**: desktop shortcut,
`.ini` **"Open with"** association (per-user `HKCU\Software\Classes` ProgID +
`OpenWithProgids` — does *not* hijack the default `.ini` handler; passes the file as
`"%1"`, the arg `cwatm_gui.py` reads at `sys.argv[1]`), and launch-after-install. The
uninstaller removes the program files, shortcuts and the HKCU keys but **leaves user
data** (QSettings, the `%LOCALAPPDATA%\CWatM_GUI` Journal of Runs). Bump `MyAppVersion` in the
**Version — one source of truth**: `__version__` in **`src/gui/__init__.py`** is the
only place the GUI version is written down. `main_window` imports it
(`from src.gui import __version__ as GUI_VERSION`) for the About dialog, and the `.iss`
**scrapes that same line** in its preprocessor (`FileOpen`/`FileRead` loop → `Copy`
between the quotes) instead of defining `MyAppVersion` itself, so a bump there flows
into `AppVersion`/`AppVerName` and the setup's ProductVersion. If the line is missing
the compile **aborts** (`#error`) rather than shipping a blank version. Two ISPP
gotchas the block depends on: assign with `#expr`, **not** `#define`, inside a `#sub`
(a `#define` there does not survive into global scope), and the loop body goes **after**
the `#for {…}` braces. Keep the literal on one line as `__version__ = "X.YZ"`. Keep the
fixed `AppId` GUID so upgrades/uninstall track correctly. The manual
(`documentation/CWatM_GUI_Documentation.md`: title header + §18 prose and table) still
needs its own edit per release.
- **Build the installer**: `build_release.ps1` does it (step `installer`). By hand it is
  `python -m PyInstaller cwatm_gui_dir.spec --noconfirm` (produces `dist\CWatM_GUI\`),
  then `ISCC installer\CWatM_GUI.iss` →
  `installer\Output\CWatM_GUI_Setup.exe` (~260 MB, lzma2/max solid). `ISCC.exe` is the
  Inno Setup 7 compiler; **its location differs per machine — probe both known paths**:
  `C:\Apps\Inno Setup 7\ISCC.exe` and
  `%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe` (Inno Setup is installable per-user
  via its own `/CURRENTUSER` flag, which is why it is not under Program Files). The
  script uses only 6-era directives, which 7 compiles unchanged.
- The setup is **unsigned**, so SmartScreen / FortiClient may warn on first run even
  though it installs fine — Authenticode-sign the setup + both exes to avoid that.

### Building on the local disk — `build_release.ps1`
**The standard procedure for producing `CWatM_GUI.exe` and `CWatM_GUI_Setup.exe`.**
Development happens here in `P:\watmodel\cwatmpublic\gui`, but **the build itself never
runs on P:** — PyInstaller reads tens of thousands of small files (site-packages, the
collected Qt/GDAL/matplotlib trees) and writes ~950 MB, and Inno Setup then reads all of
it again; over SMB that is the dominant cost of a release. The build therefore runs in a
**local working copy, `C:\work\CWatM_GUI`** (override with `-Work`), which is refreshed
from the repo on every build:

```powershell
pwsh -NoProfile -Command "& '.\build_release.ps1'"          # full release
pwsh -NoProfile -Command "& '.\build_release.ps1' -Steps sync,build"   # exe only
pwsh -NoProfile -Command "& '.\build_release.ps1' -ForceVenv"          # after a pip install
```
(Call it with `-Command`, not `-File`: with `-File` the shell passes `-Steps a,b` as one
string and the `ValidateSet` rejects it.)

Five steps, selectable with `-Steps`:

| Step | What it does |
|------|--------------|
| `venv` | Mirrors the repo `venv\` to `C:\work\CWatM_GUI\venv` **once** (1.3 GB) — so site-packages is read locally too, which is half the win. Skipped when it is already there; `-ForceVenv` re-mirrors it after a `pip install`/upgrade. The copy works because the venv's `home` is the local `C:\Python312`; nothing hardcodes the P: path except the console scripts, and the script always invokes `venv\Scripts\python.exe -m PyInstaller`. |
| `sync` | Robocopy `/MIR` of what the build reads — `src`, `cwatm`, `assets`, `documentation`, `installer` (minus `Output`) — plus `cwatm_gui.py`, `cwatm_model.py`, `cwatm_gui_dir.spec`, `LICENSE`. Nothing else is needed: the spec bundles code through `collect_submodules('cwatm'/'src')` and only assets, `metaNetcdf.xml`, the Help markdown + figures and the t5 routing libraries as data. |
| `build` | `venv\Scripts\python.exe -m PyInstaller cwatm_gui_dir.spec --noconfirm` in the working copy, then asserts `dist\CWatM_GUI\CWatM_GUI.exe` **and** `dist\CWatM_GUI\_internal\CWatM_model.exe` exist. |
| `installer` | `ISCC installer\CWatM_GUI.iss` in the working copy (probing the per-machine ISCC paths). Both the spec and the `.iss` resolve everything relative to their own location — including the version the `.iss` scrapes from `src\gui\__init__.py` — so the local copy builds exactly what the repo would. |
| `copyback` | `dist\CWatM_GUI` → `P:\…\gui\dist\CWatM_GUI` (robocopy `/MIR`, so removed files disappear) and `installer\Output\CWatM_GUI_Setup.exe` → `P:\…\gui\installer\Output\`, overwriting the previous release. **This is the only P: write of the whole build**, and it is a straight sequential copy. |

Consequences to keep in mind: `C:\work\CWatM_GUI` is a **build artefact, never a second
working copy** — edit here, and `sync` overwrites anything changed there; and the exe
that is tested/shipped is the one *copied back*, so `copyback` is not optional. The
spec's `_netsafe_copyfile` patch (SMB `OSError 22` on large writes) stays for anyone who
still runs PyInstaller directly on P:.

### Watercycle template scripts (repo root — canonical balance computation)
The two Analyse water-balance windows do **not** invent their own maths — each
**ports** the balance computation from a stand-alone template script that lives in
the repo root (run directly against a `WaterCycle_areasum_monthtot.csv`). Keep the
widget in sync with its template when the CWatM water-balance variables change:

- **`Watercycles1.py`** → **Analyse ▸ Watercycle** (`analysis_watercycle.py`,
  `_build_figure`). Reads the csv with `pd.read_csv(csv, skiprows=3)`; `cellArea`
  is `cellArea_sum_m3[0] / days_in_month[0]` (the monthly cell-area is summed over
  the month's days). Builds the `Vars` table (flux/store, grouped into Inputs /
  Outputs / Storage / Evapotranspiration / Transpiration), sums fluxes over the
  window and takes the store change (`end − baseline`), then assembles the Plotly
  **Sunburst** (mm/yr = `Σm³ / cellArea × 1000 / nyears`; discharge kept as m³/s).
- **`sankey_waterbalance_month.py`** → **Analyse ▸ Flow Diagram**
  (`analysis_flowdiagram.py`, `_build_figure` + `_build_balance_links` +
  `build_sankey`). Same csv/`cellArea` convention; builds a `bal` dict of long-term
  **mm/yr** averages per variable, derives the rain/snow runoff split, and defines
  the fixed-layout **Sankey** nodes (`Precipitation → Rain/Snow → Soil / Groundwater
  / Runoff → Waterbodies → Discharge`, plus Withdrawal / Consumption / Glacier) and
  the link list. Colour/gradient helpers (`_adjust_color`, `build_sankey`,
  `_GRADIENT_JS`) are ported verbatim.

Both GUI widgets differ from their template only in that they run over the
**slider-selected month window** (not a hardcoded year range) and read the station
lon/lat + settings `Title` from the csv header instead of hardcoded strings.

## Tests & CI

```bash
pytest                       # the whole suite (~290 tests)
python tools/check_invariants.py    # the structural rules below, no dependencies
python tools/check_requirements.py  # every requirements file parses, -r includes resolve
python tools/import_all.py          # import all of src/gui + build the main window
```

`tests/` covers the **pure logic** — the layer that is otherwise only ever exercised by
hand: `cell_formula` (the ast whitelist, and that `is_formula` does not over-claim),
`cell_fill`, `metrics`, `var_dims`, `tab_manager.next_copy_path`, `temp_page`,
`run_ledger`, and the **Check settingsfile semantic pass** (`settings_check`, run on a
bare host object — its only `self` use is a pure method, so it needs no window).
`conftest.py` sets `QT_QPA_PLATFORM=offscreen` before the first PySide6 import, so
nothing needs a display.

Two rules for this suite:
- **Match the code, not the assumption.** Where a test disagreed with the code, the code
  was checked against `cwatm/` first — `OUT_TSS_Daily = none` really is an error, because
  CWatM's sentinel test is `!= "None"`, case-sensitive (`configuration.py:249`).
- **A known defect gets an `xfail(strict=True)`, never a softened assertion** — the suite
  stays green, the bug stays recorded, and a fix turns the xfail into a failure instead
  of rotting. Two are recorded in `tests/test_cell_formula.py::TestKnownBugs`.

`tools/check_invariants.py` enforces what this file states as always-true: no silent
`except: pass`, no literal exotic line separator in a source file (a stray **U+2029**
in `main_window.py` used to put every line-based tool one line out of step —
`str.splitlines()` breaks on it, the tokenizer does not; it is written as an escape),
no `os.startfile` outside `open_path.py`, and no heavy import on the startup path.
`.github/workflows/ci.yml` runs all of it plus a Windows job that installs the pinned
stack and imports every GUI module.

## Development Notes
- Built with PySide6 for cross-platform compatibility
- **Fast startup / lazy imports (report §4.1)**: at launch only PySide6 + the light
  GUI modules are imported — `basin_viewer` (numpy/xarray/rasterio/QtWebEngine) and
  `check_data_window` (→ `cwatm.run_cwatm` → scipy/pandas/netCDF4) are imported
  lazily at their call sites, and `cwatm_gui.py` warms the heavy stack up in a
  background daemon thread ~0.5 s after the window shows. **Keep it that way**: do
  not add module-level imports of cwatm / xarray / rasterio / plotly to
  `main_window.py` or anything it imports at the top level. The frozen splash
  closes only after `window.show()` (§4.5).
- Settings editor is plain text at all times (`QPlainTextEdit` + `QSyntaxHighlighter`, report §3.2) — what you save is exactly `toPlainText()`, folding only hides blocks
- Implements real-time date validation with signal connections
- Modular architecture allows for easy extension and maintenance
- **Unsaved-changes styling**: the Save / Save As buttons are recoloured light blue via `_set_save_dirty` whenever there are unsaved edits
- **Real-time Print Capture**: Custom stdout redirection system for immediate output display
- **Global Exception Handling**: Comprehensive error handling prevents application crashes
- **Thread Safety**: All CWatM operations run in separate threads with proper signal handling
- **Resource Management**: Automatic cleanup of file handles and NetCDF datasets after an interrupted run; the process std streams, the `gui.log` stream and the run-log handle are protected from this cleanup (`_protected_file_objects`)
- **Diagnostic log**: swallowed/guarded exceptions are recorded in `%LOCALAPPDATA%/CWatM_GUI/gui.log` (rotating, via `src/gui/utils/gui_log.py`) — check it when "nothing happened". **Qt's own messages land there too** (`cwatm_gui._install_qt_message_handler`, installed in `_create_app` before the `QApplication`): a warning/critical is logged **with the Python stack that triggered it**, plus Qt's own `QMessageLogContext` (category/file/line — usually only filled in a debug build) and a **widget line** (`focus=` / `under-mouse=` / `active-window=`, class + objectName). The stack names the call site when Python caused it; when the stack stops at `app.exec()` the message came from **inside Qt's C++ event loop** (`QFont::setPointSize: Point size <= 0 (-1)` is one of those — Qt's stylesheet font resolution meeting the editor's **pixel**-sized font; harmless, Qt keeps the current size) and the widget line is the only clue left. Chromium/QtWebEngine messages arrive from C++ callbacks the same way. **Three lines are filtered off the console** (`expected_messages`) because they are Chromium complaining about the configuration `_configure_qtwebengine` deliberately asks for — *"Sandboxing disabled by user"* (`--no-sandbox`, needed to launch `QtWebEngineProcess.exe` from a network share), *"--use-gl=angle is set with --disable-gpu. Expect troubles!"* and *"GPUInfo not initialized on GpuInfoUpdate"* (software WebGL with the GPU off). They are still recorded in `gui.log` at DEBUG, and **`CWATM_GUI_QT_VERBOSE=1`** puts them back on the console. Never silence a message here without that pairing: filtered means *logged elsewhere*, not lost. The message is still written to the **real** console (`sys.__stderr__`, `None`-guarded for `pythonw.exe`) and never to the redirected `sys.stderr`, so a run from a terminal looks unchanged and Qt chatter stays out of the CWatM output box
- **Native Qt Graphics**: Custom drawing routines for high-performance data visualization

## Data Visualization internals → `documentation/CWatM_GUI_Internals.md`

The rendering/interaction deep dives for the map & plot viewers live in
[`documentation/CWatM_GUI_Internals.md`](documentation/CWatM_GUI_Internals.md):
**Basin viewer** (infra `basin_viewer.py` + folium Show Basin `basin_viewer2.py`) ·
**Timeseries** · **NetCDF** · **Watercycle** · **Flow Diagram**. Their module files are
listed in [Core Modules](#core-modules); the always-true rules they depend on
(EPSG:4326, the shared `osmtile://` handler, the fast-startup / theme-token rules) stay
in this file.




