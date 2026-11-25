"""Analyse ▸ NetCDF: the unit / long name of the shown variable (colour bar, point
Timeseries y-axis). The file's own ``units`` / ``long_name`` come first and
metaNetcdf.xml fills in what the file does not say - a variable metaNetcdf does not
list under that exact name (``discharge_monthavg``) used to lose its unit."""

import pytest

pytestmark = pytest.mark.qt

from src.gui.widgets.analysis_netcdf_base import NetcdfDataBase  # noqa: E402


def _bare(source=None):
    w = NetcdfDataBase.__new__(NetcdfDataBase)     # no __init__: no file, no window
    w._point_source = source
    return w


def test_file_units_used_for_a_name_metanetcdf_does_not_know():
    w = _bare(dict(varname="discharge_monthavg", units="m3 s-1",
                   long_name="Channel discharge: monthly average"))
    unit, long_name, _desc = w._var_meta("discharge_monthavg")
    assert unit == "m3 s-1"
    assert long_name == "Channel discharge: monthly average"


def test_metanetcdf_fills_in_when_the_file_has_no_units():
    w = _bare(dict(varname="discharge", units="", long_name=""))
    unit, long_name, _desc = w._var_meta("discharge")
    assert unit == "m3 s-1"                       # from cwatm/metaNetcdf.xml
    assert long_name == "Channel discharge"


def test_attributes_of_another_variable_are_not_borrowed():
    w = _bare(dict(varname="other", units="mm", long_name="Something else"))
    unit, _long, _desc = w._var_meta("discharge")
    assert unit == "m3 s-1"


def test_unknown_everywhere_gives_empty_strings():
    w = _bare(None)
    assert w._var_meta("no_such_variable_xyz") == ("", "", "")
