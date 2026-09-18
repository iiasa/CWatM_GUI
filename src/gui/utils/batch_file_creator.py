"""
RUN CWATM > Create batch - write a standalone Windows .bat file that runs CWatM on
the current settings file without opening the GUI at all.

Reuses cwatm_process_worker.model_command() - the exact same frozen/source
detection the GUI itself uses to spawn the model child process - so the batch file
launches CWatM the identical way a normal Run CWATM does (CWatM_model.exe when
frozen, the venv python running "cwatm_gui.py --run-cwatm" from source). Pure
logic, no Qt: kept separate from the QFileDialog/QMessageBox wiring in
run_controller.py so it can be unit tested without a display.
"""

import os
import re

from src.gui.utils.cwatm_process_worker import model_command


def _quote(token):
    """Double-quote a command-line token unconditionally. Harmless for a bare
    flag (cmd.exe's argv parser strips the surrounding quotes back off) and
    required for any program/settings path that may contain spaces."""
    return '"%s"' % token


def build_batch_script(file_path, workdir):
    """Return the text of a .bat file that runs CWatM on `file_path` with the
    '-l' flag and then pauses so a double-clicked console window stays open to
    show the result.

    `workdir` (typically the main window's working_dir()) is cd'd into first, so
    relative paths in the settings file resolve the same way they do for a normal
    Run CWATM - the batch file can then be moved anywhere and still work."""
    program, args, _default_workdir = model_command(file_path)
    command = " ".join(_quote(t) for t in [program] + list(args) + ["-l"])
    lines = ["@echo off"]
    if workdir:
        lines.append("cd /d %s" % _quote(workdir))
    lines.append(command)
    lines.append("pause")
    return "\r\n".join(lines) + "\r\n"


def suggested_batch_name(file_path):
    """A filesystem-safe default filename for the batch file, derived from the
    settings file's own name (e.g. settings.ini -> Run_settings.bat)."""
    base = os.path.splitext(os.path.basename(file_path or ""))[0] or "cwatm"
    base = re.sub(r'[<>:"/\\|?*]', "_", base).strip() or "cwatm"
    return f"Run_{base}.bat"
