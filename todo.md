# CWatM GUI — improvement backlog (reviewed 2026-08-13)

> **Done 2026-08-13:** items **1–13 and 15**. Only **item 14 (i18n)** remains, open by
> choice — worth starting only if a non-English user base is actually targeted.
>
> **Item 5 (tests)** landed last: `tests/` holds **290 tests + 5 xfail**, covering
> `cell_formula`, `cell_fill`, `metrics`, `var_dims`, `tab_manager.next_copy_path`,
> `temp_page`, `run_ledger` and the `settings_check` semantic pass. Three findings came
> out of writing them:
> - **`cell_formula` computes hyphenated text.** `1-2` → `-1.0` and `10-2020` → `-2010.0`
>   are written to the workbook as numbers. `cell_fill._as_number()` deliberately keeps
>   `1-2` as text, so the two modules disagree about the same cell. A date like
>   `2026-08-13` is claimed by `is_formula()` and then fails to evaluate, so the cell
>   shows `#SYNTAX`. Recorded as `xfail(strict=True)`, **not fixed** — the fix changes
>   user-visible cell behaviour and is the owner's call.
> - **Absolute references only work inside a range.** `=SUM($A$1:$C$1)` computes;
>   `=$B$2` raises `#SYNTAX`, because `_rewrite_ranges` strips the `$` only from a
>   matched range. Also `xfail(strict=True)`.
> - **`run_ledger._entry_key` can collide** — (ts to the millisecond, settings, pathout).
>   Two runs of the same file into the same folder finishing in the same millisecond are
>   indistinguishable, so removing one removes both. Not practically reachable (Batch Run
>   refuses duplicate PathOuts); pinned by a test that documents it.
>
> One test expectation of mine was simply **wrong**, and the code was right:
> `OUT_TSS_Daily = none` *is* an error, because CWatM's sentinel test is `!= "None"`,
> case-sensitive (`configuration.py:249`, `output.py:198/1037/1178`).
>
> Notes from the second round:
> - **Item 12 needed no work** — the exit-status policy had already been settled in
>   `cwatm_gui.py`'s own uncommitted changes. Verified: a clean quit returns 0 silently,
>   a non-zero code is propagated to the caller. My grep had matched the docstring
>   describing the fix and the deliberate `handle_exception` interception.
> - **Item 9** covers Timeseries / Watercycle / Flow Diagram only. **NetCDF keeps its own
>   `_save_html` on purpose**: its page is served through the `osmtile://` scheme rather
>   than a temp file, and it saves the page *string* with its own caveat about basemap
>   tiles. Forcing it into the base would have obscured a genuinely different shape.
> - **Item 8**: 128 KB → 110 KB (17.7k → ~14.5k words). The detail was *moved*, not
>   deleted — Internals gained four sections (Settings-file tabs, Change Options, Check
>   Data, Add output variables) and grew to 1356 lines.
>
> Notes from the first round:
> - Item 7's "Set max Gauge" claim was **backwards** — the code says `Set max Gauge`, so
>   the README was right and CLAUDE.md was stale. CLAUDE.md is now fixed, and two menu
>   items it never listed (**File ▸ Change Working Dir**, **Help ▸ CWatM Homepage**)
>   were added.
> - Still open, found while doing item 7: the in-app gauge warning and
>   `find_largest_ups_gauge`'s error message say *"Tools/Set Gauge"*, naming a menu item
>   that does not exist (`main_window.py:1146` and `:2100`). One-line user-facing fix,
>   left alone because it changes displayed text.
> - Found while doing item 6: `main_window.py` contains a stray **U+2029 paragraph
>   separator**. `str.splitlines()` treats it as a line break and Python's parser does
>   not, so any line-based tool over that file is off by one after it. Harmless at
>   runtime; worth deleting.

Ranked by **user/maintainer impact ÷ effort**. Scope: GUI code (`cwatm_gui.py`,
`src/gui/**`), docs and repo hygiene. Nothing under `cwatm/` is touched.

Every finding below was verified against the working tree, not inferred from the docs.

---

## P0 — broken right now

### 1. `requirements.txt` does not exist — every documented install path fails
**Effort: 15 min. Impact: a new user or Linux user cannot install the GUI.**

The canonical file is gone. What is actually on disk:

| File | Size | Date | What it is |
|------|------|------|-----------|
| `requirements - Copy.txt` | 4129 B | 14/07/2026 | **The real, current pin set** — PySide6 6.11.1, numpy 2.5.0, rasterio 1.5.0, xarray 2026.4.0, flopy 3.10.0 |
| `_requirements.txt` | 1478 B | 11/07/2026 | **Stale** — "Python 3.8" header, numpy 1.24.4, PySide6 6.6.3.1, rasterio 1.3.11; still lists `SpeechRecognition`/`PyAudio`, which CLAUDE.md records as *removed* |
| `requirements_new.txt` | 402 B | 03/07/2026 | Unpinned name-only scratch list |
| `requirements_linux.txt` | 5370 B | 10/08/2026 | Current, correctly named |

The numpy 2.5.0 / rasterio 1.5.0 pair in `requirements - Copy.txt` is exactly the
combination `src/gui/utils/warning_filters.py` exists to work around — that confirms
which file is live.

**15 places break on the missing name**, and they are all the *entry* instructions:
- `CLAUDE.md:895` — the Installation block
- `documentation/CWatM_GUI_Documentation.md:63, 66, 796`
- `documentation/CWatM_GUI_FAQ.md:172`
- `cwatm_gui_linux.md:16, 48, 181, 208, 212, 427`
- `gui.sh:47, 223, 252` — the "PySide6 missing" error tells the user to run it
- `requirements_build.txt:10` — `-r requirements.txt`, so **the build env cannot be
  created either**

**Fix:** `requirements - Copy.txt` → `requirements.txt`; delete `_requirements.txt` and
`requirements_new.txt`. Confirm the rename was accidental before deleting.

### 2. Three Plotly windows leak multi-MB temp HTML files, forever
**Effort: 30 min. Impact: hundreds of MB in `%TEMP%` over a working session.**

`analysis_timeseries.py:904`, `analysis_watercycle.py:550` and
`analysis_flowdiagram.py:539` each write a self-contained Plotly page (plotly.js
inlined, ~4 MB) to `NamedTemporaryFile(delete=False)`, store the path in
`self._temp_html`, and **never remove it** — not on re-render, not on close. Every
render overwrites the *variable*, orphaning the previous file.

This is not a once-per-window cost: `_show_current()` in Timeseries is called from
**9 sites** including a 200 ms-debounced range slider (`analysis_timeseries.py:371`),
and Watercycle/Flow Diagram rebuild on every slider move
(`analysis_watercycle.py:226`). Dragging a range slider writes a new 4 MB file per tick.

The correct pattern is already in the codebase — `analysis_netcdf.py:1147-1148` and
`basin_viewer2.py:987-988` both `os.remove` theirs on close. Copy it, and also unlink
the previous file before writing the next.

### 3. Docs reference three files that are not in the repo
**Effort: 10 min.**

`cwtmexe.md`, `makeitfaster.md` and `nuitka_plan.md` are cited as the reference docs for
packaging, build speed and the Nuitka option — at `CLAUDE.md:899` (the "do not install
the GDAL wheel" rationale), `CLAUDE.md:999`, and `documentation/README.md:127-129`.
None of the three exists. The README links are doubly wrong: even if restored they sit
at the repo root, so the link from `documentation/` needs `../`.

**Fix:** restore them, or delete the references and fold the one load-bearing sentence
(rasterio ships its own GDAL) into CLAUDE.md directly.

---

## P1 — high value

### 4. `main_window.py` is 3953 lines and is the maintenance bottleneck
**Effort: 1–2 days. Impact: every future feature touches this file.**

Three self-contained extractions, no behaviour change:

| Extract | Lines | To |
|---------|-------|-----|
| Check-settingsfile engine — `check_settingsfile`, `_write_check_summary`, `_semantic_settings_problems`, `_forcing_time_range`, `clear_checking`, `toggle_check_settings` + the `_SECTION_GATED_BY` / `_KEY_GATED_BY` / `_OPTION_REQUIRES` tables | ~840 (1164–2003) | `src/gui/utils/settings_check.py` |
| Find & Replace dialog — already fully self-contained, owns its own widgets and closures | ~200 (394–595) | `src/gui/widgets/find_replace_dialog.py` |
| Stylesheet builders — `_left_panel_style`, `_right_panel_style`, `_output_box_style`, `_editor_style`, `_run_button_idle_style`, `_build_modern_button_style`, … | ~300 (3199–3535) | `src/gui/components/main_window_styles.py` |

The check engine is the valuable one: it is nearly pure (content string in, `(row,
message)` tuples out) and is currently the largest untestable block in the project —
extracting it is the precondition for item 5.

Target: main_window under 2000 lines.

### 5. Zero automated tests
**Effort: 1 day for a meaningful first suite. Impact: regressions currently only surface when a user opens the window.**

No `tests/`, no `pytest.ini`/`pyproject.toml`, no `conftest.py`, no CI. Yet a large
share of the trickiest logic is pure and needs no Qt:

- `utils/cell_formula.py` — `is_formula` / `evaluate`, an ast whitelist with range and
  function handling. Off-by-one in a range is silent and wrong.
- `utils/cell_fill.py` — `extend_series` (number step, text+trailing number, weekday /
  month / quarter lists)
- `utils/var_dims.py` — `dim_problem` / `index_options`, mirrored by hand from cwatm's
  allocation lists; drift here produces wrong Check-settingsfile verdicts
- `utils/metrics.py` — KGE / NSE / PBIAS / RMSE against known reference values
- `components/config_parser.py`, `components/tab_manager.next_copy_path`,
  `utils/run_ledger.py`, `utils/meta_netcdf.py`,
  `restore_settings_window.parse_input_files`
- `_semantic_settings_problems` once item 4 lands — date ordering, option dependencies,
  output-keyword grammar, index validation, all table-driven and all ideal for tests

### 6. 104 silent `except: pass` against 33 logging calls — the diagnostic log rule is not followed
**Effort: half a day sweep. Impact: "nothing happened" is currently undiagnosable.**

Across `src/gui`: 547 `except` clauses, **312** catching bare/broad `Exception`, of
which **104** are followed by nothing but `pass`. Total references to `gui_log` /
`log.*` in the whole tree: **33**.

CLAUDE.md states the invariant plainly — *"swallowed exceptions go to a rotating
`%LOCALAPPDATA%/CWatM_GUI/gui.log` … check it when nothing happened"* — but roughly
70 % of swallowed exceptions write nothing, so the log is empty exactly when it is
needed. Worst concentrations: `analysis_netcdf.py` (12), `main_window.py` (13),
`analysis_netcdf_base.py` (8), `basin_viewer.py` (8), `batch_runner_window.py` (6),
`restore_settings_window.py` (6).

**Fix:** mechanical — replace `pass` with `log.debug("<what failed>", exc_info=True)`.
Keep the broad catch (this is GUI chrome; a raise would be worse), just stop discarding
the evidence.

### 7. `documentation/README.md` is a release behind on almost every section
**Effort: 1 hour. Impact: it is the first file a new contributor reads.**

Verified against the current code:
- **Menus (line 16, 58-67)** list `File · Settings · Tools · RUN CWATM · Configure ·
  Info` — the **Analyse** menu and the **CWatM AI** button are missing entirely, i.e.
  every visualisation feature is invisible in the README
- **line 64** — "Set max Gauge"; the item is **Set Gauge**
- **line 126-127** — "`cwatm_gui.spec` is one-file"; that spec was **removed**
- **line 99-111** — the project-structure block predates `menu_builder.py`,
  `run_controller.py`, `tab_manager.py`, `output_box.py`, `preferences_window.py`,
  `theme.py` and all six Analyse widgets
- **line 28** — quick-start is `pip install PySide6 numpy pandas scipy xarray netCDF4
  rasterio`: no PySide6-WebEngine, folium or plotly, so a user who follows it gets a
  blank Show Basin and no plots
- **line 115** — "Python 3.8+"; the venv is **3.12.10** and CWatM AI needs ≥ 3.10
- **line 127-129** — links to the three missing files of item 3, with wrong relative
  paths

---

## P2 — worth doing

### 8. `CLAUDE.md` is 126 KB / 1078 lines and loads into every session
**Effort: half a day.**

It already spun `CWatM_GUI_Internals.md` (96 KB) and `CWatM_GUI_Features.md` out, and
carries its own editing rule — *"keep always-true rules and invariants in CLAUDE.md; put
per-feature window/rendering detail in Internals"* — but the menu table has drifted back
into narrative: several single table cells (Add output variables, Journal of Runs,
Compare Tab, the Settings-file tabs note, the Excel window's Core Modules entry) run
400+ words of implementation detail each.

**Fix:** apply its own rule. One line of behaviour + the invariant in CLAUDE.md, the
narrative in Internals. Target under 600 lines.

### 9. Four Plotly windows duplicate the same render/save/cleanup sequence
**Effort: half a day. Fixes item 2 structurally.**

`TimeseriesWindow`, `WatercycleWindow`, `FlowDiagramWindow` and `NetcdfWindow` each
repeat: build fig → `theme.themed_plot_page(html)` → `NamedTemporaryFile` → `web_view.load(QUrl.fromLocalFile)` →
a `_save_html` that `shutil.copyfile`s the temp file to a user path. Four near-identical
`_save_html` implementations (`analysis_timeseries.py:468`, `analysis_watercycle.py:504`,
`analysis_flowdiagram.py:494`, `analysis_netcdf.py:1108`).

`FlowDiagramWindow` is `(GeometryMemoryMixin, QDialog)` and does **not** subclass
`WatercycleWindow`, despite CLAUDE.md describing it as reusing that window's header —
the reuse is by importing loose helpers.

**Fix:** a `PlotlyWindowBase(GeometryMemoryMixin, QDialog)` owning `_render(html)`,
`_save_html()` and temp-file lifetime. Removes ~150 duplicated lines and makes item 2
impossible to reintroduce.

### 10. Repo hygiene — 57 MB of wheels and a dozen scratch files at the root
**Effort: 30 min.**

- **`gdal-3.12.2-…whl` (46 MB)**, `netcdf4-1.7.4-…whl` (6.5 MB),
  `rasterio-1.5.0-…whl` (4 MB) sit at the root. CLAUDE.md explicitly says *"Do not
  install the GDAL wheel"* — and the repo ships it, inviting exactly the broken env the
  docs warn about.
- Scratch: `new2.txt`, `new4.txt`, `new5.txt`, `new8.txt`, `news3.txt`, `news6.txt`,
  `idea1.txt`, `bash.exe.stackdump`, `check_cwatm1.csv` (123 KB run output),
  `nc2_shot.png`, `discharge_daily.nc` (371 KB), `cwatm_settings_reservoirs_morava.xlsx`
  (968 KB)
- **`CWatM_GUI_Features.md` at the root is 0 bytes** — an empty file sharing its name
  with the real `documentation/CWatM_GUI_Features.md`, so a search hits the wrong one
- `documentation/CWatM_GUI_Documentation.docx` (05/09/2025) and `.rtf` (04/09/2025) are
  11 months behind the live `.md` (13/08/2026) — regenerate or delete
- `.gitignore` covers only `/venv`, `/venv2`, `/dist`, `/build` and three explicit
  `cwatm/**/__pycache__` paths. Add `__pycache__/` globally, `*.whl`, `*.stackdump`,
  `installer/Output/`, `.idea/`

### 11. No CI
**Effort: 2 hours once item 5 exists.**

A Windows GitHub Action doing `pip install -r requirements.txt`,
`python -m compileall src`, and `pytest` would catch the class of bug that currently
only appears when a user opens a rarely used window — an import error in, say,
`restore_settings_window.py` is invisible until someone clicks the menu item. The
`compileall` step alone is worth it and needs no tests.

---

## P3 — when convenient

### 12. `_exec()` announces a false "System exit intercepted" on every clean quit
Carried forward from `improve.md` §3, still open and explicitly flagged there as
*"Do not change it without deciding."* `sys.exit(0)` is raised inside the same `try`
that catches `SystemExit`, so a normal quit prints two misleading lines to `sys.stderr`
— which is the `PrintRedirector` by then, so they land in the CWatM output box while the
window closes. Decide the policy: keep the guard but exclude code 0, or drop it.

### 13. Version notes are accumulating as separate files
`CWatM_GUI_Version_1.04.md`, `CWatM_GUI_Version_1.05.md`, one per release. A single
`CHANGELOG.md` with newest-first sections is easier to diff and to link from the About
dialog. (`src/gui/__init__.py` = 1.05 and the manual = 1.05 — versioning itself is in
sync and working.)

### 14. No i18n
Every user-facing string is hardcoded English. Qt's `tr()` + `.ts` files would be a
large mechanical change; only worth starting if a non-English user base is actually
targeted.

---

## Deliberately not on this list

Things that were checked and are in good shape:

- **Version single-source-of-truth** — `src/gui/__init__.py:10` scraped by the installer,
  read by the About dialog; docs agree
- **No `TODO`/`FIXME`/`HACK` markers anywhere in `src/`** — unusual and good
- **Startup lazy-import discipline** — no module-level cwatm/xarray/rasterio/plotly
  import on the startup path, as the invariant requires
- **Theme tokens** — no hardcoded colours found in GUI chrome
- **`os.startfile` never called directly** — all three "open this" paths go through
  `utils/open_path.py`
