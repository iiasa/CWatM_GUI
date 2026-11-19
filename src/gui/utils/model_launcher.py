"""
How the Windowed Run CWatM window starts the model (its gear button).

Two choices, persisted in QSettings:
- **Use predefined** (default): the model the GUI ships with - ``model_command`` in
  ``cwatm_process_worker`` (frozen: ``_internal/CWatM_model.exe``; from source: the
  venv python running ``cwatm_model.py``).
- **User defined**: a command line the user types, e.g.
  ``P:\\watmodel\\CWatM_model.exe`` or ``python P:\\watmodel\\cwatmpublic\\develop\\run_cwatm.py``
  (or just a ``.py`` script / a CWatM folder). The settings file and the CWatM flags
  are appended to it.

Pure logic (no Qt) except the two QSettings helpers at the end.
"""

import os
import shlex
import shutil
from datetime import datetime, timedelta

PREDEFINED_KEY = "hidden_run/use_predefined"
USER_COMMAND_KEY = "hidden_run/user_command"
# Expert only: the user-defined model also runs the main RUN CWATM (and Run CWatM +
# error message). Off by default; meaningful only with "User defined".
MAIN_RUN_KEY = "hidden_run/use_for_main_run"

# CWatM flags for a user-defined model: -l = loud (the per-timestep date + discharge
# line, which also drives the progress display). No -g: such a model has no GUI hook.
USER_FLAGS = ["-l"]


def _read_key(content, key):
    """First uncommented ``key = value`` in a settings file, or ""."""
    for line in (content or "").split("\n"):
        s = line.strip()
        if not s or s[0] in "#;[" or "=" not in s:
            continue
        k, v = s.split("=", 1)
        if k.strip().lower() == key.lower():
            return v.strip()
    return ""


def run_window(content):
    """(StepStart, StepEnd) as datetimes from the settings content, or (None, None).
    StepEnd may be a timestep count (CWatM: the n-th day from StepStart)."""
    try:
        start = datetime.strptime(_read_key(content, "StepStart"), "%d/%m/%Y")
    except ValueError:
        return None, None
    end_txt = _read_key(content, "StepEnd")
    if end_txt.isdigit():
        return start, start + timedelta(days=int(end_txt) - 1)
    try:
        return start, datetime.strptime(end_txt, "%d/%m/%Y")
    except ValueError:
        return None, None


def progress_from_line(text, window):
    """Progress % from a CWatM per-timestep line ``\\r<step> <dd/mm/yyyy> <dis>``
    against ``window`` = run_window(...); None when it cannot be told. Used for a
    user-defined model, which sends no progress markers."""
    start, end = window
    if start is None or end is None or end < start:
        return None
    parts = (text or "").strip().split()
    if len(parts) < 2:
        return None
    try:
        date = datetime.strptime(parts[-2], "%d/%m/%Y")
    except ValueError:
        return None
    total = (end - start).days + 1
    done = (date - start).days + 1
    return max(0, min(100, int(done * 100 / total)))

# Inside a CWatM folder: what to run, in this order.
_FOLDER_CANDIDATES = ("CWatM_model.exe", os.path.join("_internal", "CWatM_model.exe"),
                      "run_cwatm.py", os.path.join("cwatm", "run_cwatm.py"))


def _unquote(token):
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    return token


def _for_target(path, python):
    """(program, prefix args) for one existing file or folder."""
    if os.path.isdir(path):
        for cand in _FOLDER_CANDIDATES:
            full = os.path.join(path, cand)
            if os.path.isfile(full):
                return _for_target(full, python)
        raise ValueError(
            "No CWatM_model.exe or run_cwatm.py found in the folder:\n  %s" % path)
    if path.lower().endswith(".py"):
        return python, ["-u", path]
    return path, []


def parse_command(text, python):
    """Turn the user's command line into ``(program, prefix_args)``.

    ``python`` is the interpreter used for a bare ``.py`` script or a folder holding
    ``run_cwatm.py``. Raises ``ValueError`` with a readable reason."""
    text = (text or "").strip()
    if not text:
        raise ValueError("No user-defined command given.")
    # A whole line that is one existing path (it may hold spaces, unquoted).
    whole = _unquote(text)
    if os.path.exists(whole):
        return _for_target(whole, python)
    try:
        tokens = [_unquote(t) for t in shlex.split(text, posix=False)]
    except ValueError as e:
        raise ValueError("Cannot read the command: %s" % e)
    if not tokens:
        raise ValueError("No user-defined command given.")
    program, rest = tokens[0], tokens[1:]
    if not rest and program.lower().endswith(".py"):
        if not os.path.isfile(program):
            raise ValueError("Script not found:\n  %s" % program)
        return python, ["-u", program]
    if os.path.dirname(program):
        if not os.path.isfile(program):
            raise ValueError("Program not found:\n  %s" % program)
    else:
        found = shutil.which(program)
        if found is None:
            raise ValueError("'%s' is not found on the PATH." % program)
        program = os.path.normpath(found)   # full path: shown, and what is started
    for arg in rest:
        if arg.lower().endswith(".py") and not os.path.isfile(arg):
            raise ValueError("Script not found:\n  %s" % arg)
    return program, rest


def display(program, args):
    """One readable line for the output box."""
    return " ".join('"%s"' % a if " " in a else a for a in [program] + list(args))


# ------------------------------------------------------------------ QSettings
def _settings():
    from PySide6.QtCore import QSettings
    return QSettings("IIASA", "CWatM_GUI")


def load_choice():
    """``(use_predefined, user_command)`` as stored."""
    s = _settings()
    use = s.value(PREDEFINED_KEY, True)
    if isinstance(use, str):
        use = use.lower() not in ("false", "0", "no")
    return bool(use), str(s.value(USER_COMMAND_KEY, "") or "")


def save_choice(use_predefined, user_command):
    s = _settings()
    s.setValue(PREDEFINED_KEY, bool(use_predefined))
    s.setValue(USER_COMMAND_KEY, user_command or "")


def load_main_run():
    """The Expert tick: does the main RUN CWATM use the user-defined model too?"""
    v = _settings().value(MAIN_RUN_KEY, False)
    if isinstance(v, str):
        v = v.lower() in ("true", "1", "yes")
    return bool(v)


def save_main_run(on):
    _settings().setValue(MAIN_RUN_KEY, bool(on))


def main_run_user_command():
    """The user-defined command text when the **main** run must use it (User defined
    chosen **and** the Expert tick on), else None = the standard CWatM."""
    use_predefined, cmd = load_choice()
    if use_predefined or not load_main_run():
        return None
    return cmd
