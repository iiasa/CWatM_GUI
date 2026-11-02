# Accelerator-backed points/badges ledger (in progress)

Replaces the Supabase-backed CWatM account (`supabase/`) entirely - login
moves to IIASA's Accelerator platform, and this becomes the new backend for
points/badges/shop/leaderboard/academy progress. Everything resets: no
migration of existing Supabase accounts (decided explicitly - a clean
cutover).

## Why this shape

Accelerator has no general-purpose database service (confirmed against the
live API, 2026-11-02 - jobs are finite/timeout-bounded, no ingress/exposed
ports, no database-as-a-service). The Accelerator team's own suggestion,
given a simple read/write use case like this: write small immutable files
directly into project storage rather than trying to run a traditional
database.

**Ledger layout** (a dedicated Accelerator project, write access restricted
to the validator below - not yet created):

```
ledger/<uid>/runs/<run_uid>.json                          # one per successful run
ledger/<uid>/academy/level-<n>.json                        # one per academy level, pays once ever
ledger/<uid>/feature-runs/<feature>/<date>/<fingerprint>.json
ledger/<uid>/purchases/<item>.json                         # shop: skill levels, animals
ledger/_aggregates/leaderboard.json                        # periodically recomputed snapshot
ledger/_aggregates/field_test_record.json                  # global highscore
```

The filename *is* the dedup key for each event type (a run's own uid, an
academy level number, ...) - writing the same event twice is just
overwriting the same path with identical content, so "this can only count
once" falls out of the file layout instead of needing separate bookkeeping.

**The validator**: since the desktop GUI can't be trusted with direct write
access to the ledger (anyone could forge a "sign-me-up for 1000 points"
file), event files are written by a GitHub Actions workflow instead (free
for this public repo), triggered off small "claim" files the GUI writes
into a staging area it *does* have ordinary write access to. The workflow
checks each claim (mirroring what the old Supabase RPC functions already
validated) and only then writes the real event file, using a service-account
credential stored as a repo secret - no GitHub credential ever touches the
client. **Not yet built.**

## What's here now

- `award_run.py` - the first (and so far only) rule, a straight port of
  `supabase/migrations/20260928120100_gamification_functions.sql`'s
  `award_run()`: same status vocabulary (`awarded`/`duplicate`/`too_short`/
  `daily_limit`/`invalid_run_uid`), same thresholds
  (`points_per_run`/`min_timesteps`/`daily_run_cap` = 1/30/20). Pure logic -
  no Accelerator API calls, no file I/O; the caller supplies the claim and
  the user's existing ledger state. Run its tests with
  `pytest accelerator_backend/tests/` (not part of the main GUI's `pytest`
  run - `pytest.ini`'s `testpaths = tests` only, deliberately, since this is
  a separate component, same relationship `tauri-app/` has to the GUI).
  Deliberately not ported from the SQL: the email-confirmation check (no
  equivalent once Accelerator is the identity provider) and the Postgres
  advisory lock (no concurrent-claims-for-the-same-user scenario expected
  from a GitHub Actions run - revisit if that changes).

## Not yet built

- The GitHub Actions workflow itself (claim pickup, validation, the actual
  ledger write, the service-account credential).
- Everything beyond run-completion points: badges (river-badge tiers,
  feature badges, Field Test badge), the shop, leaderboard aggregation,
  academy progress, run locations.
- `who_am_i()` (`src/gui/utils/accelerator_auth.py`) - blocked on an
  Accelerator endpoint the team hasn't shipped yet (confirmed live,
  2026-11-02: exposing logged-in-user details on the aterm-cli routes,
  "next deployment cycle", no date given). Nothing here can be wired into
  the GUI's own login until that lands - this ledger logic was built ahead
  of it deliberately, since the rule logic itself doesn't depend on how the
  uid was obtained.
- The ledger Accelerator project itself (not yet created).
