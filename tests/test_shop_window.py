"""The Shop window (src/gui/widgets/shop_window.py) and the menu-bar Shop button,
against a fake worker - no network. The server decides every purchase; these check
what the window shows and sends."""

import pytest

pytestmark = pytest.mark.qt

from PySide6.QtWidgets import QMessageBox  # noqa: E402

from src.gui.components import account_ui  # noqa: E402
from src.gui.widgets import shop_window as W  # noqa: E402
from tests.test_account_ui import FakeMainWindow, _dispose, _Host, STATUS  # noqa: E402
from tests.test_account_shop import ITEMS  # noqa: E402


def _status(earned, spent=0, owned=(), badges=({"code": "breg", "name": "Breg"},)):
    return dict(STATUS, total_points=earned, earned_points=earned,
                balance=earned - spent, purchases=[{"code": c} for c in owned],
                badges=list(badges))


class ShopHost(FakeMainWindow):
    def __init__(self, status):
        super().__init__(status=status)
        self.animal, self.level = None, None

    def _set_animal(self, name):
        self.animal = name

    def set_experience_level(self, level):
        self.level = level


@pytest.fixture
def shop(qapp):
    made = []

    def open_with(status):
        m = ShopHost(status)
        w = W.ShopWindow(m)
        assert m.worker.sent == [("get_shop_items", (), {})]
        m.worker.succeeded.emit("get_shop_items", ITEMS)
        assert m.worker.sent[-1] == ("get_status", (), {})
        m.worker.succeeded.emit("get_status", status)
        made.append(m)
        return m, w
    yield open_with
    for m in made:
        _dispose(qapp, m)


def test_header_shows_actual_and_earned_points(shop):
    _m, w = shop(_status(30, 8))
    assert w.lbl_balance.text() == "Your points: 22  ·  earned in total: 30"


def test_level_rows(shop):
    _m, w = shop(_status(30))
    assert w.level_buttons["advanced"].isEnabled()
    assert not w.level_buttons["expert"].isEnabled()          # Advanced first
    _m, w = shop(_status(60, 20, ["advanced"]))
    assert "advanced" not in w.level_buttons                    # ✓ already bought
    assert w.level_buttons["expert"].isEnabled()
    _m, w = shop(_status(50, 20, ["advanced"]))                 # 30 left < 40
    assert not w.level_buttons["expert"].isEnabled()


def test_only_affordable_unowned_animals_are_offered(shop):
    _m, w = shop(_status(25, 5, ["fish"]))                       # 20 left
    offered = [w.cmb_animal.itemData(i) for i in range(w.cmb_animal.count())]
    assert offered == ["otter", "beaver"]


def test_nothing_affordable(shop):
    _m, w = shop(_status(3))
    assert not w.btn_animal.isEnabled()
    notes = [lbl.text() for lbl in w.body.findChildren(type(w.lbl_balance))]
    assert any("needs 2 points more" in t for t in notes)


def test_buying_asks_first_and_uses_the_purchase(shop, monkeypatch):
    m, w = shop(_status(30))
    answers = [QMessageBox.No]
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: answers.pop(0)))
    w._buy(next(i for i in ITEMS if i["code"] == "otter"))
    assert m.worker.sent[-1] == ("get_status", (), {})          # declined: nothing
    answers[:] = [QMessageBox.Yes]
    w._buy(next(i for i in ITEMS if i["code"] == "otter"))
    assert m.worker.sent[-1] == ("buy", ("otter",), {})
    m._status = _status(30, 10, ["otter"])
    m.worker.succeeded.emit("buy", dict(m._status, status="bought", item="otter"))
    assert m.animal == "Otter"                                   # shown at once
    assert "Bought: Otter" in w.status.text()


def test_a_bought_level_is_offered_at_once(shop, monkeypatch):
    m, w = shop(_status(30))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    w._buy(next(i for i in ITEMS if i["code"] == "advanced"))
    m._status = _status(30, 20, ["advanced"])
    m.worker.succeeded.emit("buy", dict(m._status, status="bought", item="advanced"))
    assert m.level == "Advanced"


def test_a_refusal_stays_readable_after_the_refresh(shop, monkeypatch):
    m, w = shop(_status(30))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    w._buy(next(i for i in ITEMS if i["code"] == "beaver"))
    m.worker.failed.emit("buy", "not_enough_points", "You need 2 more points for this.")
    assert m.worker.sent[-1] == ("get_status", (), {})
    m.worker.succeeded.emit("get_status", _status(18))
    assert "2 more points" in w.status.text()


@pytest.mark.parametrize("status,visible", [
    (None, False),                                              # logged out
    (dict(STATUS, badges=[]), False),                           # no Breg yet
    (STATUS, True),                                             # logged in + Breg
])
def test_shop_button_needs_login_and_breg(qapp, tmp_path, monkeypatch, status, visible):
    from src.gui.utils import run_ledger
    monkeypatch.setattr(run_ledger, "history_dir", lambda: str(tmp_path))
    monkeypatch.setattr(account_ui.account_config, "is_configured", lambda: True)
    h = _Host(tmp_path / "s.ini")
    h._create_shop_button().setParent(h)
    h._init_account()
    if status is not None:
        h._on_account_succeeded("login", status)
    assert h.shop_visible() is visible
    assert h._shop_button.isVisibleTo(h) is visible
    run_ledger.remove_listener(h._on_run_recorded)
    _dispose(qapp, h)


def test_level_row_text():
    adv, exp = ITEMS[0], ITEMS[1]
    assert W.level_row_text(exp, _status(100)) == (
        "Buy Advanced first", False, "Expert needs the Advanced level first")
    assert W.level_row_text(adv, _status(5))[:2] == ("15 more points needed", False)
    assert W.level_row_text(adv, _status(20, 20, ["advanced"]))[0] == "✓ already bought"
