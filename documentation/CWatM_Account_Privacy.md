# CWatM account - privacy notice

**Version 2026-09-28 (DRAFT 5)** - adds the anonymous run locations, their world map
and your optional own location (on the map only if you choose so)

> **Draft - not yet approved.** This notice describes what the CWatM GUI and its
> account server actually store. It must be reviewed and completed by IIASA (legal /
> data protection) before the account is opened to users. Parts in *[brackets]* still
> need to be filled in.

## In short

- The CWatM account is **optional**. The CWatM GUI and the CWatM model work fully
  without it.
- With an account, every **full CWatM run** you make while logged in earns a point, and
  points earn river badges.
- We store your **username, email address, password (encrypted)** and, only if you enter
  them, your **name, country, institute and location** (latitude/longitude).
- For a counted run we store **only**: when it was counted, the GUI version, the kind of
  run, the number of timesteps, the run time and a **fingerprint** of the model settings
  (a one-way hash - it tells whether two runs used the same setup, but the settings
  cannot be read back from it). **Never** file paths, settings files, model data or
  results.
- If you agree, the **location of the first gauge** of every run that earns a point (rounded to
  about 100 m) is counted **anonymously** - without your name or account - to show where
  CWatM is used. See *Anonymous run locations* below.
- You can **see, export, change and delete** all of your personal data yourself in the
  account window.

## Who is responsible

International Institute for Applied Systems Analysis (IIASA),
Schlossplatz 1, 2361 Laxenburg, Austria.
Contact for questions about this notice and your data: *[contact address - to be
filled in by IIASA]*.

## What is stored, and why

| Data | Why | Where |
|------|-----|-------|
| Email address | log in, confirmation and password-reset codes | account server |
| Username | log in, shown on the leaderboard if you choose so | account server |
| Password | log in - stored only as a one-way hash, nobody can read it | account server |
| Name, country, institute *(optional)* | shown in your account; country on the leaderboard if you choose so | account server |
| Your location - latitude/longitude you enter, stored to 0.001° *(optional)* | shown in your account. **Only if you tick** *Show my location on the world map* (off by default): shown to every GUI user on the world map (Info ▸ World Map ▸ User location) as a point **without your name**, rounded to 0.01° (~1 km), counted together with other users at the same place | account server |
| Leaderboard choice | whether your username, country and points are shown to other users (off by default) | account server |
| Points and badges | the purpose of the account | account server |
| Per counted run: date and time, GUI version, run kind (run / windowed / batch), number of timesteps, run time, a random run number | to award a point once per run, and to check the rules (e.g. a minimum run length) | account server |
| Per counted run: a fingerprint of the model settings (SHA-256 one-way hash; Title, PathOut and output settings left out) | one point per distinct model setup - the same settings run again earn no further point | account server |
| Version and time of your agreement to this notice | proof of your consent | account server |
| Whether (and since when) you agreed to the anonymous run locations | proof of that consent; only then is a location sent | account server |
| Per run that earns a point, *if you agreed*: the location of its first gauge, rounded to 0.001° (~100 m), counted per month - **without any link to you** | to know where CWatM is used and how often | account server, see below |
| Sign-in times; technical request logs including the IP address | security and operation of the service | account server (logs kept for a limited time by the hosting provider) |
| Failed logins by username (username and time) | protection against password guessing | account server, deleted after at most one day |

**Not collected:** file paths, names or contents of settings files, input data, model
results, your location, or any information about your computer beyond what every
internet request carries (the IP address in the server logs).

## Anonymous run locations

If you agreed, the GUI reports for every run that **earns a point** the **first coordinate pair of
`Gauges`** in the settings the run used (see the rules below). You are asked with a tick box when you
register (**ticked by default** - untick it to decline) or, for older accounts, with a
one-time question at login (**Yes** preselected). You can change it at any time in the
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
  circle per place, larger for more runs.
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
- Runs finished while the server could not be reached, waiting to be sent
  (`account_pending.json` in the Run History folder): run number, GUI version, run kind,
  timesteps, run time, settings fingerprint. Removed when sent, at the latest after 30
  days.

## Legal basis

Your **consent**, given when you create the account (the tick box *I agree that these
data are stored*). You can withdraw it at any time by deleting your account.
*[To be confirmed by IIASA with regard to its status as an international organisation
and its own data protection rules.]*

## Who processes the data

- **Supabase Inc.** hosts the account server (database and login). The data are stored
  in the **EU (Frankfurt, Germany)**. *[Data processing agreement with Supabase and any
  access from outside the EU (e.g. support) - to be confirmed by IIASA.]*
- An **email provider** delivers the confirmation and password-reset codes.
  *[Provider to be named - during testing: Google Gmail.]*
- Other users see your username, country and points **only if** you switch on the
  leaderboard.

The data are not sold, not used for advertising and not passed on to anyone else.

## How long

As long as your account exists. When you delete your account, your profile, points,
badges and run records are deleted **immediately**. Server backups and logs of the
hosting provider may keep copies for a short period *[number of days - to be filled in
from the Supabase plan]* before they are overwritten.

## Your rights

| You want to | How |
|-------------|-----|
| See everything stored about you | Account window ▸ **Export my data…** (a JSON file) |
| Correct your data | Account window ▸ edit the fields ▸ **Save changes** (email address: contact us) |
| Remove your location | Account window ▸ empty *latitude* and *longitude* ▸ **Save changes** |
| Take your location off the world map | Account window ▸ untick *Show my location on the world map* ▸ **Save changes** (it disappears from the map at once) |
| Delete everything | Account window ▸ **Delete account…** |
| Stop counting runs | Preferences ▸ Account ▸ untick *Count my full CWatM runs* |
| Stop recording run locations | Account window ▸ untick *Record the location of my runs anonymously* ▸ **Save changes**, or Preferences ▸ Account ▸ untick it (already recorded anonymous counts cannot be removed - see above) |
| Remove the login from this computer | Log out, or untick *Stay logged in on this computer* |
| Withdraw your consent | Delete your account |
| Complain | to the contact above, or to a data protection supervisory authority *[applicable authority - to be confirmed by IIASA]* |

## Age

The CWatM account is meant for people aged **16 or older**.

## Changes

If this notice changes in a way that matters, the new version is shown with a new date,
and you will be asked to agree again.
