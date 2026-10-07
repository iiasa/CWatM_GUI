"""
RUN CWATM > Create batch - write a standalone Windows .bat file that runs CWatM on
the current settings file without opening the GUI at all.

Reuses cwatm_process_worker.model_command() - the exact same frozen/source
detection the GUI itself uses to spawn the model child process - so the batch file
launches CWatM the identical way a normal Run CWATM does (CWatM_model.exe when
frozen, the venv python running "cwatm_model.py" from source). Pure
logic, no Qt: kept separate from the QFileDialog/QMessageBox wiring in
run_controller.py so it can be unit tested without a display.
"""

import os
import re

from src.gui.utils.cwatm_process_worker import model_command


def _quote(token):
    """One token for a .bat line: double-quoted, with every ``%`` doubled.

    Quoting keeps spaces and cmd's operators (``& | < > ^``) literal. It does NOT
    stop ``%NAME%`` expansion: cmd expands variables even inside quotes, so a
    folder or file name containing ``%`` (allowed on Windows) would be rewritten -
    with an environment value that could itself carry operators. ``%%`` is cmd's
    literal percent in a batch file. A ``"`` cannot occur (not allowed in Windows
    paths); a token that has one anyway, or a line break, is refused rather than
    written into a script."""
    token = str(token)
    if any(c in token for c in '"\r\n'):
        raise ValueError(f"cannot put this into a batch file safely: {token!r}")
    return '"%s"' % token.replace("%", "%%")


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
