"""CWatM Academy's Torus guide bubble (`src/gui/widgets/academy_guide.py`):
opening *below* a target (tail on top, for a menu-bar title), stepping aside while
a menu or modal dialog is open, and finding a menu by object name, never by its
translated title (`academy_window._menu_point`)."""

import types

import pytest

pytestmark = pytest.mark.qt

# A 1920x1080 screen whose available area starts at (0, 0); QRect convention:
# right/bottom are the last pixel.
SCREEN = dict(left=0, top=0, right=1919, bottom=1039)
W, H = 380, 220


class TestBelowPlacement:
    def test_centred_under_the_target_with_the_tail_on_it(self):
        from src.gui.widgets.academy_guide import below_placement
        x, y, tail_x = below_placement(620, 300, W, H, **SCREEN)
        assert (x, y) == (620 - W // 2, 300)        # tip exactly on the point
        assert x + tail_x == 620                     # tail at the target's x

    def test_left_screen_edge_clamps_the_card_not_the_tail(self):
        from src.gui.widgets.academy_guide import below_placement, _TAIL_EDGE_MIN
        x, _y, tail_x = below_placement(120, 300, W, H, **SCREEN)
        assert x == 0
        assert x + tail_x == 120                     # still pointing at it
        assert tail_x >= _TAIL_EDGE_MIN

    def test_right_screen_edge(self):
        from src.gui.widgets.academy_guide import below_placement
        x, _y, tail_x = below_placement(1850, 300, W, H, **SCREEN)
        assert x + W <= SCREEN["right"] + 1          # inside the screen
        assert x + tail_x == 1850

    def test_tail_keeps_off_the_rounded_corners(self):
        # A target at the very screen edge: the tail stops short of the corner.
        from src.gui.widgets.academy_guide import below_placement, _TAIL_EDGE_MIN
        _x, _y, tail_x = below_placement(0, 300, W, H, **SCREEN)
        assert tail_x == _TAIL_EDGE_MIN
        _x, _y, tail_x = below_placement(1919, 300, W, H, **SCREEN)
        assert tail_x == W - _TAIL_EDGE_MIN

    def test_kept_on_screen_vertically(self):
        from src.gui.widgets.academy_guide import below_placement
        _x, y, _t = below_placement(620, 1000, W, H, **SCREEN)
        assert y + H <= SCREEN["bottom"]


class _FakeApp:
    popup = None
    modal = None

    @classmethod
    def activePopupWidget(cls):
        return cls.popup

    @classmethod
    def activeModalWidget(cls):
        return cls.modal


@pytest.fixture
def fake_app(monkeypatch):
    from src.gui.widgets import academy_guide
    _FakeApp.popup = _FakeApp.modal = None
    monkeypatch.setattr(academy_guide, "QApplication", _FakeApp)
    return _FakeApp


class TestOtherPopupOrModal:
    def test_nothing_open(self, qapp, fake_app):
        from PySide6.QtWidgets import QWidget
        from src.gui.widgets.academy_guide import other_popup_or_modal
        assert other_popup_or_modal(QWidget()) is False

    def test_a_menu_or_a_dialog_counts(self, qapp, fake_app):
        from PySide6.QtWidgets import QWidget
        from src.gui.widgets.academy_guide import other_popup_or_modal
        own = QWidget()
        fake_app.popup = QWidget()
        assert other_popup_or_modal(own) is True
        fake_app.popup, fake_app.modal = None, QWidget()
        assert other_popup_or_modal(own) is True

    def test_own_widgets_do_not_count(self, qapp, fake_app):
        from PySide6.QtWidgets import QWidget
        from src.gui.widgets.academy_guide import other_popup_or_modal
        own = QWidget()
        fake_app.popup = QWidget(own)                # e.g. the bubble's own popup
        fake_app.modal = own
        assert other_popup_or_modal(own) is False


class TestBubble:
    def _bubble(self, target):
        from src.gui.widgets.academy_guide import TorusGuideBubble
        bubble = TorusGuideBubble()
        bubble.start([(target, "Open <b>Analyse</b>.")])
        return bubble

    def test_below_target_puts_the_tail_on_top(self, qapp):
        from PySide6.QtCore import QPoint
        from src.gui.widgets.academy_guide import below_placement
        target = QPoint(300, 120)
        bubble = self._bubble(lambda: (target, "below"))
        try:
            avail = bubble._screen_geometry(target)
            x, y, tail_x = below_placement(
                target.x(), target.y(), bubble.width(), bubble.height(),
                avail.left(), avail.top(), avail.right(), avail.bottom())
            assert bubble._tail_side == "top"
            assert (bubble.x(), bubble.y(), bubble._tail_anchor_x) == (x, y, tail_x)
        finally:
            bubble._close_and_finish()

    def test_steps_aside_and_comes_back(self, qapp, monkeypatch):
        from PySide6.QtCore import QPoint
        from src.gui.widgets import academy_guide
        busy = {"value": False}
        monkeypatch.setattr(academy_guide, "other_popup_or_modal",
                            lambda own: busy["value"])
        bubble = self._bubble(lambda: (QPoint(600, 300), "below"))
        try:
            pos = bubble.pos()
            assert bubble.isVisible()
            busy["value"] = True                     # a menu or a dialog opens
            bubble._check_aside()
            assert not bubble.isVisible()
            busy["value"] = False                    # ... and closes again
            bubble._check_aside()
            assert bubble.isVisible()
            assert bubble.pos() == pos               # back where it was
        finally:
            bubble._close_and_finish()

    def test_a_finished_tour_stays_hidden(self, qapp, monkeypatch):
        from PySide6.QtCore import QPoint
        from src.gui.widgets import academy_guide
        busy = {"value": True}
        monkeypatch.setattr(academy_guide, "other_popup_or_modal",
                            lambda own: busy["value"])
        bubble = self._bubble(lambda: (QPoint(600, 300), "below"))
        bubble._check_aside()                        # aside ...
        bubble._close_and_finish()                   # ... and the tour ends
        busy["value"] = False
        bubble._check_aside()
        assert not bubble.isVisible()
        assert not bubble._aside_timer.isActive()


class TestMenuPoint:
    def _menu_bar(self):
        from PySide6.QtWidgets import QMenuBar
        bar = QMenuBar()
        bar.addMenu("File").setObjectName("fileMenu")
        analyse = bar.addMenu("Analisi")             # translated title (Italian)
        analyse.setObjectName("analyseMenu")
        bar.show()
        return bar

    def _point(self, bar, name):
        from src.gui.widgets.academy_window import AcademyWindow
        holder = types.SimpleNamespace(mw=types.SimpleNamespace(menu_bar=bar))
        return AcademyWindow._menu_point(holder, name)()

    def test_found_by_object_name_whatever_the_title(self, qapp):
        bar = self._menu_bar()
        try:
            from PySide6.QtWidgets import QMenu
            point, side = self._point(bar, "analyseMenu")
            assert side == "below"
            menu = bar.findChild(QMenu, "analyseMenu")
            rect = bar.actionGeometry(menu.menuAction())
            assert rect.left() > 0                   # not the first entry ("File")
            local = bar.mapFromGlobal(point)
            assert local.x() == rect.center().x()
            assert local.y() == rect.bottom()        # just under the title
        finally:
            bar.close()

    def test_unknown_menu_gives_no_target(self, qapp):
        bar = self._menu_bar()
        try:
            assert self._point(bar, "noSuchMenu") is None
        finally:
            bar.close()


def test_main_window_menus_carry_their_object_names():
    # menu_builder names every top-level menu; the Academy finds Analyse by it.
    import os
    import re
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "src", "gui", "components", "menu_builder.py"),
              encoding="utf-8") as fh:
        source = fh.read()
    assert re.search(r'\(analyse_menu,\s*"analyseMenu"\)', source)
