"""Save PNG (src/gui/utils/png_export.py) and its setting (display_format PNG dpi):
the pure parts - no page, no window."""

import base64

import pytest

from src.gui.utils import display_format, png_export


@pytest.fixture(autouse=True)
def _restore_dpi():
    before = display_format.get_png_dpi()
    yield
    display_format.set_png_dpi(before)


def test_default_is_150():
    assert display_format.PNG_DPI_DEFAULT == 150


def test_dpi_is_clamped_and_bad_input_ignored():
    display_format.set_png_dpi(300)
    assert display_format.get_png_dpi() == 300
    display_format.set_png_dpi(10)
    assert display_format.get_png_dpi() == display_format.PNG_DPI_MIN
    display_format.set_png_dpi(99999)
    assert display_format.get_png_dpi() == display_format.PNG_DPI_MAX
    display_format.set_png_dpi("abc")
    assert display_format.get_png_dpi() == display_format.PNG_DPI_MAX


def test_scale_is_dpi_over_screen_dpi():
    assert png_export.scale_for(96) == 1.0
    assert png_export.scale_for(150) == pytest.approx(1.5625)
    assert png_export.scale_for(300) == pytest.approx(3.125)


def test_export_js_carries_the_scale_and_the_size_limit():
    js = png_export.export_js(3.125)
    assert "(3.125)" in js and "Plotly.toImage" in js and "__cwatmPng" in js
    assert str(png_export._MAX_SIDE) in js


def test_decode_data_url():
    raw = b"\x89PNG\r\n\x1a\nabc"
    url = "data:image/png;base64," + base64.b64encode(raw).decode()
    assert png_export.decode_data_url(url) == raw
    with pytest.raises(ValueError):
        png_export.decode_data_url("data:image/jpeg;base64,AAAA")
    with pytest.raises(ValueError):
        png_export.decode_data_url(None)


@pytest.mark.qt
def test_saved_png_carries_the_dpi(tmp_path, qapp):
    from PySide6.QtGui import QImage
    img = QImage(20, 10, QImage.Format_RGB32)
    img.fill(0xFFFFFF)
    from PySide6.QtCore import QBuffer, QByteArray
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    path = str(tmp_path / "x.png")
    assert png_export.save_png_bytes(bytes(ba), path, 300) == ""
    back = QImage(path)
    assert (back.width(), back.height()) == (20, 10)
    assert round(back.dotsPerMeterX() * 0.0254) == 300
