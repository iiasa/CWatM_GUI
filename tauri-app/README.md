# CWatM Accelerator Client (Tauri)

A Tauri-based client, separate from the existing PySide6 `CWatM_GUI` app,
that logs into IIASA's Accelerator platform (device flow) and browses a
project's files. Runs both as a native desktop app and in a plain
browser from the same code.

**Milestone 1**: login + file browsing, verified end-to-end against the
live `cwatm-gui-dev` project.

**Milestone 2**: dispatching a real CWatM run as an Accelerator "WKube"
job (the Run CWatM button on any `.ini` in the file browser), with live
in-app status, against a CWatM-ready docker image built automatically
from `iiasa/CWatM_GUI`'s `cwatm-docker-image` branch. Verified live end
to end, including a full run against real uploaded basin data (job
15422, succeeded).

**Milestone 3** (this state): once a run succeeds, a **Browse** button
jumps the existing file browser straight to that run's own output
folder - reusing the already-working list/download UI rather than a
separate one. Verified live end to end (job 15631, 2026-10-29, full
successful run, all 75 output files correctly browsable/downloadable) -
see "Job outputs" below for how the folder path itself is found. (An
earlier version of this milestone rendered the file list and a Plotly
csv-chart preview inline in its own component; dropped in favour of this
simpler approach - no duplicate listing UI, no csv-shape guessing, no
~4.6 MB chart library, see git history.)

## Running it

```bash
npm install

npm run tauri dev       # the real desktop app - needs Rust (rustup.rs)
                         # and, on Windows, the "Desktop development with
                         # C++" workload from the VS Build Tools installer

npm run dev              # the Tauri app's own dev server, fixed at
                          # http://localhost:1420 (what `tauri dev` loads) -
                          # desktop bypasses browser CORS entirely via
                          # Tauri's Rust HTTP client, so this origin was
                          # never allowlisted and opening it in a plain
                          # browser tab will fail on CORS

npm run dev:browser      # for testing the plain-browser-tab target
                          # specifically: https://localhost:7979 (HTTPS,
                          # self-signed cert via @vitejs/plugin-basic-ssl -
                          # accept the one-time browser warning), a
                          # separate dev server/config from the above.
                          # The Accelerator team confirmed (2026-10-28)
                          # this exact origin is CORS-allowlisted; a
                          # different port or http:// will not work.
                          # Browser-mode login is independent of the
                          # desktop app's (localStorage vs. OS keychain).
```

## Architecture

- `src/lib/accelerator/` - the Accelerator API client, framework-agnostic:
  - `config.ts` - server/API base URLs
  - `auth.ts` - device-flow login, access-token refresh/caching
  - `atermFetch.ts` - the one shared authenticated-fetch helper for all of
    `aterm-cli` (auth header, 401/403 handling)
  - `client.ts` - project file browsing (list/download) over `aterm-cli`
  - `jobs.ts` - dispatching a CWatM run as a WKube job
  - `jobStatus.ts` - polling a dispatched job's own uploaded log file for
    its result (no status/log endpoint exists in aterm-cli yet)
  - `outputs.ts` - `wdrvPathToProjectPath`, converting a job's own
    `OUTPUT_DIR` log marker into the project-relative path its output
    files land at (confirmed live, see below)
  - `storage.ts` - refresh-token persistence (OS keychain on desktop,
    `localStorage` in browser)
  - `platform.ts` - the one place that branches on desktop vs. browser
    (HTTP client, opening URLs externally)
- `src/components/` - `Login.tsx`, `FileBrowser.tsx` (file browsing +
  job dispatch/status + the output-folder Browse button, see "Job
  outputs" below)
- `src-tauri/src/keychain.rs` - the Rust command backing `storage.ts`'s
  desktop path, via the `keyring` crate (same OS credential store the
  existing PySide6 app's Supabase login already uses, under a distinct
  service name)
- `vite.config.ts` / `vite.browser.config.ts` - two separate dev servers,
  see "Running it" above

## Job outputs (Milestone 3)

Once `FileBrowser` sees a dispatched job succeed, it shows that run's own
output folder path and a **Browse** button, which jumps the *same* file
browser already used for the rest of the project straight into that
folder - the existing list/download UI takes it from there, nothing
output-specific to build or maintain separately.

**Where the output directory actually comes from** went through two
iterations (see `jobs.ts`'s `buildCommand` doc comment for the full
story): an earlier version wrote CWatM's output to `/mnt/output`, on the
Accelerator team's own confirmation (2026-10-28) that this path always
maps to a fresh, job-scoped, writable directory - which then failed live
anyway (job 15561, 2026-10-29: `PermissionError` writing
`/mnt/output/settings_run.ini`, before CWatM even started). That same
job's build log named the real mechanism instead: a step called
`UploadWdrvFilesCreatedByJobGid` scans `/mnt/wdrv` (not `/mnt/output`)
for files tagged with the job's own JOB_GID and uploads exactly those.
So `buildCommand` now writes into a job-unique directory under
`/mnt/wdrv/output/` (process id + unix time, to avoid colliding with
another job's leftover - the original reason a fixed `/mnt/wdrv/output/`
path was abandoned once already, see git history for job 15415).

Since that directory name is generated **inside the container at
runtime**, the client can't know it ahead of dispatch - the script prints
it as its own `@@CWATM_GUI:OUTPUT_DIR:<path>@@` log marker (same
technique as `cwatm_model_runner.py`'s own RESULT marker), which
`jobStatus.ts` parses back out of the job's log once it finishes
(`JobResult.outputDir`), converted to a project-relative path via
`outputs.ts`'s `wdrvPathToProjectPath`.

**Confirmed live** (job 15631, 2026-10-29, a full successful run): the
marker printed correctly, all 75 of CWatM's output files were uploaded
and registered at exactly the paths `wdrvPathToProjectPath` predicts, and
clicking Browse in the app correctly listed and offered them for
download, using the existing file browser.

An earlier version of this milestone instead rendered its own file list
in-place and let the user preview a `.csv` inline as a Plotly chart
(`JobOutputs.tsx`/`CsvChart.tsx`/`csv.ts`). Dropped after live testing:
the in-app csv preview didn't actually render (never root-caused -
likely the presigned download URL's host not being CORS-allowlisted for
an in-app `fetch`, unlike `aterm-cli` itself, since Download's own
`openExternal` sidesteps that by never fetching the content from app JS
at all), and once that was going to need fixing anyway, reusing the
already-proven file browser was the simpler, smaller design: no
duplicate listing UI, no CWatM csv-shape guessing, no ~4.6 MB chart
library in the bundle. See git history if csv charting is wanted again
later - the csv-parsing/chart code itself (tested, working in isolation)
is still there in that history, just not wired in.

## Things learned the hard way (see the code comments for detail)

The Accelerator API has a few sharp edges that cost real debugging time
to find - each is documented at its exact call site, not just here:

- Device-flow tokens must be sent as a **bare token** (no `Bearer`
  prefix) in the **`x-authorization`** header against **`aterm-cli`**
  routes specifically - `/v1/projects/` requires a session cookie
  regardless of headers, and adding `Bearer` to `x-authorization` breaks
  JWT parsing server-side.
- An absolute node path for `node-items` must have **no trailing
  slash** - `"cwatm-gui-dev"` works, `"cwatm-gui-dev/"` silently returns
  empty.
- Desktop requests go through Tauri's Rust HTTP client
  (`@tauri-apps/plugin-http`) to bypass the webview's CORS enforcement
  entirely, and external URLs (the auth-code page, file downloads) must
  go through the opener plugin - plain `window.open()` does nothing
  useful in a Tauri webview.
- Tauri's HTTP plugin has its own allowed-URL **scope**
  (`src-tauri/capabilities/default.json`), separate from CORS - presigned
  download/upload URLs land on different `*.iiasa.ac.at` subdomains than
  the API itself (`recon.iiasa.ac.at`, `s3.iiasa.ac.at`), so the scope has
  to cover the whole domain, not just `accelerator.iiasa.ac.at`.
- `job_kwargs.command` (the WKube job's entry command) is a plain string
  whose exact tokenization (shell? `shlex`?) isn't documented, so anything
  needing more than one command (`mkdir ... && ...`) should go through a
  single `python -c "<script>"` call instead of relying on shell operators.
- CWatM has no CLI override or environment-variable substitution for
  `PathOut` - a run that needs a different output directory than what's in
  the settings file has to patch the file's own text. The dispatched job
  does this itself (reads the original settings file, patches `PathOut` to
  `/mnt/output`, writes the patched copy, runs against that) rather than
  the client uploading a pre-patched copy - see `jobs.ts`'s next point.
- The project's real file index (what `node-items`/a job's `/mnt/wdrv`
  mount actually see) is built on a content-addressable upload protocol
  (Xet, `huggingface/xet-core`), not the S3-multipart endpoints present in
  `accli`'s reference client - those "succeed" (real object, real id) but
  never become visible anywhere browsable. The Accelerator team confirmed
  (2026-10-28) the multipart uploader is deprecated/on their backlog to
  remove.
- `/mnt/output` (not a path under `/mnt/wdrv`) always maps to a fresh
  directory scoped to the running job's own ID - confirmed by the
  Accelerator team (2026-10-28), who also confirmed this per-job write
  isolation is intentional and guaranteed, and that a job's own files
  can't be overwritten/deleted by another job (only by the project
  owner/admin via the web UI).
