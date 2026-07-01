# Making the CWatM GUI executable build faster

This is a practical guide to speeding up packaging of the CWatM GUI (PySide6 +
rasterio + cwatm) on Windows. Most of the slowness in a default PyInstaller build
is **UPX compression**, not PyInstaller itself.

---

## TL;DR

1. Set `upx=False` in the spec (or build with `--noupx`). **Biggest single win.**
2. Don't use `--clean`, and keep the `build/` folder — it caches the analysis.
3. Build one-folder (`cwatm_gui_dir.spec`), not one-file.
4. For internal iteration, consider the **embedded-Python launcher** (no build step at all).

---

## Why it's slow

A default build spends most of its time on:

- **UPX compression** — re-compresses every bundled DLL. With big libraries
  (PySide6, GDAL, scipy, numpy) this dominates the build time and only saves some
  disk space. The current specs have `upx=True`.
- **Cold analysis** — `--clean` (or deleting `build/`) forces PyInstaller to
  re-analyze every module from scratch each time.
- **One-file mode** — has to pack everything into a single exe at build time and
  **unpack to a temp dir on every launch**, so it's slower to build *and* to start.

---

## Fastest wins — stay on PyInstaller, just tune it

### 1. Disable UPX (biggest build-time win)
In **both** `cwatm_gui.spec` and `cwatm_gui_dir.spec`, set `upx=False` in the
`EXE(...)` and `COLLECT(...)` calls:

```python
exe = EXE(
    ...
    upx=False,        # was upx=True
    ...
)

coll = COLLECT(
    ...
    upx=False,        # was upx=True
    ...
)
```

Or leave the spec alone and pass `--noupx` on the command line. Trade-off: a
somewhat larger output folder, no effect on whether it runs.

### 2. Keep the build cache — avoid `--clean`
PyInstaller caches analysis in `build/`. A warm rebuild is far faster than a cold
one.

```powershell
# fast (warm cache)
python -m PyInstaller cwatm_gui_dir.spec --noconfirm

# slow (throws away the cache) — only when something is genuinely stale
python -m PyInstaller cwatm_gui_dir.spec --noconfirm --clean
```

### 3. Build one-folder, not one-file
Use `cwatm_gui_dir.spec` (onedir) for iteration. It builds faster and starts much
faster than a one-file build, which unpacks to a temp dir on every launch.

### 4. Keep excluding big unused packages
The specs already exclude `matplotlib`, `tkinter`, `PyQt5/6`, `IPython`, `wx`,
etc. Keeping that list tight reduces analysis time. Don't add packages the GUI
doesn't actually import.

**With UPX off + warm `build/` + onedir, PyInstaller is usually fast enough for
day-to-day iteration.**

---

## If you want to switch tools

| Tool | Build speed | Runtime speed | Notes |
|---|---|---|---|
| **PyInstaller (tuned)** | Good (warm, no UPX) | Fine | Current setup; lowest effort |
| **Nuitka** | **Slower** (compiles to C) | **Faster** startup/exec | Choose for runtime perf, not build speed |
| **cx_Freeze** | Comparable, sometimes faster | Fine | Less "magic"; you'd hand-list rasterio data |
| **Embedded Python + launcher** | **Instant** (no build) | Native | Often the real answer for internal use — see below |

**Note:** Nuitka does *not* make the build faster — it makes the resulting program
faster to start and run, at the cost of a longer (C-compilation) build. Reach for
it only if runtime performance is the goal.

---

## The embedded-Python / launcher trick (no build step)

When iterating internally, the genuinely fastest path is to **not build at all**.
Ship the working venv plus the source, with a tiny launcher:

`run_gui.bat`:
```bat
@echo off
"%~dp0build_env\Scripts\pythonw.exe" "%~dp0cwatm_gui.py" %*
```

(`pythonw.exe` runs without a console window; use `python.exe` if you want to see
console output.)

Zip the folder and it runs on another Windows machine of the same architecture.

**Trade-offs:**
- Larger footprint, not a single polished `.exe`.
- The environment must be **relocatable** — use a *freshly created* venv, not a
  copied one. Copied venvs have absolute paths baked into their `Scripts\*.exe`
  launchers and fail with "Unable to create process using ...". A venv made with
  `python -m venv` and launched via `pythonw.exe` (as above) avoids that.

For an internal scientific GUI this is often the most practical choice: use it for
everyday runs, and invoke PyInstaller only for the occasional polished release
build.

---

## Recommendation

- **Day-to-day:** set `upx=False`, stop using `--clean`, build `cwatm_gui_dir.spec`.
  Two small changes, no tool switch.
- **Internal sharing:** the embedded-Python launcher (zero build time).
- **Releases only:** a full PyInstaller build (UPX optional if you care about size).
- **Need faster runtime, not faster build:** Nuitka.

---

## Quick command reference

```powershell
# Activate the build env
.\build_env\Scripts\Activate.ps1

# Fast iteration build (onedir, warm cache)
python -m PyInstaller cwatm_gui_dir.spec --noconfirm

# Same but force-disable UPX without editing the spec
python -m PyInstaller cwatm_gui_dir.spec --noconfirm --noupx

# Run the result
.\dist\CWatM_GUI\CWatM_GUI.exe
```
