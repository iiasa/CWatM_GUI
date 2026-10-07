# CWatM GUI — account, points & Shop (developer internals)

Optional user login + points for full runs + river badges, on Supabase. Schema, rpc API,
Edge Functions and project setup: [`supabase/README.md`](../supabase/README.md); Shop plan
and decisions: `shop.md`. The always-true invariants are summarised in `CLAUDE.md`
(*Gamification backend*); this file holds the detail.

## Privacy (S6)
The notice `documentation/CWatM_Account_Privacy.md` must describe what the code does —
`tests/test_account_privacy.py` ties its version line, the offline-queue facts and the
run fields to the code, so changing what is stored or sent means changing the notice.
Every sign-up carries `account_config.PRIVACY_VERSION` (`register(...,
privacy_version=)`); the server **refuses** a sign-up without it and stores version +
time in `profiles` (migration `…140000_privacy_consent.sql`). **Data minimisation**
(migration `…150000_minimal_point_data.sql`): a counted run is stored as fingerprint +
the UTC **day** only, an Academy level as the level only; the export masks the email.

## Client layer (`src/gui/utils/account_*.py`)
**`account_client.py` is the only importer of `supabase`**, and only `AccountWorker` (a
`QThread`, `submit(op, …)` → `succeeded`/`failed`/`busy`) creates it, **on its own
thread** — never call it from the GUI thread. Only the **refresh token** is persisted, in
the **OS keyring** (`account_store.py`, never QSettings), re-saved on every rotation
(`_on_auth_event`); auto-refresh is off, `_session()` refreshes on demand. Every failure
surfaces as `AccountError(code, message)`. `account_validation.py` holds the pure input
rules — its username regex must match the `profiles.username` constraint.

## UI (`account_ui.py` = `AccountMixin`, `account_dialogs.py`)
The mixin owns the **one** worker (created on first use) and the login state
(`logged_out`/`restoring`/`logged_in`/`offline`); dialogs only `submit` and react to the
answer for **their own pending op** — never set the login state themselves. The startup
re-login runs **only when** `account/remembered` says a login is stored,
`_RESTORE_DELAY_MS` after construction, so a user who never logged in never loads
supabase. At exit the worker is stopped, and **terminated** if still inside a request.

**Tests:** `QSettings("IIASA", "CWatM_GUI")` is **always the registry** —
`setDefaultFormat()` (the `isolated_qsettings` fixture) does not apply to that
constructor, so a test must give its host an explicit ini file; and a test must close
its dialogs and flush `DeferredDelete` itself (`_dispose` in `test_account_ui.py`) —
leaving it to teardown order corrupted the heap (0xc0000374).

## Points for runs (S5)
The one hook is `run_ledger.add_entry` — it tells its **listeners** (`add_listener`)
about every recorded run; all three run paths (main, Windowed, Batch) record through it,
so a new run path is counted by recording it in the journal. `make_entry` also stores
**`timesteps`** (`settings_timesteps(content)`: StepStart..StepEnd read the way CWatM's
`Calendar` does — StepEnd a date **or** a count, `/ . -`, 2- or 4-digit year, last
duplicate wins). `account_runs.qualifies` = success + kind run/hidden/batch + a
`settings_hash`; `run_meta` sends only `settings_hash` + `timesteps`. Logged out → not
counted; logged in → `award_run`; a stored-but-unreachable login (offline/restoring) or a
failed send → **`account_pending.json`** (next to `run_ledger.json`), tagged with the user
and sent at **that** user's next login, capped 100 entries / 30 days. Award answers are
matched **in submit order** (`_award_fifo`) — only the mixin submits `award_run`.

**One point per distinct setup**: `settings_hash` = `run_ledger.settings_fingerprint`
— SHA-256 over the settings read like CWatM (comments/blank lines/spacing/line
order/key case ignored, last duplicate wins) with **`Title`, `PathOut` and every
`OUT_*` key left out**; `award_run` answers `same_settings` for a setup that already
earned a point (migration `…150000_leaderboard_badge_repeat_runs.sql`).

## Anonymous run locations
With consent (`profiles.share_locations` — an optional, **unticked** tick at Register, a
one-time question after an interactive `login`/`reset_password` for older accounts (**No**
the default; not asked after `confirm_signup`), a tick in the account window and in
Preferences ▸ Account; **default no everywhere**, `security.md` finding 4) every
qualifying run reports its **first gauge** (`run_ledger.settings_gauge`: first lon/lat
pair of `Gauges`, None for a map file or projected x/y; stored locally as
`entry["gauge"]`) via its **own** request `record_location` → rpc
`record_run_location`, **never inside `award_run`** (`run_meta` must not carry it —
tested). The server keeps only **counts per (0.001°-rounded lon/lat, month)** in
`run_locations`, which has **no user column** (migration `…160000_run_locations.sql`); a
per-user daily quota (`location_quota`) caps it at `game_config.location_daily_cap`.
**Only runs that earn a point are located**: the gauge rides along locally with the
award request and `record_location` is submitted only when the answer is `awarded`.

The user's **own location** (`profiles.location_lat/lon`, optional, both-or-none,
migration `…190000_user_location.sql`) is kept only to **0.5°** — rounded by the GUI
(`account_validation.round_location`) **and** enforced by the `profiles_round_location`
trigger (`20261001120000_user_location_half_degree.sql`); never on the leaderboard, on
the World Map only with the *Show my location on the world map* opt-in (no names).

## The Shop (migration `20261001130000_shop.sql`)
Points split in two, both **computed, never stored** — **earned** =
`sum(point_events)` (never goes down, decides badges; `get_my_status.total_points` keeps
this meaning for older GUIs) and **balance** = earned − `sum(purchases.price_paid)` −
recorded decay (shown on the account button, ranked on the leaderboard, spent in the
Shop). Spending **never removes a badge** nor moves a badge goal. Items + prices live on
the server (`shop_items`: `advanced` 20, `expert` 40 *requires* `advanced`; animals
(`20261007120000_shop_animals_v2.sql`): `trout` 10, `catfish` 30, `otter` 20,
`clownfish` 30, `beaver` 30, `octopus` 20, `bottle` 2). **`shop_buy` is the only
buyer** (per-user lock; checks the Breg badge `game_config.shop_required_badge`, not
owned yet, the `requires` item, the balance) and answers with the full status (`buy` ∈
`_STATUS_OPS`).

A row with `shop_items.reward` set is **never sold** (hidden from `get_shop_items`,
`shop_buy` answers `reward_only`) — it is given once by **`claim_reward(reward)`**: the
**mole** (`modflow_first_run`) for the first successful coupled-MODFLOW run.
`run_ledger.make_entry` marks `entry["modflow"]` (`settings_modflow`),
`AccountMixin._check_modflow_reward` claims it when logged in, else keeps
`account/reward_pending/…` and claims at the next login; `granted` selects the mole and
shows `_show_mole_reward`; logged out, a one-time popup says to log in. The server cannot
verify the run — it only opens an animal, no points.

`award_run` / `academy_complete_level` are thin wrappers adding `earned_points` +
`balance`; their logic lives in `_award_run_core` / `_academy_complete_level_core` —
change those, not the wrappers. GUI side: pure rules in `account_shop.py`;
`AccountMixin.owned_items()` / `level_allowed()` / `owned_animals()` drive the levels and
the sparkline animal; purchases are **cached** per user in QSettings
`account/owned/<user>` for `offline`/`restoring` — and while **no cache exists yet**
nothing is locked, so a stored Expert never flashes to Beginner during the re-login.

## Point decay (migration `20261001140000_point_decay.sql`)
The **balance** shrinks while CWatM GUI is not used — −3 % after the first week, then
−5 % of what is left every further week, rounded, **never below 5**; earned points and
badges never decay. "Used" = **a login**: after every `_LOGIN_OPS` answer the mixin
submits **`touch_activity`** (∈ `_STATUS_OPS`), which records the decay due
(`point_decay`) and restarts the clock (`profiles.last_active_at`); a recorded decay is
noted in the output box (`account_ui.decay_message`), and the account window states the
rule (`account_ui.DECAY_RULE` — the privacy test ties it to the notice). Status,
leaderboard and Shop show the **current** balance (`_current_balance`), and `shop_buy`
records the decay before charging. Percentages / minimum are `game_config` `decay_*`.

## Badge images
`assets/badges/<badge code>.png`, drawn by `badge_images.badge_pixmap(code, size,
faded, dpr)`: it **finds the medal in the square image** (middle row/column vs the corner
colour), crops and clips it round, so backgrounds/watermarks never show; a new river
needs only a PNG named after its code. No image → 🏅 + name. 88 px in the account window
(earned + next faded), 32 px in the leaderboard (ladder via `get_badges`). Present:
amazon, breg, danube, drava, elbe, ganges, inn, mekong, morava, nile, rhine, thames.

Note: the repo-root `supabase/` folder is importable as an empty namespace package; the
installed `supabase` library wins over it, but only while it is installed.
