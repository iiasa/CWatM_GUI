"""River badges by total EARNED points - a port of
``supabase/migrations/20260928120100_gamification_functions.sql``'s
``_award_badges()``/``_total_points()``, with the final ladder from
``20260929140000_badge_ladder_v3.sql`` (12 tiers, Breg to Amazonas - the
last of three revisions to this table, confirmed by checking every later
migration for a further change; none exists).

Pure logic: no Accelerator API calls, no file I/O. "Earned" points never
go down (CLAUDE.md: "Earned points (badges) never go down; the balance...
is what is shown, ranked and spent") - badges are checked against the sum
of every positive point event this user has (every file under
ledger/<uid>/.../*.json whose event carries "points"), never against a
spendable balance reduced by shop purchases.
"""

RIVER_BADGES = (
    ("breg", "Breg", 5),
    ("thames", "Thames", 15),
    ("morava", "Morava", 30),
    ("inn", "Inn", 50),
    ("drava", "Drava", 100),
    ("elbe", "Elbe", 200),
    ("rhine", "Rhine", 400),
    ("ganges", "Ganges", 800),
    ("danube", "Danube", 1500),
    ("mekong", "Mekong", 3000),
    ("nile", "Nile", 5000),
    ("amazonas", "Amazonas", 10000),
)


def earned_badges(total_points):
    """Every badge code this total has reached, ascending by threshold."""
    return [code for code, _name, required in RIVER_BADGES if required <= total_points]


def new_badges(total_points, already_held_codes):
    """Badges this total newly reaches that aren't already held - what
    _award_badges() returns (and would insert into the ledger). Ascending
    by threshold, same order the SQL's `order by b.sort_order` produces for
    the current ladder (sort_order tracks ascending points_required)."""
    held = set(already_held_codes)
    return [
        {"code": code, "name": name, "points_required": required}
        for code, name, required in RIVER_BADGES
        if required <= total_points and code not in held
    ]


def next_badge(total_points):
    """The next badge above this total, or None once all 12 are held -
    mirrors the "next badge" query repeated across several migrations
    (e.g. 20260928200000_user_locations_map.sql): points_required > total,
    order by points_required, limit 1. No already-held check needed here
    (unlike new_badges) - nothing above the current total can be held yet,
    since a badge is awarded the moment its threshold is reached."""
    for code, name, required in RIVER_BADGES:
        if required > total_points:
            return {"code": code, "name": name, "points_required": required}
    return None
