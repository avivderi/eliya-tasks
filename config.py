"""
Shared configuration for the Xiaomi -> Google Keep migration toolkit.
Edit values here instead of digging through the two main scripts.
All output is English-only by design (avoids console encoding issues).
"""

import os

# ---------------------------------------------------------------------------
# Folders (created automatically on first run)
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILES_DIR = os.path.join(BASE_DIR, "browser_profiles")
DATA_DIR = os.path.join(BASE_DIR, "data")

XIAOMI_PROFILE_DIR = os.path.join(PROFILES_DIR, "xiaomi_profile")
GOOGLE_PROFILE_DIR = os.path.expanduser("~/keep_migration_chrome_profile")

NOTES_BACKUP_FILE = os.path.join(DATA_DIR, "notes_backup.json")
EXTRACT_PROGRESS_FILE = os.path.join(DATA_DIR, "extract_progress.json")
IMPORT_PROGRESS_FILE = os.path.join(DATA_DIR, "import_progress.json")
FAILED_NOTES_FILE = os.path.join(DATA_DIR, "failed_notes.json")
EXTRACT_LOG_FILE = os.path.join(DATA_DIR, "extract_debug.html")
SELECTORS_FILE = os.path.join(DATA_DIR, "xiaomi_selectors.json")

for d in (PROFILES_DIR, DATA_DIR):
    os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------------------------
# Timing (seconds). Keep these generous -- both i.mi.com and Google Keep are
# JS-heavy single page apps, and going too fast is the #1 cause of "flaky"
# automation. Slower and 100% reliable beats fast and fragile.
# ---------------------------------------------------------------------------
SHORT_WAIT = 0.6
MEDIUM_WAIT = 1.5
LONG_WAIT = 3.0
PAGE_LOAD_TIMEOUT_MS = 45_000
ACTION_TIMEOUT_MS = 15_000

# Retry each note this many times before giving up and logging it as failed
MAX_RETRIES_PER_NOTE = 3

# ---------------------------------------------------------------------------
# Browser channel used for the Google Keep script. Playwright's own bundled
# Chromium build is labeled "Chrome for Testing", which Google's sign-in
# page actively detects and blocks ("This browser or app may not be
# secure") -- even for a fully manual, human login. Using "chrome" here
# makes Playwright drive your real, already-installed Google Chrome
# instead, which is not flagged this way. Requires Google Chrome to
# already be installed on the machine (it is, on both your setups).
# ---------------------------------------------------------------------------
GOOGLE_CHROME_CHANNEL = "chrome"

# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------
XIAOMI_NOTES_URL = "https://i.mi.com/note/h5#/"
GOOGLE_KEEP_URL = "https://keep.google.com/"
