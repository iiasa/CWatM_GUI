# Idea of a shop:

## The Shop
Make a menu Shop right of the login menu. But this appears only if you have logged in and if you have the Breg badge.
For the points you accumulated you can buy things in the shop.
if you buy things the amount of points you have is reduced by the priz.
The badges you have are not affected, but for new badges you still have to earn the amount of point 
eg you have 20 points and you have the badges Breg and Thames and you by something for 18 points , your account has now 2 points left
and you still have the badges Breg and Thames

## In the shop you can buy

- Advanced (cost 20 points) and Expert (cost 40 points) level. once you bought this you can change from Beginner to Advanced or Expert. Without you cannot change but you get a message
- in shop create a item where you can select to buy advance or expert. if you bought it then mark it as already bought
- you can buy animals for the menu: Preferences/Display/Select Animal
  Fish (cost 5), Otter (10), Beaver (20), Sailboat (30), Octupus (50)
 - in the shop make a menuitem similar to Preferences/Display/Select Animal where you can select which animal you want to buy.
   But show only those animals you can afford with your point

## Other things to change

In the menu Preferences/Display/Select Animal show only the animal you brought

in the supabase database store the things you bought, the badge you have, the actual points and the maximum point you ever archived

---

# Implementation plan (not programmed yet)

The core idea is to split points into two numbers:

- **Earned points:** everything you ever earned. They never go down, they decide your badges, and they are the "maximum points ever achieved". They are what the server already calls total points.
- **Balance:** earned points minus everything you spent. This is what you buy with.

In the example: 20 earned, 18 spent, so the balance is 2. Breg and Thames stay because badges keep using the earned 20. The next badge still needs 30 earned points.

## Step 1 – Decisions

1. **Existing users keep their levels.**
   Every account that exists when the shop migration is pushed gets Advanced and Expert as free purchases (price 0, so the balance is untouched).
   Only accounts created afterwards have to buy them. Nobody who uses Expert today is demoted.
2. **Advanced first, then Expert.** Both are shown with their price, but without Advanced the Expert item is greyed out (tooltip: "Buy Advanced first"). The server refuses Expert without Advanced too.
3. **No free animal.** Without a bought animal the sparkline shows only the plain dot. Fish costs 5, as specified. Animals are cosmetic, so losing the fish is acceptable.
4. **The leaderboard ranks by actual points** (the balance, after spending). Buying something therefore moves you down the ranking. The "highest badge" column stays on earned points, because badges are never lost.
5. **What the shop shows:**
   - Levels are always listed. If you cannot afford one, it is greyed out and shows its price, so you can see the goal.
   - Animals: as specified, the selector offers only animals you can afford and do not own yet. Owned animals are listed separately, marked "✓ bought".
   - If you can afford nothing, a note says how many points the cheapest item still needs.
6. **No refunds and no selling back.** Each purchase is final, and the confirmation dialog says so.
7. **No Supabase key configured** (developer/source runs without an account server): everything stays open, as today. All levels and all animals are available, and there is no Shop menu.
8. **Logged out:** Beginner and the plain dot, no Shop. Logging in again restores what was bought.
9. **Offline / still reconnecting:** use the purchases cached from the user's last successful status. A purchase itself always needs the server.

10. **Cheat option.** Preferences ▸ Account gets a tick box **"Cheat - and get the Expert level without buying it"**.
    - Ticked: you can switch freely between Beginner, Advanced and Expert, without buying the levels. Animals are not affected.
    - **Session only.** The tick is kept in memory, never saved (no QSettings key), so every start of the CWatM GUI begins with it off. When it is switched off, or at the next start, the level falls back to what the user owns.
    - **Local only.** Nothing is sent to the server, and no purchase or points are created.
    - **Works while logged out too** (decided). On the Preferences ▸ Account page it is the one control that stays enabled when logged out, and while it is ticked the Skill-of-user box and the level button are enabled as well.
    - Anyone can skip buying levels this way. That is intended: see the guiding principle below.

**Guiding principle (decided):** the gamification must not hinder anyone who uses CWatM seriously; at most it is a tiny annoyance. Every feature a serious user needs stays reachable without points or a login. The Cheat tick is the always-available way out for the levels, and animals are purely cosmetic. When a later detail is unclear, it is decided in favour of the serious user.

---

### The open questions as first listed (kept for reference)
- **Existing users:** today Advanced/Expert unlock just by logging in. Once they cost points, a user now on Expert, or someone with no points, drops back to Beginner. Options: give current accounts the levels for free, or accept the drop. Expert also hides the tabs, Compare Tab (F8) and Create batch, so this hits experienced CWatM users hardest. Expert at 40 points means about 40 different model setups (one point per distinct setup).
- **Buying order:** can Expert be bought without Advanced first?
- **The free animal:** Fish costs 5, but it is today's default. Who gets what before buying anything? Proposal: a plain dot (no animal) until one is bought. The alternative is Fish for free.
- **Leaderboard:** rank by earned points (proposal) or by balance?
- **Shop visibility:** the menu appears with the Breg badge, but Advanced costs 20. Should items you cannot afford yet be shown greyed with their price? The idea says only affordable animals are shown; treat levels the same way, or show them greyed so users see the goal.
- **Refunds:** none (proposal).
- **No Supabase key configured** (developer/source runs): keep everything open as today (proposal).

## Step 2 – Database (one new Supabase migration) — DONE and pushed 2026-10-01

Written as `supabase/migrations/20261001130000_shop.sql` (see also `supabase/README.md`).
Implementation notes beyond the bullets below:
- Item codes: `advanced`, `expert`, `fish`, `otter`, `beaver`, `sailboat`, `octopus`. The GUI's animal "Octopus (for Carla)" maps to `octopus` in Step 4.
- The required badge is the setting `game_config.shop_required_badge` (`"breg"`).
- Grandfathered rows have `price_paid = 0` and `granted = true`.
- The leaderboard column `total_points` is now the **balance** (old GUIs therefore show the ranked number); `earned_points` is added. `get_my_status.total_points` stays **earned**, and `earned_points` + `balance` are added next to it.
- `award_run` / `academy_complete_level`: the old logic was renamed to `_award_run_core` / `_academy_complete_level_core` and wrapped, so the existing rules stay exactly as they were.
- `shop_buy` answers with the full `get_my_status()` plus `status` (`bought`, `already_owned`, `badge_required`, `requires_item`, `not_enough_points`, `unknown_item`).

- **`shop_items` table:** code, kind (`level` / `animal`), name, price, sort order. Seeded with Advanced 20, Expert 40, Fish 5, Otter 10, Beaver 20, Sailboat 30, Octopus 50. Prices live on the server, so they can change without a new GUI release.
- **`purchases` table:** user, item, price paid, time. One row per user and item, so nothing can be bought twice. It is deleted together with the account. Users can read their own rows but cannot write them.
- **`shop_buy(item)` function:** the only way to buy. In one step it locks the user's row, checks the Breg badge, the balance, "not owned yet" and, for Expert, "Advanced owned", records the purchase and returns the new status. Two quick clicks can never overspend.
- **Server helpers:** earned stays as the existing total; spent = sum of purchases; balance = earned − spent.
- **Badges:** keep evaluating them on earned points. No change needed, but it must be stated in the migration.
- **`get_my_status` returns** `earned_points` (= maximum ever), `balance`, `purchases` (owned item codes) and the existing badges. For older GUIs, keep `total_points` meaning earned.
- **Same new fields for** the run reward (`award_run`) and the Academy reward (`academy_complete_level`), so the GUI updates the balance right after a run.
- **A public `get_shop_items` function** returns the item list.
- **Data export** includes the purchases.
- **Leaderboard (`get_leaderboard`):** rank and points by balance (decision 4); the highest badge still from earned points.
- **Grandfathering (decision 1):** a one-time insert of free 0-price "Advanced"/"Expert" purchases for the existing accounts.
- **Stored state:** owned items (`purchases`), badges (the existing `user_badges`), current balance and maximum points. Compute the last two from the point and purchase tables rather than keep them as columns, so they can never drift. If real columns are wanted, they would be kept up to date automatically on every change.

## Step 3 – Client layer (`account_client.py` / `account_worker.py`) — DONE 2026-10-01

Done as planned, plus a pure rules module `src/gui/utils/account_shop.py` for Steps 4–5: earned / balance / owned, the Breg check, `item_state` (owned / locked / unaffordable / buyable), the animals for sale, the points still needed for the cheapest item, and the animal-name → item-code map. Tests: `tests/test_account_shop.py` and `TestShopClient` in `tests/test_account.py`.

- Add `buy(item_code)` and `get_shop_items()`. Register both as worker operations.
- Add an error code for "not enough points", "already owned", "Breg needed" and "Advanced first", with readable messages.

## Step 4 – Entitlements in the main window (`account_ui.py`) — DONE 2026-10-01

Done as planned. Details decided while building it:
- `levels_unlocked()` keeps its meaning (a login is in place); the Academy's Level-4 rule still uses it. The levels use the new `level_allowed(level)`.
- Effective level = the preferred one if owned, else the highest owned level below it (preferred Expert, only Advanced bought → Advanced). The preferred choice stays saved.
- Level button: a level you do not own shows the message (how to buy it, plus the Cheat tick), then the cycle goes on to Beginner.
- Offline cache: QSettings `account/owned/<user>`. When no cache exists yet (the first start after this update), nothing is locked while the login is restored, so an Expert does not flash to Beginner.
- A saved animal that is not owned falls back to the first owned one, else the plain dot. The saved choice is kept, so it comes back once bought.
- The Cheat tick is applied before a level chosen in the same Apply.
- Tests: `TestShopEntitlements`, `TestEffectiveLevel` and the sparkline test in `tests/test_account_ui.py`.

- **One place answers "does the user own X?":** `owns(item)`, read from the last account status. Everything else asks it.
- **Levels:** the current `levels_unlocked()` check (logged in) becomes per level: Advanced if Advanced is owned, Expert if Expert is owned. Re-checked on every login-state or status change.
  - Logged out, or not owned, means Beginner, unless the Cheat tick is on. The level button and the Preferences box keep their current message, but it says "buy it in the Shop, or tick Cheat in Preferences ▸ Account" instead of "log in". That way the way out is always named.
  - The Academy's login rule from Level 4 on stays login-only. It does not need Advanced.
  - **Cheat (decision 10):** a session-only flag on the main window (`_cheat_levels`, in memory, never persisted). While it is on, every level counts as owned. Preferences ▸ Account shows it as a tick box, applied through the usual buffered Apply. Switching it off re-derives the level from what is owned.
- **Offline / still reconnecting at start:** use what the user owned at their last successful login, so a network hiccup does not demote them. This needs a small per-user cache of owned items, which is only a cache; the server decides.
- **Animals:** Preferences ▸ Display ▸ Select animal lists only bought animals. With none bought: the plain dot only (decision 3); the Select animal box then shows "None – buy one in the Shop". A saved animal that is not owned falls back.

## Step 5 – Shop menu and window — DONE 2026-10-01

Done as planned: `src/gui/widgets/shop_window.py` (`ShopWindow`, `open_shop`), and the **Shop** button between the account button and ⋮ (`AccountMixin._create_shop_button` / `shop_visible`). Details decided while building it:
- After buying an **animal**, it becomes the sparkline's animal at once. After buying a **level**, a question offers to switch to it now.
- A refused purchase (e.g. not enough points) keeps its message and re-reads the status, so the window matches the server again.
- The account button, its tooltip, the account window, Preferences ▸ Account and the run/Academy output-box notes show the **actual points** (balance), with "earned in total" next to them when the two differ. The next-badge bar and "N more points" stay on earned points.
- Tests: `tests/test_shop_window.py`.

- **Menu-bar button "Shop"** next to the account button. Visible only when logged in **and** Breg is owned. Re-checked whenever the status changes, including right after the run that earns Breg.
- **Shop window** (rebuilt each time it opens, themed, follows the language setting):
  - **Header:** "Balance: N points · earned in total: M".
  - **Level section:** Advanced and Expert, always listed with price; "✓ already bought" when owned. Greyed out when not affordable, and Expert also while Advanced is not owned (decision 2).
  - **Animal section:** a selector like the Preferences one, listing the animals you can afford and do not own yet, with emoji and price. Owned ones are shown marked as bought.
  - **Before buying:** a confirmation, e.g. "Buy Otter for 10 points? Balance afterwards: 2".
  - **After buying:** status, header, menu and Preferences are refreshed. A bought level can be switched to at once.
- **Account window:** the "Points:" line becomes "Balance / earned in total". The progress bar towards the next badge stays on earned points.
- **Leaderboard:** ranks and shows actual points (decision 4).

## Step 6 – Texts, privacy, docs — DONE 2026-10-01 (without translations)

Done: the privacy notice (purchases, the local copy of owned items, deletion; tied to the code by `test_notice_describes_the_shop`, notice version unchanged), `CLAUDE.md`, the manual (§15 Account page + "The Shop") and the feature tour. `supabase/README.md` was already done in Step 2.
**Left out on request:** the translations, so the Shop texts are English in every language for now.

- **Translations:** add the new strings to `ui_strings_languages.csv`.
- **Privacy notice:** add a line about purchases (what was bought, when, price). The privacy test is tied to this notice and must be updated with it. Decide whether a new notice version is needed. Purchases are ordinary account data, so probably not.
- **Docs:**
  - `CLAUDE.md`: the menu table, the skill-level note (levels now bought rather than unlocked by login), the Select animal row and the account section.
  - `supabase/README.md`: the migration list.
  - The manual and the feature tour: a Shop section.

## Step 7 – Tests — DONE 2026-10-01

Where each item is tested:
- **Rules (pure):** `tests/test_account_shop.py` (balance = earned − spent, the 20 − 18 = 2 example, item states, animals for sale, cheapest item).
- **Client:** `TestShopClient` in `tests/test_account.py` (every refusal → a readable message).
- **UI with a fake worker:**
  - `tests/test_shop_window.py`: Shop button only with login + Breg, Buy disabled when not affordable, Expert greyed without Advanced, "already bought", confirmation, a bought animal/level is used at once, a refusal stays readable;
  - `TestShopEntitlements` / `TestEffectiveLevel` in `tests/test_account_ui.py`: offline cache, Cheat never persisted, no flash to Beginner while restoring.
- **Real main window** (`tests/test_shop_main_window.py`):
  - the level button refuses an unowned level and names both ways out (Shop + Cheat);
  - `set_experience_level` refuses, and buying Expert switches to it;
  - Preferences ▸ Select animal lists only bought animals ("None – buy one in the Shop" otherwise);
  - Cheat is off after a restart and absent from the settings file;
  - the Cheat tick enables the level box before Apply.
- **Server SQL** (`tests/test_server_sql.py`, reads the LATEST definition of each of the 34 functions across all migrations):
  - badges and the next-badge goal use earned points, never the balance (a mutation check confirmed the test catches the opposite);
  - balance = earned − spent − decay;
  - `shop_buy` runs every check under the shop lock before writing, at the server's price;
  - decay shares that lock and never goes below 5;
  - the shown balances include the decay due;
  - no client write grants on points/purchases/decay/badges;
  - a run is stored by its fingerprint only;
  - security rules for all functions and tables: `search_path` pinned on every definer function, EXECUTE revoked from anon/authenticated on every non-trigger function, RLS on every table, no dynamic SQL.

**Server review (by reading the current SQL, after the decay and data-minimisation changes): no defect found.** Notes, none needing action now:
- `award_run` (lock `award_run:`) and the decay settlement (lock `shop:`) use different locks. A run counted at the very moment a decay is recorded can make that decay differ by about one point – harmless.
- The leaderboard computes the current balance (incl. the decay due) per opted-in user. That is fine for hundreds of users; with thousands it should become a stored/cached value.
- A purchase records the price paid, so later price changes never alter old purchases.
- Accounts created after the Shop migration was pushed have to buy Advanced/Expert (or use Cheat); only the accounts that existed then got them free.

- **Rules (pure logic):** balance = earned − spent; badges unaffected by spending; the 20 − 18 = 2 example; ownership and affordability checks.
- **UI with a fake worker:** Shop visible only with login + Breg; Buy disabled when not affordable; Expert greyed without Advanced; the Cheat tick unlocks all levels and is off again after a restart (never persisted); "already bought" marking; level button refuses an unbought level with a message; Preferences lists only owned animals; offline keeps the cached ownership.
- **Server function:** buying twice, insufficient balance, no Breg, and Expert without Advanced are refused. Verified by reading the migration; no live checks after `db push`.

## Step 8 – Rollout
1. Push the migration (`npx supabase db push`) and test it on the server by hand.
2. Release the GUI with `/creategui`.
3. Older GUIs keep working, because `total_points` keeps its meaning. They just have no shop.

**Suggested build order:** steps 1 → 2 → 3 → 4 → 5, with tests written alongside each step, then 6 and 8. Steps 4 and 5 can be tested with a fake server answer before the migration is pushed.


---

# Point decay (decided 2026-10-01)

**Rule:** your *actual points* (the balance spent in the Shop) decay when CWatM GUI is not used:
- after 1 week without use: −3 %
- every further week: −5 % of what is left (compounding)
- never below **5 points**; a balance of 5 or less does not decay
- whole points, rounded to the nearest point

Example with 100 points: 1 week → 97, 2 weeks → 92, 3 weeks → 88, 4 weeks → 83.

**Earned points and badges never decay** (same rule as Shop purchases).

**"Using CWatM GUI" = a login** to the CWatM account, including the automatic re-login at start ("Stay logged in"). Runs do not count separately for now; this may change later.

**Existing accounts** start their clock when the migration is pushed, so nobody loses points at once.

## Steps
1. **Server migration:**
   - `profiles.last_active_at` and the weeks already decayed;
   - a `point_decay` table (one row per decay);
   - `touch_activity()`, called by the GUI after every login, which first settles the decay due, then restarts the clock;
   - `game_config` values for 3 % / 5 % / minimum 5;
   - the balance becomes earned − spent − decayed, and the leaderboard and status already include decay that is due but not yet recorded;
   - `shop_buy` settles the decay first;
   - export and account deletion include the decay rows.
2. **Client + GUI:**
   - `touch_activity` in the client and worker;
   - submitted after each login;
   - a note in the output box and status bar when points decayed;
   - a hint in the account window ("log in at least once a week").
3. **Privacy notice + docs + tests.**

## Status — built and pushed 2026-10-01
- Server: `supabase/migrations/20261001140000_point_decay.sql`.
- GUI: `touch_activity` after every login (`account_ui`), the output-box note (`decay_message`) and the rule in the account window (`DECAY_RULE`).
- Docs: privacy notice (last-use time + decay rows), `CLAUDE.md`, the manual, the feature tour, `supabase/README.md`.
- Tests: `TestPointDecay` and `test_documented_decay_numbers` in `tests/test_account_ui.py`, `test_notice_describes_the_point_decay`.
- Correction: after 3 weeks, 100 points are **88** (87.5 rounded), not 87.
