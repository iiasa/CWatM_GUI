"""Batch Run window: the Preferences widgets stay hidden, and Run all/Stop all
button<->action state stays in sync (`src/gui/widgets/batch_runner_window.py`).

Two regressions from this session's menu conversion, both real bugs caught only
after the fact:
1. `parallel_spin`/`stop_on_fail`/`skip_finished` are kept as real widgets (shared
   state with the Preferences dialog) but were meant to never be shown inline - a
   parented-but-unlayouted Qt widget still becomes visible once its window is
   shown, so they floated at the window's top-left corner until `setVisible(False)`
   was added explicitly.
2. Run all/Stop all exist as BOTH a menu action and a button (unlike every other
   converted window, which dropped the buttons) - the two must never show a
   different enabled state.
"""

import pytest

from src.gui.widgets.batch_runner_window import BatchRunnerWindow

# Needs Qt: constructs a real (offscreen) QDialog.
pytestmark = pytest.mark.qt

_BASE_CONTENT = (
    "[FILE_PATHS]\nPathRoot = .\n\n"
    "[TIME-RELATED_CONSTANTS]\nStepStart = 01/01/2000\nStepEnd = 02/01/2000\n\n"
    "[OUTPUT]\nOUT_TSS_Daily = discharge\n"
)


@pytest.fixture
def batch_window(qapp, isolated_qsettings, tmp_path):
    base_path = str(tmp_path / "settings.ini")
    win = BatchRunnerWindow(base_path, _BASE_CONTENT, None)
    win.show()
    yield win
    win.close()


class TestPreferenceWidgetsStayHidden:
    def test_hidden_before_show(self, qapp, isolated_qsettings, tmp_path):
        base_path = str(tmp_path / "settings.ini")
        win = BatchRunnerWindow(base_path, _BASE_CONTENT, None)
        try:
            assert win.parallel_spin.isVisible() is False
            assert win.stop_on_fail.isVisible() is False
            assert win.skip_finished.isVisible() is False
        finally:
            win.close()

    def test_still_hidden_after_show(self, batch_window):
        # This is the actual regression: a child widget with a parent but no
        # layout inherits its ancestor's shown state once THAT is shown, unless
        # explicitly hidden.
        assert batch_window.parallel_spin.isVisible() is False
        assert batch_window.stop_on_fail.isVisible() is False
        assert batch_window.skip_finished.isVisible() is False

    def test_preferences_values_are_still_readable(self, batch_window):
        # Hidden, but not gone - every other method still reads these directly.
        assert batch_window.parallel_spin.value() >= 1
        assert batch_window.stop_on_fail.isChecked() in (True, False)
        assert batch_window.skip_finished.isChecked() in (True, False)


class TestRunStopButtonActionSync:
    def test_initial_state(self, batch_window):
        assert batch_window.run_button.isEnabled() is True
        assert batch_window.stop_button.isEnabled() is False
        assert batch_window.run_action.isEnabled() is True
        assert batch_window.stop_action.isEnabled() is False

    def test_starting_a_run_flips_both_button_and_action(self, batch_window, monkeypatch):
        # _pump() is where a real run would spawn a subprocess per queued row -
        # stub it out so this stays a pure state-machine test. The state flip
        # under test happens in _run_rows() BEFORE _pump() is ever called.
        monkeypatch.setattr(batch_window, "_pump", lambda: None)
        batch_window._run_rows([0])
        assert batch_window.run_button.isEnabled() is False
        assert batch_window.stop_button.isEnabled() is True
        assert batch_window.run_action.isEnabled() is False
        assert batch_window.stop_action.isEnabled() is True

    def test_stopping_flips_both_button_and_action_back(self, batch_window, monkeypatch):
        monkeypatch.setattr(batch_window, "_pump", lambda: None)
        batch_window._run_rows([0])
        batch_window._stop_all()
        assert batch_window.run_button.isEnabled() is True
        assert batch_window.stop_button.isEnabled() is False
        assert batch_window.run_action.isEnabled() is True
        assert batch_window.stop_action.isEnabled() is False

    def test_button_and_action_enabled_state_never_diverges(self, batch_window, monkeypatch):
        monkeypatch.setattr(batch_window, "_pump", lambda: None)
        assert (batch_window.run_button.isEnabled()
                == batch_window.run_action.isEnabled())
        assert (batch_window.stop_button.isEnabled()
                == batch_window.stop_action.isEnabled())
        batch_window._run_rows([0])
        assert (batch_window.run_button.isEnabled()
                == batch_window.run_action.isEnabled())
        assert (batch_window.stop_button.isEnabled()
                == batch_window.stop_action.isEnabled())
        batch_window._stop_all()
        assert (batch_window.run_button.isEnabled()
                == batch_window.run_action.isEnabled())
        assert (batch_window.stop_button.isEnabled()
                == batch_window.stop_action.isEnabled())
