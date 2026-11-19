# CWatM GUI — FAQ & Troubleshooting

Short answers to the questions that come up most often. For a full feature tour see
**Help ▸ CWatM GUI Features**; for how-to documentation **Help ▸ CWatM GUI
Documentation**.

---

## Running the model

**I changed a value and ran, but the run used the old value. Why?**
A run always uses the settings file **on disk**, not the unsaved editor content. Save
first (**File ▸ Save .ini**, Ctrl+S). The **Save** button turns light blue whenever
there are unsaved changes, and a blue hint next to **RUN CWATM** lists which fields
(dates / PathOut / MaskMap / Gauges) differ from the saved file.

**The run doesn't start / nothing happens.**
- Make sure a settings file is loaded ("Loaded: …" shows the name).
- Run **Settings ▸ Check settingsfile** (F4) — missing input files are marked red.
- Check the output box for an error (shown in dark red).
- Look at the diagnostic log: `%LOCALAPPDATA%\CWatM_GUI\gui.log`.

**A message says CWatM would refuse some output entries.**
An `OUT_…` line holds something CWatM does not accept as a variable name — a typo, an
expression or a `$(…)` placeholder (CWatM stops with *Error 135*). The run is not
started, and the message names the lines. Fix them (F4 marks them red, and **Tools ▸
Add output variables** writes correct entries), save and run again.

**How do I stop a run?**
Press **RUN CWATM** again (it reads **STOP CWatM** while running). Because the model
runs in its **own process**, Stop is an immediate kill — it works even if the model is
stuck in C code.

**The run stopped with an error — how do I find where?**
Use **RUN CWATM ▸ Run CWatM + error message**. It is the same run with CWatM's `-e` flag:
an error message then also names the code lines where it happened.

**The run crashes partway through with a date/time error.**
Usually the run window extends past your forcing data. Check that **StepEnd** is within
the time range of your meteo/forcing NetCDFs, and that `StepStart ≤ SpinUp ≤ StepEnd` —
**Check settingsfile** (F4) checks both. The date calendars also dim the days outside
the forcing data.

**Can I run several things at once?**
Yes. **RUN CWATM ▸ Windowed Run CWatM** opens independent run windows (each its own
process), and **RUN CWATM ▸ Batch Run…** runs many scenarios, up to N in parallel. The
main GUI stays usable throughout.

**Can I run a different CWatM than the one built into the GUI (e.g. my development
version)?**
Yes, in **Windowed Run CWatM ▸ ⚙** (the gear right of *Load*): tick **User defined** and
enter a `CWatM_model.exe`, a CWatM folder, or a command line such as
`python P:\watmodel\cwatmpublic\develop\run_cwatm.py`, then press **Apply**. The green
line shows the exact command (the settings file and `-l` are added). This applies to
Windowed Runs only — unless you also tick the red **"WARNING: Expert only. Use this
model for the main RUN CWATM too"**.

**Why does the main window show "⚠ User-defined CWatM: …" in red?**
That red tick is on: **RUN CWATM** and **Run CWatM + error message** run the user-defined
model, and the status line at the bottom names the full command at the start of a run.
Untick it (Windowed Run ▸ ⚙ ▸ Apply) to get the standard CWatM back.

**Can I run CWatM without the GUI?**
**RUN CWATM ▸ Create batch** (Expert level) writes a Windows `.bat` file that runs the
current settings file exactly like the GUI does. Double-click it, or schedule it.

**Where does the output go?**
To the resolved **PathOut**. Open it quickly with **Analyse ▸ Open PathOut Folder** or
browse/open results with **Analyse ▸ Output Explorer**. If PathOut doesn't exist, use
**Tools ▸ Create PathOut Folder** (Windowed Run and Batch Run create it themselves).

**Which CWatM version is inside the GUI?**
**Info ▸ About CWatM** shows the GitHub repository, the **branch** and the **commit**
(short hash and date) the built-in CWatM was taken from.

---

## The settings editor

**A line is red — what does that mean?**
- **Strong red** = a **duplicate keyword** (the same key defined twice; the later one
  silently wins). *Note:* the stock Morava settings legitimately shows the `PathSoil`
  pair red — it really is an override.
- **Light red** = **Check settingsfile** (F4) flagged a **missing file/path** or another
  problem (date order, a missing key a switched-on option needs, a wrong output entry).
  F4 is a **toggle**: after a scan the menu item reads **Clear checking** — press **F4**
  again to remove the marks (your own bookmarks are kept).
- **Orange** = the file exists but with a **different extension** than written, or CWatM
  will not read it at all (its `[OPTIONS]` switch is off) — a hint, not an error.

**A line is red but the file exists.**
Re-run F4 after saving; the check uses the editor content and resolves `$(…)`
placeholders against the settings-file folder. Keys starting with `path` are checked as
**directories** (strict existence). If it still flags, the resolved path (shown in the
output-box summary after `->`) is where it actually looked.

**A line is highlighted light blue.**
That line differs from the last loaded/saved file — it clears when you Save.

**How do folded sections work? Will folding lose lines?**
No. Folding only **hides** lines (double-click a `[SECTION]` header or the ▾/▸ marker in
the gutter). Folded lines are still saved and searched; Find auto-unfolds a match.

**Whole sections of my settings file are missing.**
The **skill level** decides how much is shown: *Beginner* shows only the file paths,
mask/outlet, time and output sections; *Advanced* adds options, initial conditions, meteo
and evaporation; *Expert* shows everything. Click the coloured level button right of
**Font-** (or Preferences ▸ Editor & Dates ▸ Skill of user). Hidden sections are still in
the file and still saved. Every level is free.

**Some menu entries are missing.**
Also the skill level: *Beginner* hides the advanced entries (e.g. Windowed Run, Batch
Run, Check Data, the Excel editor, most water-balance analyses); *Compare Tab* and
*Create batch* are shown at *Expert* only.

**SpinUp / StepEnd is a number, not a date — is that OK?**
Yes. An integer is a **timestep count** (StepStart = timestep 1). The date fields show
the computed date.

**Can I have two settings files open at the same time?**
Yes — the bar above the editor holds **one tab per file**. The **+** right of the last
tab opens an empty one, and the file of the tab you are looking at is what everything
(RUN CWATM, the left-panel fields, Check settingsfile, Show Basin, Check Data, the
Analyse windows) works on. **F8** colours the differences between the active tab and the
one next to it, in both tabs. Tabs are shown in the **Expert** skill level, and can be
switched off with **Preferences ▸ Editor & Dates ▸ Use Tabs**.

**I loaded a file and it just switched to another tab instead.**
That file is already open in that tab. One settings file can only be open **once**:
two tabs on one file would each hold their own version of the text, and the second Save
would quietly throw the first one's edits away. *Save As* onto another tab's file is
refused for the same reason.

**Can I run a second settings file without touching the one I am working on?**
Right-click its tab ▸ **Run CWatM** — that opens a **Windowed Run CWatM** window on that
tab's file (as saved on disk), which runs in its own process beside everything else.

**The font of the settings file is too small / too large.**
**Font+ / Font-** above the editor, or **Preferences ▸ Display ▸ Font size of
settingsfile** (and *Font of settingsfile* for the family).

---

## Options and output variables

**An option is missing from Tools ▸ Change Options.**
Use the **filter box** to find it (options are grouped by topic), or **Add option…** if
your file does not define it yet. Comments after a value
(`includeGlaciers = False   # no OGGM data yet`) are kept when you tick the box.

**What does this option actually do?**
Hover the small **ⓘ** next to it. **Changed only** shows what you altered in this
session, each changed row has a dot, and **Revert all** puts them back. A tick is one
**Ctrl+Z** in the editor.

**Where do I find the output variable I want (Tools ▸ Add output variables)?**
The list is **grouped by topic** and the filter box searches the **unit, long name and
description** as well as the name — typing *evapo* finds `actualET`. Only the
recommended variables are shown by default; **Load all Variable** shows all ~580, and
only the ones that fit your `[OPTIONS]` are ever listed.

**A variable has a ✓ — what does that mean?**
Your settings file already writes it. The tooltip says in which `OUT_…` key and on which
line; clicking it again takes it out (and deletes the output line if it was the last
variable on it). Tick **Only variables already in the settings file** to see your outputs
at a glance.

**Why does a variable say `[index]`, and which number do I use?**
It is an array — `actualET` is calculated per land cover, so CWatM needs `actualET[1]`.
You are asked **by name** (*1 - grassland*, *0,2 - top soil layer, irrPaddy*), so you
never have to look the numbers up. Check settingsfile flags a missing or out-of-range
index the same way.

**Does the list follow my changes?**
Yes, without a refresh: the window re-reads the settings file whenever you come back to
it, and rebuilds the list if you changed one of the `[OPTIONS]` switches that filter it.

---

## Maps (Show Basin, NetCDF)

**The map is blank or very slow.**
The maps need WebGL, which the GUI runs in **software** mode so it works on any machine.
First open can take a moment. If it stays blank, check `gui.log`. Behind a corporate
proxy the GUI fetches the map tiles itself (Python), so a proxy that blocks the browser
engine is not a problem — but a fully offline machine shows the data overlays over a
white background (no basemap), which is expected.

**The basemap doesn't line up / is missing.**
The viewers use **EPSG:4326 WMS** basemaps (not the usual web tiles) so they align with
CWatM's lon/lat grids. Pick a different basemap (NetCDF: **Display**; Show Basin: the
basemap selector), or set a default in **Preferences ▸ Display ▸ Default openstreet map**.

**My grid is in x/y (e.g. UTM) and there is no OpenStreetMap behind it.**
That is expected: a projected grid is drawn on its own x/y coordinates, without a
basemap. Everything else (clicks, gauges, timeseries) works the same.

**How do I fade the data vs. the map?**
The **OSM transparency slider**. Set the value a new map window opens with in
**Preferences ▸ Display ▸ Initial map transparency**.

---

## Gauges & basin

**"Gauge is not inside the basin!"**
The Gauges point falls outside the catchment mask. Fix it with **Tools ▸ Set max Gauge**
(sets it to the largest-upstream cell inside the mask), or open **Tools ▸ Show Basin**,
click a point and **Copy Gauge**. The Gauges field is blue when all gauges are inside,
red when any is outside.

**"PathOut does not exist!"**
Use **Tools ▸ Create PathOut Folder**.

---

## Analysing results

**Which file do I open for each viewer?**

| Viewer | File |
|--------|------|
| Analyse ▸ Timeseries | a result `.csv` (e.g. `discharge_daily.csv`) |
| Analyse ▸ NetCDF | a result `.nc` |
| Analyse ▸ Watercycle ▸ Watercycle / Flow Diagram / Chord Analysis | the WaterCycle csv (`WaterCycle_areasum_daily.csv`, a monthly or annual one works too) |
| Analyse ▸ Watercycle ▸ Mean Weekly Fluxes / Annual bars | a **daily** WaterCycle or WaterBalance csv |
| Analyse ▸ Full Waterbalance | `WaterBalance_areasum_daily.csv` |

Or just use **Analyse ▸ Output Explorer** and double-click — it opens the right viewer.

**There is no WaterCycle / WaterBalance csv in my output folder.**
CWatM only writes it when the settings ask for it. **Tools ▸ Add output Watercycle**
(or **Add output WaterBalance**) adds the line `OUT_TSS_AreaSum_Daily = WaterCycle`
(`= WaterBalance`) under `[OUTPUT]`; save and run again.

**The Watercycle entries are missing from the Analyse menu.**
At the *Beginner* skill level only **Analyse ▸ Watercycle ▸ Watercycle** is shown; switch
to *Advanced* or *Expert* for Flow Diagram, Chord Analysis, Mean Weekly Fluxes, Annual
bars and Full Waterbalance.

**How do I choose what Mean Weekly Fluxes or Annual bars show?**
The **⚙ gear** top right. Every tick applies at once and is remembered (each window keeps
its own choice). A component that is not in your csv is greyed out — e.g. withdrawals
when water demand was off, or most components in a WaterCycle csv compared with a
WaterBalance csv.

**Annual bars shows fewer years than my run.**
Only **complete** years inside the slider period get a bar; a year cut by the start or
end of the run (or of the slider) is left out, so the bars stay comparable.

**What is "Fossil groundwater" in the water balance?**
When a run does not limit abstraction (`limitAbstraction = False`), the demand the model
could not meet from the available water is still taken — from an unlimited source. The
Watercycle views show it as an input *Fossil groundwater* (Sankey: *Other source*), and
what of it is lost as *Unmet demand lost*.

**How do I compare a run against observations?**
In the **Timeseries** window press **Load observed** (a CWatM `.csv` or a simple
`date,value.csv`). It overlays the observed line and shows **KGE / NSE / PBIAS / RMSE**.
Drag the **range slider** under the plot to compute the metrics over just that period.

**How do I compare two scenarios?**
Two NetCDF results: **NetCDF ▸ Action ▸ Compare A−B** shows the difference map per
timestep. Two csv results: **Timeseries ▸ Compare**. Several runs at once: mark them in
the **Journal of Runs** (or the Batch Run table) and press **Compare results**.

**NetCDF ▸ Total Timeseries is very slow.**
Reading one grid cell across *every* timestep is one disk read per timestep, so a long
run takes a while (a progress bar with **Cancel** shows). Use **Fast Display Timeserie**
for a quick look with gaps; use **Total Timeseries** when you need every day (e.g. to
Save as csv).

**Can I get one map of the mean (or the median) over the whole run?**
**NetCDF ▸ Action ▸ Calculate mean** / **Calculate percentile** (50 = median) write a new
NetCDF next to the original and show it. **Save as a .tif** writes the shown map as a
GeoTIFF.

**The little animal on the discharge plot — what is it?**
Just a cameo on the live sparkline during a run. Pick which one in
**Preferences ▸ Display ▸ Select animal** — the Trout and the Bottle are free, the others
come from the Shop (see below).

---

## Check Data

**Does the GUI freeze while the check runs?**
No — the check runs in the background and the window (and the rest of the GUI) stays
usable, with the elapsed time shown. It reads every input file, so on a network drive it
takes a while. There is no Stop: CWatM's check has no break point, so it runs to the end.

**Where is the output?**
In the **log pane below the table** — CWatM's messages and the full traceback of a
failure appear there.

**It says my settings file has unsaved changes.**
CWatM reads the settings **from disk**, so an unsaved editor would be checked in its
saved state — a different file than the one you see. Save first (offered in the prompt),
or continue knowingly.

**Run Check is greyed out.**
Your **MaskMap is a coordinate**, and CWatM's check mode needs a MaskMap **map file**.
The tooltip on the button says so with the value it found.

**How do I find the problem rows?**
Rows with a problem are tinted across their full width and counted above the table
(*"312 rows · 7 not valid · 3 date mismatches"*). **Select trouble** keeps only those,
the **filter box** narrows further, columns are **sortable**, and a **double-click on a
row jumps to that key** in the settings editor.

**Where is the result csv?**
`<PathOut>/check_cwatm1.csv` by default (change it with *Save result file as .csv*).
**Copy Table** and **Export CSV** take exactly the rows currently shown.

---

## Reading a result file's settings (Restore settingsfile)

**Which settings produced this output file?**
Open it with **Tools ▸ Restore settingsfile** — CWatM stores the complete settings file
and the input-file list inside every discharge/ET output. The summary card names the
title, run time, CWatM version and settings file; **Preview settingsfile** shows the
stored file read-only before you change anything.

**How is it different from what I have now?**
**Compare with current** diffs the stored settings against your loaded ones side by side.

**I want it back without losing my current file.**
Either **Restore settingsfile** (writes a new `<title>_<date>.ini` and loads it) or, from
the preview, **Load into editor (unsaved)** — nothing is written to disk and one
**Ctrl+Z** takes it back.

**Are my input files still the ones that run used?**
**Show Inputfiles** checks each recorded file: **missing** (red), **changed since the
run** (orange, with the file's current time stamp) or unchanged. Double-click a file to
open it — a NetCDF opens in the map viewer.

**Which run wrote this file?**
**Show in Journal** jumps to it in the Journal of Runs.

---

## Runs history (Journal of Runs)

**Where is my run history?**
**RUN CWATM ▸ Journal of Runs** — every run (main, Windowed, Batch) is logged with time,
Title, PathOut, duration and last discharge. **Open results** shows its output folder,
**Load settings** reopens the exact file that ran, **Re-run** starts it again, and
**Show log** opens its output log.

**Compare settings is greyed out.**
Mark **exactly two** runs (Ctrl/Shift+click); it then diffs the settings each run
actually used (a snapshot is kept per run, so the diff is right even if you edited the
file afterwards).

**How do I find one run among hundreds?**
The **filter box** (Title, PathOut, settings file, date), sorting by any column, and the
**Note** column — double-click it and write e.g. *"calibration attempt 3"*.

**Where is it stored / how long is it kept?**
**Preferences ▸ Run History** (folder and retention; default: keep 60 days under
`%LOCALAPPDATA%\CWatM_GUI`).

---

## Excel sheets

**Tools ▸ Excel Crops/Reservoirs is greyed out.**
Your settings file has no `Excel_settings_file` key — the editor opens the workbook that
key names.

**Tools ▸ Excel Crops/Reservoirs won't save.**
Close the workbook in Excel first — a file open in Excel is locked, and the editor shows
an error. Every other sheet and all styling is preserved when it saves.

**Where is the Reservoirs_downstream sheet?**
On its own **tab below the table**, together with every other sheet of the workbook.

**I edited two sheets — does Save write both?**
Yes. Save / Save As write every sheet you touched; a sheet with unsaved edits shows a
`*` on its tab. Closing the window while a `*` is showing asks Save / Discard / Cancel,
so edits are never lost by closing.

**I deleted the wrong column — can I get it back?**
Press **Ctrl+Z** (or the ↶ button in the symbol bar). Undo covers cell edits, pastes,
fills, clears and whole inserted/deleted columns and rows, up to 200 steps per sheet,
and still works after a Save. The only exception is a deletion far too large to hold in
memory — the confirmation warns you when that is the case, and then **Reload**
(discarding all edits) is the way back.

**My typed formula stayed as text.**
A formula is recognised by a leading `=` (always), or when it is made only of numbers,
cell references (`I3`), operators and known functions — `2 + I3` computes, `Winter 3`
does not. Numbers joined by `-` or `/` (`1-2`, `2026-08-13`) are kept as typed (ids,
ranges, dates). Use the `=` form when in doubt. A leading `'` forces text on purpose.

**The cell shows `#NAME?` / `#CYCLE` / `#DIV/0!`.**
`#NAME?` = unknown function or name, `#CYCLE` = the formula refers back to itself,
`#DIV/0!` = division by zero, `#SYNTAX` = it could not be parsed, `#VALUE!` = a
referenced cell is text where a number is needed.

**Will my formulas be in the saved file?**
No — the **computed value** is saved. CWatM reads these sheets with pandas/openpyxl,
which would see a formula as text rather than a number. The formulas stay live (and
recalculate) as long as the window is open.

**Nothing happens when I drag the fill handle far down.**
Keep the mouse button held near the bottom edge — the table scrolls while you drag.
Filling copies displayed values; a filled formula becomes its value, references are not
shifted.

**Dragging one cell down repeats it instead of counting up.**
That is on purpose: a single cell fills **its own value** into the rest. Select two
cells that show the step you want (`1, 3` or `Crop1, Crop2`) and drag from those to get
a series.

**I inserted or deleted a column — do my formulas follow?**
No. Inserting and deleting move the cells and their formatting, but formulas and merged
ranges are not re-pointed to their new position — check the formulas around the change.
**Ctrl+Z** takes the insert or delete back.

**"Paste 1 column left" is greyed out.**
Its tooltip says why. Either the clipboard holds a **row** (a row cannot be pasted as a
column — use the row header), or the column was copied from **another sheet**, into
which it cannot be pasted back. A plain block of copied cells is never restricted.

**Ctrl+C on a column I selected doesn't count as copying the column.**
That is intended: a full column or row is only copied with **Copy column / Copy row in
the header's right-click menu**. Ctrl+C copies the selected cells as a plain block, which
you can paste anywhere.

---

## MODFLOW coupling

**My MODFLOW run fails.**
The coupling needs the `xmipy` and `flopy` Python packages **and** the compiled MODFLOW
6 library (`libmf6.dll`) whose path you set in the settings (`path_mf6dll`) — the GUI
does not ship the DLL. Make sure `modflow_coupling = True` and the
`[GROUNDWATER_MODFLOW]` paths are set; **Check settingsfile** (F4) marks the
`modflow_coupling` line when a key it needs is missing.

**Do I have to switch MODFLOW on somewhere in the GUI?**
No. A run with `modflow_coupling = True` loads `flopy` and `xmipy` by itself (in the
installed version too); the GUI never loads them, so its startup is not affected.

---

## CWatM AI (NotebookLM chat)

**How do I log in?**
Click **Login**, choose Microsoft Edge or Google Chrome, and sign in on Google's page that
opens in that browser. No browser cookies are read and no administrator rights are
needed.

**"Login" even though I signed in.**
The session expired; the GUI verifies the login in the background and prompts you to
re-authenticate — click **Login** and sign in again.

**Can I use my own notebook?**
Yes: **Preferences ▸ Editor & Dates ▸ NotebookLM** (or the window's *Notebook…*
button) takes a notebook link or id. Empty = the openly available CWatM notebook.

---

## CWatM Academy, account and Shop

**What is CWatM Academy?**
A guided introduction in levels — the **CWatM Academy** button in the menu bar. It works
without a login; **Preferences ▸ CWatM Academy** opens it at every start until you turn
that off. It switches the skill level to *Beginner*; switch back any time.

**Do I need an account?**
No. CWatM, the GUI, every skill level and the Academy work fully without one. Logged in
(the account button in the menu bar's right corner), full runs with a new model setup and
finished Academy levels earn **points**, and points earn **river badges**.

**Why did my run not earn a point?**
A point needs a **successful full run** with a model setup you have not been awarded for
yet (changing only the Title, PathOut or outputs does not count as new), *Count my full
CWatM runs* on in **Preferences ▸ Account**, and there is a daily cap. The output box
says why a run did not count.

**I cannot select an animal.**
The **Trout** and the **Bottle** are free for everyone; the others are bought in the
**Shop** (its button appears once you hold the *Breg* badge), and the **Mole** is the
reward for the first successful run coupled with MODFLOW.

**My points went down.**
Without a login for a week the points you can spend drop a little (3 %, then 5 % a week,
never below 5). Logging in stops it. Points *earned in total* and your badges never go
down.

**What is stored about me?**
See **Help ▸ CWatM account privacy**.

---

## Running on Linux

**Can I run the GUI on Linux?**
Yes, from source (the `.exe` and the installer are Windows-only). The full guide —
system packages per distro, the venv, remote displays and troubleshooting — is
**`cwatm_gui_linux.md`** in the program folder. In short:
`python3 -m venv venv2` → `. venv2/bin/activate` →
`pip install --only-binary=:all: -r requirements.txt` → `./gui.sh` (`chmod +x gui.sh`
once). Use **`gui.sh`** rather than calling python directly if your display is
forwarded (Xming, X2Go, VNC): it sets the software-rendering variables the map and
plot windows need — those are Chromium, and on a forwarded X11 display without them
they come up blank. `CWATM_GUI_SOFTWARE_GL=0 ./gui.sh` turns that off on a local
desktop. `./gui.sh --check` diagnoses the whole environment. To run only the model,
with no GUI at all: `python cwatm_model.py settings.ini`.

**Linux: "Could not load the Qt platform plugin xcb".**
Qt 6.5+ needs a few X11 system libraries that no pip package can provide — most often
`libxcb-cursor0`. Install them (`sudo apt install libxcb-cursor0 libxcb-xinerama0
libxkbcommon-x11-0 libegl1 libgl1 libfontconfig1 libdbus-1-3`, or on RHEL/Fedora
`sudo dnf install xcb-util-cursor xcb-util-wm xcb-util-keysyms libxkbcommon-x11
mesa-libEGL mesa-libGL fontconfig dbus-libs`). `./gui.sh` checks this for you and lists
every missing library by name. Without root you can unpack the packages under your home
directory and export `LD_LIBRARY_PATH` — see `cwatm_gui_linux.md`.

**Linux/Xming: "X server does not support XInput 2", "failed to get the current screen
resources", "Cannot create platform OpenGL context".**
The first two are Xming telling you it has no XInput2 and no XRandR — warnings, the GUI
runs; but the missing XRandR means Qt cannot read the screen layout, which is why
maximizing behaves oddly there. The third comes from GL being switched off in the xcb
plugin (`CWATM_GUI_XCB_NO_GL=1`) or from an X server without GLX; harmless for the main
window, fatal for the map/plot views. **A newer X server fixes all three**: VcXsrv is
the maintained successor to Xming (XRandR, GLX, better large-window handling), and
X2Go/VNC are better still. Otherwise run `CWATM_GUI_NO_MAXIMIZE=1 ./gui.sh`.

**Linux/Xming: the window disappears when I maximize it.**
The X server could not allocate a backing store the size of the whole desktop, so the
window is gone (usually with `BadAlloc` on the terminal). Start the GUI windowed and
resize it by hand:

    CWATM_GUI_NO_MAXIMIZE=1 ./gui.sh

`gui.sh` also switches off Qt's shared-memory path (`QT_X11_NO_MITSHM`) whenever the
display is not local, which is the other common cause of a window dying on resize. If it
persists, run Xming in **Multiple windows** mode (it provides a window manager) rather
than *One large window*, or use X2Go/VNC, which handle large windows far better than
plain X11 forwarding. Run from a terminal and keep the output — the last lines say
whether it was an X error or a crash.

**Linux: an import fails with "undefined symbol" (`ffi_type_uint32`,
`krb5_ser_context_init`, …).**
Two copies of one system library are in play — the distribution's and one bundled in a
Python wheel (rasterio ships curl/krb5) or in a conda environment. Load the system ones
first: `CWATM_GUI_PRELOAD_SYSLIBS=1 ./gui.sh`, or put the `LD_PRELOAD` line that
`./gui.sh --check` prints into your `~/.bashrc`. Details in `cwatm_gui_linux.md` §7.

**Linux: the map/plot windows say "unavailable — undefined symbol: ffi_type_uint32".**
The maps and plots run in QtWebEngine, which loads the system `libwayland-server`; that
needs symbols from your distribution's `libffi`, and another `libffi` is winning the
load order (usually a conda environment, or a package you unpacked into
`LD_LIBRARY_PATH`). Put the system one first:

    CWATM_GUI_PRELOAD_FFI=1 ./gui.sh          # or: export LD_PRELOAD=/lib/x86_64-linux-gnu/libffi.so.8

`./gui.sh --check` reports this and tells you which library it would preload. To see who
supplies the competing copy:
`LD_DEBUG=libs venv2/bin/python -c 'import PySide6.QtWebEngineWidgets' 2>&1 | grep -i ffi`.

---

## General

**Nothing happened when I clicked something.**
Check the diagnostic log: `%LOCALAPPDATA%\CWatM_GUI\gui.log` (swallowed errors are
recorded there).

**Where are all the settings of the GUI?**
**Configure ▸ Preferences…** (Ctrl+, or the **⋮** button at the right of the menu bar).
Nothing changes until **Apply** or **OK**; **Cancel** discards what you have not applied.

**How do I change the look?**
**Preferences ▸ Display ▸ Mode** — Normal (light), Dark, or Mikhail (black + amber). It
switches live and is remembered. **Show Header** hides the banner at the top for more
room.

**Can I have the GUI in my language?**
**Preferences ▸ Display ▸ Language** — English, Deutsch, Français, Español, Italiano,
Magyar, Română, Srpski, Hrvatski, Slovenčina, Български, Čeština, Українська, 简体中文
(Simplified Chinese). Menus, buttons, labels and tooltips switch at once; messages,
window titles and the settings file stay in English.

**Linux: Chinese characters show as boxes.**
No Chinese font is installed. Install one, e.g. `sudo apt install fonts-noto-cjk`
(RHEL/Fedora: `sudo dnf install google-noto-sans-cjk-fonts`), and restart the GUI.
Windows always has one (Microsoft YaHei).

**How many decimals are shown?**
**Preferences ▸ Display ▸ Show decimals** (default 3) — applies across the live
discharge, map read-outs and point labels.

**Can I associate `.ini` files with the GUI?**
Yes — `CWatM_GUI.exe <settings.ini>` loads that file at startup, so "Open with" and
drag-and-drop onto the window both work. Tick **Preferences ▸ Startup & Model ▸ Load
previous settings at start** to reopen your last files (all tabs) automatically.
