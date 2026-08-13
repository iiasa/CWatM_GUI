# CWatM GUI on Linux — install & run

Everything needed to get the CWatM GUI running on Linux, including from a Windows
desktop over a forwarded X display (Xming / VcXsrv / X2Go / VNC / WSLg).

There is **no Linux executable or installer** — those are Windows-only (PyInstaller +
Inno Setup). On Linux the GUI runs **from source**, which is fully supported: the same
`cwatm_gui.py`, the same model, the same settings files.

> **In a hurry?**
> ```bash
> sudo apt install -y python3-venv libxcb-cursor0 libxcb-xinerama0 libxkbcommon-x11-0 \
>      libegl1 libgl1 libfontconfig1 libdbus-1-3 fonts-dejavu xdg-utils
> cd /path/to/cwatmpublic/gui
> python3 -m venv venv2 && . venv2/bin/activate
> pip install --only-binary=:all: -r requirements.txt
> chmod +x gui.sh && ./gui.sh
> ```
> Something wrong? Run **`./gui.sh --check`** — it diagnoses the whole environment and
> names the fix.

---

## Contents

1. [Requirements](#1-requirements)
2. [System libraries](#2-system-libraries)
3. [The Python environment](#3-the-python-environment)
4. [Starting the GUI](#4-starting-the-gui)
5. [Remote display: Xming, VcXsrv, X2Go, VNC, WSLg](#5-remote-display)
6. [`gui.sh` — options and environment variables](#6-guish--options-and-environment-variables)
7. [Troubleshooting](#7-troubleshooting)
8. [Running the model without the GUI](#8-running-the-model-without-the-gui)
9. [What differs from the Windows version](#9-what-differs-from-the-windows-version)
— [Appendix: a worked example](#appendix-a-worked-example)

---

## 1. Requirements

| | |
|---|---|
| **Python** | 3.10 or newer. The pins were resolved against 3.12 on Windows; **3.13.5 with PySide6 6.9.3 has been run successfully**. Needs the `venv` module: `python3-venv` on Debian/Ubuntu. |
| **Disk** | ~2 GB for the virtual environment (PySide6 + QtWebEngine are most of it). |
| **Display** | Any X11 or Wayland session, local or forwarded. QtWebEngine (the map and plot windows) is the demanding part. |
| **Root** | Only to install the system libraries in §2. There is a no-root path if you cannot get them. |

**About the pinned versions.** `requirements.txt` pins the exact stack of the Windows
3.12 environment. Nothing in the GUI or in `cwatm/` uses a stdlib module removed in 3.13
(checked against the full PEP 594 removal list), so a newer interpreter is not itself a
problem — the only risk is a package having no wheel for it. Installing with
`--only-binary=:all:` makes that fail immediately and visibly instead of starting a
silent source build; then relax **that one** pin (e.g. `PySide6>=6.8`) and leave the
rest alone.

---

## 2. System libraries

These are **not** pip packages — Qt loads them from the system. Missing ones are the
single most common reason the GUI will not start.

**Qt itself** (without these the GUI does not start at all):

> **Which family am I on?** `cat /etc/os-release` (or `lsb_release -a`). Debian, Ubuntu,
> Mint and their derivatives use **`apt`**; RHEL, Rocky, Alma and Fedora use **`dnf`**.
> Running the wrong one just says *"Command 'dnf' not found"* — take the other block.

```bash
# Debian / Ubuntu
sudo apt install -y libxcb-cursor0 libxcb-xinerama0 libxkbcommon-x11-0 \
     libegl1 libgl1 libfontconfig1 libdbus-1-3 fonts-dejavu xdg-utils

# RHEL / Rocky / Alma / Fedora
sudo dnf install -y xcb-util-cursor xcb-util-wm xcb-util-keysyms libxkbcommon-x11 \
     mesa-libEGL mesa-libGL fontconfig dejavu-sans-fonts xdg-utils dbus-libs
```

`libxcb-cursor0` (`xcb-util-cursor` on RPM) is the one Qt 6.5+ refuses to start without,
and the one most systems are missing. Note that this is a library on the **Linux
machine** — changing or upgrading the X server on your Windows PC (Xming → VcXsrv) makes
no difference to it.

**QtWebEngine** (only the map and plot windows need it — Show Basin, NetCDF, Timeseries,
Watercycle, Flow Diagram, CWatM AI. The settings editor, the Excel editor, Check Data,
Options and the model run all work without it):

```bash
# Debian / Ubuntu
sudo apt install -y libnss3 libnspr4 libasound2t64 libxcomposite1 libxdamage1 \
     libxrandr2 libxtst6 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libgbm1 \
     libpangocairo-1.0-0 libxshmfence1

# RHEL / Rocky / Alma / Fedora
sudo dnf install -y nss nspr alsa-lib libXcomposite libXdamage libXrandr libXtst \
     at-spi2-atk cups-libs libdrm mesa-libgbm pango
```

(`libasound2t64` is `libasound2` on releases before Ubuntu 24.04.)

**To see exactly what is missing** rather than installing blind — this is what
`./gui.sh` does for you before starting:

```bash
ldd venv2/lib/python3.*/site-packages/PySide6/Qt/plugins/platforms/libqxcb.so | grep 'not found'
```

**Is it really absent, or only unknown to the loader?** Worth two seconds before
installing anything:

```bash
ldconfig -p | grep -i xcb-cursor
find /usr/lib* /lib* -name 'libxcb-cursor*' 2>/dev/null
```

If the file exists but Qt does not see it, the fix is `LD_LIBRARY_PATH` (below), not a
package.

### No root?

You do **not** need an administrator: unpack the package into your home directory and
point the dynamic loader at it. Nothing is installed system-wide, and nothing else on
the machine is affected.

**Debian / Ubuntu**

```bash
mkdir -p ~/qtlibs && cd ~/qtlibs
apt-get download libxcb-cursor0                 # a normal user may download
dpkg -x libxcb-cursor0_*.deb .
export LD_LIBRARY_PATH=$HOME/qtlibs/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}
echo 'export LD_LIBRARY_PATH=$HOME/qtlibs/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH:-}' >> ~/.bashrc
```

**RHEL / Rocky / Alma / Fedora**

```bash
mkdir -p ~/qtlibs && cd ~/qtlibs
dnf download xcb-util-cursor                    # or: yumdownloader xcb-util-cursor
rpm2cpio xcb-util-cursor*.rpm | cpio -idmv
export LD_LIBRARY_PATH=$HOME/qtlibs/usr/lib64:${LD_LIBRARY_PATH:-}
echo 'export LD_LIBRARY_PATH=$HOME/qtlibs/usr/lib64:${LD_LIBRARY_PATH:-}' >> ~/.bashrc
```

The `echo … >> ~/.bashrc` line is what makes it survive the next login — without it the
GUI works now and fails tomorrow.

**No repository access either?** `dpkg -x` and `rpm2cpio` need neither root nor a repo:
download the package on your Windows PC from
[packages.ubuntu.com](https://packages.ubuntu.com) /
[packages.debian.org](https://packages.debian.org) (pick the release that
`cat /etc/os-release` reports), copy it over with `scp`, and run the unpack + export
lines above.

**Then check it worked:**

```bash
cd /path/to/cwatmpublic/gui
./gui.sh --check          # want: "xcb plugin ... missing libs: none"
./gui.sh
```

Repeat the same recipe for any further library `--check` reports; several packages can
be unpacked into the same `~/qtlibs`.

> **A conda/mamba environment** (`conda install -c conda-forge xcb-util-cursor`) is
> another way to get these libraries without root — but be aware that a conda env on the
> path is the usual cause of the libffi clash in §7, which breaks the map and plot
> windows. Prefer the unpack recipe above.

---

## 3. The Python environment

```bash
cd /path/to/cwatmpublic/gui

python3 -m venv venv2                       # venv2, not venv - see the note below
. venv2/bin/activate
python -m pip install --upgrade pip
pip install --only-binary=:all: -r requirements.txt

python -c "import PySide6; print(PySide6.__version__)"    # sanity check
```

> **Why `venv2`?** If the same checkout is shared with Windows (a mounted P: drive, a
> network share), `venv/` there is the **Windows** environment: it has
> `Scripts/python.exe` and no `bin/python`, so it is unusable from Linux. `gui.sh`
> looks for `venv2/` first for exactly this reason, and `.gitignore` covers both.

> **Which `python3` builds the venv matters.** If a conda/miniconda environment is
> active (your prompt starts with `(base)`), `python3 -m venv` builds the environment on
> **conda's** interpreter, and the process then loads conda's libraries — whose `libffi`
> carries no symbol versions, which is what breaks QtWebEngine (§7). Prefer the system
> interpreter when it is new enough:
> ```bash
> conda deactivate
> /usr/bin/python3 -V                 # 3.10 or newer? then use it
> /usr/bin/python3 -m venv venv2
> ```
> `./gui.sh --check` prints the interpreter a venv was built on, and flags conda.

**On a network share**, a virtualenv is slow to create and slow to import from at every
start. Put it on local disk instead and point `gui.sh` at it:

```bash
python3 -m venv ~/cwatm-venv
~/cwatm-venv/bin/pip install --only-binary=:all: -r requirements.txt
CWATM_GUI_PYTHON=~/cwatm-venv/bin/python ./gui.sh
```

**Optional blocks** in `requirements.txt` you can drop if you do not need them:
`playwright` (only for the CWatM AI Google-login window) and
`flopy` / `matplotlib` / `xmipy` / `bmipy` / `black` (only for MODFLOW coupling). That
saves a lot of download.

**Ignore the `*.whl` files in the repository root** (`rasterio-…win_amd64.whl`,
`netcdf4-…win_amd64.whl`, `gdal-…win_amd64.whl`) — they are Windows wheels for the
Windows environment. On Linux everything comes from PyPI. Do **not** install a separate
GDAL wheel either; rasterio ships its own.

---

## 4. Starting the GUI

```bash
chmod +x gui.sh          # once
./gui.sh                 # no settings file
./gui.sh settings.ini    # load a settings file at startup
```

`gui.sh` is the Linux counterpart of `gui.bat` / `gui.vbs`. It

* picks the interpreter: `$CWATM_GUI_PYTHON` → an activated `$VIRTUAL_ENV` → `venv2/` →
  `venv/` → `python3` from `PATH`;
* refuses to start, with a readable explanation, when that interpreter has no PySide6 or
  when Qt's system libraries are missing;
* warns (but starts) when only the **QtWebEngine** libraries are missing;
* sets the environment a forwarded X display needs (§5);
* forwards its arguments to `cwatm_gui.py`.

You can also start it directly — `python cwatm_gui.py settings.ini` — but then none of
the above happens, which is why the errors in §7 are so much harder to read.

---

## 5. Remote display

Every map and plot window is **QtWebEngine, i.e. Chromium**, which expects a GPU and a
real GLX. A forwarded X11 display provides neither, so `gui.sh` forces software
rendering:

```
QT_OPENGL=software
LIBGL_ALWAYS_SOFTWARE=1
QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu --disable-gpu-compositing
                           --disable-software-rasterizer --no-sandbox
```

and, when `DISPLAY` is **not** local (anything other than `:0`), also
`QT_X11_NO_MITSHM=1` / `QT_XCB_NO_MITSHM=1` — the MIT-SHM shared-memory extension cannot
work over the wire, and Qt asking for it anyway is a classic `BadAccess`/`BadAlloc`
crash on large windows.

### Which X server

| Option | Verdict |
|---|---|
| **X2Go** | Best experience for a remote Linux desktop; handles large windows and reconnects. |
| **VNC** (TigerVNC + a light desktop) | Very reliable; the session survives a dropped connection. |
| **VcXsrv** | The maintained successor of Xming, free. Has XRandR and GLX — **recommended if you want plain X11 forwarding from Windows**. |
| **Xming** | Works, but it is old: no XInput2, no (working) XRandR, no usable GLX. Expect the warnings in §7 and trouble with maximized windows. |
| **WSLg** (WSL2) | Works out of the box, nothing to configure. |

### Connecting with X11 forwarding

```bash
ssh -Y user@linuxbox        # -Y = trusted forwarding; -X is often too restricted
echo $DISPLAY               # e.g. localhost:10.0 - set by ssh, do not override
cd /path/to/cwatmpublic/gui && ./gui.sh
```

On the Windows side start the X server first. In VcXsrv/Xming's **XLaunch** wizard
choose **Multiple windows**, display number `0`, **Start no client**, and tick
*Disable access control* (or set up `xauth`). *Multiple windows* also brings a window
manager, which the *One large window* mode does not — that matters for maximizing.

---

## 6. `gui.sh` — options and environment variables

| | |
|---|---|
| `./gui.sh [settings.ini]` | start the GUI |
| `./gui.sh --check` | **diagnose and exit** — see below |
| `CWATM_GUI_PYTHON=…` | use this interpreter (e.g. a venv on local disk) |
| `CWATM_GUI_NO_MAXIMIZE=1` | start windowed instead of maximized |
| `CWATM_GUI_SOFTWARE_GL=0` | keep hardware OpenGL (a local desktop with a GPU) |
| `CWATM_GUI_XCB_NO_GL=1` | switch GL off in the xcb plugin entirely — for an X server with no usable GLX at all (Xming) |
| `CWATM_GUI_PRELOAD_SYSLIBS=1` | `LD_PRELOAD` the distribution's libffi/krb5/gssapi — the fix for `undefined symbol` clashes (§7) |
| `CWATM_GUI_PRELOAD_FFI=1` | the same, libffi only (the older switch) |
| `CWATM_GUI_SKIP_LIB_CHECK=1` | do not test the Qt libraries before starting |
| `CWATM_GUI_VERBOSE=1` | print which interpreter is used |

### What `--check` reports

```
python            : venv2/bin/python            the interpreter that would be used
                    Python 3.13.5
venv built on     : …/miniconda3/bin            flagged when it is conda (§3, §7)
PySide6           : 6.9.3 …/site-packages/…
DISPLAY           : localhost:31.0              local, forwarded, or unset
LD_LIBRARY_PATH   : …                           plus a warning for LD_PRELOAD entries
LD_PRELOAD        : <unset>                       that do not exist
CONDA_PREFIX      : …/miniconda3
conda on PATH     : …/miniconda3/bin/python3    a common source of library clashes
system libs to preload:                         the exact LD_PRELOAD list for this box
  /lib/x86_64-linux-gnu/libffi.so.7:…

xcb plugin        : …/plugins/platforms/libqxcb.so
  missing libs    : none                        anything here = install it (§2)
QtWebEngine       : …/libexec/QtWebEngineProcess
  missing libs    : none

imports:                                        one line per package
  PySide6.QtWebEngineWidgets: FAILED            + the error, cut to the point
  rasterio                  : OK
  …
  retry with the system libraries preloaded: … : OK   <- it tries the fix for you
  => Start the GUI with:   CWATM_GUI_PRELOAD_SYSLIBS=1 ./gui.sh
```

The last block is the useful part: when an import fails with a library clash, `--check`
**retries it with the preload applied** and tells you whether that is the answer — and
if it is not, it looks at how the virtualenv was built and says so.

---

## 7. Troubleshooting

**Always start with `./gui.sh --check`.** It answers most of the questions below in one
go, and verifies its own suggestion.

| Symptom | Cause | Where |
|---|---|---|
| `ModuleNotFoundError: No module named 'PySide6'` | wrong interpreter — no Linux venv yet | [below](#modulenotfounderror-no-module-named-pyside6) |
| `Could not load the Qt platform plugin "xcb"` | missing system libraries, usually `libxcb-cursor0` | [§2](#2-system-libraries) |
| `undefined symbol: ffi_type_uint32` / `krb5_ser_context_init` | two copies of one system library (conda, or a wheel) | [below](#undefined-symbol--library-clashes) |
| Map/plot windows say "unavailable" | the same clash, or missing QtWebEngine libraries | [§2](#2-system-libraries), below |
| The window disappears when maximized | the X server cannot hold a desktop-sized window | [below](#the-window-vanishes-when-maximized) |
| `X server does not support XInput 2`, `failed to get the current screen resources` | Xming's age — warnings | [below](#x-server-does-not-support-xinput-2-failed-to-get-the-current-screen-resources) |
| `object … from LD_PRELOAD cannot be preloaded` | a hand-written `LD_PRELOAD` path that does not exist | [below](#undefined-symbol--library-clashes) |

### `ModuleNotFoundError: No module named 'PySide6'`

The interpreter that ran is not the one with the packages — usually because no Linux
virtualenv exists yet and the fallback landed on the system `python3` (remember: a
shared checkout's `venv/` is the *Windows* one). Create `venv2` as in §3. `gui.sh` now
detects this and says so instead of letting Python throw.

### `Could not load the Qt platform plugin "xcb"` / `libxcb-cursor.so.0` missing

Missing system libraries — most often `libxcb-cursor0`, which Qt 6.5+ requires. `gui.sh`
lists every missing library by name before starting. Install them as in §2
(`sudo apt install -y libxcb-cursor0` on Debian/Ubuntu, `sudo dnf install -y
xcb-util-cursor` on RHEL/Fedora), or use the **no-root unpack recipe** in §2 if you have
no administrator rights.

Two things that catch people out:

* These libraries live on the **Linux machine**. Installing or upgrading the X server on
  your Windows PC (Xming → VcXsrv) does not change anything here — that fixes screen
  geometry, GLX and large windows, not a missing Linux library.
* `dnf` exists only on RHEL-family systems; on Debian/Ubuntu the command is `apt`, and
  vice versa. *"Command 'dnf' not found"* simply means you took the wrong block.

### `undefined symbol:` … — library clashes

Two copies of the same system library are in play: the distribution's, and one shipped
**inside a Python wheel** (rasterio's manylinux wheel bundles curl, krb5 and friends in
`rasterio.libs/`) or in a **conda environment**. Whichever copy loses the load order
cannot resolve a symbol, and the import dies. The two that occur here:

| Message | Who pulls it in | What breaks |
|---|---|---|
| `libwayland-server.so.0: undefined symbol: ffi_type_uint32` | QtWebEngine → `libwayland-server` → **libffi** | every map/plot window reports "unavailable" |
| `libgssapi_krb5.so.2: undefined symbol: krb5_ser_context_init, version krb5_3_MIT` | rasterio/netCDF4 → curl/GDAL → **libkrb5** | the basin viewer, Check Data and the model's raster reads |

**Where the second copy usually comes from: conda.** If your prompt shows `(base)` — or
`./gui.sh --check` prints `venv built on … miniconda3` / `conda on PATH` — the
virtualenv was created from conda's Python, so the process loads conda's libraries
through that interpreter. Conda's `libffi` carries **no symbol versions**, while the
system `libwayland-server` asks for `ffi_type_uint32, version LIBFFI_BASE_7.0`: exactly
the error above.

Both clashes have the same first fix — load the distribution's copies first:

```bash
CWATM_GUI_PRELOAD_SYSLIBS=1 ./gui.sh --check     # does it fix the import?
CWATM_GUI_PRELOAD_SYSLIBS=1 ./gui.sh             # then start
```

To keep it, put the **variable** in your `~/.bashrc` — not a literal path:

```bash
echo 'export CWATM_GUI_PRELOAD_SYSLIBS=1' >> ~/.bashrc
```

> **Never copy an `LD_PRELOAD` path out of documentation** (including this file) — the
> directory and the soname differ per distribution (this machine has `libffi.so.7`, the
> next one `libffi.so.8`). A path that does not exist makes `ld.so` print *"object … from
> LD_PRELOAD cannot be preloaded … ignored"* before **every** command in that shell. Let
> the script resolve them (`CWATM_GUI_PRELOAD_SYSLIBS=1`), or copy the line `--check`
> prints for *your* box. Already stuck with a broken one? `unset LD_PRELOAD` and delete
> it from `~/.bashrc`; `gui.sh` and `--check` now flag non-existent entries.

**If preloading is not enough**, remove conda from the picture instead. The venv from §3
needs nothing from it:

```bash
conda deactivate                                     # leave the (base) environment
export PATH=$(echo "$PATH" | tr ':' '\n' | grep -v conda | paste -sd:)   # this shell
which -a python3                                     # miniconda should be gone

/usr/bin/python3 -V                                  # 3.10 or newer?
/usr/bin/python3 -m venv venv3 && . venv3/bin/activate
pip install --only-binary=:all: -r requirements.txt
CWATM_GUI_PYTHON=$PWD/venv3/bin/python ./gui.sh
```

If the system Python is older than 3.10, stay on the conda-built environment and use the
preload — that combination works; it is only less tidy.

To see which copy was actually loaded and from where:

```bash
LD_DEBUG=libs venv2/bin/python -c 'import PySide6.QtWebEngineWidgets' 2>&1 | grep -i ffi
```

### The window vanishes when maximized

The X server could not allocate a backing store the size of the whole desktop (look for
`BadAlloc` on the terminal). Start windowed:

```bash
CWATM_GUI_NO_MAXIMIZE=1 ./gui.sh
```

`gui.sh` already disables MIT-SHM on remote displays, which is the other common cause.
A newer X server (VcXsrv, or X2Go/VNC) fixes this properly — Xming has no working
XRandR, so Qt cannot even read the screen layout it is maximizing against.

### `X server does not support XInput 2`, `failed to get the current screen resources`

Xming has no XInput2 and no XRandR. **Warnings** — the GUI runs; mouse and keyboard work
through core X input. The missing XRandR is why maximizing misbehaves there. VcXsrv or
X2Go removes both.

### `Cannot create platform OpenGL context, neither GLX nor EGL are enabled`

GL is switched off in the xcb plugin (`CWATM_GUI_XCB_NO_GL=1`) or the X server has no
GLX. Harmless for the main window; fatal for the map/plot views. Try without
`CWATM_GUI_XCB_NO_GL` first — with software Mesa that usually works better — and use a
server with GLX (VcXsrv) if you need the viewers.

### Maps are blank, or the app dies when a viewer opens

Chromium and remote X11. Check that the QtWebEngine libraries from §2 are installed
(`./gui.sh --check` lists the missing ones), keep the software-GL defaults, and prefer
X2Go/VNC over plain forwarding.

### Where are the logs?

`%LOCALAPPDATA%` does not exist on Linux, so the diagnostic log and the run ledger fall
back to the temp directory: `/tmp/CWatM_GUI/gui.log` and `/tmp/CWatM_GUI/run_ledger.json`.
Point **Preferences ▸ Run History ▸ Run history folder** at something permanent (e.g.
`~/.local/share/CWatM_GUI`) so your run history survives a reboot.

---

## 8. Running the model without the GUI

The model runs completely headless — no Qt is imported at all. This is the same child
process the GUI uses for every run, so results are identical:

```bash
venv2/bin/python cwatm_gui.py --run-cwatm settings.ini
```

Useful over SSH without a display, in a batch script, or on a compute node. You can
still edit the settings file in the GUI on your desktop and run it here.

---

## 9. What differs from the Windows version

| | |
|---|---|
| **Executable / installer** | Windows only. Linux runs from source. |
| **Launcher** | `gui.sh` instead of `gui.bat` / `gui.vbs`. |
| **Log & run ledger** | `/tmp/CWatM_GUI/` instead of `%LOCALAPPDATA%\CWatM_GUI\` (configurable — §7). |
| **Opening files/folders** | Goes through `xdg-open` (the desktop's default handler) instead of `os.startfile`; needs `xdg-utils`. |
| **Taskbar icon** | The Windows AppUserModelID call is skipped; your desktop environment decides the icon. |
| **Model subprocess** | `python cwatm_gui.py --run-cwatm <ini>` instead of `CWatM_model.exe`. Same protocol, same behaviour (Stop is a real kill, a crash cannot take the GUI down). |
| **Everything else** | Identical: the settings editor, Excel editor, Check settingsfile, Run Ledger, Batch Run, Hidden Run, the viewers, themes and preferences all behave the same. |

---

## Appendix: a worked example

One real setup, in the order the problems appeared — useful because they show up one at
a time, each hiding the next.

| | |
|---|---|
| Machine | Linux host on a university network, home directory on `/h/…`, the CWatM checkout on a share (`/p/…`) also mounted as `P:` on Windows |
| Distribution | `libffi.so.7` era (Debian 11 / Ubuntu 20.04 generation), no root for the user |
| Python | miniconda **3.13.5** (a `(base)` environment active at login) |
| Qt | PySide6 **6.9.3** |
| Display | Windows desktop, X11 forwarding over `ssh -Y`, Xming first, then VcXsrv |

1. **`ModuleNotFoundError: No module named 'PySide6'`** — no Linux venv existed yet;
   `venv/` in the shared checkout is the *Windows* one. → `python3 -m venv venv2` (§3).
2. **`Could not load the Qt platform plugin "xcb"` → `libxcb-cursor.so.0`** — one
   missing system library, everything else present. No root, so it was unpacked into
   `~/qtlibs` with `apt-get download` + `dpkg -x` and `LD_LIBRARY_PATH` (§2).
   *Switching Xming → VcXsrv did not help here: this library lives on the Linux side.*
3. **Xming's warnings** (`X server does not support XInput 2`, `failed to get the current
   screen resources`) and **the window disappearing when maximized** → VcXsrv fixed the
   first two; `CWATM_GUI_NO_MAXIMIZE=1` covers the third (§7).
4. **`libwayland-server.so.0: undefined symbol: ffi_type_uint32, version
   LIBFFI_BASE_7.0`** — the map/plot windows only. Cause: the venv was built from
   **conda's** Python, so conda's unversioned `libffi` shadowed the system one.
   → `CWATM_GUI_PRELOAD_SYSLIBS=1`, or rebuild the venv on the system Python (§7).
5. A **hand-copied `LD_PRELOAD`** from the documentation pointed at `libffi.so.8`, which
   this machine does not have → `ld.so` complained before every command. Always let
   `gui.sh` resolve the paths (§7).

Throughout steps 3–5 the GUI itself was usable: the settings editor, the Excel editor,
Check Data, Options and model runs need none of QtWebEngine. Only the map and plot
windows waited for the last fix.

---

*Developer notes on the same subject (why `gui.sh` sets what it sets, the `.gitattributes`
LF rule, `open_path.py`, the `CWATM_GUI_NO_MAXIMIZE` hook) live in `CLAUDE.md` under
**Running on Linux**. User-facing feature documentation is in `documentation/`.*
