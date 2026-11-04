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
client.

**How the write itself happens**: there is no confirmed working direct-
upload API into an Accelerator project (the S3-multipart endpoints in
accli's reference client are dead/deprecated, confirmed by the team live,
2026-10-28). The only confirmed way a new file lands in a project from
outside it is a dispatched job writing to `/mnt/wdrv`, which Accelerator's
own infrastructure then auto-uploads once the job finishes - the same
mechanism the Tauri client's `jobs.ts` already proved live for CWatM's own
output files. So the validator doesn't call an upload endpoint; it
dispatches a small job (as its own service-account identity) whose command
writes the event file and exits.

## What's here now

- `award_run.py` - a straight port of `supabase/migrations/
  20260928120100_gamification_functions.sql`'s `award_run()`: same status
  vocabulary (`awarded`/`duplicate`/`too_short`/`daily_limit`/
  `invalid_run_uid`), same thresholds (`points_per_run`/`min_timesteps`/
  `daily_run_cap` = 1/30/20). Deliberately not ported from the SQL: the
  email-confirmation check (no equivalent once Accelerator is the identity
  provider) and the Postgres advisory lock (no concurrent-claims-for-the-
  same-user scenario expected from a GitHub Actions run - revisit if that
  changes).
- `badges.py` - the river badges, a port of the same file's
  `_award_badges()`/`_total_points()`, with the final 12-tier ladder from
  `20260929140000_badge_ladder_v3.sql` (Breg 5 ... Amazonas 10000 -
  confirmed no later migration changes it). Checked against total
  **earned** points (never decreases), not the spendable balance.

`award_run.py`/`badges.py` are pure logic - no Accelerator API calls, no
file I/O; the caller supplies the claim/totals and the user's existing
ledger state. The rest talk to the real API:

- `config.py` - server URLs (duplicated from `src/gui/utils/
  accelerator_config.py` on purpose - a separate component, not meant to
  import from `src/gui/`).
- `service_account.py` - the validator's own Accelerator identity: exchanges
  the `ACCELERATOR_VALIDATOR_REFRESH_TOKEN` env var (a GitHub Actions
  secret) for an access token. No keyring, no persistence - a CI run is a
  fresh container every time.
- `dispatch.py` - writes a file into the ledger project by dispatching a
  small job (see "How the write itself happens" above). `build_write_command`
  is tested against a **real shell + real Python subprocess**
  (`test_round_trips_through_an_actual_shell_and_python`), not just
  reasoned about - the exact kind of escaping bug (`json.dumps` vs. a
  hand-written outer quoter) that broke the TypeScript version live once
  already. Reuses the proven `cwatm-docker-image` build rather than a
  separate minimal image, since a file write needs no CWatM-specific
  dependency and this image is already known to work.

Run the tests with `pytest accelerator_backend/tests/` (not part of the
main GUI's `pytest` run - `pytest.ini`'s `testpaths = tests` only,
deliberately, since this is a separate component, same relationship
`tauri-app/` has to the GUI).

## Resolved

- `who_am_i()` (`src/gui/utils/accelerator_auth.py`) - the team shipped
  `GET /v1/aterm-cli/user/me/` (2026-11-04) and it's confirmed live: a
  real device-flow login round-trip through login → access-token →
  identity lookup correctly returned `{'full_name': 'SMILOVIC Mikhail',
  'email': 'smilovic@iiasa.ac.at', 'roles': ['APP__VIEW'], 'uid': 315}`.
  The desktop GUI's own login can now be wired to a real `uid` - the one
  thing every piece of this ledger design was waiting on.

## Not yet built

- The GitHub Actions workflow itself that ties the pieces above together:
  claim pickup (the GUI's staging-area write), reading the user's
  existing ledger state, calling `award_run.decide()`/`badges.new_badges()`,
  dispatching the write.
- Confirming a dispatched write job actually succeeds (no result-marker
  polling wired in yet - `dispatch_write_job` returns a job id and nothing
  more).
- Everything beyond run-completion points and river badges: feature badges
  (ModFlow/pySnowClim/Glacier), the Field Test badge, the shop, leaderboard
  aggregation, academy progress, run locations.
- A real login dialog in the desktop GUI itself (`accelerator_auth.py` is
  not yet wired into any UI - see its module doc comment).
- The ledger Accelerator project and the validator's own Accelerator
  account (not yet created - blocked live on a 403 Forbidden creating a
  new Accelerator project, reported to the team, awaiting their reply) -
  see the setup checklist below.

## Setup checklist (for a human, not something Claude can do)

1. A new, empty Accelerator project for the ledger (e.g. `cwatm-points-ledger`).
2. A dedicated Accelerator account for the validator - separate from any
   personal login, added as a collaborator with write access to that
   project only.
3. That account's device-flow refresh token, added as a repo secret named
   `ACCELERATOR_VALIDATOR_REFRESH_TOKEN` (Settings → Secrets and variables
   → Actions, in `iiasa/CWatM_GUI`).
