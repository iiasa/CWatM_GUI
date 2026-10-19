# CWatM GUI and CWatM account - privacy notice

**Version 2026-10-19 (DRAFT 6)** - proposed answers for every open point, and a new
section on what the GUI sends outside the account (maps, CWatM AI)

> **Draft for IIASA approval.** This notice describes what the CWatM GUI and its
> account server actually do. IIASA (legal / data protection) has to approve it before
> the account is opened to users and before the GUI is published in the Microsoft
> Store, which requires a privacy-policy URL. Every point IIASA has to decide carries
> a mark **[A1]** to **[A9]**: the text there is a *proposed* answer. The reasons, and
> what each answer depends on, are in *For IIASA: the points to approve* at the end;
> that section is removed before the notice is published.

## In short

- The CWatM account is **optional**. The CWatM GUI and the CWatM model work fully
  without it.
- With an account, every **full CWatM run** you make while logged in earns a point, and
  points earn river badges.
- We store your **username, email address, password (encrypted)** and, only if you enter
  them, your **name, country, institute and location** (latitude/longitude).
- For a counted run we store **only** the day it was counted and a **fingerprint** of
  the model settings
  (a one-way hash - it tells whether two runs used the same setup, but the settings
  cannot be read back from it). **Never** file paths, settings files, model data or
  results.
- If you agree, the **location of the first gauge** of every run that earns a point (rounded to
  about 100 m) is counted **anonymously** - without your name or account - to show where
  CWatM is used. See *Anonymous run locations* below.
- You can **see, export, change and delete** all of your personal data yourself in the
  account window.
- Without an account, IIASA receives nothing about you. The map backgrounds come from
  public map services, and the optional **CWatM AI** sends your questions to Google.
  See *Outside the account* below.

## Who is responsible

International Institute for Applied Systems Analysis (IIASA),
Schlossplatz 1, 2361 Laxenburg, Austria.
Contact for questions about this notice and your data: IIASA's Data Protection
Officer, **dataprotection@iiasa.ac.at**. **[A1]**

## What is stored, and why

| Data | Why | Where |
|------|-----|-------|
| Email address | log in, confirmation and password-reset codes | account server |
| Username | log in, shown on the leaderboard if you choose so | account server |
| Password | log in - stored only as a one-way hash, nobody can read it | account server |
| Name, country, institute *(optional)* | shown in your account; country on the leaderboard if you choose so | account server |
| Your location - latitude/longitude you enter, rounded to 0.5° (about 50 km) before it is stored *(optional)* | shown in your account. **Only if you tick** *Show my location on the world map* (optional and unticked on the Register form - tick it there or later in the account window): shown to every GUI user on the world map (Info ▸ World Map ▸ User location) as a point **without your name**, at the same 0.5° (~50 km), counted together with other users at the same place | account server |
| Leaderboard choice | whether your username, country and points are shown to other users (optional and unticked on the Register form - tick it there or later in the account window). The leaderboard shows your actual points (after Shop purchases) and your highest badge - never what you bought | account server |
| Points and badges | the purpose of the account | account server |
| When you last used CWatM GUI - the time of your last login - and every point decay (points taken, weeks without use, date) | your actual points shrink while CWatM GUI is not used (-3 % after one week, then -5 % a week, never below 5 points); earned points and badges never shrink | account server |
| Shop purchases - what you bought (a skill level or an animal for the live discharge plot), when, and the points paid; levels given for free to accounts that existed when the Shop opened are marked as given, and so is a reward animal (the mole, given for your first successful run with coupled MODFLOW - which records that such a run happened, and when) | so you can use what you bought, on any computer; your actual points are your earned points minus the points paid | account server |
| CWatM Academy progress - which Academy levels you finished | so you can continue the Academy on any computer; each finished level earns points. **Only while** *Link CWatM Academy to your login* is ticked (Preferences ▸ CWatM Academy, on by default); unticked, the progress stays on your computer only | account server |
| CWatM Academy Field Test highscore - your best score in the Field Test (one number) and the 2 to 3 initials you typed for it | shown in the Field Test window on any computer; it earns no points. While logged out the highscore stays on your computer only | account server |
| The number of your successful runs with coupled MODFLOW, with pySnowClim and with glaciers (one number each) | for the MoleFlow, pySnowClim and Glacier OGGM badges - bronze with the first such run (for MoleFlow together with the mole), silver at 20, gold at 50; they earn no points. Runs made while logged out are counted on your computer and sent at your next login | account server |
| Per run counted for one of these badges: which feature (MODFLOW, pySnowClim or glaciers), the fingerprint of the model settings (the same one-way hash as for a counted run) and the day - nothing else | a run counts for these badges under the same rules as for a point: the same settings count once per feature, and there is a daily limit | account server |
| The Field Test record of all users - the best score and the 2 to 3 initials its holder typed, and when it was set | shown to every GUI user in the Field Test window as *Highscore*, **without your name or username** - only the initials. It is not linked to your account, so it stays until someone beats it, also after your account is deleted | account server |
| Per counted run: a fingerprint of the model settings (SHA-256 one-way hash; Title, PathOut and output settings left out) and the day it was counted - nothing else | one point per distinct model setup (the same settings run again earn no further point); the day for the daily limit of counted runs | account server |
| Sent with a run but **not stored**: the number of timesteps | checked once against the minimum run length | - |
| Per finished CWatM Academy level: which level it was - no date | its points are paid once per level | account server |
| Version and time of your agreement to this notice | proof of your consent | account server |
| Whether (and since when) you agreed to the anonymous run locations | proof of that consent; only then is a location sent | account server |
| Per run that earns a point, *if you agreed*: the location of its first gauge, rounded to 0.001° (~100 m), counted per month - **without any link to you** | to know where CWatM is used and how often | account server, see below |
| Sign-in times; technical request logs including the IP address | security and operation of the service | account server (logs kept for up to 7 days by the hosting provider **[A5]**) |
| Failed logins by username (username and time) | protection against password guessing | account server, deleted after at most one day |

**Not collected:** file paths, names or contents of settings files, input data, model
results, your location, or any information about your computer beyond what every
internet request carries (the IP address in the server logs).

## Anonymous run locations

If you agreed, the GUI reports for every run that **earns a point** the **first coordinate pair of
`Gauges`** in the settings the run used (see the rules below). You are asked with a tick box when you
register (**optional, unticked** - registering does not depend on it) or, for older accounts, with a
one-time question at login (no answer preselected). You can change it at any time in the
account window or in Preferences ▸ Account.

- **Only runs that earn a point** are counted - long enough, a new model setup, within
  the daily limit. The location stays on your computer until the server has awarded
  the point, and is sent only then.
- It is stored **without your username, email or account** - only as *"one more run
  at this place in this month"*. There is no list of single runs, so it cannot be
  traced back to you, not even by the time of the run.
- The coordinates are **rounded to 0.001°** (about 100 m) before they are stored.
- Nothing is sent when `Gauges` is a map file or not a geographic longitude/latitude.
- Each location is sent on its own, never together with the points of the run.
- **Shown to everyone**: the totals per place - the number of runs, no users and no
  dates - are shown to every CWatM GUI user on a world map (**Info ▸ World Map**), one
  circle per place, larger for more runs. The map shows places only **rounded to 0.1°
  (about 10 km)**, coarser than they are stored.
- To prevent misuse, the server counts how many locations each account reported per
  day (a number, never a place). Counters older than yesterday are removed whenever a
  location is reported, and all of an account's counters go with the account.

Because these counts are **anonymous**, they **cannot be shown, exported or deleted per
person** - nothing connects them to you, and they stay after you delete your account.
Untick *Record the location of my runs* in the account window or in Preferences ▸
Account to stop further reports.

## What stays on your computer

- If *Stay logged in on this computer* is on: a login token in the **Windows Credential
  Manager** (on Linux the desktop keyring) - never in a plain file.
- The settings *Stay logged in* and *Count my full CWatM runs*, and the name of the
  last logged-in user (CWatM GUI settings).
- A copy of the list of Shop items you own (CWatM GUI settings), so a missing
  connection does not take a bought level away. It is only a copy - the account
  server decides what you own.
- Whether a reward (the mole) was earned while logged out and still waits to be
  collected at the next login, and whether you were told about it (CWatM GUI
  settings) - no details of the run.
- Runs finished while the server could not be reached, waiting to be sent
  (`account_pending.json` in the Run History folder): a random run number (only on
  your computer, to keep the list in order), the number of timesteps and the settings
  fingerprint. Removed when sent, at the latest after 30
  days.

## Outside the account **[A8]**

What CWatM GUI sends over the internet whether or not you have an account:

- **Map backgrounds.** The maps (Show Basin, NetCDF, World Map, CWatM Academy) load
  their background from public OpenStreetMap map services - mainly the map service of
  terrestris (Germany), in some views also the OpenStreetMap, OpenTopoMap and CARTO
  tile servers. Like any website, these services see your IP address and which part of
  the map is requested; they are not told who you are. Downloaded map pieces are kept
  in a cache on your computer (`%LOCALAPPDATA%\CWatM_GUI\cache`).
- **Public figures from the account server.** Info ▸ World Map and the CWatM Academy
  Field Test load public figures (the run-location totals, the user locations shown on
  the map, the Field Test record) from the account server, also without an account.
  The server's logs keep the IP address of these requests for up to 7 days **[A5]**;
  nothing else about you is sent.
- **CWatM AI** *(optional)*. Your questions are sent to **Google NotebookLM** and
  answered there, under your own Google account and Google's terms and privacy policy
  (policies.google.com/privacy). IIASA does not receive your questions or the answers.
  You sign in to Google in a separate, private browser window; the GUI then keeps that
  Google session in a file on your computer
  (`%USERPROFILE%\.notebooklm\profiles\…\storage_state.json`), so you do not have to
  sign in every time. Anyone with access to your Windows account could use that
  session. **Logout** in the CWatM AI window removes it.
- **Links.** Help ▸ CWatM Homepage and similar links open web pages in your browser;
  those websites' own privacy policies apply.

Everything else stays on your computer and is never sent: the diagnostic log
(`gui.log`), the Journal of Runs, your settings and the caches. In the Microsoft Store
version Windows keeps them in the app's own folder.

## Legal basis **[A2]**

IIASA processes these data in line with the principles and requirements of the EU
General Data Protection Regulation (GDPR) and relevant Austrian legislation.

- **The account and its data:** your **consent** (Article 6(1)(a) GDPR), given when you
  create the account (the tick box *I agree that these data are stored*). You can
  withdraw it at any time by deleting your account; this does not affect what was done
  before.
- **Anonymous run locations:** your separate consent (*Record the location of my runs*),
  which you can withdraw at any time by unticking it.
- **Sign-in times, request logs with IP addresses and failed-login records:** IIASA's
  legitimate interest in keeping the service secure and working (Article 6(1)(f) GDPR).

## Age **[A7]**

You need to be at least **16 years old** to create a CWatM account. The GUI and the
CWatM model can be used at any age without an account.

## Who processes the data

- **Supabase** hosts the account server (database and login) as IIASA's processor,
  under Supabase's data processing agreement. The data are stored in the **EU
  (Frankfurt, Germany)**. Supabase and the service providers it uses (for example
  Amazon Web Services for hosting, and tools for monitoring and support) may access them
  from outside the EU, mainly from the USA, to run and support the service; these
  transfers are covered by the **EU Standard Contractual Clauses** in that agreement.
  **[A3]**
- **IIASA's own mail server** delivers the confirmation and password-reset codes.
  **[A4]**
- Other users see your username, country and points **only if** you switch on the
  leaderboard.

The data are not sold, not used for advertising and not passed on to anyone else.

## How long

As long as your account exists. When you delete your account, your profile, points,
badges, Shop purchases, point decays and run records are deleted **immediately**.
Server backups and logs of the hosting provider keep copies for **up to 7 days**
before they are overwritten. **[A5]**

## Your rights

| You want to | How |
|-------------|-----|
| See everything stored about you | Account window ▸ **Export my data…** (a JSON file; your email address appears masked in it, e.g. `p***@g***.com`, so the file is safer to keep or pass on - the full address is shown in the account window) |
| Correct your data | Account window ▸ edit the fields ▸ **Save changes** (email address: write to the contact above **[A1]**) |
| Remove your location | Account window ▸ empty *latitude* and *longitude* ▸ **Save changes** |
| Take your location off the world map | Account window ▸ untick *Show my location on the world map* ▸ **Save changes** (it disappears from the map at once) |
| Delete everything | Account window ▸ **Delete account…** |
| Stop counting runs | Preferences ▸ Account ▸ untick *Count my full CWatM runs* |
| Stop recording run locations | Account window ▸ untick *Record the location of my runs anonymously* ▸ **Save changes**, or Preferences ▸ Account ▸ untick it (already recorded anonymous counts cannot be removed - see above) |
| Remove the login from this computer | Log out, or untick *Stay logged in on this computer* |
| Withdraw your consent | Delete your account |
| Restrict or object to processing, or ask anything else | write to the contact above **[A1]** |
| Complain | to the contact above, or to the Austrian data protection authority: Österreichische Datenschutzbehörde, Barichgasse 40-42, 1030 Wien, dsb@dsb.gv.at **[A6]** |

## Changes

If this notice changes in a way that matters, the new version is shown with a new date,
and you will be asked to agree again. **[A9]**

---

## For IIASA: the points to approve

*This section is for the review only and is removed before the notice is published.*

Each point names the question, the answer proposed in the text above, why that answer
is likely, and what IIASA has to confirm or do. The proposals follow the wording of
IIASA's own published data-protection information (for example the FeliX newsletter
consent declaration of February 2026), so that this notice matches IIASA's practice.

### A1 - Contact for data-protection questions

- **Proposed:** IIASA's Data Protection Officer, dataprotection@iiasa.ac.at.
- **Why:** this is the contact IIASA's other data-protection notices give.
- **To confirm:** whether routine account requests (such as changing an email
  address) should also go to the Data Protection Officer, or to a CWatM team mailbox
  that the CWatM team would name.

### A2 - Legal framework and legal basis

- **Proposed:** processing "in line with the principles and requirements of the GDPR
  and relevant Austrian legislation"; **consent** for the account and, separately, for
  the anonymous run locations; **legitimate interest** for the short-lived security
  logs and failed-login records.
- **Why:** IIASA's other notices use the same framework sentence and consent as the
  basis. Security logs are not something a user can meaningfully refuse while using an
  online account, so consent is a weak basis for them; legitimate interest is the usual
  choice.
- **To confirm:** the framework sentence; the legitimate-interest basis for logs;
  whether IIASA wants to add a sentence that the notice does not waive its privileges
  and immunities as an international organisation (IIASA's other notices do not
  include one).

### A3 - Supabase as processor, and transfers outside the EU

- **Proposed:** Supabase processes the data for IIASA under its data processing
  agreement; storage in Frankfurt; access from outside the EU covered by the EU
  Standard Contractual Clauses.
- **Why:** Supabase's data processing agreement is part of its Terms of Service and
  takes effect when they are accepted; it includes the EU Standard Contractual Clauses
  (controller to processor). Supabase's sub-processor list (12 October 2026) names
  mostly US companies (Amazon Web Services, Cloudflare and Google for hosting, Sentry
  for error monitoring, among others) and Supabase entities in the USA and Singapore;
  Supabase runs support and monitoring around the clock from several countries.
- **To confirm:**
  - that IIASA accepts transfers based on the Standard Contractual Clauses. IIASA's
    other notices say data go "only to countries for which the European Commission has
    decided" on adequate protection; that sentence cannot be used here as it stands,
    because the USA (for companies outside the EU-US Data Privacy Framework) and
    Singapore are covered by the clauses, not by such a decision;
  - whether IIASA wants a separately signed copy of the agreement, and that the
    Supabase organisation is held by an IIASA account (not a personal one) on the paid
    **Pro** plan (a free project pauses after a week without use).

### A4 - Who sends the confirmation and password-reset emails

- **Proposed:** IIASA's own mail server, connected to Supabase by SMTP.
- **Why:** Supabase's built-in sender is for testing only, and testing currently uses
  Gmail. With IIASA's own server no further company receives the email addresses.
- **To do:** IIASA IT provides an SMTP account and a sender address (for example a
  no-reply address at iiasa.ac.at). If IIASA prefers an email-sending service instead,
  it is named here and added as a processor.

### A5 - How long backups and logs keep data

- **Proposed:** up to **7 days**.
- **Why:** on Supabase's **Pro** plan, daily backups are kept for 7 days and logs for
  7 days. (Team plan: 14 days of backups, 28 days of logs. If point-in-time recovery
  is switched on, its own period of 7, 14 or 28 days applies instead.)
- **To confirm:** the plan the production project uses; the number is then fixed.

### A6 - Supervisory authority

- **Proposed:** Österreichische Datenschutzbehörde, Barichgasse 40-42, 1030 Wien,
  dsb@dsb.gv.at.
- **Why:** IIASA's other notices name this authority.
- **To confirm:** that IIASA names it here as well.

### A7 - Minimum age (new point)

- **Proposed:** 16 years for an account.
- **Why:** the account rests on consent, and the Microsoft Store requires apps to
  follow the laws on children's data. The GDPR sets 16 as the age for consent to
  online services; Austria lowers it to 14 (§ 4(4) DSG), other EU countries to 13 to
  15. One rule of 16 holds in every country; 14 would follow Austrian law only.
- **To confirm:** 16 or 14. The CWatM team then adds the age to the consent tick box of
  the Register form.

### A8 - Outside the account (new section)

- **Proposed:** the section *Outside the account* above.
- **Why:** the Microsoft Store policy (10.5.1) requires the privacy policy to cover
  everything the app sends, not only the account, and says Win32 desktop apps always
  need a privacy policy. The section names the map services, the public figures from
  the account server, Google NotebookLM for CWatM AI, and what stays on the computer.
  IIASA receives none of the CWatM AI data; Google and the map services act under
  their own terms.
- **To confirm:** the wording.

### A9 - Publication and later changes

- **Proposed:** the approved notice is published on a page of cwatm.iiasa.ac.at, and
  that address goes into the Microsoft Store listing.
- **To confirm:** the address, and who at IIASA approves later changes to the notice.
- **For the CWatM team before publishing:** remove the draft banner, the marks
  [A1]-[A9] and this section; give the notice its final version date; set the same
  date in `PRIVACY_VERSION` (`src/gui/utils/account_config.py`, checked by a test). The
  GUI does not yet ask existing users to agree again when the version changes, so
  either that is added, or the *Changes* section says users are told at their next
  login.
