"""Windowed Run CWatM's gear window: parsing the user-defined model command."""

import os

import pytest

from src.gui.utils import model_launcher as m

PY = os.path.join("venv", "python.exe")


def test_exe_alone(tmp_path):
    exe = tmp_path / "CWatM_model.exe"
    exe.write_text("")
    assert m.parse_command(str(exe), PY) == (str(exe), [])


def test_exe_with_spaces_unquoted(tmp_path):
    d = tmp_path / "my apps"
    d.mkdir()
    exe = d / "CWatM_model.exe"
    exe.write_text("")
    assert m.parse_command(str(exe), PY) == (str(exe), [])
    assert m.parse_command(f'"{exe}"', PY) == (str(exe), [])


def test_script_alone_uses_given_python(tmp_path):
    script = tmp_path / "run_cwatm.py"
    script.write_text("")
    assert m.parse_command(str(script), PY) == (PY, ["-u", str(script)])


def test_folder_finds_run_cwatm(tmp_path):
    (tmp_path / "run_cwatm.py").write_text("")
    assert m.parse_command(str(tmp_path), PY) == (
        PY, ["-u", str(tmp_path / "run_cwatm.py")])


def test_python_command_line(tmp_path):
    script = tmp_path / "run_cwatm.py"
    script.write_text("")
    exe = tmp_path / "python.exe"
    exe.write_text("")
    assert m.parse_command(f"{exe} {script}", PY) == (str(exe), [str(script)])


@pytest.mark.parametrize("text", ["", "   ", r"Z:\no\such\CWatM_model.exe",
                                  "no_such_program_xyz run.py"])
def test_refused(text):
    with pytest.raises(ValueError):
        m.parse_command(text, PY)


def test_run_window_dates_and_count():
    from datetime import datetime
    assert m.run_window("StepStart = 1/1/2000\nStepEnd = 31/12/2000") == (
        datetime(2000, 1, 1), datetime(2000, 12, 31))
    assert m.run_window("StepStart = 1/1/2000\nStepEnd = 10")[1] == datetime(2000, 1, 10)
    assert m.run_window("StepStart = x") == (None, None)


def test_progress_from_line():
    win = m.run_window("StepStart = 1/1/2000\nStepEnd = 10")
    assert m.progress_from_line("\r5      05/01/2000      3.20", win) == 50
    assert m.progress_from_line("\r.....", win) is None
    assert m.progress_from_line("\r5 05/01/2000 3.2", (None, None)) is None


def test_missing_script_refused(tmp_path):
    exe = tmp_path / "python.exe"
    exe.write_text("")
    with pytest.raises(ValueError):
        m.parse_command(f"{exe} {tmp_path / 'missing.py'}", PY)
