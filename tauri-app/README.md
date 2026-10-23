# CWatM Accelerator Client (Tauri)

A Tauri-based client, separate from the existing PySide6 `CWatM_GUI` app,
that logs into IIASA's Accelerator platform (device flow) and browses a
project's files. Runs both as a native desktop app and in a plain
browser from the same code.

**Milestone 1** (this state): login + file browsing, verified end-to-end
against the live `cwatm-gui-dev` project. Remote CWatM execution via
Accelerator's Jobs API is a deliberately separate, not-yet-started
milestone - it needs a CWatM-ready docker image on their execution
cluster first.

## Running it

```bash
npm install

npm run dev          # browser only, http://localhost:5173
                      # (needs the Accelerator to allow CORS for this
                      # origin - not yet requested/confirmed)

npm run tauri dev     # the real desktop app - needs Rust (rustup.rs)
                       # and, on Windows, the "Desktop development with
                       # C++" workload from the VS Build Tools installer
```

## Architecture

- `src/lib/accelerator/` - the Accelerator API client, framework-agnostic:
  - `config.ts` - server/API base URLs
  - `auth.ts` - device-flow login, access-token refresh/caching
  - `client.ts` - project file browsing (list/download) over the
    `aterm-cli` API
  - `storage.ts` - refresh-token persistence (OS keychain on desktop,
    `localStorage` in browser)
  - `platform.ts` - the one place that branches on desktop vs. browser
    (HTTP client, opening URLs externally)
- `src/components/` - `Login.tsx`, `FileBrowser.tsx`
- `src-tauri/src/keychain.rs` - the Rust command backing `storage.ts`'s
  desktop path, via the `keyring` crate (same OS credential store the
  existing PySide6 app's Supabase login already uses, under a distinct
  service name)

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
