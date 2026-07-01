
https://www.pythonguis.com/tutorials/packaging-pyside6-applications-windows-pyinstaller-installforge/

claude: use a folder with a python project with many python modules and create a windows executable with all libraries used in the project


#new try:

Use a powershell:

## 1. Create a fresh venv from the base Python 3.8 (matches pyvenv.cfg: home = C:\Python38)
python.exe -m venv venv

## 2. Activate it
.\venv\Scripts\Activate.ps1
#    Prompt should now show (venv). If activation is blocked by execution policy:
#    Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

## 3. Upgrade pip (the bundled 21.1.1 is old)
python -m pip install --upgrade pip

## 4. Install dependencies
python -m pip install -r requirements.txt

## 5. Verify the key pieces import and the launchers work
(Get-Command python).Source            # shopts\python.exe
python -c "import rasterio, rasterio.sample, PySide6; print('ok')"
pip --version                          # baresh launcher)
pyinstaller --version

## check xarray


## 6.
python -m PyInstaller cwatm_gui_dir.spec --noconfirm



Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\venvv\Scripts\Activate.ps1

use claude and cwtmexe.md

cd P:\watmodel\cwatmpublic\gui
build_env\Scripts\activate
pyinstaller cwatm_gui_dir.spec









1) Install PyInstaller
pip install PyInstaller
pip install --upgrade PyInstaller pyinstaller-hooks-contrib

2) Virtual environment
python -m venv build_env

######################################
cd P:\watmodel\cwatmpublic\gui
build_env\Scripts\activate
pyinstaller cwatm_gui_dir.spec




3) Install libs

##pip install -r requirements.txt

pip install numpy
pip install scipy
pip install netCDF4
pip install pandas
pip install openpyxl
pip install GDAL-3.6.1-cp38-cp38-win_amd64.whl


If using a GUI:
pip install PySide6
pip install rasterio
pip install xarray

pip install py-splash

4)
# Generate requirements.txt
pip freeze > requirements.txt


5)
###pyinstaller --add-data "cwatm;cwatm"  --onefile run_cwatm.py


# For a single file executable (larger but portable)
pyinstaller --onefile --windowed main.py

# For a directory distribution (faster startup)
pyinstaller --onedir --windowed main.py

# With custom icon
pyinstaller --onefile --windowed --icon=icon.ico main.py




##pyinstaller .\run_cwatm.spec
pyinstaller .\cwatm_gui.spec


executabel i9 in P:\watmodel\cwatmpublic\exe\dist

Executable and test of Morava in:
P:\watmodel\CWATM\Regions\Danube_1min\CWATMexe


# ------------------------------------------------------



# Example main.spec
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['run_cwatm.py'],
    pathex=['C:\\path\\to\\your\\project'],
    binaries=[],
    datas=[('cwatm/', 'cwatm/'), ('assets/', 'assets/')],  # Include data files
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='cwatm',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Set to True if you need console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='cwatm.ico'  # Add your icon
)

# Then build with: pyinstaller main.spec