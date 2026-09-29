# CWatM GUI - Supabase backend (gamification, step S1)

The server side of the optional CWatM GUI login: user accounts, points for full
CWatM runs, and the river badge ladder (Breg ... Amazonas). The GUI client
(steps S2-S5) talks to it with `supabase-py`.

```
supabase/
  migrations/
    20260928120000_gamification_schema.sql     tables, row level security, sign-up trigger
    20260928120100_gamification_functions.sql  rpc API (award_run, get_my_status, ...)
    20260928120200_gamification_seed.sql       game rules + badge ladder
    20260928140000_privacy_consent.sql         consent version + time in profiles;
                                               sign-up without privacy_version refused
    20260928150000_leaderboard_badge_repeat_runs.sql
                                               get_leaderboard + top_badge; award_run:
                                               one point per settings_hash (same_settings)
    20260928160000_run_locations.sql           consent profiles.share_locations; the
                                               ANONYMOUS run_locations counts (no user);
                                               record_run_location(); location_quota
    20260928170000_run_locations_precision.sql locations rounded to 0.001° (~100 m)
    20260928180000_world_map.sql               get_run_locations(): public totals per
                                               place (lon, lat, runs) for Info ▸ World Map
    20260928190000_user_location.sql           optional own location in profiles
                                               (location_lat/lon, both or none)
    20260928200000_user_locations_map.sql      show_location_on_map (opt-in, default
                                               off); get_user_locations(): public, no
                                               names, 0.01°, counted per place
    20260928210000_badge_ladder_v2.sql         11 badges at 5 … 10000 points (Breg …
                                               Amazonas); earned badges re-evaluated
    20260929120000_signup_visibility_choices.sql
                                               sign-up stores show_on_leaderboard +
                                               show_location_on_map (Register ticks,
                                               pre-ticked in the GUI)
    20260929130000_academy_progress.sql        profiles.academy_completed (CWatM
                                               Academy progress, rpc-only);
                                               academy_complete_level() = 5 points
                                               per level once (source 'training');
                                               academy_reset(); get_my_status
                                               carries academy_completed
    20260929140000_badge_ladder_v3.sql         12 badges at 5, 15, 30, 50, 100,
                                               200, 400, 800, 1500, 3000, 5000,
                                               10000 points (Ganges back, between
                                               Rhine and Danube); re-evaluated
  functions/
    login-with-username/index.ts   username + password -> session
    delete-account/index.ts        delete the caller's account (password re-check)
  templates/
    confirm_signup.html            6-digit code instead of a link
    reset_password.html            6-digit code instead of a link
```

## Rules that must stay true

- **The service-role / secret key never goes into the GUI.** The client holds only
  the project URL and the **anon / publishable** key. Everything a client may do is
  enforced by row level security and function grants.
- **Points are written only by `award_run()`** (security definer). No table has an
  insert/update/delete policy for clients; the server decides how many points a
  run is worth (`game_config`).
- **A run counts once**: `point_events` is unique on `(user_id, source, source_ref)`
  and `source_ref` is the Journal-of-Runs `uid`.
- **No paths or settings content leave the machine**: `award_run` keeps only
  `gui_version`, `kind`, `timesteps`, `duration_s` from the metadata it receives.

## Client API

| Call | Who | Returns |
|------|-----|---------|
| `auth.sign_up(email, password, options.data={username, privacy_version, full_name?, country?, institute?})` | anon | creates the user; the trigger creates the profile (fails if the username is taken/invalid **or `privacy_version` is missing**) |
| `auth.verify_otp(email, token, type="signup")` | anon | confirms the email with the 6-digit code |
| `auth.sign_in_with_password(email, password)` | anon | session (login with email) |
| Edge Function `login-with-username` `{username, password}` | anon | `{session}` (login with username) → `auth.set_session(...)` |
| `auth.reset_password_for_email(email)` → `verify_otp(type="recovery")` → `update_user(password)` | anon | password reset by code |
| rpc `username_available(p_username)` | anon | bool |
| rpc `award_run(p_run_uid, p_meta)` | user | `{status: awarded\|duplicate\|same_settings\|too_short\|daily_limit\|email_not_confirmed\|invalid_run_uid, total_points, new_badges, ...}` — `p_meta.settings_hash` (SHA-256 hex of the setup) makes it one point per distinct setup |
| rpc `record_run_location(p_lon, p_lat)` | user | `{status: recorded\|no_consent\|invalid_location\|daily_limit}` — adds 1 to the anonymous count of (round(lon,2), round(lat,2), month); stores **no user** |
| rpc `get_my_status()` | user | `{profile, total_points, badges, next_badge}` |
| rpc `export_my_data()` | user | everything stored about the user (GDPR export) |
| rpc `get_leaderboard(p_limit)` | anon | opt-in users only: rank, username, country, points, top_badge |
| `from("profiles").update({...}).eq("id", uid)` | user | edit own username/name/country/institute/leaderboard flag |
| Edge Function `delete-account` `{password}` + Bearer token | user | deletes the account and all its data |

A username is 3-30 characters (`A-Z a-z 0-9 _ . -`, starting alphanumeric) and never
contains `@` - so the GUI tells "username" from "email" by the `@`.

## Setting up a project (once per project: `dev`, then `prod`)

1. **Create the project** at <https://supabase.com/dashboard>, region
   **Central EU (Frankfurt)** (personal data, GDPR).
   A free project **pauses after ~1 week without traffic** - use the **Pro** plan for
   `prod`, or login breaks for everyone while it sleeps.
2. **Authentication ▸ Sign In / Providers ▸ Email**: enabled, *Confirm email* **on**,
   minimum password length **8**. Leave anonymous sign-ins and all other providers off.
3. **Authentication ▸ Emails ▸ SMTP settings**: configure a real SMTP server (IIASA's
   or Resend/SendGrid). The built-in sender is for testing only and is heavily
   rate-limited.
4. **Authentication ▸ Emails ▸ Templates**: paste `templates/confirm_signup.html`
   into *Confirm signup* and `templates/reset_password.html` into *Reset password*
   (subjects e.g. "Your CWatM confirmation code" / "Your CWatM password reset code").
   A desktop app cannot catch a link, so the emails carry a code.
5. **Apply the database + functions** with the Supabase CLI (no install needed, `npx`
   fetches it; Docker is *not* needed for these commands):

   ```powershell
   cd P:\watmodel\cwatmpublic\gui
   npx supabase login
   npx supabase link --project-ref <project-ref>
   npx supabase db push
   npx supabase functions deploy login-with-username --no-verify-jwt
   npx supabase functions deploy delete-account --no-verify-jwt
   ```
   (`supabase link` writes `supabase/.temp/`, which is git-ignored.)
6. **Note for the GUI** (step S3): *Project Settings ▸ API* → the project URL and the
   **anon / publishable** key. These two go into the GUI; nothing else.

## Tuning without a GUI release

`game_config` and `badges` are plain data (SQL editor or Table editor):

```sql
update public.game_config set value = '100' where key = 'min_timesteps';
insert into public.badges (code, name, river_length_km, points_required, sort_order)
values ('volga', 'Volga', 3530, 350, 99);
```

| key | default | meaning |
|-----|---------|---------|
| `points_per_run` | 1 | points for one full run |
| `min_timesteps` | 30 | a run must cover at least this many timesteps (0 = off) |
| `daily_run_cap` | 20 | max run awards per user per 24 h (0 = off) |
| `login_max_failures` / `login_window_minutes` | 10 / 15 | username-login throttle |

Changing a badge threshold does not take a badge away from anyone; users reaching a
lowered threshold get it with their next award.

## Open points to verify on the first real project

- Whether Auth's per-IP rate limit honours the `X-Forwarded-For` the
  `login-with-username` function passes on. If not, every username login counts
  against the function's own IP; the per-username throttle in `login_attempts` is the
  protection that does not depend on it.
- `SUPABASE_ANON_KEY` is provided to Edge Functions automatically. If the project
  has only the new publishable/secret keys, check that it is still set.
