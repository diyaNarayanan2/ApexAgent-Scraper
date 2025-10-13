import os
import time
import json
import random
from urllib.parse import urlparse, urljoin
from collections import deque
from playwright.sync_api import sync_playwright

# -------------------------------
# CONFIG
# -------------------------------
START_URL = "https://www.pymc-labs.com/blog-posts/2022-10-26-AlvaLabs"   # <-- change this to your target site
MAX_PAGES = 50                     # safety limit to avoid infinite crawling
DELAY_RANGE = (1.5, 3.0)           # polite random delay between page loads

# -------------------------------
# HELPER FUNCTIONS
# -------------------------------

def save_text(domain, url, text):
    """Save text of a page into text/<domain>/<page>.txt"""
    safe_name = url.replace("https://", "").replace("http://", "").replace("/", "_")
    os.makedirs(f"text/{domain}", exist_ok=True)
    with open(f"text/{domain}/{safe_name}.txt", "w", encoding="utf-8") as f:
        f.write(text)


def save_json(domain, data):
    """Save all collected data to processed/<domain>.json"""
    os.makedirs("processed", exist_ok=True)
    json_path = f"processed/{domain}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def extract_links(page, base_url, local_domain):
    """Extract and clean internal links from the page."""
    anchors = page.query_selector_all("a[href]")
    links = set()
    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)
        if parsed.netloc == local_domain:
            links.add(abs_url.split("#")[0])  # remove fragments
    return list(links)


# -------------------------------
# MAIN CRAWLER FUNCTION
# -------------------------------

def playwright_crawl(start_url):
    local_domain = urlparse(start_url).netloc
    seen = set([start_url])
    queue = deque([start_url])
    results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()

        print(f"🌐 Starting crawl on: {start_url}")
        page = context.new_page()

        while queue and len(results) < MAX_PAGES:
            url = queue.popleft()
            print(f"[{len(results)+1}] Visiting: {url}")

            try:
                page.goto(url, wait_until="networkidle", timeout=30000)

                # OPTIONAL: auto-accept cookie banners
                for selector in ['button:has-text("Accept")', 'button:has-text("OK")']:
                    try:
                        if page.locator(selector).is_visible():
                            page.click(selector)
                            print("✅ Accepted cookies banner.")
                            break
                    except Exception:
                        pass

                # Extract text
                text = page.inner_text("body")
                results[url] = text
                save_text(local_domain, url, text)

                # Extract internal links
                links = extract_links(page, url, local_domain)
                for link in links:
                    if link not in seen:
                        seen.add(link)
                        queue.append(link)

                # Polite delay
                sleep_time = random.uniform(*DELAY_RANGE)
                print(f"🕒 Sleeping {sleep_time:.2f}s...")
                time.sleep(sleep_time)

            except Exception as e:
                print(f"⚠️ Error visiting {url}: {e}")

        browser.close()

    # Save results
    save_json(local_domain, results)
    print(f"\n✅ Crawl complete! {len(results)} pages saved.")
    print(f"📁 Text files: text/{local_domain}/")
    print(f"📄 JSON file: processed/{local_domain}.json")


# -------------------------------
# ENTRY POINT
# -------------------------------
if __name__ == "__main__":
    playwright_crawl(START_URL)
