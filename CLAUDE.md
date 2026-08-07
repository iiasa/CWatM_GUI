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
- **UI & behaviour** — [Menu Bar & Keyboard Shortcuts](#menu-bar--keyboard-shortcuts-current-ui) · [Behavioral notes](#behavioral-notes) · [Gauges, mask and PathOut checks](#gauges-mask-and-pathout-checks) · [Check settingsfile](#check-settingsfile-settings-menu) · [Output-box log file](#output-box-log-file-configure-menu)
- **Architecture** — [Core Modules](#core-modules) · [Module Dependencies](#module-dependencies) · [CWatM Integration](#cwatm-integration)
- **Build & deps** — [Technical Details / Requirements](#requirements) · [Installation](#installation) · [Virtual environment & building the executable](#virtual-environment--building-the-executable) · [Watercycle template scripts](#watercycle-template-scripts-repo-root--canonical-balance-computation)
- **Development Notes** (fast-startup, thread-safety, styling rules)

**In [`documentation/CWatM_GUI_Internals.md`](documentation/CWatM_GUI_Internals.md)** (deep dives, kept out of the always-loaded reference):
- **Secondary windows** — Excel sheet editor · Compare settings · Output Explorer · Hidden Run CWatM · Batch Run · Run Ledger · Restore settingsfile · CWatM AI
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
results", "Help & Info"): **File · Settings · Excel · Tools · RUN CWATM ·
Configure │ Analyse │ CWatM AI · Help · Info** (**CWatM AI** is a clickable
top-level action — a button, not a dropdown — placed left of Help).

| Menu | Item | Shortcut | Action |
|------|------|----------|--------|
| File | Load .ini | Ctrl+O | Load a settings file (was the "Load Text" button) |
| File | Reload | Ctrl+L | Reload the current file from disk (prompts if there are unsaved changes) |
| File | Save .ini | Ctrl+S | Save to current file |
| File | Save As | Ctrl+Alt+S | Save to a new file |
| File | 1. … 6. (recent files) | — | Up to 6 recent settings files listed **directly** in the File menu between Save As and Exit (persisted via `QSettings`); rebuilt on open |
| File | Exit | — | Quit (prompts Save/Discard/Cancel if there are unsaved changes) |
| Settings | _(section headers)_ | — | The Settings menu is grouped into **five titled sections** — **View** · **Find & Replace** · **Edit** · **Bookmarks & Changes** · **Check & Compare** — rendered as bold, disabled header rows via `menu_builder._add_menu_section` (same helper as the Configure sections; **not** `QMenu.addSection`). The rows below follow that order |
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
| Settings | Compare settings | — | (last item, separator above) Side-by-side diff of two settings files — left = the current settings (preloaded), right has a **Load** button; files aligned with gray filler, differing lines **orange**, one synced scrollbar on the right, Next/Previous Diff, File/History/Settings menus — see `CWatM_GUI_Internals.md` |
| Excel | Crops | — | Open the **Crops** sheet of the settings `Excel_settings_file` (placeholders resolved) in an editable table that reproduces the sheet's cell colours; bottom buttons **Reload / Save / Save As** — see `CWatM_GUI_Internals.md` |
| Excel | Reservoirs | — | Same as Crops but opens the **Reservoirs** sheet; adds a **Release** button (right of Save As) that opens the **Reservoirs_downstream** sheet in its own editor — greyed out when that sheet is absent |
| Tools | _(section headers)_ | — | The Tools menu is grouped into **four titled sections** — **Basin & Gauges** · **Outputs** · **Setup & Data** · **Results & History** — rendered as bold, disabled header rows via `menu_builder._add_menu_section` (same helper as the Configure/Settings sections). The rows below are listed by section |
| Tools | Change Options | — | _(Setup & Data)_ Open the Options window (tooltip: "Display a popup with the settingsfile [Options]") |
| Tools | Show Basin | — | Open the basin viewer — the folium (Leaflet) **EPSG:4326** map (`basin_viewer2.py`); ups.nc/mask overlays in native lon/lat over an OSM WMS basemap. (This is the former "Show Basin2"; the classic native-canvas / Mercator viewer was removed.) **Projected (non lat/lon) grids** — x/y coordinates, e.g. Norway UTM33 (`grid_is_latlon` in `basin_viewer.py`) — are shown in Leaflet **CRS.Simple** on the raw x/y **without** an OSM basemap (basemap selector + OSM-transparency slider disabled, overlay fully opaque, read-outs labelled X/Y); everything else (mask, gauges, clicks, Copy Mask/Gauge) works unchanged |
| Tools | Set Gauge | — | Set Gauges to the largest-upstream point inside the mask |
| Tools | Add output Watercycle | — | Insert `OUT_TSS_AreaSum_MonthTot = WaterCycle` under `[OUTPUT]` if absent |
| Tools | Add output variables | — | (separator below) Open a picker of the metaNetcdf.xml output variables that **fit the current `[OPTIONS]`** (glacier/modflow/small-lake/… vars hidden when their feature is off); shows only `priority="high"` vars by default, a **Load all Variable** toggle above the filter shows every fitting var; item tooltips show `unit:` + `Dimension:` (metaNetcdf `dim`); **left-click** inserts it at the editor cursor — only on an `OUT_TSS_…`/`OUT_MAP_…` line; **right-click** opens a type menu (Timeseries (TSS) ▸ time step / **upstream calculation** ▸ `AreaSum`\|`AreaAvg` ▸ time step, or Map (MAP) ▸ time step) that builds `OUT_<TSS\|MAP>_<selection>` and appends the variable to that line, creating the key under `[OUTPUT]` if absent — see `CWatM_GUI_Internals.md` |
| Tools | Check Data | — | Open the Check Data window |
| Tools | Create PathOut Folder | — | Create the resolved PathOut directory if missing |
| Tools | Restore settingsfile | — | Open a CWatM output NetCDF (`dis*.nc`) and show its stored run metadata; **Restore settingsfile** re-creates the settings file from `version_settingsfile`, **Show Inputfiles** lists `version_inputfiles` — see `CWatM_GUI_Internals.md` |
| Tools | Run Ledger | — | (last item, separator above) Table of past runs (time, Title, PathOut, duration, success, last discharge); reopen a run's results (Output Explorer), reload its settings, or **Compare settings** of two marked runs — see `CWatM_GUI_Internals.md` |
| RUN CWATM | Run CWATM | Ctrl+R | Run / stop the CWatM model |
| RUN CWATM | Hidden Run CWatM | — | Open a **separate, non-modal window** that runs CWatM in its **own OS process**, independent of the main run and main GUI — several can run in parallel — see `CWatM_GUI_Internals.md` |
| RUN CWATM | Batch Run… | — | Run many scenarios from the loaded settings file — a table where each row overrides a few keys + its own PathOut → a temp `.ini` run in its own process, **up to N in parallel** — see `CWatM_GUI_Internals.md` |
| Configure | _(section headers)_ | — | The Configure menu is grouped into **five titled sections** — **Output** · **Startup & Model** · **Display** · **Editor & Dates** · **Run History** — rendered as bold, disabled (non-clickable) header rows via `menu_builder._add_menu_section` (**not** `QMenu.addSection`, whose title text the native windows11 style does not draw). The rows below are listed by section |
| Configure | _(item types)_ | — | Three visually distinct item kinds: **tick boxes** carry a ☐/☑ box (`_wire_checkbox_glyph`, kept in sync on toggle — so a toggle is obvious even unchecked), **dialog-openers** end with `…` (Set output box file… / Show Decimals… / Transparency… / Run history folder…/retention…), and **submenus** show `▸` (Mode / Default openstreet map / Select animal). A `_KeepMenuOpenFilter` on the Configure menu **keeps it open** after a tick box is clicked so the ☐→☑ change is visible |
| Configure | Set output box file | — | _(Output)_ Choose a custom output-box log file (kept in memory) |
| Configure | Write output box | — | Checkable; writes the run log (tooltip shows the current output path) |
| Configure | Load previous settings at start | — | Checkable (persisted `startup/load_previous`, default OFF); when ticked, the most recently used settings file is re-opened automatically on the next startup (handled in `cwatm_gui.py main()` when no file is passed on the command line) |
| Configure | Use Modflow | — | Checkable (persisted `modflow/enabled`, default OFF); when ON the GUI **pre-imports flopy** (the CWatM↔MODFLOW library — heavy, pulls the matplotlib stack) so in-process MODFLOW use is ready; when OFF flopy is never loaded, keeping startup fast (`src/gui/utils/modflow.py`, `_on_use_modflow_toggled`) |
| _(hidden)_ | ~~Run model in separate process~~ | — | **No longer shown in Configure** but the functionality is kept: `run_subprocess_action` is created standalone (default ON, persisted `run/subprocess`) and still drives `_run_subprocess_enabled` (own OS process = real Stop, crash isolation). Re-add it to a menu to expose it again |
| Configure | Default openstreet map | — | Submenu; pick the default basemap for **Show Basin** — its EPSG:4326 WMS layers (OSM / Topographic / Terrain / Dark), persisted via `QSettings` (`basin/default_basemap`) |
| Configure | Skill of User | — | _(Editor & Dates, first item)_ Exclusive submenu — **Beginner / Advanced / Expert**; decides how much of the settings file is shown (hides the sections the level may not see). In sync with the colour-coded level button right of the editor's `-` button; persisted `editor/level`, default Expert (see the Skill of User behavioral note) |
| Configure | Mode | — | Submenu; colour theme of the whole GUI: **Normal** (classic light), **Dark Mode**, **Mikhail** (black background, amber font); switches live, persisted via `QSettings` (`display/theme`) |
| Configure | Bookmark Change | — | Checkable (persisted `editor/bookmark_change`); when ticked, a changed settings line is **auto-bookmarked** — but skipped if a bookmark already sits 1 or 2 lines above/below it |
| Configure | Show Decimals | — | Set how many decimals numeric values show throughout all displays (default 3, range 0–12), persisted via `QSettings` (`display/decimals`) |
| Configure | Transparency | — | Set the **initial** map transparency (0–100) the **NetCDF** and **Show Basin** viewers open with (start value of their transparency slider), default 100, persisted via `QSettings` (`display/transparency`) |
| Configure | Web-style date picker | — | Checkable (persisted `display/date_picker_web`, default ON): Start/Spin/End dates picked via a 📅 button + frameless shadowed calendar popup; unticked = classic `QDateEdit` drop-down calendar (see the Date calendar popups behavioral note) |
| Configure | Date timeline | — | Checkable (persisted `display/date_timeline`, default ON): show the three-handle **Start/Spin/End timeline** below the date fields — drag a handle (or click the track to jump the nearest one) to set the date; the light band behind the track is the meteo-forcing coverage (see the Date calendar popups behavioral note) |
| Configure | Show Header | — | Checkable (persisted `display/show_header`, default ON): show the top **banner** (CWatM icon + title + "The Community Water Model User Interface" + IIASA logo). Unticked hides the banner (`self._banner_widget.setVisible(False)`) so everything below moves up; ticked looks like before (`_on_show_header_toggled`) |
| Configure | Select animal | — | Exclusive submenu (below Transparency) — the cameo shown now and then on the live discharge sparkline: **Fish · Otter · Beaver · Sailboat**, persisted `display/animal` (default Fish); applied live via `discharge_sparkline.set_animal` (edit the `ANIMALS` registry to change the set) |
| Configure | Run history folder… | — | Choose the general folder where the **Run Ledger** (`run_ledger.json`) is stored (`history/folder`, default `%LOCALAPPDATA%/CWatM_GUI`) |
| Configure | Run history retention… | — | How many days of runs to keep in the Run Ledger (0 = keep forever), `history/retention_days`, default 60 |
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
| Info | About CWatM | — | About dialog |

- **Save locked while CWatM runs**: during a run all functionality stays available
  (so you can analyse, chat with CWatM AI, etc.) — only **Save** is greyed out (the
  run uses the file on disk; **Save As** still works). `_set_tools_enabled(False)`
  greys just the Save button + File ▸ Save .ini action, re-enabled on
  finish/error/stop.
- **QAction/QMenu lifetime**: menus are kept referenced (`self._menus`) and the
  "Write output" state is mirrored to a plain bool so a stale QAction cannot crash a
  run; menu-touching code is guarded against `RuntimeError` (deleted C++ object).

### Behavioral notes
- **Full view on start**: the main window always opens **maximized**
  (`Qt.WindowMaximized`) regardless of screen size.
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
- **Plain-text editor (report §3.2)**: the settings editor is a `SettingsEditor`
  (`QPlainTextEdit` + `IniHighlighter` syntax highlighting —
  `src/gui/widgets/settings_editor.py`); the document **is** the settings file at
  all times, saving is `toPlainText()`. **Folding** hides a section's blocks
  (`QTextBlock.setVisible(False)`) without removing them — folded sections are
  still saved/searched, and Find/Replace/jump-to-bottom auto-unfold a hit inside
  a folded section (`reveal_cursor`). Fold a section by **double-clicking its
  `[SECTION]` header** or clicking the ▾/▸ marker in the gutter.
- **Skill of User / experience level (Beginner / Advanced / Expert)**: a
  **colour-coded button** right of the editor's `-` font button cycles
  Beginner → Advanced → Expert → Beginner (`cycle_experience_level` /
  `set_experience_level`, persisted `editor/level`, default **Expert**). It is
  mirrored by **Configure ▸ Skill of User** (an exclusive radio submenu — the
  **first item of the Editor & Dates section**, tooltip "The skill of the user
  determines how much of the settingsfile is presented") — the two stay in sync
  via `_sync_level_menu` /
  `_level_menu_actions`. The button's background is the level colour at **50%
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
  everything (the pre-existing behaviour). Driven by
  `main_window._apply_experience_level` (`_LEVEL_ALLOWED`) →
  `SettingsEditor.set_locked_sections(names)` (hides locked sections;
  `apply_folds` / `unfold_all` / `set_content_preserving` all skip locked
  sections so `_folded` stays the user's own fold set); the locked set is
  **recomputed from the current section list after every file load**, so it
  stays correct across files.
- **Editor extras**: a **line-number gutter** showing **file line numbers**
  (numbers jump across a folded section) plus the ▾/▸ fold markers
  (`src/gui/widgets/line_number_gutter.py`), and **hover
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
- **Bookmark Change / Goto last change**: Configure ▸ **Bookmark Change** (persisted
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
  `set_current_diff_rows`). The last three are used only by the Compare settings window.
- **Date calendar popups**: the Start/Spin/End date fields use `CWatMCalendar`
  (`date_manager.py`, subclass of `QCalendarWidget` with a custom `paintCell`):
  selected day = filled accent circle, today = thin accent ring, the **other two
  date fields** shown as small dots (green = Start, orange = Spin, red = End;
  side by side when equal), and days **outside the meteo-forcing time coverage
  dimmed** — the coverage comes from `_forcing_time_range` (the same F4 semantic
  check) via `main_window._forcing_range_for_calendar`, computed lazily on the
  first popup open and cached in `DateManager` until the next file load
  (`invalidate_forcing_range` in `set_dates_from_config`). All colours are theme
  tokens read at paint time; the popup chrome (nav bar, headers, no grid/week
  numbers) is styled by QSS in `DateManager.retheme()`. **Two picker styles**
  (Configure ▸ **Web-style date picker**, persisted `display/date_picker_web`,
  default ON): the fields are sized exactly to the date text
  (`setFixedWidth(sizeHint)` in `retheme`); *web-style* = a calendar button
  right of each field **carrying the field's handle colour** (background at 70%
  transparency, border + `_calendar_icon` glyph in the full colour —
  green/orange/red; the field's spin arrows are removed, `NoButtons`) opening a
  frameless, rounded, drop-shadowed popup (`_CalendarPopup`, `Qt.Popup` — closes
  on outside click/Esc; clicking a day sets the field); *classic* (unticked) =
  the normal `QDateEdit` drop-down (arrows restored). Both use
  the same `CWatMCalendar` cells; `set_web_picker` switches live. Below the
  date row sits the **`DateTimeline`** (option 4, Configure ▸ **Date timeline**,
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
  **cell-value and lon/lat hovers** + point labels). Set via **Configure ▸
  Show Decimals**, restored from `QSettings` at startup. Coordinates written back
  into the settings file (gauge / mask copy) keep their fixed 4-decimal precision -
  that is data serialisation, not a display. Newly opened displays pick up the
  current value; on-the-fly read-outs update immediately.
- **Global initial transparency**: the same `display_format.py` also holds
  `get_transparency`/`set_transparency` (0–100, default 100) — the **start value** of
  the transparency slider in the **NetCDF** and **Show Basin** viewers (read in their
  `__init__`, so each newly opened window opens at that transparency; changing it later
  via the slider is per-window). Set via **Configure ▸ Transparency**, restored from
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
  animal is chosen in **Configure ▸ Select animal** (Fish/Otter/Beaver/Sailboat,
  `ANIMALS` registry + `display/animal`; `set_animal` applies it live).
- **Taskbar icon**: the app sets a Windows AppUserModelID and `assets/cwatm.ico` so
  the taskbar shows the CWatM icon (see `cwatm_gui.py`).
- **Colour themes (Configure ▸ Mode)**: `src/gui/utils/theme.py` holds three token
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
  chrome — use a theme token.**
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
`main_window.check_settingsfile` walks the **editor content** (not the saved file) line
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
- **Clearing the check** (`main_window.clear_checking` → `SettingsEditor.clear_checking`)
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
    **Array dimensions** are checked too (`_dim_problem`): multi-dim variables need
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

### Output-box log file (Configure menu)
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
of this always-loaded reference to keep it lean): **Excel sheet editor · Compare settings ·
Output Explorer · Hidden Run CWatM · Batch Run · Run Ledger · Restore settingsfile ·
CWatM AI**. Their menu entries + one-line behaviour are in the Menu Bar table above; their
module files in [Core Modules](#core-modules) below.

## Architecture

The application is structured with a modular architecture for better maintainability.

### Core Modules

- **`cwatm_gui.py`**: Main entry point and application launcher with global exception handling
- **`src/gui/components/main_window.py`**: Main window class orchestrating all components (inherits the three mixins below)
- **`src/gui/components/menu_builder.py`**: `MenuBuilderMixin` — builds the full menu bar and maintains the History menu
- **`src/gui/components/run_controller.py`**: `RunControllerMixin` — start/stop the threaded CWatM run, progress/finish/error handling, run-log file, menu locking, post-run cleanup
- **`src/gui/components/output_box.py`**: `OutputBoxMixin` — the CWatM output box (throttled appends, `\r` progress overwrite, copy actions)
- **`src/gui/components/config_parser.py`**: Configuration file parsing and formatting logic
- **`src/gui/managers/date_manager.py`**: Date input validation and management
- **`src/gui/managers/file_manager.py`**: File I/O operations and management
- **`src/gui/managers/text_display.py`**: Text area operations and cursor management (plain text only since §3.2)
- **`src/gui/widgets/settings_editor.py`**: `SettingsEditor` — the plain-text settings editor (`QPlainTextEdit` + `IniHighlighter` + section folding via block visibility; report §3.2)
- **`src/gui/widgets/options_window.py`**: Options management window for boolean configurations
- **`src/gui/widgets/check_data_window.py`**: Data validation window for CWatM configuration checking
- **`src/gui/widgets/output_variables_window.py`**: Tools ▸ Add output variables — `OutputVariablesWindow`, an alphabetical, filterable picker of `meta_netcdf.output_varnames()` (metaNetcdf.xml data variables; no-type / `_`-prefixed / list-table / scalar-type vars excluded) narrowed to those that fit the loaded `[OPTIONS]` (`_FEATURE_VAR_PATTERNS`: glacier/modflow/small-lake/waterbody/water-demand/runoff-conc/environ vars hidden when their switch is off); by default only `priority="high"` vars are shown (`output_varnames(high_only=True)`), a checkable **Load all Variable** toggle above the filter box shows every fitting var; each item's tooltip carries `unit:` + `Dimension:` (the metaNetcdf `dim` attribute via `meta_netcdf.dim_of`); an item click **toggles** the varname on the settings-editor's current line — inserted at the cursor with auto comma separators if absent, removed if already present — but only on an `OUT_TSS_…`/`OUT_MAP_…` line (else it warns + beeps). **Removal deletes the whole output line** when the varname was the last one on it (`_remove_output`, shared by both click styles — so a line the right-click menu just created disappears again on a second pick). Note the shipped `cwatm/metaNetcdf.xml` carries **no `priority` attribute at all**, so the default high-priority view would be empty — `_available_varnames` detects that and falls back to the full list, noting it in the status line (`_priority_missing`); it starts filtering on its own once the xml gains `priority="high"` flags. A **right-click** needs no cursor position: `_on_context_menu` builds a two-level `QMenu` (`setToolTipsVisible`) — **Timeseries (TSS)** with the ten `_TIME_TYPES` plus an **upstream calculation** submenu that branches once more into `AreaSum` / `AreaAvg` (`_AREA_AGGS`), each listing the seven `_AREA_TIME_TYPES` (Daily/Month*/Annual* — TSS-only), and **Map (MAP)** with the same ten types; every entry's tooltip explains the time step (`_TYPE_TOOLTIPS`, the Area ones generated as "… summing up/averaging over all upstream cells") and shows the resulting line. `_add_output` then appends the variable to the existing `OUT_<TSS\|MAP>_<sel>` line (preferring a hit inside `[OUTPUT]`; a `None`/empty value is replaced rather than appended to) or creates the key at the end of `[OUTPUT]` (`_insert_output_line`, same placement as `add_output_watercycle`), written through `set_content_preserving` so it is **one undo step** that keeps folding, then jumps the cursor there (`_goto_row` + `reveal_cursor`). `OUT_TSS_TotalEnd` is shown **disabled** — `outputTypTss` (cwatm `globals.py`) has no `totalend`, it is map-only
- **`src/gui/widgets/excel_sheet_window.py`**: `ExcelSheetWindow` — Excel ▸ Crops / Reservoirs: an editable `QTableWidget` view of one xlsx worksheet that reproduces the sheet's cell fill/font colours (openpyxl); Reload / Save / Save As write edits back preserving all other sheets and styling; optional **Release** button opens a companion sheet (Reservoirs → Reservoirs_downstream)
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
- **`src/gui/widgets/batch_runner_window.py`**: RUN CWATM ▸ Batch Run… — `BatchRunnerWindow`, a scenario table (base .ini + per-row key overrides → temp .ini) that runs up to N in parallel via `CWatMProcessWorker`; `set_settings_key` does the per-key value replacement
- **`src/gui/widgets/run_ledger_window.py`**: RUN CWATM ▸ Run Ledger — `RunLedgerWindow`, a table of past runs (open results / reload settings)
- **`src/gui/utils/run_ledger.py`**: Persistent run log (`run_ledger.json`) — `add_entry`/`load_entries`/`make_entry`, per-run **settings snapshots** (`snapshots/`, diffed by Compare settings), plus the configurable folder + retention (Configure menu)
- **`src/gui/utils/metrics.py`**: Goodness-of-fit scores (KGE / NSE / PBIAS / RMSE) for the Timeseries observed-vs-simulated comparison
- **`src/gui/utils/cwatm_process_worker.py`**: Subprocess CWatM worker (QProcess; default run mode — real Stop, crash isolation). Optional `output_sink(text, is_error)` ctor arg routes run output to a caller's box instead of the global `sys.stdout`/`sys.stderr` (used by the Hidden Run windows; default `None` = main-window behaviour)
- **`src/gui/widgets/hidden_run_window.py`**: RUN CWATM ▸ Hidden Run CWatM — `HiddenRunWindow`, a non-modal window that runs CWatM in its own process (via `CWatMProcessWorker` + `output_sink`) with a bold-green settings label, Load / Run-Stop buttons and its own output box; several can run in parallel
- **`src/gui/utils/cwatm_model_runner.py`**: Child-process side of the subprocess run (no Qt; stdout marker protocol)
- **`cwatm_model.py`** (root): entry script of `CWatM_model.exe` (the frozen child process)
- **`src/gui/utils/cwatm_worker.py`**: Threaded CWatM execution worker (in-process fallback)
- **`src/gui/utils/display_format.py`**: Global display-decimals setting (Configure ▸ Show Decimals)
- **`src/gui/utils/modflow.py`**: Configure ▸ Use Modflow toggle (`modflow/enabled`) — `is_enabled`/`set_enabled` + `warm_flopy` (background flopy pre-import); gates the heavy flopy/matplotlib import so a non-MODFLOW start stays fast
- **`src/gui/utils/theme.py`**: Colour themes (Configure ▸ Mode: Normal / Dark / Mikhail) — token sets, app palette/QSS, persistence
- **`src/gui/utils/assets.py`**: `asset_path()` — absolute asset resolution (source, `_internal/`, exe folder)
- **`src/gui/utils/gui_log.py`**: Diagnostic logging — swallowed exceptions go to a rotating `%LOCALAPPDATA%/CWatM_GUI/gui.log` (UI behaviour unchanged)
- **`src/gui/utils/warning_filters.py`**: The third-party warnings the GUI silences — currently only rasterio 1.5.0 × numpy 2.5 ("Setting the shape on a NumPy array has been deprecated", raised inside `rasterio._io.read()` but **attributed to the caller**, i.e. `cwatm/management_modules/data_handling.py:317/654`, so it looks like a CWatM problem). Three nets, because a user's machine may enable DeprecationWarnings (`PYTHONWARNINGS`, IDE, older build): `apply()` installs the message-matched filter **and** exports `PYTHONWARNINGS` (called at the top of `cwatm_gui.py` and of `cwatm_model_runner.py`, before numpy/rasterio/cwatm are imported; `cwatm_process_worker.start()` also puts it in the child's `QProcessEnvironment`), and `LineSuppressor` drops the warning's lines on the way to the output box (`cwatm_process_worker._forward` for every child run — main/Hidden/Batch — and `print_redirector` for in-process prints). Delete the module + its call sites once a fixed rasterio ships
- **`src/gui/utils/window_geometry.py`**: `GeometryMemoryMixin` — persists window size/position of the Analyse/Basin windows via QSettings
- **`src/gui/utils/meta_netcdf.py`**: Cached varname → (unit, long_name, description) lookup from `cwatm/metaNetcdf.xml` (editor hover tooltips); also `all_varnames()` (Check settingsfile output-name validation), `output_varnames(high_only=)` (Add output variables — data vars, excluding no-type / `_`-prefixed names, `list(...)` tables and Flag/Number/String scalar types; `high_only` keeps only `priority="high"`), and `dim_of()`/`priority_of()` (the metaNetcdf `dim`/`priority` attributes, parsed alongside the type)
- **`src/gui/widgets/line_number_gutter.py`**: Line-number gutter widget for the settings editor
- **`src/gui/widgets/notebooklm_window.py`**: CWatM AI — `NotebookLMWindow` (Gemini/NotebookLM chat: persistent transcript + question history, Up/Down recall, login-state colouring; see CWatM AI section)
- **`src/gui/utils/notebooklm_worker.py`**: `NotebookLMWorker(QThread)` — off-thread NotebookLM questions (queue, lazy connect, `status/reply/error/busy` signals)
- **`src/gui/utils/notebooklm_client.py`**: The **only** importer of `notebooklm` — `NotebookLMClientWrapper` (async→sync over one asyncio loop; `connect/ask/close`, `is_authenticated`, notebook auto-resolve)
- **`src/gui/widgets/compare_settings_window.py`**: Tools ▸ Compare settings — `CompareSettingsWindow` (two side-by-side `SettingsEditor` panes; left preloaded from the main window, right has a Load button; differing lines marked red via `diff_rows` + `set_error_rows`)
- **`src/gui/widgets/restore_settings_window.py`**: Tools ▸ Restore settingsfile — `RestoreSettingsWindow` (NetCDF metadata table + **Restore settingsfile** / **Show Inputfiles** buttons) and `InputFilesWindow` (File/Date table from `version_inputfiles`); `read_netcdf_metadata`/`read_netcdf_attr`/`parse_input_files`

### Module Dependencies
```
cwatm_gui.py
    └── src/gui/components/main_window.py
            ├── src/gui/components/menu_builder.py    (mixin)
            ├── src/gui/components/run_controller.py  (mixin)
            ├── src/gui/components/output_box.py      (mixin)
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
  action still exists and persists `run/subprocess`, but is **no longer shown in the
  Configure menu** — default ON) → the old `CWatMWorker` `QThread` path (same signals
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
python cwatm_gui.py
```
Do **not** install the GDAL wheel — rasterio ships its own GDAL (see `cwtmexe.md`).

The application starts in maximized window mode for optimal viewing of configuration files.

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
  **Excel menu** (`excel_sheet_window.py`) and cwatm's xlsx settings-sheet reads
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
  run works frozen), but the GUI only *imports* flopy when **Configure ▸ Use Modflow** is
  on, so a normal start is unaffected. It also builds a **second executable, `CWatM_model.exe`**:
  the lightweight child process the GUI spawns for every model run (no Qt — fast
  start; `console=True` for valid std pipes, but QProcess starts it with
  `CREATE_NO_WINDOW` so no console window appears). It is built with
  `contents_directory='.'` and **moved into `_internal/`** at the end of the spec
  (users see only `CWatM_GUI.exe` in the app folder; the bootloader finds all its
  dependencies next to itself there — never rename `_internal` or the model exe's
  bootstrap breaks). The GUI looks for it in `_internal/` first, then the folder
  root (older builds).
- Build: `python -m PyInstaller cwatm_gui_dir.spec --noconfirm` (UPX disabled for faster builds).
- Reference docs in this folder: **`cwtmexe.md`** (rasterio/xarray/GDAL packaging fixes), **`makeitfaster.md`** (PyInstaller speed), **`nuitka_plan.md`** (optional Nuitka build for faster runtime).

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
data** (QSettings, the `%LOCALAPPDATA%\CWatM_GUI` run ledger). Bump `MyAppVersion` in the
`.iss` per release; keep the fixed `AppId` GUID so upgrades/uninstall track correctly.
- **Build the installer**: first `python -m PyInstaller cwatm_gui_dir.spec --noconfirm`
  (produces `dist\CWatM_GUI\`), then `ISCC installer\CWatM_GUI.iss` →
  `installer\Output\CWatM_GUI_Setup.exe` (~260 MB, lzma2/max solid). `ISCC.exe` is the
  Inno Setup 7 compiler; its location differs per machine — this box:
  `%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe`, the other build box:
  `C:\Apps\Inno Setup 7\ISCC.exe` (Inno Setup is installable per-user via its own
  `/CURRENTUSER` flag). The script uses only 6-era directives, which 7 compiles
  unchanged.
- The setup is **unsigned**, so SmartScreen / FortiClient may warn on first run even
  though it installs fine — Authenticode-sign the setup + both exes to avoid that.

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
- **Diagnostic log**: swallowed/guarded exceptions are recorded in `%LOCALAPPDATA%/CWatM_GUI/gui.log` (rotating, via `src/gui/utils/gui_log.py`) — check it when "nothing happened"
- **Native Qt Graphics**: Custom drawing routines for high-performance data visualization

## Data Visualization internals → `documentation/CWatM_GUI_Internals.md`

The rendering/interaction deep dives for the map & plot viewers live in
[`documentation/CWatM_GUI_Internals.md`](documentation/CWatM_GUI_Internals.md):
**Basin viewer** (infra `basin_viewer.py` + folium Show Basin `basin_viewer2.py`) ·
**Timeseries** · **NetCDF** · **Watercycle** · **Flow Diagram**. Their module files are
listed in [Core Modules](#core-modules); the always-true rules they depend on
(EPSG:4326, the shared `osmtile://` handler, the fast-startup / theme-token rules) stay
in this file.

