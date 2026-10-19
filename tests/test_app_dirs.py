"""app_dirs.user_data_base: Windows env var wins, macOS gets Application Support."""
import os
import sys
import tempfile

from src.gui.utils import app_dirs


def test_localappdata_wins(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", "X")
    monkeypatch.setattr(sys, "platform", "darwin")
    assert app_dirs.user_data_base() == "X"


def test_macos_application_support(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert app_dirs.user_data_base().endswith(
        os.path.join("Library", "Application Support"))


def test_linux_keeps_temp(monkeypatch):
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    assert app_dirs.user_data_base() == tempfile.gettempdir()
