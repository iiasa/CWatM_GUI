"""The map windows run only shipped, hash-pinned JavaScript; caches are per user; the
Chromium sandbox is off only where it cannot work (security.md, finding 2)."""

import hashlib
import os
import re

import pytest

from src.gui.utils import web_assets as W


def test_every_pinned_file_is_shipped_and_matches_its_hash():
    from src.gui.utils.assets import asset_path
    for url, (name, sha) in W.PINNED.items():
        with open(asset_path(os.path.join("web", name)), "rb") as f:
            assert hashlib.sha256(f.read()).hexdigest() == sha, url


def test_leaflet_matches_the_integrity_leaflet_publishes():
    # leafletjs.com download page, 1.9.3 (independent of the CDN we copied from)
    import base64
    published = {"leaflet.js": "WBkoXOwTeyKclOHuWtc+i2uENFpDZ9YPdf5Hf+D7ewM=",
                 "leaflet.css": "kLaT2GOSpHechhsozzB+flnD+zUyjE2LlfWPgU04xyI="}
    for name, b64 in published.items():
        url = "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/" + name
        assert base64.b64encode(bytes.fromhex(W.PINNED[url][1])).decode() == b64


@pytest.mark.qt          # imports a Qt module
def test_everything_folium_loads_is_pinned():
    # a folium upgrade with new URLs must fail here, not as a blank map
    folium = pytest.importorskip("folium")
    from src.gui.widgets.basin_viewer2 import _strip_unused_assets
    html = _strip_unused_assets(folium.Map().get_root().render())
    urls = set(re.findall(r'(?:src|href)=["\'](https?://[^"\']+\.(?:js|css))', html))
    assert urls and urls <= set(W.PINNED), urls - set(W.PINNED)


def test_pinned_bytes_refuses_anything_else():
    with pytest.raises(W.UnpinnedAsset):
        W.pinned_bytes("https://evil.example.org/x.js")


@pytest.mark.qt          # imports a Qt module
def test_an_unpinned_script_is_removed_never_fetched(monkeypatch):
    from src.gui.widgets import basin_viewer2 as B
    html = ('<script src="https://evil.example.org/x.js"></script>'
            '<script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js">'
            '</script>')
    out = B._inline_remote_assets(html)
    assert "evil.example.org" not in out
    assert "removed unpinned script" in out
    assert "Leaflet" in out                       # the pinned one is inlined


@pytest.mark.qt          # imports a Qt module
def test_leaflet_css_images_are_inlined_from_pinned_files():
    from src.gui.widgets import basin_viewer2 as B
    html = ('<link rel="stylesheet" '
            'href="https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css"/>')
    out = B._inline_remote_assets(html)
    assert "<style>" in out and "url(images/" not in out
    assert "data:image/png;base64," in out


def test_user_cache_dir_is_per_user(monkeypatch, tmp_path):
    monkeypatch.setattr(W.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    d = W.user_cache_dir("tiles")
    assert d == os.path.join(str(tmp_path), "CWatM_GUI", "cache", "tiles")
    assert os.path.isdir(d)


@pytest.mark.parametrize("platform,path,drive_type,env,off", [
    ("win32", r"C:\Users\x\AppData\Local\Programs\CWatM_GUI\_internal", 3, {}, False),
    ("win32", r"P:\watmodel\gui\venv\Lib\site-packages\PySide6", 4, {}, True),
    ("win32", r"\\pdrive\share\CWatM_GUI\_internal", None, {}, True),
    ("linux", "/home/x/venv/lib/PySide6", None, {}, True),
    ("win32", r"P:\x", 4, {"CWATM_GUI_WEBENGINE_SANDBOX": "1"}, False),   # forced on
    ("win32", r"C:\x", 3, {"CWATM_GUI_WEBENGINE_SANDBOX": "0"}, True),    # forced off
])
def test_sandbox_off_only_where_it_cannot_work(platform, path, drive_type, env, off):
    assert W.sandbox_must_be_off(platform=platform, process_dir=path, env=env,
                                 drive_type=drive_type) is off
