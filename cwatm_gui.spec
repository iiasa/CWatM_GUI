# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

# rasterio imports several submodules dynamically (rasterio.sample, rasterio._shim,
# rasterio.vrt, ...) which PyInstaller's static analysis cannot see. Collect them all,
# plus rasterio's bundled GDAL/PROJ data (gdal_data/proj_data) so the frozen GUI does
# not fail with "ModuleNotFoundError: rasterio.sample" or
# "Cannot find gdalvrt.xsd (GDAL_DATA is not defined)". rasterio ships its own GDAL,
# so the osgeo/GDAL wheel is not needed (see cwtmexe.md).
rasterio_hiddenimports = collect_submodules('rasterio')
rasterio_datas = collect_data_files('rasterio')

# xarray loads its backends (netCDF4, scipy, ...) dynamically via entry points and
# reads its own version from package metadata. Collect its submodules and data, and
# copy its dist metadata so the backend plugins are discoverable in the frozen app,
# otherwise the GUI fails with "No module named 'xarray'" / backend errors.
xarray_hiddenimports = collect_submodules('xarray')
xarray_datas = collect_data_files('xarray') + copy_metadata('xarray')

# Get the directory of this spec file
spec_root = os.path.dirname(os.path.abspath(SPEC))

# Collect all cwatm submodules
cwatm_hiddenimports = collect_submodules('cwatm')

# Additional hidden imports for CWatM and GUI dependencies
hiddenimports = rasterio_hiddenimports + xarray_hiddenimports + cwatm_hiddenimports + [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'py_splash',
    'numpy',
    'pandas',
    'scipy',
    'netCDF4',
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

# Data files to include
datas = [
    # Include assets
    (os.path.join(spec_root, 'assets', '*'), 'assets'),
    # Include entire cwatm package data
    (os.path.join(spec_root, 'cwatm'), 'cwatm'),
    # Include source GUI files
    (os.path.join(spec_root, 'src'), 'src'),
]
# Include rasterio's bundled GDAL/PROJ data files
datas += rasterio_datas
# Include xarray's data files and package metadata (for backend discovery)
datas += xarray_datas

# Binary files to include (DLLs and shared libraries)
binaries = []

# Add routing reservoir binaries
routing_binaries_path = os.path.join(spec_root, 'cwatm', 'hydrological_modules', 'routing_reservoirs')
if os.path.exists(routing_binaries_path):
    binaries.extend([
        (os.path.join(routing_binaries_path, 't5.dll'), '.'),
        (os.path.join(routing_binaries_path, 't5_linux.so'), '.'),
        (os.path.join(routing_binaries_path, 't5_mac.so'), '.'),
        (os.path.join(routing_binaries_path, 't5cyg.so'), '.'),
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
        'tkinter',
        'matplotlib',
        'IPython',
        'jupyter',
        'notebook',
        'PyQt5',
        'PyQt6',
        'wx'
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)


splash = Splash('assets/cwatm.png',
                binaries=a.binaries,
                datas=a.datas,
                text_pos=(10, 50),
                text_size=12,
                text_color='blue',
                always_on_top = False)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    splash,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    exclude_binaries=False,  # This must be True for onedir
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
    icon=os.path.join(spec_root, 'assets', 'cwatm.ico') if os.path.exists(os.path.join(spec_root, 'assets', 'cwatm.ico')) else None,
    version_file=None,
)

coll = COLLECT(
    exe,
    splash.binaries,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='CWatM_GUI'
)


# Optional: Create version info
if sys.platform == 'win32':
    # You can create a version file later with pyi-grab_version or manually
    pass