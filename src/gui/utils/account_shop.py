"""The Shop's rules on the GUI side - pure, no network, no Qt.

The server decides every purchase (``shop_buy``, migration ``..._shop.sql``); these
helpers only read an account status (``get_my_status`` / ``buy`` answer) and the
price list (``get_shop_items``) so the Shop window, the level button and
Preferences ▸ Select animal agree on what is owned, affordable or still locked.

Points: *earned* never goes down and decides the badges; *balance* = earned minus
what was spent, the points that can be spent. A status from a server without the
Shop has neither field - then balance = earned = ``total_points``.
"""

SHOP_BADGE = "breg"          # = game_config.shop_required_badge

# the sparkline's animal names (discharge_sparkline.ANIMALS) -> Shop item codes
ANIMAL_CODES = {
    "Fish": "fish",
    "Otter": "otter",
    "Beaver": "beaver",
    "Sailboat": "sailboat",
    "Octopus (for Carla)": "octopus",
}
LEVEL_CODES = {"Advanced": "advanced", "Expert": "expert"}

# item_state() answers
OWNED, LOCKED, UNAFFORDABLE, BUYABLE = "owned", "locked", "unaffordable", "buyable"


def earned(status):
    """Points ever earned (the maximum ever achieved; decides the badges)."""
    status = status or {}
    return int(status.get("earned_points", status.get("total_points", 0)) or 0)


def balance(status):
    """Points that can be spent (earned minus purchases)."""
    status = status or {}
    return int(status.get("balance", earned(status)) or 0)


def owned(status):
    """The codes of the items the user owns (bought or granted)."""
    return {p.get("code") for p in (status or {}).get("purchases") or []
            if p.get("code")}


def has_shop_badge(status):
    return any(b.get("code") == SHOP_BADGE for b in (status or {}).get("badges") or [])


def item_state(item, status):
    """Where one price-list item stands for this user:
    OWNED, LOCKED (its ``requires`` item is not owned yet - Expert before
    Advanced), UNAFFORDABLE (balance too low) or BUYABLE."""
    mine = owned(status)
    if item.get("code") in mine:
        return OWNED
    if item.get("requires") and item["requires"] not in mine:
        return LOCKED
    if balance(status) < int(item.get("price", 0)):
        return UNAFFORDABLE
    return BUYABLE


def animals_for_sale(items, status):
    """The animals the selector offers: affordable and not owned yet (decision 5)."""
    return [i for i in items
            if i.get("kind") == "animal" and item_state(i, status) == BUYABLE]


def points_to_cheapest(items, status):
    """How many more points the cheapest not-owned, unlocked item needs - 0 when
    something is affordable now, None when everything is owned."""
    open_items = [i for i in items if item_state(i, status) in (UNAFFORDABLE, BUYABLE)]
    if not open_items:
        return None
    return max(0, min(int(i.get("price", 0)) for i in open_items) - balance(status))
