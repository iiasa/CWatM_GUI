# `cwatm_gui.py` — structure & simplification report

> ## ✅ ALL TEN ITEMS IMPLEMENTED (2026-07-19)
> `cwatm_gui.py` went from **379 lines to 356**, with `main()` down from **108 lines
> to 24**. The line anchors in the findings below refer to the **pre-refactor** file
> and are kept as a record of what was found and why — they no longer point at live code.
>
> One item is **implemented but not resolved**: the exit-status policy (#3). The
> refactor preserved that behaviour exactly and documented it in `_exec`'s docstring;
> the decision about what it *should* be is still open — see the correction under #3.
>
> *(Recreated after this file reverted to an older version and
> `documentation/performance_report.md` disappeared entirely, mid-session — the `P:`
> share was returning inconsistent directory listings and silently dropping writes.
> All source-code edits were verified intact.)*

**Scope:** structure only. No feature removal, no behaviour change, no startup-cost
regression.

---

## Invariants the refactor had to preserve

| # | Invariant | Status after refactor |
|---|-----------|----------------------|
| I1 | The `--run-cwatm` / `--notebooklm-login` dispatches run **before any Qt import**. | ✅ **Verified** — the child path imports *zero* PySide6 modules and no `main_window`. |
| I2 | `QTWEBENGINE_CHROMIUM_FLAGS` / `QTWEBENGINE_DISABLE_SANDBOX` set **before the first QtWebEngine import**. | ✅ Now in `_configure_qtwebengine()`, first statement of `main()`; every QtWebEngine import is lazy and later. |
| I3 | No module-level import of cwatm / xarray / rasterio / plotly / folium on the startup path. | ✅ Unchanged. |
| I4 | The splash closes only **after** `window.show()`. | ✅ Order preserved in `main()`. |
| I5 | `sys.stdout`/`sys.stderr` swapped **before** anything prints during startup. | ✅ `_install_stdio_redirects(window)` still runs before `show()`. |
| — | `sys.excepthook` installed **before** `CWatMMainWindow()` is constructed. | ✅ Preserved — easy to lose in the split. |

---

## Findings (as originally found — all now addressed)

### 1. `asset_path` was duplicated verbatim — High

`cwatm_gui.py:100-118` duplicated `src/gui/utils/assets.py:13-35` — same search order,
differing only in how the source-tree base was computed (both resolved to the project
root). The rest of the codebase already imported the `utils` one
(`main_window.py:229, 267`).

**Done:** local copy deleted, now `from src.gui.utils.assets import asset_path`.
*Verified: `cwatm_gui.asset_path is assets.asset_path`.*

### 2. `main()` did eight unrelated jobs — High

`cwatm_gui.py:268-375` covered: Windows app-ID, Qt attribute, `QApplication`, theme,
icon, excepthook, stdio redirect, window construction, the foreground dance, two
warm-ups, command-line/recent-file loading, and the exec loop — with error handling
interleaved so it could not be read as a sequence.

**Done:** split into `_configure_qtwebengine` / `_create_app` /
`_install_stdio_redirects` / `_schedule_startup_tasks` / `_load_initial_settings` /
`_exec`. `main()` now reads as 24 lines of named steps.

### 3. Four-level nested `try/except` in `main()` — Med

Handlers at `:270`, `:352`, `:360`, `:365`, `:370`; three did the same thing. The
nesting hid an oddity at `:355-358`: on a non-zero exit code the function **prints and
falls through**, returning `None`, so the process exit status is 0 regardless.

> ### ⚠️ CORRECTION — the original claim here was wrong
>
> This report originally said the `except SystemExit` around `app.exec()` was
> "likely unreachable", reasoning that exceptions in Qt slots go through
> `sys.excepthook`. **It is reachable, and it fires on every normal shutdown.**
> `sys.exit(0)` on the clean-exit path is raised *inside* the same `try` that catches
> `SystemExit`, so a normal quit prints to stderr:
>
> ```
> System exit intercepted in main loop: 0
> Application will continue running...
> ```
>
> Verified by driving `_exec()` with a stub app returning 0. Since `sys.stderr` is the
> `PrintRedirector` by then, those two misleading lines are also pushed into the CWatM
> output box while the window is closing.
>
> This sharpens the policy question rather than settling it: the code reads as
> protection against a stray `sys.exit()` from model code, but its most common effect
> is announcing a false "intercepted" on every clean quit.

**Done (structurally):** flattened into `_exec(app)`, behaviour preserved **verbatim**
and both quirks documented in its docstring. *Verified: exit code 0 still hits the
SystemExit handler; exit code 3 still falls through returning `None`.*
**Still open:** what the policy should be. Do not change it without deciding.

### 4. The two CLI dispatch blocks shared a copy-pasted preamble — Med

`cwatm_gui.py:25-33` and `:42-55` both did: try-import `pyi_splash` → `close()` →
swallow → `sys.path.insert(0, <script dir>)` → import a runner → exit.

**Done:** `_CHILD_DISPATCH` table + `_dispatch_child_process()`; each handler keeps its
imports inside itself, so I1 holds.

### 5. Import-time side effects made the module unimportable for testing — Med

Importing `cwatm_gui` set two environment variables, imported and mutated the splash,
imported Qt, imported the whole main window, and constructed a logger — part of why
`asset_path` got copied in the first place (#1).

**Done:** the `os.environ` block moved into `_configure_qtwebengine()`. The Qt and
`main_window` imports intentionally stay at module level — moving them into `main()`
would change the frozen splash's perceived progress (I4).

### 6. Startup settings-file selection mixed two policies inline — Low

`cwatm_gui.py:336-349`: an `if/else` whose `else` branch was itself a try/except
reading `QSettings` and poking `window._recent_files`.

**Done:** `_initial_settings_file(window) -> str | None`. *Verified across all four
cases: argv wins; load-previous on; load-previous off; empty recents.*

### 7. `PrintRedirector` lived in the entry point — Low

`cwatm_gui.py:223-236`. GUI plumbing that `cwatm_process_worker.py:17, 96` documents as
part of the run architecture, but could not be imported without triggering #5.

**Done:** moved to `src/gui/utils/print_redirector.py`.

**Deliberately NOT changed:** `write()` guards with `if text.strip():`, so
whitespace-only writes — including a bare `"\n"` — are dropped. The output box's `\r`
progress-line overwrite may depend on this. Preserved verbatim and commented.
*Verified: `"\n"` and `"   "` still dropped; `"hello"`/`"x"` still emitted.*

### 8. Unnamed startup timings — Low

`QTimer.singleShot(0 / 300 / 500 / 1500, ...)`.

**Done:** `_FOREGROUND_RETRY_MS = 300`, `_WARMUP_DELAY_MS = 500`,
`_WEBENGINE_PREWARM_DELAY_MS = 1500`. *Verified unchanged values.* Registration order is
preserved too — the two 0 ms callbacks still fire foreground-then-load.

### 9. Small cleanups — Low

**Done:** `import threading` hoisted to module top; the "Python 3.8+" docstring
corrected; the five repeated `print(..., file=sys.stderr)` calls in `handle_exception`
folded into an `_err(*lines)` helper. *Verified byte-identical output for the SystemExit
branch.*

### 10. Splash state was handled in five places through a module global — Med

Touched at `:26-30`, `:43-47`, `:78-82`, `:88-92`, `:160-167` — three of which closed it.
The module global `pyi_splash` doubled as the "are we frozen?" sentinel, which is why the
CLI blocks in #4 could not simply call `_close_splash()` (defined below them, after the
Qt import).

**Done:** one `_splash(action, text=None)` helper defined **above** the child dispatches;
all five sites go through it, and the "are we frozen" test is a single failed import.
*Verified: returns `False` and no-ops when not frozen.*

**Related, fixed in the same pass:** `cwatm_gui_dir.spec` listed a hidden import
`'py_splash'`, a typo for `pyi_splash` that silently collected nothing (the splash worked
anyway because `Splash(...)` injects it). Now `'pyi_splash'`.

---

## Verification performed

Offscreen (`QT_QPA_PLATFORM=offscreen`), no GUI window shown — 8 checks, all passing:

| Check | Result |
|---|---|
| `asset_path` is the shared one | PASS |
| `PrintRedirector` moved + whitespace guard intact | PASS |
| `_splash()` no-ops when not frozen | PASS |
| Startup timings still (300, 500, 1500) | PASS |
| `_initial_settings_file` precedence, 4 cases | PASS |
| Clean `exit(0)` still caught by the SystemExit handler | PASS |
| Non-zero exit still falls through returning `None` | PASS |
| `handle_exception` SystemExit output unchanged | PASS |

Plus **I1 proven directly**: `cwatm_gui.py --run-cwatm <missing.ini>` exits with code 1,
emits its `@@CWATM_GUI:RESULT:...@@` marker, and imports **zero** PySide6 modules.

### Not covered by the above

Frozen-only or needing a running GUI — **not** exercised:

1. The frozen splash (items 5 + 10 are entirely frozen-only — a source run touches none
   of it). Needs a built exe.
2. `--notebooklm-login` dispatch (needs the notebooklm stack + a browser).
3. Show Basin opening a map — the real proof that the QtWebEngine flags still land before
   Chromium initialises. **A blank map means the flags arrived late.**
4. A live run, to confirm the stdout redirect and the `\r` progress-line overwrite still
   behave after the `PrintRedirector` move.
