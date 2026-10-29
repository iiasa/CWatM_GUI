# CWatM Accelerator Client (Tauri)

A Tauri-based client, separate from the existing PySide6 `CWatM_GUI` app,
that logs into IIASA's Accelerator platform (device flow) and browses a
project's files. Runs both as a native desktop app and in a plain
browser from the same code.

**Milestone 1**: login + file browsing, verified end-to-end against the
live `cwatm-gui-dev` project.

**Milestone 2** (this state): dispatching a real CWatM run as an
Accelerator "WKube" job (the Run CWatM button on any `.ini` in the file
browser), with live in-app status, against a CWatM-ready docker image
built automatically from `iiasa/CWatM_GUI`'s `cwatm-docker-image` branch.
Verified live end to end, including a full run against real uploaded
basin data (job 15422, succeeded).

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
  - `storage.ts` - refresh-token persistence (OS keychain on desktop,
    `localStorage` in browser)
  - `platform.ts` - the one place that branches on desktop vs. browser
    (HTTP client, opening URLs externally)
- `src/components/` - `Login.tsx`, `FileBrowser.tsx`
- `src-tauri/src/keychain.rs` - the Rust command backing `storage.ts`'s
  desktop path, via the `keyring` crate (same OS credential store the
  existing PySide6 app's Supabase login already uses, under a distinct
  service name)
- `vite.config.ts` / `vite.browser.config.ts` - two separate dev servers,
  see "Running it" above

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
