"""
Parent-side subprocess CWatM worker (GUI_Improvement_Report §3.1).

Runs the model in a separate OS process via QProcess and exposes the same signal
interface as the in-process CWatMWorker (finished / error / progress), so
run_controller can use either interchangeably (Configure > "Run model in separate
process"). What this buys over the QThread worker:

- Stop is a real kill() - works even when the model hangs inside C code;
- a hard crash (segfault in a C extension) cannot take the GUI down;
- every run starts from a fresh interpreter: no sys.modules purging, no
  gc.get_objects() file cleanup, GUI memory stays flat between runs.

The child (src/gui/utils/cwatm_model_runner.py) streams the model output over the
stdout/stderr pipes. This worker strips the '@@CWATM_GUI:...@@' marker lines
(progress percentage + final result), splits the rest into per-line writes to
sys.stdout / sys.stderr - the GUI's PrintRedirector routes both into the output
box exactly like in-process prints (stderr in dark red, '\r' lines overwriting
in place).
"""

import os
import re
import sys

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from src.gui.utils.gui_log import get_logger
from src.gui.utils import warning_filters

log = get_logger("cwatm_process_worker")

# Marker protocol shared with cwatm_model_runner.py (keep in sync).
MARKER = "@@CWATM_GUI:"
MARKER_END = "@@"


def _gui_root():
    """The gui project root (the folder holding cwatm_gui.py, cwatm/ and src/)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))


def _model_command(file_path):
    """Return (program, arguments, working_dir) that runs the model runner in a
    child process.

    frozen build: prefer the dedicated CWatM_model.exe (light, console subsystem =
    guaranteed std pipes; QProcess starts it with CREATE_NO_WINDOW so no console
    flashes). It lives in _internal/ (hidden from users - the app folder shows
    only CWatM_GUI.exe; the spec moves it there and builds it with
    contents_directory='.'), or next to the GUI exe in older builds. Fall back to
    re-entering the GUI exe with --run-cwatm (shows the splash briefly and pays
    the Qt bootstrap, but works).
    from source: the venv python running cwatm_gui.py --run-cwatm (the dispatch at
    the top of cwatm_gui.py runs the model before any Qt import)."""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        for model_exe in (os.path.join(exe_dir, "_internal", "CWatM_model.exe"),
                          os.path.join(exe_dir, "CWatM_model.exe")):
            if os.path.isfile(model_exe):
                return model_exe, [file_path], exe_dir
        return sys.executable, ["--run-cwatm", file_path], exe_dir
    root = _gui_root()
    return (_console_python(),
            ["-u", os.path.join(root, "cwatm_gui.py"), "--run-cwatm", file_path],
            root)


def _console_python():
    """The console python (python.exe) matching this interpreter. When the GUI is
    launched with pythonw.exe (e.g. via gui.bat, to hide the console), sys.executable
    is pythonw.exe - but pythonw has no std streams, which would break the run-output
    pipe. python.exe sits next to it in the venv; use that for the model child."""
    exe = sys.executable
    base = os.path.basename(exe).lower()
    if base == "pythonw.exe":
        cand = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.isfile(cand):
            return cand
    return exe


class CWatMProcessWorker(QObject):
    """Run CWatM in a child process; same signals as CWatMWorker."""

    finished = Signal(bool, object)  # success, last_dis
    error = Signal(str)              # error message
    progress = Signal(int)           # progress value 0-100

    def __init__(self, file_path, gui_window=None, output_sink=None,
                 working_dir=None):
        super().__init__(gui_window)
        self.file_path = file_path
        # working_dir: the directory the child process is started in, so relative
        # paths in the settings file resolve from there (File > Change Working Dir).
        # None = _model_command's default (the exe/source root).
        self._working_dir = working_dir
        # output_sink(text, is_error): if given, run output is delivered here instead
        # of being written to sys.stdout / sys.stderr. Used by the Hidden Run windows
        # so each one shows its run in its OWN output box (the default None keeps the
        # main-window behaviour - route through the global PrintRedirector - unchanged).
        self._output_sink = output_sink
        self._stdout_buf = ""   # undelivered stdout (may hold a partial marker)
        self._stdout_line = ""  # unterminated stdout line held back for display
        self._stderr_line = ""  # unterminated stderr line held back for display
        self._result = None     # (success, last_dis) from the RESULT marker
        # Last net for the rasterio x numpy 2.5 shape deprecation: drops those
        # lines if the child prints them regardless of the filters (a frozen
        # CWatM_model.exe left over from an older build, a PYTHONWARNINGS the
        # user set themselves, ...). One per stream - they interleave.
        self._suppress = {"_stdout_line": warning_filters.LineSuppressor(),
                          "_stderr_line": warning_filters.LineSuppressor()}
        self._stopped = False   # user pressed Stop - suppress signals
        self._reported = False  # finished/error already emitted

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.SeparateChannels)
        # (QProcess on Windows starts the child with CREATE_NO_WINDOW by default, so
        # the console python child never flashes a window - even when the GUI itself
        # runs without a console, e.g. launched via gui.bat/pythonw.)
        self.process.readyReadStandardOutput.connect(self._on_stdout)
        self.process.readyReadStandardError.connect(self._on_stderr)
        self.process.finished.connect(self._on_finished)
        self.process.errorOccurred.connect(self._on_proc_error)

    # ------------------------------------------------------------- lifecycle
    def start(self):
        """Spawn the model child process."""
        program, args, workdir = _model_command(self.file_path)
        if self._working_dir and os.path.isdir(self._working_dir):
            workdir = self._working_dir
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")    # live output through the pipe
        env.insert("PYTHONIOENCODING", "utf-8")
        # Silence the rasterio x numpy 2.5 shape deprecation from the child's
        # interpreter start-up (a frozen child ignores this - it applies the
        # filter itself; _suppress below is the final net for either).
        env.insert("PYTHONWARNINGS",
                   warning_filters.export_to_environment(dict(os.environ)))
        self.process.setProcessEnvironment(env)
        self.process.setWorkingDirectory(workdir)
        self.progress.emit(0)
        log.info("starting model process: %s %s", program, args)
        self.process.start(program, args)

    def stop(self):
        """Kill the model process (a real, immediate stop - the whole point of
        the subprocess architecture). Safe to call at any time."""
        self._stopped = True
        if self.process.state() != QProcess.NotRunning:
            self.process.kill()
            self.process.waitForFinished(3000)

    # --------------------------------------------------------------- stdout
    def _on_stdout(self):
        data = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")
        self._stdout_buf += data.replace("\r\n", "\n")
        self._drain_stdout()

    def _drain_stdout(self, final=False):
        """Extract complete @@CWATM_GUI:...@@ markers from the buffered stream,
        forward the remaining text for display, and keep back only an incomplete
        marker / an unterminated normal line until more data arrives."""
        buf = self._stdout_buf
        out = []
        pos = 0
        while True:
            i = buf.find(MARKER, pos)
            if i < 0:
                break
            end = buf.find(MARKER_END, i + len(MARKER))
            if end < 0:
                break  # marker not complete yet - wait for the next chunk
            seg = buf[pos:i]
            if seg.endswith("\n"):
                seg = seg[:-1]  # swallow the newline the runner injects before
            out.append(seg)
            self._handle_marker(buf[i + len(MARKER):end])
            pos = end + len(MARKER_END)
            if pos < len(buf) and buf[pos] == "\n":
                pos += 1        # ... and the one it injects after
        rest = buf[pos:]
        # Hold back an incomplete marker, or a possible marker prefix at the end
        hold = 0
        if not final:
            i = rest.find(MARKER)
            if i >= 0:
                hold = len(rest) - i
            else:
                for k in range(min(len(MARKER) - 1, len(rest)), 0, -1):
                    if rest.endswith(MARKER[:k]):
                        hold = k
                        break
        cut = len(rest) - hold
        out.append(rest[:cut])
        self._stdout_buf = rest[cut:]
        self._forward("".join(out), sys.stdout, "_stdout_line", final)

    def _handle_marker(self, payload):
        kind, _, value = payload.partition(":")
        if kind == "PROGRESS":
            try:
                self.progress.emit(int(value))
            except ValueError:
                log.debug("bad progress marker: %r", value)
        elif kind == "RESULT":
            ok, _, dis = value.partition(":")
            try:
                last_dis = None if dis in ("", "None") else float(dis)
            except ValueError:
                last_dis = None
            self._result = (ok == "True", last_dis)

    # --------------------------------------------------------------- stderr
    def _on_stderr(self):
        data = bytes(self.process.readAllStandardError()).decode("utf-8", "replace")
        self._forward(data.replace("\r\n", "\n"), sys.stderr, "_stderr_line", False)

    # -------------------------------------------------------------- display
    def _forward(self, text, stream, line_attr, final):
        """Forward stream text as one write() per line, mimicking the in-process
        prints the output box was built around (each write = one box line; a
        leading '\r' marks the overwrite-in-place progress line). An unterminated
        trailing line is held back unless it is a '\r' progress line (those are
        never newline-terminated - the model overwrites them in place)."""
        data = getattr(self, line_attr) + text
        lines = data.split("\n")
        tail = lines.pop()
        if final or tail.lstrip(" \t").startswith("\r"):
            if tail:
                lines.append(tail)
            tail = ""
        setattr(self, line_attr, tail)
        suppress = self._suppress[line_attr]
        for line in lines:
            if suppress(line):
                continue
            # A chunk can carry several '\r' progress prints - split them so each
            # becomes its own write (the box coalesces consecutive ones).
            for piece in re.split(r"(?=\r)", line):
                if piece:
                    try:
                        if self._output_sink is not None:
                            self._output_sink(piece, stream is sys.stderr)
                        else:
                            stream.write(piece)
                    except Exception:
                        log.debug("output forward failed", exc_info=True)

    # ------------------------------------------------------------ completion
    def _on_finished(self, exit_code, exit_status):
        self._drain_stdout(final=True)
        self._forward("", sys.stderr, "_stderr_line", True)
        if self._stopped or self._reported:
            return
        self._reported = True
        if self._result is not None:
            success, last_dis = self._result
            self.finished.emit(success, last_dis)
        elif exit_status == QProcess.CrashExit:
            self.error.emit("CWatM process crashed")
        else:
            self.error.emit(
                "CWatM process ended without a result (exit code %s)" % exit_code)

    def _on_proc_error(self, proc_error):
        # Crashed is reported through _on_finished; only a start failure must be
        # raised here (finished() never fires in that case).
        if self._stopped or self._reported:
            return
        if proc_error == QProcess.FailedToStart:
            self._reported = True
            self.error.emit(
                "Could not start the CWatM process: %s" % self.process.program())
