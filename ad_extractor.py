import argparse
import json
import os
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, ElementHandle

def extract_ads_with_playwright(url: str, output_file: str):
    """
    Navigates to a URL, extracts information about ads, takes screenshots of ads,
    and saves the data to a JSON file.
    """
    
    ad_results = []
    
    # Create a directory for ad screenshots
    screenshots_dir = Path("ad_screenshots") / Path(url).name.replace('.', '_').replace('/', '_')
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True) # Set headless=False to see the browser
        page = browser.new_page()

        print(f"Navigating to: {url}")
        try:
            page.goto(url, wait_until="networkidle")
            # Give a little extra time for very late-loading ads, adjust if needed
            page.wait_for_timeout(60000)
        except Exception as e:
            print(f"Error navigating to {url}: {e}")
            browser.close()
            return

        print("Page loaded. Executing JavaScript for ad detection...")

        # JavaScript code to run in the browser context
        # This function identifies potential ads and collects their basic data
        js_ad_detection_script = """
        (function() {
            const adData = [];

            function getElementSelector(el) {
                if (!el || typeof el.tagName === 'undefined') {
                    return null;
                }
                if (el.id) return '#' + CSS.escape(el.id); // Use CSS.escape for robustness
                let selector = el.tagName.toLowerCase();
                if (el.className) {
                    selector += '.' + Array.from(el.classList).map(cls => CSS.escape(cls)).join('.');
                }
                return selector;
            }

            // Heuristic 1: Look for Google AdSense containers
            document.querySelectorAll('ins.adsbygoogle').forEach(adEl => {
                const rect = adEl.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) { // Only consider visible ads
                    adData.push({
                        type: 'Google AdSense',
                        selector: getElementSelector(adEl),
                        width: rect.width,
                        height: rect.height,
                        x: rect.x,
                        y: rect.y,
                        link: adEl.querySelector('a')?.href || null,
                        imageSrc: adEl.querySelector('img')?.src || null
                    });
                }
            });

            // Heuristic 2: Look for common ad iframes
            document.querySelectorAll('iframe').forEach(iframeEl => {
                const rect = iframeEl.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    let adType = 'Unknown External Ad';
                    let iframeSrc = iframeEl.src || null;

                    if (iframeSrc && iframeSrc.includes('recaptcha')) { // Exclude reCAPTCHA
                        return; 
                    } else if (iframeSrc && (iframeSrc.includes('google') || iframeSrc.includes('doubleclick'))) {
                        adType = 'Google Ad (iframe)';
                    } else if (iframeSrc && !iframeSrc.includes(window.location.hostname)) {
                        adType = 'External Ad (iframe)';
                    } else if (iframeSrc && iframeSrc.includes(window.location.hostname)) {
                        adType = 'Internal Ad (iframe)'; 
                    }

                    // For cross-origin iframes, contentDocument is not accessible due to Same-Origin Policy
                    // So link and imageSrc will likely be null for most ad iframes
                    let link = null;
                    let imageSrc = null;
                    try {
                        if (iframeEl.contentWindow && iframeEl.contentWindow.document) {
                            link = iframeEl.contentWindow.document.querySelector('a')?.href;
                            imageSrc = iframeEl.contentWindow.document.querySelector('img')?.src;
                        }
                    } catch (e) {
                        // Cross-origin access blocked, link/imageSrc remain null
                    }

                    adData.push({
                        type: adType,
                        selector: getElementSelector(iframeEl),
                        width: rect.width,
                        height: rect.height,
                        x: rect.x,
                        y: rect.y,
                        iframeSrc: iframeSrc,
                        link: link,
                        imageSrc: imageSrc
                    });
                }
            });

            // Heuristic 3: Look for divs with common ad classes/ids (refine as needed)
            const genericAdSelectors = [
                'div[id*="ad"]', 'div[class*="ad-"]', 'div[class*="banner"]',
                'div[class*="advert"]', 'div[data-ad-type]',
                'div.gfg-ad-cont', 'div.ad_content_wrapper' // Example specific to GFG
            ];
            genericAdSelectors.forEach(selector => {
                document.querySelectorAll(selector).forEach(el => {
                    const rect = el.getBoundingClientRect();
                    // Avoid duplicates and only consider visible elements
                    // Check if an ad with the same selector or very similar dimensions/position is already found
                    const currentSelector = getElementSelector(el);
                    if (rect.width > 0 && rect.height > 0 && 
                        !adData.some(item => item.selector === currentSelector || 
                                             (Math.abs(item.x - rect.x) < 5 && Math.abs(item.y - rect.y) < 5 && Math.abs(item.width - rect.width) < 5 && Math.abs(item.height - rect.height) < 5))) {
                        
                        let adType = 'Generic Ad';
                        const link = el.querySelector('a')?.href;
                        if (link && link.includes(window.location.hostname)) {
                            adType = 'Internal Ad';
                        } else if (link) {
                            adType = 'External Ad';
                        }

                        adData.push({
                            type: adType,
                            selector: currentSelector,
                            width: rect.width,
                            height: rect.height,
                            x: rect.x,
                            y: rect.y,
                            link: link,
                            imageSrc: el.querySelector('img')?.src || null
                        });
                    }
                });
            });

            return JSON.stringify(adData);
        })();
        """

        # Execute the JavaScript and get the results
        js_raw_results = page.evaluate(js_ad_detection_script)
        
        try:
            identified_ads = json.loads(js_raw_results)
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON from JS execution: {e}")
            print(f"Raw JS result: {js_raw_results}")
            identified_ads = []

        print(f"Found {len(identified_ads)} potential ad elements from JS detection.")

        # --- Iterate through identified ads and take screenshots ---
        for i, ad_info in enumerate(identified_ads):
            selector = ad_info.get("selector")
            if not selector:
                print(f"Warning: Ad {i} has no selector. Skipping screenshot.")
                continue

            try:
                # Playwright's locator to find the element
                ad_element = page.locator(selector).first

                # Check if the element exists and is visible
                if ad_element and ad_element.is_visible():
                    screenshot_name = f"ad_{i}_{ad_info['type'].replace(' ', '_').replace('(', '').replace(')', '')}_{ad_info['width']}x{ad_info['height']}.png"
                    screenshot_path = screenshots_dir / screenshot_name
                    
                    print(f"Attempting screenshot for ad {i} ({ad_info['type']}) at {screenshot_path}")
                    ad_element.screenshot(path=str(screenshot_path))
                    ad_info['screenshot_path'] = str(screenshot_path)
                else:
                    print(f"Warning: Ad element for selector '{selector}' not found or not visible. Skipping screenshot.")
                    ad_info['screenshot_path'] = "N/A (element not found or visible)"

            except Exception as e:
                print(f"Error taking screenshot for ad {i} (selector: {selector}): {e}")
                ad_info['screenshot_path'] = f"Error: {e}"
            
            ad_results.append(ad_info)

        browser.close()

    # --- Save all results to a JSON file ---
    final_output = {
        "url": url,
        "total_ads_identified": len(ad_results),
        "ad_data": ad_results
    }
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(final_output, f, indent=4, ensure_ascii=False)
    
    print(f"\nAd extraction complete. Results saved to {output_file}")
    print(f"Screenshots saved to: {screenshots_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extracts ad information from a webpage using Playwright.")
    parser.add_argument("--url", required=True, help="The URL of the webpage to scrape.")
    parser.add_argument("--outfile", default="ad_extraction_results.json",
                        help="Path to the output JSON file. Defaults to 'ad_extraction_results.json'.")
    
    args = parser.parse_args()
    
    extract_ads_with_playwright(args.url, args.outfile)