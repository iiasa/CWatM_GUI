"""
Child-process CWatM runner - the code that runs INSIDE the model subprocess.

The GUI runs the model in a separate OS process (GUI_Improvement_Report §3.1):
Stop is a real kill, a model crash cannot take the GUI down, and every run starts
from a genuinely fresh interpreter (no sys.modules purging). This module executes
the model exactly like the old in-process worker did - run_cwatm.mainwarm with the
'-lg' flags and a stub GUI object - and talks back to the parent over plain stdout:

- all model output streams through unchanged (the GUI shows it live, including the
  '\r date discharge' progress line);
- progress: the pre-existing GUI hook in cwatm/management_modules/output.py calls
  gui.progress_clock.setValue(pct) once per timestep - the stub turns that into a
  '@@CWATM_GUI:PROGRESS:<pct>@@' stdout line (no cwatm code involved);
- result: a final '@@CWATM_GUI:RESULT:<success>:<last_dis>@@' line.

The parent side (src/gui/utils/cwatm_process_worker.py) strips these marker lines
from the stream before display. Entry points that call main():
- frozen build:  CWatM_model.exe <settings.ini>          (see cwatm_gui_dir.spec)
                 CWatM_GUI.exe --run-cwatm <settings.ini> (fallback, older builds)
- from source:   python cwatm_gui.py --run-cwatm <settings.ini>
                 (dispatched at the very top of cwatm_gui.py, before any Qt import)

MUST NOT import PySide6/Qt: the child stays light, and run_cwatm.mainwarm calls
globalclear() when it sees PySide6 in sys.modules (an in-process-era workaround
that a fresh process does not need).
"""

import io
import os
import sys
import traceback

# Same rasterio-1.5.0 x numpy-2.5 deprecation filter as cwatm_gui.py - applied
# here too because the model child (CWatM_model.exe) starts at this module and
# never imports cwatm_gui, and the model does far more raster reads than the GUI.
from src.gui.utils.warning_filters import apply as _apply_warning_filters

_apply_warning_filters()

# Marker protocol shared with cwatm_process_worker.py (keep in sync).
MARKER = "@@CWATM_GUI:"
MARKER_END = "@@"


def _emit(kind, payload):
    """Write one marker line. The leading newline terminates a dangling
    '\r...' model progress line; the parent strips both injected newlines."""
    sys.stdout.write("\n%s%s:%s%s\n" % (MARKER, kind, payload, MARKER_END))
    sys.stdout.flush()


class _MarkerClock:
    """Receives the model-side progress hook (progress_clock.setValue(pct),
    called once per timestep from cwatm/management_modules/output.py) and
    emits each new percentage as a stdout marker line."""

    def __init__(self):
        self._last = None

    def setValue(self, value):
        value = int(value)
        if value != self._last:
            self._last = value
            _emit("PROGRESS", str(value))


class _GuiStub:
    """Minimal object handed to run_cwatm.mainwarm as the 'gui' argument."""

    def __init__(self):
        self.progress_clock = _MarkerClock()


def _ensure_std_streams():
    """A windowed frozen exe can start with sys.stdout/stderr set to None even
    though the parent provided pipe handles; reattach them to fd 1/2 so the GUI
    receives the output. No-op when the streams are already usable."""
    for name, fd in (("stdout", 1), ("stderr", 2)):
        if getattr(sys, name, None) is None:
            try:
                stream = io.TextIOWrapper(open(fd, "wb", buffering=0),
                                          encoding="utf-8", errors="replace",
                                          write_through=True)
            except OSError:
                stream = open(os.devnull, "w")
            setattr(sys, name, stream)


def main(argv):
    """Run CWatM on the settings file in argv[0] and report the result marker.
    Optional extra argv entries are the CWatM flags (default '-lg': loud output
    + the GUI progress hook, exactly like the in-process worker). Returns the
    process exit code (0 = model reported success)."""
    _ensure_std_streams()
    if not argv:
        sys.stderr.write("usage: CWatM_model <settings.ini> [cwatm flags]\n")
        return 2

    settings = argv[0]
    flags = list(argv[1:]) or ["-lg"]
    success, last_dis = False, None
    try:
        if not os.path.isfile(settings):
            raise FileNotFoundError("Settings file not found: %s" % settings)
        import cwatm.run_cwatm as run_cwatm
        result = run_cwatm.mainwarm(settings, flags, _GuiStub())
        if isinstance(result, tuple) and len(result) == 2:
            success, last_dis = result
    except SystemExit as e:
        # CWatM calls sys.exit() deep inside on some fatal errors - in its own
        # process that is safe; just report it and fall through to the result.
        sys.stderr.write("CWatM exited early (code %s)\n" % (e.code,))
    except BaseException:
        traceback.print_exc()

    try:
        last_txt = "None" if last_dis is None else repr(float(last_dis))
    except (TypeError, ValueError):
        last_txt = "None"
    _emit("RESULT", "%s:%s" % (bool(success), last_txt))
    return 0 if success else 1


if __name__ == "__main__":
    # Allow direct invocation for debugging: python cwatm_model_runner.py <ini>
    _root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    sys.exit(main(sys.argv[1:]))
