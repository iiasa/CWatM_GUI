# -*- mode: python ; coding: utf-8 -*-

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

import pkgutil
import rasterio

# list all rasterio and fiona submodules, to include them in the package
additional_packages = list()
for package in pkgutil.iter_modules(rasterio.__path__, prefix="rasterio."):
    additional_packages.append(package.name)

# Get the directory of this spec file
spec_root = os.path.dirname(os.path.abspath(SPEC))

# Collect all cwatm submodules
cwatm_hiddenimports = collect_submodules('cwatm')

# Additional hidden imports for CWatM and GUI dependencies
hiddenimports = additional_packages + cwatm_hiddenimports + [
    'PySide6.QtCore',
    'PySide6.QtGui', 
    'PySide6.QtWidgets',
    'py_splash',
    'numpy',
    'pandas',
    'scipy',
    'netCDF4',
    'osgeo',
    'osgeo.gdal',
    'osgeo.osr',
    'osgeo.gdalconst',
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

# Binary files to include (DLLs and shared libraries)
binaries = []

# Add GDAL/OSGEO binaries if available
try:
    from osgeo import gdal
    gdal_path = os.path.dirname(gdal.__file__)
    # Include GDAL DLLs if they exist
    gdal_dll_path = os.path.join(gdal_path, '..', 'DLLs')
    if os.path.exists(gdal_dll_path):
        binaries.append((gdal_dll_path + '/*', 'DLLs'))
except:
    pass

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
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name='CWatM_GUI'
)


# Optional: Create version info
if sys.platform == 'win32':
    # You can create a version file later with pyi-grab_version or manually
    pass