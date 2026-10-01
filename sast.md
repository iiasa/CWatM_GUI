# SAST plan – CWatM GUI

*Static Application Security Testing for `iiasa/CWatM_GUI`, written 2026-10-01.
The repo is **public**, so GitHub's CodeQL code scanning, secret scanning and push
protection are free. Findings are tracked in [`security.md`](security.md).*

What there is to scan:
- **Python:** `src/`, `cwatm_gui.py`, `cwatm_model.py`, `tools/`.
- **TypeScript:** `supabase/functions/` (the two server functions).
- **SQL:** `supabase/migrations/`.
- **PowerShell:** `build_release.ps1`, `.claude/skills/creategui/publish_gui.ps1`.
- **Model code:** `cwatm/`, which we must not edit.

CI already runs on every push (`.github/workflows/ci.yml`): byte-compile,
`tools/check_invariants.py`, the requirements check, and the tests on Linux and Windows.

## Ground rules – so it helps instead of drowning you

1. **Scope:** scan the GUI's own code strictly. Scan `cwatm/` only in **report-only**
   mode: it cannot be fixed here, so its findings go upstream to the CWatM maintainers
   and never block.
2. **Baseline first, then only *new* findings block.** The first scan produces a
   backlog that is triaged once. After that, a push or pull request can only fail on
   findings it *introduced*.
3. **Only a few things ever block:**
   - the deterministic project rules;
   - a leaked secret;
   - new high-severity / high-confidence security findings.

   Everything else shows up as an annotation or alert and does not stop work.
4. **One register:** every finding that matters ends up in `security.md`.

## Steps, ranked by value for effort

| Rank | Step | Tool | Value | Effort | Blocks? |
|---|---|---|---|---|---|
| 1 | Secret scanning | GitHub secret scanning + push protection, gitleaks in CI | Very high – a leaked Supabase **secret** key exposes the whole database | ~1 h | **Yes** |
| 2 | Project rules as code | `tools/check_invariants.py` (exists) – extend | High – zero false positives, tailored to our real risks | ~2 h | **Yes** (already in CI) |
| 3 | Python SAST, fast loop | Bandit (locally + CI) | High | ~½ day incl. triage | New HIGH/HIGH only |
| 4 | CodeQL | GitHub code scanning (Python + JS/TS + Actions) | High – deeper data-flow analysis | ~½ day | New "error" security alerts in PRs only |
| 5 | Dependency vulnerabilities (SCA – not SAST, but where most real CVEs come from) | Dependabot alerts + `pip-audit` weekly | High – PySide6/Chromium, rasterio/GDAL, requests | ~1 h | No – alerts |
| 6 | Server SQL | `tests/test_server_sql.py` (exists) + Supabase Security Advisor | Medium – the SQL already has its own tests | ~1 h | Tests yes, Advisor no |
| 7 | Editor feedback | Ruff `S` rules (Bandit's checks in the linter), pre-commit | Medium – finds issues before commit | ~1 h | No |
| 8 | PowerShell build scripts | PSScriptAnalyzer | Low | ~1 h | No |

### 1. Secrets (do first)
- Repo **Settings ▸ Code security**: enable **secret scanning** and **push protection**
  (free for public repos).
- A `gitleaks` job in CI.
- Allowlist the **publishable** key in `src/gui/utils/account_config.py`, with a
  comment – it is public by design.
- **Must fail:** anything that looks like `sb_secret_…`, a service-role JWT, or a
  Google/NotebookLM cookie or session file.

### 2. Extend our own rules (cheap, exact)
**Already blocked** by `check_invariants.py`:
- `shell=` / `os.system` / `os.popen` / single-string `subprocess`;
- `os.startfile` outside `open_path`;
- silent `except: pass`;
- heavy imports on the startup path.

**To add**, for the GUI code:
- ~~no `eval` / `exec`~~ – **left out for now (decided 2026-10-01).** The eval/exec
  problem is handled inside CWatM by its maintainer; the GUI's run guard
  (`run_guard.py`, security.md #1) stays as it is.
- no `pickle` / `yaml.load` / `marshal` on files;
- no `verify=False` in `requests`;
- no `sb_secret` / `service_role` strings outside `supabase/functions`;
- no `setHtml` / rich text with text from the server or the AI chat without escaping.

They are deterministic, so they can safely block.

### 3. Bandit
- Targets: `src`, `cwatm_gui.py`, `cwatm_model.py`, `tools`. `tests/` and `cwatm/` excluded.
- **Skips**, each with a one-line reason in the config:
  - B404 / B603: `subprocess` with an argument list – our own rule already forbids the dangerous forms;
  - B311: `random` is not used for security (the sparkline animal).
- Create the baseline once: `bandit -r … -f json -o .bandit-baseline.json`.
  CI then runs with `-b .bandit-baseline.json` and fails only on **new HIGH severity
  with MEDIUM-or-higher confidence**.
- A reviewed and accepted line gets `# nosec B…  <reason>`, never a bare `# nosec`.

### 4. CodeQL
- **Workflow:** `.github/workflows/codeql.yml` (GitHub "advanced setup"), languages:
  - **python** – buildless;
  - **javascript-typescript** – the two server functions;
  - **actions** – catches injection in the CI workflows themselves.
- **`paths-ignore`:** `cwatm/`, `tests/`, `dist/`, `build/`, `venv/`, `venv2/`.
- **Query suite:** start with **default** (high precision). Move to `security-extended`
  only once the backlog is empty – that is the "don't drown" lever.
- **Triggers:** push to `main`, pull requests, and **weekly** (`schedule`), so new
  queries also find old code.
- **Ruleset** (Settings ▸ Rules ▸ Rulesets ▸ *Require code scanning results*): blocks a
  merge only for **new** alerts at *error* / *high* security severity. Medium and low
  stay visible in the Security tab and as PR annotations.
- **Separate weekly, report-only CodeQL run on `cwatm/`**: it flags its `eval`/`exec`
  (security.md #1) as tracked evidence for the CWatM maintainers.

### 5. Dependencies
- Enable **Dependabot alerts** (and optionally Dependabot security updates).
- A weekly, non-blocking `pip-audit -r requirements.txt` job.
- Upgrades go through the normal release testing (`/creategui`): they change the
  bundled exe.

### 6. Server SQL
No SAST tool understands Supabase row level security well. `tests/test_server_sql.py`
is our own SAST for it and already blocks. It checks:
- the latest definition of every function;
- `search_path` pinned;
- EXECUTE revoked by default;
- RLS on every table;
- no dynamic SQL;
- the points / shop rules.

After each `npx supabase db push`, look at **Dashboard ▸ Advisors ▸ Security** by hand.
It reports tables without RLS, functions whose `search_path` can change, and
over-exposed views.

### 7–8. Optional
- **Ruff** with the `S` rules in pre-commit: Bandit's checks while editing.
- **PSScriptAnalyzer** for `build_release.ps1` and `publish_gui.ps1`.

## Handling findings

**Triage each finding on three questions:**
1. How bad would it be if exploited?
2. How sure is the tool?
3. Can untrusted input reach the line?

Untrusted input here means: settings files, NetCDF / Excel inputs, answers from the
account server, files in an output folder, AI-chat answers. Severity alone is not
enough – a HIGH finding on fixed internal data is low priority.

**Each finding gets exactly one outcome:**
- **Fix**, with a test, as done for security.md findings 1, 2, 4, 6 and 11.
- **Accept**, with a one-line reason: `# nosec B…: <why>` in the code, or CodeQL's
  *Dismiss → won't fix / false positive* with a comment.
- **Defer**: an entry in `security.md` with a target release.

**Response times:**

| Severity | Fix by |
|---|---|
| Critical / High, new | before merge |
| Critical / High, backlog | the next release |
| Medium | within 2 releases |
| Low | when that code is touched anyway |

**Fixed review budget:** 15 minutes a week in the repo's Security tab, instead of
reacting to every alert as it arrives.

## Rollout – in this order

Each step is finished, and green in CI, before the next one starts.
**Who** = what can be done in the repo vs. what needs a repo admin on GitHub.

| # | Step | Who | Blocks after it is done |
|---|------|-----|-------------------------|
| 1 | Turn on **secret scanning + push protection** (Settings ▸ Code security) | Repo admin, 5 min | A push with a secret is refused |
| 2 | Run **gitleaks once over the whole git history**; if something real is found, rotate that key first | Repo | – |
| 3 | Add the **gitleaks job** to CI, with the publishable-key allowlist | Repo | New secrets |
| 4 | **Extend `check_invariants.py`**: no `pickle`/`yaml.load`/`marshal`, no `verify=False`, no secret-key strings, no unescaped `setHtml`; fix whatever it finds (an `eval`/`exec` rule is left out for now – handled inside CWatM) | Repo | New violations |
| 5 | **Run Bandit locally once** – size the backlog before wiring anything in | Repo (needs `pip install bandit` in the venv) | – |
| 6 | **Triage that backlog** in one sitting: fix / accept with `# nosec B…: reason` / defer to `security.md` | Repo | – |
| 7 | Write the **Bandit config** (scope, skips with reasons) and the **baseline**; add the Bandit job to CI | Repo | New HIGH / ≥MEDIUM-confidence |
| 8 | Enable **Dependabot alerts**; add a weekly, non-blocking **`pip-audit`** job | Repo admin + repo | – (alerts) |
| 9 | Add **`codeql.yml`** (python, javascript-typescript, actions; `paths-ignore`; default suite; push + PR + weekly) | Repo | – (results only) |
| 10 | **Triage CodeQL's first run** in the Security tab (fix / dismiss with reason / defer) | Repo | – |
| 11 | Add the **ruleset** that blocks merges on *new* error/high code-scanning alerts | Repo admin | New high CodeQL alerts in PRs |
| 12 | Add the **report-only CodeQL run on `cwatm/`** – kept as an independent **check on the eval/exec fix** being done inside CWatM: its code-injection alerts should disappear once the fix lands (decided 2026-10-01) | Repo | – |
| 13 | Make the **Supabase Security Advisor** check part of every `db push` (manual, a line in `supabase/README.md`) | You | – |
| 14 | Optional: **Ruff `S` rules + pre-commit**, **PSScriptAnalyzer** | Repo | – |
| 15 | **Ongoing:** 15 min a week in the Security tab; switch CodeQL to `security-extended` once its backlog is empty | You | – |

Steps 1–4 cost little and each one closes a real hole on its own. Steps 5–7
add Bandit, 8 dependencies, 9–12 CodeQL; 13–15 keep it running.

## Status
- [x] 1 Secret scanning + push protection — enabled 2026-10-01 via the GitHub API
      (`security_and_analysis`); first history scan: no alerts at the time of checking
- [x] 2 gitleaks over the history — 2026-10-01, gitleaks 8.30.1 (official release,
      SHA-256 verified), `--all` branches, `--no-textconv`, `--redact`: 28 commits,
      **no real secret**.
      - The only hit (`generic-api-key`, `src/gui/utils/account_config.py:19`) is the
        Supabase **publishable** key – public by design, the only value ever committed
        there.
      - The working folder: the same key in the git-ignored, never-committed note
        `gamification/game1.txt`.
      - An extra search for what gitleaks' default rules miss (`sb_secret_…`,
        service-role JWTs) found nothing, in history or on disk.
      - **Nothing to rotate.** Step 3's CI config must allowlist exactly this
        publishable key (by value, not by file), so a real secret in
        `account_config.py` would still fail.
- [x] 3 gitleaks job in CI — 2026-10-01, job `secrets` in `.github/workflows/ci.yml`,
      config `.gitleaks.toml`.
      - **Scan:** gitleaks 8.30.1 with its SHA-256 pinned in the workflow, the whole
        history on every push.
      - **Rules:** gitleaks' defaults plus Supabase secret key, service-role JWT (all 3
        base64 positions) and Google session cookie.
      - **Allowlist:** only the publishable key, by exact value.
      - **Self-tested with fake secrets:** publishable key passes; secret key,
        service-role tokens and Google cookie each caught.
      - **Activates on the next push.**
- [x] 4 Extra rules in `check_invariants.py` — 2026-10-01, `content_problems()`.
      - **The rules:** no pickle/marshal/shelve/unsafe yaml; no `verify=False`; no
        secret-key or JWT literals; every `setHtml`/`insertHtml`/`setMarkdown`/
        `appendHtml` carries a `# html-safe: <reason>` note; no
        `setOpenExternalLinks(True)`. The `eval`/`exec` rule is left out by decision.
      - **What it found and fixed:**
        - The CWatM AI transcript and the Help viewer handed any clicked link to the
          desktop: a `file://…exe` link would run it. Links now go through
          `open_path.open_link` – web/mail only, plus local non-program files;
          `#anchors` scroll.
        - AI answers were rendered with raw HTML allowed. Now `html=False`: shown as
          text.
      - **Review:** the 5 rich-text sites were reviewed and noted.
      - **Tests:** `tests/test_safe_links.py`.
- [x] 5 Bandit local run — 2026-10-01, Bandit 1.9.4 (installed in `venv`) over
      `src`, `cwatm_gui.py`, `cwatm_model.py`, `tools`: 94 files, 12 s, **22
      findings** (2 HIGH, 20 LOW, 0 MEDIUM). First assessment for step 6:
      - **B324 ×2 (HIGH)** – `hashlib.md5` in `basin_viewer.py:171` (tile/WMS cache
        file name) and `batch_runner_window.py:1564` (batch identity). Not security
        use → `usedforsecurity=False`: same hash value, so cache names and
        identities stay identical.
      - **B105 ×8, B107 ×1** – false positives. Messages and error codes that
        contain the word "password"/"token" (`account_client.py`), a colour-token
        argument (`account_dialogs.py`). Real secrets are gitleaks' job → skip in
        the config.
      - **B311 ×3** – `random` for the sparkline animal and the Academy's random
        basin; not security → skip.
      - **B404 / B603** – `subprocess` with an argument list in `open_path.py`; our
        own invariant already forbids the dangerous forms → skip.
      - **B101 ×1** – `assert` in the tool script `tools/import_all.py` → fine there.
      - **To review in step 6: B110 ×3** (`try/except/pass` in `cwatm_gui.py:48,
        89, 503` – outside `src/gui`, so our silent-except rule never covered it)
        and **B112 ×2** (`try/except/continue` in `settings_check.py:201`,
        `restore_settings_window.py:217`).

      **Net: 7 real items** (2 to fix, 5 to review); 15 are config skips.
- [x] 6 Bandit backlog triaged — 2026-10-01, all 7 real items handled:
      - **Fixed – B324 ×2:** `usedforsecurity=False` on both `md5` calls (verified: the
        same hash value, so cache files and saved batch tables keep their names).
      - **Fixed – B112 ×2:** `settings_check.py`, `restore_settings_window.py` – still
        skip the bad section / folder, but now `log.debug(..., exc_info=True)`.
      - **Accepted – B110 ×3** in `cwatm_gui.py`, each with `# nosec B110 - <reason>`:
        the profiler cannot log itself; the splash runs before logging exists (also in
        the model child); a Qt message handler must never raise.
      - **Re-run:** 0 HIGH. The 15 left are exactly the planned config skips (B105×8,
        B107, B311×3, B404, B603, B101 in `tools/`) → step 7.
- [x] 7 Bandit config + CI job — 2026-10-01.
      - **Config `.bandit.yaml`:** skips B105/B106/B107, B311, B404, B603, and B101 in
        `tools/`, each with its reason.
      - **Deliberately no `exclude_dirs`:** Bandit matches them as path substrings,
        and "cwatm" silently excluded the whole repo (`cwatmpublic`). The first
        "0 findings" was hollow; caught by a negative test.
      - **No baseline file:** the backlog after step 6 is zero, so "block on new" =
        "block on any".
      - **CI job `bandit`:** lists every finding without failing, and **fails on HIGH
        severity with MEDIUM+ confidence**. Version pinned in `requirements_dev.txt`
        (`bandit==1.9.4`).
      - **Checked locally:** the repo passes (94 files, 35.5k lines, 0 findings). A
        sample of bad code fails on md5, `shell=True` and `verify=False`, and lists
        eval/pickle/yaml/mktemp/assert.
      - **New invariant:** every `# nosec` must name its check (`# nosec B110`) and
        carry `# B110 accepted: <why>` on the line above. The 3 accepted sites in
        `cwatm_gui.py` follow it.
- [ ] 8 Dependabot + pip-audit
- [ ] 9 CodeQL workflow
- [ ] 10 CodeQL first run triaged
- [ ] 11 Ruleset blocking new high alerts
- [ ] 12 Report-only CodeQL on `cwatm/`
- [ ] 13 Security Advisor after each `db push` (`test_server_sql.py` ✅ already in place)
- [ ] 14 Ruff `S` + pre-commit, PSScriptAnalyzer (optional)
- [ ] 15 Weekly review routine
