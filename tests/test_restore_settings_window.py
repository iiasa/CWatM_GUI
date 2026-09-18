"""RestoreSettingsWindow's Action-menu enable/tooltip state (`_update_actions`,
`src/gui/widgets/restore_settings_window.py`).

This window's whole button row was converted to File/Action/Restore menus this
session; the dynamic "grey this action out, with the reason in the tooltip" logic
that used to live on the buttons was carried over by hand (`_update_buttons` ->
`_update_actions`) and was only checked once, manually, at the time. Pins that
behaviour down: preview/compare/restore depend on `version_settingsfile`,
Show Inputfiles depends on `version_inputfiles`, independently.
"""

import pytest

from src.gui.widgets.restore_settings_window import RestoreSettingsWindow

# Needs Qt: constructs a real (offscreen) QDialog.
pytestmark = pytest.mark.qt


def _make_window(qapp, **attrs):
    metadata = list(attrs.items())
    win = RestoreSettingsWindow("C:/fake/dis_daily.nc", metadata, None)
    return win


class TestNoStoredSettings:
    def test_settings_actions_are_disabled(self, qapp):
        win = _make_window(qapp)
        try:
            assert win.preview_action.isEnabled() is False
            assert win.compare_action.isEnabled() is False
            assert win.restore_action.isEnabled() is False
        finally:
            win.close()

    def test_tooltip_explains_why(self, qapp):
        win = _make_window(qapp)
        try:
            assert "version_settingsfile" in win.preview_action.toolTip()
        finally:
            win.close()

    def test_inputfiles_action_is_independently_disabled(self, qapp):
        win = _make_window(qapp)
        try:
            assert win.inputfiles_action.isEnabled() is False
            assert "version_inputfiles" in win.inputfiles_action.toolTip()
        finally:
            win.close()


class TestWithStoredSettings:
    def test_settings_actions_are_enabled(self, qapp):
        win = _make_window(qapp, version_settingsfile="[FILE_PATHS]\nPathRoot = .\n")
        try:
            assert win.preview_action.isEnabled() is True
            assert win.compare_action.isEnabled() is True
            assert win.restore_action.isEnabled() is True
        finally:
            win.close()

    def test_tooltip_no_longer_mentions_the_missing_attribute(self, qapp):
        win = _make_window(qapp, version_settingsfile="[FILE_PATHS]\nPathRoot = .\n")
        try:
            assert "no stored settings file" not in win.preview_action.toolTip()
        finally:
            win.close()

    def test_inputfiles_action_stays_disabled_without_its_own_attribute(self, qapp):
        win = _make_window(qapp, version_settingsfile="[FILE_PATHS]\nPathRoot = .\n")
        try:
            assert win.inputfiles_action.isEnabled() is False
        finally:
            win.close()


class TestWithStoredInputfiles:
    def test_inputfiles_action_is_enabled(self, qapp):
        win = _make_window(qapp, version_inputfiles="dem.nc 01/01/2020 00:00")
        try:
            assert win.inputfiles_action.isEnabled() is True
        finally:
            win.close()

    def test_settings_actions_are_unaffected(self, qapp):
        win = _make_window(qapp, version_inputfiles="dem.nc 01/01/2020 00:00")
        try:
            assert win.preview_action.isEnabled() is False
        finally:
            win.close()


class TestNoJournalLeftovers:
    def test_show_in_journal_was_removed_not_moved(self, qapp):
        """Show in Journal (button + _on_show_in_journal/_journal_entry) was
        deleted outright per the menu conversion, not carried into a menu item -
        guard against it quietly reappearing."""
        win = _make_window(qapp)
        try:
            assert not hasattr(win, "journal_button")
            assert not hasattr(win, "journal_action")
            assert not hasattr(win, "_on_show_in_journal")
            assert not hasattr(win, "_journal_entry")
        finally:
            win.close()

    def test_no_buttons_are_left_on_the_window(self, qapp):
        win = _make_window(qapp)
        try:
            for name in ("preview_button", "compare_button", "restore_button",
                        "inputfiles_button", "export_button", "close_button"):
                assert not hasattr(win, name), f"{name} should have been removed"
        finally:
            win.close()
