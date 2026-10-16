"""MSIX (Microsoft Store) package detection - `src/gui/utils/msix.py`.

`package_full_name` takes a stand-in for kernel32's GetCurrentPackageFullName, so
both answers (packaged / not packaged) are tested on any OS. No Qt needed.
"""

import ctypes

import pytest

from src.gui.utils import msix


def fake_api(name=None, first_rc=None):
    """A GetCurrentPackageFullName double: `name` = the package's full name, None
    = not packaged. It writes the needed length (incl. the terminating NUL) through
    the pointer and fills the buffer on the second call, as the real API does."""
    calls = []

    def api(length_ref, buf):
        calls.append(buf)
        if name is None:
            return msix._APPMODEL_ERROR_NO_PACKAGE
        length = length_ref._obj                # the c_uint32 behind byref()
        if buf is None or length.value < len(name) + 1:
            length.value = len(name) + 1
            return msix._ERROR_INSUFFICIENT_BUFFER if first_rc is None else first_rc
        buf.value = name
        return msix._ERROR_SUCCESS

    api.calls = calls
    return api


FULL_NAME = "IIASA.CWatMGUI_1.11.0.0_x64__8wekyb3d8bbwe"


class TestPackageFullName:
    def test_not_packaged(self):
        api = fake_api(None)
        assert msix.package_full_name(api) is None
        assert len(api.calls) == 1               # no second call without a package

    def test_packaged_returns_the_full_name(self):
        api = fake_api(FULL_NAME)
        assert msix.package_full_name(api) == FULL_NAME
        assert api.calls[0] is None              # first call only asks for the length
        assert isinstance(api.calls[1], ctypes.Array)

    def test_unexpected_answer_counts_as_not_packaged(self):
        # e.g. ERROR_INVALID_PARAMETER (87) - never claim a package we cannot name
        assert msix.package_full_name(fake_api(FULL_NAME, first_rc=87)) is None

    def test_this_test_process_is_not_packaged(self):
        # The real API (or its absence off Windows): pytest never runs packaged.
        assert msix.package_full_name() is None


class TestIsPackaged:
    def test_cached_answer(self, monkeypatch):
        monkeypatch.setattr(msix, "_packaged", None)
        seen = []
        monkeypatch.setattr(msix, "package_full_name", lambda: seen.append(1) or FULL_NAME)
        assert msix.is_packaged() is True
        assert msix.is_packaged() is True
        assert seen == [1]

    def test_failure_means_not_packaged(self, monkeypatch):
        monkeypatch.setattr(msix, "_packaged", None)

        def broken():
            raise OSError("no package API")

        monkeypatch.setattr(msix, "package_full_name", broken)
        assert msix.is_packaged() is False

    @pytest.mark.parametrize("name, expected", [(None, False), (FULL_NAME, True)])
    def test_follows_package_full_name(self, monkeypatch, name, expected):
        monkeypatch.setattr(msix, "_packaged", None)
        monkeypatch.setattr(msix, "package_full_name", lambda: name)
        assert msix.is_packaged() is expected


def test_model_alias_matches_the_manifest():
    # The alias Create batch writes must be the one the package declares.
    import os
    import xml.etree.ElementTree as ET
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    manifest = os.path.join(root, "installer", "msix", "AppxManifest.xml")
    ns = {"desktop": "http://schemas.microsoft.com/appx/manifest/desktop/windows10",
          "f": "http://schemas.microsoft.com/appx/manifest/foundation/windows10",
          "uap3": "http://schemas.microsoft.com/appx/manifest/uap/windows10/3"}
    tree = ET.parse(manifest)
    model_apps = [a for a in tree.getroot().iterfind("f:Applications/f:Application", ns)
                  if a.get("Executable") == r"_internal\CWatM_model.exe"]
    assert len(model_apps) == 1
    aliases = [e.get("Alias") for e in model_apps[0].iter(
        "{%s}ExecutionAlias" % ns["desktop"])]
    assert aliases == [msix.MODEL_ALIAS]
