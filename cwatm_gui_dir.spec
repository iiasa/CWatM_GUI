# -*- mode: python ; coding: utf-8 -*-

import os
import sys

# --- Windows network-drive (SMB) copy fix ------------------------------------
# This project lives on a mapped network share (P: -> \\pdrive\...). Python 3.8's
# shutil.copyfile uses _copyfileobj_readinto (memoryview writes) which fails with
# "OSError: [Errno 22] Invalid argument" when writing large files (plotly.min.js,
# QtWebEngine DLLs, ICU data) to an SMB share during the COLLECT phase. Replace
# copyfile with a plain, small-chunk copy that works on network drives.
import shutil as _shutil
def _netsafe_copyfile(src, dst, *, follow_symlinks=True):
    if os.path.abspath(src) == os.path.abspath(dst):
        raise _shutil.SameFileError(f"{src!r} and {dst!r} are the same file")
    with open(src, 'rb') as _fsrc, open(dst, 'wb') as _fdst:
        while True:
            _buf = _fsrc.read(512 * 1024)
            if not _buf:
                break
            _fdst.write(_buf)
    _shutil.copymode(src, dst)
    return dst
_shutil.copyfile = _netsafe_copyfile

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata, collect_all

# rasterio imports several submodules dynamically (rasterio.sample, rasterio._shim,
# rasterio.vrt, ...) which PyInstaller's static analysis cannot see. Collect them all,
# plus rasterio's bundled GDAL/PROJ data (gdal_data/proj_data) so the frozen GUI does
# not fail with "ModuleNotFoundError: rasterio.sample" or
# "Cannot find gdalvrt.xsd (GDAL_DATA is not defined)". rasterio ships its own GDAL,
# so the osgeo/GDAL wheel is not needed (see cwtmexe.md).
rasterio_hiddenimports = collect_submodules('rasterio')
rasterio_datas = collect_data_files('rasterio')

# rasterio's OWN GDAL (this venv's rasterio wheel bundles it via delvewheel) lives in a
# SIBLING `rasterio.libs/` directory - not inside the package - so PyInstaller does NOT
# collect it automatically (no hook; collect_dynamic_libs misses the sibling dir). Without
# these DLLs the frozen app dies with "ImportError: DLL load failed while importing _base".
# rasterio/__init__.py's delvewheel patch adds `<parent>/rasterio.libs` to the DLL search
# path at import, and when frozen the rasterio package sits in `_internal/rasterio/`, so the
# DLLs must land in `_internal/rasterio.libs/`. This is what replaced the old osgeo/GDAL wheel
# that rasterio used to borrow its GDAL from (see runtime_speedup.md T4).
import sysconfig as _sysconfig
import glob as _glob
_rasterio_libs_dir = os.path.join(_sysconfig.get_paths()['purelib'], 'rasterio.libs')
rasterio_lib_binaries = [(_p, 'rasterio.libs')
                         for _p in _glob.glob(os.path.join(_rasterio_libs_dir, '*.dll'))]
if not rasterio_lib_binaries:
    print("[spec] WARNING: no rasterio.libs GDAL DLLs found at %s - the frozen app "
          "will fail to import rasterio. Reinstall rasterio from a wheel that bundles "
          "GDAL: pip install --force-reinstall --no-deps rasterio" % _rasterio_libs_dir)
else:
    print("[spec] bundling %d rasterio.libs GDAL DLLs from %s"
          % (len(rasterio_lib_binaries), _rasterio_libs_dir))

# xarray loads its backends (netCDF4, scipy, ...) dynamically via entry points and
# reads its own version from package metadata. Collect its submodules and data, and
# copy its dist metadata so the backend plugins are discoverable in the frozen app,
# otherwise the GUI fails with "No module named 'xarray'" / backend errors.
xarray_hiddenimports = collect_submodules('xarray')
xarray_datas = collect_data_files('xarray') + copy_metadata('xarray')

# folium / branca / xyzservices ship Jinja2 templates and JSON data that PyInstaller
# does not pick up automatically - collect everything for them (basin viewer OSM map).
# plotly / narwhals ship a large bundled plotly.js and package data used by the
# Analyse > Timeseries plot - collect them too.
folium_datas, folium_binaries, folium_hiddenimports = [], [], []
for _pkg in ('folium', 'branca', 'xyzservices', 'plotly', 'narwhals'):
    _d, _b, _h = collect_all(_pkg)
    folium_datas += _d
    folium_binaries += _b
    folium_hiddenimports += _h
# plotly/narwhals read their version from dist metadata at import - copy it too.
folium_datas += copy_metadata('plotly') + copy_metadata('narwhals')

# openpyxl (+ et_xmlfile): the Excel menu (Excel > Crops / Reservoirs -
# excel_sheet_window.py) reads/writes xlsx workbooks with openpyxl, and cwatm reads
# xlsx settings sheets at runtime via pd.read_excel. openpyxl pulls its submodules
# lazily (openpyxl.reader.excel, openpyxl.writer, openpyxl.styles, ...) and both those
# call sites are lazy imports, so collect openpyxl explicitly for BOTH exes rather than
# trusting static analysis. (openpyxl does not read its version from metadata, so no
# copy_metadata is needed.)
openpyxl_hiddenimports = collect_submodules('openpyxl') + ['et_xmlfile']

# requests (+ its lazy TLS/encoding deps): the app-lifetime osmtile:// scheme handler
# fetches OSM tiles / WMS imagery with Python requests (Show Basin + NetCDF maps).
requests_hiddenimports = ['requests', 'certifi', 'urllib3', 'charset_normalizer', 'idna']

# CWatM AI (Gemini NotebookLM) + markdown answer rendering.
# - notebooklm-py is a fully ASYNC httpx RPC client (no Playwright at runtime); it
#   reads its own version from dist metadata and pulls anyio/httpcore/h11/rich lazily.
# - markdown_it (markdown-it-py) renders the answers; rich also depends on it.
# NOTE (source-run only, degrades gracefully when frozen): the **Login…** flow shells
# out to `python -m notebooklm` / `playwright` / rookiepy via QProcess - that is NOT
# bundled (the window shows a manual-command message when frozen). Asking questions
# with an already-stored session and markdown rendering both work frozen.
ai_datas, ai_binaries, ai_hiddenimports = [], [], []
# rookiepy = the browser-cookie reader used by `notebooklm login --browser-cookies`;
# bundling it lets the CWatM AI Login… work from the frozen exe (via the exe's own
# --notebooklm-login self-dispatch), reading the Google session from Firefox/Chrome/
# Edge without needing a Python install. (The Google-login *window* still needs
# Playwright, which is not bundled - that path stays source-only.)
for _pkg in ('notebooklm', 'httpx', 'httpcore', 'h11', 'anyio', 'sniffio',
             'rich', 'markdown_it', 'mdurl', 'pygments', 'filelock', 'rookiepy'):
    try:
        _d, _b, _h = collect_all(_pkg)
        ai_datas += _d
        ai_binaries += _b
        ai_hiddenimports += _h
    except Exception as _e:
        print(f"[spec] optional AI package not collected: {_pkg} ({_e})")
# Packages that read their version from dist metadata at import time.
for _meta in ('notebooklm-py', 'httpx', 'anyio', 'rich', 'markdown-it-py'):
    try:
        ai_datas += copy_metadata(_meta)
    except Exception as _e:
        print(f"[spec] metadata not copied: {_meta} ({_e})")
# notebooklm's CLI (run in-process by the frozen exe for Login…) is built on click;
# make sure it and rookiepy are in the graph even if static analysis misses them.
ai_hiddenimports += ['click', 'rookiepy']

# MODFLOW coupling: flopy (CWatM<->MODFLOW) + its matplotlib plotting stack and xmipy.
# Bundled so a MODFLOW-coupled run works frozen; because flopy imports matplotlib, the
# whole stack (matplotlib -> contourpy / kiwisolver / cycler / fontTools / PIL) is
# collected and matplotlib is NO LONGER excluded below. The GUI only *imports* flopy
# when Configure > Use Modflow is ON (src/gui/utils/modflow.py), and cwatm imports it
# only when a settings file enables modflow_coupling - so bundling it does not slow a
# normal (non-MODFLOW) start; it just makes the library available when needed.
modflow_datas, modflow_binaries, modflow_hiddenimports = [], [], []
for _pkg in ('flopy', 'matplotlib', 'contourpy', 'kiwisolver', 'PIL', 'fontTools'):
    try:
        _d, _b, _h = collect_all(_pkg)
        modflow_datas += _d
        modflow_binaries += _b
        modflow_hiddenimports += _h
    except Exception as _e:
        print(f"[spec] optional MODFLOW package not collected: {_pkg} ({_e})")
modflow_hiddenimports += ['flopy', 'matplotlib', 'cycler']
# xmipy (+ bmipy): cwatm imports xmipy with flopy under modflow_coupling (run_cwatm.py),
# which static analysis misses; xmipy needs bmipy. Both are single-module-ish and
# collect_all yields little, so add them as explicit hidden imports ONLY if xmipy is
# really installed (a bare hidden import for a missing module just warns). If absent,
# MODFLOW coupling runs will need `pip install xmipy` before a rebuild. `black` (a bmipy
# dependency used only by its code-render CLI, never at model runtime) is EXCLUDED below
# to keep the bundle lean.
try:
    import xmipy as _xmipy_probe  # noqa: F401
    modflow_hiddenimports += ['xmipy', 'bmipy']
    print("[spec] bundling xmipy + bmipy (MODFLOW coupling)")
except Exception:
    print("[spec] xmipy not installed - MODFLOW coupling needs it (pip install xmipy); "
          "not bundled")

# QtWebEngine (OpenStreetMap view). These hidden imports trigger the PySide6 hooks
# that bundle QtWebEngineProcess.exe, the web resources, ICU data and translations.
webengine_hiddenimports = [
    'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebChannel',
    'PySide6.QtNetwork',
    'PySide6.QtPrintSupport',
]

# Get the directory of this spec file
spec_root = os.path.dirname(os.path.abspath(SPEC))

# Collect all cwatm submodules
cwatm_hiddenimports = collect_submodules('cwatm')

# Collect all GUI submodules explicitly. Since §4.2 the src/ tree is no longer
# shipped as datas (which used to double as an import fallback via sys.path),
# so every module - including the lazily imported ones (§4.1: basin_viewer,
# check_data_window, analysis_*) - must be in the PYZ.
src_hiddenimports = collect_submodules('src')

# Additional hidden imports for CWatM and GUI dependencies
hiddenimports = rasterio_hiddenimports + xarray_hiddenimports + cwatm_hiddenimports + src_hiddenimports + [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'py_splash',
    'numpy',
    'pandas',
    'scipy',
    'netCDF4',
    'cftime',   # netCDF/xarray time decoding (non-standard calendars, num2date)
    'configparser',
    'xml.dom.minidom',
    'difflib',
    'calendar',
    'math',
    'threading',
    'gc',
    'time',
    'datetime',
    'importlib',
    'platform',
    'ctypes',
    'warnings',
    'decimal',
    'contextmanager',
    're',
    'glob',
    'sys',
    'os',
    'io'
]
hiddenimports += folium_hiddenimports + webengine_hiddenimports
hiddenimports += openpyxl_hiddenimports + requests_hiddenimports
hiddenimports += ai_hiddenimports  # CWatM AI (notebooklm) + markdown rendering
hiddenimports += modflow_hiddenimports  # MODFLOW coupling (flopy + matplotlib stack)

# Data files to include.
# §4.2: do NOT ship the whole cwatm/ and src/ trees - their code is already
# compiled into the PYZ via collect_submodules; bundling the trees as datas
# duplicated every .py (plus stray __pycache__/ working files) and made the
# folder bigger and slower to cold-start (more files for the OS/AV to touch).
# Only the non-code data cwatm reads at runtime is included:
#   - metaNetcdf.xml (editor hover tooltips + Analyse windows + model output)
#   - the t5 routing libraries (added under `binaries` below, at the package
#     path where cwatm/management_modules/globals.py resolves them via __file__)
datas = [
    # Include assets
    (os.path.join(spec_root, 'assets', '*'), 'assets'),
    (os.path.join(spec_root, 'cwatm', 'metaNetcdf.xml'), 'cwatm'),
    # Documentation shown by the Help menu
    (os.path.join(spec_root, 'documentation', 'CWatM_GUI_Documentation.md'), 'documentation'),
    (os.path.join(spec_root, 'documentation', 'CWatM_GUI_Features.md'), 'documentation'),
    (os.path.join(spec_root, 'documentation', 'CWatM_GUI_FAQ.md'), 'documentation'),
    # Screenshots referenced by the Help markdown (figures/*.png) - the Help viewer
    # sets its base URL to the documentation folder, so relative refs resolve here.
    (os.path.join(spec_root, 'documentation', 'figures', '*.png'), 'documentation/figures'),
]
# Include rasterio's bundled GDAL/PROJ data files
datas += rasterio_datas
# Include xarray's data files and package metadata (for backend discovery)
datas += xarray_datas
# Include folium/branca/xyzservices templates and data (OSM map)
datas += folium_datas
# Include CWatM AI package data + metadata (notebooklm, markdown_it, rich, ...)
datas += ai_datas
# Include MODFLOW coupling data (matplotlib mpl-data/fonts, flopy package data, ...)
datas += modflow_datas

# Binary files to include (DLLs and shared libraries)
binaries = list(folium_binaries)
# CWatM AI binaries (e.g. rookiepy's compiled cookie reader).
binaries += ai_binaries
# rasterio's bundled GDAL stack (rasterio.libs/*.dll -> _internal/rasterio.libs/).
# Shared by both exes: the model child also imports rasterio (cwatm reads .map/.tif).
binaries += rasterio_lib_binaries
# MODFLOW coupling binaries (matplotlib/contourpy/kiwisolver/PIL C-extensions, ...).
binaries += modflow_binaries

# Add routing reservoir binaries. globals.py builds the library path from its
# own __file__ (cwatm/management_modules/../hydrological_modules/routing_reservoirs),
# so the libraries MUST sit at that package path inside the bundle - a copy in
# the bundle root is never found.
routing_binaries_path = os.path.join(spec_root, 'cwatm', 'hydrological_modules', 'routing_reservoirs')
_routing_dest = 'cwatm/hydrological_modules/routing_reservoirs'
if os.path.exists(routing_binaries_path):
    binaries.extend([
        (os.path.join(routing_binaries_path, 't5.dll'), _routing_dest),
        (os.path.join(routing_binaries_path, 't5_linux.so'), _routing_dest),
        (os.path.join(routing_binaries_path, 't5_mac.so'), _routing_dest),
        (os.path.join(routing_binaries_path, 't5cyg.so'), _routing_dest),
    ])

a = Analysis(
    [os.path.join(spec_root, 'cwatm_gui.py')],
    pathex=[spec_root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Tkinter/Tcl: the PySide6 app never uses it. Exclude the C extension too
        # (_tkinter), otherwise a dependency pulling it in creates a partial bundle
        # that fails at runtime with "Failed to load Tcl DLL ... tcl86t.dll".
        'tkinter',
        '_tkinter',
        'Tkinter',
        'tcl',
        'tk',
        'PIL.ImageTk',
        # matplotlib is NO LONGER excluded: flopy (MODFLOW coupling) imports it, and it
        # is collected above (modflow_*). Only the Tk backend bits stay out via the
        # tkinter excludes.
        'IPython',
        'jupyter',
        'notebook',
        'PyQt5',
        'PyQt6',
        'wx',
        # black is only bmipy's code-render CLI formatter (not used at runtime); keep it
        # and its deps out of the bundle (bmipy imports it lazily, so this is safe).
        'black',
        # T-followup (runtime_speedup.md): notebooklm pulls in `playwright` (a ~101 MB
        # node driver) via its login CLI, but playwright is only ever imported lazily
        # inside the interactive Google-login window - a source-only path (the window
        # button is hidden when frozen). Asking questions (httpx) and the browser-cookie
        # login (rookiepy) never touch it, so exclude it to drop the 101 MB of waste.
        'playwright',
        # The CWatM AI 🎤 Voice dictation feature was removed, so its libraries are no
        # longer used or bundled - exclude them so a stray install can't re-add them.
        'speech_recognition', 'pyaudio', '_portaudio',
        # T4 (runtime_speedup.md): rasterio ships its own private GDAL, so the
        # separate `osgeo`/GDAL wheel is not needed (cwtmexe.md). If it is installed,
        # rasterio's guarded `import osgeo` makes PyInstaller bundle a SECOND ~95 MB
        # GDAL stack - excluded here so a stray reinstall can never re-bloat the build.
        'osgeo',
        # NOTE (§4.4): openpyxl/et_xmlfile must NOT be excluded - cwatm reads
        # xlsx settings sheets at runtime (pd.read_excel in initcondition.py /
        # lakes_reservoirs.py) and pandas needs openpyxl for that.
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
    # T6 (runtime_speedup.md): compile the PYZ at optimization level 1 (drop
    # `assert`/`__debug__` blocks) -> smaller bytecode, slightly faster module load.
    # Level 1 (not 2) keeps docstrings, which some libs read via __doc__.
    optimize=1,
)


# --- Second executable: CWatM_model.exe (subprocess model run, report §3.1) ---
# A lightweight child process the GUI spawns via QProcess for every model run:
# real Stop (kill), crash isolation, fresh interpreter state. No Qt/QtWebEngine/
# plotting imports, so it starts much faster than the GUI exe. console=True
# guarantees valid std pipes for the live output stream; QProcess starts it with
# CREATE_NO_WINDOW, so no console window ever appears. It shares this COLLECT
# folder (duplicate libraries are deduplicated by target name).
model_a = Analysis(
    [os.path.join(spec_root, 'cwatm_model.py')],
    pathex=[spec_root],
    binaries=binaries,
    datas=[],
    # rasterio MUST be included: cwatm/management_modules/data_handling.py imports it
    # at module level and calls rasterio.open() for .map/.tif masks. If it is excluded
    # here, the shared COLLECT folder still contains the _internal/rasterio/ *data*
    # directory (gdal_data/proj_data from the GUI exe), so `import rasterio` silently
    # resolves to an empty NAMESPACE package and the model dies at runtime with
    # "AttributeError: module 'rasterio' has no attribute 'open'" (wrapped in a
    # CWATMFileError for the mask file).
    # openpyxl included: cwatm reads xlsx settings sheets (reservoirs/crops) at runtime
    # via pd.read_excel, so the model child process needs it too.
    # + modflow_hiddenimports: the MODEL child process is what actually runs the
    # MODFLOW coupling (cwatm imports flopy when modflow_coupling is on), so flopy +
    # matplotlib must be in ITS graph too.
    hiddenimports=cwatm_hiddenimports + rasterio_hiddenimports + openpyxl_hiddenimports
                  + modflow_hiddenimports
                  + ['numpy', 'pandas', 'scipy', 'netCDF4', 'cftime'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PySide6', 'shiboken6',
        'tkinter', '_tkinter', 'Tkinter', 'tcl', 'tk', 'PIL.ImageTk',
        # matplotlib kept IN (flopy needs it); Qt/plot GUIs stay out.
        'IPython', 'jupyter', 'notebook', 'PyQt5', 'PyQt6', 'wx',
        'folium', 'branca', 'xyzservices', 'plotly', 'narwhals',
        # black = bmipy's render-CLI formatter, never used at model runtime.
        'black',
        # T4: same as the GUI exe - keep the separate osgeo/GDAL wheel out (rasterio
        # brings its own GDAL). Do NOT exclude rasterio - cwatm needs it.
        'osgeo',
        # notebooklm/playwright never run in the model child - exclude here too.
        'playwright', 'notebooklm',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
    # T6 (runtime_speedup.md): compile the PYZ at optimization level 1 (drop
    # `assert`/`__debug__` blocks) -> smaller bytecode, slightly faster module load.
    # Level 1 (not 2) keeps docstrings, which some libs read via __doc__.
    optimize=1,
)

# T9 (runtime_speedup.md): the Tcl/Tk runtime DLLs (tcl86t.dll / tk86t.dll, ~3.4 MB)
# in the GUI bundle turned out NOT to be dead weight - they are pulled in by the
# PyInstaller **Splash** screen below, which renders through Tk. Removing them breaks
# the splash, so they are kept. (The model exe has no splash and no Tk, so nothing to
# strip there.) Qt translations/resources are left alone too: QtWebEngine needs its
# locales/resources for the maps, and trimming them risks breaking Show Basin / NetCDF.

splash = Splash('assets/cwatm.png',
                binaries=a.binaries,
                datas=a.datas,
                text_pos=(10, 50),
                text_size=12,
                text_color='blue',
                always_on_top = False)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)
model_pyz = PYZ(model_a.pure, model_a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    splash,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    exclude_binaries=True,  # This must be True for onedir
    name='CWatM_GUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Set to False for windowed application
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Embed the multi-size icon (16..256 px) so Windows renders the CWatM icon in the
    # taskbar; cwatm.ico has only one large size and shows blank/generic at 16-32 px.
    icon=next((p for p in (
        os.path.join(spec_root, 'assets', 'cwatm_small.ico'),
        os.path.join(spec_root, 'assets', 'cwatm.ico'),
    ) if os.path.exists(p)), None),
    version_file=None,
)

model_exe = EXE(
    model_pyz,
    model_a.scripts,
    [],
    exclude_binaries=True,  # shares the one-folder COLLECT below
    name='CWatM_model',
    # The exe is MOVED into _internal/ after COLLECT (see the end of this spec)
    # so users only see CWatM_GUI.exe in the app folder. contents_directory='.'
    # makes its bootloader look for the dependencies NEXT TO the exe - which,
    # once it sits inside _internal/, is exactly the shared dependency folder.
    # (COLLECT's layout comes from the FIRST EXE passed to it - the GUI exe -
    # so the folder keeps the normal _internal layout.)
    contents_directory='.',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # valid std pipes; QProcess spawns it with CREATE_NO_WINDOW
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=next((p for p in (
        os.path.join(spec_root, 'assets', 'cwatm_small.ico'),
        os.path.join(spec_root, 'assets', 'cwatm.ico'),
    ) if os.path.exists(p)), None),
    version_file=None,
)

coll = COLLECT(
    exe,
    splash.binaries,
    a.binaries,
    a.zipfiles,
    a.datas,
    model_exe,
    model_a.binaries,
    model_a.zipfiles,
    model_a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='CWatM_GUI'
)

# --- Hide CWatM_model.exe inside _internal/ --------------------------------
# COLLECT always drops executables at the folder root; move the model child-
# process exe into _internal/ so users see only CWatM_GUI.exe. Its bootloader
# finds everything it needs there thanks to contents_directory='.' above. The
# GUI spawns it from _internal/ first (cwatm_process_worker._model_command),
# falling back to the root location for older builds.
_model_src = os.path.join(DISTPATH, 'CWatM_GUI', 'CWatM_model.exe')
_model_dst = os.path.join(DISTPATH, 'CWatM_GUI', '_internal', 'CWatM_model.exe')
if os.path.exists(_model_src):
    if os.path.exists(_model_dst):
        os.remove(_model_dst)
    os.replace(_model_src, _model_dst)
    print(f"Moved CWatM_model.exe -> {_model_dst}")


# Optional: Create version info
if sys.platform == 'win32':
    # You can create a version file later with pyi-grab_version or manually
    pass