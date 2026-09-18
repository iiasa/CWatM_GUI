"""`src/gui/managers/file_manager.py` - FileManager.

Covers the plain file I/O methods (`load_file_from_path`, `save_file`, `save_as_file`
with an explicit path, the getters) against real files under `tmp_path`.
`choose_load_path`/`choose_save_path` open a `QFileDialog` and are exercised only
through `save_as_file(file_path=None)`, monkeypatched so no real dialog pops up - the
same split main_window relies on to run its duplicate-tab guard before a path is
chosen (see the module docstring).
"""

import pytest

from src.gui.managers.file_manager import FileManager

pytestmark = pytest.mark.qt


@pytest.fixture
def fm():
    return FileManager(parent_window=None)


class TestLoadFileFromPath:
    def test_reads_content_and_records_the_path(self, fm, tmp_path):
        f = tmp_path / "settings.ini"
        f.write_text("Title = test\n", encoding="utf-8")
        content, name = fm.load_file_from_path(str(f))
        assert content == "Title = test\n"
        assert name == "settings.ini"
        assert fm.current_file_path == str(f)

    def test_missing_file_returns_none_and_an_error_message(self, fm, tmp_path):
        content, message = fm.load_file_from_path(str(tmp_path / "nope.ini"))
        assert content is None
        assert message.startswith("Error:")
        assert fm.current_file_path is None       # unchanged on failure

    def test_reads_utf8_content(self, fm, tmp_path):
        f = tmp_path / "unicode.ini"
        f.write_text("Title = Bassin de l'Èbre\n", encoding="utf-8")
        content, _name = fm.load_file_from_path(str(f))
        assert "Èbre" in content


class TestSaveFile:
    def test_writes_to_the_given_path(self, fm, tmp_path):
        f = tmp_path / "out.ini"
        ok, message = fm.save_file("Title = x\n", str(f))
        assert ok is True
        assert f.read_text(encoding="utf-8") == "Title = x\n"
        assert str(f) in message

    def test_falls_back_to_current_file_path(self, fm, tmp_path):
        f = tmp_path / "out.ini"
        fm.current_file_path = str(f)
        ok, _message = fm.save_file("content\n")
        assert ok is True
        assert f.read_text(encoding="utf-8") == "content\n"

    def test_no_path_at_all_fails_cleanly(self, fm):
        ok, message = fm.save_file("content\n")
        assert ok is False
        assert message == "No file path specified"

    def test_unwritable_path_reports_the_error_instead_of_raising(self, fm, tmp_path):
        bad = tmp_path / "missing_dir" / "out.ini"    # parent directory doesn't exist
        ok, message = fm.save_file("content\n", str(bad))
        assert ok is False
        assert "Error" in message


class TestSaveAsFile:
    def test_with_an_explicit_path_writes_and_updates_current_file_path(self, fm, tmp_path):
        f = tmp_path / "saved_as.ini"
        ok, name, message = fm.save_as_file("content\n", str(f))
        assert ok is True
        assert name == "saved_as.ini"
        assert fm.current_file_path == str(f)
        assert f.read_text(encoding="utf-8") == "content\n"

    def test_a_write_failure_leaves_current_file_path_unset(self, fm, tmp_path):
        bad = tmp_path / "missing_dir" / "out.ini"
        ok, name, _message = fm.save_as_file("content\n", str(bad))
        assert ok is False
        assert name is None
        assert fm.current_file_path is None

    def test_no_path_given_asks_the_dialog_and_honours_a_cancel(self, fm, monkeypatch):
        monkeypatch.setattr(fm, "choose_save_path", lambda: "")
        ok, name, message = fm.save_as_file("content\n", file_path=None)
        assert ok is False
        assert name is None
        assert message == "Save cancelled"

    def test_no_path_given_uses_whatever_the_dialog_returns(self, fm, tmp_path, monkeypatch):
        f = tmp_path / "picked.ini"
        monkeypatch.setattr(fm, "choose_save_path", lambda: str(f))
        ok, name, _message = fm.save_as_file("content\n", file_path=None)
        assert ok is True
        assert name == "picked.ini"
        assert f.read_text(encoding="utf-8") == "content\n"


class TestFileStateGetters:
    def test_no_file_loaded_initially(self, fm):
        assert fm.get_current_file_path() is None
        assert fm.get_current_filename() is None
        assert fm.has_file_loaded() is False

    def test_reflect_the_loaded_file(self, fm, tmp_path):
        f = tmp_path / "loaded.ini"
        f.write_text("x", encoding="utf-8")
        fm.load_file_from_path(str(f))
        assert fm.get_current_file_path() == str(f)
        assert fm.get_current_filename() == "loaded.ini"
        assert fm.has_file_loaded() is True
