"""The account server's rules, read from the SQL itself (supabase/migrations).

The migrations are applied in file-name order and a later ``create or replace``
replaces an earlier one, so each test looks at the LATEST definition of a function
- what actually runs on the server. Nothing here talks to a server; it pins the
rules the GUI relies on (shop.md Step 7) and the security rules every function and
table must follow (security.md).
"""

import glob
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIGRATIONS = sorted(glob.glob(os.path.join(ROOT, "supabase", "migrations", "*.sql")))

_FUNC = re.compile(
    r"create\s+(?:or\s+replace\s+)?function\s+public\.(\w+)\s*\((.*?)\)\s*"
    r"returns\s+(.*?)\$\$(.*?)\$\$", re.IGNORECASE | re.DOTALL)


def _sql():
    return [(os.path.basename(p), open(p, encoding="utf-8").read()) for p in MIGRATIONS]


def _strip_comments(text):
    return re.sub(r"--[^\n]*", "", text)


def latest_functions():
    """name -> (migration, header, body) of the last definition."""
    out = {}
    for name, text in _sql():
        for m in _FUNC.finditer(_strip_comments(text)):
            out[m.group(1)] = (name, m.group(3), m.group(4))
    return out


FUNCS = latest_functions()


def body(fn):
    assert fn in FUNCS, f"{fn} is not defined in any migration"
    return re.sub(r"\s+", " ", FUNCS[fn][2]).lower()


def header(fn):
    return re.sub(r"\s+", " ", FUNCS[fn][1]).lower()


# ---- the points rules (shop.md) -------------------------------------------------------

def test_badges_follow_the_earned_points_never_the_balance():
    # spending (and decay) must never take a badge away or move a badge goal
    b = body("_award_badges")
    assert "_total_points(" in b
    assert "_balance(" not in b and "_current_balance(" not in b
    s = body("get_my_status")
    assert "v_total := public._total_points(v_user)" in s
    assert "points_required > v_total" in s                 # next badge on earned


def test_earned_points_are_only_the_point_events():
    assert "sum(e.points)" in body("_total_points")
    assert "purchases" not in body("_total_points")


def test_balance_is_earned_minus_spent_minus_decay():
    b = body("_balance")
    assert "_total_points(" in b and "- public._spent_points(" in b \
        and "- public._decayed_points(" in b


def test_shop_buy_checks_everything_under_one_lock_before_writing():
    b = body("shop_buy")
    lock = b.index("pg_advisory_xact_lock(hashtext('shop:'")
    insert = b.index("insert into public.purchases")
    for check in ("_settle_decay(", "'already_owned'", "'badge_required'",
                  "'requires_item'", "'not_enough_points'", "v_balance < v_item.price"):
        assert lock < b.index(check) < insert, check
    assert "insert into public.purchases (user_id, item_code, price_paid) " \
           "values (v_user, v_item.code, v_item.price)" in b   # the server's price


def test_decay_shares_the_shop_lock_and_never_goes_below_the_minimum():
    assert "hashtext('shop:'" in body("touch_activity")
    d = body("_decay_due")
    assert "greatest(v_min, round(v_balance * v_factor)" in d
    assert "if v_balance <= v_min then" in d


def test_shown_balances_include_the_decay_due():
    for fn in ("get_my_status", "_points_summary", "get_leaderboard"):
        assert "_current_balance(" in body(fn), fn


def test_purchases_and_points_are_written_only_by_definer_functions():
    for name, text in _sql():
        t = _strip_comments(text).lower()
        for table in ("purchases", "point_events", "point_decay", "user_badges"):
            assert not re.search(rf"grant\s+(insert|update|delete)[^;]*on\s+(table\s+)?"
                                 rf"public\.{table}\b", t), (name, table)


def test_a_run_is_identified_by_its_fingerprint_only():
    b = body("_award_run_core")
    assert "values (v_user, 'run', v_hash, v_points" in b
    assert "meta" not in b.split("insert into public.point_events")[1].split(";")[0]


# ---- security rules for every function and table (security.md) -----------------------

@pytest.mark.parametrize("fn", sorted(FUNCS))
def test_definer_functions_pin_the_search_path(fn):
    _mig, head, _b = FUNCS[fn]
    if "security definer" in head.lower():
        assert "set search_path = ''" in head.lower(), fn


def _revoked_after(fn):
    """Is EXECUTE revoked from anon/authenticated in or after the latest definition?
    (Supabase grants EXECUTE on every new function to them by default.)"""
    defined_in = FUNCS[fn][0]
    for name, text in _sql():
        if name < defined_in:
            continue
        t = re.sub(r"\s+", " ", _strip_comments(text)).lower()
        for m in re.finditer(r"revoke execute on function (.*?) from ([^;]*);", t):
            if re.search(rf"public\.{fn.lower()}\s*\(", m.group(1)) \
                    and "anon" in m.group(2) and "authenticated" in m.group(2):
                return True
    return False


@pytest.mark.parametrize("fn", sorted(FUNCS))
def test_every_function_starts_closed(fn):
    if "trigger" in FUNCS[fn][1].lower():
        return                       # trigger functions cannot be called over the API
    assert _revoked_after(fn), f"{fn}: no 'revoke execute ... from anon, authenticated'"


def test_every_table_has_row_level_security():
    created, rls = set(), set()
    for _name, text in _sql():
        t = _strip_comments(text).lower()
        created |= set(re.findall(r"create table public\.(\w+)", t))
        rls |= set(re.findall(r"alter table public\.(\w+)\s+enable row level security", t))
    assert created and created <= rls, created - rls


def test_no_dynamic_sql():
    for name, text in _sql():
        assert not re.search(r"\bexecute\s+(format|'|\w+\s*\|\|)",
                             _strip_comments(text), re.IGNORECASE), name
