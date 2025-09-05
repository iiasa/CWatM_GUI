# Building CWatM GUI Executable

This guide explains how to build a Windows executable for the CWatM GUI application.

## Prerequisites

1. **Python 3.8+** installed
2. **All dependencies** installed (see requirements_build.txt)
3. **PyInstaller** installed

## Quick Build (Recommended)

### Method 1: Using Batch File (Simplest)
```batch
# Double-click or run from command prompt
build_executable.bat
```

### Method 2: Using Advanced Python Script
```bash
# Check requirements
python build_advanced.py --check-only

# Basic build (single file, windowed)
python build_advanced.py

# Debug build with console
python build_advanced.py --debug --console

# Directory distribution (faster startup)
python build_advanced.py --onedir
```

### Method 3: Direct PyInstaller
```bash
# Install requirements
pip install -r requirements_build.txt

# Build using spec file
pyinstaller cwatm_gui.spec
```

## Build Options

The `cwatm_gui.spec` file is configured for:
- **Single file executable** (`--onefile`)
- **Windowed application** (no console)
- **Includes all assets** (icons, config files)
- **Includes entire CWatM library**
- **UPX compression** enabled (if UPX is available)

## Customization

### To modify the build:

1. **Edit `cwatm_gui.spec`** for PyInstaller settings
2. **Modify icon**: Replace `assets/cwatm.ico`
3. **Add/remove files**: Update `datas` section in spec file
4. **Hidden imports**: Add to `hiddenimports` list

### Common spec file modifications:

```python
# For console application (debugging)
console=True

# To disable UPX compression
upx=False

# To exclude large unused libraries
excludes=['matplotlib', 'jupyter', 'tkinter']

# To add custom icon
icon='path/to/your/icon.ico'
```

## Build Outputs

- **Single file**: `dist/CWatM_GUI.exe`
- **Directory**: `dist/CWatM_GUI/` (with CWatM_GUI.exe inside)
- **Build files**: `build/` (temporary, can be deleted)

## Troubleshooting

### Common Issues:

1. **Missing modules**: Add to `hiddenimports` in spec file
2. **Missing data files**: Add to `datas` section
3. **Large file size**: 
   - Enable UPX compression
   - Exclude unused libraries
   - Use `--onedir` for faster startup

### GDAL/OSGEO Issues:
If GDAL fails to load:
```python
# In spec file, ensure GDAL data is included
datas = [
    ('C:/path/to/gdal/data', 'gdal-data'),
]
```

### NetCDF4 Issues:
For netCDF4 dependency issues:
```python
# Add to hiddenimports
hiddenimports = [
    'netCDF4.utils',
    'netCDF4._netCDF4',
]
```

## File Sizes (Approximate)

- **Basic build**: ~150-200 MB
- **With UPX compression**: ~100-150 MB
- **Debug build**: ~200-300 MB

## Distribution

The final `CWatM_GUI.exe` is self-contained and can be distributed without Python installation. Users only need:

1. **Windows OS** (7/8/10/11)
2. **Visual C++ Redistributable** (usually already installed)
3. **Optional**: GDAL/OSGEO for advanced geospatial features

## Advanced Options

### Creating MSI Installer:
```bash
# After building exe, create installer
pip install cx_Freeze
# Use cx_Freeze to create MSI package
```

### Code Signing (Optional):
```bash
# Sign the executable (requires certificate)
signtool sign /f certificate.pfx /p password CWatM_GUI.exe
```

### Performance Tips:
1. Use `--onedir` for faster startup (larger distribution)
2. Enable UPX compression for smaller size
3. Exclude unused libraries to reduce size
4. Use `--strip` to remove debug symbols