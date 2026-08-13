# CWatM GUI - changelog

Release notes, newest first. The version itself lives in `src/gui/__init__.py`
(`__version__`), which the About dialog reads and the installer scrapes at compile time.


## CWatM GUI 1.05 — what is new

*Released 11 August 2026. Previous release: 1.04 (10 August 2026).*

This release opens the editor to **several settings files at once**, and works on the
four windows you use **before and after** a run — the ones that tell you what your
settings say, what CWatM will write, whether the data is sound, and what a finished run
actually used. Each of them could show you something; none of them could tell you enough.

---

### 1. Tabs — several settings files open at once

Comparing two settings files, or preparing a variant beside the original, meant loading
one, reading it, loading the other back. The editor now holds **one tab per settings
file**, in a bar between the button row and the editor.

| | |
|---|---|
| **The active tab is the application** | RUN CWATM, the Start/Spin/End dates, PathOut, MaskMap and Gauges boxes, Check settingsfile, Show Basin, Check Data, the Excel editor and the Analyse windows all work on the file of the tab you are looking at — switching tabs swaps the whole left panel with it. |
| **Every tab keeps its own editing state** | Undo history, bookmarks, folded sections, changed-line highlights and the red Check-settingsfile marks belong to the tab, not to the window. |
| **Add, close, reorder** | The small **+** right of the last tab opens an empty one; an **✕** appears on the tab under the mouse to close it; tabs can be dragged into another order. A tab with unsaved edits carries a **`*`**, and on exit you are asked once per unsaved file. |
| **One file, one tab** | Loading a file another tab already has brings you to that tab instead of opening a second copy — two tabs on one file would mean two independent versions of the text, and the second Save quietly discarding the first tab's work. *Save As* onto another tab's file is refused for the same reason. |
| **They come back** | With **Load previous settings at start** (Preferences ▸ Startup & Model) ticked, *all* the tabs are reopened on the next start, the one you were working in on top. |

**Right-click a tab** for **Delete Tab**; **Copy Tab**, which writes what the tab
currently shows — unsaved edits included — to `settings_2.ini` next to it and opens that
in a new tab, so a scenario variant is two clicks; **Run CWatM**, which runs *that tab's*
file in its own Windowed Run window, beside whatever else is running; and **Link
scrolling**, which ties a tab to the one before it — scroll either and the other follows,
fold `[OPTIONS]` in one and it folds in the other, so switching between the two lands you
on the same lines.

Comparing two open files got shorter with them:

- **Settings ▸ Compare Tab (F8)** colours every line that differs from the neighbouring
  tab light green **in both tabs**, right in the editor. F8 again clears it; nothing is
  written to either file.
- **Settings ▸ Compare settings** opens with the active tab in the left pane and the
  neighbouring tab in the right one — with two files open, a side-by-side diff is one
  menu click.

Tabs are part of the **Expert** skill level and can be switched off in
**Preferences ▸ Editor & Dates ▸ Use Tabs** (on by default). Unticking hides only the
bar: the open tabs keep their content and the file you were working in stays in the
editor.

### 2. Change Options — what does this switch do?

The `[OPTIONS]` tick boxes were a flat, unexplained list. Now:

| | |
|---|---|
| **ⓘ per option** | A small circled **i** next to each switch. Hover it to read what the option controls and what True/False mean — 34 switches are described so far, from `TemperatureInKelvin` to `static_irrigation_map`. |
| **Grouped by topic** | Meteo & evaporation · Grid & soil · Snow & glaciers · Water demand · Crops · Groundwater & MODFLOW · Water bodies & routing · Initial conditions · Output & reporting · Water balance (debug) · Other. |
| **Filter + Changed only** | Find a switch by name; or see just what you altered since opening the window. |
| **Change marks + Revert all** | A dot on every option you changed, and one button to put them all back. |
| **Add option…** | Offers the switches CWatM understands that your file does not define yet, and writes the chosen one into `[OPTIONS]`. |
| **Not modal** | The settings editor stays readable beside the window, and it remembers its size and position. |

Two long-standing bugs went with it: an option written with a comment after it
(`includeGlaciers = False   # no OGGM data yet`) **never appeared in the window at
all**, and ticking a box **deleted the comment**. Ticking is now also a single
**Ctrl+Z** in the editor.

### 3. Add output variables — pick the right one, with the right index

CWatM offers 580 output variables in one alphabetical list. Now:

- **Grouped by topic** (snow, meteo, evaporation, soil, groundwater, lakes, routing,
  water demand, crops, balance totals, static maps) and the **filter box searches the
  unit, long name and description** as well as the name — typing *evapo* finds
  `actualET`.
- **A ✓ marks every variable your settings file already writes**, in green and bold,
  with the `OUT_…` keys and line numbers in its tooltip. Tick **Only variables already
  in the settings file** and the picker becomes an overview of your outputs. Clicking a
  ✓ variable takes it out again.
- **Array variables are handled.** `actualET` is calculated per land cover and is
  invalid as an output without an index. Such variables are marked **`[index]`**, and
  both click styles now ask which one **by name** — *1 - grassland*, *0,2 - top soil
  layer, irrPaddy* — instead of leaving you to guess a number. Check settingsfile flags
  a wrong index from the very same table, so the checker and the picker cannot disagree.
- **No Refresh button**: the window re-reads the settings file when you come back to it,
  and rebuilds the list only if you changed an option that filters it.

### 4. Restore settingsfile — a result file explains itself

Every CWatM discharge/ET output carries the complete settings file and the input-file
list of the run that made it. Until now you could only *write it out and load it* —
replacing the file you were working on, unseen.

- **A summary card** on top: title, when it was created, which CWatM version, which
  settings file.
- **Preview settingsfile** — the stored settings in a read-only editor, with colouring
  and folding. From there **Save as…**, **Compare with current** (a side-by-side diff
  against your loaded file: *what did this run do differently?*), or **Load into editor
  (unsaved)** — nothing is written to disk and one **Ctrl+Z** takes it back.
- **Show Inputfiles now checks them.** For each recorded file: is it still there
  (**missing**, red), is it still the version the run used (**changed since the run**,
  orange, with the file's current time stamp), or is everything as it was? A line above
  counts them, and a **double-click opens the file** — a NetCDF in the map viewer.
- **Show in Journal** jumps to the run that wrote the file.
- **Ctrl+C, a right-click menu and Export as CSV** on both tables — before this, nothing
  could leave the window at all.
- Buttons a file cannot serve are **greyed out with the reason**, instead of explaining
  it after you click; the restored file is suggested as `<title>_<run date>.ini` so
  restoring several runs into one folder no longer collides.

Fixed here: *Check Data ▸ Restore settings from discharge map* wrote the settings file
**one character per line** — it looped over the stored text as if it were a list of
lines. It now opens the same Restore settingsfile window, so there is one implementation
instead of two.

### 5. Check Data — no longer a frozen window

The data check opens every input map your settings reference. It used to do that in the
GUI thread, so the whole application stopped responding — with no progress, and with
every message printed into the main output box *behind* the dialog, where it could not
be seen.

- **It runs in the background**, with the elapsed time shown; the window and the rest of
  the GUI stay usable. (There is still no Stop: CWatM's check has no break point.)
- **CWatM's output appears in the window**, in a log pane under the table — including
  the full traceback when something fails.
- **Unsaved changes are caught first.** CWatM reads the settings from disk, so an
  unsaved editor would have checked a different file than the one you see.
- **Reading the results**: problem rows are tinted across their full width and counted
  above the table (*"312 rows · 7 not valid · 3 date mismatches"*), columns are
  **sortable**, a **filter box** narrows them, and a **double-click on a row jumps to
  that key** in the settings editor.
- **Run Check is disabled for a coordinate MaskMap** — the window always said it needed
  a MaskMap map, but let you press the button and fail deep inside CWatM.
- The result CSV defaults to **`<PathOut>/check_cwatm1.csv`** (it used to be written to
  whatever the working directory happened to be), and **Copy Table** / **Export CSV**
  take exactly the rows shown.

---

### Also in this release

- **Five windows were never themed**: a stylesheet ended in `}}` — an escape only inside
  an f-string — so Qt rejected the whole sheet. The **Journal of Runs** table and its log
  viewer, the **Batch Run** log viewer, the **Windowed Run** progress bar, the **CWatM AI**
  input box and the **Output Explorer** header now follow the colour mode like everything
  else.
- **`src/gui/utils/var_dims.py`** is the new single source for which model variables are
  arrays and what index they need (mirrored from CWatM's allocation lists). Check
  settingsfile validates against it; Add output variables offers the choices from it.
- **Hidden Run CWatM is now Windowed Run CWatM** — the same window (its own OS process,
  several at once), under a name that says what it does: *run CWatM in a separate
  window*. It is what a tab's right-click **Run CWatM** opens, and what the Journal of
  Runs' **Re-run** starts.
- **The FAQ gained three sections** (options & output variables, Check Data, reading a
  result file's settings) and lost three stale answers — including a *Clear checking
  (Shift+F4)* shortcut that no longer exists, and a dozen Linux questions filed under the
  heading *Excel sheets*.

### Upgrading

Nothing to do: settings files, run history and preferences are unchanged. Check Data now
opens as a normal window rather than a modal dialog, so you can leave it open while you
work in the editor.


---


## CWatM GUI 1.04 — what is new

*Released 10 August 2026. Previous release: 1.03 (7 August 2026).*

Two areas changed in this release: the **Excel workbook editor** moved and grew up, and
the **Batch Run** was rebuilt around not losing work.

---

### 1. Excel workbook editor — now in Tools, and much closer to Excel

**The separate *Excel* menu is gone.** Its single item now lives in
**Tools ▸ Excel Crops/Reservoirs**, directly below *Change Options*. It behaves exactly
as before — it opens the workbook named in the settings `Excel_settings_file`, with all
its sheets on tabs — and it is still greyed out when the settings file has no such key.

What the editor gained:

| | |
|---|---|
| **Bold** | Mark cells and press **B** in the symbol bar or **Ctrl+B**. Pressing it again on cells that are all bold removes it. It is written into the workbook when you save, and **Ctrl+Z** undoes it. |
| **Symbol bar, top left** | ⧉ copy · ✂ cut · 📋 paste · 🗑 delete │ **B** │ ↶ undo · ↷ redo. Each button does what its shortcut does and is greyed out when it cannot be used. The sheet name is no longer repeated above the table — it is on the tab. |
| **The header row is editable** | Row 1 is shown on the frozen strip above the table; you can now edit it there (double-click, F2, or just type) to rename a column. Marking cells in the header row and pressing **B**, Delete, Ctrl+C/X/V or Ctrl+Z acts on the header row, not on the table below. |
| **The header row stays put** | Clicking it or spinning the mouse wheel over it scrolls the table underneath instead of scrolling the header out of sight. |
| **Clearer selection** | Marked cells are dark gray, a whole marked column or row a darker shade still. |
| **Column widths** | Columns are sized to their content **and their header** — a long header no longer runs into the next column. Text that still does not fit is cut off at the column edge instead of being painted over the neighbouring cell. Widen a column to read the rest. A few known columns keep a guaranteed minimum: the reservoir IDs in *Reservoir_transfers*, and the description column of *Reservoirs*. On a very wide sheet the B and C columns are 70 % wider than the rest, since those name the rows. |
| **Big workbooks stay responsive** | The file is read in the background — the window shows *Loading …* instead of freezing, which matters on a network drive. A sheet with a thousand columns now opens and scrolls immediately: it used to block the whole application for minutes, and a Select All left it unusable. |
| **Nothing is lost silently** | Reload, Load and closing the window ask first when a sheet still holds unsaved edits. |

### 2. Batch Run — safer, and useful for comparing scenarios

**Before anything starts, the scenarios are checked.** A batch is expensive and its worst
failures are silent, so these are caught up front:

- *refused*: a row without a **PathOut** (it would write into the base PathOut together
  with every other scenario), two rows sharing a PathOut (they would overwrite each
  other's results), a PathOut that cannot be created;
- *asked*: an override key that is **not in the base settings file** (it would be added
  silently as a new key — a typo otherwise runs the base value to completion), a
  duplicate scenario name, an output folder that already holds files, or a parallel count
  well beyond half the machine's cores.

**Every scenario writes its own log** to `<PathOut>/cwatm_out.txt` instead of mixing into
the main output box, where parallel scenarios used to interleave into one unreadable
stream. Hover a failed row to see the real error; right-click for **Show log**.

**Right-click a scenario** to run just that one, re-run everything that failed, open its
output folder, show its log, or see **what it changes in the settings file** side by side
with the base.

**Following a long batch**: each row shows its **duration**, and the line under the title
reads `3/20 finished · 2 running · 15 queued · ~1:12:30 left`. When it is done the
taskbar entry flashes and the line becomes a summary. Progress is drawn as a bar.

**Comparing the results** — the reason a sweep is run at all: **Compare results**
overlays the same result file from every scenario in a single Timeseries plot, each line
labelled with its scenario.

**Scenario tables**: **Import CSV / Export CSV** (build them in Excel; the export
includes each row's duration, status and last discharge, so it doubles as the result
table). The table is now remembered **per settings file** — opening another project no
longer greets you with the previous project's scenarios and its PathOuts.

**Interruptions**: tick **Skip finished** to resume a batch without re-running the
scenarios that already have results, and **Stop on first failure** to hold the queue back
when something fails (runs already going are left to finish).

Fixed along the way: two scenarios whose names differ only in punctuation (`run 1` /
`run_1`) wrote and deleted the *same* temporary settings file while both were running;
stopped scenarios left temporary files behind and disappeared from the Journal of Runs.

---

### Also in this release

- **Opening a file or folder** (Analyse ▸ Open PathOut Folder, the Journal of Runs, Output
  Explorer) now works on Linux and macOS as well, not only Windows.
- **Running on Linux** is documented end to end in `cwatm_gui_linux.md`, together with a
  `gui.sh` launcher that sets up remote-display (Xming/VcXsrv/X2Go) rendering and
  diagnoses a broken environment with `./gui.sh --check`.

### Upgrading

Nothing to do: settings files, run history and preferences are unchanged. The Excel item
has simply moved from the *Excel* menu into **Tools**.
