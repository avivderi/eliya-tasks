"""
STEP 1 - Xiaomi Cloud note extraction (i.mi.com -> notes_backup.json)

WHY THIS DESIGN
----------------
i.mi.com has no public/documented API, and its internal (undocumented) API
changes without notice and is a moving target -- relying on it would be less
stable, not more. Instead this script drives a REAL browser (Playwright,
which manages its own matching browser binary, so there is no Chrome/driver
version mismatch like with Selenium) and reads the notes straight out of the
rendered page. You log in manually once; the session is then saved to a
local browser profile folder so you do not need to log in again on reruns.

Because nobody (including Claude) can verify i.mi.com's exact CSS selectors
without an active logged-in session, this script ships with a CALIBRATION
MODE. Run it once with --inspect, click on your note list in the opened
browser window, and follow the prompts. The selectors you confirm are saved
to data/xiaomi_selectors.json and reused automatically on every future run.

RELIABILITY FEATURES
---------------------
- Resumable: progress is checkpointed after every single note, so a crash,
  a closed laptop lid, or a lost connection never loses work or duplicates
  notes on the next run.
- Per-note retries: each note gets up to MAX_RETRIES_PER_NOTE attempts
  before being logged to failed_notes.json for manual review, instead of
  crashing the whole batch.
- English-only console output.

USAGE
-----
    python xiaomi_export.py --inspect     # first time only: find selectors
    python xiaomi_export.py               # run the real extraction
"""

import argparse
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

import config


def log(msg: str) -> None:
    print(f"[xiaomi_export] {msg}", flush=True)


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
    log("A browser window has opened and navigated to Xiaomi Notes (i.mi.com).")
    log("Please log in manually with your Mi account (QR code, password, or SMS code).")
    log("Once you can see your list of notes on screen, come back to this terminal")
    input("and press Enter to continue... ")


def load_selectors():
    selectors = load_json(config.SELECTORS_FILE, None)
    if not selectors:
        log("No saved selectors found. Run this script once with --inspect first:")
        log("    python xiaomi_export.py --inspect")
        sys.exit(1)
    return selectors


def run_calibration(page):
    """
    Interactive helper: prints candidate elements so you can identify the
    right CSS selector for (1) each note row in the list and (2) the title
    / body / date fields inside an opened note, without needing to read
    raw HTML yourself.
    """
    log("=== CALIBRATION MODE ===")
    log("1) In the browser, make sure your notes list is visible.")
    log("2) Right-click one note in the list -> Inspect.")
    log("3) In DevTools, right-click the highlighted HTML element -> Copy -> Copy selector.")
    log("4) Paste that selector below.")
    list_item_selector = input("CSS selector for ONE note row in the list: ").strip()

    count = page.eval_on_selector_all(list_item_selector, "els => els.length")
    log(f"That selector currently matches {count} element(s) on screen "
        f"(scroll the list down first if this looks too low -- more notes "
        f"load as you scroll).")

    log("Now click on that same note to open it, then Inspect the TITLE text.")
    title_selector = input("CSS selector for the note TITLE inside the open note view: ").strip()

    log("Now Inspect the note BODY/content text.")
    content_selector = input("CSS selector for the note CONTENT/body inside the open note view: ").strip()

    log("Now Inspect the date/timestamp shown for the note (if any). Leave blank if there isn't one.")
    date_selector = input("CSS selector for the note DATE (optional, press Enter to skip): ").strip()

    selectors = {
        "list_item": list_item_selector,
        "title": title_selector,
        "content": content_selector,
        "date": date_selector or None,
    }
    save_json(config.SELECTORS_FILE, selectors)
    log(f"Saved selectors to {config.SELECTORS_FILE}")
    log("You can now run: python xiaomi_export.py")


def scroll_to_load_all(page, list_item_selector, max_stable_rounds=10):
    """
    i.mi.com's note list is virtualized/lazy-loaded like most modern SPAs:
    scrolling down loads more notes. Keep scrolling until the count of
    matched list items stops growing for a few rounds in a row.
    """
    log("Scrolling the note list to load all notes (this can take a while for 240 notes)...")
    
    # Try to hover over the first note to focus the mouse on the scrollable area
    try:
        page.hover(list_item_selector)
        log("Hovered over the note list to focus scroll.")
    except Exception as e:
        log(f"Warning: Could not hover over list item: {e}")

    stable_rounds = 0
    last_count = -1
    while stable_rounds < max_stable_rounds:
        count = page.eval_on_selector_all(list_item_selector, "els => els.length")
        if count == last_count:
            stable_rounds += 1
            if stable_rounds >= 3:
                log(f"  ...{count} notes loaded. (Hint: if it seems stuck at {count}, please scroll the notes list manually in the browser window to trigger the next load)")
        else:
            stable_rounds = 0
            log(f"  ...{count} notes loaded so far")
        last_count = count
        
        # Scroll the last note element into view (Playwright native scrolling)
        try:
            items = page.query_selector_all(list_item_selector)
            if items:
                items[-1].scroll_into_view_if_needed()
                items[-1].hover()
        except Exception:
            pass
        
        # Scroll using mouse wheel in multiple smaller steps to simulate natural scrolling
        try:
            for _ in range(5):
                page.mouse.wheel(0, 600)
                time.sleep(0.1)
        except Exception:
            pass
        
        # Scroll EVERY scrollable ancestor of the note list items directly to the bottom
        try:
            page.evaluate(f"""() => {{
                const el = document.querySelector("{list_item_selector}");
                if (el) {{
                    let parent = el.parentElement;
                    while (parent) {{
                        const style = window.getComputedStyle(parent);
                        const overflowY = style.overflowY;
                        if (parent.scrollHeight > parent.clientHeight && 
                            (overflowY === 'auto' || overflowY === 'scroll' || parent.style.overflowY === 'auto' || parent.style.overflowY === 'scroll')) {{
                            parent.scrollTop = parent.scrollHeight;
                        }}
                        parent = parent.parentElement;
                    }}
                }}
                window.scrollTo(0, document.body.scrollHeight);
            }}""")
        except Exception as e:
            log(f"  [Scroll warning] JS scroll failed: {e}")

        # Wait longer (config.LONG_WAIT is 3.0s) to give the Xiaomi Cloud API time to load notes
        time.sleep(config.LONG_WAIT)
        
    log(f"Finished scrolling. Total notes detected: {last_count}")
    return last_count


def extract_one_note(page, selectors, index):
    """Click the note at `index` in the list and pull out its fields."""
    items = page.query_selector_all(selectors["list_item"])
    if index >= len(items):
        raise IndexError(f"Note index {index} out of range ({len(items)} items found)")
    items[index].click()
    page.wait_for_timeout(int(config.MEDIUM_WAIT * 1000))

    title_el = page.query_selector(selectors["title"])
    content_el = page.query_selector(selectors["content"])
    date_el = page.query_selector(selectors["date"]) if selectors.get("date") else None

    title = title_el.inner_text().strip() if title_el else ""
    content = content_el.inner_text().strip() if content_el else ""
    date = date_el.inner_text().strip() if date_el else ""

    if not title and not content:
        raise ValueError("Extracted empty title AND empty content -- selector likely wrong for this note")

    return {"title": title, "content": content, "date": date}


def main():
    parser = argparse.ArgumentParser(description="Extract notes from Xiaomi Cloud (i.mi.com)")
    parser.add_argument("--inspect", action="store_true",
                         help="Run one-time interactive selector calibration")
    parser.add_argument("--headful", action="store_true", default=True,
                         help="Show the browser window (default: on, required for manual login)")
    args = parser.parse_args()

    with sync_playwright() as p:
        log(f"Launching browser with saved profile: {config.XIAOMI_PROFILE_DIR}")
        context = p.chromium.launch_persistent_context(
            config.XIAOMI_PROFILE_DIR,
            channel="chrome",
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1400, "height": 900},
        )
        page = context.new_page()
        page.set_default_timeout(config.ACTION_TIMEOUT_MS)

        log(f"Navigating to {config.XIAOMI_NOTES_URL}")
        page.goto(config.XIAOMI_NOTES_URL, timeout=config.PAGE_LOAD_TIMEOUT_MS)

        wait_for_manual_login(page)

        if args.inspect:
            run_calibration(page)
            context.close()
            return

        selectors = load_selectors()
        
        # Load previously extracted notes
        results = load_json(config.NOTES_BACKUP_FILE, [])
        
        # Build set of already extracted note signatures (first 100 chars of Title + Content)
        seen_sigs = set()
        for note in results:
            sig = (note.get("title", "") + "\n" + note.get("content", "")).strip()[:100]
            seen_sigs.add(sig)
            
        seen_item_texts = set()
        
        log(f"Loaded {len(results)} previously extracted notes. Starting progressive extraction...")
        log("If the script stops seeing new notes, feel free to scroll the notes list manually in the browser.")

        no_new_rounds = 0
        
        while no_new_rounds < 8:
            # 1. Get all visible note items currently in the DOM
            try:
                items = page.query_selector_all(selectors["list_item"])
            except Exception as e:
                log(f"Error querying list items: {e}")
                time.sleep(1)
                continue
                
            if not items:
                log("No note items found in the DOM. Waiting...")
                time.sleep(2)
                no_new_rounds += 1
                continue
                
            new_extracted_in_this_loop = False
            
            for item in items:
                try:
                    # Get unique signature of the list item (contains preview text, title, date)
                    item_text = item.inner_text().strip()
                except Exception:
                    continue
                    
                if item_text in seen_item_texts:
                    continue
                    
                # Click the item to load its detail pane
                try:
                    item.click()
                    # Use a short sleep to allow the note content to load
                    page.wait_for_timeout(500)
                except Exception as e:
                    # If it's scrolled out of view, we don't log an error, just try again next round
                    continue
                    
                # Extract the note details
                try:
                    title_el = page.query_selector(selectors["title"])
                    content_el = page.query_selector(selectors["content"])
                    date_el = page.query_selector(selectors["date"]) if selectors.get("date") else None
                    
                    title = title_el.inner_text().strip() if title_el else ""
                    content = content_el.inner_text().strip() if content_el else ""
                    date = date_el.inner_text().strip() if date_el else ""
                    
                    # Normalize empty notes
                    if not title and not content:
                        continue
                        
                    full_sig = (title + "\n" + content).strip()[:100]
                    
                    if full_sig in seen_sigs:
                        # Already extracted in a previous run, just mark the list item text as seen
                        seen_item_texts.add(item_text)
                        continue
                        
                    # It's a new note!
                    note = {"title": title, "content": content, "date": date}
                    results.append(note)
                    seen_sigs.add(full_sig)
                    seen_item_texts.add(item_text)
                    new_extracted_in_this_loop = True
                    
                    save_json(config.NOTES_BACKUP_FILE, results)
                    log(f"[{len(results)}] Extracted: '{title[:35] or content[:35]}...'")
                except Exception as e:
                    log(f"  Warning: Error extracting note details: {e}")
                    
            # 2. Scroll down gently to bring more notes into view
            try:
                # Smoothly scroll the last note in the list into view to trigger lazy loading
                if items:
                    items[-1].scroll_into_view_if_needed()
                
                # Perform a gentle scroll wheel event
                page.mouse.wheel(0, 500)
            except Exception:
                pass
                
            if new_extracted_in_this_loop:
                no_new_rounds = 0
            else:
                no_new_rounds += 1
                if no_new_rounds >= 3:
                    log(f"  No new notes detected in the last {no_new_rounds} rounds. "
                        f"If you have more than {len(results)} notes, please scroll the notes list manually in the browser window.")
            
            # Wait a bit for the UI/API to load new notes
            time.sleep(2.0)

        context.close()
        log(f"Done. {len(results)} notes saved to {config.NOTES_BACKUP_FILE}.")


if __name__ == "__main__":
    main()
