# CWatM GUI — Internals (secondary windows & data-visualization deep dives)

> Companion to the root **`CLAUDE.md`** (the concise developer reference). This file
> holds the **per-feature internals** for the secondary windows and the
> **data-visualization** viewers — the deep detail that CLAUDE.md links to but does not
> inline, to keep the always-loaded reference lean. The invariants that must not be
> broken (fast-startup / lazy-import rule, theme-token rule, subprocess run model,
> menu bar, architecture, build) stay in `CLAUDE.md`.

## Secondary-window internals

### Excel sheet editor (Excel menu)
**Excel ▸ Crops** / **Excel ▸ Reservoirs** (`main_window.open_excel_sheet(sheet_name)`)
resolve the settings `Excel_settings_file` value (placeholders via
`_resolve_settings_placeholders`, made absolute against the settings-file dir) and open
that worksheet in `ExcelSheetWindow` (`src/gui/widgets/excel_sheet_window.py`). The two
menu items are the same generic handler with a different sheet name; adding another
sheet is one more `excel_menu.addAction(...)` → `open_excel_sheet("<Sheet>")`.
- The sheet is read with **openpyxl** (keeping styles) into an **editable
  `QTableWidget`** with Excel A1-style headers (column letters / row numbers). Each
  cell reproduces the workbook's **fill** and **font** colour (solid `rgb` fills →
  `QBrush`; `_argb_to_qcolor` converts `FF00A87C`-style ARGB; theme/indexed colours
  are left uncoloured), plus bold/italic.
- **Save / Save As** push only the **changed** cells back into the loaded workbook
  (`_flush_to_wb`: unchanged cells - including the `\xa0` spacers - are left untouched
  so their type/formatting survives; numbers are re-parsed to int/float) and
  `wb.save()`, so **every other sheet and all styling is preserved**; a merged
  non-anchor cell is skipped, and a file open in Excel reports a friendly error.
  **Reload** re-reads from disk (confirming if there are unsaved edits). The window
  is modal, geometry remembered via QSettings key `excel_<sheet>`.
- **Release button** (`release_sheet` arg → `_open_release`): Reservoirs is opened with
  `open_excel_sheet("Reservoirs", release_sheet="Reservoirs_downstream")`, which adds a
  **Release** button to the right of Save As (with a gap). It is **enabled only when the
  companion sheet exists** in the workbook (checked in `_load`), otherwise greyed out;
  clicking it opens that sheet in its own `ExcelSheetWindow` (same colours/buttons).
  Crops passes no `release_sheet`, so it has no Release button.
- Needs `openpyxl` (already a dependency - cwatm reads xlsx settings sheets via
  `pd.read_excel`; do not exclude it from the build, §4.4). Reusable for other sheets:
  `ExcelSheetWindow(path, sheet_name, parent, release_sheet=None)`.

### Compare settings (Settings menu)
**Settings ▸ Compare settings** (last item, separator above)
(`main_window.open_compare_settings` →
`src/gui/widgets/compare_settings_window.py`, `CompareSettingsWindow`) opens a
non-modal side-by-side diff of two settings files. Two `_ComparePane`s, each a
`SettingsEditor` + `LineNumberGutter` with the main window's top button row
(**Save / Save As / Fold All / Unfold All / Top / Down**). The **left** pane is
preloaded with the main window's **current** editor text (live, incl. unsaved edits)
and file path; the **right** pane starts empty and adds a **Load** button (left of
Save) for a `*.ini`.
- **Alignment**: `align_and_diff` (difflib opcodes) inserts light-gray **filler**
  lines on the shorter side of each change so equal lines share a row on both sides;
  both editors end up the same length. Differing lines are marked **orange**
  (`SettingsEditor.set_diff_rows` + `diff_line` token), filler lines **gray**
  (`set_filler_rows` + `filler_line` token), and the difference you **jumped to**
  (Next/Previous Diff) a **darker orange** (`set_current_diff_rows` +
  `current_diff_line`). File-name headers are **bold dark green**. Each pane's
  `real_text()` strips the (empty) filler rows,
  so **Save never writes the padding** and edits to real lines survive; `real_text` is
  also what feeds the next re-compare (Load / Save re-run `_recompare`).
- **Synced scrolling**: the two editors' vertical + horizontal scrollbars mirror each
  other (`_link_scrollbars`, reentrancy-guarded). Only the **right** pane shows a
  vertical scrollbar (wide 16px, same as the main window's right part) — a single
  scrollbar on the very right that drives both; the left pane hides its own.
- **Next Diff F6 / Prev Diff Sh+F6** (bigger **blue** buttons flush-right on the
  **left** pane = the **centre of the window**, between the left pane's Down and the
  right pane's Load; hotkeys **F6 / Shift+F6**; also in the Settings menu): jump both
  editors to the next/previous difference block (`_diff_blocks`, `_goto_diff` →
  `centerCursor`) and mark that block a **darker orange** (`_highlight_current_block`).
  The right pane's Load/Save/Save As are shifted right of the divider (`lead_spacing=60`).
  Only the **left** pane has Top/Down (scrollbars synced).
- **Fold sync**: only the **left** pane has **Fold All / Unfold All**, and they fold/
  unfold **both** sides (`_fold_all_both`/`_unfold_all_both`); folding/unfolding a
  single **section** on either side mirrors to the other (`foldingChanged` →
  `_sync_folds` via `apply_folds(folded_sections())`, reentrancy-guarded).
- **File / History / Settings menu bar** operating on the **active** side (whichever
  editor last had focus, tracked via a FocusIn event filter): File = Load/Reload/Save/
  Save As/Close (Ctrl+O/L/S, Ctrl+Alt+S); History = the main window's `_recent_files`
  opened into the active pane; Settings = Fold All/Unfold All (fold both, Alt+0/
  Alt+Shift+0), Top/Down (Alt+T/Alt+D), Find (**F5** — free now that diff-nav is F6),
  Find next (Ctrl+F), **Bookmarks** (Toggle/Next/Previous/Clear — Ctrl+F2/F2/Shift+F2/
  Ctrl+Shift+F2, same as the main window), Next/Previous Diff.
Themed like the other secondary windows; geometry key `compare_settings`.
- **Open two specific files** (used by Run Ledger ▸ Compare settings):
  `open_compare_files(parent, a, b)` → `CompareSettingsWindow.load_files(left, right)`
  reads both paths into the two panes and re-diffs (a missing file loads as empty).

### Output Explorer (Analyse menu)
**Analyse ▸ Output Explorer** (`main_window.open_output_explorer` →
`src/gui/widgets/output_explorer.py`, `OutputExplorerWindow`) opens a **non-modal**
`QTreeView`/`QFileSystemModel` rooted at the resolved **PathOut** (falls back to the
settings-file directory; a friendly note if neither exists). Name-filtered to
`*.nc/*.csv/*.html/*.txt/*.tif/*.map` (`setNameFilterDisables(False)` hides other
files, keeps folders). **Double-clicking** a file (or Open) **dispatches** it to the
existing viewer by name: `*.nc`→`NetcdfWindow` (incl. `dis*.nc`),
`*watercycle*.csv`→`WatercycleWindow`, other `*.csv`→`TimeseriesWindow`, else
`os.startfile`. Each viewer is imported lazily at dispatch (fast-startup rule) and
opened modally over the still-open explorer. **Refresh** re-roots (picks up new run
output), **Change folder…** browses elsewhere. Themed at construction; kept alive on
`parent._output_explorer_windows`; geometry key `output_explorer`.

### Hidden Run CWatM (RUN CWATM menu)
**RUN CWATM ▸ Hidden Run CWatM** (`run_controller.open_hidden_run` →
`src/gui/widgets/hidden_run_window.py`, `HiddenRunWindow`) opens a small **non-modal**
window that runs CWatM on one settings file in its **own OS process**, independent of
the main run and of every other Hidden Run window — so **several can run in parallel**
while the main GUI stays fully interactive. Each window:
- opens **pre-loaded** with the settings file currently loaded in the main window (an
  `.ini` in that file's directory); a **Load** button picks a different `.ini` (dialog
  starts in that directory);
- shows the settings-file path in **bold green** (`#1a9a3c`);
- has a **Run CWatM** button that toggles to **Stop CWatM** (blue→red) while running;
- streams the run into its **own** read-only output box (per-timestep `\r` discharge
  line overwrites in place, errors in dark red — same rendering as the main box).
- The run reuses **`CWatMProcessWorker`** with a new **`output_sink`** parameter, so the
  model output is delivered to *this* window's box instead of the global
  `sys.stdout`/`sys.stderr` (default `None` = unchanged main-window behaviour). Each
  window owns its own worker + `QProcess`; `WA_DeleteOnClose` + `closeEvent` kill an
  in-flight run when the window is closed (no orphan model process). The main window
  keeps the windows in `self._hidden_run_windows` so they are not GC'd; the list entry
  is dropped on `destroyed`.

### Batch Run (RUN CWATM menu)
**RUN CWATM ▸ Batch Run…** (`main_window.open_batch_runner` →
`src/gui/widgets/batch_runner_window.py`, `BatchRunnerWindow`) runs many scenarios
derived from **one base settings file** (the file loaded in the main window). A
**table** where each row is a scenario: **Scenario** name, its own **PathOut**, plus
per-scenario **key = value overrides** (columns added with **Add key column**, which
takes the key from the **settings-editor cursor line** via `_key_at_main_cursor`, no
dialog — with a tooltip; a non-`key = value` line is ignored with a hint). For each
row the GUI builds the scenario content (`set_settings_key` replaces each override key's
value + PathOut in the base content — first uncommented `key =` line, appended if absent)
and writes a temporary `<base>.batch_<name>.ini` **next to the base file** (so
placeholders / relative paths resolve identically), then runs it in its **own OS
process** via `CWatMProcessWorker` (the same subprocess worker as the main run).
- **Up to N in parallel** (a spin box, default 1): `_pump` keeps up to N workers running
  and starts queued rows as slots free; each row shows a live **Progress** (`worker.progress`)
  and **Status** (queued/running/done/failed/stopped) cell. **Run all** / **Stop all**
  (Stop kills every running process). New rows default PathOut to
  `<base PathOut>_<scenario>` so runs don't collide; **Duplicate** copies a row,
  **Remove** deletes one, **Clear** wipes the whole table (all rows + override columns)
  back to one fresh row. Each scenario's resolved PathOut (placeholders expanded via
  `basin_viewer.pathout_exists`) is **created with `os.makedirs` before its run** if
  missing (CWatM does not create it), and a row that cannot create its folder is marked
  `error` and skipped.
- **Parameter sweep** (**Sweep…** button, `_open_sweep`/`_apply_sweep`): auto-generates
  scenario rows from `<key>: <values>` lines — `values` a **list** (`3.5, 4.0, 4.5`) or a
  **range** `min:max:step` (`3.5:4.5:0.5`; step optional → 5 steps), parsed by
  `_parse_values`. **Several keys → the full grid** (`itertools.product`); each row is
  named `<key><val>[_<key2><val2>…]` with its own PathOut, the swept keys get override
  columns, and >200 scenarios prompts a confirm. **Replace** (default) gives a clean
  table (rows + old override columns dropped).
- **The scenario table persists across sessions**: on close (`_save_config`) the rows
  (name/PathOut/overrides), the override-key columns, and the parallel count are stored
  as JSON in `QSettings` (`batch_runner/config`); the next open restores them
  (`_restore_config`, else one default row). **Clear** starts fresh (the empty state is
  persisted on the next close).
- On finish each scenario is logged to the **Run Ledger** (`kind="batch"`, title
  `<base Title> [<scenario>]`, PathOut resolved via `basin_viewer.pathout_exists`); the
  temp `.ini` is deleted on success (kept on failure for debugging). Non-modal; the main
  GUI stays usable. `closeEvent` stops in-flight processes; geometry key `batch_runner`.

### Run Ledger (Tools menu)
**Tools ▸ Run Ledger** (last item, separator above) (`main_window.open_run_ledger` →
`src/gui/widgets/run_ledger_window.py`, `RunLedgerWindow`) shows a table of **past runs**
recorded by `src/gui/utils/run_ledger.py` — one JSON row per run (`run_ledger.json`):
time, `kind` (run/hidden/batch/stopped), settings path, settings **Title**, resolved
**PathOut**, duration, success, last discharge. Rows are actionable: **Open results**
(the run's PathOut in the **Output Explorer**), **Load settings** (reload the run's
settings file into the main window), **Compare settings**, **Refresh**, **Clear
ledger**. Newest first; non-modal; geometry key `run_ledger`.
- **Compare settings**: the table is **ExtendedSelection**, so two runs can be marked
  (Ctrl/Shift+click). The **Compare settings** button is **grey/disabled** until
  **exactly two** rows are marked, then **blue** (`itemSelectionChanged` →
  `_update_compare_enabled`); pressing it diffs the two runs' settings in the **Compare
  settings** window via `compare_settings_window.open_compare_files(parent, a, b)` (a new
  `CompareSettingsWindow.load_files` reads both paths into the two panes and re-diffs).
  It prefers each run's **run-time snapshot** (`entry["snapshot"]`, what actually ran)
  over the live `settings` path, so the diff is accurate even if the file was edited
  afterwards; a missing file loads as empty.
- **Logging**: `run_controller` captures the run facts at start (`_run_ledger_ctx`:
  settings path, Title via `_current_settings_title`, resolved PathOut, start time) and
  `_log_run_to_ledger(success, last_dis, kind)` appends an entry on **finish** (`run`),
  **error** (`run`, success False), and **stop** (`stopped`) — logged **once** per run
  (best-effort; a logging failure never breaks a run). The **Batch runner** logs its
  scenarios too (`kind="batch"`).
- **Settings snapshot**: at run start `run_controller` reads the on-disk settings file
  (what CWatM actually runs) into `_run_ledger_ctx["content"]`; on log, `make_entry`
  writes it via `_write_snapshot` to `<history>/snapshots/<YYYYMMDD_HHMMSS>_<base>.ini`
  (name **uniquified** so parallel runs finishing in the same second don't collide) and
  stores its path as `entry["snapshot"]`. This is what **Compare settings** diffs. The
  **Batch runner** snapshots each scenario's generated content too.
- **Storage / retention** (`run_ledger.py`, `QSettings`): folder `history/folder`
  (default `%LOCALAPPDATA%/CWatM_GUI`, set via **Configure ▸ Run history folder…**),
  retention `history/retention_days` (default 60; 0 = keep forever, set via **Configure ▸
  Run history retention…**) — entries older than the window are pruned on write **and
  their snapshot files deleted**, plus a hard `_MAX_ENTRIES` cap. **Clear ledger** also
  removes the `snapshots/` folder. Writes are atomic (`.tmp` + `os.replace`).

### Restore settingsfile (Tools menu)
**Tools ▸ Restore settingsfile** (`main_window.restore_settingsfile`) opens a `dis*.nc`
output file and shows its global attributes in a table (`RestoreSettingsWindow`,
`src/gui/widgets/restore_settings_window.py`), **excluding** the three bulky ones
(`version_settingsfile`, `version_inputfiles`, `version_modules`). Two bottom-left
buttons act on those hidden attributes:
- **Restore settingsfile** (`_on_restore`): writes `version_settingsfile` (the full
  settings file CWatM stamped into the output) to a **new file** (Save-As dialog,
  suggested in PathOut / next to the nc), then **loads** it in the main window
  (`load_recent_file`). If the currently loaded settings file has **unsaved changes**
  (`main_window._is_dirty`) it first warns *"Current settingsfile is not saved. Save it
  or loose content."* with **Save current first / Continue (lose changes) / Cancel**.
- **Show Inputfiles** (`_on_show_inputfiles` → `InputFilesWindow`): parses
  `version_inputfiles` (entries separated by `;`, each `<filename> <DD/MM/YYYY HH:MM>`,
  via `parse_input_files`, exact duplicates dropped) into a 2-column **File / Date**
  table.

### CWatM AI (Gemini NotebookLM)
**CWatM AI** button (left of Help) opens a chat window where questions about CWatM are
answered by Google **NotebookLM** (Gemini) over a predefined CWatM notebook (source
PDF, e.g. `CWATM_shorter.pdf`). Uses the **`notebooklm-py`** library (fully async;
httpx RPC — **not** Playwright at runtime). **Source-run feature**: not in the
PyInstaller spec; a frozen build degrades gracefully (friendly message, never a crash).
See `ai.md` for the full plan/history.
- **Threading**: all `notebooklm` work runs off the GUI thread. `NotebookLMWorker`
  (`src/gui/utils/notebooklm_worker.py`, a `QThread`) owns a question `queue.Queue`,
  connects lazily on the first question, and emits `status/reply/error/busy` signals.
  The **only** importer of `notebooklm` is `src/gui/utils/notebooklm_client.py`
  (`NotebookLMClientWrapper` — one persistent asyncio loop drives `connect/ask/close`;
  `is_authenticated`, notebook auto-resolve by title containing "cwat"). Lazy-imported
  in `main_window.open_cwatm_ai()` (fast-startup rule — never import notebooklm/httpx
  at module level).
- **Window** (`src/gui/widgets/notebooklm_window.py`, `NotebookLMWindow` =
  `GeometryMemoryMixin` + non-modal `QDialog`, geometry key `cwatm_ai`, themed like the
  NetCDF window — every colour a `theme.c(token)`): header + a centred login-state line,
  a `QTextBrowser` transcript (You / Gemini / status / error colours), a multi-line
  input (Enter sends, Shift+Enter = newline) + **Send** (blue), and **Login… /
  Notebook… / Clear / Exit** (Notebook/Clear/Exit grey). **Gemini answers are
  rendered as markdown** (`markdown-it-py` "gfm-like": bold/lists/tables/code —
  `_render_markdown`), each answer followed by an `<hr>` **separator** before the next
  question; the *Explaining settings line: …* notice (Explain button / phrase) is shown
  **bold blue** (`_append_action`).
- **Answer-length selector** (compact Short / Medium / Long exclusive toggle buttons
  in the bottom row, right of **Notebook…**; selected = blue, persisted
  `notebooklm/response_length`, default Medium):
  sets NotebookLM verbosity via `chat.configure(notebook_id, response_length=…)`
  (`ChatResponseLength` SHORTER/DEFAULT/LONGER). The wrapper applies it on its asyncio
  loop from `connect`/`ask`; the worker pushes the current choice on the worker thread
  before each ask. (It is a NotebookLM **server-side** per-notebook setting.)
- **Transcript + question history persist** across close/open (QSettings
  `notebooklm/transcript_html`, `notebooklm/history`; saved in `closeEvent`/`done`,
  restored in `__init__` — a restored transcript shows a "— New session —" separator).
  **Up/Down** in the input recall older/newer questions (only at the first/last line, so
  multi-line editing still works; a live draft is kept when paging past the newest).
- **Login state is verified, not assumed**: a stored session **file** existing does
  not mean it still works, so on open (and after a login) a background `_AuthCheckWorker`
  (QThread) calls `notebooklm_client.check_connection()` — a real `notebooks.list()`
  probe — off the GUI thread. `_refresh_login_state()` then colours the Login button
  **blue "✓ Logged in"** only when *confirmed* (`_auth_verified is True`), **"Checking…"
  (blue)** while the probe runs, and **red "Login required"** when the session is
  **expired/invalid** (`check_connection` → `"auth"`, detected via `is_auth_error`:
  "Authentication expired or invalid", a Google-accounts redirect, "Run 'notebooklm
  login'"…). On an expired session (also if a **question** fails with an auth error —
  `_on_worker_error`) it drops the dead worker and **prompts to re-authenticate**
  (`_prompt_reauth` → the Google login window). A transient network/proxy error leaves
  the state unchanged (just a note). `playwright` (pinned) drives that Google-login
  re-auth path. **Login…** (`QProcess`, source-run) offers a **Google login
  window** (system Chrome via `--browser chrome`, no download; bundled-Chromium
  fallback offered on failure) and browser-cookie paths (Firefox works on Windows;
  Chrome/Edge cookies are app-bound-encrypted and usually cannot be read — precise
  hints are shown). Reads the session cookie bundle via **`rookiepy`**
  (`notebooklm-py[cookies]`).
- **Notebook selection**: `notebooklm/notebook_id` (a bare id or a NotebookLM URL;
  `Notebook…` sets/persists it); if unset the wrapper auto-picks a notebook whose title
  contains "cwat", else the only one, else raises listing the choices.
- **Settings bridge** (answer ⇄ settings editor): two grey buttons above the input,
  **→ Settings** and **Explain current line**, each also triggerable by typing a set
  phrase (e.g. "put this in the settings" / "explain this line" — matched in
  `_maybe_handle_command`, so genuine questions are not intercepted). **→ Settings**
  takes the **marked** transcript text; if it names no `[SECTION]` it first **asks
  NotebookLM which heading the key belongs under** (e.g. `[OPTIONS]`) — via a
  `_pending_ctx` question whose reply is intercepted in `_on_reply`, the `[...]` parsed
  out and prepended — then calls `main_window.ai_put_text_in_settings`, which
  **validates** it as `[SECTION]`/`key = value` (rejects prose), updates existing keys
  in place / inserts new ones under their section (created if needed) via
  `set_content_preserving` (one undoable step; Save turns dirty), and **jumps** the
  editor to that line (`_goto_editor_line` + `reveal_cursor`). The *Explaining settings
  line: …* / *Placed under […]: …* notices use `_append_label_line` (**bold-blue label
  + normal-weight body**).
  **Explain current line** reads `main_window.ai_current_settings_line()` (the editor's
  cursor line) and asks NotebookLM to explain it. (Phases 2–3 of `ai.md`.)

## Data Visualization internals

### Basin viewer infrastructure (`src/gui/widgets/basin_viewer.py`)
This module no longer holds a viewer window — the classic native-canvas / Mercator
`BasinWindow` + `BasinCanvas` were **removed** (there is only one basin viewer now:
the folium EPSG:4326 one in `basin_viewer2.py`, below). What remains here:
- **`BasinViewer`**: the data loader (ups.nc/mask NetCDF loading, `Title`/`MaskMap`
  lookup, placeholder resolution) used by `show_basin2`.
- **`BasinDataHelpers`**: a mixin of the display-agnostic helpers (`_build_ups_rgba`/
  `_build_mask_rgba` overlay images, `_field_gauges`/`_mask_start_point`/
  `_largest_ups_point`/`_ups_text` field readers, `_mask_bbox`, `_run_gauge_check`) —
  `BasinWindow2` inherits it. They only read `self.basin_data/lats/lons/mask_data`.
  The ups.nc overlay's valid cells are drawn at **full per-pixel alpha (255)** so the
  transparency slider's opaque extreme fully hides the OSM basemap.
- **Networking / WebGL**: the app-lifetime `osmtile://` scheme handler
  (`_get_tile_handler`) serves the map pages **and** basemap tiles/WMS with Python
  `requests` (bypasses a proxy that blocks Chromium, caches results); reused across
  every basin/NetCDF window. `cwatm_gui.py` sets `QTWEBENGINE_CHROMIUM_FLAGS=
  "--disable-gpu --no-sandbox --use-gl=angle --use-angle=swiftshader"` (swiftshader =
  **software WebGL**, needed by the Leaflet maps) and `AA_ShareOpenGLContexts`.
- **Gauge-in-mask / PathOut checks**: module-level `build_mask_context`,
  `gauges_inside`, `pathout_exists`, `find_largest_ups_gauge` (used by the main window).

### Basin Viewer (`src/gui/widgets/basin_viewer2.py`) — folium / EPSG:4326
**Tools ▸ Show Basin**: the basin viewer in a **single**
view, built on **folium** (`folium.Map(crs='EPSG4326')` → Leaflet) in
QtWebEngine. Rewritten from the earlier Plotly/MapLibre experiment (which warped
the raster onto a Mercator basemap and did not render well).
- **Projection = EPSG:4326** (`crs='EPSG4326'`), matching the CWatM results
  (ups.nc, mask, and the NetCDF Analyse maps are all plain lon/lat). So the
  overlays need **no rasterio reprojection**: `_build_ups_rgba`/`_build_mask_rgba`
  (inherited from the `BasinDataHelpers` mixin, with the marker/field/check helpers)
  are added as `folium.raster_layers.ImageOverlay`
  with their lon/lat corner **bounds** and `mercator_project=False` — drawn 1:1,
  so the raster stays **crisp** (no Mercator warp blur). `pixelated=True` +
  nearest-neighbour `_upscale_rgba` keep the cell edges sharp.
- **Basemap = WMS (not XYZ tiles)**: OSM XYZ tiles are Web-Mercator and **cannot**
  align on an EPSG:4326 map — using them left the basemap blank and fired a storm
  of failing tile requests (extremely slow). The basemap is instead a **WMS**
  layer (`L.tileLayer.wms`), which returns imagery in the map's own CRS so it
  aligns exactly with the lon/lat overlays. The `_B2_PROVIDERS` selector holds
  **EPSG:4326 WMS layer names** (OSM-WMS / TOPO-OSM-WMS / SRTM30-Colored-Hillshade
  / Dark) served by the terrestris OSM WMS through the `osmtile://wms/…` handler
  branch (query forwarded verbatim, Python-fetched, cached, proxy-proof). The
  Configure-menu default (a Mercator XYZ key) falls back to `OSM-WMS`.
- **Markers are CSS teardrop pins** (`L.divIcon`, `.cwatm-pin`, ~22 px, the
  `folium.Icon` look but self-contained — no font-awesome, which is stripped):
  red gauges labelled **1..N** (the station number, from `setRedAll`'s forEach
  index), blue **M** = mask-start, black (blank) = last clicked.
  Created/moved by JS helpers (`setRedAll`/`setBlue`/`setBlack`/`clearBlack`) so
  Create gauge / Create mask / Copy actions update them live. The map cursor is a
  plain **arrow** (Leaflet's grab/hand cursor is overridden via CSS).
- **Gauge editing (working list `self._gauges`)**: the red pins are a **working list**
  of `(lon, lat)`, **seeded** from the live Gauges box on open
  (`BasinWindow2._field_gauges` overrides the mixin to read `gauges_field` only, no
  settings-file fallback). **Create gauge** *appends* the clicked point as a new
  numbered pin (it no longer replaces the set); **clicking a pin** removes it
  (`B2DEL <idx> <nonce>` → `_on_web_title` → `_remove_gauge`, popping it from the list),
  and the remaining pins **renumber** automatically (index-based labels). **Copy Gauge**
  commits the *whole* list to the Gauges box (`lon lat …`, which auto-applies to the
  settings) and re-runs the gauge-in-mask check. `_refresh_markers` always draws
  `self._gauges`. (Since the window is modal, the box can't change underneath it, so
  seeding once is safe.)
- **Page assembly**: folium's map is rendered, then the sizing CSS and the helper
  `<script>` are **string-inserted** into the HTML (before `</head>` / `</html>`)
  — *not* via `folium.Element`, which re-renders the string as a Jinja template
  and mangles JS/CSS braces. The sizing CSS (`html,body{height:100%}` +
  `.folium-map` absolute-fill) is essential: a standalone folium page gives
  `<body>` no height, so the map would otherwise collapse to 0 px (blank). The
  helper script is inserted last so folium's global map/overlay vars already
  exist when it runs.
- Buttons/behaviour: Hide/Show Mask, Create new Mask (same
  `mainwarm -vgm` temp-ini call; `updateMask` swaps the mask ImageOverlay in
  place — creating it if the basin had none), Copy Mask, Create gauge / Copy Gauge
  (see gauge editing above), Zoom to Mask (`fitBounds`), **OSM transparency slider**,
  basemap selector (`setBasemap` swaps the `L.tileLayer.wms` in place), Exit. Clicks
  route via `document.title` (`B2 <lon>|<lat>`) → `_on_web_title`.
- **OSM transparency slider** (`_on_opacity_changed`) — same coupled model as NetCDF:
  as it goes 0 → 100% the **OSM basemap opacity** rises 0.0 → 1.0 (`setBaseOpacity` →
  `_tile.setOpacity`) and the **ups.nc/mask overlay opacity** falls 1.0 → 0.5
  (`setOverlayOpacity`). So **0% = OSM hidden + data fully opaque** (only ups.nc/mask,
  over white) and **100% = OSM fully visible + data 50% opaque on top**. The **initial**
  value comes from **Configure ▸ Transparency** (`display_format.get_transparency()`,
  default 100). `setBasemap` re-applies `_baseOp` on a basemap switch.
- **Load JSON** button: opens a `*.geojson`/`*.json` file (starting in the settings
  file's folder), parses it with `json.load`, and draws it via the `addGeoJson` JS
  helper (`L.geoJSON` — orange lines/polygons, circle markers for points, feature
  `properties` shown in a popup, `fitBounds` to the layer). Kept in its own
  `geoGroup` layer under the pin markers; parse errors are reported, never crash.
- **JS readiness**: helpers exist once Leaflet has loaded, so `_js()` **queues**
  calls until `loadFinished`, then flushes and re-applies markers from the live
  boxes (`_refresh_markers`).
- **Networking / offline**: the page is served **same-origin** from the shared
  `osmtile://` handler (`osmtile://map2`, `set_html2`); WMS basemap requests go
  through the handler's `wms` branch — Python-fetched, cached, proxy-proof. Only
  the assets the map needs are kept: folium's Leaflet + awesome-markers CSS/JS are
  **inlined** by `_inline_remote_assets` (each `<script src>` / `<link>` fetched
  with Python `requests`; CSS `url()` marker PNGs/fonts become `data:` URIs), and
  the unused CDN libs (jquery, bootstrap, font-awesome) are **stripped** by
  `_strip_unused_assets` — so the page is self-contained, ~0.3 MB (was ~4.6 MB),
  and renders behind the proxy that blocks Chromium. Any inlining failure leaves
  the original markup (never worse than plain folium).

### Timeseries Analysis (`src/gui/widgets/analysis_timeseries.py`)
**Analyse ▸ Timeseries** opens a **`.csv`-only** file dialog (starting in the resolved
**PathOut** directory when a settings file is loaded) and shows the result as a
**Plotly** line chart (`plotly.graph_objects`, `mode="lines"`) rendered in a
QtWebEngine window (plotly.js inlined — no CDN).
- CWatM result CSV layout: series names in **row 4 from column 2**; **column 1 = date**
  (daily/monthly/yearly) and columns 2+ = values from row 5 on.
- Multiple result columns are shown **one at a time** with **Forward / Backward**
  buttons (hidden for a single column).
- A blue **Compare** button (bottom-left) opens another result `.csv` and overlays its
  series on the current plot; both axes are rescaled to the combined min/max of all
  series and a **legend** is shown. Overlays follow Forward/Backward (matching column
  index, else the compare file's first column). Multiple Compare files can be stacked.
- A **Load observed** button (right of Compare) overlays an **observed** series (a CWatM
  result `.csv` — first result column — or a simple `date,value` two-column `.csv`;
  `_parse_observed`) as a **dashed high-contrast** line and shows goodness-of-fit
  metrics — **KGE / NSE / PBIAS / RMSE** (+ n) — in a label under the description
  (`src/gui/utils/metrics.py`). Metrics are computed on the **date overlap** of the
  observed series and the **currently shown** simulated column (`_aligned_obs_sim`
  aligns via a pandas day-normalised key, so a `dd/mm/yyyy` sim and an ISO observed
  match), and recompute on Forward/Backward. The button toggles to **Clear observed**.
- A **two-handle range slider** below the plot (`RangeSlider`, reused from
  `analysis_watercycle.py`; shown only with >2 time steps) **shrinks the displayed
  period** from either end — the plot's x-axis (and y-axis) rescale to the selected
  `[lo, hi]` index window (`_window_bounds`; the "Displayed period: … – …" label above
  it updates live). The **same window defines the period** over which the observed
  goodness-of-fit metrics are computed (`_aligned_obs_sim` iterates only `lo..hi`), so
  KGE/NSE/PBIAS/RMSE follow the slider. Metrics/label update immediately on drag; the
  heavier figure rebuild is debounced 200 ms (`_range_timer`). The window is display/
  metrics only — **Save as csv still writes every day** (full series), unchanged.
- The variable name is the part of the file name **before the first `_`** (e.g.
  `discharge_daily.csv` → `discharge`); its **unit**, **long_name** and **description**
  are looked up in `cwatm/metaNetcdf.xml` (regex, as the file has non-XML `#` lines):
  long_name = figure title, unit = y-axis label, description (trailing `[Array]`/`[Flag]`
  stripped) = caption below the figure.
- Can also be built **in-memory** (not from a CSV) via `TimeseriesWindow.from_point(...)`
  — used by **Analyse ▸ NetCDF ▸ Display timeserie** to plot a grid cell's series,
  rendered identically but with a **legend** labelled by the point location.
- **Save as csv** button (left of Save HTML, `_save_csv`): writes the current series +
  any overlaid point series to a CWatM result `.csv` **byte-format-compatible with
  `discharge_daily.csv`** — `Timeseries,settingsfile: …` header, `xloc`/`yloc` rows
  (`%#.4f`), `Date,G1..Gn` header, `DD/MM/YYYY` dates, values as `,%13.10g`, CRLF line
  endings. Station coords come from `xlocs/ylocs` (main) or are parsed from a point's
  `lon …, lat …` label (overlays); re-opening the file reproduces the data.

### NetCDF Analysis (`src/gui/widgets/analysis_netcdf.py`)
**Analyse ▸ NetCDF** draws the variable **on a map**: a **folium** (Leaflet,
**EPSG:4326**) page with the grid as a `folium.raster_layers.ImageOverlay` over an
**OSM WMS** basemap (same WMS providers as **Show Basin**), served same-origin
through the shared `osmtile://` handler so it renders behind the proxy that blocks
Chromium. `NetcdfWindow` **subclasses `NetcdfDataBase`** (`analysis_netcdf_base.py`)
and reuses its data loading (`_load`), meta lookup (`_lookup_meta`) and point-series
extraction (`_point_series`); the rendering/interaction is implemented here. (This is
the former "NetCDF2"; the plain Plotly heatmap that used to be "NetCDF" was removed,
so this folium viewer is now simply **NetCDF**.)
- **Projection = EPSG:4326** (`crs='EPSG4326'`), matching the CWatM `.nc` output, so
  the raster needs **no rasterio reprojection** — each timestep is colourised in
  numpy to an RGBA image (`_colorize`: fixed `zmin/zmax`, NaN → transparent alpha,
  flipped north-up + west→east to match the lon/lat corner **bounds**) and handed to
  Leaflet as a **base64 PNG `data:` URI** (`_rgba_to_datauri`, via `QImage`), drawn
  1:1 with `pixelated=True` so cells stay crisp. LUTs (`_lut`, from
  `plotly.colors.sample_colorscale`) and per-`(scale, timestep)` URIs are cached.
- **Basemap = WMS**, not XYZ tiles (XYZ are Web-Mercator and cannot align on an
  EPSG:4326 map — same reason as Show Basin). The `L.tileLayer.wms` is kept **below**
  the overlay (`bringToBack`) so the overlay-transparency slider fades the data to
  reveal the basemap.
- **Controls (no description caption; laid out in three rows** — the NetCDF
  description label is intentionally omitted here): row 1 = timestep slider + **▶ Play**
  (driven by a Qt `QTimer`, since a folium overlay has no built-in animation) + date +
  **Speed**; row 2 = **Colour scale** selector (restyles by rebuilding the overlay URI +
  the HTML colour-bar) + **OSM transparency** slider + **Basemap** selector
  (`setBasemap` swaps the WMS in place) + **Log scale**; row 3 =
  **Fast Display Timeserie** + **Total Timeseries** (+ a **progress bar** to their right
  while the full point series loads) … **Save HTML**. Play/slider/colourscale changes rebuild the
  overlay's `data:` URI in Python and push it with `_ov.setUrl(...)`.
- **OSM transparency slider** (`_on_opacity_changed`): one slider fades **both** layers
  as it goes 0 → 100% — the **OSM basemap opacity** 0.0 → 1.0 (`setBaseOpacity` →
  `_tile.setOpacity`) **and** the **NetCDF overlay opacity** 1.0 → 0.5 (`setNcOpacity`
  → `_ov.setOpacity`). So **0% = OSM hidden + NetCDF fully opaque** (only the data, over
  white) and **100% = OSM fully visible + NetCDF 50% opaque on top**. The **initial**
  value comes from **Configure ▸ Transparency** (`display_format.get_transparency()`,
  default 100). `setBasemap` re-applies `_baseOp` when the layer is swapped. (There is no separate
  Hide OSM button — sliding to 0% hides the basemap.)
- **Log scale** button (checkable, `_toggle_log`): maps the values to colour on a
  **logarithmic** scale (`_colorize`: `log1p(clip(z)-zmin) / log1p(zmax-zmin)`, which
  tolerates a zero/negative minimum) instead of linear; the `_uri_cache` key includes
  the log flag so linear/log frames don't collide, and toggling re-pushes the current
  frame. The info-label value read-out stays the raw cell value.
- **Coordinate/value read-out**: an `info_label` under the map shows "Click on the map
  to see coordinates and values"; on each click it becomes
  `Lon: … | Lat: … | Value: … <unit> | <timestep>` (the clicked cell's value at the
  current timestep), like Show Basin's info label.
- **Click-to-mark**: clicking routes the lon/lat via `document.title` (`NC2 <lon>|<lat>`,
  read through `titleChanged` like the basin viewers) → `_on_web_title`, which snaps to
  the nearest cell, stores `_clicked`, drops a red **pending** pin, and updates the
  read-out. Pressing
  Either **Fast Display Timeserie** or **Total Timeseries** adds that cell to the
  persisted point set and (re)builds the Timeseries window from **all** points
  (`_open_or_refresh_timeseries` — recreated from scratch each time since
  `TimeseriesWindow` has no remove-series API: first point → `from_point`, rest →
  `add_point_series`; the mode is remembered in `self._ts_full`). **Two modes**
  (`_point_series(..., full=)`), because reading one cell across time is one chunk read
  **per timestep** (CWatM `.nc` is chunked `[1, lat, lon]`), so the cost scales with the
  number of timesteps:
  - **Total Timeseries** (`full=True`) — **every timestep** (dates from
    `_point_source["full_time_labels"]`), so the plotted / **Save as csv**'d series has
    every day. This can be **slow** (tens of seconds on a long / networked file), so it
    is read **off the GUI thread** by `_PointSeriesWorker` (a `QThread` calling
    `_series_for(p, full=True)` per point) with the **progress bar** (`ts_progress`:
    busy/indeterminate for a single point, per-point `n/m` for several); both buttons are
    disabled while loading, the newest request wins (`_ts_next` chain), and `closeEvent`
    waits for an in-flight read.
  - **Fast Display Timeserie** (`full=False`) — only the **strided map-animation frames**
    (`time_indices` / `time_labels`, `_MAX_FRAMES`), so it is quick (far fewer chunk
    reads) but the series has **gaps**. Read **synchronously** (no progress bar), like the
    original behaviour.

  Both build from the precomputed series in `_build_ts_window(..., full=)` (dates chosen
  to match the mode) on the main thread. Confirmed points are drawn by
  **`_update_map_markers`** as **numbered pin icons** (`L.divIcon`, `.nc-pin` CSS
  teardrop) whose fill is the point's **Timeseries line colour** (index-derived:
  `TimeseriesWindow._MAIN_COLOR` / `_COMPARE_COLORS`), so map marker N == legend line N.
- **Points persist & are removable**: `_displayed_points` holds the confirmed cell
  centres as `(lon, lat)`; closing the Timeseries window (`_on_ts_closed`) **keeps**
  the pins (reopening re-plots the same points). **Clicking a numbered pin removes it**
  everywhere — the pin's click fires `document.title='NC2DEL <n> <nonce>'` (nonce so a
  repeat refires `titleChanged`; `L.DomEvent.stopPropagation` prevents a stray pending
  marker) → `_on_web_title` → `_remove_point`, which drops it from the list, renumbers/
  recolours the remaining pins, and refreshes the Timeseries **only if it is open**
  (`open_if_closed=False`, so removing a pin never pops the plot open).
- **Gauge reference pins**: the main-window **Gauges** stations (read from the parent's
  `gauges_field` via `_parse_coord_pairs`, `_gauge_stations`) are drawn as **smaller
  red numbered pins** (`.nc-gauge` / `gpin`, in their own `gaugeGroup`, `setGauges`) —
  purely for reference, distinct from the click-to-add discharge points; applied on
  load (`_refresh_gauges` in `_on_loaded`).
- **JS readiness**: helper calls are **queued** until `loadFinished` then flushed
  (`_js` / `_on_loaded`), like Show Basin. **Save HTML** writes the self-contained
  page (its basemap WMS only resolves inside the app's `osmtile://` scheme, so an
  external browser shows the data overlay only). Window geometry remembered via
  QSettings key `netcdf2`.
- **Compare A−B** (`_toggle_compare` → `_enter_compare`/`_exit_compare`): loads a second
  `.nc` and shows **this − other** per timestep on a **diverging** scale. It calls
  `_load(B)` (restoring A's `_point_source` afterwards), checks the grids match
  (`frames[0].shape`), builds `diff[i] = A[i] − B[i]` over the `min(len)` overlapping
  frames, sets a **symmetric** `zmin/zmax = ±max|diff|`, the `RdBu (diff)` colour scale
  (blue = negative, red = positive) and **linear** scale. `_apply_data_swap` re-syncs the
  slider/colour-scale/log controls, clears `_uri_cache`, pushes the frame + colour-bar,
  and disables the point-timeserie buttons (a difference has no single source series). The
  button toggles to **Clear compare**, which restores A from the saved `_orig` state.
  (Frames are aligned by index — the strided animation frames — so compare same-period
  runs.)

### Watercycle Analysis (`src/gui/widgets/analysis_watercycle.py`)
**Analyse ▸ Watercycle** opens a **`.csv`-only** file dialog (starting in the resolved
**PathOut** directory) for a CWatM **`WaterCycle_areasum_monthtot.csv`** result and shows
the overall water balance as a Plotly **`go.Sunburst`** rendered in a QtWebEngine window
(plotly.js inlined — no CDN). The balance computation is **ported from the stand-alone
`Watercycles1.py`** template (see *Watercycle template scripts* in CLAUDE.md).
- **Window/plot title** = the settings-file **`Title`** (from the settings file named in
  the csv header row 1 `settingsfile:`, else the title loaded in the main window —
  `_read_settings_title`).
- **Subtitle** "Station: lon: x, lat: y" — **x** from csv **row 2, col 2** (`xloc`), **y**
  from **row 3, col 2** (`yloc`), each to 3 decimals (`_read_station` / `_fmt3`). With
  **multiple stations** it reads "Station k/N: lon: x, lat: y" (`_station_label`).
- **Multiple stations** (`_load_data`): a WaterCycle csv can hold several stations laid
  out side by side — after the Date column each station occupies a **fixed-width block**
  of variable columns (the ~79 `<var>_<unit>` names are **repeated** per station and its
  lon/lat is repeated across its block in rows 2/3, matching CWatM's
  `writeFileHeaderWaterCycle`). The block width is auto-detected from the **first repeat**
  of the leading column name (single-station csvs have no repeat → whole width, N=1), the
  numeric data is read **headerless** (`skiprows=4, header=None`, so pandas doesn't
  de-duplicate the repeated names) into `self._full`, and `_select_station(idx)` slices
  that station's block into `self._df` with the canonical column names and refreshes
  `self.lon/lat` + `self._cellAreaSum`. A name can legitimately repeat **within** one
  block (CWatM's watercycle list holds `act_livConsumption` twice), so `_select_station`
  mangles repeats to `name.1` pandas-style — `df[name]` stays a Series (first
  occurrence), exactly like the old header-based read. Blue **◀ Backward / Forward ▶** buttons (same
  styling as the Timeseries window, centred in the bottom row left of Save HTML) switch
  stations and rebuild the figure (`_prev_station`/`_next_station`/`_goto_station` →
  `_refresh_figure`); they are **hidden when N=1** and enable/disable at the ends
  (`_update_station_nav`).
- **Month range slider** (`RangeSlider`, two draggable handles over the csv's months):
  the sunburst is recomputed for the selected **[start, end]** window (defaults to the
  full span); dragging shows the range live and **debounces** the heavy rebuild (200 ms
  `_rebuild_timer`). The 3rd subtitle line is the covered range (`_date_range_text`).
- **Sunburst computation** (`_build_figure`, ported from `Watercycles1.py`):
  - Data read once in `_load_data` (headerless per-station slice, see above); `cellAreaSum` =
    `cellArea_sum_m3[0] / days_in_month[0]` (monthly cell-area is summed over the
    month's days). Dates parsed from column 0 (`%d/%m/%Y`).
  - A `Vars` table classifies each variable as **flux** or **store** and assigns it to
    an **Inputs / Outputs / Storage / Evapotranspiration / Transpiration** wedge. Fluxes
    are **summed** over the window (`flux_start:end_idx`); stores use the **change**
    `store[end_idx] − store[baseline_idx]` (baseline = the month before the window start,
    so the full-span default reproduces the template). Unit suffix per variable:
    `M`→`_areasum_m3`, `M3`→`_sum_m3`, `M3/S`→`_m3s-1` (discharge × 86400 s/day). Columns
    whose variable is **absent are skipped** (e.g. the optional `Glacier` pair,
    added only when both `GlacierMelt`/`GlacierRain` columns exist).
  - The wedge assembly computes `total_input/output/store`; **negative** total storage is
    folded into discharge as "Storage (out)", otherwise the residual is a **"Balance"**
    wedge ("Storage (into)"). The root wedge shows the station **lon/lat** (monospace);
    hover shows per-wedge **% of parent**, **volume (km³)**, and **mm/year** (`Σm³ /
    cellAreaSum × 1000 / noyears`; the discharge wedge shows **m³/s** instead), plus the
    basin name / area / date-range on the root.
- **Save HTML** button (same as Timeseries): saves the self-contained Plotly plot to a
  user-chosen `.html`, suggesting the resolved PathOut directory.
- Themed like the other Analyse windows (Plotly template + layout overrides from
  `theme`); the plot **fills the page** (`themed_plot_page` + a `100vh` style so there is
  no internal scrollbar); window geometry remembered via QSettings key `watercycle4`.

### Flow Diagram Analysis (`src/gui/widgets/analysis_flowdiagram.py`)
**Analyse ▸ Flow Diagram** opens the **same** `WaterCycle_areasum_monthtot.csv`
result file as Watercycle and shows the overall water balance as a Plotly
**`go.Sankey`** flow diagram (precipitation → rain/snow → soil/groundwater/runoff
→ discharge, plus withdrawal/consumption), rendered in a QtWebEngine window
(plotly.js inlined — no CDN). The Sankey nodes/links/colour helpers and the
`build_sankey` builder are **ported from the stand-alone
`sankey_waterbalance_month.py`** template.
- **Header + subtitle + month range slider + multi-station support are identical to
  the Watercycle window** — `RangeSlider` and `WatercycleWindow`'s csv-parsing/station
  helpers (`_read_station`, `_read_settings_title`, `_load_data`, `_fmt_month`,
  `_date_range_text`, `_select_station`, `_station_label`, `_goto_station`,
  `_prev_station`, `_next_station`, `_update_station_nav`) are imported/reused from
  `analysis_watercycle.py`; only `_refresh_figure` is overridden to rebuild the **Sankey**.
  Window title = settings-file **`Title`**, subtitle = station **lon/lat** (csv row 2/3
  col 2, "Station k/N:" when several) + the selected month range. Multi-station csvs get
  the same blue **◀ Backward / Forward ▶** buttons.
- Link values are **long-term averages in mm/yr** over the basin area, computed
  over the **slider-selected month window** (a shorter window rescales `nyears`);
  missing csv columns read as 0 so an incomplete watercycle csv still renders.
  Per-link **source→target SVG gradients** (`_GRADIENT_JS`) are injected into the
  exported HTML.
- **Save HTML** button (same as Watercycle): saves the self-contained Plotly plot,
  suggesting the resolved PathOut directory. Window geometry remembered via
  QSettings key `flowdiagram`.
