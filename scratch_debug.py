import os
import sys
import time
from playwright.sync_api import sync_playwright
import config

def main():
    with sync_playwright() as p:
        print("Launching browser...")
        context = p.chromium.launch_persistent_context(
            config.XIAOMI_PROFILE_DIR,
            channel="chrome",
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1400, "height": 900},
        )
        page = context.new_page()
        print("Navigating to Xiaomi Notes...")
        page.goto(config.XIAOMI_NOTES_URL)
        
        print("Waiting 15 seconds for notes list to be visible...")
        time.sleep(15)
        
        # 1. Take a screenshot
        screenshot_path = os.path.join(config.BASE_DIR, "data", "debug_screenshot.png")
        page.screenshot(path=screenshot_path)
        print(f"Screenshot saved to: {screenshot_path}")
        
        # 2. Count list items
        list_item_selector = "div[class*='note-item']"
        count = page.eval_on_selector_all(list_item_selector, "els => els.length")
        print(f"Current count of '{list_item_selector}': {count}")
        
        # 3. Analyze DOM containers and scrollability
        diagnostics = page.evaluate("""() => {
            const results = [];
            const all = document.querySelectorAll('*');
            for (const el of all) {
                if (el.scrollHeight > el.clientHeight) {
                    const style = window.getComputedStyle(el);
                    const overflowY = style.overflowY;
                    if (overflowY === 'auto' || overflowY === 'scroll') {
                        let path = el.tagName.toLowerCase();
                        if (el.id) path += '#' + el.id;
                        if (el.className) path += '.' + Array.from(el.classList).join('.');
                        results.push({
                            selector: path,
                            scrollHeight: el.scrollHeight,
                            clientHeight: el.clientHeight,
                            scrollTop: el.scrollTop,
                            overflowY: overflowY
                        });
                    }
                }
            }
            return results;
        }""")
        print("Scrollable containers found:")
        for idx, diag in enumerate(diagnostics):
            print(f"  [{idx}] {diag['selector']}")
            print(f"      scrollHeight: {diag['scrollHeight']}, clientHeight: {diag['clientHeight']}, scrollTop: {diag['scrollTop']}, overflowY: {diag['overflowY']}")
            
        context.close()

if __name__ == '__main__':
    main()
