# Security & privacy review – CWatM GUI + Supabase account

*Reviewed 2026-10-01 by reading the code: `src/gui/**`, `cwatm_gui.py`,
`supabase/migrations/*`, `supabase/functions/*`, and the CWatM model where the GUI
runs it. Nothing was tested against the live server. Settings that live only in the
Supabase dashboard (not in this repo) are marked **not verified**.*

## Summary – what to fix, by severity

| # | Severity | Finding | Where |
|---|----------|---------|-------|
| 1 | ~~**High**~~ **FIXED in CWatM 2026-10-01** | A crafted **settings file** or **NetCDF input file** could make CWatM run arbitrary code (`eval`/`exec` on its contents) - the realistic watering-hole route. **Fixed at the source:** the current `cwatm/` has no `eval`/`exec`. It parses output entries with `parseoutvar` (name + whole-number indices, otherwise **Error 135**) and reads them with `getattr`, and copies NetCDF attributes with `setattr`. So runs outside the GUI are protected too. **GUI side:** `run_guard.py` now only gives CWatM's own Error-135 verdict early, with the lines named (tested against CWatM's `parseoutvar`; 400 real settings files: none stopped). The interim NetCDF warning was removed, since there is no `exec` left to guard. Confirmation from outside: the report-only CodeQL scan of `cwatm/` (sast.md step 12) should show no code-injection alerts. | `cwatm/management_modules/output.py`, `data_handling.py` |
| 2 | ~~**Medium**~~ **FIXED 2026-10-01** | The map/plot windows ran Chromium **without its sandbox, always**, and executed JavaScript **downloaded at run time from CDNs**, cached unchecked in the temp folder. Now Leaflet ships with the app, pinned by SHA-256; unpinned remote scripts are removed, never fetched; tile caches are per user; the sandbox is off only on a network path / non-Windows. | `src/gui/utils/web_assets.py`, `assets/web/` |
| 3 | **Medium – partly fixed** | The exe/installer is **unsigned** and handed out from a **network share**: whoever can write there can replace it for every user. Now `SHA256SUMS.txt` is published and every copy is hash-checked, and the build signs automatically once a certificate exists. **Still open:** getting the certificate, and making the share read-only (see the admin checklist). | `build_release.ps1`, `publish_gui.ps1` |
| 4 | ~~**Medium (privacy law)**~~ **FIXED 2026-10-01** | At registration the **run-location consent was mandatory**, and the leaderboard / world-map boxes were **pre-ticked**. Under the GDPR neither counts as valid consent. Now all three are optional and unticked, the one-time question has **No** as its default button and is not asked again right after registering, and Preferences shows "no" while logged out. | `account_dialogs.py` Register tab, `account_ui.py` |
| 5 | **Medium** | CWatM AI's login **reads the Google cookies out of the user's browsers**, and the NotebookLM library keeps that Google session in a file. | `notebooklm_window.py`, notebooklm-py |
| 6 | Low – **XFF part FIXED and deployed 2026-10-01** | The login function passed the client's `X-Forwarded-For` on (spoofable) – removed. Still: anyone can **lock a known username out** for 15 min (the email login keeps working). | `functions/login-with-username` |
| 7 | Low | It can be found out whether a username or an email address has an account. | `username_available`, sign-up |
| 8 | Low | Points and run locations are whatever the client reports: fake runs (≤ 20/day) and fake locations (≤ 50/day) per account. | `award_run`, `record_run_location` |
| 9 | Low (privacy) | The **public** run-location map is at **0.001° (~100 m)**, much finer than the 0.5° used for people. | `get_run_locations` |
| 10 | Info | The export file holds personal data, but nothing that lets anyone log in. | `export_my_data` |
| 12 | ~~**Medium**~~ **FIXED 2026-10-01** | **Links and HTML in rich-text views.** The CWatM AI transcript and the Help viewer used `setOpenExternalLinks(True)`, which hands ANY link to the desktop - a `file:///…/x.exe` or `\\server\share\x.bat` link would run that program on a click. CWatM AI answers (from outside) were rendered with raw HTML allowed. Now every link goes through `open_path.open_link` (http/https/mailto only, local non-program files via `open_path`, no network shares, `#anchors` scroll), AI answers render with `html=False`, and `check_invariants.py` forbids `setOpenExternalLinks(True)` and un-noted rich-text sinks (sast.md step 4). | `notebooklm_window.py`, `main_window.py` (Help), `open_path.py` |
| 11 | ~~**Medium**~~ **FIXED 2026-10-01** | **Process launching (bandit B602/B603/B606/B607).** The model run, the CWatM AI login and the Linux file opener already used an argument **list**, no shell (unchanged, so runs stay bit-identical). Two real gaps, both fixed: (a) **Output Explorer / Restore settingsfile** handed any file from an output folder to `os.startfile`, so a `.bat`/`.exe`/`.vbs`/`.js`/`.lnk`… placed in a (shared) PathOut **ran on a double-click** → `open_path` now opens the folder instead (`RUNNABLE_EXTENSIONS`). (b) **Create batch** wrote paths into a `.bat` where `cmd` expands `%NAME%` even inside quotes (a real test showed `%PATH%` replaced by the whole system PATH) → `%` is written as `%%`; a `"` or line break is refused. `tools/check_invariants.py` now rejects `shell=`, `os.system`, `os.popen` and single-string `subprocess` commands anywhere in the GUI. | `open_path.py`, `batch_file_creator.py` |

**What is solid:**
- Every table has row level security; client rights were revoked and granted back column by column.
- All server functions are `security definer` with `search_path = ''` and no dynamic SQL, so no SQL injection was found.
- The admin helpers (`_email_for_username`, …) are `service_role` only.
- The **service-role key is not in the GUI or the repo**; only the publishable key is.
- The refresh token sits in the OS keyring.
- Data minimisation is done: a run is a fingerprint + a day, and the export masks the email.
- A compromised account server **cannot run code in the GUI**: everything it returns is shown as plain text or numbers.

---

## 1. Are the data we require OK to ask for?

Required at registration: **username, email, password, agreement to the privacy notice** (version + time stored) and – currently – the **run-location consent**.

- **Username, email, password: yes.** The email is needed for the confirmation and password-reset codes. The username is a pseudonym, and the password is stored only as a hash by Supabase Auth.
- **Consent record: yes.** That is your proof of consent (accountability).
- **Run-location consent as a condition of registering: no (finding 4).**
  - Consent must be *freely given*. Making an account depend on agreeing to an unrelated processing is the textbook case of invalid consent (GDPR Art. 7(4)).
  - The locations are stored anonymously, but the request that reports them is authenticated (account + IP), so it is personal data in transit.
  - **Fix:** make the tick optional (pre-filled is not enough – see the next point).
- **Pre-ticked boxes** for *Show me on the leaderboard* and *Show my location on the world map* (and the location tick): a pre-ticked box is **not valid consent** (CJEU *Planet49*, C-673/17).
  - **Fix:** start them unticked. Also the "Yes preselected" one-time location question for older accounts → no preselection.
- Whether the GDPR applies to IIASA as an international organisation is for IIASA legal; the notice already flags it. Following the GDPR anyway is the safe default.

## 2. Is the user's own location at 0.5° (~50 km) OK?

**Yes.** 0.5° is about 55 km north–south and 35 km east–west at 50°N, i.e. a region, not a town.
- It is optional.
- It is rounded **on the server** by a trigger, so a precise value is never stored.
- It appears on the public map only for users who opt in, and without names.

Residual risk is small. In a very sparse region one point, combined with the country and institute someone shows on the leaderboard, could narrow it to a person – acceptable at this precision.

**But see finding 9:** the *run* locations on the public map are at 0.001° (~100 m), 500× finer.
- A single run at an unusual gauge in a month, combined with knowing who models that river, says more about a person than the 0.5° home location does.
- **Fix:** coarsen the *public* output (e.g. 0.1°), and/or show only places with at least 2–3 runs. Stored data can stay as is.

## 3. The email address

### In Supabase
- **Where it is stored:** in `auth.users` (Supabase Auth), in the EU (Frankfurt) region, on Supabase's managed Postgres. Supabase states that it encrypts at rest and in transit – **not verified** here.
- **Who can read it:**
  - only the project's admins (dashboard / SQL editor);
  - anything holding the **service-role key** – it exists only in the two Edge Functions' environment;
  - Supabase staff (support);
  - the **mail provider** that sends the codes. The notice says *"during testing: Google Gmail"*: a personal Gmail as sender is a weak point. If it is taken over, someone can send official-looking CWatM mails.
- **Not readable through the API:** the `auth` schema is not exposed, and `profiles` (read-own) does not contain the email.
  - `_email_for_username` is `service_role` only.
  - `login-with-username` uses it server-side and returns a session **only after the right password**, never another user's address.
- **To do (dashboard, not verified):**
  - MFA for every Supabase organisation member, and as few members as possible;
  - a proper SMTP sender with a DPA (IIASA's own or a transactional provider), not a personal Gmail;
  - "leaked password protection" (Pro plan);
  - consider a minimum password length of 10–12.

### In the CWatM GUI
- The GUI holds **only its own user's** email, in memory while logged in, and shows it in the account window.
- It is **never written to disk** (checked: no `QSettings` key, no log line contains it). `gui.log` never logs request arguments.
- The data export masks it (`p***@g***.com`).
- **"Hacking the app"** (decompiling the exe) yields only the URL and the **publishable key**. Both are public by design and give no more than any anonymous visitor has. There are no other users' emails and no admin key in the app.
- **Malware already running as the user** can read the refresh token from the Windows Credential Manager and use that user's own account (and see their email). That is inherent to any "stay logged in"; the impact is limited to that one CWatM account.

## 4. Can someone attack the database through CWatM GUI?

The GUI is **not a privileged way in**: anyone can talk to the API directly with the public key, so the protection has to be – and is – on the server.

- **Row level security** on every table. Clients start from *no* rights; only "read your own rows" plus a list of profile columns they may edit are granted back.
  - Points, badges, purchases, decay and Academy progress are written **only** by server functions.
- **Server functions:** `security definer` + `search_path = ''` (no search-path hijack); parameters only, **no dynamic SQL** (no SQL injection); inputs checked (regexes, ranges); `EXECUTE` revoked from everybody, then granted per function.
- **Edge Functions:** they validate their input and use the service key server-side only. `delete-account` re-checks the password.

Residual abuse (low – these are about the game, not the data):
- **Fake points (finding 8):** any account can report invented runs, up to the daily cap of 20, and invented locations, up to 50/day. Several accounts multiply that.
  - This cannot be fully prevented with client-reported runs.
  - Keep the caps; watch the leaderboard; points buy nothing that the Cheat tick does not give for free.
- **Lock-out and rate-limit evasion (finding 6):**
  - 10 wrong passwords lock a username for 15 minutes, and usernames are visible on the leaderboard. The victim can still log in with the email.
  - The function forwards the client's `X-Forwarded-For`, which a client can forge, so the per-IP limit of Auth may be bypassed.
  - **Fix:** forward only the address the edge platform itself saw (the last hop, or Supabase's own client-IP header), or drop the forwarding.
- **Enumeration (finding 7):** `username_available` (needed for registration) and the sign-up answer "an account with this email exists" reveal that someone uses CWatM. Low; acceptable for usernames. For emails, a neutral message ("check your inbox") would hide it.

## 5. Can CWatM GUI be used as a watering hole?

That is, can an attacker use the program (or what it loads) to infect its users? **Yes, through these routes, most important first:**

1. **Shared model setups and data – High (finding 1).** CWatM runs code taken from its inputs (verified in the `cwatm/` submodule, which the GUI may not change):
   - **Settings file:** `output.py` checks only the part before `[` of an `OUT_MAP_…`/`OUT_TSS_…` variable name, then evaluates `"self.var." + name` with `eval`. A value like `discharge[<python expression>]` passes the check, and the expression runs when the model starts writing output.
   - **NetCDF input file:** `data_handling.py` copies the attributes of an input file with `exec('longitude.<name>="<value>"')`. An attribute value containing a `"` breaks out of the string and runs code.
   - **Why it matters:** settings files and input maps are exactly what researchers download and pass on. Opening such a setup and pressing RUN is enough. This includes Windowed/Batch runs and *Create batch*.
   - **Fix (upstream, in CWatM):** replace `eval`/`exec` with `getattr`/`setattr` plus an integer index.
   - **Interim fix (possible in the GUI, without touching `cwatm/`):** before any run, refuse output names whose index is not a plain number. *Check settingsfile* already flags these (`var_dims.dim_problem`), but does not block a run. Warn when the mask/metadata NetCDF has attribute values containing quotes or line breaks.
   - **Status 2026-10-01: both done.** The interim GUI guard went in first. Then CWatM itself was fixed (no `eval`/`exec`; `parseoutvar` + `getattr`/`setattr`, Error 135 for a bad entry). The GUI guard now mirrors Error 135, and the NetCDF warning was removed. This route is closed.
2. **Run-time JavaScript in an unsandboxed browser – Medium (finding 2).**
   - The map windows download Leaflet/folium JavaScript from public CDNs at run time. They cache it in `%TEMP%\cwatm_web` (on Linux the **shared** `/tmp/cwatm_web`) **without checking a hash**, and run it in QtWebEngine started with `--no-sandbox` – **always**, although the sandbox is only a problem when the exe runs from a network path.
   - A compromised CDN file – or, on a shared Linux machine, another user planting a file in `/tmp/cwatm_web` – runs JavaScript in a browser engine whose renderer is not isolated. A browser exploit then becomes a full compromise of the user.
   - **Fix:**
     - bundle the few JS/CSS files with the app (or check them against pinned SHA-256 hashes);
     - use a per-user cache folder (`%LOCALAPPDATA%` / `~/.cache`) instead of the shared temp directory;
     - disable the sandbox only when actually running from a network path.
3. **The download itself – Medium (finding 3).**
   - `CWatM_GUI_Setup.exe` / the zip are **unsigned** and published from `P:\watmodel\CWatM_GUI`.
   - Anyone with write access to that share – or to the GitHub release – can swap in a modified build, and nobody would notice.
   - **Fix:** Authenticode-sign the setup and both exes; make the share read-only for everyone but the release maintainer; publish SHA-256 checksums.
4. **Not routes (checked):**
   - **The account server:** its answers are shown as plain text (`QTableWidgetItem`, plain labels) or used as numbers. Usernames are restricted to `[A-Za-z0-9_.-]`, and badge images are local files. A compromised server can show wrong data but cannot run code in the GUI.
   - **The tile/WMS proxy:** it fetches only a fixed list of providers (no arbitrary URLs).
   - **The Excel formula engine:** an `ast` whitelist, never `eval`.

## 6. The exported data (`cwatm_account_data.json`)

- **What is in it:**
  - the masked email and account dates;
  - the profile: internal id, username, optional name/country/institute, the 0.5° location, the opt-in flags, the consent version + time, Academy levels, last use;
  - per counted run a settings fingerprint + day;
  - badges, purchases, point decays, and the earned/actual points.
- **No password, no token, no key.** The file **cannot be used to log in** or to reach the database. The internal id is not a secret – it is useless without a session.
- **Is it a danger to the system?** No. The GUI only *writes* it and never reads it back, so a tampered file has no way in. The server knows nothing about the file.
- **Is it a danger to the person?** Somewhat. It is personal data, so whoever gets it learns those facts.
  - The run fingerprints are one-way, but someone who has a *candidate* settings file can compute its fingerprint and check whether this person ran exactly that setup. That's minor.
  - Advice in the notice: "keep it like any personal document".

## 7. Is "Export my data" required?

**Legally, the *right* is required; the *button* is not.** Under the GDPR every user may ask for a copy of their data (Art. 15) in a machine-readable form (Art. 20). Answering such requests by email within one month would also comply.

The self-service button is the cheapest compliant way (no manual work, no identity checks by email), and it shows openness. **Recommendation: keep it.**

---

## Recommended actions, in order

1. **GUI guard against code injection** (finding 1): block a run when an `OUT_*` value has a non-numeric index; warn on suspicious NetCDF attribute values. **Report the `eval`/`exec` use to the CWatM maintainers** for a proper fix in the model.
2. **Registration consent** (finding 4): run-location consent optional; leaderboard / world-map / location boxes **unticked** by default; no preselected "Yes".
3. **Release integrity** (finding 3): sign the binaries, make the share read-only, publish checksums.
4. **Web content** (finding 2): bundle or hash-pin the map JavaScript; per-user cache; sandbox off only on network paths.
5. **Supabase dashboard** (not verified): MFA for all members, few members, a proper SMTP sender with a DPA, leaked-password protection, a longer minimum password.
6. **Login function** (finding 6): stop forwarding the client-supplied `X-Forwarded-For`.
7. **Public run map** (finding 9): coarsen to 0.1° and/or a minimum count per place.
8. **CWatM AI** (finding 5): say clearly in the window and the privacy notice that the browser-cookie login reads the Google session from the browser and keeps it on this computer. Prefer the interactive login where possible.

---

## Admin checklist – what only a person with the right access can do

Status 2026-10-01. Tick when done.

### Release integrity (finding 3)
- [ ] **Code-signing certificate** (IIASA IT; an OV/EV code-signing cert). Install it in
      the build account's certificate store, then build with
      `$env:CWATM_SIGN_THUMBPRINT = '<thumbprint>'` (or `-SignThumbprint`):
      `build_release.ps1` then signs `CWatM_GUI.exe`, `CWatM_model.exe` and
      `CWatM_GUI_Setup.exe` (signtool, SHA-256, timestamped). Without it the build
      prints "NOT signed" and goes on.
- [ ] **`P:\watmodel\CWatM_GUI` read-only** for everyone except the release
      maintainer(s) (NTFS rights on the share - IIASA IT). Same for the repo's
      `dist\` / `installer\Output\` folders if users take files from there.
- [ ] **GitHub**: protect `main` (no force-push), require 2FA for everyone with write
      access, and attach releases only from the maintainer account.
- [x] `SHA256SUMS.txt` is published next to the setup and the zip by `/creategui`
      (`publish_gui.ps1`), after checking each published copy against the build.
      Users can verify with `Get-FileHash CWatM_GUI_Setup.exe -Algorithm SHA256`.

### Supabase dashboard (finding 5 of the action list - not verifiable from the repo)
- [ ] **Organization ▸ Members**: as few members as possible; **MFA required** for
      all (Organization settings ▸ Security ▸ enforce MFA).
- [ ] **Authentication ▸ Emails ▸ SMTP**: a proper sender (IIASA's mail server or a
      transactional provider such as Resend/SendGrid/Brevo) with a data processing
      agreement - **not a personal Gmail**. Update the privacy notice's provider line.
- [ ] **Authentication ▸ Policies / Passwords**: enable **leaked password protection**
      (HaveIBeenPwned check, Pro plan); consider raising the minimum length to 10-12
      (then change `PASSWORD_MIN` in `src/gui/utils/account_validation.py`).
- [ ] **Authentication ▸ Rate limits**: check sign-up / sign-in / email limits are on.
- [ ] **Project Settings ▸ API Keys**: the secret / service-role key is used only by
      the two Edge Functions; rotate it if it was ever pasted anywhere else.
- [ ] **Billing**: the Pro plan keeps the project from pausing (and is needed for
      leaked-password protection).

### Deploy the changed login function (finding 6) — done 2026-10-01
```powershell
npx supabase functions deploy login-with-username --no-verify-jwt
```
