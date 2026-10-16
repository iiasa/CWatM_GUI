# CWatM GUI — build, packaging & dependencies

Developer reference for producing `CWatM_GUI.exe`, `CWatM_model.exe`,
`CWatM_GUI_Setup.exe` and the Microsoft Store package. The short version (commands + the never-build-on-P: rule) is in
`CLAUDE.md`; history of past build regressions is in
[`CWatM_GUI_History.md`](CWatM_GUI_History.md).

## Dependencies — packaging notes
- **pyshp** (`shapefile`) — Show Basin's and NetCDF's File ▸ Load shape: reads an ESRI
  `.shp` as GeoJSON, pure Python, no GDAL/fiona; imported lazily at the call site.
- **dask** (`xr.open_dataset(path, chunks={})` in the NetCDF viewer) — parallelises
  chunked point-series reads for Total Timeseries / Flow duration / Flow regime on a
  large `.nc`; trimmed in the frozen build (below).
- **notebooklm-py** + **playwright** — CWatM AI and its login (needs Python ≥ 3.10).
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
  `filelock`, `playwright`/`greenlet`/`pyee` (+ `copy_metadata` for the version-reading
  ones). playwright has **no PyInstaller hook**: `collect_all` brings its driver
  (`node.exe` + package, ~105 MB) as data. **Login** works frozen through the exe's
  `--notebooklm-browser-login <browser>`
  self-dispatch, opening the **installed** browser — nothing downloaded. `rookiepy` is
  excluded (no browser cookies are read).- **MODFLOW coupling** (`flopy` + its `matplotlib` stack — `contourpy`/`kiwisolver`/
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
| `msix` | The Microsoft Store package `installer\Output\CWatM_GUI_<version>_x64.msix` from the same `dist\CWatM_GUI` — see [Microsoft Store (MSIX)](#microsoft-store-msix--installermsix) below. Skipped with a warning while `installer\msix\store_identity.json` is empty. |
| `copyback` | `dist\CWatM_GUI` → `P:\…\gui\dist\CWatM_GUI` (`/MIR`), the setup and the `.msix` → `P:\…\gui\installer\Output\`. The only P: write of the build. |

**Signing and checksums** (`security.md` #3): with a code-signing thumbprint in
`CWATM_SIGN_THUMBPRINT` (or `-SignThumbprint`) the script signs both exes after the
build and the setup after Inno Setup (`Invoke-Sign`: signtool, SHA-256, RFC 3161
timestamp); without one it prints "NOT signed" and continues. `/creategui`'s
`publish_gui.ps1` checks each published file's SHA-256 and writes **`SHA256SUMS.txt`**
next to the setup and zip in `P:\watmodel\CWatM_GUI`.

## Microsoft Store (MSIX) — `installer/msix/`
**Why.** `CWatM_GUI_Setup.exe` is unsigned, so Windows 11's **Smart App Control** blocks
it outright (no "Run anyway"), and SmartScreen warns where Smart App Control is off.
Smart App Control also checks every DLL/`.pyd` the app loads, so signing only the setup
and the two exes would not be enough. The Store route avoids buying a certificate:
the package is uploaded **unsigned**, Microsoft signs it after certification, the Store
delivers the updates, and Store installs pass Smart App Control. Registration in Partner
Center is free for companies as well as individuals.

**What the package is.** The unchanged one-folder build `dist\CWatM_GUI` plus
`AppxManifest.xml`, `Images\` and `resources.pri`. The spec and the PyInstaller build
are the same for both channels; the Inno Setup installer is still built alongside.

| File | Role |
|------|------|
| `installer/msix/AppxManifest.xml` | Template. The `msix` step fills `{{IDENTITY_NAME}}`, `{{PUBLISHER}}`, `{{PUBLISHER_DISPLAY_NAME}}`, `{{VERSION}}` (XML-escaped), refuses a leftover token and checks the result parses. |
| `installer/msix/store_identity.json` | The three values from **Partner Center ▸ Product management ▸ Product identity**: `Package/Identity/Name` → `IdentityName`, `Package/Identity/Publisher` → `Publisher`, `Package/Properties/PublisherDisplayName` → `PublisherDisplayName`. Public values (every package carries them), so they are committed. |
| `installer/msix/Images/` | The logo set, committed. `python installer/msix/make_images.py` regenerates it from `assets/cwatm_small.ico` (its hand-made 16–48 px frames are used as they are). |
| `src/gui/utils/msix.py` | `is_packaged()` (kernel32 `GetCurrentPackageFullName`, cached) and `MODEL_ALIAS`. |

**The `msix` step** (needs the Windows SDK: `makepri.exe`, `makeappx.exe`, found like
`signtool.exe`, newest SDK first):
1. `dist\CWatM_GUI` → `<Work>\msix\layout` (`/MIR`), plus `Images\` and the filled manifest.
2. `makepri` → `layout\resources.pri`, which maps the qualified logo files
   (`scale-*`, `targetsize-*`, `altform-unplated`) to the names the manifest uses. It
   indexes the small `<Work>\msix\res` folder (manifest + `Images\` only), never the
   layout's thousands of build files, and the `<packaging>` section of `priconfig.xml`
   is removed so all variants stay in the one `resources.pri` (that section splits them
   into resource packs, which only a bundle carries).
3. `makeappx pack` → `<Work>\installer\Output\CWatM_GUI_<version>_x64.msix`, unsigned.
   Older `.msix` files there are removed; `copyback` copies the new one to the repo.

**Version.** `__version__ = "X.YZ"` becomes `X.YZ.<MsixBuild>.0`; each part is read as a
number, so keep `YZ` two digits (`1.05` → `1.5`, then `1.10` still sorts higher). The
Store needs a higher version for every upload: to resubmit the same `__version__` after a
packaging-only fix, run with `-MsixBuild 1` (2, …), and drop back to 0 when
`__version__` moves on. The last field stays 0; the Store reserves it.

**What the manifest declares.**
- `runFullTrust` (a classic Win32 app), x64, Windows 10 1809 or later.
- Application **`CWatMGUI`** (`CWatM_GUI.exe`): the Start menu entry; **"Open with" for
  `.ini`** (like the Inno task `iniassoc`, the default `.ini` handler stays untouched;
  the file arrives as `argv[1]`); execution alias **`CWatM_GUI.exe`**, so
  `CWatM_GUI.exe settings.ini` works from any console.
- Application **`CWatMModel`** (`_internal\CWatM_model.exe`, `AppListEntry="none"`):
  only there for its execution alias **`CWatM_model.exe`** (see Create batch below).
- No desktop shortcut: MSIX creates none; users pin from Start.

**Packaged-mode rules** (what differs when the GUI runs from the package):
- **The install folder is read-only** (`C:\Program Files\WindowsApps\…`). The app writes
  only to `%LOCALAPPDATA%`, QSettings and user-chosen folders (PathOut, the Journal
  folder, …) — keep it that way: nothing is ever written next to the exe or into
  `_internal` / `sys._MEIPASS`.
- **AppData and HKCU writes are redirected per package.** `gui.log`, the default Journal
  folder and the web cache land in
  `%LOCALAPPDATA%\Packages\<package family>\LocalCache\Local\CWatM_GUI`, QSettings in the
  package's private registry. The GUI itself sees them at the usual paths; Explorer and
  other programs see the real location. A Store copy and an Inno-installed copy
  therefore keep separate settings. The OS keyring (stored login) and
  `%USERPROFILE%\.notebooklm` are outside AppData and shared.
- **AppUserModelID**: the package assigns it, so `cwatm_gui._set_windows_app_id`
  returns early when `msix.is_packaged()`; our own ID would split the taskbar button
  from the Start entry and the pinned icon.
- **Create batch**: a `.bat` outside the package starts the model through its execution
  alias, so `batch_file_creator.build_batch_script` writes `"CWatM_model.exe"` (found on
  PATH via `%LOCALAPPDATA%\Microsoft\WindowsApps`) when packaged. The GUI itself keeps
  starting `_internal\CWatM_model.exe` by its path (`model_command`).
- The Chromium sandbox stays on: `WindowsApps` is a local path (`web_assets`).

### Trying the package locally
Works before the Partner Center account exists. After a build:

```powershell
pwsh -NoProfile -Command "& '.\build_release.ps1' -Steps msix -MsixTestIdentity"
```

This writes only the layout, with the placeholder identity `IIASA.CWatMGUI.LocalTest`
(distinct from the Store identity, so it never collides with a Store install). With
**Developer Mode** on (Settings ▸ System ▸ For developers):

```powershell
Add-AppxPackage -Register 'C:\work\CWatM_GUI\msix\layout\AppxManifest.xml'   # install
Get-AppxPackage IIASA.CWatMGUI.LocalTest | Remove-AppxPackage                  # remove
```

A registered layout runs from `C:\work\…`, so it shows the packaged behaviour (identity,
icons, aliases, Open with, redirected AppData) but neither the read-only `WindowsApps`
folder nor Smart App Control: those two only a Store install shows.

**Checklist** (local layout, and again for the first Store install): starts with the
CWatM icon on the taskbar and Start; a model run with Stop; Show Basin and NetCDF (the
QtWebEngine windows); Create batch, then double-click the `.bat`; right-click an `.ini`
▸ Open with ▸ CWatM GUI; `CWatM_GUI.exe <ini>` in a console; CWatM AI login; account
login and Stay logged in.

### Publishing in Partner Center
Once:
1. **Account**: register IIASA as a **company** in [Partner Center](https://partner.microsoft.com/dashboard)
   (Apps and games), signing in with an IIASA (Entra ID) work account. A D-U-N-S number
   makes the business verification quicker; without one, upload registry documents.
2. **Apps and games ▸ New product ▸ MSIX or PWA app**, reserve the name **CWatM GUI**.
3. **Product management ▸ Product identity**: copy the three values into
   `installer/msix/store_identity.json` and commit.

Each release:
1. Bump `__version__`, run the full build (`msix` is in the default steps) →
   `installer\Output\CWatM_GUI_<version>_x64.msix`.
2. **Start a submission**:
   - **Pricing and availability**: free. For the first submission choose **Private
     audience** (or keep the listing hidden), to test the Store install before it is public.
   - **Properties**: category (e.g. Education); **privacy policy URL**, required because
     the optional CWatM account stores a username and email. The in-app privacy notice
     (`CWatM_Account_Privacy.md`) is still a draft awaiting IIASA review, so publish the
     approved text at a URL first. Website `https://cwatm.iiasa.ac.at`.
   - **Age ratings**: the IARC questionnaire.
   - **Packages**: upload the `.msix`. Partner Center rejects it when Identity or
     Publisher differ from Product identity.
   - **Store listing**: description, at least one desktop screenshot (1366×768 or
     larger), the Store logos.
   - **Submission options**: the runFullTrust justification and notes for certification,
     e.g.: *"CWatM GUI is a classic Win32 desktop application (Python and Qt, frozen with
     PyInstaller) for the Community Water Model, a hydrological model developed at IIASA.
     It needs runFullTrust because it starts its own model executable as a child process
     and reads and writes model input and output files in folders the user chooses.
     Every feature works without an account; the optional CWatM account adds points and
     badges only. Model runs need the user's own CWatM input data; settings files can be
     opened and edited without it."*
3. After certification: install from the Store on a machine with **Smart App Control
   on**, go through the checklist above, then switch the visibility to public.

A packaging-only fix of a published version: `-MsixBuild 1`, new submission.
