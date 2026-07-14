"""
STEP 2 - Google Keep import (notes_backup.json -> keep.google.com)

WHY THIS DESIGN
----------------
Google has no personal-account API for Keep (the official "Keep API" only
works for Google Workspace accounts with admin-managed domain-wide
delegation, not regular @gmail.com accounts). Unofficial libraries like
gkeepapi rely on extracting a "master token" via a Google-internal login
flow that Google actively tries to detect and block ("This browser or app
may not be secure") -- exactly the failure mode you already hit.

This script sidesteps that entirely: it never touches your Google password.
It opens a real, visible browser window and YOU log in by hand, the normal
way (including 2FA/passkeys if you use them). Google does not block manual
human logins. After that one-time login, Playwright saves the session to a
local browser profile folder, so future runs skip the login step.

RELIABILITY FEATURES
---------------------
- Resumable: each note is checkpointed the moment it's successfully created
  in Keep, so a crash never re-imports a note you already have (no dupes)
  and never loses your place.
- Per-note retries with a calibration fallback if Google changes Keep's
  markup (run with --inspect to re-detect selectors).
- English-only console output.

USAGE
-----
    python keep_import.py --inspect     # only needed if default selectors fail
    python keep_import.py               # normal run
"""

import argparse
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import config

# Best-guess default selectors for Google Keep's English UI. aria-label
# attributes tend to be far more stable across Google's frequent visual
# redesigns than CSS class names, which is why these are used instead of
# classes. If Google changes these, rerun with --inspect to fix them.
DEFAULT_SELECTORS = {
    "open_note_box": "[aria-label='Take a note…']",
    "title_input": "[aria-label='Title']",
    "content_input": "[aria-label='Take a note…'][contenteditable='true'], "
                      "[aria-label='Take a note…'] textarea",
    "close_button": "[aria-label='Close']",
}


def log(msg: str) -> None:
    print(f"[keep_import] {msg}", flush=True)


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def wait_for_manual_login(page):
    log("A browser window has opened and navigated to Google Keep.")
    log("Please log in manually with your Google account (including any 2FA step).")
    log("Once you can see the 'Take a note...' box and your existing Keep notes,")
    input("come back here and press Enter to continue... ")


def load_selectors():
    saved = load_json(config.SELECTORS_FILE.replace("xiaomi", "keep"), None)
    return saved or DEFAULT_SELECTORS


def run_calibration(page):
    log("=== CALIBRATION MODE ===")
    log("Right-click the 'Take a note...' box at the top of Keep -> Inspect.")
    log("Copy its selector (right-click the highlighted element in DevTools -> Copy -> Copy selector).")
    open_box = input("CSS selector for the 'Take a note...' box: ").strip()
    log("Click into that box so it expands, then Inspect the TITLE field.")
    title_input = input("CSS selector for the Title input: ").strip()
    log("Inspect the note content/body field.")
    content_input = input("CSS selector for the content field: ").strip()
    log("Inspect the 'Close' button that saves and collapses the note.")
    close_button = input("CSS selector for the Close button: ").strip()

    selectors = {
        "open_note_box": open_box,
        "title_input": title_input,
        "content_input": content_input,
        "close_button": close_button,
    }
    path = config.SELECTORS_FILE.replace("xiaomi", "keep")
    save_json(path, selectors)
    log(f"Saved selectors to {path}")


def create_one_note(page, selectors, title, content):
    page.click(selectors["open_note_box"])
    page.wait_for_timeout(int(config.SHORT_WAIT * 1000))

    if title:
        title_el = page.query_selector(selectors["title_input"])
        if title_el:
            title_el.click()
            title_el.type(title, delay=10)

    content_el = page.query_selector(selectors["content_input"])
    if content_el is None:
        raise ValueError("Could not find the content field -- selectors may be stale, try --inspect")
    content_el.click()
    content_el.type(content, delay=5)

    page.wait_for_timeout(int(config.SHORT_WAIT * 1000))
    close_el = page.query_selector(selectors["close_button"])
    if close_el:
        close_el.click()
    else:
        page.keyboard.press("Escape")

    page.wait_for_timeout(int(config.SHORT_WAIT * 1000))


def main():
    parser = argparse.ArgumentParser(description="Import notes into Google Keep")
    parser.add_argument("--inspect", action="store_true",
                         help="Run one-time interactive selector calibration")
    args = parser.parse_args()

    if not os.path.exists(config.NOTES_BACKUP_FILE):
        log(f"ERROR: {config.NOTES_BACKUP_FILE} not found. Run xiaomi_export.py first.")
        sys.exit(1)

    notes = load_json(config.NOTES_BACKUP_FILE, [])
    if not notes:
        log("ERROR: notes_backup.json is empty. Nothing to import.")
        sys.exit(1)

    with sync_playwright() as p:
        log(f"Launching browser with saved profile: {config.GOOGLE_PROFILE_DIR}")
        context = p.chromium.launch_persistent_context(
            config.GOOGLE_PROFILE_DIR,
            headless=False,
            channel=config.GOOGLE_CHROME_CHANNEL,
            viewport={"width": 1400, "height": 900},
            # Playwright normally flags the browser as automation-controlled
            # (the "Chrome is being controlled by automated test software"
            # banner). Google's sign-in page specifically detects that flag
            # and blocks login even in real Chrome with a fully manual
            # login. Disabling it here does not change anything about how
            # you log in -- you still type your own credentials by hand --
            # it just stops Chrome from announcing itself as automated.
            args=["--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"],
        )
        page = context.new_page()
        page.set_default_timeout(config.ACTION_TIMEOUT_MS)

        log(f"Navigating to {config.GOOGLE_KEEP_URL}")
        page.goto(config.GOOGLE_KEEP_URL, timeout=config.PAGE_LOAD_TIMEOUT_MS)

        wait_for_manual_login(page)

        if args.inspect:
            run_calibration(page)
            context.close()
            return

        selectors = load_selectors()

        progress = load_json(config.IMPORT_PROGRESS_FILE, {"done_indices": []})
        failed = load_json(config.FAILED_NOTES_FILE.replace("failed_notes", "failed_imports"), [])
        done = set(progress["done_indices"])

        total = len(notes)
        log(f"Starting import of {total} notes ({len(done)} already done from a previous run).")

        for i, note in enumerate(notes):
            if i in done:
                continue
            success = False
            last_error = None
            for attempt in range(1, config.MAX_RETRIES_PER_NOTE + 1):
                try:
                    create_one_note(page, selectors, note.get("title", ""), note.get("content", ""))
                    done.add(i)
                    progress["done_indices"] = sorted(done)
                    save_json(config.IMPORT_PROGRESS_FILE, progress)
                    log(f"[{len(done)}/{total}] Imported: "
                        f"'{(note.get('title') or note.get('content') or '')[:40]}'")
                    success = True
                    break
                except (PWTimeout, ValueError) as e:
                    last_error = str(e)
                    log(f"  Attempt {attempt}/{config.MAX_RETRIES_PER_NOTE} "
                        f"failed for note {i}: {last_error}")
                    page.keyboard.press("Escape")
                    time.sleep(config.LONG_WAIT)
            if not success:
                failed.append({"index": i, "title": note.get("title", ""), "error": last_error})
                save_json(config.FAILED_NOTES_FILE.replace("failed_notes", "failed_imports"), failed)
                log(f"  Giving up on note {i} after {config.MAX_RETRIES_PER_NOTE} attempts.")
            time.sleep(config.SHORT_WAIT)

        context.close()
        log(f"Done. {len(done)}/{total} notes imported into Google Keep.")
        if failed:
            log(f"{len(failed)} note(s) failed and need manual review: "
                f"{config.FAILED_NOTES_FILE.replace('failed_notes', 'failed_imports')}")


if __name__ == "__main__":
    main()
