"""Regression tests for the startup-speed fix (main window construction dropped
from ~6.2s to ~0.5s in the frozen build after this session's changes).

Two invariants, each the direct cause of the ~6s stall when it didn't hold:

1. Importing `basin_viewer.py` must not pull in `xarray`/`rasterio`/
   `cwatm.run_cwatm` - the module is imported the instant ANY settings file is
   loaded into a tab (the gauge-in-mask check), which happens during
   `CWatMMainWindow.__init__` for the construction-time empty first tab. Those
   three used to be imported at basin_viewer's own module top level; now they are
   imported inside the functions that actually need them. Checked in a subprocess
   so it is immune to another test file having already imported them (several
   other test files import basin_viewer-dependent modules at their own module
   level - see test_check_settingsfile.py / test_settings_check.py).
2. The construction-time gauge-in-mask check itself must not run synchronously
   inside `__init__` - `tab_manager.build_settings_tabs`'s first tab now passes
   `defer_warnings=True` through to `_activate_tab`, which schedules it via
   `QTimer.singleShot(0, ...)` instead.
"""

import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

pytestmark = pytest.mark.qt


class TestBasinViewerStaysImportLight:
    def test_importing_basin_viewer_does_not_import_heavy_deps(self):
        script = (
            "import sys\n"
            "import src.gui.widgets.basin_viewer\n"
            "heavy = [m for m in ('xarray', 'rasterio', 'cwatm.run_cwatm')\n"
            "         if m in sys.modules]\n"
            "assert not heavy, 'basin_viewer import pulled in: ' + ', '.join(heavy)\n"
            "print('OK')\n"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = ROOT
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        # Generous timeout: a cold Python + PySide6/basin_viewer import from a
        # slow/network drive can genuinely take a while - this is checking what
        # gets imported, not how fast.
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=180,
        )
        assert result.returncode == 0, result.stdout + result.stderr


class TestConstructionTimeMaskCheckIsDeferred:
    # Deliberately never call window.close()/deleteLater(): CWatMMainWindow's
    # closeEvent runs cleanup_file_operations(), which walks gc.get_objects() for
    # open file-like handles and closes them - under pytest that can catch
    # pytest's OWN stdout/stderr capture stream and take the whole session's
    # output capturing down with it. Nothing here needs the window closed; the
    # process ending at the end of the test run is cleanup enough (the same
    # choice tools/import_all.py makes).

    def test_mask_context_is_not_built_immediately_after_construction(
            self, qapp, isolated_qsettings, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from src.gui.components.main_window import CWatMMainWindow
        window = CWatMMainWindow()
        assert window._mask_context_built is False, (
            "the construction-time tab's gauge-in-mask check ran "
            "synchronously - this re-imports basin_viewer (and xarray/"
            "rasterio with it) inside __init__, undoing the startup-speed fix")

    def test_mask_context_is_built_once_the_event_loop_runs(
            self, qapp, isolated_qsettings, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from src.gui.components.main_window import CWatMMainWindow
        window = CWatMMainWindow()
        qapp.processEvents()
        qapp.processEvents()
        assert window._mask_context_built is True, (
            "the deferred check (QTimer.singleShot(0, ...) from "
            "_activate_tab) never ran even after the event loop processed "
            "events")
