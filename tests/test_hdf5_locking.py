"""HDF5 file locking fix for network-mounted filesystems (`src/gui/utils/hdf5_locking.py`)."""

from src.gui.utils import hdf5_locking


def test_apply_sets_the_variable_in_this_process(monkeypatch):
    monkeypatch.delenv(hdf5_locking.HDF5_LOCKING_VAR, raising=False)
    hdf5_locking.apply(export_env=False)
    import os
    assert os.environ[hdf5_locking.HDF5_LOCKING_VAR] == "FALSE"


def test_apply_does_not_override_a_value_the_user_already_set(monkeypatch):
    monkeypatch.setenv(hdf5_locking.HDF5_LOCKING_VAR, "TRUE")
    hdf5_locking.apply(export_env=False)
    import os
    assert os.environ[hdf5_locking.HDF5_LOCKING_VAR] == "TRUE"


def test_export_to_environment_sets_it_on_a_plain_dict_without_touching_the_real_one(monkeypatch):
    monkeypatch.delenv(hdf5_locking.HDF5_LOCKING_VAR, raising=False)
    env = {}
    value = hdf5_locking.export_to_environment(env)
    assert value == "FALSE"
    assert env[hdf5_locking.HDF5_LOCKING_VAR] == "FALSE"
    import os
    assert hdf5_locking.HDF5_LOCKING_VAR not in os.environ


def test_export_to_environment_keeps_an_existing_value_in_the_given_dict():
    env = {hdf5_locking.HDF5_LOCKING_VAR: "TRUE"}
    value = hdf5_locking.export_to_environment(env)
    assert value == "TRUE"
    assert env[hdf5_locking.HDF5_LOCKING_VAR] == "TRUE"
