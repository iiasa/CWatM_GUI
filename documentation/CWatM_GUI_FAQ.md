# CWatM GUI — FAQ & Troubleshooting

Short answers to the questions that come up most often. For a full feature tour see
**CWatM_GUI_Features.md**; for the developer reference see **CLAUDE.md**.

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

**How do I stop a run?**
Press **RUN CWATM** again (it reads **STOP CWatM** while running). Because the model
runs in its **own process**, Stop is an immediate kill — it works even if the model is
stuck in C code.

**The run crashes partway through with a date/time error.**
Usually the run window extends past your forcing data. Check that **StepEnd** is within
the time range of your meteo/forcing NetCDFs, and that `StepStart ≤ SpinUp ≤ StepEnd`
(F4 now flags the ordering).

**Can I run several things at once?**
Yes. **RUN CWATM ▸ Hidden Run CWatM** opens independent run windows (each its own
process), and **RUN CWATM ▸ Batch Run…** runs many scenarios, up to N in parallel. The
main GUI stays usable throughout.

**Where does the output go?**
To the resolved **PathOut**. Open it quickly with **Analyse ▸ Open PathOut Folder** or
browse/open results with **Analyse ▸ Output Explorer**. If PathOut doesn't exist, use
**Tools ▸ Create PathOut Folder** (Batch Run creates each scenario's folder itself).

---

## The settings editor

**A line is red — what does that mean?**
- **Strong red** = a **duplicate keyword** (the same key defined twice; the later one
  silently wins). *Note:* the stock Morava settings legitimately shows the `PathSoil`
  pair red — it really is an override.
- **Light red** = **Check settingsfile** (F4) flagged a **missing file/path**. Clear
  these marks with **Clear checking** (Shift+F4).

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

**SpinUp / StepEnd is a number, not a date — is that OK?**
Yes. An integer is a **timestep count** (StepStart = timestep 1). The date fields show
the computed date.

---

## Maps (Show Basin, NetCDF)

**The map is blank or very slow.**
The maps need WebGL, which the GUI runs in **software** mode (SwiftShader) so it works on
any machine. First open can take a moment. If it stays blank, check `gui.log`. Behind a
corporate proxy the GUI fetches OSM tiles itself (Python), so a proxy that blocks the
browser engine is not a problem — but a fully offline machine shows the data overlays
over a white background (no basemap), which is expected.

**The basemap doesn't line up / is missing.**
The viewers use **EPSG:4326 WMS** basemaps (not the usual web tiles) so they align with
CWatM's lon/lat grids. Pick a different basemap from the selector, or set a default in
**Configure ▸ Default openstreet map**.

**How do I fade the data vs. the map?**
The **transparency slider**: 0% = only the data (basemap hidden), 100% = basemap fully
visible with the data 50% on top. Set the opening value in **Configure ▸ Transparency**.

---

## Gauges & basin

**"Gauge is not inside the basin!"**
The Gauges point falls outside the catchment mask. Fix it with **Tools ▸ Set Gauge**
(snaps to the largest-upstream cell inside the mask), or open **Tools ▸ Show Basin**,
click a point and **Copy Gauge**. The Gauges field is blue when all gauges are inside,
red when any is outside.

**"PathOut does not exist!"**
Use **Tools ▸ Create PathOut Folder**.

---

## Excel sheets

**Excel ▸ Crops / Reservoirs won't save.**
Close the workbook in Excel first — a file open in Excel is locked, and the editor shows
a friendly error. Only the cells you changed are written back; every other sheet and all
styling is preserved.

**The Release button is greyed out.**
It only enables when the `Reservoirs_downstream` companion sheet exists in the workbook.

---

## Analysing results

**Which file do I open for each viewer?**
- **Timeseries** — a result `.csv` (e.g. `discharge_daily.csv`).
- **NetCDF** — a result `.nc`.
- **Watercycle / Flow Diagram** — `WaterCycle_areasum_monthtot.csv`.
- Or just use **Analyse ▸ Output Explorer** and double-click — it opens the right viewer.

**How do I compare a run against observations?**
In the **Timeseries** window press **Load observed** (a CWatM `.csv` or a simple
`date,value.csv`). It overlays the observed line and shows **KGE / NSE / PBIAS / RMSE**.
Drag the **range slider** under the plot to compute the metrics over just that period.

**NetCDF ▸ Total Timeseries is very slow.**
Reading one grid cell across *every* timestep is one disk read per timestep, so a long
run takes a while (a progress bar shows). Use **Fast Display Timeserie** for a quick look
with gaps; use **Total Timeseries** when you need every day (e.g. to Save as csv).

**The little animal on the discharge plot — what is it?**
Just a cameo on the live sparkline during a run. Pick which one in
**Configure ▸ Select animal**.

---

## Runs history (Run Ledger)

**Where is my run history?**
**Tools ▸ Run Ledger** — every run (main, Hidden, Batch) is logged with time, Title,
PathOut, duration and last discharge. Double-click **Open results**, or **Load settings**
to reopen the exact file that ran.

**Compare settings is greyed out.**
Mark **exactly two** runs (Ctrl/Shift+click); the button turns blue and diffs the
settings each run actually used (a snapshot is kept per run, so the diff is right even if
you edited the file afterwards).

**Where is it stored / how long is it kept?**
**Configure ▸ Run history folder…** and **Run history retention…** (default: keep 60
days under `%LOCALAPPDATA%\CWatM_GUI`).

---

## MODFLOW coupling

**My MODFLOW run fails.**
The coupling needs the `xmipy` and `flopy` Python packages **and** the compiled MODFLOW
6 library (`libmf6.dll`) whose path you set in the settings — the GUI does not ship the
DLL. Make sure `modflow_coupling = True` and the `[GROUNDWATER_MODFLOW]` paths are set.

**Startup feels slower after enabling MODFLOW.**
Turn on **Configure ▸ Use Modflow** only when you need it — when on, the GUI pre-loads
flopy (heavy) so MODFLOW use is ready; when off it isn't loaded, keeping startup fast.

---

## CWatM AI (NotebookLM chat)

**Login…**
- **From Firefox** works without special rights.
- **From Chrome / Edge / Opera**: run CWatM GUI **as administrator** once first —
  Windows encrypts those browsers' cookies.
- The interactive **Google login window** is available only when running from source.

**"Login required" even though I signed in.**
The session expired; the GUI verifies the login in the background and prompts you to
re-authenticate. This feature is source-run only; a frozen build shows a friendly message
instead of crashing.

---

## General

**Nothing happened when I clicked something.**
Check the diagnostic log: `%LOCALAPPDATA%\CWatM_GUI\gui.log` (swallowed errors are
recorded there).

**How do I change the look?**
**Configure ▸ Mode** — Normal (light), Dark, or Mikhail (black + amber). It switches
live and is remembered.

**How many decimals are shown?**
**Configure ▸ Show Decimals** (default 3) — applies across the live discharge, map
read-outs and point labels.

**Can I associate `.ini` files with the GUI?**
Yes — `CWatM_GUI.exe <settings.ini>` loads that file at startup, so "Open with" and
drag-and-drop onto the window both work. Tick **Configure ▸ Load previous settings at
start** to reopen your last file automatically.
