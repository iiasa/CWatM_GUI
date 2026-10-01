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


class TestNoShellInjection:
    """The .bat is a shell script: a path must reach the program unchanged - no
    %VAR% expansion, no command operators (security review: B602/B605-type)."""

    HOSTILE = r"C:\data %PATH% & calc ^ x\set%USERNAME%tings (1).ini"

    def test_percent_is_doubled_and_quoted(self):
        assert bfc._quote(r"C:\a%b%\c.ini") == r'"C:\a%%b%%\c.ini"'

    def test_quote_or_line_break_is_refused(self):
        for bad in ('C:\\a"b.ini', "C:\\a\nb.ini", "C:\\a\rb.ini"):
            with pytest.raises(ValueError):
                bfc._quote(bad)

    @pytest.mark.skipif(sys.platform != "win32", reason="needs cmd.exe")
    def test_cmd_passes_the_path_through_verbatim(self, tmp_path):
        # A real cmd.exe runs a .bat built with _quote: the program must receive
        # the hostile path as ONE argument, character for character.
        import subprocess
        out = tmp_path / "argv.txt"
        probe = "import sys,pathlib; pathlib.Path(sys.argv[1]).write_text(" \
                "repr(sys.argv[2:]), encoding='utf-8')"
        line = " ".join(bfc._quote(t) for t in
                        [sys.executable, "-c", probe, str(out), self.HOSTILE, "-l"])
        bat = tmp_path / "probe.bat"
        bat.write_text("@echo off\r\n" + line + "\r\n", encoding="utf-8")
        subprocess.run(["cmd", "/c", str(bat)], check=True, timeout=60,
                       capture_output=True)
        assert out.read_text(encoding="utf-8") == repr([self.HOSTILE, "-l"])
