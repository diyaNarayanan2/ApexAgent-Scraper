import argparse
import asyncio
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, BrowserConfig
from crawl4ai.async_configs import CacheMode
import json

def save_json(data, outfile):
    # Open the file in write mode
    with open(outfile, "w") as file:
        # Convert the dictionary to a JSON string and write it to the file
        json.dump(data, file, indent=4)  # `indent=4` adds pretty formatting

async def crawl_with_ads(url: str, outfile: str): 
    # Streamlined JS code
    # Define your JavaScript code as a multi-line string
# This version is an IIFE that returns the JSON string
    js_code_string = """
    (function() {
        const adData = [];

        // Helper to get a unique selector for an element
        function getElementSelector(el) {
            if (!el || typeof el.tagName === 'undefined') {
                return null;
            }
            if (el.id) return `#${el.id}`;
            let selector = el.tagName.toLowerCase();
            if (el.className) {
                selector += '.' + Array.from(el.classList).join('.');
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
                    link: adEl.querySelector('a')?.href || 'N/A',
                    imageSrc: adEl.querySelector('img')?.src || 'N/A'
                });
            }
        });

        // Heuristic 2: Look for common ad iframes
        document.querySelectorAll('iframe').forEach(iframeEl => {
            const rect = iframeEl.getBoundingClientRect();
            if (rect.width > 0 && rect.height > 0) {
                let adType = 'Unknown External Ad';
                let iframeSrc = iframeEl.src || 'N/A';

                if (iframeSrc.includes('recaptcha')) { // Exclude reCAPTCHA
                    return; // Skip this iframe
                } else if (iframeSrc.includes('google') || iframeSrc.includes('doubleclick')) {
                    adType = 'Google Ad (iframe)';
                } else if (iframeSrc !== 'N/A' && !iframeSrc.includes(window.location.hostname)) {
                    adType = 'External Ad (iframe)';
                } else if (iframeSrc.includes(window.location.hostname)) {
                    adType = 'Internal Ad (iframe)';
                }

                let iframeDoc = null;
                try {
                    if (iframeEl.contentWindow && iframeEl.contentWindow.document) {
                        iframeDoc = iframeEl.contentWindow.document;
                    }
                } catch (e) {
                    // Cross-origin iframe, contentDocument is not accessible
                }

                adData.push({
                    type: adType,
                    selector: getElementSelector(iframeEl),
                    width: rect.width,
                    height: rect.height,
                    iframeSrc: iframeSrc,
                    link: iframeDoc?.querySelector('a')?.href || 'N/A',
                    imageSrc: iframeDoc?.querySelector('img')?.src || 'N/A'
                });
            }
        });

        // Heuristic 3: Look for divs with common ad classes/ids
        const genericAdSelectors = [
            'div[id*="ad"]', 'div[class*="ad-"]', 'div[class*="banner"]',
            'div[class*="advert"]', 'div[data-ad-type]',
            'div.gfg-ad-cont', 'div.ad_content_wrapper'
        ];
        genericAdSelectors.forEach(selector => {
            document.querySelectorAll(selector).forEach(el => {
                const rect = el.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0 && !adData.some(item => item.selector === getElementSelector(el))) {
                    let adType = 'Generic Ad';
                    const link = el.querySelector('a')?.href;
                    if (link && link.includes(window.location.hostname)) {
                        adType = 'Internal Ad';
                    } else if (link) {
                        adType = 'External Ad';
                    }

                    adData.push({
                        type: adType,
                        selector: getElementSelector(el),
                        width: rect.width,
                        height: rect.height,
                        link: link || 'N/A',
                        imageSrc: el.querySelector('img')?.src || 'N/A'
                    });
                }
            });
        });

        // Return the data directly from the IIFE
        return JSON.stringify(adData);
    })(); // <--- Don't forget to invoke the function!
    """

    config2 = CrawlerRunConfig(
        js_code = js_code_string,
        wait_until="domcontentloaded",
        
        # Key settings for news sites:
        wait_for="js:() => document.readyState === 'complete'",  # Wait for your data
        verbose=True, 
        page_timeout= 120000, # 60 s
        cache_mode=CacheMode.DISABLED
        
        # Don't wait for network idle (news sites never idle)
        # wait_for_images=False,  # Skip waiting for all images
    )

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url, config=config2)
        if result.success: 
            save_json(data=result.js_execution_result , outfile=outfile)
            print(f"[+] Saved ad content to: {outfile}")
        else:
            print(f"[-] Crawl failed for {url}: {result.error_message}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crawl a webpage and save as Markdown using crawl4ai")
    parser.add_argument("--url", required=True, help="URL of the webpage to crawl")
    parser.add_argument("--outfile", required=True, help="Path to save the Markdown file")
    args = parser.parse_args()

    asyncio.run(crawl_with_ads(args.url, args.outfile))
