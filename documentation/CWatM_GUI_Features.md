# CWatM GUI — Feature & Usage Guide

> This is the user-facing feature/usage tour for the CWatM GUI. The concise,
> developer-facing reference (menu table, architecture, build) lives in the
> project root `CLAUDE.md`.

## Features

### Working with several settings files (tabs)
- **Switching tabs on or off**: the tab bar appears when **Preferences ▸ Editor &
  Dates ▸ Use Tabs** is ticked (it is by default) **and** the skill level is
  **Expert** — Beginner and Advanced keep the familiar single-file window. Hiding
  the bar never throws anything away: whatever was open stays open, and the file you
  were working in stays in the editor.
- **One tab per settings file**, in the bar between the button row and the editor.
  A loaded file goes into the **active** tab — at start that is the first one — and
  so does a settings file you **drop** onto the window.
- **Add a tab**: click the small **+** right of the last tab — the new tab becomes the
  active one; load or drop the next settings file there.
- **The same settings file can only be open once.** Loading a file that another tab
  already has simply brings you to that tab (nothing is loaded twice), and *Save As*
  onto a file another tab has open is refused — otherwise the two tabs would edit
  their own copy of one file and the second save would quietly throw the first one's
  work away. Reloading the file of the tab you are in is of course unaffected.
- **The active tab is what everything works on**: RUN CWATM, the dates, PathOut,
  MaskMap and Gauges boxes, Check settingsfile, Show Basin, Check Data, Compare,
  the Excel editor and the Analyse windows all use the file of the tab you are
  looking at. Switching tabs swaps the whole left panel with it.
- Each tab keeps **its own** editing state: undo history, bookmarks, folded sections,
  changed-line highlights and the red Check-settingsfile marks. A tab with unsaved
  edits shows a **`*`** in front of its name, and **Save** only ever writes the active
  tab; on exit you are asked once per unsaved file.
- **Settings ▸ Compare Tab (F8)** — shown in the **Expert** skill level only, like
  the tabs themselves — colours, right in the editor, every line that
  differs from the neighbouring tab — light green, in **both** tabs, so switching
  between them shows the differences from either side. Press **F8** again (or pick the
  menu item again) and the colouring disappears. Nothing is changed in either file.
- **Settings ▸ Compare settings** uses the tabs: the **active** tab goes into the left
  pane and the tab **next to it** into the right one — the tab immediately left of the
  active one, or the one immediately right when the active tab is the first. So with
  two settings files open, comparing them is a single menu click; you can still load
  any other file into the right pane with its **Load** button.
- **Closing a tab**: move the mouse over it and an **✕** appears at its right edge —
  clicking it closes that tab (asking first if it has unsaved changes), exactly like
  *Delete Tab* below.
- **Right-click a tab** for:
  - **Delete Tab** — closes it (asking first if it has unsaved changes). Deleting the
    last remaining tab just empties it.
  - **Copy Tab** — writes what the tab currently shows (including unsaved edits) to a
    new settings file **in the same folder** and opens it in a new tab next to it:
    `settings.ini` → `settings_2.ini`, `settings_2.ini` → `settings_3.ini`, and so on;
    a name that already exists is skipped.
  - **Run CWatM** — runs **this tab's** settings file (as saved on disk) in its own
    **Windowed Run CWatM** window, independently of the main run and of the other tabs.
  - **Link scrolling** (a tick) — scrolls this tab and the **previous** one together
    and keeps the **same sections folded** in both: scroll either of them and the
    other moves to the same place, fold a section in one and it folds in the other,
    so switching between the two lands you on the same lines — handy for reading two
    settings files against each other. Greyed out on the first tab (there is no previous one), and ticking
    several tabs in a row links them all into one group. The setting lasts for the
    session.
- Tabs can be dragged into another order, and with **Load previous settings at start**
  ticked (Preferences ▸ Startup & Model) **all** of them are re-opened next time.

### File Management
- **Load Configuration Files**: Load INI files with a preselected `.ini` filter.
- **Load previous settings at start** (Preferences ▸ Startup & Model): when ticked, all
  the tabs you had open are re-opened automatically the next time the GUI starts (the
  one you were working in on top).
- **Recent files**: up to 6 recently opened settings files are listed directly in the
  **File** menu (between Save As and Exit).
- **Save Files**: Save to the same file or Save As a new file — the editor holds the
  file as plain text at all times, so exactly what you see is saved (folded sections
  are only hidden from view and are written in full).
- **Auto-apply (no save)**: changing Start/Spin/End Date, PathOut, or MaskMap updates
  the settings content in memory automatically (debounced ~500 ms); writing to disk
  only happens on Save / Save As.
- **Section Management** (Settings menu): **Fold All** (Alt+0) collapses all sections;
  **Unfold All** (Alt+Shift+0) expands them.
- **Navigation & search** (Settings menu): **Top** (Alt+T), **Down** (Alt+D),
  **Find** (Ctrl+F), **Find next / previous** (F3 / Shift+F3), **Replace** (Ctrl+H),
  **Goto last change** (F5), **Undo** (Ctrl+Z) / **Redo** (Ctrl+Y). Undo/redo cover both
  manual editor edits and left-window field changes (Date/PathOut/MaskMap/Gauges).
- **Bookmarks** (Settings menu): **Toggle Bookmark** (Ctrl+F2) — or click a line's
  number in the gutter — marks the current line with an orange dot; **Next /
  Previous Bookmark** (F2 / Shift+F2) jump between them (wrapping around);
  **Clear all Bookmarks** (Ctrl+Shift+F2) removes them all.
- **Unsaved-change highlight**: lines that differ from the last loaded/saved file are
  shown with a light-blue background until the file is saved.
- **Duplicate-keyword highlight**: lines whose keyword is defined more than once are
  shown with a light-red background (the later definition silently overrides the
  earlier one; `OUT_*` output keys are per-section and only flagged if repeated
  within the same section).

### Configuration Parsing
- **Automatic Parsing** on load, with syntax highlighting and section folding.
- **Visual Formatting**:
  - Comments (`#`) in dark gray
  - `True` values in blue
  - `False` values in red
  - Section headers in bold
- **Foldable Sections**: click a section's ▾/▸ marker in the line-number gutter (or
  double-click its `[SECTION]` header) to fold/unfold it; all sections are unfolded
  when a file is loaded. Folding only hides lines — they stay in the saved file, and
  Find automatically unfolds a match inside a folded section.
- **Line-number gutter**: shows file line numbers (numbers jump across a folded
  section, so you can see how many lines are hidden).
- **Whitespace Preservation**: original file formatting and spacing are maintained.

### Date Management
- **Three Date Fields**: Start Date (`StepStart`), Spin Date (`SpinUp`), End Date
  (`StepEnd`).
- **Automatic Validation**: enforces chronological order (start ≤ spin ≤ end).
- **Flexible Date Formats**: including single-digit days/months.
- **Integer SpinUp/StepEnd**: if `SpinUp` or `StepEnd` is an integer N (a timestep
  count), the field is computed as `StepStart + (N-1)` days, matching CWatM's
  `datetoInt` convention (StepStart = timestep 1). See `date_manager.py`.
- **Auto-population**: dates are extracted from the configuration file on parse.

### Smart Run Functionality
- **Change Detection**: only updates/saves when values actually changed.
- **What-you-see saving**: the saved file is exactly the editor content (folded
  sections included).
- **Manual Change Preservation**: user edits survive fold/unfold.
- **Automatic Re-parsing**: reformats after updates without clobbering status messages.
- **Status Messages**: Save shows "File saved"; Save As shows "File saved: path".
- **Navigation**: jumps to `StepStart` after saving changes.
- **Scroll Position Memory**: keeps scroll/cursor position across saves.

### Options Management
- **Options Window** (Tools ▸ Change Options): manage boolean settings from the
  `[Options]` section as checkboxes. The window is **not modal**, so the settings
  editor stays readable beside it, and it remembers its size and position.
- **Grouped by topic** — Meteo & evaporation, Water demand, Crops, Groundwater &
  MODFLOW, Water bodies & routing, Output & reporting, … — with a **filter box** to
  find a switch by name and **Changed only** to see just what you altered.
- **What does it do?** Hover the small **ⓘ** next to an option.
- **A dot** marks every option changed since the window opened; **Revert all** puts
  them back.
- **Add option…** offers the switches CWatM understands that your file does not define
  yet and writes the chosen one into `[OPTIONS]`.
- Ticking a box is **one undo step** in the editor (Ctrl+Z), and any comment after the
  value — `includeGlaciers = False   # no OGGM data yet` — is kept. (Options written
  with such a comment now also *appear* in the window; they used to be skipped.)
- **Automatic Detection**: finds and parses all boolean options.
- **Real-time Updates**: checkbox changes update the content immediately and mark the
  document dirty (Save / Save As turn light blue). No Apply/Cancel — changes take effect
  instantly.
- **Smart Parsing**: recognizes True/False (case insensitive).
- **Format Preservation**: keeps original formatting/indentation when updating values.
- **Empty Section Handling**: shows an informative message when no boolean options
  exist.
- **Auto Section Expansion**: expands `[OPTIONS]`, `[FILE_PATHS]`, `[MASK_OUTLET]`,
  `[TIME-RELATED_CONSTANTS]` when the window opens.

### CWatM Model Execution
- **Integrated Model Runs**: run CWatM directly from the GUI (no external command line).
- **Real-time Output Display**: all print statements and messages appear immediately in
  the CWatM output area.
- **Smart Scrolling**: auto-scrolls to the latest output only if you were already at the
  bottom.
- **Error Highlighting**: errors and exceptions are shown in dark red; internal
  `Worker:` debug lines are filtered out.
- **Separate-process execution**: CWatM runs in its **own OS process**, so the GUI stays
  responsive, **Stop** is an immediate kill (even if the model hangs in C code), and a
  model crash cannot take the GUI down.
- **Stop/Start Control**: interrupt a run mid-execution.
- **Progress Tracking**: the progress clock advances based on actual model dates.
- **Windowed Run CWatM** (RUN CWATM ▸ Windowed Run CWatM): open one or more **separate**
  windows that each run CWatM in their own process, independent of the main window — so
  several runs can go in parallel while you keep working. Each has a bold-green settings
  label, a **Load** button, a **Run/Stop** button and its own output box; it opens
  pre-loaded with the main window's current settings file — or with **one tab's** file,
  when you start it from a tab's right-click ▸ **Run CWatM**. (This is the window that
  was called *Hidden Run CWatM* before.) It shows a **progress bar
  with elapsed and remaining time**, flashes the taskbar when it is done, and appears in
  the **Journal of Runs** like any other run. The output folder is created before the run
  starts (a missing PathOut is the usual reason a run dies minutes in), new windows
  cascade instead of stacking, and closing a window — or the GUI — while a run is going
  asks first. The header shows the run's **Title** and **output folder** (with a button
  to open it); you can set the file by **dropping an `.ini` onto the window** or with
  **Use current** (the file the main window has loaded right now); and the output box
  has a right-click menu — *Copy all output*, *Save output as…*, *Find…* (**Ctrl+F**,
  **F3** for the next hit), *Clear output*.
- **Batch Run…** (RUN CWATM ▸ Batch Run…): run many scenarios from the loaded settings
  file. A table where each row is a scenario — a name, its own **PathOut**, and a few
  **key = value overrides** (add a column with **Add key column**, which takes the key
  from the settings-editor cursor line). Each row runs as a temporary `.ini` in its own
  process, **up to N in parallel** (a spin box), with a live **Progress / Status** per
  row. The scenario table is **remembered** between sessions; **Clear** starts fresh; the
  output folders are created automatically. Every finished scenario is logged to the Run
  Ledger. **Sweep…** auto-fills the table for a **parameter sweep** — enter
  `SnowMeltCoef: 3.5, 4.0, 4.5` (a list) or `3.5:4.5:0.5` (a range), and several keys make
  the full grid of combinations.
- **Live discharge sparkline**: next to the progress clock, a small live plot of the
  discharge at the first gauge for the last ~3 months (older values fade out). Now and
  then a little animal (Preferences ▸ Display ▸ **Select animal**: Fish / Otter / Beaver / Sailboat)
  briefly swims along the trace.

### Journal of Runs (RUN CWATM ▸ Journal of Runs — 2nd item)
A table of your past runs — time, Title, PathOut, duration, success and last discharge —
kept automatically (main runs, Windowed Runs and Batch scenarios). Select a run and **Open
results** (its PathOut in the Output Explorer) or **Load settings** (reopen its settings
file). **Mark two runs** (Ctrl/Shift+click) to enable **Compare settings**, which diffs
the exact settings each run used (a snapshot is saved per run). Where the journal is
stored and how long runs are kept are set in **Preferences ▸ Run History**.

More on the same table:

- **Find a run**: type in the **filter box** (matches Title, PathOut, settings file,
  kind, date) and click any column header to **sort** by it.
- **Show log** opens that run's output log — the journal tells you a run failed, the log
  tells you why. (Main runs write one when *Write output box* is on; batch scenarios
  always do.)
- **Re-run** starts the same settings again in a Windowed Run window — even if the original
  file is gone, using the snapshot taken when it ran.
- **Compare results** (two or more marked runs) overlays the same result file from each
  of them in one Timeseries plot, labelled per run.
- **Delete** removes just the marked runs; *Clear journal* still removes everything.
- **Group batches** shows a whole Batch Run as a single row (`… — batch of 14`, with
  `12/14` succeeded); untick it to list every scenario.
- **Runs in progress** — the main run, Windowed Runs and batch scenarios — appear at the
  top marked *running…* with a live elapsed time, and the table refreshes itself.
- **Dead rows are visible**: an output folder or settings file that has been deleted
  since is shown greyed out, instead of only failing when you click it.
- **Note column**: double-click it and write anything — *"calibration attempt 3"*. It is
  kept with the run, and is what makes a months-old journal navigable when every run is
  called the same thing.
- **Export CSV** writes what you currently see (so filter first, then export).
- **Right-click a run** for the rest: open its output folder in the file manager, copy
  its PathOut or settings path, load, re-run, show the log, or delete it.

### Data Validation and Checking
- **Check Data Window** (Tools ▸ Check Data): validate a configuration without a full
  run — CWatM runs in check mode (`-c`).
- **Runs in the background**: the check opens every input file, which takes a while on a
  network drive — the window and the rest of the GUI stay usable, with an elapsed-time
  counter, instead of freezing until it is done.
- **You can see what it does**: CWatM's output — and the full traceback when it fails —
  appears in the **log pane** below the table.
- **Unsaved changes are caught**: CWatM reads the settings from disk, so if your editor
  has unsaved edits you are asked to save first (otherwise you would be checking a
  different file than the one you see).
- **NetCDF Comparison**: optionally compare against an existing discharge NetCDF file
  (its filename is passed to CWatM automatically).
- **Reading the results**: rows with a problem are tinted across the whole row and
  counted above the table (*"312 rows · 7 not valid · 3 date mismatches"*). Columns are
  **sortable**, the **filter box** narrows the list, **Select trouble** keeps only the
  bad rows, and a **double-click on a row jumps to that key** in the settings editor.
- **CSV Output**: results are written to `<PathOut>/check_cwatm1.csv` (changeable);
  **Copy Table** and **Export CSV** take exactly the rows shown.
- **Only with a MaskMap map**: with a coordinate MaskMap the **Run Check** button is
  disabled and its tooltip says why.
- **Settings Restoration**: **Restore settings from discharge map** (enabled once a
  discharge NetCDF is selected) opens that file in **Restore settingsfile**, where you
  can preview, compare and restore the settings it carries.

![Check Data](figures/screenshot_checkdata.png)

### Add output variables (Tools menu)
Pick what CWatM should write, without looking anything up:
- Opening it **scrolls the settings file to the bottom** (like *Settings ▸ Down*), where
  the `[OUTPUT]` section is — so the `OUT_…` lines, and the cursor a click inserts at,
  are right there.
- The variables that **fit your `[OPTIONS]`** (no glacier output when glaciers are off,
  …), **grouped by topic** — snow, meteo, evaporation, soil, groundwater, lakes,
  routing, water demand, crops, balance totals, static maps.
- The **filter box searches the unit, long name and description too**, so typing
  *evapo* finds `actualET`.
- A **✓ green** marks every variable your settings file already writes; the tooltip says
  in which `OUT_…` key and on which line, and clicking it again takes it out. Tick
  **Only variables already in the settings file** to see just those — the picker then
  works as an overview of your outputs.
- Variables marked **`[index]`** are arrays: `actualET` is calculated per land cover, so
  it must be written `actualET[1]`. You are asked which one **by name** —
  *1 - grassland*, *0,2 - top soil layer, irrPaddy* — instead of having to know the
  numbers. (Check settingsfile flags a wrong index with the same table.)
- **Left-click** inserts at the cursor (on an `OUT_TSS_…`/`OUT_MAP_…` line);
  **right-click** picks the output type and time step, creating the key if needed.
- By default only the recommended (high-priority) variables are listed; **Load all
  Variable** shows all ~580. Whatever your file already uses is always listed.

### Restore settingsfile (Tools menu)
Every CWatM discharge/ET output file carries the **complete settings file** and the
**list of input files** the run used. Tools ▸ Restore settingsfile opens such a `dis*.nc`
and shows what is inside:
- A **summary card** on top — Title, when it was created, which CWatM version, which
  settings file — above the full attribute table.
- **Preview settingsfile** — read the stored settings in a read-only editor (with the
  usual colouring and folding) *before* you decide anything. From there you can **Save
  as…**, **Load into editor (unsaved)** — the settings go into the main editor without
  writing any file, and one **Ctrl+Z** takes it back — or **Compare with current**.
- **Compare with current** — a side-by-side diff of the stored settings against the ones
  you have loaded: what did this run do differently?
- **Restore settingsfile** — write the stored settings to a new file and load it. The
  suggested name is now `<title>_<run date>.ini`, so restoring several runs into one
  folder no longer collides; if your current file has unsaved edits you are asked first.
- **Show Inputfiles** — the recorded input files, each with the date the run saw, and a
  **check**: is the file still there (**missing**, in red), is it still the same version
  (**changed since the run**, in orange), or is everything as it was? A summary line
  counts them. Use **Re-check files** after you fixed something. **Double-click a file**
  to open it — a NetCDF opens in the map viewer (Analyse ▸ NetCDF), anything else in the
  program your desktop uses for it.
- **Show in Journal** — jump to the run that wrote this file in the Journal of Runs.
- **Ctrl+C**, a right-click menu and **Export as CSV** work on both tables.
- Buttons a file cannot serve (e.g. an output NetCDF without a stored settings file) are
  greyed out with the reason in the tooltip.

### Check settingsfile (Settings menu)
- **Check settingsfile** (F4) is a **toggle**: it scans the settings and flags every
  value that is a filename/path (a `$(…)` placeholder, a data-file extension, or an
  absolute path), then the menu item relabels to **Clear checking** — press **F4** again
  to remove all the marks (your own bookmarks are kept). Lines are colour-coded by
  severity:
  - **Red + bookmarked** — the file/folder **does not exist** (jump with F2 / Shift+F2).
    Keys starting with `path` are checked as **directories**.
  - **Light orange, no bookmark — wrong extension**: the file exists under a different
    raster extension than written (e.g. `cellarea.map` written, `cellarea.nc` on disk).
  - **Dimmed light orange, no bookmark — not read**: a missing file CWatM won't actually
    read, e.g. a section whose `[OPTIONS]` switch is off, a value-gated file
    (`averageDischarge`/`averageBaseflow` with `swAbstractionFrac ≥ 0`), or the
    preprocessed/optional groundwater-MODFLOW input.
- It also runs **semantic checks**: the date ordering `StepStart ≤ SpinUp ≤ StepEnd`,
  whether an option that is **on** has its required keys/paths (e.g. MODFLOW coupling with
  a missing `path_mf6dll` marks the `modflow_coupling` line), the validity of every
  `OUT_…` output key and its variable names, and whether the run window fits inside the
  **meteo forcing** data's time range (catches the common "StepEnd is past my forcing
  data" crash before you waste a run). A summary of only the problem lines is written to
  the output box.

### Batch Run — what protects you

- Before anything starts, the scenarios are **checked**: a row without a PathOut, or two
  rows sharing one, is refused (they would write over each other's results); an override
  key that does not exist in the base settings file, a duplicate scenario name or an
  output folder that already holds files asks first.
- Every scenario writes **its own log** to `<PathOut>/cwatm_out.txt` instead of mixing
  into the main output box. Right-click a row for **Show log**, and hover a failed row to
  see the actual error.
- **Right-click a scenario** to run just that one, re-run everything that failed, open its
  output folder, or see **what it changes in the settings file** side by side with the
  base.
- Each row shows its **duration**, and the line under the title tells you how far the
  batch is and roughly how long is left (`3/20 finished · 2 running · ~1:12:30 left`).
  When it is done the taskbar entry flashes and the line becomes a summary.
- **Import CSV / Export CSV**: build the scenarios in Excel (columns *Scenario*,
  *PathOut*, then one per key you override) and read them in. Export writes the same
  columns plus each row's duration and status — so it is also the batch's result table.
- **Parallel runs** starts at a sensible value for your machine and warns if you push it
  well past half your cores. Tick **Stop on first failure** to hold the queue back when
  something fails (runs already going are left to finish).
- **Compare results**: one click overlays the same result file from every scenario in a
  single Timeseries plot, each line labelled with its scenario — the reason you ran the
  sweep. If several result files qualify, you are asked which one.
- **Skip finished** resumes an interrupted batch: scenarios whose output folder already
  holds results are not run again. Running a single scenario from the row menu always
  runs it, whatever is in its folder.
- The **Progress** column is a bar, so a long table can be read at a glance.

## Maps, Excel and Result Analysis

### Show Basin (Tools ▸ Show Basin)
The catchment on an OpenStreetMap map (EPSG:4326): the `ups.nc` river network and the
green mask overlay, numbered red gauge pins, a blue mask-start pin. Click to read
coordinates/area; create/copy the mask and gauges; overlay a GeoJSON (**Load JSON**);
fade the OSM basemap with the transparency slider.

![Show Basin](figures/screenshot_basin.png)

### Excel editor (Tools ▸ Excel Crops/Reservoirs)
Edit the settings `Excel_settings_file` in a table that **reproduces the Excel cell
colours** — and works like Excel:

- **Sheet tabs below the table** (Crops, Reservoirs, Reservoirs_downstream, …); a sheet
  with unsaved edits gets a `*` on its tab.
- **Formulas**: type `2+3.5`, `2 + I3`, `=(A1+B1)/2` or `=SUM(C2:C10)` — the cell shows
  the result, editing it shows the formula again, and it recalculates when a cell it
  refers to changes. Start with `'` to keep something as plain text.
- **Copy & paste blocks**: select one cell or many, **Ctrl+C** / **Ctrl+X** / **Ctrl+V**,
  **Delete** to clear — or use the **right-click menu**. The clipboard is tab-separated,
  so blocks travel to and from Excel itself.
- **Fill handle**: drag the little square at the selection's bottom-right corner to
  autofill. One cell fills its value into the rest; from two or more, the series
  continues (`1, 3` → `5, 7, …`, `Crop1, Crop2` → `Crop3…`, month and weekday names).
- **Whole columns and rows**: click a column letter or row number — a full-line
  selection is shown in a stronger gray. **Right-click the header** to *copy*,
  *insert empty*, *paste* (making room instead of overwriting) or *delete* whole
  columns/rows. A line copied from a header remembers whether it is a column or a row
  and which sheet it came from, so it cannot be pasted the wrong way round or into
  another sheet.
- **Text columns** are shown at half width (and never wider than ~120 characters) with
  **word wrap**; widen or narrow a column and the text re-wraps. Text that still does
  not fit is **cut off at the column edge** rather than drawn over the next column —
  widen the column to see it all. Columns are sized to their **header** as well as their
  data, and the reservoir-ID columns of *Reservoir_transfers* always stay wide enough to
  read an ID such as `400001`.
- **Symbol bar** at the top left: copy, cut, paste, delete │ **B** │ undo, redo — the
  same things the shortcuts do, greyed out when they cannot be used right now.
- **Bold**: mark cells and press **B** (or **Ctrl+B**) to make them bold; press again to
  take it off. It is saved with the workbook and can be undone.
- Marked cells are shown in **dark gray**, a whole marked column or row in a darker
  shade still.
- The **header row stays put**: it is the sheet's first row and never scrolls away —
  the mouse wheel over it scrolls the table underneath. It **can be edited** there
  (double-click it, or press F2, or just start typing), like any other row.
- **Undo / redo** (**Ctrl+Z** / **Ctrl+Y**) covers everything you change: single cells,
  pastes, fills, and whole inserted or deleted columns and rows. Each sheet keeps its
  own history.
- **Nothing is lost silently**: **Reload**, **Load** and **closing the window** ask
  first when a sheet still holds unsaved edits (Save / Discard / Cancel).
- **Big workbooks stay responsive**: the file is read in the background — the window
  shows *Loading …* instead of freezing (which matters when the workbook lives on a
  network drive), and even a sheet with a thousand columns opens and scrolls at once.

**Load / Reload / Save / Save As** work on the whole workbook: your edits on *every*
sheet are written back, preserving all other sheets and styling; large sheets load
instantly (lazy).

![Excel — Crops](figures/screenshot_excel_crops.png)

![Excel — Reservoirs](figures/screenshot_excel_reservoirs.png)

### Output Explorer (Analyse ▸ Output Explorer)
A browser of your PathOut folder: **double-click** a result and it opens in the matching
viewer — `.nc` → NetCDF map, `WaterCycle*.csv` → sunburst, other `.csv` → Timeseries. No
more hunting through file dialogs after a run.

### Timeseries (Analyse ▸ Timeseries)
Plot a result `.csv` (line chart). Step through multiple columns, **Compare** another
file, **Save as csv** in the CWatM result format, or **Save HTML**. A **range slider**
below the plot shrinks the displayed period from either end. **Load observed** overlays
an observed series and shows goodness-of-fit metrics — **KGE / NSE / PBIAS / RMSE** —
computed over the period the slider selects. **Flow duration** and **Flow regime**
(Action menu) open a dedicated window for the column currently on screen, over the
**displayed period** — move the slider and an open Flow duration / Flow regime window is
recalculated for the new period. See below.

![Timeseries](figures/screenshot_timeseries.png)

### NetCDF (Analyse ▸ NetCDF)
A result `.nc` as a raster overlay on an OSM map with a timestep slider + Play,
colour-scale, **Log scale**, OSM-transparency slider, and click-to-read. **Left-click a cell
(or a gauge pin) to select it** - it gets a numbered pin; click more cells to add more
stations, and click a selected cell or its pin again to remove it. Two ways to plot
the selected cells' series: **Fast Display Timeserie** (quick, the map's timesteps only, with
gaps) or **Total Timeseries** (every timestep — can take a while, so a progress bar with
elapsed time and a **Cancel** button shows while it reads). **Right-click anywhere on the
map** for the same menu. **Compare A−B** loads a second
`.nc` on the same grid and shows the **difference** (this − other) per timestep on a
red/blue diverging scale — ideal for comparing two scenarios you just ran.
**File ▸ Load netcdf** opens another `.nc` (starting in the current file's folder) in the
same window. **Calculate mean** / **Calculate percentile** (Action menu) reduce the whole time axis to
one map - the mean, or a percentile you choose (e.g. 50 = median) - and save it as a new
NetCDF next to the original (`discharge_mean.nc` / `discharge_50_percentile.nc`, name
changeable). The new file keeps all metadata of the original plus where it came from
(file name, folder, creation time), and the map switches to it.

**Flow duration / Flow regime** (Action menu, on the map, or from Timeseries above) plot
the **last point you clicked** — never several at once. **Flow duration** ranks each
year's values into an exceedance-probability curve; **Flow regime** shows the seasonal
cycle (day-of-year or month-of-year). Both show every year as a thin line plus a black
cross-year average, with buttons to hide the single years, show light-gray 0–100 %/40–60 %
percentile bands, save the per-year table as csv, or save the plot as HTML.

![NetCDF](figures/screenshot_netcdf.png)

### Watercycle (Analyse ▸ Watercycle)
The water balance of a `WaterCycle_areasum_monthtot.csv` as a **sunburst**, over a
month range slider. **Save CSV** (lower left) stores the numbers behind the plot
(suggested name `watercycle.csv`), **Save HTML** the plot itself.

![Watercycle](figures/screenshot_watercycle.png)

### Flow Diagram (Analyse ▸ Flow Diagram)
The same water balance as a **Sankey** flow diagram. **Save CSV** stores one row per
flow in mm/year (suggested name `flowdiagram.csv`).

![Flow Diagram](figures/screenshot_flowdiagram.png)

### CWatM AI (CWatM AI button)
Ask questions about CWatM in a chat window answered by Google **NotebookLM** (Gemini),
grounded on a notebook that holds the CWatM documentation. Answers are formatted, the
transcript/history persist between sessions, and a **Short / Medium / Long** selector
sets the answer length (Short = fastest).

- **Prepare once:** at *notebooklm.google.com* create a notebook whose title contains
  **"CWatM"** and upload the CWatM docs as sources (the GUI ships
  `documentation/CWATM_shorter.pdf`); CWatM AI auto-selects that notebook.
- **Login is one click:** **Login…** auto-detects the browser you're signed in to Google
  with (Firefox → Chrome → Edge → Opera) and verifies the session. Firefox needs no admin;
  Chrome/Edge/Opera need CWatM **run as administrator** (Windows encrypts their cookies).
  **Choose browser…** is the manual fallback (and the source-only Google login window).
- **Explain current line** asks NotebookLM to explain the settings line at the cursor.

Full guide: `documentation/CWatM_AI_NotebookLM.md`.

### CWatM account, points and the Shop

The CWatM account is **optional** - CWatM and the GUI work fully without it. Logged
in (the account button in the menu bar's right corner), every full CWatM run with a
new model setup earns a point, finished CWatM Academy levels earn points too, and the
points earn **river badges** (Breg, Thames, Morava, …).

- **Your points** are the points you can spend. Next to them the account window shows
  the points **earned in total** - those never go down and decide your badges.
- **The Shop** (the **Shop** button left of your name; it appears once you have the
  **Breg** badge) sells:
  - the **Advanced** (20 points) and **Expert** (40 points) skill levels - Advanced
    first, then Expert. Expert stays greyed out until you own Advanced;
  - **animals** for the live discharge plot: Fish (5), Otter (10), Beaver (20),
    Sailboat (30), Octopus (50). The selector offers the ones you can afford.
- **Buying** asks first, takes the price from your points and is final (no refunds).
  Your badges stay, and the next badge still needs its full earned points. A bought
  animal appears on the discharge plot at once; a bought level can be switched to
  right away.
- **Example:** you earned 20 points and hold Breg and Thames; you buy Advanced for 20 -
  you now have 0 points to spend, still 20 earned in total, and both badges.
- **The leaderboard** (Info ▸ Leaderboard) ranks by your current points.
- **Use it or lose it a little:** without a login for a week your points drop by 3 %,
  every further week by another 5 % of what is left - never below 5 points. Logging in
  (the automatic login at start counts) stops it. Earned points and badges never shrink.
- **Not interested in the game?** Tick **Cheat - and get the Expert level without
  buying it** in Preferences ▸ Account: every skill level is open for this session,
  logged in or not. It switches itself off when the GUI is restarted.
- Accounts that existed when the Shop opened got Advanced and Expert for free.

## Usage

### Basic Workflow
1. **Load a Configuration File**: **File ▸ Load .ini** (Ctrl+O) — parsing begins
   immediately.
2. **Navigate and Edit**: use Settings ▸ Fold/Unfold/Top/Down/Find and the ▾/▸ fold
   markers in the gutter (or double-click a section header).
3. **Adjust Dates/Settings**: modify Start/Spin/End Date, PathOut, or MaskMap — changes
   auto-apply in memory; Save / Save As turn blue.
4. **Manage Options**: **Tools ▸ Change Options** for boolean settings.
5. **Save**: **File ▸ Save .ini** (Ctrl+S) or **Save As** (Ctrl+Alt+S).
6. **Run CWatM**: **RUN CWATM ▸ Run CWATM** (Ctrl+R) — runs the file on disk, so save
   first.
7. **Monitor Progress**: watch the progress clock (below the output box) and the output
   area.
8. **Stop if Needed**: Run CWATM (Ctrl+R) again to interrupt.
9. **Check Data (Optional)**: **Tools ▸ Check Data** to validate before running.
10. **Analyse Results (Optional)**: **Analyse ▸ Timeseries** to plot a result `.csv`
    (opens in the PathOut folder).
11. **Exit**: **File ▸ Exit** prompts to save if there are unsaved changes.

### Data Validation Workflow
1. Open the Check Data window (Tools ▸ Check Data) — it is not modal, so the settings
   editor stays reachable beside it.
2. Optionally change where the result CSV is written (default `<PathOut>/check_cwatm1.csv`).
3. Optionally select a discharge NetCDF file for comparison.
4. Optionally **Restore settings from discharge map** — opens it in *Restore settingsfile*.
5. Run the check (CWatM check mode); it runs in the background, with its output in the
   log pane and an elapsed-time counter.
6. Review the results: problem rows are tinted and counted, **Select trouble** isolates
   them, and a double-click jumps to that key in the settings file.

## User Interface Layout

### Top
- **Banner**: CWatM icon + "CWatM GUI" title, centered "The Community Water Model User
  Interface", IIASA logo.
- **Menu bar** (below the banner): File · Settings · Tools ·
  RUN CWATM · Configure │ Analyse │ **CWatM AI** · Help · Info (see the Menu Bar
  section in `CLAUDE.md`), and a **⋮** button in the bar's right corner. The Excel
  workbook editor lives in **Tools ▸ Excel Crops/Reservoirs**; there is no Excel
  menu. Recently
  opened files (up to 6) are listed directly in the **File** menu — there is no
  separate History menu.
- **Preferences** (**Configure ▸ Preferences…**, **Ctrl+,**, or the **⋮** button on
  the right of the menu bar): one window holding every GUI setting, on five pages you
  pick from the list on the left:
  - **Output** — the file the output box is written to, and whether it is written.
  - **Startup & Model** — reopen the last session's tabs at start.
  - **Display** — colour mode, header banner, the font and font size of the settings
    file, decimals shown, initial map transparency, default background map,
    sparkline animal.
  - **Editor & Dates** — skill level (how much of the settings file **and of the
    menus** is shown: *Beginner* hides the advanced entries, e.g. Batch Run, Windowed
    Run, Check Data, the Excel editor and the water-balance analyses), the
    date picker style, the date timeline, auto-bookmark on change, and **Use Tabs**
    (the settings-file tabs, Expert level only). Advanced and Expert are bought in
    the **Shop** - or tick *Cheat* on the Account page.
  - **Account** — stay logged in, count my runs, record run locations, and the
    **Cheat** tick (all skill levels for this session, no purchase needed).
  - **Run History** — where the Journal of Runs is kept and for how long.

  Nothing changes while you are clicking around: **Apply** puts the current page's
  choices into effect and keeps the window open, **OK** applies them and closes, and
  **Cancel** throws away anything you have not applied yet. All settings are
  remembered for the next session (except *Write output box*, which always starts off).
- **Language** (Preferences ▸ Display ▸ Language): **English** (default), Deutsch, Italiano,
  Magyar, Română, Srpski, Hrvatski, Slovenčina, Български, Čeština or Українська.
  Menus, menu items, buttons, labels and tooltips change at once, and the choice is
  remembered for the next start. Messages, window titles and the settings file itself
  stay in English.
- **Colour modes** (Preferences ▸ Display ▸ Mode): switch the whole GUI between **Normal**
  (classic light), **Dark Mode**, and **Mikhail** (black background with amber
  font, CRT style). The choice applies immediately — including the settings
  editor's syntax colours and the changed/duplicate line highlights — and is
  remembered across sessions. The Options, Check Data, Basin, About and both
  Analyse windows follow the mode too (Analyse plots switch to a dark Plotly
  style); a window that is already open keeps its colours until it is reopened.
  Map/data content (OSM tiles, the basin canvas) stays in its natural colours.
- **Select animal** (Preferences ▸ Display): pick the little animal that
  occasionally appears on the live discharge sparkline. The list holds the animals you
  bought in the **Shop** (Fish / Otter / Beaver / Sailboat / Octopus); without one, the
  sparkline shows a plain dot.
- **Font of the settings file** (Preferences ▸ Display): **Font of settingsfile** picks
  the family the settings editor is displayed with (the list shows the monospaced fonts
  installed on your machine; Consolas by default on Windows), and **Font size of
  settingsfile** picks its size in pixels (6–32). The size is the same setting as the
  **Font+** / **Font-** buttons above the settings file — change it either way, the
  other follows, and both are remembered for the next session.

### Control Panel (Left Side)
- "Loaded: …" filename label (left-aligned, slightly larger font).
- Date input fields with validation (Start / Spin / End Date).
- PathOut and MaskMap input fields (changes auto-apply to content in memory).
- **CWatM Output Area**: left-aligned scrollable display (taller box; max width capped
  at the End Date field), text selectable/copyable.
- **Progress Clock**: centred/left **below** the output box.

### Text Display Area (Right Side)
- Button row above the editor: Save · Save As · Fold All · Unfold All · Top · Down ·
  **Font+** / **Font-** (grow/shrink the settings-file font one step; the same setting
  as Preferences ▸ Display ▸ *Font size of settingsfile*) · the coloured skill-level
  button.
- **Tabs** — one settings file per tab, in the bar below the button row (see
  *Working with several settings files* below).
- Syntax-highlighted configuration content (plain text — what you see is what is saved).
- Line-number gutter with ▾/▸ fold markers on section headers (click to toggle;
  double-clicking a header line works too).
- Preserved whitespace and formatting.

## Workflow Guidance System

### Change Detection & Visual Cues
- **Save / Save As** turn light blue whenever there are unsaved changes (editor edits,
  date/path field changes, or option toggles) and return to normal after a save or load.
- **RUN CWATM ▸ Run CWATM** runs the model; selecting it again while running stops it
  (Ready = "RUN CWatM", Running = "STOP CWatM").
- Monitored inputs: Start/Spin/End Date, PathOut, MaskMap, and boolean options in the
  Options window.

## Execution Internals (progress, errors, cleanup)

### Real-time Progress Tracking
- **Progress Clock**: a circular indicator sized responsively to the screen
  (~110–220 px); blue arc (`#0066CC`) on a light-gray background circle, blue percentage
  text, and the elapsed / remaining run time drawn inside the face; no border/ticks.
- **Percentage**: `progress = (current_day - start_day + 1) / total_days * 100`, clamped
  to 0–100%.
- **Live Updates**: the clock updates each model timestep. This is driven by a GUI hook
  inside `cwatm/management_modules/output.py` (a pre-existing model-side integration
  point) using `dateVar['intStart']`, `dateVar['intEnd']`, `dateVar['curr']`.
- Resets to 0% when a new run starts; state is preserved across stop/start.

### Error Handling
- Color-coded output: normal in black, errors/exceptions in dark red, status in the
  default color (HTML formatting in the output area).
- Exception capture at three levels: a global handler, local try/except in critical
  operations, and thread-safe error reporting via Qt signals.

### Execution Control & Cleanup
- **Separate-process architecture** (default): `CWatMProcessWorker` runs the model in
  its own OS process via `QProcess`; **Stop** is a real `kill()` and a model crash is
  isolated from the GUI. The model output is streamed back over the process pipes.
  (An in-process `QThread` worker, `CWatMWorker`, remains as a fallback.) Both expose
  the same signals: `finished(bool, object)`, `error(str)`, `progress(int)`.
- **Interrupt**: an immediate kill in separate-process mode; a cooperative stop with a
  graceful shutdown + force-termination fallback in the in-process mode.
- **Resource cleanup** (on stop, on error, and on shutdown): close `netCDF4.Dataset`
  objects and `io.IOBase` file handles, then garbage-collect to release references —
  preventing file locks and leaks.


