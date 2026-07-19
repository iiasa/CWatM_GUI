# CWatM AI — NotebookLM Help

**CWatM AI** is the chat window opened from the **CWatM AI** button in the menu bar
(left of *Help*). It answers questions about CWatM using Google **NotebookLM**
(Gemini) grounded on a predefined CWatM notebook (the CWatM documentation PDF). To
use it you sign in **once** with your Google account; after that the GUI reuses the
stored session automatically.

This page covers:

1. [What NotebookLM is (and why it needs a login)](#1-what-notebooklm-is)
2. [Logging in — several options](#2-logging-in--several-options)
3. [Using the CWatM AI chat window](#3-using-the-cwatm-ai-chat-window)
4. [Getting good answers (NotebookLM best practices)](#4-getting-good-answers)
5. [Troubleshooting](#5-troubleshooting)

---

## 1. What NotebookLM is

NotebookLM is an AI research assistant built on a different idea from a general
chatbot: **grounding**. Instead of answering from the whole internet, it is a closed
Retrieval-Augmented-Generation (RAG) system limited to the **sources in the
notebook** — for CWatM AI that is the CWatM documentation. This makes answers
verifiable and greatly reduces made-up ("hallucinated") replies, at the cost that it
will only answer from what is in the CWatM sources.

### Why a login is needed

CWatM AI talks to your own NotebookLM account, so it needs a **Google session**.
It does not ask for your password inside CWatM — instead it reuses the sign-in you
already have (browser cookies) or lets you sign in through a Google window. The
result is a small session file stored on your machine that the GUI reads on every
later run.

### Account prerequisites (one-time)

- A **personal Google account**, or a **Workspace / school account** (Workspace
  accounts may need administrator approval for NotebookLM).
- You must be **signed in to Google** in whichever browser you use for the login.
- Visit **notebooklm.google.com** once in that browser and sign in, so the account
  is active and any **age verification** is done (Google Account →
  *"Access age-restricted content and features"*). This is a common first-time
  snag; if NotebookLM works in the browser, CWatM AI can use it.

---

## 2. Logging in — several options

Click **Login…** in the CWatM AI window. A dialog offers the options below. The
login-state line at the top of the window shows **✓ Logged in** (blue) when a working
session is confirmed, **Checking…** while it verifies, or **Login required** (red)
when you need to sign in.

> **Which should I pick?**
> - Signed in to Google in **Firefox** → **From Firefox** (easiest, no admin).
> - Signed in only in **Chrome / Edge / Opera** → **Run CWatM as administrator**
>   first, then **From Chrome / Edge / Opera**.
> - Running CWatM **from source** and want a fresh interactive sign-in →
>   **Google login window**.

### Option 1 — From Firefox *(recommended, no admin)*

If you are signed in to your Google account in **Firefox**, choose **Login… → From
Firefox**. CWatM reads the Google session cookie from Firefox and stores it. This is
the most reliable path on Windows and needs **no administrator rights**.

### Option 2 — From Chrome / Edge / Opera *(needs "Run as administrator")*

Chrome, Edge and Opera share the Chromium cookie store, which on current Windows is
**app-bound-encrypted** — a security feature that stops other programs from reading
those cookies unless they run **elevated**. So:

1. Close CWatM.
2. **Right-click `CWatM_GUI.exe` → *Run as administrator*.**
3. Open **CWatM AI → Login… → From Chrome** (or *From Edge* / *From Opera*).

If you try this **without** administrator rights you will get a message like
*"…can be decrypted only when running as admin due to app-bound encryption…"* — that
is expected; run elevated and try again, or use Firefox.

> After the session is stored you can go back to running CWatM **normally
> (non-elevated)** — the elevation is only needed for the one-time cookie read.

### Option 3 — Google login window *(interactive; running from source only)*

When you run CWatM **from source** (not the packaged `.exe`), the dialog also offers
**Google login window**. This opens a real browser (your installed Google Chrome, or
a bundled Chromium as a fallback), you sign in to Google there, and the session is
captured directly — **no cookie decryption and no administrator rights** needed.

This option needs the **Playwright** package, which is not included in the packaged
executable, so the button appears **only when running from source**. Install it once
with `pip install playwright` if it is missing.

### After you log in

- CWatM verifies the new session in the background and the login line turns
  **✓ Logged in** (blue).
- The session **persists across restarts** — you normally log in only once, until
  Google expires it (then the window will say *Login required* again and offer to
  re-authenticate).

---

## 3. Using the CWatM AI chat window

- **Ask a question:** type in the input box and press **Enter** (use **Shift+Enter**
  for a new line) or click **Send**. Answers stream back from Gemini and are shown as
  formatted **Markdown** (bold, lists, tables, code).
- **Answer length:** the **Short / Medium / Long** toggle (bottom row) sets how
  detailed replies are. Your choice is remembered.
- **Question history:** press **Up / Down** in the input box to recall previous
  questions. The whole transcript and your question history are **kept across
  close/open**.
- **🎤 Voice:** the microphone button dictates your question by speech (needs a
  microphone and internet; it simply types the recognised words into the input box).
- **Notebook…:** by default CWatM AI auto-selects the notebook whose title contains
  *"CWatM"*. Use **Notebook…** to point at a specific notebook id or URL if you keep
  your own.
- **Clear / Exit:** clear the transcript, or close the window (your session and
  history are saved either way).

### Settings bridge (source of the questions ↔ your settings file)

Two buttons above the input link the chat to the settings editor:

- **→ Settings** takes a marked `key = value` line from an answer and inserts/updates
  it in the settings file under the right `[SECTION]`, then jumps the editor to it.
- **Explain current line** asks NotebookLM to explain the settings line your editor
  cursor is on.

---

## 4. Getting good answers

CWatM AI is only as good as the **grounding** and your prompt. Tips adapted from the
NotebookLM onboarding guidance:

- **Be specific.** Instead of *"explain routing"*, try *"What does the
  `PathOut` option control and what files are written there?"* Specific keywords help
  it retrieve the right passage.
- **Verify with citations.** NotebookLM answers point back to the source. Don't just
  read the snippet — read a little before and after it to be sure a detail wasn't
  taken out of context. Cross-check when several citations appear.
- **Why it may decline.** If an answer is refused or "not found", it is usually
  because the question is **outside the CWatM sources**, the phrasing was unclear
  (re-prompt with exact keywords), or a safety filter triggered. Staying inside its
  "grounded box" is by design.
- **Summarise a session.** At the end, ask it to *"summarise the key points of this
  chat"* so you can pick up where you left off next time.

> CWatM AI is an **experimental** aid. Its grounding makes it far more accurate than a
> generic chatbot, but it is not infallible — treat it as a research partner, verify
> against the CWatM documentation and code, and never rely on it as the final
> authority for a decision.

For the full NotebookLM feature set (creating notebooks, adding your own sources,
Studio outputs such as audio/video overviews and mind maps, subscription tiers), use
the NotebookLM website directly at **notebooklm.google.com** — the CWatM AI window is
a focused chat client over the CWatM notebook, not the full NotebookLM studio.

---

## 5. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| **"Login required"** (red) after it worked before | The Google session expired. Click **Login…** and sign in again (Firefox = no admin; Chrome/Edge/Opera = run as administrator). |
| **"…can be decrypted only when running as admin…"** | App-bound encryption on Chrome/Edge/Opera. **Run CWatM as administrator**, then retry that browser — or use **From Firefox**. |
| **"From Chrome/Edge" reads nothing / no account** | You are not signed in to Google in that browser, or the wrong profile. Sign in to Google there first. |
| **No "Google login window" button** | That option needs Playwright and appears **only when running from source**; install with `pip install playwright`. |
| **CWatM AI button does nothing / import error** | The NotebookLM libraries are unavailable in this build. Asking questions with a stored session works in the packaged exe; if it degrades, run from source with `pip install "notebooklm-py[cookies]"`. |
| **Voice does nothing** | Needs a working microphone and the optional `SpeechRecognition` + `PyAudio` packages; it degrades gracefully if they are missing. |

---

*This help describes the CWatM AI window and its login. General NotebookLM concepts
(grounding, sources, verification) are summarised from Google's NotebookLM onboarding
material.*
