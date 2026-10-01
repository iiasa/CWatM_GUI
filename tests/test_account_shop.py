"""The Shop's GUI-side rules (src/gui/utils/account_shop.py) - pure, no network.

They must agree with the server (shop_buy in supabase/migrations/..._shop.sql):
spending lowers the balance, never the earned points or the badges; Expert needs
Advanced; nothing is bought twice.
"""

import pytest

from src.gui.utils import account_shop as S

ITEMS = [
    {"code": "advanced", "kind": "level", "name": "Advanced", "price": 20, "requires": None},
    {"code": "expert", "kind": "level", "name": "Expert", "price": 40, "requires": "advanced"},
    {"code": "fish", "kind": "animal", "name": "Fish", "price": 5, "requires": None},
    {"code": "otter", "kind": "animal", "name": "Otter", "price": 10, "requires": None},
    {"code": "beaver", "kind": "animal", "name": "Beaver", "price": 20, "requires": None},
    {"code": "sailboat", "kind": "animal", "name": "Sailboat", "price": 30, "requires": None},
    {"code": "octopus", "kind": "animal", "name": "Octopus", "price": 50, "requires": None},
]
BREG_THAMES = [{"code": "breg", "name": "Breg"}, {"code": "thames", "name": "Thames"}]


def status(earned, spent=0, purchases=(), badges=BREG_THAMES):
    return {"total_points": earned, "earned_points": earned, "balance": earned - spent,
            "purchases": [{"code": c} for c in purchases], "badges": list(badges)}


def by_code(code):
    return next(i for i in ITEMS if i["code"] == code)


def test_the_example_from_the_idea():
    # 20 points, Breg + Thames, buy something for 18 -> 2 left, badges unchanged
    st = status(20, spent=18, purchases=["beaver"])
    assert (S.balance(st), S.earned(st)) == (2, 20)
    assert S.has_shop_badge(st) and len(st["badges"]) == 2


def test_server_without_the_shop_falls_back_to_total_points():
    st = {"total_points": 12}
    assert (S.earned(st), S.balance(st), S.owned(st)) == (12, 12, set())


@pytest.mark.parametrize("code,st,state", [
    ("advanced", status(25), S.BUYABLE),
    ("advanced", status(19), S.UNAFFORDABLE),
    ("advanced", status(25, 20, ["advanced"]), S.OWNED),
    ("expert", status(100), S.LOCKED),                       # Advanced first
    ("expert", status(100, 20, ["advanced"]), S.BUYABLE),
    ("expert", status(50, 20, ["advanced"]), S.UNAFFORDABLE),  # balance 30 < 40
    ("expert", status(0, 0, ["advanced", "expert"]), S.OWNED),  # granted, free
])
def test_item_state(code, st, state):
    assert S.item_state(by_code(code), st) == state


def test_only_affordable_unowned_animals_are_for_sale():
    st = status(25, 5, ["fish"])                               # balance 20
    assert [i["code"] for i in S.animals_for_sale(ITEMS, st)] == ["otter", "beaver"]


def test_points_to_cheapest():
    assert S.points_to_cheapest(ITEMS, status(3)) == 2          # Fish costs 5
    assert S.points_to_cheapest(ITEMS, status(30)) == 0         # something affordable
    everything = [i["code"] for i in ITEMS]
    assert S.points_to_cheapest(ITEMS, status(200, 175, everything)) is None
    # Expert is locked (not "open") while Advanced is missing
    st = status(10, 10, ["fish", "otter", "beaver", "sailboat", "octopus"])
    assert S.points_to_cheapest(ITEMS, st) == 20                # Advanced, not Expert


def test_animal_codes_cover_the_sparkline_animals():
    from src.gui.widgets.discharge_sparkline import ANIMALS
    assert set(S.ANIMAL_CODES) == {name for name, _emoji in ANIMALS}
    assert set(S.ANIMAL_CODES.values()) == {i["code"] for i in ITEMS
                                            if i["kind"] == "animal"}
