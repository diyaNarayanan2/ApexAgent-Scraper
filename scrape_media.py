#!/usr/bin/env python3
import os
import re
import json
import hashlib
import argparse
import mimetypes
from urllib.parse import urlparse, urljoin
from base64 import b64decode

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# -------------------------------
# CONFIG
# -------------------------------
TIMEOUT = 30000  # 30s navigation timeout (adjust as needed)
WAIT_STRATEGIES = ["domcontentloaded", "load"]


# -------------------------------
# HELPERS - Content extraction
# -------------------------------
def extract_content_hierarchy(page):
    """Return header->text list structure (simplified)"""
    content = []
    headers = page.query_selector_all("h1, h2, h3, h4, h5, h6")

    if not headers:
        # fallback to paragraphs as a single "Page" section
        paragraphs = page.query_selector_all("p")
        text = " ".join([p.inner_text().strip() for p in paragraphs if p.inner_text().strip()])
        return [{"header": "Page", "text": text}]

    for i, header in enumerate(headers):
        try:
            header_text = header.inner_text().strip() or f"Section {i+1}"
        except Exception:
            header_text = f"Section {i+1}"

        paragraphs = []
        try:
            sibling = header.evaluate_handle("el => el.nextElementSibling")
            while sibling:
                # avoid errors if the element was detached
                try:
                    tag = sibling.evaluate("el => el.tagName ? el.tagName.toLowerCase() : null")
                except Exception:
                    break
                if not tag:
                    break
                if tag.startswith("h"):
                    break
                if tag == "p":
                    try:
                        para_text = sibling.evaluate("el => el.innerText").strip()
                        if para_text:
                            paragraphs.append(para_text)
                    except Exception:
                        pass
                # move to next sibling
                try:
                    sibling = sibling.evaluate_handle("el => el.nextElementSibling")
                except Exception:
                    break
        except Exception:
            # on any JS handle issues, ignore and continue
            pass

        combined_text = " ".join(paragraphs)
        content.append({"header": header_text, "text": combined_text})

    return content


# -------------------------------
# HELPERS - Media extraction
# -------------------------------
def collect_media_urls(page, base_url):
    """Collect candidate media URLs from many DOM/CSS sources on the page."""
    urls = set()

    # 1) Standard attributes (img, video, audio, source, link[rel~=icon], meta og:image)
    try:
        imgs = page.query_selector_all("img")
        for img in imgs:
            try:
                src = img.get_attribute("src")
                if src:
                    urls.add(urljoin(base_url, src))
                srcset = img.get_attribute("srcset")
                if srcset:
                    # srcset contains comma separated entries "url 1x, url2 2x"
                    for part in srcset.split(","):
                        url_part = part.strip().split()[0]
                        if url_part:
                            urls.add(urljoin(base_url, url_part))
            except Exception:
                continue
    except Exception:
        pass

    # video/audio/source/picture
    try:
        for sel in ["video", "audio", "source", "picture", "iframe"]:
            nodes = page.query_selector_all(sel)
            for n in nodes:
                try:
                    src = n.get_attribute("src")
                    if src:
                        urls.add(urljoin(base_url, src))
                    # <source src="">
                    src2 = n.get_attribute("data-src") or n.get_attribute("data-srcset")
                    if src2:
                        urls.add(urljoin(base_url, src2))
                except Exception:
                    continue
    except Exception:
        pass

    # link rel icons / images
    try:
        links = page.query_selector_all("link[rel]")
        for l in links:
            try:
                rel = (l.get_attribute("rel") or "").lower()
                if "icon" in rel or "image" in rel:
                    href = l.get_attribute("href")
                    if href:
                        urls.add(urljoin(base_url, href))
            except Exception:
                continue
    except Exception:
        pass

    # meta og:image
    try:
        metas = page.query_selector_all("meta[property='og:image'], meta[name='og:image']")
        for m in metas:
            try:
                content = m.get_attribute("content")
                if content:
                    urls.add(urljoin(base_url, content))
            except Exception:
                continue
    except Exception:
        pass

    # 2) Inline styles background-image via computed style
    try:
        background_candidates = page.evaluate(
            """() => {
                const out = [];
                const all = Array.from(document.querySelectorAll('*'));
                for (const el of all) {
                    try {
                        const style = window.getComputedStyle(el).getPropertyValue('background-image');
                        if (style && style !== 'none') out.push(style);
                    } catch (e) {
                        // ignore
                    }
                }
                return out;
            }"""
        )
        for item in background_candidates:
            # style like: url("..."), url('...'), linear-gradient(...), etc.
            matches = re.findall(r'url\((?:["\']?)(.*?)(?:["\']?)\)', item)
            for m in matches:
                if m:
                    urls.add(urljoin(base_url, m))
    except Exception:
        pass

    # 3) CSS files referenced on the page - fetch href of <link rel="stylesheet"> and scan for url(...)
    css_hrefs = []
    try:
        linksheets = page.query_selector_all("link[rel='stylesheet']")
        for l in linksheets:
            try:
                href = l.get_attribute("href")
                if href:
                    href_abs = urljoin(base_url, href)
                    css_hrefs.append(href_abs)
                    urls.add(href_abs)  # also include CSS itself
            except Exception:
                continue
    except Exception:
        pass

    # 4) Parse inline <style> blocks for url(...)
    try:
        style_nodes = page.query_selector_all("style")
        for s in style_nodes:
            try:
                txt = s.inner_text()
                matches = re.findall(r'url\((?:["\']?)(.*?)(?:["\']?)\)', txt)
                for m in matches:
                    if m:
                        urls.add(urljoin(base_url, m))
            except Exception:
                continue
    except Exception:
        pass

    return urls, css_hrefs


def download_with_requests(session, url, dest_path, max_bytes=None):
    """Download resource via requests.Session (stream), save to dest_path."""
    try:
        with session.get(url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            total = 0
            with open(dest_path, "wb") as fw:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        fw.write(chunk)
                        total += len(chunk)
                        if max_bytes and total > max_bytes:
                            # optional: allow stopping large downloads
                            break
        return True, None
    except Exception as e:
        return False, str(e)


def save_data_uri(data_uri, dest_path):
    """Decode data:... base64 URI and write to file"""
    try:
        header, b64 = data_uri.split(",", 1)
        if ";base64" in header:
            raw = b64decode(b64)
        else:
            raw = b64.encode("utf-8")
        with open(dest_path, "wb") as f:
            f.write(raw)
        return True, None
    except Exception as e:
        return False, str(e)


def guess_extension_from_url_or_type(url, content_type=None):
    """Attempt to produce a file extension for saving."""
    # try from URL path
    parsed = urlparse(url)
    base = os.path.basename(parsed.path)
    if "." in base:
        ext = os.path.splitext(base)[1]
        if ext:
            return ext
    # fallback from content-type
    if content_type:
        ext = mimetypes.guess_extension(content_type.split(";")[0].strip())
        if ext:
            return ext
    return ""


# -------------------------------
# MAIN - parse + collect + download
# -------------------------------
def parse_single_page_and_media(start_url, outfile, media_dir):
    parsed_base = urlparse(start_url)
    base_origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
    os.makedirs(media_dir, exist_ok=True)

    results = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-blink-features=AutomationControlled"])
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        page = context.new_page()

        # navigate with fallback wait strategies
        print(f"Visiting {start_url} ...")
        for wait_type in WAIT_STRATEGIES:
            try:
                page.goto(start_url, wait_until=wait_type, timeout=TIMEOUT)
                break
            except PlaywrightTimeout:
                print(f"⚠️ Timeout with wait='{wait_type}', trying next...")
        else:
            print("⚠️ All navigation strategies timed out — continuing with partial load.")

        # structured content
        content = extract_content_hierarchy(page)
        results["url"] = start_url
        results["domain"] = parsed_base.netloc
        results["content"] = content

        # collect media candidate URLs and linked CSS files
        media_urls, css_hrefs = collect_media_urls(page, start_url)
        print(f"Found {len(media_urls)} media/CSS candidates on page and {len(css_hrefs)} CSS files to scan.")

        # prepare requests.Session using cookies from Playwright so protected resources can be fetched
        sess = requests.Session()
        # Save user-agent string in a variable when creating the context
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        context = browser.new_context(user_agent=user_agent)

        # Later, set it explicitly in requests.Session
        sess.headers.update({"User-Agent": user_agent})

        try:
            # get cookies from context
            cookies = context.cookies()
            jar = requests.cookies.RequestsCookieJar()
            for c in cookies:
                # convert Playwright cookie to requests cookie
                jar.set(c.get("name"), c.get("value"), domain=c.get("domain"), path=c.get("path"))
            sess.cookies = jar
        except Exception:
            pass

        # download list and keep mapping
        downloaded = {}
        errors = {}

        # 1) First handle CSS files: fetch and parse url(...) to find assets referenced inside
        for css_url in css_hrefs:
            try:
                css_abs = urljoin(start_url, css_url)
                print(f"Fetching CSS {css_abs} ...")
                r = sess.get(css_abs, timeout=30)
                if r.status_code == 200:
                    # search for url(...) patterns
                    matches = re.findall(r'url\((?:["\']?)(.*?)(?:["\']?)\)', r.text)
                    for m in matches:
                        if m:
                            media_urls.add(urljoin(css_abs, m))
                else:
                    print(f"⚠️ CSS fetch returned {r.status_code} for {css_abs}")
            except Exception as e:
                print(f"⚠️ CSS fetch error: {e}")

        # 2) Iterate through media candidates and download
        for murl in sorted(media_urls):
            if not murl:
                continue
            if murl in downloaded or murl in errors:
                continue

            # handle data URIs separately
            if murl.startswith("data:"):
                # guess extension from media type if present in header
                header = murl.split(",", 1)[0]
                content_type = None
                if ";" in header:
                    content_type = header.split(";", 1)[0].split(":", 1)[1] if ":" in header else None
                ext = guess_extension_from_url_or_type(murl, content_type) or ".bin"
                # create filename by hashing the URI (to avoid super long names)
                h = hashlib.sha256(murl.encode("utf-8")).hexdigest()[:16]
                fname = f"{h}{ext}"
                dest = os.path.join(media_dir, fname)
                ok, err = save_data_uri(murl, dest)
                if ok:
                    downloaded[murl] = dest
                    print(f"[DATA] Saved {murl[:60]}... -> {dest}")
                else:
                    errors[murl] = err
                    print(f"[DATA-ERR] {murl[:60]}... -> {err}")
                continue

            # otherwise, standard URL
            try:
                abs_url = urljoin(start_url, murl)
            except Exception:
                abs_url = murl

            # HEAD request to determine content-type and length (if remote server allows)
            try:
                head = sess.head(abs_url, allow_redirects=True, timeout=20)
                content_type = head.headers.get("content-type", "")
            except Exception:
                content_type = None

            ext = guess_extension_from_url_or_type(abs_url, content_type) or ""
            # file base name from URL path, else use hash
            name_base = os.path.basename(urlparse(abs_url).path) or ""
            if not name_base or "." not in name_base:
                # derive from hash
                h = hashlib.sha256(abs_url.encode("utf-8")).hexdigest()[:16]
                fname = f"{h}{ext or '.bin'}"
            else:
                # sanitize name_base
                safe_base = re.sub(r'[^A-Za-z0-9._-]', '_', name_base)
                fname = safe_base
                if ext and not fname.endswith(ext):
                    fname = f"{fname}{ext}"

            dest = os.path.join(media_dir, fname)

            # If filename exists, add numeric suffix to avoid overwrite
            base_noext, extension = os.path.splitext(dest)
            counter = 1
            while os.path.exists(dest):
                dest = f"{base_noext}_{counter}{extension}"
                counter += 1

            # Download (stream)
            print(f"Downloading: {abs_url} -> {dest}")
            ok, err = download_with_requests(sess, abs_url, dest)
            if ok:
                downloaded[murl] = dest
            else:
                errors[murl] = err
                print(f"⚠️ Error downloading {abs_url}: {err}")

        # finalize results
        results["media"] = { "downloaded": downloaded, "errors": errors }

        # also collect top-level links from page (only first page)
        try:
            anchors = page.query_selector_all("a[href]")
            links = sorted(set([urljoin(start_url, a.get_attribute("href")) for a in anchors if a.get_attribute("href")]))
        except Exception:
            links = []
        results["links"] = links

        # write JSON
        os.makedirs(os.path.dirname(outfile) or ".", exist_ok=True)
        with open(outfile, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print(f"\n✅ Done. Output saved to {outfile}")
        print(f"Media saved to: {media_dir} (downloaded: {len(downloaded)}, errors: {len(errors)})")

        browser.close()


# -------------------------------
# CLI
# -------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract page content and download media assets from a single webpage.")
    parser.add_argument("--url", required=True, help="URL to scrape")
    parser.add_argument("--outfile", required=True, help="Output JSON path (structured content + media manifest)")
    parser.add_argument("--media-dir", default="media", help="Directory to save media files")
    args = parser.parse_args()

    parse_single_page_and_media(args.url, args.outfile, args.media_dir)
