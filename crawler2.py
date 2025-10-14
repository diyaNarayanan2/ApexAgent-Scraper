import os
import json
import argparse
from urllib.parse import urlparse, urljoin
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# -------------------------------
# CONFIG
# -------------------------------
TIMEOUT = 15000          # 15 seconds timeout
WAIT_STRATEGIES = ["domcontentloaded", "load"]  # fallback strategies


# -------------------------------
# HELPERS
# -------------------------------
def save_text(domain, url, structured_text):
    """Save structured text into text/<domain>/<page>.txt"""
    safe_name = url.replace("https://", "").replace("http://", "").replace("/", "_")
    os.makedirs(f"text/{domain}", exist_ok=True)
    text_path = f"text/{domain}/{safe_name}.txt"

    with open(text_path, "w", encoding="utf-8") as f:
        for section, content in structured_text.items():
            f.write(f"\n=== {section.upper()} ===\n")
            if isinstance(content, list):
                for item in content:
                    f.write(f"- {item}\n")
            else:
                f.write(f"{content}\n")
    return text_path


def save_json(domain, data):
    """Save structured JSON data to processed/<domain>.json"""
    os.makedirs("processed", exist_ok=True)
    json_path = f"processed/{domain}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return json_path


def extract_links(page, base_url, local_domain):
    """Extract internal links only from the given page."""
    anchors = page.query_selector_all("a[href]")
    links = set()
    for a in anchors:
        href = a.get_attribute("href")
        if not href:
            continue
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)
        if parsed.netloc == local_domain:
            links.add(abs_url.split("#")[0])
    return sorted(list(links))


def extract_structured_text(page):
    """Extract text grouped by semantic page sections."""
    structured = {}

    selectors = {
        "title": "title",
        "headers": "h1, h2, h3, h4, h5, h6",
        "paragraphs": "p",
        "buttons": "button, input[type='button'], input[type='submit']",
        "links_text": "a",
        "lists": "li",
        "footer": "footer",
    }

    for section, selector in selectors.items():
        try:
            elements = page.query_selector_all(selector)
            structured[section] = [
                el.inner_text().strip() for el in elements if el.inner_text().strip()
            ]
        except Exception:
            structured[section] = []

    # For completeness, also store raw visible body text (fallback)
    try:
        structured["body_text"] = page.inner_text("body")
    except Exception:
        structured["body_text"] = ""

    return structured


# -------------------------------
# MAIN FUNCTION
# -------------------------------
def parse_single_page(start_url):
    local_domain = urlparse(start_url).netloc
    results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/119.0.0.0 Safari/537.36"
            )
        )

        page = context.new_page()
        print(f"🌐 Visiting {start_url}")

        # Try multiple wait strategies to reduce timeouts
        for wait_type in WAIT_STRATEGIES:
            try:
                page.goto(start_url, wait_until=wait_type, timeout=TIMEOUT)
                break
            except PlaywrightTimeout:
                print(f"⚠️ Timeout on wait='{wait_type}', trying next...")
        else:
            print("❌ All wait strategies failed. Proceeding with partial load.")

        # Optional: auto-accept cookie banners
        for selector in ['button:has-text("Accept")', 'button:has-text("OK")']:
            try:
                if page.locator(selector).is_visible():
                    page.click(selector)
                    print("✅ Accepted cookies banner.")
                    break
            except Exception:
                pass

        # Extract structured content
        structured_text = extract_structured_text(page)

        # Extract links (internal only)
        links = extract_links(page, start_url, local_domain)

        results = {
            "url": start_url,
            "domain": local_domain,
            "structured_text": structured_text,
            "links": links,
        }

        # Save files
        text_path = save_text(local_domain, start_url, structured_text)
        json_path = save_json(local_domain, results)

        browser.close()

    print(f"\n✅ Done! Extracted structured text and links from {start_url}")
    print(f"📁 Text saved at: {text_path}")
    print(f"📄 JSON saved at: {json_path}")


# -------------------------------
# ENTRY POINT (ARGPARSE)
# -------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract structured text and links from a single webpage."
    )
    parser.add_argument(
        "--url",
        type=str,
        required=True,
        help="The URL of the webpage to extract text and links from.",
    )

    args = parser.parse_args()
    parse_single_page(args.url)
