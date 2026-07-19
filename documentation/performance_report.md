# CWatM GUI — Performance Analysis Report

Read-only audit of `cwatm_gui.py`, `src/gui/**` and `cwatm_gui_dir.spec`.
No source file was modified. The `cwatm/` submodule was read for behaviour only
and is out of scope for fixes (⛔ hard rule in `CLAUDE.md`).

Findings are tagged **[MEASURED]** (a number was collected on this machine) or
**[REASONED]** (derived from reading the code). Anything I could not check is
marked **UNCONFIRMED**.

Environment: Python 3.12.10 (`venv/Scripts/python.exe`), Windows 11, project on a
**mapped network share** (`P:` → `\\pdrive\…`). Import/IO numbers are therefore
pessimistic vs. a local SSD — treat them as upper bounds, but note that this *is*
the environment the app ships into.

---

## Executive summary — top 5 by impact/effort

| # | Finding | Severity | Effort | Anchor |
|---|---------|----------|--------|--------|
| 1 | Analyse/Basin dialogs are parented to the main window and **never destroyed** after `exec()` — every opened NetCDF window leaks its frame list (up to 400 grids) + an unbounded base64-PNG cache + a QWebEngine page | **High** | ~1 line each | `analysis_netcdf.py:109`, `analysis_timeseries.py:80`, `basin_viewer2.py:223` |
| 2 | `build_mask_context` runs the **full CWatM mask routine (`mainwarm -vgm`) synchronously on the GUI thread**, and re-runs it on *every* field edit when it fails (the "unchanged" guard only holds for a successful build) | **High** | ~10 lines | `basin_viewer.py:666`, `main_window.py:776` |
| 3 | `_load` builds up to **400 full grids eagerly** and keeps them for the window's lifetime; Compare A−B holds **two** such lists at once. No dask/chunking, no bbox subsetting | **High** | medium | `analysis_netcdf_base.py:201`, `analysis_netcdf.py:724` |
| 4 | Per-timestep time labels built with **scalar `pd.to_datetime` in a Python loop** — 0.43 s for an 11 000-step file where a vectorised call takes 0.027 s | **Med** | ~3 lines | `analysis_netcdf_base.py:200` |
| 5 | `show_basin2` does NetCDF read + mask generation + **synchronous HTTP downloads** (Leaflet JS/CSS, `timeout=15` each) all on the GUI thread with no progress feedback | **Med** | medium | `basin_viewer2.py:203-223`, `:116` |

The documented fast-startup / lazy-import architecture is **holding up well** —
see §1. The real costs have migrated to the Analyse windows and the gauge-check
path, not to startup.

---

## 1. Startup latency

### 1.1 The lazy-import rule is being respected — [MEASURED] ✅

`main_window.py:9-37` imports only PySide6, stdlib and light GUI modules. All 26
call-site imports of `basin_viewer` / `check_data_window` / `analysis_*` /
`run_ledger` / `hidden_run_window` are inside methods (`main_window.py:779, 842,
859, 1043, 1106, 1219, 1259, 1291, 1366, 2632, 2657, 2665, 2673, 2681, 3094`;
`run_controller.py:34`). No violation found.

Measured import cost of the deferred stack (network share, cold):

| Module | Cost |
|---|---|
| `PySide6.QtWidgets` | 1.86 s |
| `src.gui.components.main_window` (total) | 1.49 – 3.18 s |
| `pandas` | 16.5 s |
| `cwatm.run_cwatm` | 23.9 s |
| `xarray` | 4.79 s |
| `openpyxl` | 6.24 s |
| `folium` | 4.14 s |
| `plotly.graph_objects` | 0.21 s |
| `rasterio` | 0.00 s (already pulled in by `cwatm.run_cwatm`) |

**Deferring ~55 s of imports is what makes this app usable on the share.** Do not
regress it.

### 1.2 `import cwatm.version` at module level — Low — [MEASURED]

`main_window.py:45`. Costs **~68-76 ms** (`-X importtime`), all of it package-dir
resolution for `cwatm/__init__.py` + `cwatm/version.py` on the share. Both files
are pure metadata (no heavy imports), so this is safe — but it is the only
module-level touch of the `cwatm` tree at startup.

**Fix (optional):** read the six `__…__` strings lazily inside the About dialog.
Saves ~70 ms on a network start, ~5 ms locally. Low value; note it only so a
future edit does not turn this into a real `cwatm` import.

### 1.3 Background warm-up warms things most sessions never use — Low/Med — [REASONED]

`cwatm_gui.py:181-189` unconditionally imports `openpyxl` (6.2 s) and `folium`
(4.1 s) in the warm-up thread. Most sessions never open the Excel menu or a map.
Python import machinery holds the GIL while unmarshalling/executing bytecode, so
~10 s of avoidable import work competes with the UI thread during the first
minute.

**Fix:** gate `openpyxl` behind first use of the Excel menu and `folium` behind
first use of Show Basin / NetCDF (both are already lazy at their call sites — this
is only about the *pre*-warm). Keep `pandas` → `cwatm.run_cwatm` → `xarray`
(needed by Run and Check Data, which are the common paths). Effort: ~5 lines.
Risk: first Excel/map click gets slower — acceptable, and it is what already
happens today if the click beats the warm-up.

### 1.4 Work in `CWatMMainWindow.__init__` — Low — [REASONED]

`main_window.py:88-109` probes up to 4 icon paths with `os.path.exists` +
`QIcon()` construction; `create_header` (`:230`, `:267`) loads and rescales
`cwatm.ico` and `iiasa-logo.svg` (SVG rasterisation). Three separate
`QApplication.primaryScreen().availableGeometry()` calls (`:209`, `:242`, `:712`).
All are single-digit ms. Not worth changing; listed for completeness so it is not
re-investigated.

### 1.5 `_prewarm_webengine` is well placed — ✅

`cwatm_gui.py:328` fires at T+1500 ms on the GUI thread (correct — Qt widgets are
not thread-safe) and keeps the view referenced so the render process is not torn
down. Good as-is.

---

## 2. UI responsiveness / event-loop blocking

### 2.1 `mainwarm -vgm` on the GUI thread — **High** — [REASONED]

`basin_viewer.py:644-685`. For a **coordinate-based** MaskMap the gauge check
writes a temp `.ini` (`:661`) and calls `run_cwatm.mainwarm(run_file, ["-vgm"], [])`
(`:666`) — a full CWatM mask-generation run — **synchronously**, plus a whole
`ups.nc` read via `_load_netcdf_data` (`basin_viewer.py:772`).

This is reached from `_update_warnings` → `_rebuild_mask_cache`
(`main_window.py:800 → 769`), which runs on load, on Save/Save As, after the
500 ms field-edit debounce (`main_window.py:2591`) and after an undo/redo
(`main_window.py:2529`). The window is frozen for the whole duration with no
cursor change and no status message.

**Compounding bug — the cache guard is one-sided.** `main_window.py:776`:

```python
if not force and self._mask_context is not None and maskmap == self._mask_context_key:
    return
```

When `build_mask_context` returns `None` (mask cannot be built — a very common
state while the user is mid-typing a MaskMap value, or when `ups.nc` is missing),
`self._mask_context` stays `None`, so the guard **never fires** and the full
tempfile + `mainwarm` path re-runs on *every* subsequent `_update_warnings` call.
The status hint at `:786` confirms the failure case is expected, but the caching
does not cover it.

**Fix:**
1. Cache the key unconditionally — set `self._mask_context_key = maskmap` and add
   a `self._mask_context_built = True` sentinel so a `None` result is also cached.
   *(~4 lines, no invariant risk, fixes the repeat-storm on its own.)*
2. Move the coordinate-MaskMap branch to a `QThread`/`QRunnable` that emits the
   context back; grey the Gauges field while it runs. *(~40 lines. Risk: the
   documented "check is always based on the current left-window boxes"
   invariant must be preserved — the worker must be handed the `_live_content()`
   snapshot, and a newer request must supersede an in-flight one.)*

Do (1) first; it is cheap and removes most of the pain.

### 2.2 `show_basin2` — full load + network fetch on the GUI thread — **Med** — [REASONED]

`basin_viewer2.py:203-223` runs, in order and all blocking:
`_load_netcdf_data` (whole ups grid), `_load_mask_data` (→ §2.1's `mainwarm`),
folium page build, then `_inline_remote_assets` (`:170`) which issues synchronous
`requests` GETs for every remote `<script src>` / `<link href>`
(`_dl_bytes`, `:116`, `timeout=15` each). On a cold `%TEMP%\cwatm_web` cache
behind a slow proxy this is easily 15-60 s of frozen window.

**Fix:** show a modal progress dialog (or move the load into a worker) and add a
short-circuit that skips inlining when the cache dir is already populated. Also
`_dl_bytes` re-reads the cached file from disk on every call (`:128`) — a small
in-memory `dict` keyed by URL would remove repeat disk hits for the same assets
within a session. Effort: ~20 lines for the memo, medium for the worker.

### 2.3 Blocking waits on the GUI thread — Med — [REASONED]

| Call | Max block | Anchor |
|---|---|---|
| `process.waitForFinished(3000)` on Stop | 3 s | `cwatm_process_worker.py:134` |
| `worker.wait(5000)` then `wait(2000)` (in-process fallback) | 7 s | `run_controller.py:429, 437` |
| `worker.wait(4000)` in NetCDF `closeEvent` | 4 s | `analysis_netcdf.py:1085` |

The subprocess `kill()` normally returns in ms, so `:134` rarely bites; the
in-process path (`run/subprocess` off, not exposed in the menu) can freeze the app
for 7 s on Stop. Acceptable for a non-default path — flag, don't fix.

### 2.4 `gc.get_objects()` heap walks after an interrupted run — Med — [REASONED]

`run_controller.py:496` and `:539` each walk the **entire Python heap** with an
`isinstance` test per object. After a CWatM run in the in-process mode the heap
holds millions of numpy/xarray objects; this is seconds of frozen UI, run twice
(`cleanup_file_operations` calls both, `:477`/`:480`), plus a `gc.collect()`
(`:483`).

Correctly **skipped for the subprocess path** (`run_controller.py:306` guards
`on_cwatm_error`) — good design. But `stop_cwatm_execution` calls
`cleanup_file_operations()` unconditionally at `:418` and again at `:443` in the
in-process branch. Only the non-default path is affected; low priority.

### 2.5 Debouncing is present and correct — ✅

`_field_update_timer` 500 ms (`main_window.py:140-143`), editor change-highlight
120 ms (`settings_editor.py:122-126`), output box 150 ms
(`main_window.py:132-134`). Well done — no missing debounce found.

---

## 3. Hot paths during a run

### 3.1 Output box append path — ✅ well engineered

`output_box.py:36-129`. Per-line cost is: a `strip()`, a `startswith('\r')` test,
one buffered file `write()` (no flush — flushed once per 150 ms tick at `:90`),
and an append to a Python list. Consecutive progress lines are **coalesced in the
queue** (`:74-75`) so only the newest is ever rendered. The document is capped at
5000 blocks via `maximumBlockCount`. Rendering happens inside one
`beginEditBlock`/`endEditBlock` (`:113`/`:126`). This is the right design; I found
nothing to improve.

One micro-nit: `theme.qcolor(...)` and two `QTextCharFormat()` are constructed on
every flush (`:106-110`) — ~7/s during a run, negligible.

### 3.2 Discharge sparkline repaint — Low — [REASONED]

`discharge_sparkline.py:112-118`. `add_value` calls `self.update()` per timestep.
Qt coalesces `update()` into one paint per event-loop pass, so this does **not**
cause per-timestep repaints. `_trim` (`:120`) rebuilds the point list on every
sample — O(n) with n ≈ 92 for a daily run; irrelevant.

`paintEvent` (`:188-193`) draws each segment with a fresh `QColor` + `QPen` per
segment. Bounded by `_MAX_POINTS = 4000` (`:72`), which is only reached for
sub-daily runs — 4000 individual `drawLine` calls with antialiasing at ~7 fps is
noticeable but not fatal.

**Fix (optional):** batch segments into a handful of alpha buckets and use
`drawPolyline` per bucket. ~15 lines. Only worth it if sub-daily runs matter.

### 3.3 `_animal_timer` runs forever — Low — [REASONED]

`discharge_sparkline.py:86-89` starts a 600 ms `QTimer` in `__init__` and never
stops it. It ticks for the whole application lifetime even with no run active and
an empty plot, and `_tick_animal` (`:96`) can call `update()` on an empty widget.
Cost is trivial; the real objection is that it defeats Windows timer coalescing /
idle power states.

**Fix:** start it in `clear()` / on first `add_value`, stop it when the run ends.
~5 lines. No behavioural change.

### 3.4 Progress clock — ✅

`progress_clock.py:41-51`, `:61-118`. `setValue` → `update()` (coalesced). Paint
is a fixed handful of primitives on a 240×240 widget. `theme.qcolor()` per paint
is a dict lookup + `QColor()` construction — fine. No issue.

### 3.5 Subprocess stdout drain — ✅

`cwatm_process_worker.py:137-179`. `_stdout_buf` is truncated to the held-back
tail on every drain (`:178`), so the `+=` concat stays O(chunk). `re.split` uses
the compiled-pattern cache. Correct.

---

## 4. Editor performance

### 4.1 Gutter iterates hidden blocks to the end of the document — **Med** — [REASONED, UNCONFIRMED at runtime]

`line_number_gutter.py:42-57`. `_visible_blocks` walks `block.next()` and breaks
only when `y > self.height()`. A **folded** block has zero bounding height, so `y`
does not advance across it — the loop therefore continues through every hidden
block. With *Fold All* on a ~1500-line settings file, each gutter paint iterates
~1500 blocks instead of the ~50 on screen.

That paint is triggered on **every keystroke and every cursor move**:
`:32` `editor.textChanged.connect(self.update)` and `:33`
`cursorPositionChanged.connect(self.update)`.

**Fix:** break out of the loop once a *visible* block has been seen and the
running `y` exceeds the widget height — or track the last visible block's bottom
separately from `y`. ~5 lines.
*I could not measure this without a live session; the reasoning follows directly
from `QPlainTextEdit::blockBoundingGeometry` returning zero height for
`setVisible(False)` blocks, which is how folding is implemented here
(`settings_editor.py:535`).* Mark UNCONFIRMED.

### 4.2 `_section_spans()` recomputed 2-3× per fold operation — Low — [REASONED]

`settings_editor.py:484-501` walks the whole document. Callers:
- `apply_folds` (`:530`) then `section_names()` (`:537`) → **two** full walks;
- `fold_all` (`:520`) calls `section_names()` → `_section_spans()`, then
  `apply_folds` walks it twice more → **three** walks per Fold All;
- `folded_sections` (`:509`), `_set_folded` (`:544`), `reveal_cursor` (`:588`).

For a 1500-line file that is ~4500 block hops per Fold All. Perceptible only on
very large files.

**Fix:** memoise `_section_spans` keyed on `document().revision()`, invalidated in
`_on_contents_change`. ~10 lines. No invariant risk (folding semantics unchanged).

Same file, same pattern: `apply_folds` (`:533`) and `_set_folded` (`:548`) call
`doc.findBlockByNumber(n)` inside the loop instead of chaining `blk.next()` —
turns an O(1) walk into O(n) lookups.

### 4.3 One `ExtraSelection` per highlighted row — Med — [REASONED]

`settings_editor.py:392-405`. `_add` appends one `QTextEdit.ExtraSelection` (each
with its own `QTextCursor`) per row, and all six categories are unioned into a
single `setExtraSelections` call (`:419`). Qt re-scans the extra-selection list on
every viewport paint.

Worst case is the **Compare settings** window, where `_diff_rows` + `_filler_rows`
can cover most of both files — hundreds to low-thousands of selections per pane,
re-applied on every `set_*_rows` call (`:192, 198, 204, 210` each call
`_recompute_change_highlights` in full).

**Fix:** merge contiguous row runs into a single selection (`FullWidthSelection`
already spans the line, so a multi-block cursor renders identically). Typical diff
blocks are contiguous, so this collapses hundreds of selections into tens.
~15 lines. Risk: verify the documented colour **priority order**
(changed < error < duplicate < diff < filler < current-diff) still holds after
merging — do the merge *within* each category, not across.

### 4.4 The debounced diff itself — ✅

`settings_editor.py:371-423`: `difflib.SequenceMatcher(autojunk=False)` +
`_duplicate_key_rows` over the whole file every 120 ms while typing. For a
settings file of 500-2000 lines this is sub-millisecond. Fine as-is. (Would matter
at 100 k lines — not a realistic `.ini`.)

### 4.5 `format_content_for_display` is dead code — [MEASURED]

`config_parser.py:78-112`. Grepped the whole tree: **defined, never called**
(the editor became plain-text in §3.2). 35 lines of HTML string-building that can
be deleted. Not a perf win — a maintenance one; flagging so it is not "optimised".

---

## 5. Data / plot windows

### 5.1 Frames are loaded eagerly and never released — **High** — [REASONED]

`analysis_netcdf_base.py:186-209`. `_load` loops over up to `_MAX_FRAMES = 400`
strided timesteps and materialises each as a full `float32` grid (`:202-204`).
There is **no dask chunking and no bounding-box subsetting** — the whole spatial
extent of every frame is read and kept.

Memory: 400 frames × H×W×4 bytes. A 400×300 grid ≈ 192 MB; a 1000×1000 grid
≈ **1.6 GB**.

The base module's own docstring claims *"The frame list itself is released after
rendering (see `_show_map`, report §3.4)"* (`analysis_netcdf_base.py:185-186`) —
but `analysis_netcdf.py:198` (`z = self.frames[ti]`) and `:811`
(`float(self.frames[self._ti][lati, loni])`) read `self.frames` for the whole
window lifetime. **The docstring is stale; the frames are not released.**

Compare A−B is worse: `_compare` keeps A in `self._orig["frames"]` (`:724`) while
`self.frames` holds the diff (`:728`) — **two** full lists live simultaneously.

**Fix (ranked):**
1. Read frames through `xr.open_dataset(..., chunks=…)` and materialise only the
   currently displayed timestep + a small LRU around it. Medium effort, biggest
   win.
2. Cheaper interim: keep the eager load but store frames as the raw dtype (often
   `float32` already) and drop `self._orig["frames"]` in favour of re-reading file
   A on Clear-compare. ~10 lines.
3. Subset to the data's non-NaN bounding box before storing — CWatM outputs are
   usually a small basin inside a large grid, so this alone can cut memory by an
   order of magnitude. Medium effort.

### 5.2 `_uri_cache` is unbounded — **High** — [REASONED]

`analysis_netcdf.py:150` declares `self._uri_cache = {}` keyed by
`(colorscale, log_scale, ti)` (`:231`), populated in `_frame_uri` (`:235`), and
cleared **only** in `_apply_data_swap` (`:758`, i.e. on the compare toggle). It is
never cleared on colour-scale change, log toggle, or window close.

Playing through 400 frames stores 400 base64 PNG strings; switching colour scale
and playing again stores 400 more. With 9 colour scales + a log toggle the
theoretical ceiling is 7200 entries. At ~30-100 KB per data URI that is
**hundreds of MB of strings**, on top of §5.1's frames.

**Fix:** replace with a bounded `collections.OrderedDict` LRU (say 64 entries) or
just key it on `ti` only and clear it whenever `_colorscale_name` / `_log_scale`
changes. ~8 lines. No behavioural change — it is a pure cache.

### 5.3 Dialogs leak because Qt parent ownership outlives `exec()` — **High** — [MEASURED]

`analysis_netcdf.py:109-110`:

```python
win = NetcdfWindow(path, parent)
win.exec()
```

Same pattern at `analysis_timeseries.py:80-81`, `basin_viewer2.py:221-223`, and
`output_explorer.py:257, 261, 265`.

Passing `parent` transfers ownership to the C++ parent, so the dialog survives
`win` going out of scope. Verified empirically:

```
$ QT_QPA_PLATFORM=offscreen python -c "…create 5 QDialog(mw); del d; gc.collect()…"
QDialog children still owned by parent: 5
```

So **every Analyse/Basin window ever opened stays alive until the main window
closes**, carrying its frames (§5.1), its `_uri_cache` (§5.2), its
`QWebEngineView` + render-process page, and its `_page_html` string. Open ten
NetCDF files in a session and the GUI is holding ten complete copies.

`closeEvent` (`analysis_netcdf.py:1069-1093`) stops the timer, waits for the
worker and removes the temp HTML — but frees no data and does not delete the
dialog.

**Fix:** `win.setAttribute(Qt.WA_DeleteOnClose)` before `exec()`, or
`win.deleteLater()` after it returns. **~1 line per call site**, highest
impact/effort ratio in this report. Risk: none for `exec()`-style modal use —
nothing reads the dialog after `exec()` returns at any of these six sites (checked).

### 5.4 Scalar `pd.to_datetime` per timestep — **Med** — [MEASURED]

`analysis_netcdf_base.py:200`:

```python
point_time_labels = [self._fmt_time(tvals[i]) for i in range(ntime)]
```

`_fmt_time` (`:239-248`) does `import pandas as pd` **inside the function** and
`str(pd.to_datetime(v).date())` per element. Measured on an 11 000-step axis
(≈ 30 years daily):

```
per-scalar pd.to_datetime x11000: 0.430s
vectorized numpy          x11000: 0.027s
```

**0.4 s of pure waste on every NetCDF window open**, on the GUI thread, before the
map appears. Note this runs over the **full** `ntime`, not the strided 400 frames.

**Fix:** when `tvals.dtype` is `datetime64`, use
`np.datetime_as_string(tvals, unit="D")` once and fall back to the per-element
path only for object/cftime axes. ~6 lines, 16× faster. No invariant risk.

### 5.5 `_point_series` reopens the dataset per click — Med — [REASONED]

`analysis_netcdf_base.py:336` calls `_open_dataset_safe(src["path"])` and closes
it at `:351` on **every** clicked point. Each open re-reads headers and, in the
tolerant branch (`:116-132`), can re-scan every 1-D CF variable. Clicking 10
points = 10 full opens.

**Fix:** hold one open `xr.Dataset` handle on the window (closed in `closeEvent`,
which already exists at `:1069`). ~10 lines. Note this interacts with §5.3 — an
undestroyed window would then also hold an open file handle, so fix §5.3 first.

### 5.6 WaterCycle CSV read 3-4× — Low — [MEASURED as non-issue]

`analysis_watercycle.py`: `_read_station` does `list(csv.reader(f))` on the whole
file (`:244-245`) just to read rows 1 and 2; `_read_settings_title` reads the
first line (`:268`); `_load_data` does another full `list(csv.reader(f))` (`:303`)
and then `pd.read_csv` (`:332`). Four passes over the same file.

Monthly-totals files are small (hundreds of rows), so the cost is single-digit ms.
**Recommend leaving it** — parse once and pass the rows down only if this file is
touched for other reasons.

### 5.7 Timeseries CSV parsing — [MEASURED, no action]

I suspected `analysis_timeseries.py:168-201` (pure-Python `csv.reader` +
per-cell `float()` in a try/except) was a bottleneck. **It is not:**

```
11 000 rows × 10 cols
pure-python _parse_csv: 0.059s
pandas read_csv:        0.133s
```

The hand-rolled parser is **2× faster** than pandas here (pandas' per-call setup
dominates at this size). Do **not** "optimise" this to pandas. Recorded so the
question is not re-opened.

### 5.8 Unclosed file handles — Low — [REASONED]

`analysis_timeseries.py:235` and `analysis_watercycle.py:275`:
`content = open(path, encoding="utf-8", errors="ignore").read()` — no context
manager. CPython refcounting closes these promptly in practice, but it is a
latent handle leak under any non-refcounting path. Same pattern at
`main_window.py:736` and `meta_netcdf.py:42`. Trivial fix, cosmetic priority.

---

## 6. Memory / resource leaks

| Issue | Severity | Anchor | Note |
|---|---|---|---|
| Dialogs retained by Qt parent after `exec()` | **High** | `analysis_netcdf.py:109`, `analysis_timeseries.py:80`, `basin_viewer2.py:221`, `output_explorer.py:257,261,265` | §5.3, **measured** |
| `_uri_cache` unbounded | **High** | `analysis_netcdf.py:150` | §5.2 |
| `self.frames` + `_orig["frames"]` both live | **High** | `analysis_netcdf.py:724,728` | §5.1 |
| `_animal_timer` never stopped | Low | `discharge_sparkline.py:86` | §3.3 |
| `_dl_bytes` re-reads disk cache each call | Low | `basin_viewer2.py:128` | §2.2 |
| Bare `open().read()` (4 sites) | Low | `analysis_timeseries.py:235` et al. | §5.8 |

**Correctly handled — no action:**
- `QPainter` state: `progress_clock.py:61` and `discharge_sparkline.py:142` rely
  on the stack-scoped painter (fine in PySide6); `line_number_gutter.py:88-89` has
  an explicit `finally: painter.end()`; `_draw_animal` pairs
  `painter.save()`/`restore()` (`discharge_sparkline.py:215, 226`). ✅
- xarray handles: `_load` and `_point_series` both close in `finally`
  (`analysis_netcdf_base.py:233-237`, `:349-353`); `basin_viewer.py:612` closes
  the ups dataset; `build_mask_context` uses `with rasterio.open(...)`
  (`basin_viewer.py:751`). ✅
- Hidden Run windows drop their reference on `destroyed` (`run_controller.py:39-41`). ✅
- Run-log handle opened once per run, closed on every exit path
  (`run_controller.py:246-264`), and protected from the generic cleanup
  (`run_controller.py:511-529`). ✅

---

## 7. Packaging (`cwatm_gui_dir.spec`)

Built artifact on disk: **`dist/CWatM_GUI.zip` = 369 MB** [MEASURED]. (The
expanded `dist/CWatM_GUI/` folder was not present to measure directly; the
uncompressed folder will be substantially larger.)

### 7.1 `binaries` force-fed to the model exe — Low — [REASONED]

Line 274 passes `binaries` to the GUI `Analysis`; **line 341 passes the same list
to the model `Analysis`**. That list contains `folium_binaries`, `ai_binaries`
(rookiepy's compiled cookie reader) and `modflow_binaries` — even though the model
`Analysis` explicitly excludes `folium`, `plotly`, `notebooklm` as *modules*
(`:366`, `:373`).

Real disk impact is ~zero (COLLECT dedupes by target name, and both exes share one
folder), but it makes the model's dependency graph misleading. **Fix:** pass only
`rasterio_lib_binaries + modflow_binaries + routing binaries` at `:341`. ~2 lines,
cosmetic.

### 7.2 `collect_all` calls that could be narrowed — Med — [REASONED, sizes UNCONFIRMED]

`:132` `for _pkg in ('flopy', 'matplotlib', 'contourpy', 'kiwisolver', 'PIL', 'fontTools')`.

- **`fontTools`** — matplotlib only needs it for font *subsetting* in PDF/PS/SVG
  output. Nothing in CWatM or the GUI produces those. `collect_all('fontTools')`
  pulls the whole library (~10-15 MB with its data). Candidate for the excludes
  list, guarded by a smoke test that a MODFLOW run still starts.
- **`PIL`** — pulled only as a matplotlib image backend. `collect_all` brings all
  plugins; `collect_submodules` + the needed binaries would be leaner.
- **`matplotlib`** — `mpl-data` (fonts, sample data, stylelib) is tens of MB.
  `collect_data_files('matplotlib', excludes=['**/sample_data/**'])` would trim it.
- **`plotly`** (`:70`) — `collect_all` bundles the full `plotly.js` **plus**
  `plotly/package_data`, datasets and validators. The GUI uses `graph_objects`
  only; `collect_submodules('plotly') + the package_data JS` would be smaller.

All four are **size/cold-start** wins (fewer files for Windows + AV to touch on
first launch), not runtime-speed wins. Effort: an afternoon of build-and-verify.
**Risk: medium** — each narrowing can produce a runtime `ModuleNotFoundError` that
only shows up when a rarely used path is exercised. Do them one at a time, and
verify a MODFLOW-coupled run and a Show Basin / NetCDF / Timeseries open after each.

### 7.3 `'py_splash'` hidden import is a typo — Low — [REASONED]

`:183` lists `'py_splash'`. The PyInstaller runtime module is **`pyi_splash`**
(as correctly imported at `cwatm_gui.py:27, 79`). The entry silently does nothing
(PyInstaller warns about a missing hidden import and continues). The splash works
anyway because `Splash(...)` at `:392` injects `pyi_splash` itself.

**Fix:** delete the line or correct it to `pyi_splash`. 1 line.

### 7.4 Already-good decisions — ✅ (do not regress)

- `optimize=1` on both PYZs (`:327`, `:382`) — smaller bytecode, faster load.
- `src` and `cwatm` ship **only in the PYZ**, not duplicated as datas (`:170-176`,
  `:218-223`).
- `playwright` (~101 MB), `osgeo` (~95 MB duplicate GDAL), `black`,
  `speech_recognition`/`pyaudio` all excluded (`:301-315`).
- rasterio **not** excluded from the model exe, with the namespace-package trap
  documented inline (`:343-349`) — this matches the stored memory note; leave it.
- Tcl/Tk kept because the PyInstaller `Splash` renders through Tk (`:385-390`).
- The `_netsafe_copyfile` SMB shim (`:13-24`) — necessary on this share.

---

## 8. Measured baseline

All numbers collected on this machine with `venv/Scripts/python.exe` (3.12.10),
project on the `P:` network share.

**Import graph (`-X importtime`, cold then warm):**

```
src.gui.components.main_window          3.92 s (cold) → 3.18 s (warm)
  PySide6.QtWidgets                     2.17 s → 1.81 s
    PySide6.QtGui                       0.72 s → 0.64 s
    PySide6.QtCore                      0.44 s → 0.39 s
  src.gui.components.run_controller     0.18 s → 0.14 s
  cwatm.version                         0.076 s → 0.076 s
  src.gui.utils.progress_clock          0.117 s → 0.102 s
  src.gui.widgets.line_number_gutter    0.115 s → 0.120 s
```

**Deferred (background warm-up) stack, individually timed:**

```
pandas                 16.52 s
cwatm.run_cwatm        23.93 s
xarray                  4.79 s
openpyxl                6.24 s
folium                  4.14 s
plotly.graph_objects    0.21 s
rasterio                0.00 s   (already loaded via cwatm.run_cwatm)
                       -------
total deferred        ≈ 55.8 s
```

**NetCDF time-label construction (11 000 timesteps ≈ 30 years daily):**

```
per-scalar pd.to_datetime (current code)   0.430 s
np.datetime_as_string (proposed)           0.027 s     → 16× faster
```

**Timeseries CSV parse (11 000 rows × 10 columns):**

```
pure-python csv.reader loop (current)      0.059 s
pandas.read_csv (proposed alternative)     0.133 s     → current code is 2× FASTER
```

**metaNetcdf lookup miss (`get_meta`, 847 entries, `meta_netcdf.py:73`):**

```
2000 misses: 0.128 s  →  64.3 µs per miss (full case-insensitive dict scan)
```

Fires only on `QEvent.ToolTip` (`main_window.py:3057`), i.e. after the hover
delay — not per mouse-move. **Low priority**, but a one-time lowercase index in
`_load()` (`meta_netcdf.py:34-59`) makes it O(1) for ~4 lines.

**Qt dialog parent-ownership check (offscreen platform):**

```
5 QDialog(mw) created, references dropped, gc.collect()
→ QDialog children still owned by parent: 5
```

Confirms §5.3.

**Build artifact:**

```
dist/CWatM_GUI.zip     369 MB
```

---

## Appendix: suggested order of work

1. `WA_DeleteOnClose` on the six dialog sites — §5.3. *(1 line × 6, High impact)*
2. Cache the `None` mask result in `_rebuild_mask_cache` — §2.1 fix (1). *(~4 lines)*
3. Bound `_uri_cache` — §5.2. *(~8 lines)*
4. Vectorise `point_time_labels` — §5.4. *(~6 lines)*
5. Gutter loop early-break — §4.1. *(~5 lines)*
6. Drop `openpyxl`/`folium` from the eager warm-up — §1.3. *(~5 lines)*
7. Merge contiguous `ExtraSelection` runs — §4.3. *(~15 lines)*
8. Move the coordinate-MaskMap build off the GUI thread — §2.1 fix (2). *(~40 lines)*
9. Chunked / bbox-subset NetCDF frame loading — §5.1. *(medium)*
10. Narrow the `collect_all` calls, one at a time with verification — §7.2.

Items 1-6 are ~30 lines total and address every High finding except §5.1.
