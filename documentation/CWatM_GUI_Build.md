# CWatM GUI — build, packaging & dependencies

Developer reference for producing `CWatM_GUI.exe`, `CWatM_model.exe` and
`CWatM_GUI_Setup.exe`. The short version (commands + the never-build-on-P: rule) is in
`CLAUDE.md`; history of past build regressions is in
[`CWatM_GUI_History.md`](CWatM_GUI_History.md).

## Dependencies — packaging notes
- **pyshp** (`shapefile`) — Show Basin's and NetCDF's File ▸ Load shape: reads an ESRI
  `.shp` as GeoJSON, pure Python, no GDAL/fiona; imported lazily at the call site.
- **dask** (`xr.open_dataset(path, chunks={})` in the NetCDF viewer) — parallelises
  chunked point-series reads for Total Timeseries / Flow duration / Flow regime on a
  large `.nc`; trimmed in the frozen build (below).
- **notebooklm-py[cookies]** (+ `rookiepy`) — CWatM AI (needs Python ≥ 3.10).
- **supabase** (supabase-py 2.31, reuses httpx) + **keyring** (+ `pywin32-ctypes` on
  Windows, `SecretStorage`/`jeepney` on Linux) — the optional CWatM account; imported
  lazily by `account_client.py` / `account_store.py` only. Bundled into the **GUI exe
  only** (`account_*` in `cwatm_gui_dir.spec`, excluded from `CWatM_model.exe`).
  **keyring has no PyInstaller hook** — the spec collects its backends, its dist
  metadata (backend discovery reads the `keyring.backends` entry points) and
  `win32ctypes`, without which the frozen exe silently never remembers a login.
- **GDAL**: do **not** install the GDAL wheel — the rasterio wheel ships its own GDAL
  (`rasterio.libs/`). A GDAL-less rasterio borrowing the `osgeo` DLL breaks when GDAL is
  removed (`ImportError: DLL load failed while importing _base`); cure:
  `pip install --force-reinstall --no-deps rasterio`. Full note at the top of
  `requirements.txt`.

## Virtual environment & launchers
- The project venv is **`venv/`** (`venv\Scripts\python.exe`; activate via
  `venv\Scripts\Activate.ps1`).
- **`gui.bat`** / **`gui.vbs`** start `cwatm_gui.py` with the venv's **`pythonw.exe`**
  (no console window); `gui.bat` uses `start ""` (brief flash), `gui.vbs` runs fully
  hidden. Both resolve paths from their own folder (`%~dp0` / `ScriptFullName`) and
  forward args. Because pythonw makes `sys.executable` = `pythonw.exe` (no std streams),
  the subprocess run worker forces the console **`python.exe`** for the model child
  (`cwatm_process_worker._console_python`); QProcess's default `CREATE_NO_WINDOW` keeps
  it from flashing a console.

## PyInstaller spec — `cwatm_gui_dir.spec`
The **one-folder** build (faster startup, easier debugging than a single-file exe).
- Collects rasterio + xarray submodules/data and `copy_metadata('xarray')`,
  `collect_all` for folium/branca/xyzservices and **plotly/narwhals**, the QtWebEngine
  hidden imports; `console=False`.
- **Code ships only in the PYZ** (`collect_submodules` for `cwatm` **and `src`**); the
  datas are just assets, `cwatm/metaNetcdf.xml`, the Help markdown + figures, the
  translation table and the `t6*` routing libraries, which land at
  `cwatm/hydrological_modules/routing_reservoirs/` (the path cwatm's `globals.py`
  resolves from `__file__`). `assets/badges/` has its own spec line (the `assets/*` glob
  does not reach a subfolder).
- **`openpyxl`** (`collect_submodules('openpyxl') + ['et_xmlfile']`) for **both** exes,
  never excluded: Tools ▸ Excel Crops/Reservoirs and cwatm's xlsx settings-sheet reads
  (`pd.read_excel`) import it lazily.
- **`requests`** (+ `certifi`/`urllib3`/`charset_normalizer`/`idna`) for the GUI's
  `osmtile://` tile/WMS fetching.
- **CWatM AI** (GUI exe only): `collect_all` for `notebooklm`,
  `httpx`/`httpcore`/`h11`/`anyio`/`sniffio`, `rich`, `markdown_it`/`mdurl`/`pygments`,
  `filelock`, `rookiepy` (+ `copy_metadata` for the version-reading ones). The
  **Login…** browser-cookie paths work frozen (the exe's `--notebooklm-login`
  self-dispatch + bundled `rookiepy`); the interactive Google-login window needs
  `playwright`, which is **not** bundled (source-run only; the button is hidden when
  frozen).
- **MODFLOW coupling** (`flopy` + its `matplotlib` stack — `contourpy`/`kiwisolver`/
  `cycler`/`fontTools`/`PIL`) is `collect_all`-ed into **both** exes (`modflow_*`);
  `matplotlib` is not excluded. `xmipy` + `bmipy` are hidden imports **only if `xmipy`
  is installed** (guarded by a real import in the spec). `black` (a `bmipy` dependency,
  never used at model runtime) is **excluded** from both exes. The GUI itself **never
  imports** flopy/xmipy — cwatm imports them in the model process when
  `modflow_coupling` is on.
- **`dask`** (GUI exe only, `collect_all`) is trimmed: `dask.dataframe`/`dask.bag`/
  `dask.tests` are filtered out of `hiddenimports` and `datas`
  (`_DASK_TRIM`/`_dask_module_kept`/`_dask_data_kept`, plus the same names in
  `excludes=`). `dask.array`, the scheduler/config and the root-level
  `dask.yaml`/`dask-schema.yaml` stay. **`dask.widgets` must NOT be trimmed** —
  `dask/array/core.py` imports `get_template` from it at module level.
- A **second executable, `CWatM_model.exe`**: the lightweight child the GUI spawns for
  every model run (no Qt; `console=True` for valid std pipes, started with
  `CREATE_NO_WINDOW`). Built with `contents_directory='.'` and **moved into
  `_internal/`** at the end of the spec — never rename `_internal` or the model exe's
  bootstrap breaks. The GUI looks for it in `_internal/` first, then the folder root.
- The spec's `_netsafe_copyfile` patch (SMB `OSError 22` on large writes) stays for
  anyone who runs PyInstaller directly on P:.

## Installer — `installer/CWatM_GUI.iss` (per-user, no admin)
An **Inno Setup 7** script packaging the one-folder build into **`CWatM_GUI_Setup.exe`**
(~260 MB, lzma2/max solid), `PrivilegesRequired=lowest` → `{autopf}` =
`%LOCALAPPDATA%\Programs`, user Start menu / desktop. A directory-picker page lets the
user change the folder. Copies **`dist\CWatM_GUI\*`** verbatim (`recursesubdirs
createallsubdirs`) so `_internal\` keeps its exact layout. Optional **[Tasks]**: desktop
shortcut, `.ini` **"Open with"** association (per-user `HKCU\Software\Classes` ProgID +
`OpenWithProgids` — does not hijack the default `.ini` handler; passes `"%1"`), launch
after install. The uninstaller leaves user data (QSettings, `%LOCALAPPDATA%\CWatM_GUI`).
Keep the fixed `AppId` GUID.
- `ISCC.exe` location differs per machine — probe `C:\Apps\Inno Setup 7\ISCC.exe` and
  `%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe`.

### Version — one source of truth
`__version__` in **`src/gui/__init__.py`** is the only place the version is written.
`main_window` imports it for the About dialog, and the `.iss` **scrapes that line** in
its preprocessor (`FileOpen`/`FileRead` loop → `Copy` between the quotes); if the line
is missing the compile **aborts** (`#error`). ISPP gotchas: assign with `#expr`, not
`#define`, inside a `#sub`, and the loop body goes **after** the `#for {…}` braces. Keep
the literal on one line as `__version__ = "X.YZ"`. The manual
(`CWatM_GUI_Documentation.md`: title header + §18) still needs its own edit per release.

## `build_release.ps1` — building on the local disk
The build runs in a **local working copy, `C:\work\CWatM_GUI`** (`-Work` overrides),
because PyInstaller + Inno Setup reading/writing ~950 MB over SMB dominates a release.

| Step | What it does |
|------|--------------|
| `venv` | Mirrors the repo `venv\` to `C:\work\CWatM_GUI\venv` **once** (1.3 GB); `-ForceVenv` re-mirrors after a `pip install`. Works because the venv's `home` is the local `C:\Python312`; the script always invokes `venv\Scripts\python.exe -m PyInstaller`. |
| `sync` | Robocopy `/MIR` of `src`, `cwatm`, `assets`, `documentation`, `translations`, `installer` (minus `Output`) plus `cwatm_gui.py`, `cwatm_model.py`, `cwatm_gui_dir.spec`, `LICENSE`. |
| `build` | `python -m PyInstaller cwatm_gui_dir.spec --noconfirm`, then asserts `dist\CWatM_GUI\CWatM_GUI.exe` **and** `dist\CWatM_GUI\_internal\CWatM_model.exe` exist. |
| `installer` | `ISCC installer\CWatM_GUI.iss` (probing both ISCC paths). Spec and `.iss` resolve everything relative to themselves, so the local copy builds exactly what the repo would. |
| `copyback` | `dist\CWatM_GUI` → `P:\…\gui\dist\CWatM_GUI` (`/MIR`) and the setup → `P:\…\gui\installer\Output\`. The only P: write of the build. |

**Signing and checksums** (`security.md` #3): with a code-signing thumbprint in
`CWATM_SIGN_THUMBPRINT` (or `-SignThumbprint`) the script signs both exes after the
build and the setup after Inno Setup (`Invoke-Sign`: signtool, SHA-256, RFC 3161
timestamp); without one it prints "NOT signed" and continues. `/creategui`'s
`publish_gui.ps1` checks each published file's SHA-256 and writes **`SHA256SUMS.txt`**
next to the setup and zip in `P:\watmodel\CWatM_GUI`.
