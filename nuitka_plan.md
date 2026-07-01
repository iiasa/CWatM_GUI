# Plan: faster runtime for the CWatM GUI with Nuitka

A roadmap for producing a Nuitka build of the CWatM GUI (PySide6 + rasterio +
xarray + netCDF4 + cwatm) on Windows / Python 3.8. **This is a plan — nothing here
has been executed.** Keep the working PyInstaller specs as-is; Nuitka is a parallel
build path until it is proven.

---

## 0. Expectations first

- Nuitka **compiles to C**, so build time is *longer* than PyInstaller, but the
  resulting app **starts and runs faster** — especially the pure-Python parts (the
  CWatM model loop in `cwatm/...` and the GUI logic).
- It will **not** speed up `numpy` / `scipy` / `rasterio` / `netCDF4` work — those
  are already compiled C. The realistic win is faster startup + faster
  Python-level computation, not faster raster/array math.
- If the goal is faster *build* time, Nuitka is the wrong tool (see
  `makeitfaster.md`: UPX off + warm cache). Nuitka is for faster *runtime*.

---

## 1. Prerequisites (one-time)

1. **C compiler.** Nuitka needs one. On Windows + Python 3.8 the simplest is to let
   Nuitka auto-download MinGW64 (`--mingw64`); the alternative is installed MSVC
   2019 Build Tools. This is the biggest setup variable.
2. **Install into the current `venv`** (the one with rasterio + xarray + netCDF4 +
   PySide6 — the old `build_env` is gone):
   ```
   python -m pip install nuitka zstandard ordered-set
   ```
   (`zstandard` = onefile compression, `ordered-set` = faster compile.)

---

## 2. Inventory — what must be force-included

Mirror everything the PyInstaller specs already handle, mapped to Nuitka flags:

| Need | Spec equivalent | Nuitka flag |
|---|---|---|
| PySide6 + Qt plugins | `PySide6.*` hiddenimports | `--enable-plugin=pyside6` |
| rasterio dynamic submodules | `collect_submodules('rasterio')` | `--include-package=rasterio` |
| rasterio GDAL/PROJ data | `collect_data_files('rasterio')` | `--include-package-data=rasterio` |
| xarray submodules | `collect_submodules('xarray')` | `--include-package=xarray` |
| xarray data | `collect_data_files('xarray')` | `--include-package-data=xarray` |
| **xarray entry-point metadata** | `copy_metadata('xarray')` | `--include-distribution-metadata=xarray` |
| netCDF4 backend | `'netCDF4'` hiddenimport | `--include-package=netCDF4` |
| cwatm package + data | `collect_submodules('cwatm')` + `('cwatm','cwatm')` | `--include-package=cwatm --include-package-data=cwatm` |
| GUI source package | `('src','src')` | `--include-package=src` |
| assets (icons/images) | `('assets/*','assets')` | `--include-data-dir=assets=assets` |
| routing `t5*.dll` etc. | binaries list | `--include-data-files=cwatm/hydrological_modules/routing_reservoirs/t5.dll=cwatm/hydrological_modules/routing_reservoirs/t5.dll` (one per file) |

---

## 3. Draft command — start with one-folder (standalone)

```
python -m nuitka ^
  --standalone ^
  --mingw64 ^
  --enable-plugin=pyside6 ^
  --include-package=cwatm --include-package-data=cwatm ^
  --include-package=src ^
  --include-package=rasterio --include-package-data=rasterio ^
  --include-package=xarray --include-package-data=xarray ^
  --include-distribution-metadata=xarray ^
  --include-package=netCDF4 ^
  --include-data-dir=assets=assets ^
  --windows-icon-from-ico=assets/cwatm.ico ^
  --windows-console-mode=disable ^
  --output-dir=build_nuitka ^
  cwatm_gui.py
```

Output: `build_nuitka\cwatm_gui.dist\cwatm_gui.exe`.

- **Use `--standalone` (one-folder) first**, not `--onefile`. Onefile adds
  compression + an unpack-on-launch step that slows both build and startup. Switch
  to `--onefile` only for the final release artifact.
- For maximum runtime speed on the release build, add `--lto=yes` (link-time
  optimization — slower compile, faster binary).

---

## 4. Known tricky bits to plan for

1. **Splash screen:** the code's `import pyi_splash` is PyInstaller-only (already
   wrapped in `try/except`, so it no-ops under Nuitka). Nuitka has its own onefile
   splash via `--onefile-windows-splash-screen-image=assets/cwatm.png` — only
   relevant if/when you go onefile.
2. **Dynamic imports Nuitka can't see:** if a `ModuleNotFoundError` appears at
   runtime, add `--include-module=<name>` (single module) or
   `--include-package=<name>` (whole package) — same triage logic as the spec's
   hiddenimports.
3. **Data / metadata errors:** xarray backend error or `PackageNotFoundError` →
   confirm `--include-distribution-metadata=xarray` is present; other entry-point
   packages need their own `--include-distribution-metadata=<pkg>`.
4. **rasterio DLLs:** Nuitka's standalone dependency walker normally pulls
   `rasterio.libs\gdal-*.dll` automatically; verify they landed in the `.dist`
   folder, else add `--include-data-files`.
5. **First compile is slow** (many minutes). Nuitka bundles `ccache`, so
   subsequent rebuilds are much faster — don't wipe `build_nuitka` between
   iterations.

---

## 5. Verify (same checklist as the PyInstaller build)

Run `build_nuitka\cwatm_gui.dist\cwatm_gui.exe` and confirm:

- GUI window opens, no console window.
- No `ModuleNotFoundError` (rasterio.*, xarray, etc.).
- No `gdalvrt.xsd / GDAL_DATA` message; load a `.tif` in the basin viewer.
- xarray opens a `.nc` file (the netCDF4 backend resolves).
- Run a short CWatM job end-to-end.
- **A/B the runtime** vs the PyInstaller build (startup time + a timed model run)
  to confirm the gain justifies the longer builds.

---

## 6. Suggested rollout

1. Get `--standalone --mingw64` building and passing the checklist.
2. Add `--lto=yes` and re-time for the release build.
3. Only then try `--onefile` (+ splash flag) if a single-file artifact is wanted.
4. Save the final command as `build_nuitka.bat` next to the specs so it is
   repeatable.

---

## 7. Open decisions before running

1. **Compiler:** auto-MinGW (`--mingw64`, zero setup) vs MSVC (needs Build Tools
   installed, often better Windows compatibility). The draft defaults to MinGW.
2. **Effort vs payoff:** this is heavier than the PyInstaller tuning in
   `makeitfaster.md`. Worth it only if *runtime* speed is the goal.
