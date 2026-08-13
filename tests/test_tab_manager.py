"""The Copy Tab naming rule (`src/gui/components/tab_manager.py: next_copy_path`).

`settings.ini` -> `settings_2.ini` -> `settings_3.ini`, never overwriting an existing
file. Copying a tab is how a user forks a scenario, so silently landing on a name that
already exists would destroy the earlier copy.
"""

import os

import pytest

from src.gui.components.tab_manager import next_copy_path

# Needs Qt: tab_manager imports PySide6.QtWidgets at module level.
# The dependency-free CI job selects with `pytest -m "not qt"`.
pytestmark = pytest.mark.qt


def name(path):
    return os.path.basename(path)


class TestNaming:
    def test_first_copy_gets_suffix_2(self, tmp_path):
        src = tmp_path / "settings.ini"
        src.write_text("x")
        assert name(next_copy_path(str(src))) == "settings_2.ini"

    def test_a_numbered_file_increments(self, tmp_path):
        src = tmp_path / "settings_2.ini"
        src.write_text("x")
        assert name(next_copy_path(str(src))) == "settings_3.ini"

    def test_existing_names_are_skipped(self, tmp_path):
        (tmp_path / "settings.ini").write_text("x")
        (tmp_path / "settings_2.ini").write_text("x")
        (tmp_path / "settings_3.ini").write_text("x")
        got = name(next_copy_path(str(tmp_path / "settings.ini")))
        assert got == "settings_4.ini"

    def test_the_result_never_exists(self, tmp_path):
        for i in range(2, 8):
            (tmp_path / f"settings_{i}.ini").write_text("x")
        (tmp_path / "settings.ini").write_text("x")
        assert not os.path.exists(next_copy_path(str(tmp_path / "settings.ini")))

    def test_copying_twice_gives_two_different_names(self, tmp_path):
        src = tmp_path / "settings.ini"
        src.write_text("x")
        first = next_copy_path(str(src))
        open(first, "w").write("x")           # the caller writes it
        second = next_copy_path(str(src))
        assert first != second
        assert name(second) == "settings_3.ini"


class TestEdges:
    def test_extension_is_preserved(self, tmp_path):
        src = tmp_path / "run.txt"
        src.write_text("x")
        assert name(next_copy_path(str(src))) == "run_2.txt"

    def test_no_extension(self, tmp_path):
        src = tmp_path / "settings"
        src.write_text("x")
        assert name(next_copy_path(str(src))) == "settings_2"

    def test_dots_in_the_stem(self, tmp_path):
        src = tmp_path / "morava.1min.ini"
        src.write_text("x")
        assert name(next_copy_path(str(src))) == "morava.1min_2.ini"

    def test_underscore_that_is_not_a_counter(self, tmp_path):
        src = tmp_path / "settings_morava.ini"
        src.write_text("x")
        assert name(next_copy_path(str(src))) == "settings_morava_2.ini"

    def test_result_stays_in_the_same_folder(self, tmp_path):
        src = tmp_path / "sub"
        src.mkdir()
        f = src / "settings.ini"
        f.write_text("x")
        assert os.path.dirname(next_copy_path(str(f))) == str(src)

    def test_returns_an_absolute_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "settings.ini").write_text("x")
        assert os.path.isabs(next_copy_path("settings.ini"))
