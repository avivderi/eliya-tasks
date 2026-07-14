# Xiaomi Notes -> Google Keep Migration Toolkit

Moves your 240 notes from Xiaomi Cloud (i.mi.com) into Google Keep, in two
steps: **Backup** (Step 1) and **Injection** (Step 2). No copy-pasting.

## How it actually works (read this first)

- **No fragile Selenium/driver setup.** This uses **Playwright** instead.
  Playwright downloads and manages its own matching Chromium build, so the
  "Chrome version doesn't match my driver version" problem you hit before
  cannot happen here.
- **No password automation, ever.** For both Xiaomi and Google, the script
  opens a real, visible browser window and **you log in by hand** (with
  2FA/passkeys if you use them). This is exactly why Google won't block it
  — it only blocks *automated* logins, not a human typing their own
  password. For Xiaomi, the session is saved to a local folder
  (`browser_profiles/`) so you won't have to log in again on reruns. For
  Google Keep specifically, the script drives your **real, already-installed
  Google Chrome** (not Playwright's own bundled browser) using a **copy of
  your real Chrome profile** -- see the "One-time Chrome setup for Google
  Keep" section below. This is required because Google's sign-in page
  actively blocks Playwright's own bundled browser build.
- **Neither i.mi.com nor Google Keep has a public API for personal
  accounts**, so this reads/writes the same web pages you'd use manually —
  it just does it 240 times reliably instead of you doing it by hand.
  Because their internal page structure can't be verified without an
  active logged-in session, the toolkit includes a one-time **calibration
  step** (`--inspect`) that walks you through picking the right on-screen
  elements. It only takes a minute and it's the price of 100% reliability
  in the absence of an official API.
- **Crash-safe.** Every single note is checkpointed the instant it's
  extracted/imported. If your laptop sleeps, the browser closes, or
  anything else interrupts a run of 240 notes, just re-run the same
  command — it picks up exactly where it left off, with zero duplicates.
- **English-only console output**, as requested.

## Folder contents

```
keep_migration/
  config.py            shared settings (edit timings here if needed)
  xiaomi_export.py      STEP 1: Xiaomi Cloud -> data/notes_backup.json
  keep_import.py         STEP 2: data/notes_backup.json -> Google Keep
  launcher_gui.py         optional one-click GUI wrapping the two scripts
  requirements.txt
  README.md               this file
```

---

## Setup (do this once)

Both macOS and Ubuntu now block `pip install` outside a virtual
environment ("externally-managed-environment" / PEP 668). The fix on both
platforms is the same: create a **virtual environment** and install into
that instead of system Python. Follow the block for your OS.

### macOS (your sister-in-law)

1. Open **Terminal**.
2. Install **Python 3.12** (recommended, most tested with current
   libraries). If you have Homebrew: `brew install python@3.12`. Otherwise
   download the 3.12 installer from
   https://www.python.org/downloads/macos/
3. Navigate into this folder, e.g.:
   ```bash
   cd ~/Downloads/keep_migration
   ```
4. Create and activate a virtual environment (use `python3.12` if you
   installed it as above, otherwise `python3` is fine on most current
   Macs):
   ```bash
   python3.12 -m venv venv
   source venv/bin/activate
   ```
   (You'll see `(venv)` appear at the start of your terminal prompt — that
   means it worked and you're now safely inside the virtual environment.)
5. Install dependencies **inside** the venv (this avoids the PEP 668 error
   entirely, since the venv is not the "externally managed" system Python):
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   playwright install chromium
   ```

### Ubuntu (your testing machine)

> **Note:** if your Ubuntu version's default `python3` is very new (e.g.
> Python 3.14 on Ubuntu 26.04), skip straight to installing **Python 3.12**
> below. Some packages (including a Playwright dependency, `greenlet`)
> don't ship prebuilt wheels for brand-new Python versions yet, which
> causes a C-compiler error during `pip install`. Python 3.12 avoids this
> entirely and is what most libraries are tested against today.

1. Open a terminal.
2. Install Python 3.12 specifically (works alongside whatever default
   Python your system already has -- it won't replace it):
   ```bash
   sudo apt update
   sudo apt install -y python3.12 python3.12-venv python3-pip
   ```
3. Navigate into this folder:
   ```bash
   cd ~/keep_migration
   ```
4. Create and activate a virtual environment **using 3.12 specifically**:
   ```bash
   python3.12 -m venv venv
   source venv/bin/activate
   python --version   # should print Python 3.12.x
   ```
5. Install dependencies inside the venv:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   playwright install chromium
   playwright install-deps chromium   # installs OS-level libraries Chromium needs on Linux
   ```

> Every time you come back to a new terminal session, re-activate the venv
> first with `source venv/bin/activate` (macOS/Ubuntu are identical here)
> before running any of the scripts below.

---

## One-time Chrome setup for Google Keep (required before Step 2)

Google's sign-in page blocks Playwright's own bundled browser build, even
with a fully manual, human login. The fix: point the script at your
**real, already-installed Google Chrome**, using a **copy** of your real
Chrome profile (so it inherits your browser's trusted certificates and
settings).

1. Make sure Google Chrome (not just Chromium) is actually installed:
   ```bash
   google-chrome --version      # Ubuntu
   ```
   On macOS, just confirm you have Chrome in Applications. If not, install
   it from https://www.google.com/chrome/ first.

2. Close **all** Chrome windows completely (not just minimize):
   ```bash
   pkill -f "google-chrome"     # Ubuntu
   # macOS: Cmd+Q on Chrome, or: pkill -f "Google Chrome"
   ```

3. Copy your real Chrome profile into a separate working folder (skips
   heavy cache folders to keep it fast):
   ```bash
   mkdir -p ~/keep_migration_chrome_profile
   rsync -a --exclude='Cache' --exclude='Code Cache' --exclude='GPUCache' --exclude='ShaderCache' --exclude='*.lock' --exclude='SingletonLock' --exclude='SingletonCookie' --exclude='SingletonSocket' ~/.config/google-chrome/ ~/keep_migration_chrome_profile/
   ```
   (macOS path is different: `~/Library/Application Support/Google/Chrome/`
   instead of `~/.config/google-chrome/`.)

4. Don't browse with your regular Chrome while `keep_import.py` is running
   (it uses this copied profile, not your live one, so there's no
   conflict with your everyday browsing -- but avoid running both at once
   to keep things simple).

> ⚠️ **Security note:** `~/keep_migration_chrome_profile` contains a copy of
> **every saved password and cookie in your real Chrome**, not just
> Google's. It lives outside this project folder on purpose. **Never** move
> it into the project folder or commit it to git/GitHub -- it is
> effectively as sensitive as your master password list. The `.gitignore`
> in this repo also blocks `browser_profiles/` (the Xiaomi session folder)
> for the same reason.

---

## Usage

### Step 1 — Back up notes from Xiaomi Cloud

First run, one-time calibration (finds the right on-screen elements):
```bash
python xiaomi_export.py --inspect
```
A browser opens to i.mi.com. Log in manually, wait for your notes to show,
press Enter in the terminal, then follow the on-screen prompts (they'll
ask you to right-click a note in the browser -> Inspect -> Copy selector,
and paste it into the terminal — no coding knowledge needed, just
copy-paste).

Then run the real extraction:
```bash
python xiaomi_export.py
```
This logs you in once (session is remembered after that), scrolls to load
all notes, and saves each one — with live progress — into
`data/notes_backup.json`, in this format:
```json
[
  {"title": "Shopping list", "content": "Milk, eggs, bread", "date": "2024-03-11"}
]
```
If it's interrupted, just run `python xiaomi_export.py` again — it resumes
automatically. Any note that fails after 3 retries is logged to
`data/failed_notes.json` for a quick manual look, instead of stopping the
whole batch.

### Step 2 — Import notes into Google Keep

Make sure you've completed the "One-time Chrome setup for Google Keep"
section above first. Then:
```bash
python keep_import.py
```
A window of your **real Chrome** opens to Google Keep, already signed in
(since it's using a copy of your logged-in profile) or prompting a normal
manual login if not. Press Enter in the terminal once you see your notes,
and the script creates one Keep note per entry in `notes_backup.json`,
with the same crash-safe resume behavior as Step 1. Failures are logged to
`data/failed_imports.json`. If Google's page structure ever changes and
the default selectors stop working, run `python keep_import.py --inspect`
once to recalibrate, the same way as Step 1.

### Optional: one-click GUI

Instead of the two commands above, you can run:
```bash
python launcher_gui.py
```
This gives you buttons for both steps, a "I've logged in -> Continue"
button (since the terminal's `Enter` prompt is replaced by a button here),
and a live log window — all standard-library Tkinter, nothing extra to
install.

---

## Honest limitations (please read)

- Because there's no official API for either service, this relies on
  reading the live web pages. If Xiaomi or Google significantly redesign
  their site layout in the future, the saved selectors may need a quick
  `--inspect` refresh (a few minutes, no coding required) — this is true
  of *any* browser-automation approach, not a flaw specific to this
  design, and it's why the calibration step exists instead of hardcoding
  guesses that could silently break.
  - For extra safety, `data/notes_backup.json` is a plain, human-readable
  JSON backup you keep permanently — even if Step 2 ever needs
  adjustment, your extracted notes are never at risk.






# 1. מחיקת פרופילי הדפדפן (מנתק גם את Google וגם את Xiaomi)
rm -rf browser_profiles/
rm -rf ~/keep_migration_chrome_profile

# 2. מחיקת תיקיות הדיבאג וצילומי המסך
rm -rf data/keep_debug/

# 3. מחיקת כל קבצי הפתקים שחולצו
rm -f data/notes_backup.json

# 4. מחיקת כל קבצי מעקב ההתקדמות ורשימת הכישלונות
rm -f data/extract_progress.json
rm -f data/import_progress.json
rm -f data/failed_notes.json
rm -f data/failed_imports.json
rm -f data/extract_debug.html
