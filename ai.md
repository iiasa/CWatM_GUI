# Gemini NotebookLM integration

> ## ✅ v1 implemented (2026-07-09)
> The chat window is built and wired. See **"Implementation notes (as built)"**
> at the very bottom — it corrects the assumptions this original plan made after
> inspecting the real `notebooklm-py` 0.7.3 API. The sections below are the
> original plan, kept for context.

---

# Gemini NotebookLM integration — plan (v1)

**Goal:** a new menu **Gemini NotebookLM** (placed right of **Help**, left of **Info**)
that opens a chat window. Questions about CWatM are answered by Gemini through a
Google **NotebookLM** notebook whose source is a predefined PDF (e.g.
`CWATM_shorter.pdf`), driven from Python via the **`notebooklm-py`** library.

**Scope of v1:** ask a question → show the answer. **No interaction with the
settings file yet** (that is phase 2/3, sketched at the bottom).

---

## 1. How notebooklm-py fits (to be verified first — TODO #1)

`notebooklm-py` automates the NotebookLM web app (there is no official NotebookLM
API). Working assumptions to confirm against the installed version before coding:

- It drives a real browser session (Playwright/Chromium under the hood), so:
  - **First-run auth**: the user must log in to their Google account once; the
    session/profile is persisted locally and reused afterwards.
  - Calls are **slow** (seconds to tens of seconds) and **must never run on the
    GUI thread** — hence the QThread worker (section 3).
  - The client object is **not thread-safe / not shareable across threads**:
    create and use it entirely inside the worker thread.
- The notebook (with `CWATM_shorter.pdf` uploaded as a source) is expected to be
  **prepared once, manually, in the NotebookLM web UI**. The GUI only needs its
  **notebook id / name** to select it and ask questions. (Programmatic source
  upload is a later nicety, not v1.)
- API surface we need: connect/authenticate → open notebook by id → `ask(question)`
  → answer text (+ optionally source citations).

> If the installed library's API differs, only `notebooklm_client.py` (the thin
> wrapper, section 2) changes — the window and worker are insulated from it.

---

## 2. New files & touched files

### New

| File | Contents |
|------|----------|
| `src/gui/widgets/notebooklm_window.py` | `NotebookLMWindow` — the chat window (UI only, no network code) |
| `src/gui/utils/notebooklm_worker.py` | `NotebookLMWorker(QThread)` — owns the client, runs questions, emits signals |
| `src/gui/utils/notebooklm_client.py` | Thin wrapper around `notebooklm-py`: `connect()`, `ask(question) -> str`, `close()`. The **only** module that imports `notebooklm` — isolates the third-party API |

### Touched

| File | Change |
|------|--------|
| `src/gui/components/menu_builder.py` | Add the **Gemini NotebookLM** menu between `help_menu` and `info_menu`; append it to `self._menus` (QMenu GC guard); one action → `self.open_notebooklm()` |
| `src/gui/components/main_window.py` | `open_notebooklm()` handler: **lazy import** of `NotebookLMWindow` at the call site (keep the fast-startup rule — no module-level import of notebooklm/playwright anywhere near `main_window`), keep a reference so the window isn't GC'd, reuse the open window if it already exists |
| `requirements.txt` | Add `notebooklm-py` (pinned) — plus whatever it pulls (playwright); see packaging risk in section 7 |

Nothing under `cwatm/` is touched (hard rule).

---

## 3. Threading model (the core of the plan)

Network/automation calls block for a long time, so all `notebooklm-py` work lives
in a **single long-lived `QThread` worker** and the UI talks to it only via
**signals/slots** (queued connections — same pattern as `CWatMWorker` in
`src/gui/utils/cwatm_worker.py`).

```
NotebookLMWindow (GUI thread)                NotebookLMWorker (QThread)
  Send clicked ──ask(question)──────────────▶ queue.put(question)
                                              run(): loop
  ◀── status(str)  "Connecting…","Thinking…"    connect once (lazy, first question)
  ◀── reply(str)   answer text                  answer = client.ask(q)
  ◀── error(str)   friendly message             emit reply/error
  window close ──stop()────────────────────▶  sentinel → client.close(), thread ends
```

Design decisions:

- **One worker per window, started on window open, stopped on window close.**
  The client (browser session) is created lazily inside `run()` on the first
  question — opening the window stays instant.
- **Question hand-off via a `queue.Queue`** inside the worker (`ask()` just
  enqueues; `run()` loops `queue.get()`), so the thread is reusable for many
  questions without restart. `stop()` enqueues a `None` sentinel.
- **Signals** (worker → UI): `status(str)` (connection / progress notes shown in
  the chat as a grey line or in a status bar), `reply(str)`, `error(str)`,
  `busy(bool)` (drives the Send button enable/disable + a "thinking…" indicator).
- **UI never blocks**: while a question is in flight the Send button is disabled
  (one question at a time in v1 — simplest correct behaviour); the input field
  stays editable.
- **Shutdown**: `NotebookLMWindow.closeEvent` calls `worker.stop()` and waits
  briefly (`wait(ms)` with a cap — never hang the GUI); the main window's exit
  path does the same if the chat window is still open. All client cleanup
  (browser close) happens **inside** the worker thread.
- **Exception policy**: everything raised inside `run()` is caught, logged via
  `src/gui/utils/gui_log.py`, and surfaced as `error(str)` with a readable
  message (auth needed / network down / notebook not found) — never a crash,
  matching the app's global-exception-handling style.

---

## 4. The chat window (`NotebookLMWindow`)

Plain Qt widgets, modeled on the existing secondary windows:

- **Layout** (top → bottom):
  1. Header label: "Gemini NotebookLM — CWatM assistant" + the notebook/PDF name.
  2. **Transcript**: read-only `QPlainTextEdit` (or `QTextBrowser` if we want
     markdown-ish rendering of answers — decide in TODO #6). Q/A entries are
     appended as `You: …` / `Gemini: …` blocks; status lines in grey; errors in
     dark red (same conventions as the output box).
  3. **Input row**: single/multi-line `QLineEdit`/small `QPlainTextEdit` +
     **Send** button (Enter sends; Shift+Enter = newline if multi-line).
  4. Bottom row: **Clear** (transcript only), **Exit**.
- **Non-modal** (user keeps working in the editor while waiting for an answer).
- **Theme-aware at construction** like the other secondary windows: all colours
  via `theme.c(token)` — *never hardcode a colour*.
- **Geometry memory** via `GeometryMemoryMixin` (`src/gui/utils/window_geometry.py`),
  QSettings key `notebooklm`.
- **State handling**: window can be closed and reopened; reopening reuses the
  existing instance if alive (transcript preserved) — decide reuse vs. fresh in
  TODO #6; v1 default: reuse.

---

## 5. Configuration (QSettings, no new UI in v1)

| Key | Meaning | v1 handling |
|-----|---------|-------------|
| `notebooklm/notebook_id` | id/name of the prepared CWatM notebook | read from QSettings; if empty, prompt once with a simple `QInputDialog` and persist |
| `notebooklm/profile_dir` | where the browser auth profile lives | default under `%LOCALAPPDATA%/CWatM_GUI/notebooklm`; not user-visible in v1 |

A proper Configure-menu entry ("NotebookLM settings…") is phase 2.

---

## 6. TODO list (v1, in order)

- [ ] **1. Spike `notebooklm-py`** in the venv, *outside* the GUI: install, log in,
      open the CWatM notebook, `ask()` one question from a plain script. Pin the
      exact API (auth flow, notebook selection, answer format, close/cleanup).
      Everything below assumes this spike's findings.
- [ ] **2. Prepare the notebook**: create it in the NotebookLM web UI, upload
      `CWATM_shorter.pdf` as the source, note the notebook id.
- [ ] **3. `notebooklm_client.py`**: thin wrapper — `NotebookLMClient(notebook_id,
      profile_dir)` with `connect()`, `ask(str) -> str`, `close()`; readable
      exceptions (`AuthRequired`, `NotebookNotFound`, generic).
- [ ] **4. `notebooklm_worker.py`**: `NotebookLMWorker(QThread)` — question queue,
      lazy connect, signals `status/reply/error/busy`, `ask()`, `stop()` with
      sentinel; all exceptions → `error` + `gui_log`.
- [ ] **5. `notebooklm_window.py`**: `NotebookLMWindow` — transcript, input row,
      Send/Clear/Exit, busy handling, closeEvent → worker stop, theme tokens,
      geometry key `notebooklm`.
- [ ] **6. UX decisions while building #5**: transcript widget (`QPlainTextEdit`
      vs `QTextBrowser`), window reuse vs fresh-per-open, Enter-to-send binding.
- [ ] **7. Menu integration**: `menu_builder.py` — `notebooklm_menu =
      menu_bar.addMenu("Gemini NotebookLM")` inserted **after Help, before Info**
      (i.e. build it between the two, or `insertMenu` before Info's action);
      append to `self._menus`; action "Ask about CWatM…" →
      `main_window.open_notebooklm()` (lazy import inside the handler).
- [ ] **8. Run-lock decision**: `_set_tools_enabled(False)` disables every menu
      except RUN CWATM during a model run — the NotebookLM menu will be disabled
      too by default. v1: accept that (consistent); revisit if chatting during a
      run is wanted.
- [ ] **9. First-run auth UX**: when the client reports auth is needed, show a
      clear message in the transcript telling the user a browser window will
      open / they must log in once (exact mechanics depend on spike #1).
- [ ] **10. `requirements.txt`**: add pinned `notebooklm-py` (+ playwright note);
      document the one-time `playwright install chromium` step if required.
- [ ] **11. Docs**: short section in `documentation/CWatM_GUI_Features.md`
      (feature tour) — *CLAUDE.md untouched per instruction*.

Explicitly **not** in v1: no tests (per instruction), no PyInstaller/spec work
(see risk below), no settings-file interaction.

---

## 7. Risks / open questions

1. **Unofficial automation**: NotebookLM has no public API; `notebooklm-py` can
   break whenever Google changes the web app. Mitigation: all library contact is
   confined to `notebooklm_client.py`; failures degrade to an `error` message.
2. **Packaging (PyInstaller)**: Playwright's browser binaries are not part of the
   one-folder build. v1 is a **source-run feature**; the frozen `CWatM_GUI.exe`
   should degrade gracefully (menu action shows "not available in this build" or
   the import error as a friendly message). Bundling is a separate later task.
3. **Auth lifetime**: Google sessions expire; the worker must map "session
   expired" to a re-login hint, not a crash.
4. **Latency**: answers can take long; the `status`/`busy` signals plus the
   disabled Send button are the v1 answer. No cancel-in-flight in v1 (browser
   automation mid-call is hard to abort safely).
5. **Fast-startup rule**: `notebooklm`/`playwright` must never be imported at
   module level from anything `main_window.py` imports — lazy import in the
   `open_notebooklm()` handler and inside the worker only.

---

## 8. Later phases (design intent, not v1 work)

- **Phase 2 — settings suggestions**: prompt engineering so answers can include a
  fenced block of proposed settings-file changes (`[SECTION] key = value` lines);
  the window parses the block and *displays* it as a diff-like preview.
- **Phase 3 — apply to settings file**: an **Apply** button pushes accepted
  changes into the editor through `SettingsEditor.set_content_preserving` (one
  undoable step, changed-line blue highlight and field re-sync for free — never
  writes to disk itself; the user still Saves).
- **Phase 4 — configure UI**: Configure-menu entry for notebook id, profile dir,
  maybe choosing among several notebooks/PDFs.

---

## Implementation notes (as built, 2026-07-09)

Inspecting the installed **`notebooklm-py` 0.7.3** changed several assumptions
in the plan above. What was actually built:

### The library is async + cookie-auth (not Playwright at runtime)
- `notebooklm-py` is a **fully async** client (`httpx`-based RPC against Google's
  undocumented NotebookLM endpoints), **not** a Playwright browser driver at
  runtime. Public API used:
  - `async with NotebookLMClient.from_storage(profile=…) as client:`
  - `await client.notebooks.list()` → `list[Notebook]` (`.id`, `.title`,
    `.sources_count`)
  - `await client.chat.ask(notebook_id, question, conversation_id=…)` →
    `AskResult` (`.answer`, `.conversation_id`, `.references`)
- It requires **Python ≥ 3.10** (PEP 604 syntax + a runtime version guard). The
  project venv is **3.12.10**, so it imports fine — but the old
  `requirements.txt` "Python 3.8" header no longer holds for this feature.
- Core runtime deps are light: `httpx`, `anyio`, `httpcore`/`h11`, `filelock`,
  `rich` (+ `markdown-it-py`/`mdurl`/`pygments`), `typing_extensions`. All pinned
  into `requirements.txt`. **No Playwright needed for asking questions.**

### Event-loop affinity → one loop inside the worker
The async client binds to the asyncio loop it was opened on; every later call
must run on that same loop. So `notebooklm_client.NotebookLMClientWrapper` owns
**one** persistent `asyncio` loop, created lazily in `connect()` (called from the
worker thread), and drives every await through `loop.run_until_complete`. Callers
see a plain blocking API (`connect → ask → close`). The worker
(`NotebookLMWorker`, a `QThread`) creates the wrapper on the **first** question,
loops over a `queue.Queue`, and emits `status / reply(str,int) / error / busy`.

### Login (the "how to log in" answer)
Auth is a Google cookie bundle the `notebooklm` CLI stores at
`~/.notebooklm/profiles/<profile>/storage_state.json` (`notebooklm.paths.
get_storage_path`). The GUI only **reads** it; `is_authenticated()` /
`storage_state_path()` let the UI report state cheaply. The window's **Login…**
button runs the CLI via `QProcess` (source-run only) and streams output into the
transcript, offering three paths (via a `QMessageBox`):
- **From Chrome** → `notebooklm login --browser-cookies chrome`
- **From Edge** → `notebooklm login --browser-cookies edge`
  (both use **`rookiepy`** — `notebooklm-py[cookies]`, pinned — to read cookies
  from a browser the user is already signed in to; **fast, no Chromium download**)
- **Google login window** → `notebooklm login` (Playwright; needs a one-time
  `playwright install chromium` — *not* bundled, so this path may prompt to
  install). In a **frozen** build the button instead shows the manual command.
On finish it re-checks `is_authenticated()` and resets the worker so the next
question reconnects. On this dev machine a session already exists
(`is_authenticated()` returned True).

### Notebook selection
`notebook_id` is read from QSettings `notebooklm/notebook_id` (a bare id **or** a
NotebookLM URL — `_extract_notebook_id` pulls the id out of
`…/notebook/<id>`). If unset, the wrapper auto-resolves: a notebook whose title
contains "cwat", else the only notebook, else it raises a
`NotebookSelectionError` listing the choices. The **Notebook…** button
(`QInputDialog`) sets/persists the id and resets the worker.

### Files created / touched
- **New**: `src/gui/utils/notebooklm_client.py` (async→sync wrapper, the *only*
  importer of `notebooklm`), `src/gui/utils/notebooklm_worker.py` (`QThread`),
  `src/gui/widgets/notebooklm_window.py` (`NotebookLMWindow`, `QDialog` +
  `GeometryMemoryMixin`, geometry key `notebooklm`, theme-token styled).
- **Touched**: `menu_builder.py` (new **Gemini NotebookLM** menu between Help and
  Info, added to `self._menus`), `main_window.py` (`open_notebooklm()` handler,
  lazy import, single reusable window ref), `requirements.txt` (deps above).
- `_set_tools_enabled(False)` disables the new menu during a CWatM run (expected).

### Verified (no network)
`py_compile` of all changed files; import of the wrapper; and an **offscreen**
(`QT_QPA_PLATFORM=offscreen`) construction of `NotebookLMWindow` — header/
transcript render, question/answer/error blocks append, Send disables while
busy. A real end-to-end ask (which would hit the user's live Google session and
list private notebooks) was intentionally **not** run.

## Implementation notes (as actually built, 2026-07-10)

The files below are the ones present in the repo (the 2026-07-09 section above was
a forward-looking plan; the tree had no notebooklm code until now). Two changes vs
the original plan, per user request:

- **Entry point is a "CWatM AI" *button*, not a menu.** It is a **top-level
  `QAction` on the menu bar** (`menu_builder._cwatm_ai_action`) placed **left of
  Help** — a top-level action fires `triggered` on click instead of opening a
  dropdown, so it reads/behaves as a button. It stays available during a CWatM run
  (the run-lock now only greys the Save button).
- **Window styled like the other secondary windows (e.g. NetCDF).**
  `NotebookLMWindow` = `GeometryMemoryMixin` + `QDialog`, geometry key **`cwatm_ai`**,
  cwatm.ico, every colour a `theme.c(token)`; header + subtitle + a `QTextBrowser`
  transcript (You = link colour, Gemini = ok colour, status = muted italic, errors =
  `out_error`), a multi-line input (Enter sends, Shift+Enter = newline) + **Send**
  (blue accent, shows "Thinking…" + disables while busy), and **Login… /
  Notebook… / Clear / Exit**. Opened via `main_window.open_cwatm_ai()` (lazy import;
  single reusable non-modal window kept on `self._cwatm_ai_window`).

Files: **new** `src/gui/utils/notebooklm_client.py` (async→sync wrapper, the only
importer of `notebooklm`; owns one asyncio loop; `connect/ask/close`,
`is_authenticated`, notebook auto-resolve, `_extract_notebook_id`),
`src/gui/utils/notebooklm_worker.py` (`NotebookLMWorker(QThread)` — question
`queue.Queue`, lazy connect, `status/reply/error/busy` signals, `stop()` sentinel),
`src/gui/widgets/notebooklm_window.py`. **Touched** `menu_builder.py`,
`main_window.py`, `requirements.txt` (`notebooklm-py[cookies]==0.7.3`). Nothing under
`cwatm/` touched. Verified: `py_compile` of all files; offscreen construction +
Q/A/status/error transcript rendering + Send busy-toggle; menu-bar placement
(CWatM AI left of Help, top-level action); wrapper import + `_extract_notebook_id`.
A live network ask was **not** run (would hit the user's private notebooks).

## UX refinements (2026-07-10)

- **Transcript + question history persist across open/close.** `closeEvent`/`done()`
  save `transcript.toHtml()` to QSettings `notebooklm/transcript_html` and the sent
  questions to `notebooklm/history`; `__init__` restores both (`_restore_state`), and
  when a transcript is restored the greeting collapses to a "— New session —"
  separator.
- **Up/Down recall older/newer questions** in the input box (shell-style), only when
  the caret is on the first/last line so multi-line editing still works
  (`_history_prev`/`_history_next`, boundary via `_at_first_line`/`_at_last_line`;
  a live draft is preserved when you page past the newest). History survives sessions
  (persisted alongside the transcript).
- **Login state is explicit**: `_refresh_login_state()` colours the Login button
  **blue = logged in** (label "✓ Logged in") / **red = not logged in** (label
  "Login…"), with a matching centred status line ("● Logged in to NotebookLM" /
  "● Not logged in — press 'Login…'"). Re-run on open and after every login attempt.
- **Closer to the NetCDF window style**: 14px/600 header, muted sub-label, a centred
  status line like NetCDF's `info_label`, and blue-gradient action buttons (Send /
  Notebook… / Clear / Exit) matching NetCDF's `_btn`.

## Voice dictation + button colours (2026-07-10)

- **Notebook / Clear / Exit are grey** (theme `btn_*` tokens) again; only **Send**
  is blue and **Login** is blue/red by sign-in state.
- **🎤 Voice toggle** (in the input row, left of Send): turn on to dictate a
  question, off to stop; the button goes **red while recording**. Speech-to-text is
  `src/gui/utils/voice_input.py` → `VoiceDictation(QObject)`: it captures the mic in
  a background thread (`SpeechRecognition.Recognizer.listen_in_background`) and
  transcribes each phrase via **Google Web Speech** (online, no key), emitting
  `recognized/status/error/stopped` **signals** so the GUI thread just types the text
  into the input box (append with a space). Graceful degradation: if
  `SpeechRecognition`/`PyAudio` are missing or there is no microphone, it posts a
  hint in the transcript and un-toggles - the feature is optional. Deps pinned in
  `requirements.txt` (`SpeechRecognition==3.17.0`, `PyAudio==0.2.14`); source-run
  only (not added to the PyInstaller spec). Voice is stopped on window close.

## Answer-length selector (2026-07-10)

- A **Short / Medium / Long** 3-way selector (compact exclusive toggle buttons in the
  bottom row, right of **Notebook…**; selected = blue) sets NotebookLM's answer
  verbosity. Persisted in QSettings
  `notebooklm/response_length` (default **Medium**). Maps to the library's
  `ChatResponseLength` enum: short→`SHORTER`, medium→`DEFAULT`, long→`LONGER`, applied
  via `client.chat.configure(notebook_id, response_length=…)`.
- Plumbing: `NotebookLMClientWrapper` gains `set_response_length()` (store-only, any
  thread) + `_apply_response_length()` (runs on its loop, once per change) called from
  `connect()`/`ask()`; `NotebookLMWorker` carries the length and pushes it to the
  client on the **worker thread** before each ask (avoids the loop-affinity trap). The
  window forwards changes live to a running worker. Note: `configure` is a NotebookLM
  **server-side** (per-notebook) setting, so it also affects the notebook in the web UI.

## Settings-file interaction — phases 2–3 (2026-07-10)

Implemented the answer⇄settings bridge (was "later phases"). Trigger model = **Both**
(buttons + typed phrases); insert policy = **validate & reject**.
- **→ Settings** button / "put this in the settings" (+ variants): inserts the
  **marked** transcript text into the settings editor. `main_window.
  ai_put_text_in_settings(text)` → `_parse_settings_block` (each non-blank line must be
  `[SECTION]` / `key = value` / `#comment`, else rejected with a message) →
  `_apply_settings_entries` (existing key updated in place; new key inserted at the end
  of its `[SECTION]`, section created at EOF if missing; else appended) → applied with
  `SettingsEditor.set_content_preserving` (one undoable step, Save-dirty, changed-line
  highlight) → `_sync_fields_from_editor` → `_goto_editor_line` jumps/centres there.
- **Explain current line** button / "explain this line" (+ variants): reads
  `main_window.ai_current_settings_line()` (cursor line, or the editor selection) and
  submits "Explain this line from a CWatM settings file: `<line>` …" to NotebookLM.
- Command phrases are matched as exact normalised strings (`_PUT_CMDS` / `_EXPLAIN_CMDS`
  in `notebooklm_window.py`) so real questions are never intercepted; the buttons are
  the always-unambiguous path. The bridge logic lives in `main_window.py` (editor is
  its responsibility); the window only reads the marked text / shows the result.

## Real login verification (2026-07-11)

`is_authenticated()` only checks that the session **file** exists — but the cookies
expire. So CWatM AI now **verifies** the session against NotebookLM:
- `notebooklm_client.check_connection()` opens the client and does a `notebooks.list()`
  probe, returning `ok` / `auth` (expired-or-invalid, via `is_auth_error` matching
  "Authentication expired or invalid", "accounts.google.com", "notebooklm login" …) /
  `no_session` / `error` (network). Runs on its own loop → call from a thread.
- The window runs it on open (and after login) in `_AuthCheckWorker(QThread)`;
  `_refresh_login_state` shows **Checking… → ✓ Logged in (blue)** or **Login required
  (red)**. An `auth` result (or an auth-flavoured question error) flips to red and
  `_prompt_reauth()` offers the Google login window. `playwright` pinned for that path.

### Still TODO / not done in v1
- No settings-file interaction (phases 2–3 above).
- No PyInstaller/spec work — this is a **source-run** feature; the frozen exe
  degrades gracefully (Login button shows a manual-command message; a missing
  `notebooklm` import surfaces as a friendly error, not a crash).
- Docs section in `documentation/CWatM_GUI_Features.md` not yet written.
- `CLAUDE.md` intentionally left unchanged (per instruction).
