# Graphical User Interface for CWatM

A desktop GUI for the Community Water Model (CWatM) by the International Institute for
Applied Systems Analysis (IIASA). Load, parse, edit and manage CWatM settings (`.ini`)
files, run the model directly, and visualise/validate its inputs — without the command
line.

> **Full manual:** see **[CWatM_GUI_Documentation.md](CWatM_GUI_Documentation.md)**.
> **Feature & usage tour:** **[CWatM_GUI_Features.md](CWatM_GUI_Features.md)**.
> Developer reference is **[CLAUDE.md](../CLAUDE.md)** (concise: menu bar, invariants,
> architecture, build) with per-feature deep dives in
> **[CWatM_GUI_Internals.md](CWatM_GUI_Internals.md)**.

## Key benefits

- **Menu-driven** interface (File · Settings · Tools · RUN CWATM · Configure · Info).
- Live settings editing with syntax highlighting and collapsible sections.
- Integrated model execution with a progress clock and real-time output.
- Built-in checks (gauges-in-basin, PathOut existence) and helper tools.
- Basin visualisation and data validation (Check Data).

**Target audience:** researchers, hydrologists, water-resource managers and students
working with the CWatM hydrological model.

## Quick start

```bash
pip install PySide6 numpy pandas scipy xarray netCDF4 rasterio
python cwatm_gui.py
```

1. **File ▸ Load .ini** (Ctrl+O) — load a settings file (parses automatically).
2. Edit **Start/Spin/End Date, PathOut, MaskMap, Gauges** — changes auto-apply to the
   content in memory; **Save / Save As** turn blue to show unsaved changes.
3. **File ▸ Save .ini** (Ctrl+S) — write to disk.
4. **RUN CWATM ▸ Run CWATM** (Ctrl+R) — run the model (select again to stop).

## Interface at a glance

```
[banner: CWatM GUI · "The Community Water Model User Interface" · IIASA]
[menu bar: File  Settings  Tools  RUN CWATM  Configure           Info ]
┌ left control panel ─────────────┬ right editor panel ───────────────┐
│ Loaded: <file>                  │ Save  Save As  Fold All  Unfold    │
│ Start / Spin / End Date         │ All  Top  Down                     │
│ PathOut / MaskMap / Gauges      │ syntax-highlighted settings text   │
│ RUN CWatM  + warning label      │ with foldable sections + gutter    │
│ output box  (clock below it)    │                                    │
└─────────────────────────────────┴────────────────────────────────────┘
```

The GUI is menu-driven: the former **Load Text, Actualize, Options, Show Basin, Check
Data** buttons and the **Write output** checkbox were moved into menus (Actualize was
removed — field changes now auto-apply). **Save / Save As / Fold All / Unfold All /
Top / Down** and **RUN CWatM** remain as buttons *and* menu items.

## Menus (summary)

| Menu | Items (shortcuts) |
|------|-------------------|
| **File** | Load .ini (Ctrl+O), Reload (Ctrl+L), Save .ini (Ctrl+S), Save As (Ctrl+Alt+S), Exit |
| **Settings** | Fold All (Alt+0), Unfold All (Alt+Shift+0), Top (Alt+T), Down (Alt+D), Find (F5), Find next (Ctrl+F), Undo (Ctrl+Z), Redo (Ctrl+Y) |
| **Tools** | Change Options, Show Basin, Set Gauge, Add output Watercycle, Check Data, Create PathOut Folder |
| **RUN CWATM** | Run CWATM (Ctrl+R) |
| **Configure** | Set output box file, Write output box |
| **Info** | About CWatM |

## Features

- **Settings editing** — auto-parse on load; comments grey, `True` blue, `False` red;
  bold section headers with `[-]`/`[+]` collapse; whitespace preserved.
- **Fields** — Start/Spin/End Date (chronological validation; integer SpinUp/StepEnd
  interpreted as `StepStart + (N−1)` days), PathOut, MaskMap, and **Gauges** (linked to
  the settings `Gauges` entry). Edits **auto-apply in memory** (debounced); disk writes
  happen only on Save.
- **Unsaved-changes indicator** — Save / Save As turn blue; **Exit** prompts to save.
- **Gauge / PathOut checks** — the Gauges text is blue if all gauges are inside the
  basin, red otherwise; a red warning appears next to RUN CWatM. Works for file-based
  and coordinate-based MaskMaps (basin generated internally, cached). PathOut existence
  is checked with placeholder resolution.
- **Helper tools** — **Set Gauge** (largest upstream cell inside the mask),
  **Create PathOut Folder**, **Add output Watercycle** (adds
  `OUT_TSS_AreaSum_MonthTot = WaterCycle` under `[OUTPUT]`).
- **Model execution** — threaded, responsive; live progress clock (below the output
  box) and a selectable/copyable output box; errors in dark red.
- **Output logging** — **Configure ▸ Write output box** appends to
  `<PathOut>/cwatm_out.txt` (or a custom file via **Set output box file**), with a dated
  header per run.
- **Options window**, **Basin viewer**, and **Check Data** (run CWatM in check mode,
  compare against a discharge NetCDF, restore settings from a discharge map).

## Project structure

```
cwatm_gui.py                         entry point (app icon, exception handling)
src/gui/components/main_window.py     main window: menus, fields, run control, checks
src/gui/components/config_parser.py   INI parsing / date & settings extraction / updates
src/gui/managers/date_manager.py      date widgets, validation, integer SpinUp/StepEnd
src/gui/managers/file_manager.py      file load/save
src/gui/managers/text_display.py      editor text area / content
src/gui/widgets/options_window.py     [OPTIONS] boolean editor
src/gui/widgets/check_data_window.py  Check Data / NetCDF comparison
src/gui/widgets/basin_viewer.py       basin viewer + mask/gauge/PathOut helpers
src/gui/utils/progress_clock.py       circular progress indicator
src/gui/utils/cwatm_worker.py         threaded CWatM execution worker
```

## Requirements

Python 3.8+, PySide6, NumPy, pandas, SciPy, xarray, netCDF4, rasterio.

## Building the executable

The project venv is **`venv/`** (an older `build_env/` copy is deprecated).

```powershell
venv\Scripts\Activate.ps1
python -m PyInstaller cwatm_gui_dir.spec --noconfirm
```

`cwatm_gui_dir.spec` is the one-folder build (recommended); `cwatm_gui.spec` is
one-file. See **[cwtmexe.md](cwtmexe.md)** (rasterio/xarray/GDAL packaging fixes),
**[makeitfaster.md](makeitfaster.md)** (build speed), and
**[nuitka_plan.md](nuitka_plan.md)** (optional Nuitka build for faster runtime).

## License & contact

See the `LICENSE` file. Developed by IIASA — info@iiasa.ac.at ·
[CWatM on GitHub](https://github.com/iiasa/CWatM).
