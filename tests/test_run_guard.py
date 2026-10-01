"""The run guard against code hidden in a settings file or a NetCDF input
(src/gui/utils/run_guard.py, security.md #1). It must mirror what CWatM evaluates:
output entries go into eval("self.var." + entry), coordinate attributes of the
PrecipitationMaps file into exec('longitude.<name>="<value>"')."""

import pytest

from src.gui.utils import run_guard as G

INI = """[FILE_PATHS]
PathRoot = C:/data
[OPTIONS]
out_strange = whatever(1)
[OUTPUT]
OUT_Dir = $(FILE_PATHS:PathRoot)/out
OUT_MAP_Daily = discharge, actualET[1], rootDepth[0][1]
OUT_TSS_Daily = None
OUT_TSS_MonthTot = {tss}
"""


def _problems(tss):
    return G.output_problems(INI.format(tss=tss))


@pytest.mark.parametrize("tss", ["discharge", "WaterCycle", "", "None",
                                 "discharge, Precipitation"])
def test_plain_entries_pass(tss):
    assert _problems(tss) == []


@pytest.mark.parametrize("entry,reason", [
    ("discharge[__import__('os').system('calc')]", "index is not a plain number"),
    ("discharge[1+1]", "index is not a plain number"),
    ("__import__('os').system('calc')", "not a plain variable name"),
    ("discharge.__class__", "not a plain variable name"),
    ("$(FILE_PATHS:PathRoot)", "placeholder in an output name"),
    ("discharge  # comment", "not a plain variable name"),
])
def test_code_like_entries_are_found(entry, reason):
    (row, key, found, why), = _problems(entry)
    assert (key, found, why) == ("OUT_TSS_MonthTot", entry, reason)
    assert INI.format(tss=entry).split("\n")[row].startswith("OUT_TSS_MonthTot")


def test_options_section_and_dir_keys_are_not_output_entries():
    # CWatM reads [OPTIONS] as booleans and *_Dir as a folder - neither is eval'd
    assert _problems("discharge") == []


def test_a_continuation_line_is_part_of_the_value():
    # configparser joins indented lines - the guard must see what CWatM sees
    content = INI.format(tss="discharge,\n    evil[__import__('os')]")
    assert [p[2] for p in G.output_problems(content)] == ["evil[__import__('os')]"]


def _nc(tmp_path, attrs, var="lon"):
    netCDF4 = pytest.importorskip("netCDF4")
    path = str(tmp_path / "pr.nc")
    ds = netCDF4.Dataset(path, "w")
    ds.createDimension(var, 2)
    v = ds.createVariable(var, "f8", (var,))
    for k, val in attrs.items():
        v.setncattr(k, val)
    ds.close()
    return path


def test_clean_coordinates_pass(tmp_path):
    assert G.netcdf_problems(_nc(tmp_path, {"units": "degrees_east",
                                            "long_name": "longitude"})) == []


@pytest.mark.parametrize("attrs", [
    {"units": 'x";__import__("os").system("calc");"'},
    {"comment": "line one\nline two"},
    {"comment": "back\\slash"},
])
def test_breaking_out_of_the_exec_string_is_found(tmp_path, attrs):
    assert len(G.netcdf_problems(_nc(tmp_path, attrs))) == 1


def test_only_the_exec_d_variables_are_checked(tmp_path):
    # a quote in the precipitation variable's own comment is harmless
    assert G.netcdf_problems(_nc(tmp_path, {"comment": 'a "quoted" word'},
                                 var="pr")) == []


def test_the_metadata_file_is_found_like_cwatm(tmp_path):
    path = _nc(tmp_path, {"units": "x"})
    content = "[METEO]\nPrecipitationMaps = pr.nc\n"
    assert G.forcing_metadata_file(content, str(tmp_path)) == path
    content = f"[FILE_PATHS]\nPathMeteo = {tmp_path}\n[METEO]\n" \
              "PrecipitationMaps = $(FILE_PATHS:PathMeteo)/p*.nc\n"
    assert G.forcing_metadata_file(content, "") is not None


def test_check_combines_both(tmp_path):
    _nc(tmp_path, {"units": 'a"b'})
    content = ("[METEO]\nPrecipitationMaps = pr.nc\n[OUTPUT]\n"
               "OUT_MAP_Daily = discharge[x]\n")
    blocking, warnings, nc = G.check(content, str(tmp_path))
    assert len(blocking) == 1 and "line 4" in blocking[0]
    assert len(warnings) == 1 and nc.endswith("pr.nc")


def test_check_settingsfile_marks_the_same_lines():
    from tests.test_settings_check import Host      # the bare host of that suite
    probs = Host()._semantic_settings_problems(
        INI.format(tss="discharge[__import__('os')]"))
    assert any("runs output names as Python code" in m for _r, m in probs)
