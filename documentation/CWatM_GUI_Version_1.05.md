# CWatM GUI 1.05 — what is new

*Released 11 August 2026. Previous release: 1.04 (10 August 2026).*

This release opens the editor to **several settings files at once**, and works on the
four windows you use **before and after** a run — the ones that tell you what your
settings say, what CWatM will write, whether the data is sound, and what a finished run
actually used. Each of them could show you something; none of them could tell you enough.

---

## 1. Tabs — several settings files open at once

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

## 2. Change Options — what does this switch do?

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

## 3. Add output variables — pick the right one, with the right index

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

## 4. Restore settingsfile — a result file explains itself

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

## 5. Check Data — no longer a frozen window

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

## Also in this release

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

## Upgrading

Nothing to do: settings files, run history and preferences are unchanged. Check Data now
opens as a normal window rather than a modal dialog, so you can leave it open while you
work in the editor.
