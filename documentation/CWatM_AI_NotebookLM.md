# CWatM AI — NotebookLM Help

**CWatM AI** is the chat window opened from the **CWatM AI** button in the menu bar
(left of *Help*). It answers questions about CWatM using Google **NotebookLM**
(Gemini) grounded on a notebook that holds the CWatM documentation. To use it you (1)
**prepare a notebook** with the CWatM sources once, and (2) **sign in** once with your
Google account. After that the GUI reuses the stored session automatically.

This page covers:

1. [What NotebookLM is (and why it needs a login)](#1-what-notebooklm-is)
2. [Prepare a NotebookLM notebook with CWatM sources](#2-prepare-a-notebooklm-notebook)
3. [Logging in — one click](#3-logging-in--one-click)
4. [Using the CWatM AI chat window](#4-using-the-cwatm-ai-chat-window)
5. [Getting good answers](#5-getting-good-answers)
6. [Troubleshooting](#6-troubleshooting)

---

## 1. What NotebookLM is

NotebookLM is an AI research assistant built on a different idea from a general
chatbot: **grounding**. Instead of answering from the whole internet, it is a closed
Retrieval-Augmented-Generation (RAG) system limited to the **sources in the
notebook** — for CWatM AI that is the CWatM documentation. This makes answers
verifiable and greatly reduces made-up ("hallucinated") replies, at the cost that it
will only answer from what is in the CWatM sources.

### Why a login is needed

CWatM AI talks to **your own** NotebookLM account, so it needs a **Google session**.
It does not ask for your password inside CWatM — instead it reuses the sign-in you
already have in a browser (via cookies). The result is a small session file stored on
your machine that the GUI reads on every later run.

### Account prerequisites (one-time)

- A **personal Google account**, or a **Workspace / school account** (Workspace
  accounts may need administrator approval for NotebookLM).
- You must be **signed in to Google** in whichever browser you use for the login.
- Visit **notebooklm.google.com** once in that browser and sign in, so the account
  is active and any **age verification** is done (Google Account →
  *"Access age-restricted content and features"*). This is a common first-time snag;
  **if NotebookLM works in the browser, CWatM AI can use it.**

---

## 2. Prepare a NotebookLM notebook

Do this once in your browser at **notebooklm.google.com**. The goal is a notebook that
(a) is named so CWatM AI can find it and (b) contains the CWatM documentation.

1. **Create a new notebook.** Give it a title that contains the word **"CWatM"** (for
   example `CWatM`). CWatM AI auto-selects the notebook whose title contains *cwat*, so
   this name lets the GUI find it automatically — no id to configure.
2. **Add the CWatM sources.** Click **+ Add source** and upload the CWatM
   documentation. The GUI ships one ready to use:
   - **`documentation/CWATM_shorter.pdf`** — the condensed CWatM documentation, a good
     default single source;
   - optionally the **CWatM model-description papers** (the *GMD* CWatM papers and their
     supplement) and any of **your own** CWatM notes, protocols or settings guides.

   The more focused and CWatM-specific the sources, the better and more grounded the
   answers. Avoid adding unrelated material — it only dilutes retrieval.
3. **Wait for processing.** Each source shows a status; wait until they are all
   **ready** (green).
4. **Test it in the browser.** Ask the notebook a CWatM question (e.g. *"What does
   PathOut control?"*) to confirm the sources answer well.

> **Using a specific notebook.** If you keep several notebooks, copy the one you want
> from the browser address bar (its **id** or full **URL**) and paste it into
> **Notebook…** in the CWatM AI window. Otherwise leave it on *auto* and rely on the
> "CWatM" title match.

---

## 3. Logging in — one click

Click **Login…** in the CWatM AI window. CWatM AI **auto-detects** the browser you are
signed in to Google with: it tries **Firefox → Chrome → Edge → Opera** in turn,
verifies each candidate session against NotebookLM, and stops at the first that works.

```
Looking for a signed-in Google session in your browsers…
Trying Firefox…      ✗
Trying Chrome…       ✓  Logged in via Chrome.
```

The login-state line at the top of the window shows **✓ Logged in** (blue) when a
working session is confirmed, **Checking…** while it verifies, or **Login required**
(red) when you need to sign in.

### Which browser works

- **Firefox — easiest, no admin.** Its cookie store is readable without elevation, so
  it is tried first. If you are signed in to Google in Firefox, one **Login…** click is
  all you need.
- **Chrome / Edge / Opera — need "Run as administrator".** On current Windows these
  browsers **app-bound-encrypt** their cookies, so CWatM can only read them when
  **elevated**:
  1. Close CWatM.
  2. **Right-click `CWatM_GUI.exe` → *Run as administrator*.**
  3. Open **CWatM AI → Login…** (or **Choose browser… → From Chrome/Edge/Opera**).

  After the session is stored you can go back to running CWatM **normally
  (non-elevated)** — the elevation is only needed for the one-time cookie read.

### Choose browser… (manual fallback)

If auto-detect can't find a working session, CWatM AI explains why and offers **Choose
browser…** — pick a specific browser to read cookies from, or (running **from source**
only, with the optional `playwright` package installed) the interactive **Google login
window**, which signs in through a real browser with no cookie decryption or admin
rights.

### After you log in

- CWatM verifies the new session in the background and the login line turns
  **✓ Logged in** (blue).
- The session **persists across restarts** — you normally log in only once, until
  Google expires it (then the window says *Login required* again and offers to
  re-authenticate).

---

## 4. Using the CWatM AI chat window

- **Ask a question:** type in the input box and press **Enter** (**Shift+Enter** for a
  new line) or click **Send**. Answers stream back from Gemini and are shown as
  formatted **Markdown** (bold, lists, tables, code). While a question is running,
  **Send** becomes **Stop thinking** and cancels it.
- **Answer length:** the **Short / Medium / Long** toggle (bottom row) sets how detailed
  replies are — **Short** is the fastest. Your choice is remembered.
- **Question history:** press **Up / Down** in the input box to recall previous
  questions. The whole transcript and your question history are **kept across
  close/open**.
- **Explain current line:** the **Explain current line** button (or typing *"explain
  this line"*) asks NotebookLM to explain the settings line your editor cursor is on.
- **Notebook…:** by default CWatM AI auto-selects the notebook whose title contains
  *"CWatM"*. Use **Notebook…** to point at a specific notebook id or URL.
- **Clear / Exit:** clear the transcript, or close the window (your session and history
  are saved either way).

---

## 5. Getting good answers

CWatM AI is only as good as the **grounding** and your prompt. Tips adapted from the
NotebookLM guidance:

- **Be specific.** Instead of *"explain routing"*, try *"What does the `PathOut` option
  control and what files are written there?"* Specific keywords help it retrieve the
  right passage.
- **Verify with the sources.** NotebookLM answers point back to the notebook sources.
  Don't just read the snippet — read a little before and after it to be sure a detail
  wasn't taken out of context. Cross-check when several citations appear.
- **Why it may decline.** If an answer is refused or "not found", it is usually because
  the question is **outside the CWatM sources** (add a relevant source to the notebook),
  the phrasing was unclear (re-prompt with exact keywords), or a safety filter
  triggered. Staying inside its "grounded box" is by design.
- **Summarise a session.** At the end, ask it to *"summarise the key points of this
  chat"* so you can pick up where you left off next time.

> CWatM AI is an **experimental** aid. Its grounding makes it far more accurate than a
> generic chatbot, but it is not infallible — treat it as a research partner, verify
> against the CWatM documentation and code, and never rely on it as the final authority
> for a decision.

For the full NotebookLM feature set (adding your own sources, Studio outputs such as
audio/video overviews and mind maps, subscription tiers), use the NotebookLM website
directly at **notebooklm.google.com** — the CWatM AI window is a focused chat client
over the CWatM notebook, not the full NotebookLM studio.

---

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| **"Login required"** (red) after it worked before | The Google session expired. Click **Login…** and sign in again (Firefox = no admin; Chrome/Edge/Opera = run CWatM as administrator). |
| **Login can't find any session** | You are not signed in to Google in Firefox/Chrome/Edge/Opera, or (Chromium browsers) CWatM is not elevated. Sign in to Google in Firefox, or run CWatM **as administrator** and retry. |
| **"…can be decrypted only when running as admin…"** | App-bound encryption on Chrome/Edge/Opera. **Run CWatM as administrator**, then retry that browser — or use Firefox. |
| **Answers say "not found" / off-topic** | The notebook is missing CWatM sources, or the question is outside them. Check the notebook has `CWATM_shorter.pdf` (and other CWatM docs) as **ready** sources — see [§2](#2-prepare-a-notebooklm-notebook). |
| **Wrong notebook is used** | Several notebooks match. Set the exact one with **Notebook…** (paste its id or URL), or rename the intended one so only it contains "CWatM". |
| **No "Google login window" option** | It needs Playwright and appears **only when running from source**; install with `pip install playwright`. |
| **CWatM AI button does nothing / import error** | The NotebookLM libraries are unavailable in this build. Asking questions with a stored session works in the packaged exe; if it degrades, run from source with `pip install "notebooklm-py[cookies]"`. |

---

*This help describes the CWatM AI window, notebook preparation and login. General
NotebookLM concepts (grounding, sources, verification) are summarised from Google's
NotebookLM material.*
