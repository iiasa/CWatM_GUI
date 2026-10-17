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

# the sparkline's animal names -> Shop item codes: first the image animals
# (assets/ani/<name>.png, discharge_sparkline.image_animals - the names the GUI
# shows), then the older emoji names (discharge_sparkline.ANIMALS) for the emoji
# mode; the fish became the trout and the sailboat the bottle (migration
# ..._shop_animals_v2.sql renamed the items, so their buyers own the new ones).
ANIMAL_CODES = {
    "Trout": "trout",
    "Catfish": "catfish",
    "Clownfish": "clownfish",
    "Salmon (Jessi)": "salmon",          # migration ..._shop_salmon.sql
    "Otter": "otter",
    "Beaver": "beaver",
    "Octopus (Carla)": "octopus",
    "Bottle": "bottle",
    "Mole": "mole",
    "Fish": "trout",
    "Sailboat": "bottle",
    "Octopus (for Carla)": "octopus",
}
# Shop item code -> the image animal's name (the first name listed above)
ANIMAL_NAMES = {}
for _name, _code in ANIMAL_CODES.items():
    ANIMAL_NAMES.setdefault(_code, _name)

# a reward item is never sold: claim_reward(<reward>) gives it once
MODFLOW_REWARD = "modflow_first_run"     # -> the mole
MODFLOW_REWARD_ANIMAL = "Mole"
# The feature badges for successful runs with a model feature on - bronze at the
# first run, silver at MOLEFLOW_SILVER, gold at MOLEFLOW_GOLD; must match the server's
# _moleflow_tier (migration ..._moleflow_badges.sql). One tier replaces the other.
MOLEFLOW_SILVER = 20
MOLEFLOW_GOLD = 50
MOLEFLOW_TIERS = ("bronze", "silver", "gold")
# feature (= run_ledger entry flag = server p_feature) -> (badge name, image prefix
# in assets/badges: <prefix>_<tier>_badge.png, what a run needs)
FEATURE_BADGES = {
    "modflow":    ("MoleFlow", "moleflow", "coupled MODFLOW"),
    "pysnowclim": ("pySnowClim", "pysnowclim", "pySnowClim"),
    "glacier":    ("Glacier OGGM", "glacier_oggm", "glaciers"),
}


# The CWatM Academy Field Test badge - computed from the scores alone, nothing extra
# is stored: bronze = played (a best above 0), silver = a best above
# FIELD_TEST_SILVER points, gold = holding the record of all users (the own best is
# the record) - lost again when someone beats it.
FIELD_TEST_SILVER = 10000


def field_test_tier(best, record):
    """bronze | silver | gold | None from the own best and the record of all users."""
    best, record = int(best or 0), int(record or 0)
    if best <= 0:
        return None
    if record > 0 and best >= record:
        return "gold"
    if best > FIELD_TEST_SILVER:
        return "silver"
    return "bronze"


def field_test_badge_image(tier):
    """assets/badges/<code>.png of a Field Test badge tier."""
    return f"cwatm_fieldtest_{tier}_badge"


def feature_badge_image(feature, tier):
    """The image code (assets/badges/<code>.png) of a feature badge tier."""
    return f"{FEATURE_BADGES[feature][1]}_{tier}_badge"


def moleflow_tier(runs):
    """bronze (1 run, with the mole) | silver | gold | None for a run count."""
    runs = int(runs or 0)
    if runs >= MOLEFLOW_GOLD:
        return "gold"
    if runs >= MOLEFLOW_SILVER:
        return "silver"
    return "bronze" if runs >= 1 else None


def moleflow_next(runs):
    """(next tier, runs still needed) - (None, 0) at gold."""
    runs = int(runs or 0)
    for tier, need in (("bronze", 1), ("silver", MOLEFLOW_SILVER), ("gold", MOLEFLOW_GOLD)):
        if runs < need:
            return tier, need - runs
    return None, 0


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
