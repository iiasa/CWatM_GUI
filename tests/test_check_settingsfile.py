"""The Check settingsfile (F4) file-existence pass (`check_settingsfile` itself, as
opposed to `_semantic_settings_problems` which `tests/test_settings_check.py` covers).

Exercises placeholder resolution, the strict `path*`-key rule, the lenient NetCDF
fallback, wrong-extension detection, and the section/key/value gating tables - the
logic that decides whether a missing file is flagged red, dimmed orange, or ignored.

`check_settingsfile` is a mixin method that only touches `self.text_area`,
`self.status_bar`, `self.append_to_cwatminfo` and `self.working_dir()`; a small fake
host stands in for the real `CWatMMainWindow` so the pass can run with no Qt widgets
and real files under `tmp_path`.
"""

import pytest

from src.gui.components.settings_check import SettingsCheckMixin

# check_settingsfile imports src.gui.widgets.basin_viewer (rasterio/xarray) and QDate.
pytestmark = pytest.mark.qt


class FakeTextArea:
    def __init__(self, content):
        self._content = content
        self.error_rows = None
        self.inactive_rows = None
        self.wrongext_rows = None
        self.bookmarked = None
        self.cleared = False

    def toPlainText(self):
        return self._content

    def clear_checking(self):
        self.cleared = True
        self.error_rows = None
        self.inactive_rows = None
        self.wrongext_rows = None

    def set_error_rows(self, rows):
        self.error_rows = list(rows)

    def set_inactive_rows(self, rows):
        self.inactive_rows = list(rows)

    def set_wrongext_rows(self, rows):
        self.wrongext_rows = list(rows)

    def bookmark_rows(self, rows):
        self.bookmarked = list(rows)


class FakeStatusBar:
    def __init__(self):
        self.message = None

    def showMessage(self, msg):
        self.message = msg


class Host(SettingsCheckMixin):
    """Minimal carrier for the mixin - just enough for check_settingsfile to run."""

    def __init__(self, content, base_dir=""):
        self.text_area = FakeTextArea(content)
        self.status_bar = FakeStatusBar()
        self._base_dir = base_dir
        self._write_output_enabled = False
        self.output_lines = []

    def working_dir(self):
        return self._base_dir

    def append_to_cwatminfo(self, text, is_error=False):
        self.output_lines.append((text, is_error))


def run_check(tmp_path, content):
    host = Host(content, base_dir=str(tmp_path))
    host.check_settingsfile()
    return host


class TestPlainFileExistence:
    def test_existing_file_is_not_flagged(self, tmp_path):
        (tmp_path / "mask.nc").write_text("x")
        host = run_check(tmp_path, "MaskMap = mask.nc\n")
        assert host.text_area.error_rows == []

    def test_missing_file_is_flagged_and_bookmarked(self, tmp_path):
        host = run_check(tmp_path, "MaskMap = nope.nc\n")
        assert host.text_area.error_rows == [0]
        assert host.text_area.bookmarked == [0]

    def test_non_path_values_are_never_checked(self, tmp_path):
        host = run_check(tmp_path, "StepStart = 1/1/2000\nSomeNumber = 42\n")
        assert host.text_area.error_rows == []

    def test_rerun_clears_previous_marks_first(self, tmp_path):
        host = Host("MaskMap = nope.nc\n", base_dir=str(tmp_path))
        host.check_settingsfile()
        assert host.text_area.error_rows == [0]
        host.check_settingsfile()
        assert host.text_area.cleared is True
        assert host.text_area.error_rows == [0]   # still missing, re-flagged


class TestPathKeysAreStrict:
    """Keys whose first 4 letters are 'path' are directory paths: plain
    os.path.exists only, no NetCDF-without-extension / date-suffix fallback."""

    def test_existing_directory_is_not_flagged(self, tmp_path):
        (tmp_path / "out").mkdir()
        host = run_check(tmp_path, "PathOut = out\n")
        assert host.text_area.error_rows == []

    def test_missing_directory_is_flagged(self, tmp_path):
        host = run_check(tmp_path, "PathOut = nowhere\n")
        assert host.text_area.error_rows == [0]

    def test_no_lenient_fallback_for_a_path_key(self, tmp_path):
        # A non-path key gets a NetCDF-without-extension fallback (see below); a
        # path* key must not, even though the same glob would find something.
        (tmp_path / "PathRoot.nc").write_text("x")
        host = run_check(tmp_path, "PathRoot = PathRoot\n")
        assert host.text_area.error_rows == [0]


class TestLenientDataFileFallback:
    def test_netcdf_stored_without_extension_is_found(self, tmp_path):
        (tmp_path / "precip.nc").write_text("x")
        value = str(tmp_path / "precip")   # absolute, no extension -> still a path
        host = run_check(tmp_path, f"PrecipitationMaps = {value}\n")
        assert host.text_area.error_rows == []

    def test_wrong_extension_is_dimmed_orange_not_flagged(self, tmp_path):
        (tmp_path / "field.nc").write_text("x")
        host = run_check(tmp_path, "SomeMap = field.map\n")
        assert host.text_area.error_rows == []
        assert host.text_area.wrongext_rows == [0]

    def test_wrong_extension_never_applies_to_a_path_key(self, tmp_path):
        # wrong_extension_alt is only tried for non-path keys.
        (tmp_path / "PathOut.nc").write_text("x")
        host = run_check(tmp_path, "PathOut = PathOut.map\n")
        assert host.text_area.error_rows == [0]
        assert host.text_area.wrongext_rows == []


class TestPlaceholderResolution:
    def test_resolved_placeholder_finds_the_file(self, tmp_path):
        (tmp_path / "mask.nc").write_text("x")
        content = (f"[FILE_PATHS]\nPathRoot = {tmp_path}\n\n"
                   f"[MASK_OUTLET]\nMaskMap = $(PathRoot)/mask.nc\n")
        host = run_check(tmp_path, content)
        assert host.text_area.error_rows == []

    def test_unresolved_placeholder_is_flagged_as_its_own_problem(self, tmp_path):
        content = "[MASK_OUTLET]\nMaskMap = $(PathRott)/mask.nc\n"
        host = run_check(tmp_path, content)
        assert host.text_area.error_rows == [1]
        assert any("unresolved placeholder" in msg for msg, _err in host.output_lines)


class TestSectionGating:
    def test_missing_file_in_a_disabled_section_is_dimmed(self, tmp_path):
        content = ("[OPTIONS]\nincludeGlaciers = False\n\n"
                   "[GLACIER]\nglacierArea = missing.nc\n")
        host = run_check(tmp_path, content)
        assert host.text_area.error_rows == []
        assert host.text_area.inactive_rows == [4]

    def test_missing_file_in_an_enabled_section_is_flagged(self, tmp_path):
        content = ("[OPTIONS]\nincludeGlaciers = True\n\n"
                   "[GLACIER]\nglacierArea = missing.nc\n")
        host = run_check(tmp_path, content)
        # The missing file itself; row 1 (the option line) is added too by the
        # roll-up - see test_enabled_section_with_a_problem_rolls_up_to_the_option_line.
        assert 4 in host.text_area.error_rows
        assert host.text_area.inactive_rows == []

    def test_enabled_section_with_a_problem_rolls_up_to_the_option_line(self, tmp_path):
        content = ("[OPTIONS]\nincludeGlaciers = True\n\n"
                   "[GLACIER]\nglacierArea = missing.nc\n")
        host = run_check(tmp_path, content)
        assert 1 in host.text_area.error_rows      # includeGlaciers = True, own line
        assert 4 in host.text_area.error_rows       # the missing file itself

    def test_missing_switch_is_treated_as_active_not_disabled(self, tmp_path):
        # No includeGlaciers key at all - conservative default is "active".
        content = "[GLACIER]\nglacierArea = missing.nc\n"
        host = run_check(tmp_path, content)
        assert host.text_area.error_rows == [1]
        assert host.text_area.inactive_rows == []


class TestKeyGating:
    def test_key_gated_off_dims_the_missing_file(self, tmp_path):
        content = "[EVAPORATION]\nalbedo = False\nalbedoMaps = missing.nc\n"
        host = run_check(tmp_path, content)
        assert host.text_area.error_rows == []
        assert host.text_area.inactive_rows == [2]

    def test_key_gated_on_flags_the_missing_file(self, tmp_path):
        content = "[EVAPORATION]\nalbedo = True\nalbedoMaps = missing.nc\n"
        host = run_check(tmp_path, content)
        assert host.text_area.error_rows == [2]
        assert host.text_area.inactive_rows == []

    def test_prefix_key_gate_covers_every_matching_key(self, tmp_path):
        content = ("[METEO]\nusemeteodownscaling = False\n"
                   "downscale_wordclim_prec = missing.nc\n"
                   "downscale_wordclim_tavg = missing2.nc\n")
        host = run_check(tmp_path, content)
        assert host.text_area.error_rows == []
        assert host.text_area.inactive_rows == [2, 3]


class TestValueGating:
    def test_negative_gate_value_leaves_the_key_active(self, tmp_path):
        content = "[WATERDEMAND]\nswAbstractionFrac = -1\naverageDischarge = missing.nc\n"
        host = run_check(tmp_path, content)
        assert host.text_area.error_rows == [2]

    def test_nonnegative_gate_value_dims_the_missing_file(self, tmp_path):
        content = "[WATERDEMAND]\nswAbstractionFrac = 0.8\naverageDischarge = missing.nc\n"
        host = run_check(tmp_path, content)
        assert host.text_area.error_rows == []
        assert host.text_area.inactive_rows == [2]


class TestModflowInputIsSoft:
    def test_missing_modflow_input_dir_is_dimmed_not_flagged(self, tmp_path):
        content = "[GROUNDWATER_MODFLOW]\nPathGroundwaterModflow = missing_dir\n"
        host = run_check(tmp_path, content)
        assert host.text_area.error_rows == []
        assert host.text_area.inactive_rows == [1]

    def test_missing_solver_dll_is_still_flagged(self, tmp_path):
        # Only the *input directory* is soft; a path routed through the placeholder
        # (not the PathGroundwaterModflow key itself) is soft too, but an unrelated
        # missing path key in the same section is not.
        content = "[GROUNDWATER_MODFLOW]\nPathOut = missing_out\n"
        host = run_check(tmp_path, content)
        assert host.text_area.error_rows == [1]
        assert host.text_area.inactive_rows == []
