# CWatM GUI 1.04 — what is new

*Released 10 August 2026. Previous release: 1.03 (7 August 2026).*

Two areas changed in this release: the **Excel workbook editor** moved and grew up, and
the **Batch Run** was rebuilt around not losing work.

---

## 1. Excel workbook editor — now in Tools, and much closer to Excel

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

## 2. Batch Run — safer, and useful for comparing scenarios

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

## Also in this release

- **Opening a file or folder** (Analyse ▸ Open PathOut Folder, the Journal of Runs, Output
  Explorer) now works on Linux and macOS as well, not only Windows.
- **Running on Linux** is documented end to end in `cwatm_gui_linux.md`, together with a
  `gui.sh` launcher that sets up remote-display (Xming/VcXsrv/X2Go) rendering and
  diagnoses a broken environment with `./gui.sh --check`.

## Upgrading

Nothing to do: settings files, run history and preferences are unchanged. The Excel item
has simply moved from the *Excel* menu into **Tools**.

