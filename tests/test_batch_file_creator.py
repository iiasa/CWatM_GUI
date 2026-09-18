"""RUN CWATM > Create batch (`src/gui/utils/batch_file_creator.py`).

Pure logic: given a settings file path (and whether the process is frozen), build
the exact command line a standalone .bat file needs to run CWatM headlessly. It
reuses cwatm_process_worker.model_command() - the same frozen/source detection a
normal Run CWATM uses - so these tests exercise both branches directly.

Needs Qt only because cwatm_process_worker imports PySide6.QtCore for QProcess.
"""

import os
import sys

import pytest

pytestmark = pytest.mark.qt

from src.gui.utils import batch_file_creator as bfc


class TestSuggestedBatchName:
    def test_basic(self):
        assert bfc.suggested_batch_name(r"C:\runs\settings.ini") == "Run_settings.bat"

    def test_strips_unsafe_characters(self):
        # A colon/backslash inside the base name (not the directory) must not
        # survive into the filename.
        name = bfc.suggested_batch_name("weird:name?.ini")
        assert name == "Run_weird_name_.bat"

    def test_empty_falls_back(self):
        assert bfc.suggested_batch_name("") == "Run_cwatm.bat"
        assert bfc.suggested_batch_name(None) == "Run_cwatm.bat"


class TestBuildBatchScript:
    def test_source_mode(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        content = bfc.build_batch_script(r"C:\proj\settings.ini", r"C:\proj")

        lines = content.split("\r\n")
        assert lines[0] == "@echo off"
        assert lines[1] == 'cd /d "C:\\proj"'
        assert "--run-cwatm" in lines[2]
        assert '"C:\\proj\\settings.ini"' in lines[2]
        assert lines[2].rstrip().endswith('"-l"')
        assert lines[3] == "pause"
        assert content.endswith("\r\n")

    def test_frozen_mode_uses_model_exe(self, monkeypatch, tmp_path):
        exe_dir = tmp_path / "CWatM_GUI"
        internal = exe_dir / "_internal"
        internal.mkdir(parents=True)
        model_exe = internal / "CWatM_model.exe"
        model_exe.write_text("stub")

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(exe_dir / "CWatM_GUI.exe"),
                             raising=False)

        content = bfc.build_batch_script(r"C:\runs\settings.ini", r"C:\runs")

        run_line = content.split("\r\n")[2]
        assert str(model_exe) in run_line
        assert '"C:\\runs\\settings.ini"' in run_line
        assert run_line.rstrip().endswith('"-l"')

    def test_no_workdir_omits_cd(self, monkeypatch):
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        content = bfc.build_batch_script(r"C:\proj\settings.ini", "")
        lines = content.split("\r\n")
        assert lines[0] == "@echo off"
        assert not lines[1].startswith("cd /d")
