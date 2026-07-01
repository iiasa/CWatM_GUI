# Building a CWatM executable / GUI with PyInstaller — fixes for GDAL & rasterio

**Purpose:** This file is instructions for Claude (or a human) building a CWatM
executable — including the CWatM **GUI** — with PyInstaller. CWatM uses
`rasterio` for raster I/O, and PyInstaller does not bundle rasterio correctly out
of the box. This causes two recurring errors. Both are fixed by editing the
PyInstaller `.spec` file. Follow the steps below.

> Claude: this is an actionable runbook. Read the whole file, then apply the
> changes to the real files in **this** folder. Do not assume paths from the
> example — discover them (see "Discover the environment").

---

## The two errors you will hit (and what they mean)

1. **`Cannot find gdalvrt.xsd (GDAL_DATA is not defined)`**
   GDAL cannot find its data directory. With rasterio this is normally
   auto-configured, but a frozen exe loses the data files unless they are bundled.

2. **`ModuleNotFoundError: No module named 'rasterio.sample'`** (or
   `rasterio._shim`, `rasterio.vrt`, `rasterio.control`, …)
   rasterio imports several submodules **dynamically**, so PyInstaller's static
   analysis never sees them and leaves them out of the build.

Both are **packaging** problems, not install problems. If `rasterio` imports fine
in the plain venv (`python -c "import rasterio, rasterio.sample"` works) but the
**built exe** fails, you are in this situation.

---

## Key fact: you do NOT need the GDAL / osgeo wheel

CWatM imports **only `rasterio`**, which bundles its own private GDAL
(`site-packages/rasterio.libs/gdal-*.dll`) plus its own data
(`rasterio/gdal_data/` and `rasterio/proj_data/`). rasterio self-configures GDAL
on import.

- Do **not** `pip install GDAL-*.whl` to make CWatM work.
- Installing `osgeo`/GDAL **alongside** rasterio puts two independent GDAL builds
  in one environment and is a common cause of the `gdalvrt.xsd / GDAL_DATA`
  message. If `osgeo` is installed and unused, `pip uninstall gdal` removes the
  conflict.
- Do **not** hard-code `GDAL_DATA` / `PROJ_LIB` in venv activation scripts as a
  fix — it does not apply to a standalone exe and can point GDAL at the wrong
  (osgeo) data version. The correct fix is bundling rasterio's data in the spec
  (below).

Only keep GDAL/osgeo if you deliberately use the `osgeo` Python API or
`gdalwarp`/`gdal2tiles` command-line tools. CWatM does not.

---

## Discover the environment (do this first)

Run these to find the real paths in this folder (PowerShell on Windows):

```powershell
# venv location (folder containing pyvenv.cfg)
Get-ChildItem . -Recurse -Filter pyvenv.cfg -ErrorAction SilentlyContinue | Select FullName

# Confirm rasterio is the only GDAL consumer in the project source (ignore venv/ build_env/ Scripts wrappers)
# Use the Grep tool over the project's .py files for: osgeo  gdal  ogr  osr  rasterio

# Confirm rasterio bundles its own GDAL + data
Test-Path "<venv>\Lib\site-packages\rasterio.libs"
Test-Path "<venv>\Lib\site-packages\rasterio\gdal_data\gdalvrt.xsd"
Test-Path "<venv>\Lib\site-packages\rasterio\proj_data"

# Find the PyInstaller spec (or the entry script if no spec yet)
Get-ChildItem . -Recurse -Filter *.spec -ErrorAction SilentlyContinue | Select FullName
```

If `from osgeo` / `import gdal` appear only in **comments**, **docstrings**, or in
`venv\Scripts\*.py` / `build_env\Scripts\*.py` (those are wrappers installed by the
GDAL wheel, not project code), then the project is rasterio-only and the rules
above apply.

---

## The fix: edit the PyInstaller `.spec`

Add these two helpers and use them for `hiddenimports` and `datas`. This collects
**every** rasterio submodule (fixing `rasterio.sample`) and rasterio's bundled
GDAL/PROJ data (fixing `gdalvrt.xsd`).

At the top of the spec, after the header line:

```python
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# rasterio imports many submodules dynamically (rasterio.sample, rasterio._shim,
# rasterio.vrt, ...), which PyInstaller's static analysis cannot see. Collect them
# all explicitly, plus rasterio's bundled GDAL/PROJ data files.
hiddenimports = collect_submodules('rasterio')
datas = [('cwatm', 'cwatm')]          # keep existing project data; adjust as needed
datas += collect_data_files('rasterio')
```

Then in the `Analysis(...)` call, reference them:

```python
a = Analysis(
    ['run_cwatm.py'],               # <-- entry script (for the GUI, use the GUI entry script)
    pathex=[],
    binaries=[],
    datas=datas,                    # <-- was datas=[('cwatm','cwatm')]
    hiddenimports=hiddenimports,    # <-- was hiddenimports=[]
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
```

Leave the rest of the spec (PYZ, EXE) unchanged unless GUI changes below apply.

---

## GUI-specific additions

The GUI build differs from the CLI build in a few ways. Apply whichever match the
GUI's toolkit.

1. **Entry script:** point `Analysis([...])` at the GUI's main script (e.g.
   `cwatm_gui.py`), not `run_cwatm.py`.

2. **No console window:** in the `EXE(...)` call set `console=False` so a terminal
   window does not pop up behind the GUI. (Keep `console=True` temporarily while
   debugging so you can see tracebacks; flip to `False` for release.)

3. **GUI framework hidden imports / data** — add the matching line to
   `hiddenimports` / `datas`:
   - **PyQt5 / PyQt6 / PySide6:** usually auto-detected; if you see missing
     plugin errors (e.g. "could not find or load the Qt platform plugin
     'windows'"), add `datas += collect_data_files('PyQt5', include_py_files=False)`
     and `hiddenimports += collect_submodules('PyQt5')` (swap in the right
     binding name).
   - **PySimpleGUI / tkinter:** tkinter ships with Python and normally works; if
     theming/data is missing, ensure the Python install includes Tcl/Tk.
   - **matplotlib (if the GUI plots):** `hiddenimports += collect_submodules('matplotlib')`
     and `datas += collect_data_files('matplotlib')`; you may also need to set the
     backend explicitly in code (e.g. `matplotlib.use('QtAgg')`).

4. **Other dynamically-imported geo packages** the GUI might pull in — same
   `collect_submodules` / `collect_data_files` treatment if their submodules go
   missing: `pyproj`, `fiona`, `shapely`, `netCDF4`, `xarray`. Add only the ones
   actually imported. **`xarray` additionally needs its package metadata copied —
   see the next section.**

5. **Icon / resources:** if the GUI uses an icon or bundled images, add them to
   `datas` as `('relative/source/path', 'dest/folder')` and reference them at
   runtime via a `sys._MEIPASS`-aware resource path helper.

---

## xarray (and any package using entry-point plugins / version metadata)

The CWatM GUI imports `xarray` (e.g. `src/gui/widgets/basin_viewer.py` and
`cwatm/hydrological_modules/pySnowClim/`). xarray is a **second rasterio-style
trap**, and a slightly worse one: a frozen build fails with `No module named
'xarray'` or a backend error **even when xarray is installed**, because xarray:

- imports submodules dynamically (like rasterio), and
- discovers its I/O backends (`netCDF4`, `scipy`, `h5netcdf`, …) through **entry
  points stored in its package metadata**, and
- reads its own version from that metadata at import time.

So `collect_submodules('xarray')` alone is **not enough** — you must also copy the
metadata with `copy_metadata('xarray')`, or backend discovery and version lookup
fail at runtime.

Add `copy_metadata` to the hooks import and collect all three pieces:

```python
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata

xarray_hiddenimports = collect_submodules('xarray')
xarray_datas = collect_data_files('xarray') + copy_metadata('xarray')
```

Then fold them into the spec's `hiddenimports` and `datas`:

```python
hiddenimports = rasterio_hiddenimports + xarray_hiddenimports + cwatm_hiddenimports + [ ... ]
datas += xarray_datas
```

Notes:
- Make sure the **netCDF4 backend** is importable: keep `'netCDF4'` in
  `hiddenimports` (xarray opens `.nc` files through it). `collect_submodules('xarray')`
  already includes `xarray.backends.netCDF4_`.
- A build-time warning like *"Failed to collect submodules for 'xarray.tests'
  because ... No module named 'pytest'"* is **harmless** — test modules are not
  needed and are skipped.
- The same `copy_metadata(...)` step applies to **any** dependency that resolves
  plugins via entry points or reads its version from metadata (e.g. some uses of
  `pyproj`, `fiona`, packages built on `importlib.metadata`). If a frozen app
  raises `importlib.metadata.PackageNotFoundError` or "no backends found", add
  `copy_metadata('<that_package>')`.

---

## Build & verify

```powershell
# from the project folder, with the venv active
.\venv\Scripts\Activate.ps1
pyinstaller <specfile>.spec --noconfirm

# run it
.\dist\<name>\<name>.exe        # one-folder build
# or
.\dist\<name>.exe               # one-file build
```

**Verification checklist:**
- The exe launches with no `ModuleNotFoundError: rasterio.*`.
- No `gdalvrt.xsd (GDAL_DATA is not defined)` message.
- A real raster operation works end-to-end (load a `.tif`, sample/warp, write).
- For the GUI: window opens, no console flash (release build), plotting works if
  applicable.

- xarray opens/reads a NetCDF file without `No module named 'xarray'`,
  `PackageNotFoundError`, or "found no backends".

If a **different** `ModuleNotFoundError` appears after this, it is another
dynamically-imported package — add `collect_submodules('<that_package>')` to
`hiddenimports` (and `collect_data_files('<that_package>')` if it has data), then
rebuild. If instead you get a metadata / backend error, add
`copy_metadata('<that_package>')`. This is the same fix pattern, just for a
different package.

---

## Quick reference — what to change

| Symptom | Root cause | Fix |
|---|---|---|
| `ModuleNotFoundError: rasterio.sample` (or `._shim`, `.vrt`, …) | rasterio submodules imported dynamically, not bundled | `hiddenimports = collect_submodules('rasterio')` in spec |
| `Cannot find gdalvrt.xsd (GDAL_DATA is not defined)` | GDAL data not bundled into the exe | `datas += collect_data_files('rasterio')` in spec |
| `No module named 'xarray'` / backend / `PackageNotFoundError` (xarray installed) | xarray submodules + entry-point metadata not bundled | `collect_submodules('xarray')` **and** `collect_data_files('xarray') + copy_metadata('xarray')` |
| Tempted to `pip install GDAL-*.whl` | Not needed; rasterio carries its own GDAL | Don't; consider `pip uninstall gdal` to avoid dual-GDAL conflict |
| Console window behind GUI | `console=True` in EXE() | Set `console=False` for release GUI build |
| Qt platform plugin not found | Qt plugins/data not bundled | `collect_submodules`/`collect_data_files` for the Qt binding |
