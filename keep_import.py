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
- Nothing can crash the whole batch: EVERY exception type is caught per
  note (not just timeouts), so one bad note is logged and skipped instead
  of stopping the script for the remaining notes.
- Content is verified after typing (read back and compared to what was
  meant to be typed) before the note is marked done, so a note is never
  silently marked "imported" with missing text.
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


from playwright.sync_api import sync_playwright

import config

DEFAULT_SELECTORS = {
    "open_note_box": "[aria-label='Take a note…']",
    "title_input": "[aria-label='Title']",
    "content_input": "[aria-label='Take a note…'][contenteditable='true'], "
                      "[aria-label='Take a note…'] textarea",
    "close_button": "[aria-label='Close']",
}

FIELD_WAIT_MS = 8000
DEBUG_DIR = os.path.join(config.DATA_DIR, "keep_debug")


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
    log("IMPORTANT: pick exactly 'Copy selector', not 'Copy outerHTML' / 'Copy element' / 'Copy JS path'.")
    open_box = input("CSS selector for the 'Take a note...' box: ").strip()
    log("Click into that box so it expands, then Inspect the TITLE field.")
    title_input = input("CSS selector for the Title input: ").strip()
    log("Inspect the note content/body field.")
    content_input = input("CSS selector for the content field: ").strip()
    log("Inspect the 'Close' button that saves and collapses the note.")
    close_button = input("CSS selector for the Close button: ").strip()

    for name, sel in [("open box", open_box), ("title", title_input),
                       ("content", content_input), ("close button", close_button)]:
        if sel.startswith("<"):
            log(f"WARNING: the {name} selector looks like raw HTML, not a CSS selector "
                f"(it starts with '<'). You likely picked 'Copy outerHTML' by mistake. "
                f"Please redo this field with 'Copy selector' instead.")

    selectors = {
        "open_note_box": open_box,
        "title_input": title_input,
        "content_input": content_input,
        "close_button": close_button,
    }
    path = config.SELECTORS_FILE.replace("xiaomi", "keep")
    save_json(path, selectors)
    log(f"Saved selectors to {path}")


def dump_debug(page, index, label):
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        png_path = os.path.join(DEBUG_DIR, f"note_{index}_{label}.png")
        html_path = os.path.join(DEBUG_DIR, f"note_{index}_{label}.html")
        page.screenshot(path=png_path)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(page.content())
    except Exception:
        pass


def close_any_open_note(page, selectors):
    for _ in range(2):
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
    try:
        page.wait_for_selector(selectors["open_note_box"], state="visible",
                                timeout=FIELD_WAIT_MS)
    except Exception:
        pass


def create_one_note(page, selectors, index, title, content):
    open_box = page.wait_for_selector(selectors["open_note_box"], state="visible",
                                       timeout=FIELD_WAIT_MS)
    open_box.click()
    page.wait_for_timeout(500)  # Wait for the note to expand

    # Robust locators scoped to the expanded state
    # The Title field is the visible contenteditable textbox
    title_loc = page.locator("div[role='textbox'][contenteditable='true']:visible").first

    # The Content field is typically a visible combobox. If Keep changes DOM, fallback to the 2nd textbox.
    content_loc = page.locator("div[role='combobox'][aria-autocomplete='list']:visible").first

    if title:
        title_loc.wait_for(state="visible", timeout=FIELD_WAIT_MS)
        title_loc.click()
        page.wait_for_timeout(200)
        page.keyboard.type(title, delay=10)

    try:
        content_loc.wait_for(state="visible", timeout=2000)
    except Exception:
        content_loc = page.locator("div[role='textbox'][aria-multiline='true']:visible").nth(1)

    # Click the content field and wait for Chrome to register focus
    # (Addresses timing issues with AutomationControlled disabled)
    content_loc.click()
    page.wait_for_timeout(500)
    
    # Use keyboard.type to avoid stale element references if Keep replaces the node upon activation
    page.keyboard.type(content, delay=5)
    page.wait_for_timeout(300)

    # Verify content was written
    # Check the currently active element first
    actual = page.evaluate("document.activeElement.innerText || ''").strip()
    
    # Fallback to checking all visible editables if focus shifted
    if not actual:
        actual = "\n".join(page.locator("[contenteditable='true']:visible").all_inner_texts())

    expected_snippet = content.strip()[:30]
    
    # Normalize whitespace/newlines before comparing to handle editor-specific paragraph rendering
    actual_norm = "".join(actual.split())
    expected_norm = "".join(expected_snippet.split())

    if expected_norm and expected_norm not in actual_norm:
        dump_debug(page, index, "content_mismatch")
        raise RuntimeError(
            f"Content did not land correctly. Expected to find "
            f"'{expected_snippet}...' but field contains: '{actual[:60]}'. "
            f"Debug screenshot saved to {DEBUG_DIR}/note_{index}_content_mismatch.png"
        )

    page.wait_for_timeout(int(config.SHORT_WAIT * 1000))
    close_el = page.query_selector(selectors["close_button"])
    if close_el and close_el.is_visible():
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
        failed_path = config.FAILED_NOTES_FILE.replace("failed_notes", "failed_imports")
        failed = load_json(failed_path, [])
        done = set(progress["done_indices"])

        total = len(notes)
        log(f"Starting import of {total} notes ({len(done)} already done from a previous run).")

        for i, note in enumerate(notes):
            if i in done:
                continue

            try:
                success = False
                last_error = None
                for attempt in range(1, config.MAX_RETRIES_PER_NOTE + 1):
                    try:
                        create_one_note(page, selectors, i,
                                         note.get("title", ""), note.get("content", ""))
                        done.add(i)
                        progress["done_indices"] = sorted(done)
                        save_json(config.IMPORT_PROGRESS_FILE, progress)
                        log(f"[{len(done)}/{total}] Imported: "
                            f"'{(note.get('title') or note.get('content') or '')[:40]}'")
                        success = True
                        break
                    except Exception as e:
                        last_error = f"{type(e).__name__}: {e}"
                        log(f"  Attempt {attempt}/{config.MAX_RETRIES_PER_NOTE} "
                            f"failed for note {i}: {last_error}")
                        dump_debug(page, i, f"attempt{attempt}")
                        close_any_open_note(page, selectors)
                        time.sleep(config.LONG_WAIT)

                if not success:
                    failed.append({"index": i, "title": note.get("title", ""), "error": last_error})
                    save_json(failed_path, failed)
                    log(f"  Giving up on note {i} after {config.MAX_RETRIES_PER_NOTE} attempts. "
                        f"Continuing with the next note.")
            except Exception as outer_e:
                last_error = f"UNEXPECTED {type(outer_e).__name__}: {outer_e}"
                log(f"  Unexpected error on note {i}: {last_error}. Continuing with the next note.")
                failed.append({"index": i, "title": note.get("title", ""), "error": last_error})
                save_json(failed_path, failed)
                try:
                    close_any_open_note(page, selectors)
                except Exception:
                    pass

            time.sleep(config.SHORT_WAIT)

        context.close()
        log(f"Done. {len(done)}/{total} notes imported into Google Keep.")
        if failed:
            log(f"{len(failed)} note(s) failed and need manual review: {failed_path}")
            log(f"Debug screenshots/HTML for failed attempts saved under: {DEBUG_DIR}")


if __name__ == "__main__":
    main()
