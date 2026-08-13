#!/usr/bin/env bash
# Start the CWatM GUI on Linux (the counterpart of gui.bat / gui.vbs on Windows).
#
#   ./gui.sh                     start with no settings file
#   ./gui.sh settings.ini        start with that settings file loaded
#   ./gui.sh --check             diagnose the environment and exit (fixes nothing)
#
# Make it executable once:  chmod +x gui.sh
#
# Environment switches:
#   CWATM_GUI_PYTHON=/path/to/python   use this interpreter
#   CWATM_GUI_SOFTWARE_GL=0            keep hardware OpenGL (default: force software)
#   CWATM_GUI_XCB_NO_GL=1              switch GL off in the xcb plugin entirely (only
#                                      for an X server without usable GLX, e.g. Xming)
#   CWATM_GUI_PRELOAD_SYSLIBS=1        LD_PRELOAD the system libffi/krb5/gssapi, against
#                                      "undefined symbol" clashes (see --check)
#   CWATM_GUI_PRELOAD_FFI=1            the same, libffi only (older switch)
#   CWATM_GUI_NO_MAXIMIZE=1            start windowed (a maximized window can be too
#                                      much for a remote X server - it then vanishes)
#   CWATM_GUI_SKIP_LIB_CHECK=1         do not test the Qt libraries before starting
#   CWATM_GUI_VERBOSE=1                say which interpreter is used
#
# Interpreter, in this order: $CWATM_GUI_PYTHON, an already activated virtualenv
# ($VIRTUAL_ENV), venv2/, venv/, then python3 from PATH. NOTE: the venv/ folder of a
# Windows checkout is NOT usable here - it has Scripts/python.exe and no bin/python -
# so on a share used from both systems, make the Linux one venv2/.
set -euo pipefail

cd "$(dirname "$0")"

# ---------------------------------------------------------------- interpreter
if [ -n "${CWATM_GUI_PYTHON:-}" ]; then
    PYTHON="$CWATM_GUI_PYTHON"
elif [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python" ]; then
    PYTHON="$VIRTUAL_ENV/bin/python"
elif [ -x "venv2/bin/python" ]; then
    PYTHON="venv2/bin/python"
elif [ -x "venv/bin/python" ]; then
    PYTHON="venv/bin/python"
else
    PYTHON="$(command -v python3 || true)"
fi

if [ -z "${PYTHON:-}" ]; then
    echo "gui.sh: no Python found. Create the environment first:" >&2
    echo "    python3 -m venv venv2 && . venv2/bin/activate" >&2
    echo "    pip install --only-binary=:all: -r requirements.txt" >&2
    exit 1
fi

# ------------------------------------------------------------------- helpers
_qt_file() {   # _qt_file <relative path under PySide6/Qt> -> absolute path or ""
    "$PYTHON" - "$1" <<'PY' 2>/dev/null || true
import os, sys
try:
    import PySide6
except Exception:
    sys.exit(0)
p = os.path.join(os.path.dirname(PySide6.__file__), "Qt", *sys.argv[1].split("/"))
print(p if os.path.exists(p) else "")
PY
}

_webengine_file() {
    local p
    p="$(_qt_file libexec/QtWebEngineProcess)"
    [ -z "$p" ] && p="$(_qt_file lib/libQt6WebEngineCore.so.6)"
    printf '%s' "$p"
}

_missing_libs() {   # _missing_libs <file> -> the "not found" shared libraries
    [ -n "${1:-}" ] && [ -f "$1" ] && command -v ldd >/dev/null 2>&1 || return 0
    ldd "$1" 2>/dev/null | awk '/not found/ {print $1}' | sort -u || true
}

_system_lib() {     # _system_lib libfoo.so.N -> the distribution's copy, or ""
    ldconfig -p 2>/dev/null | awk -v n="$1" '$1 == n {print $NF; exit}' || true
}

_system_libffi() {  # the distribution's libffi, for LD_PRELOAD
    ldconfig -p 2>/dev/null | awk '/libffi\.so\.[0-9]/ {print $NF; exit}' || true
}

#: Libraries that a wheel or a conda env commonly ships a second, incompatible copy
#: of. When the system one loses the load order the import dies with "undefined
#: symbol" - ffi_type_uint32 (libwayland-server via QtWebEngine) and
#: krb5_ser_context_init (libgssapi_krb5, pulled in through curl/GDAL by rasterio and
#: netCDF4) are the two that actually happen here. Preloading the system copies puts
#: them first for the whole process.
_CLASH_LIBS="libffi.so.8 libffi.so.7 libkrb5.so.3 libgssapi_krb5.so.2 \
libk5crypto.so.3 libkrb5support.so.0 libcom_err.so.2"

_preload_syslibs() {   # -> a colon-separated LD_PRELOAD list of the ones present
    local list="" name path
    for name in $_CLASH_LIBS; do
        path="$(_system_lib "$name")"
        # Must really exist: ldconfig's cache can be stale, and a non-existent entry
        # makes ld.so print "cannot be preloaded ... ignored" for *every* command
        # the shell runs afterwards.
        [ -n "$path" ] && [ -f "$path" ] && list="${list:+$list:}$path"
    done
    printf '%s' "$list"
}

_venv_base() {         # -> the interpreter a virtualenv was created from
    local cfg
    cfg="$(dirname "$(dirname "$PYTHON")")/pyvenv.cfg"
    [ -f "$cfg" ] && awk -F'= *' '/^home/ {print $2; exit}' "$cfg" || true
}

_bad_preload() {       # -> LD_PRELOAD entries that do not exist
    local entry rest="${LD_PRELOAD:-}" bad=""
    while [ -n "$rest" ]; do
        entry="${rest%%:*}"
        [ "$entry" = "$rest" ] && rest="" || rest="${rest#*:}"
        [ -n "$entry" ] && [ ! -f "$entry" ] && bad="${bad:+$bad }$entry"
    done
    printf '%s' "$bad"
}

_apt_hint_qt() {
    echo "        Debian/Ubuntu:  sudo apt install -y libxcb-cursor0 libxcb-xinerama0 \\" >&2
    echo "            libxkbcommon-x11-0 libegl1 libgl1 libfontconfig1 libdbus-1-3" >&2
    echo "        RHEL/Fedora:    sudo dnf install -y xcb-util-cursor xcb-util-wm \\" >&2
    echo "            xcb-util-keysyms libxkbcommon-x11 mesa-libEGL mesa-libGL fontconfig dbus-libs" >&2
}

_apt_hint_web() {
    echo "        Debian/Ubuntu:  sudo apt install -y libnss3 libnspr4 libasound2t64 \\" >&2
    echo "            libxcomposite1 libxdamage1 libxrandr2 libxtst6 libatk1.0-0 \\" >&2
    echo "            libatk-bridge2.0-0 libcups2 libdrm2 libgbm1 libpangocairo-1.0-0 libxshmfence1" >&2
    echo "        RHEL/Fedora:    sudo dnf install -y nss nspr alsa-lib libXcomposite \\" >&2
    echo "            libXdamage libXrandr libXtst at-spi2-atk cups-libs libdrm mesa-libgbm pango" >&2
}

# --------------------------------------------------------------- --check mode
if [ "${1:-}" = "--check" ] || [ "${1:-}" = "--doctor" ]; then
    echo "python            : $PYTHON"
    echo "                    $("$PYTHON" -V 2>&1)"
    _base="$(_venv_base)"
    if [ -n "$_base" ]; then
        case "$_base" in
            *conda*|*mamba*) echo "venv built on     : $_base   <- conda: its libraries come with it" ;;
            *)               echo "venv built on     : $_base" ;;
        esac
    fi
    echo "PySide6           : $("$PYTHON" -c 'import PySide6; print(PySide6.__version__, PySide6.__file__)' 2>&1 | tail -1)"
    echo "DISPLAY           : ${DISPLAY:-<unset>}   WAYLAND_DISPLAY: ${WAYLAND_DISPLAY:-<unset>}"
    echo "QT_QPA_PLATFORM   : ${QT_QPA_PLATFORM:-<unset>}"
    echo "LD_LIBRARY_PATH   : ${LD_LIBRARY_PATH:-<unset>}"
    echo "LD_PRELOAD        : ${LD_PRELOAD:-<unset>}"
    _bad="$(_bad_preload)"
    [ -n "$_bad" ] && echo "  !! these do not exist - unset LD_PRELOAD or fix it: $_bad"
    echo "CONDA_PREFIX      : ${CONDA_PREFIX:-<unset>}"
    _conda="$(command -v python3 2>/dev/null | grep -i conda || true)"
    command -v python3 >/dev/null 2>&1 && \
        _conda="$( (which -a python3 2>/dev/null || true) | grep -i conda | head -1)"
    [ -n "${_conda:-}" ] && echo "conda on PATH     : $_conda   <- a common source of library clashes"
    echo "system libs to preload:"
    echo "  $(_preload_syslibs)"
    echo
    _p="$(_qt_file plugins/platforms/libqxcb.so)"
    _m="$(_missing_libs "$_p")"
    echo "xcb plugin        : ${_p:-<not found>}"
    echo "  missing libs    : ${_m:-none}"
    _w="$(_webengine_file)"
    _mw="$(_missing_libs "$_w")"
    echo "QtWebEngine       : ${_w:-<not found>}"
    echo "  missing libs    : ${_mw:-none}"
    echo
    echo "imports:"
    _clash=""
    _failed=""
    for _mod in PySide6.QtWebEngineWidgets rasterio netCDF4 xarray folium plotly openpyxl; do
        printf '  %-26s: ' "$_mod"
        if _err="$("$PYTHON" -c "import $_mod" 2>&1)"; then
            echo "OK"
        else
            echo "FAILED"
            echo "$_err" | tail -2 | sed 's/^/      /'
            _failed="${_failed:+$_failed }$_mod"
            case "$_err" in
                *ffi_type*|*libffi*|*krb5*|*gssapi*|*"undefined symbol"*) _clash=1 ;;
            esac
        fi
    done
    if [ -n "$_clash" ]; then
        echo
        echo "  A library clash: two copies of the same system library are in play - the"
        echo "  distribution's and one shipped inside a wheel (rasterio bundles curl/krb5)"
        echo "  or a conda environment. Whichever loses the load order fails to resolve a"
        echo "  symbol (ffi_type_uint32, krb5_ser_context_init, ...)."
        # Do not just advise it - try it, and say whether it actually helps.
        _pre="$(_preload_syslibs)"
        _still=""
        for _mod in $_failed; do
            printf '  retry with the system libraries preloaded: %-26s: ' "$_mod"
            if LD_PRELOAD="$_pre${LD_PRELOAD:+:$LD_PRELOAD}" \
                    "$PYTHON" -c "import $_mod" >/dev/null 2>&1; then
                echo "OK"
            else
                echo "still failing"
                _still="${_still:+$_still }$_mod"
            fi
        done
        echo
        if [ -z "$_still" ]; then
            echo "  => Start the GUI with:   CWATM_GUI_PRELOAD_SYSLIBS=1 ./gui.sh"
            echo "     (or put  export CWATM_GUI_PRELOAD_SYSLIBS=1  in your ~/.bashrc -"
            echo "      safer than a hand-written LD_PRELOAD, whose paths differ per system)"
        else
            echo "  => Preloading is not enough for: $_still"
            _base="$(_venv_base)"
            case "$_base" in
                *conda*|*mamba*)
                    echo "     This virtualenv was created from **$_base**, so the process"
                    echo "     loads that installation's libraries (its libffi has no symbol"
                    echo "     versions, which is exactly what libwayland-server asks for)."
                    echo "     Build the environment on the system Python instead:"
                    echo "         conda deactivate"
                    echo "         /usr/bin/python3 -V        # needs 3.10 or newer"
                    echo "         /usr/bin/python3 -m venv venv3 && . venv3/bin/activate"
                    echo "         pip install --only-binary=:all: -r requirements.txt"
                    ;;
                *)
                    echo "     Check which copy is loaded and from where:"
                    echo "         LD_DEBUG=libs $PYTHON -c 'import ${_still%% *}' 2>&1 | grep -iE 'krb5|ffi'"
                    ;;
            esac
        fi
    fi
    exit 0
fi

# ------------------------------------------------- does the interpreter work?
# Without this check the GUI dies on "ModuleNotFoundError: No module named
# 'PySide6'" without saying *which* python it tried - and the usual reason is that
# the fallback landed on the system python3 because no Linux venv exists yet.
if ! "$PYTHON" -c 'import PySide6' >/dev/null 2>&1; then
    echo "gui.sh: PySide6 is missing from the interpreter it picked." >&2
    echo "        python : $PYTHON  ($("$PYTHON" -V 2>&1))" >&2
    if [ -x "venv2/bin/python" ] || [ -x "venv/bin/python" ]; then
        echo "        A virtualenv is there, but its packages are not (fully) installed." >&2
    else
        echo "        There is no Linux virtualenv in this folder yet." >&2
        if [ -e "venv/Scripts/python.exe" ]; then
            echo "        (venv/ here is the WINDOWS environment - Scripts/python.exe," >&2
            echo "         no bin/python - so it cannot be used from Linux.)" >&2
        fi
    fi
    echo "    python3 -m venv venv2 && . venv2/bin/activate" >&2
    echo "    pip install --only-binary=:all: -r requirements.txt" >&2
    echo "        If PySide6 has no wheel for this Python, relax that one pin:" >&2
    echo "    pip install --only-binary=:all: 'PySide6>=6.8'" >&2
    exit 1
fi

# --------------------------------------------- Remote X11 (Xming, X2Go, VNC)
# The map and plot windows (Show Basin, NetCDF, Timeseries, Watercycle, Flow
# Diagram, CWatM AI) are QtWebEngine = Chromium, which wants a GPU/GLX that a
# forwarded X11 display does not really provide: without these it renders blank
# or dies. They cost nothing on a local desktop, so they are set unconditionally
# - use CWATM_GUI_SOFTWARE_GL=0 ./gui.sh to take the hardware path instead.
if [ "${CWATM_GUI_SOFTWARE_GL:-1}" != "0" ]; then
    export QT_OPENGL=software          # Qt renders with Mesa's software GL
    export LIBGL_ALWAYS_SOFTWARE=1     # ... and Mesa never asks for hardware
    export QTWEBENGINE_CHROMIUM_FLAGS="${QTWEBENGINE_CHROMIUM_FLAGS:-} --disable-gpu --disable-gpu-compositing --disable-software-rasterizer --no-sandbox"
fi

# QT_XCB_GL_INTEGRATION=none switches GL off in the xcb plugin **completely** - that
# is what makes Qt report "Cannot create platform OpenGL context, neither GLX nor EGL
# are enabled". It is the right setting only for an X server with no usable GLX at
# all (plain Xming), where Qt trying anyway can crash; with software Mesa the other
# way round usually works better, so it is opt-in.
if [ "${CWATM_GUI_XCB_NO_GL:-0}" != "0" ]; then
    export QT_XCB_GL_INTEGRATION=none
fi

# A **remote** display (DISPLAY=host:0, localhost:10.0 from ssh -Y, ...) cannot use
# the MIT-SHM shared-memory extension: Qt asking for it over the wire is a known
# source of BadAccess/BadAlloc crashes, especially on a big window. A local display
# (DISPLAY=:0) keeps it, because it is faster there.
case "${DISPLAY:-}" in
    ""|:*) : ;;
    *) export QT_X11_NO_MITSHM=1 QT_XCB_NO_MITSHM=1 ;;
esac

# Library clashes (see --check): a wheel or a conda env ships its own copy of a system
# library, and whichever copy loses the load order cannot resolve a symbol -
#   ffi_type_uint32        libwayland-server, pulled in by QtWebEngine -> maps/plots die
#   krb5_ser_context_init  libgssapi_krb5, pulled in through curl/GDAL by rasterio
# Preloading the distribution's copies puts them first for the whole process.
if [ "${CWATM_GUI_PRELOAD_SYSLIBS:-0}" != "0" ]; then
    _pre="$(_preload_syslibs)"
    if [ -n "$_pre" ]; then
        export LD_PRELOAD="$_pre${LD_PRELOAD:+:$LD_PRELOAD}"
        [ -n "${CWATM_GUI_VERBOSE:-}" ] && echo "gui.sh: LD_PRELOAD=$LD_PRELOAD" >&2
    else
        echo "gui.sh: CWATM_GUI_PRELOAD_SYSLIBS is set but ldconfig found none of them." >&2
    fi
elif [ "${CWATM_GUI_PRELOAD_FFI:-0}" != "0" ]; then
    _ffi="$(_system_libffi)"          # the older, libffi-only switch
    if [ -n "$_ffi" ]; then
        export LD_PRELOAD="$_ffi${LD_PRELOAD:+:$LD_PRELOAD}"
        [ -n "${CWATM_GUI_VERBOSE:-}" ] && echo "gui.sh: LD_PRELOAD=$LD_PRELOAD" >&2
    else
        echo "gui.sh: CWATM_GUI_PRELOAD_FFI is set but ldconfig knows no libffi." >&2
    fi
fi

if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
    echo "gui.sh: DISPLAY is not set - if you are on SSH, log in with 'ssh -Y'" >&2
    echo "        and start your X server (Xming) on the desktop machine." >&2
fi

# A stale LD_PRELOAD entry makes ld.so complain on every single command; say so once,
# clearly, instead of letting the user wonder where the noise comes from.
_bad_pre="$(_bad_preload)"
if [ -n "$_bad_pre" ]; then
    echo "gui.sh: LD_PRELOAD lists files that do not exist: $_bad_pre" >&2
    echo "        Fix it with:  unset LD_PRELOAD    (and remove it from ~/.bashrc);" >&2
    echo "        then let gui.sh find the right ones: CWATM_GUI_PRELOAD_SYSLIBS=1 ./gui.sh" >&2
fi

# --------------------------------------------------- Qt's system libraries
# Qt's own message ("Could not load the Qt platform plugin xcb ... even though it
# was found") names at most one missing library and gives no package to install.
# ldd lists them all, which turns a dead end into one apt/dnf line.
if [ -z "${QT_QPA_PLATFORM:-}" ] && [ -z "${CWATM_GUI_SKIP_LIB_CHECK:-}" ] \
        && command -v ldd >/dev/null 2>&1; then
    _missing="$(_missing_libs "$(_qt_file plugins/platforms/libqxcb.so)")"
    if [ -n "$_missing" ]; then
        echo "gui.sh: Qt cannot load its xcb platform plugin - these system" >&2
        echo "        libraries are missing (they are NOT pip packages):" >&2
        echo "$_missing" | sed 's/^/            /' >&2
        _apt_hint_qt
        echo "        No root? Unpack the package into your home directory and point" >&2
        echo "        LD_LIBRARY_PATH at it - see the Running on Linux section of CLAUDE.md." >&2
        exit 1
    fi
    # QtWebEngine has its own set. Only the map and plot windows need it, so this
    # is a **warning**: the editor, the Excel window and the model run are fine.
    _webmissing="$(_missing_libs "$(_webengine_file)")"
    if [ -n "$_webmissing" ]; then
        echo "gui.sh: warning - QtWebEngine is missing system libraries, so the map" >&2
        echo "        and plot windows (Show Basin, NetCDF, Timeseries, Watercycle," >&2
        echo "        Flow Diagram, CWatM AI) will not open. The rest works." >&2
        echo "$_webmissing" | sed 's/^/            /' >&2
        _apt_hint_web
    fi
fi

[ -n "${CWATM_GUI_VERBOSE:-}" ] && echo "gui.sh: using $PYTHON" >&2

exec "$PYTHON" cwatm_gui.py "$@"
