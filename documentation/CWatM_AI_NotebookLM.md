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
It does not ask for your password inside CWatM — you sign in on Google's own page in
a browser window CWatM opens (Edge or Chrome). The result is a small session file stored on
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

## 3. Logging in

Click **Login** in the CWatM AI window and choose a browser — **Microsoft Edge**,
or **Google Chrome** — each shown as a card with its icon; one that is not installed is
greyed out (the last choice is pre-selected). A separate window of that browser opens on **Google's own sign-in page**; sign in there and the window
closes by itself.

- It uses the browser **installed** on your computer — nothing is downloaded.
- It reads **none** of your browsers' cookies, passwords or data, and needs **no
  administrator rights**. Your password goes only to Google.
- The Google session is stored in a file on this computer
  (`%USERPROFILE%\.notebooklm\…\storage_state.json`) and used only to ask NotebookLM.
  Delete the `.notebooklm` folder to remove it. The first login explains this once and
  asks you to agree.
- Every login starts a fresh private browser session, so you type your password each
  time.

The header shows the state as a small pill next to the button: **Checking session…**
(button *Checking…*), **Logged in** (button **Logout** — click it to log out, which
removes the stored session), or **Not logged in** / **Session expired** (button
**Login**).

### After you log in

- CWatM verifies the new session in the background and the login line turns
  **Logout** (blue).
- The session **persists across restarts** — you normally log in only once, until
  Google expires it (then the window says *Login* again and offers to
  re-authenticate).

---

## 4. Using the CWatM AI chat window

- **Ask a question:** type in the input box and press **Enter** (**Shift+Enter** for a
  new line) or click **Send**. Answers stream back from Gemini and are shown as
  formatted **Markdown** (bold, lists, tables, code). While a question is running,
  **Send** becomes **Stop thinking** and cancels it.
- **Answer length:** the **Short / Long** toggle (bottom row) sets how detailed
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
| **"Login"** (red) after it worked before | The Google session expired. Click **Login**, choose a browser and sign in again. |
| **Answers say "not found" / off-topic** | The notebook is missing CWatM sources, or the question is outside them. Check the notebook has `CWATM_shorter.pdf` (and other CWatM docs) as **ready** sources — see [§2](#2-prepare-a-notebooklm-notebook). |
| **"<browser> is not installed"** | Choose another browser in the **Login** dialog. |
| **The login window closes / nothing happens** | Closing the window cancels the login - press **Login** again and finish signing in within 5 minutes. |
| **Wrong notebook is used** | Several notebooks match. Set the exact one with **Notebook…** (paste its id or URL), or rename the intended one so only it contains "CWatM". |
| **CWatM AI button does nothing / import error** | The NotebookLM libraries are unavailable in this build. Asking questions with a stored session works in the packaged exe; if it degrades, run from source with `pip install notebooklm-py playwright`. |

---

*This help describes the CWatM AI window, notebook preparation and login. General
NotebookLM concepts (grounding, sources, verification) are summarised from Google's
NotebookLM material.*
