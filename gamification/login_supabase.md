# CWatM GUI login with Supabase

Step 1 of the CWatM gamification: an **optional** user login in the GUI. A logged-in
user gets **1 point per full CWatM run**, and points earn **river badges** from the
Breg to the Amazonas. Later, the trainings (<https://cwatm.iiasa.ac.at/71_offline.html>)
will give extra points and unlock features.

This file records everything done for the login so far, and what is still to do.
Background: `CLAUDE.md` (section *Gamification backend*) and `supabase/README.md`.

> **No secrets in this file or in the repo.** Passwords, the database password and the
> Gmail app password stay in private notes (`game1.txt`, `test_pw.txt` are git-ignored).
> The project URL and the **publishable** key are public by design and are in the code.

## Status

| Step | What | Status |
|------|------|--------|
| S1 | Supabase backend: tables, security, functions, emails | ✅ done, live |
| S3 | Account layer in the GUI (no UI): client, worker, token storage | ✅ done, tested live |
| S2 | Packaging: libraries in `requirements*.txt` and in the exe | ✅ done, bundle verified |
| S4 | UI: login dialog, account indicator, profile window, Preferences page | ✅ done, tested live (not yet in a built exe) |
| S5 | Award points after a full run (hook in the Journal of Runs), offline queue | ✅ done, tested live (not yet in a built exe) |
| S6 | Privacy notice, data export, account deletion in the UI | ✅ done - notice is a **draft** for IIASA review; migration to push |
| S7 | Docs (Features/FAQ/Internals), more tests, frozen login check | open |

## Decisions taken

- **Login by username *or* email** + password. Supabase only knows email logins, so a
  username login goes through a server-side Edge Function that looks up the email; no
  email address is ever exposed to a client.
- **Codes, not links**: confirmation and password-reset emails carry a 6-digit code
  (`{{ .Token }}`) that the user types into the GUI; a desktop app cannot catch a link.
- **Server decides the points**: the client only reports "run X finished" plus
  non-identifying facts; the server function `award_run` checks the rules and writes
  the points. No client can write points directly.
- **One run counts once**: keyed on the Journal-of-Runs `uid` of the run.
- **Rules are data**: points per run, minimum timesteps, daily cap, badge thresholds
  live in tables and can be changed without a GUI release.
- **No personal paths/settings leave the machine**: the server keeps only
  `gui_version`, `kind`, `timesteps`, `duration_s` of a run.
- **Login remembered in the OS keyring** (Windows Credential Manager), never in
  QSettings or a file - and only the refresh token.
- **Region EU (Frankfurt)** because personal data (GDPR, IIASA in Austria).

## S1 - Supabase project setup (done)

### Dashboard (supabase.com)

1. **Organization** `CWatM`, **project** `CWatM GUI`, region Central EU (Frankfurt).
   Project ref `heseqywpazkdvmnieuqn`, URL `https://heseqywpazkdvmnieuqn.supabase.co`.
   *Enable automatic RLS* on (a safety net; the migrations enable RLS themselves).
   Note: a free project **pauses after ~1 week without traffic** - use the Pro plan for
   production.
2. **Authentication ▸ Sign In / Providers** (left icon bar ▸ Authentication ▸
   *Configuration* ▸ Sign In / Providers):
   - User Signups: new sign-ups **on**, *Confirm email* **on**, anonymous sign-ins **off**.
   - Auth Providers ▸ **Email**: enabled, minimum password length **8**, *Email OTP
     Expiration* **3600**, *Email OTP Length* **6**. All other providers off.
3. **Authentication ▸ Emails ▸ SMTP Settings**: *Enable custom SMTP* on.
   For testing: Gmail - host `smtp.gmail.com`, port `587`, sender = username = the
   Gmail address, password = a Gmail **app password** (Google account ▸ Security ▸
   2-Step Verification on ▸ *App passwords*). The warning *"designed for sending
   personal … email"* is expected for Gmail - save anyway. Mails may land in spam
   (GMX / IIASA flagged them). **For production use a transactional sender** (IIASA
   SMTP, Resend, Brevo).
4. **Authentication ▸ Rate Limits**: emails per hour raised to ~100.
5. **Authentication ▸ Emails ▸ Templates**:
   - *Confirm signup* - subject `Your CWatM confirmation code`, body
     `supabase/templates/confirm_signup.html`.
   - *Reset password* - subject `Your CWatM password reset code`, body
     `supabase/templates/reset_password.html`.
   Both must contain `{{ .Token }}` and **not** `{{ .ConfirmationURL }}`.
   (Pitfall seen: the reset text ended up in *Confirm signup* - the code still worked,
   but the mail said "password reset". Check subject + body of both.)
6. Delete any user created from the dashboard **before** the migrations (it would have
   no profile). After the migrations, *Add user* / *Send invitation* in the dashboard
   **fail by design** ("Database error saving new user") - every account needs a
   username, so accounts are created from the GUI only.

### Database + functions (Supabase CLI via `npx`, no install)

```powershell
cd P:\watmodel\cwatmpublic\gui
npx supabase login
npx supabase link --project-ref heseqywpazkdvmnieuqn     # asks for the database password
npx supabase db push                                       # applies the 3 migrations
npx supabase functions deploy login-with-username --no-verify-jwt
npx supabase functions deploy delete-account --no-verify-jwt
```

*"WARNING: Docker is not running"* can be ignored - Docker is only needed for a local
Supabase. If a function deploy fails for lack of Docker, add `--use-api`.

### What is on the server (`supabase/` in the repo)

| File | Content |
|------|---------|
| `migrations/20260928120000_gamification_schema.sql` | tables `profiles`, `game_config`, `badges`, `point_events`, `user_badges`, `login_attempts`; row level security; sign-up trigger creating the profile |
| `migrations/20260928120100_gamification_functions.sql` | `username_available`, `award_run`, `get_my_status`, `export_my_data`, `get_leaderboard`, login helpers |
| `migrations/20260928120200_gamification_seed.sql` | rules (1 point/run, ≥ 30 timesteps, ≤ 20 awards/24 h, login throttle 10 failures/15 min) and the first badge ladder (18 rivers, Breg 1 … Amazonas 3000) - **replaced** by `20260928210000_badge_ladder_v2.sql` (11 badges, 5 … 10000, see *Badge ladder* below) |
| `functions/login-with-username/index.ts` | username + password → session; same answer for unknown user and wrong password; per-username throttle |
| `functions/delete-account/index.ts` | deletes the account and all its data after re-checking the password |
| `templates/*.html` | the two code emails |

Security in one line each:
- clients read only their own profile/points/badges; badges and rules are public;
- clients edit only `username`, `full_name`, `country`, `institute`,
  `show_on_leaderboard` of their own profile;
- nobody but the server functions writes points or badges;
- the service-role / secret key never leaves the server.

### Tuning (SQL editor or Table editor, no release needed)

```sql
update public.game_config set value = '100' where key = 'min_timesteps';
insert into public.badges (code, name, river_length_km, points_required, sort_order)
values ('volga', 'Volga', 3530, 350, 99);
```

## S3 - Account layer in the GUI (done)

New modules in `src/gui/utils/`:

| Module | Role |
|--------|------|
| `account_config.py` | project URL + publishable key; env overrides `CWATM_GUI_SUPABASE_URL` / `CWATM_GUI_SUPABASE_KEY` (e.g. for a dev project) |
| `account_validation.py` | pure input rules (username 3-30 chars `A-Z a-z 0-9 _ . -`, no `@`; password 8-72 bytes; 6-digit code) - must match the server constraint |
| `account_store.py` | refresh token in the OS keyring; never raises (no keyring = login not remembered) |
| `account_client.py` | **the only importer of `supabase`**: register, confirm code, resend, login (username or email, told apart by `@`), restore from keyring, logout, password reset, status, profile edit, `award_run`, leaderboard, export, delete account. Errors → `AccountError(code, message)` |
| `account_worker.py` | `AccountWorker(QThread)`: `submit(op, …)` → signals `succeeded(op, result)` / `failed(op, code, message)` / `busy(bool)`. All network work off the GUI thread |

Rules that keep it working:
- never call `AccountClient` from the GUI thread - only through `AccountWorker`;
- `supabase`/`keyring` are never imported on the startup path
  (`tools/check_invariants.py` enforces it);
- automatic token refresh is off; the session is refreshed on demand before each call,
  and every rotated refresh token is saved to the keyring again.

Import cost: loading the supabase stack takes 15-27 s **from the P: share** (pandas
alone takes 32 s there) - much less from a local install. It only ever happens on the
worker thread; the automatic re-login should therefore start in the background right
after the window opens (S4).

### Tests done

- `tests/test_account.py` - 42 tests, no network (validation, error mapping, keyring
  token rotation, username vs email login, worker op allow-list).
- **Live, against the project**:
  - read-only: username check, badges (18), rules (5), leaderboard;
  - protected tables and `award_run` refused without login;
  - unknown username → `invalid_credentials`.
- **End-to-end with the test account `Blabla`** (kept for S4 testing; the password is
  in the private `test_pw.txt`):
  - register → code email → confirm;
  - login by username (case-insensitive) and by email; wrong password rejected;
  - duplicate username rejected; profile edit;
  - automatic re-login from the keyring; logout clears the keyring;
  - `award_run`: too short → rejected; invalid id → rejected; full run → +1 point +
    **Breg** badge; same run again → `duplicate`; a file path sent along was discarded
    by the server.

## S2 - Packaging (done)

- `requirements.txt` / `requirements_linux.txt`: `supabase==2.31.0` (+ its sub-packages)
  and `keyring==25.7.0` (+ `pywin32-ctypes` on Windows, `SecretStorage`/`jeepney` on
  Linux), all pinned. Installed into `venv\` without changing any existing pin.
- `cwatm_gui_dir.spec`: block `account_*` - the supabase packages are collected for the
  **GUI exe only**, and excluded from `CWatM_model.exe`.
  **keyring has no PyInstaller hook**: its backends, its dist metadata (backend
  discovery reads entry points) and `win32ctypes` are collected explicitly - without
  them the frozen exe would silently never remember a login.
- Build: `build_release.ps1 -Steps venv,sync,build -ForceVenv` (`-ForceVenv` because the
  venv changed). Verified in the build of 2026-09-28 by listing both exes' PYZ archives:
  `CWatM_GUI.exe` holds supabase, supabase_auth, postgrest, realtime, websockets, jwt,
  `keyring.backends.Windows`, `win32ctypes…win32cred` and the account modules, and the
  keyring dist metadata lists the `Windows` backend; `CWatM_model.exe` holds none of the
  account code. pydantic had slipped into the model exe (an optional import of some
  model-side package) and is now excluded there - takes effect with the next build.

## S4 - User interface (done)

| Where | What |
|-------|------|
| Menu bar, left of ⋮ | **Account button**: *Log in* · *Logging in…* · *Blabla · 1 pt* (tooltip: badges, next badge) · *Account (offline)* (click = retry) |
| Login dialog | tabs **Log in** (username or email, *stay logged in*) · **Register** (username, email, password ×2, optional name/country/institute, privacy text + required tick) → **code step** (Confirm / Send the code again) · **Forgot password** (email → code + new password). Logging in with an unconfirmed email jumps to the code step |
| Account window | username + email, points, progress bar to the next badge, earned badges, profile edit (username/name/country/institute), leaderboard opt-in, **Export my data…** (JSON), **Delete account…** (warning + password), **Log out** |
| Preferences ▸ Account | login state + *Stay logged in on this computer* (unticking drops the stored login at once) |
| Startup | re-login in the background 2.5 s after the window is built - **only if** a login was stored (`account/remembered`), so users who never log in never load supabase |

Files: `src/gui/components/account_ui.py` (`AccountMixin`: button, worker, state),
`src/gui/widgets/account_dialogs.py` (the two windows), hooks in `main_window.py`
(mixin, `_init_account`, worker stop in `closeEvent`), `menu_builder.py` (corner
container + button style), `preferences_window.py` (Account page).

Pitfalls met (and fixed):
- `QMenuBar` measures its corner widget only when set/shown - the button was elided to
  "Bla… pt" until the corner is re-shown after each text change.
- Dialogs open at least as large as their content (a small screen cut off the register
  form).
- Enter in a field + a default button submitted a request twice - the buttons have no
  default role.
- At exit a worker still inside a request is terminated (a running QThread destroyed
  with its parent aborts the process).
- Tests: `QSettings("IIASA", "CWatM_GUI")` always writes the **registry** (the
  `isolated_qsettings` fixture does not change that constructor); the account tests use
  an explicit ini file. Qt objects are closed and deleted explicitly in the tests -
  leaving it to teardown order corrupted the heap.

Tests: `tests/test_account_ui.py` (15, fake worker) + `tests/test_account.py` (42).
**Live** with the real main window and the real worker against the project: login as
`Blabla` via the dialog (21 s the first time from the P: share - the supabase import),
button *Blabla · 1 pt*, account window (1 / 5 points to Thames, 🏅 Breg), logout.

Open for S4: the new texts are English only (rows for
`translations/ui_strings_languages.csv`), and the account UI is not yet in a built exe.

## S5 - Points for runs (done)

How a run earns a point:

1. A run ends; the main run, a Windowed Run and each Batch scenario are all recorded in
   the **Journal of Runs** (`run_ledger.add_entry`). That is the **one hook**: the
   journal now tells its listeners about every recorded run, and the account part of
   the main window listens.
2. The journal entry now also holds **`timesteps`**: StepStart..StepEnd of the settings
   the run used, read the way CWatM reads them (StepEnd a date or a timestep count;
   `/ . -`; 2- or 4-digit year; a duplicate key counts by its last value).
3. It counts if it **succeeded** (a stopped or failed run does not) and it is a main
   run, Windowed Run or Batch scenario, and **Preferences ▸ Account ▸ Count my full
   CWatM runs** is on (default on).
4. **Logged in** → sent to the server (`award_run`) with only GUI version, run kind,
   timesteps and run time. The server decides: awarded / too short (< 30 timesteps) /
   daily limit (20) / duplicate.
5. The answer is written to the **output box** and the status bar:
   `CWatM account: +1 point for this run (total 2).`, a new badge as
   `CWatM account: 🏅 new badge - Thames!`, and the reason when a run does not count.
   The menu-bar button updates (`Blabla · 2 pt`).

Not logged in → the run does not count (decided: no points for runs before the login).

**Offline queue** (`account_pending.json`, next to `run_ledger.json` in the Run History
folder): a full run that could not be sent - the stored login could not be reached, or
the send failed (no connection, server error) - is kept **for that user** and sent at
their next login, or as soon as the server answers again. It is never credited to
another user logging in on the same computer. At most 100 runs, 30 days.

Batch runs: **each successful scenario counts** (they are full runs; the daily cap of
20 keeps a big batch from farming points).

Files: `src/gui/utils/account_runs.py` (new: rules, metadata, queue),
`src/gui/utils/run_ledger.py` (listeners, `settings_timesteps`, `timesteps` in the
entry), `src/gui/components/account_ui.py` (listener, sending, answers, notes),
`preferences_window.py` (*Count my full CWatM runs*).

Tests: `tests/test_account_runs.py` (34: timestep counting incl. the CWatM variants,
listener hook, which runs count, metadata whitelist, queue per user / expiry / corrupt
file) and 14 more in `tests/test_account_ui.py` (sending, not sending, notes, queue at
next login, other user gets nothing, answers matched in order). All account tests plus
the existing journal tests: 135 passed.
**Live** (real main window + worker against the project, journal in a temp folder):
a recorded one-year run → `Blabla` 1 → **2 points**, button `Blabla · 2 pt`, output
box `+1 point for this run (total 2)`; a 10-day run → "too short"; a failed run → not
sent.

Still to try in the real GUI: a real CWatM run while logged in (the run paths
themselves are unchanged - they already record into the journal).

## S6 - Privacy (done, notice is a draft)

- **Privacy notice** `documentation/CWatM_Account_Privacy.md` (version
  `2026-09-28-draft`): who is responsible, what is stored and why (table), what stays
  on the computer, legal basis, processors, retention, rights (with the button for
  each), age 16+, changes. It describes exactly what the code does. Marked **DRAFT**:
  the *[bracketed]* parts must be filled in by IIASA - contact address, IIASA's legal
  position as an international organisation, the Supabase data processing agreement,
  the email provider, backup retention, the supervisory authority.
- Shown via **Help ▸ CWatM account privacy**, the **Register** tab (*Read the full
  privacy notice*, tick box *I agree that these data are stored (privacy notice)*) and
  the **account window**. Bundled into the exe (spec datas).
- **Consent is recorded**: every sign-up sends `PRIVACY_VERSION`; the new migration
  `supabase/migrations/20260928140000_privacy_consent.sql` stores version + time in the
  profile (so it is part of *Export my data*) and **refuses a sign-up without it** - the
  tick cannot be skipped by calling the API directly. `Blabla` (registered before)
  keeps an empty consent field.
- Export and delete were already in the account window (S4).
- `tests/test_account_privacy.py` (7): the notice's version line = the version sent;
  draft marker consistent; offline-queue file name and 30 days as in the code; every
  field a run sends is named in the notice; bundled in the spec; registering without
  consent is refused and with consent sends the version.

**To do on the server** (needs the database password, so it is your step):
```powershell
cd P:\watmodel\cwatmpublic\gui
npx supabase db push        # applies 20260928140000_privacy_consent.sql
```
When the notice is approved: change the version (e.g. `2026-11-01`) in **both** the
notice's *Version* line and `account_config.PRIVACY_VERSION`, remove the DRAFT box.

## Leaderboard + one point per setup (done in the code; migration to push)

**Leaderboard**: **Info ▸ Leaderboard** - the menu item exists **only while logged
in**. The window lists the users who switched on *Show me on the leaderboard* (account
window): rank, user, country, **highest badge**, points; your own row bold and
highlighted, or a hint how to take part; Refresh. The server's `get_leaderboard` now
also returns each user's highest badge.

**Same settings again = no point.** Every run's journal entry gets a **fingerprint**
of the settings it used (SHA-256 one-way hash, `run_ledger.settings_fingerprint`), and
the server awards **one point per distinct setup per user**; a repeat answers
`same_settings` and the output box says *"these settings already earned a point -
change the model setup (not only Title, PathOut or the outputs) to earn another."*
What counts as the same setup - read the way CWatM reads the file:

| Same setup (no new point) | New setup (new point) |
|---------------------------|-----------------------|
| comments, blank lines, spacing, key case, line order changed | a parameter changed (e.g. `SnowFactor`) |
| `Title` changed | the period (`StepStart` / `StepEnd`) changed |
| `PathOut` changed | an `[OPTIONS]` switch changed |
| output keys (`OUT_*`) changed | the input data (`PathRoot`, maps, …) changed |

Only the hash leaves the computer - the privacy notice, the register text and the
Preferences tooltip now say so (and `test_account_privacy.py` checks the notice names
it). Runs counted before this change have no fingerprint, so a setup counted then can
earn one more point once.

Files: `supabase/migrations/20260928150000_leaderboard_badge_repeat_runs.sql`,
`run_ledger.py` (`settings_fingerprint`, `settings_hash` in the entry),
`account_runs.py` (sent in `run_meta`), `account_ui.py` (message, Info item
visibility, `open_leaderboard`), `account_dialogs.py` (`LeaderboardWindow`),
`menu_builder.py` (Info ▸ Leaderboard). Tests: the same/new-setup cases above in
`test_account_runs.py`, leaderboard window + menu visibility + message in
`test_account_ui.py`; 165 account/journal tests pass.

## Anonymous run locations (where CWatM is run, and how often)

**What**: for every run that **earns a badge point** (main / Windowed / Batch; server answer `awarded`) of a user who agreed, the
**first gauge** (first lon/lat pair of `Gauges =`) is reported. Nothing is sent when
`Gauges` is a map file or not geographic lon/lat (e.g. a UTM x/y grid).

**Anonymous by construction**:
- stored in `run_locations`, which has **no user column** - only
  `lon, lat, month, runs` (a **count**, not one row per run, so the time of a location
  cannot be matched to the time of a points row);
- rounded to **0.001° (~100 m)** on the server;
- sent as its **own** request (`record_run_location`), never together with the points;
- a per-user **daily quota** (default 50, `game_config.location_daily_cap`) stops
  flooding - it stores user + day + a number, never a place.

**Consent** (`profiles.share_locations` + time):
- **Register**: a **required** tick *"I agree that the location of my runs (first gauge,
  ~100 m) is recorded anonymously"* - **ticked by default**;
- **older accounts** (e.g. `Blabla`): asked **once per user and computer** after an
  interactive login (not at the silent re-login at startup); **Yes** preselected;
- **account window** and **Preferences ▸ Account**: *Record the location of my runs
  anonymously* - switch off/on at any time (Preferences: ticked by default, greyed out
  while logged out, since the choice is stored in the account).

Rounding: **0.001° (~100 m)** since migration `20260928170000_run_locations_precision.sql`
(the first test entry from before keeps its 0.01° value).

**Privacy notice** → version `2026-09-28-draft2`, new section *Anonymous run
locations*: what is sent, why it cannot be traced back, and that anonymous counts
cannot be exported or deleted per person (and stay after an account is deleted).

**The dataset** (dashboard ▸ SQL Editor):
```sql
-- where, and how often, over all months
select lon, lat, sum(runs) as runs
from public.run_locations
group by lon, lat
order by runs desc;

-- per month
select month, count(*) as places, sum(runs) as runs
from public.run_locations
group by month order by month;
```

Files: `supabase/migrations/20260928160000_run_locations.sql`, `run_ledger.py`
(`settings_gauge`, `gauge` in the journal entry), `account_runs.py` (`location_of`),
`account_client.py` (`record_location`, `share_locations` in register/profile),
`account_ui.py` (sending, the one-time question), `account_dialogs.py` (register tick,
account-window tick), the privacy notice. Tests: 28 new (gauge parsing incl. map files
and UTM, separate request, consent, question once, register tick, notice text).

**Only runs that earn a badge point** (since 2026-09-28 evening): the location is sent
only after the server answered the run's points request with `awarded` - long enough
(≥ 30 timesteps), a new setup, within the daily limit, email confirmed. Until then the
gauge stays local (with the request, or in the offline queue). *Same settings*, *too
short*, *daily limit* and *duplicate* runs are never located; with *Count my full CWatM
runs* off, no run is located. (The two map points recorded before this rule cannot be
checked afterwards - nothing links them to runs.)

## Own location (optional profile data)

Latitude/longitude of the **user**, like name, country and institute: entered when
registering (optional) or in the account window, stored to 0.001°, both or none
(migration `20260928190000_user_location.sql`). Personal data - linked to the account,
shown to the user only (not on the leaderboard or the world map), part of *Export my
data*, deleted with the account; emptying both fields removes it. Example: `Blabla` →
lat 48.067, lon 16.357. Privacy notice → `2026-09-28-draft4`.

## World map - window layout and the two views (2026-09-28 evening)

- **No Close / Refresh buttons**; the window has a **maximise** button (a real
  top-level window).
- Shows only **80°N - 60°S** (beyond covered grey - also hides the black polar bands
  of the OSM WMS); pan and zoom stay inside it.
- **First size**: the map area is 1024 × 427 px - exactly −180…180° × 90°N…60°S at
  Leaflet EPSG:4326 zoom 1 (1024 px per 360°); afterwards freely resizable.
- Two buttons below the map, **one active at a time**:
  - **CWatM runs** - blue circles, the anonymous run-location totals (only runs that
    earned a point);
  - **User location** - orange circles, the own locations of users who ticked **Show
    my location on the world map** in the account window (**off by default**; the own
    location is personal data), **without names**, rounded to **0.01° (~1 km)**,
    several users at one place counted as one bigger circle.
  The heading and the explanation text change with the view.
- Server: `get_user_locations()` (migration `20260928200000_user_locations_map.sql`),
  public like `get_run_locations()`.
- Privacy notice → `2026-09-28-draft5`.

## World map (Info ▸ World Map)

Tooltip *"Shows a world map with points where users applied CWatM"*. **Visible to
everyone** - no login needed (the data is anonymous).

- A zoomable world map (folium / Leaflet, EPSG:4326, like Show Basin) with the basemap
  chosen in **Preferences ▸ Display ▸ Default openstreet map** (OSM, Topographic,
  Terrain, Dark).
- One **blue circle** per place from the anonymous run-location counts; the more runs
  at the same place, the **bigger the circle**: radius `4 + 3·√runs` screen pixels
  (1 run 7 px, 4 → 10, 25 → 19, 100 → 34, max 40) - the circle *area* grows with the
  runs, so one busy place does not cover the map; the radius stays the same when
  zooming. Biggest circles are drawn first, so small ones stay on top. Hover: number of
  runs and lon/lat. **Refresh** reloads.
- Data: new public server function `get_run_locations()` (migration
  `20260928180000_world_map.sql`) - totals per place summed over all months; the table
  itself stays closed.
- Privacy notice → `2026-09-28-draft3`: the totals are **shown to every GUI user** on
  this map.

Files: `src/gui/widgets/world_map_window.py`, `menu_builder.py` (Info ▸ World Map),
`account_ui.py` (`open_world_map`), `account_client.py` (`get_run_locations`),
`tests/test_world_map.py`.

## Badge ladder (since 2026-09-28, migration `20260928210000_badge_ladder_v2.sql`)

| Points | Badge | Points | Badge |
|-------:|-------|-------:|-------|
| 5 | Breg | 500 | Rhine |
| 10 | Thames | 1000 | Danube |
| 25 | Morava | 2500 | Mekong |
| 50 | Inn | 5000 | Nile |
| 100 | Drava | 10000 | Amazonas |
| 250 | Elbe | | |

1 point per run that earns one (full run, new setup, ≥ 30 timesteps, ≤ 20 per day).
Dropped from the first ladder: Ganges, Zambezi, Indus, Mississippi, Congo, Yellow River,
Yangtze. Earned badges were re-evaluated when the ladder changed (a badge no longer
reached is removed, a newly reached one awarded). The ladder is plain data in
`public.badges` - rivers and thresholds can be changed with SQL, no GUI release.

## Badge images

The badges are shown as **medal images**: 88 px in the account window (every earned
badge, plus the next one faded with *next - N more points*) and 32 px in the
leaderboard's *Highest badge* column. **Clicking an earned badge** in the account window
opens it large (`BadgeViewer`, 320 px, with its name and *Earned on …*); a click or Esc
closes it. The faded next badge is not clickable. Files: `assets/badges/<code>.png` - so far
`breg`, `thames`, `morava`, `inn` (copied from `badges/badge1-4.png`). The code
finds the round medal inside each square picture by itself and clips it round, so the
white or dark background and the corner watermark never show, in any colour mode.
**A new badge picture = a PNG named after the badge code** (see the badge table in
`supabase/migrations/20260928120200_gamification_seed.sql`: `drava`, `elbe`, `rhine`,
…) in `assets/badges/` - nothing else to change. A badge without a picture shows 🏅.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "The CWatM account libraries (supabase, keyring) are not installed for the Python running this GUI" (before 2026-09-28: *"The CWatM account server reported an error"*, gui.log: `cannot import name 'ClientOptions' from 'supabase' (unknown location)`) | The GUI runs with a Python **without** the account libraries - e.g. the system `C:\Python312\python.exe` instead of `venv\`. Python then imports the repo's `supabase/` folder (the server files) as an empty package | Start the GUI with `venv\Scripts\python.exe cwatm_gui.py`, or install the two libraries into that Python: `"<python>" -m pip install supabase keyring` (the message names the Python). A stored login is kept meanwhile |
| Any other account error | see `%LOCALAPPDATA%\CWatM_GUI\gui.log` - every failure is logged there with its technical detail (`account_worker` / `account_client` lines) | |

## Next steps

**S7** - Features/FAQ/Internals docs; translations of the new texts
(`translations/ui_strings_languages.csv`); a build with S4 + S5 and the login / a run
checked in the exe.

**Before real users**
- Pro plan, so the project does not pause.
- A transactional SMTP sender instead of Gmail.
- A separate `prod` project, with `dev` kept for testing.
