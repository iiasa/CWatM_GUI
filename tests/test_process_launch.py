"""How the GUI starts other programs (security review: subprocess B602/B603/B607).

- The model run is started with QProcess.start(program, [arguments]) - an argument
  LIST, no shell - and the settings path is exactly one argument, whatever
  characters it holds. This is unchanged by the review (so the run is bit-identical).
- open_path() never hands a program or script to the desktop (os.startfile would
  RUN it); it shows the folder instead.
"""

import os
import sys

import pytest

pytestmark = pytest.mark.qt

from src.gui.utils import cwatm_process_worker as W  # noqa: E402
from src.gui.utils import open_path as O  # noqa: E402

HOSTILE = r"C:\data %PATH% & calc ^ x\settings;rm -rf (1).ini"


@pytest.mark.parametrize("frozen", [False, True])
def test_model_command_is_a_list_with_the_path_as_one_argument(monkeypatch, tmp_path,
                                                                frozen):
    if frozen:
        internal = tmp_path / "_internal"
        internal.mkdir()
        (internal / "CWatM_model.exe").write_text("stub")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(tmp_path / "CWatM_GUI.exe"))
    else:
        monkeypatch.setattr(sys, "frozen", False, raising=False)
    program, args, workdir = W.model_command(HOSTILE)
    assert isinstance(args, list) and args.count(HOSTILE) == 1
    assert all(isinstance(a, str) for a in args)


def test_the_worker_starts_the_process_with_a_list(qapp, monkeypatch):
    started = []
    worker = W.CWatMProcessWorker(HOSTILE)
    monkeypatch.setattr(worker.process, "start",
                        lambda program, args: started.append((program, args)))
    worker.start()
    (program, args), = started
    assert isinstance(args, list) and HOSTILE in args      # never one shell string


@pytest.mark.parametrize("name", ["evil.bat", "evil.EXE", "x.vbs", "x.js", "x.ps1",
                                  "x.lnk", "x.hta", "x.msi", "x.sh", "x.desktop"])
def test_a_program_is_never_opened_its_folder_is(monkeypatch, tmp_path, name):
    target = tmp_path / name
    target.write_text("stub")
    opened = []
    monkeypatch.setattr(O.os, "startfile", lambda p: opened.append(p), raising=False)
    monkeypatch.setattr(O.QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url.toLocalFile()) or True))
    assert O.open_path(str(target))
    assert opened and os.path.normcase(opened[0].rstrip("/\\")) == \
        os.path.normcase(str(tmp_path))


@pytest.mark.parametrize("name", ["discharge.html", "cwatm_out.txt", "a.csv", "a.nc"])
def test_documents_still_open_directly(monkeypatch, tmp_path, name):
    target = tmp_path / name
    target.write_text("x")
    opened = []
    monkeypatch.setattr(O.os, "startfile", lambda p: opened.append(p), raising=False)
    monkeypatch.setattr(O.QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url.toLocalFile()) or True))
    assert O.open_path(str(target))
    assert os.path.normcase(opened[0]) == os.path.normcase(str(target))


def test_a_folder_named_like_a_program_is_a_folder(tmp_path):
    d = tmp_path / "results.app"
    d.mkdir()
    assert not O.is_runnable(str(d))
