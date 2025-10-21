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
    js_code = """
    (async () => {
        try {
            // Safe scrolling loop - no triggers
            for (let i = 0; i < 3; i++) {
                window.scrollBy(0, window.innerHeight);
                await new Promise(r => setTimeout(r, 1500));
            }

            // Simple wait for ads
            for (let i = 0; i < 10; i++) {
                if (document.querySelector('iframe[src*="ads"], .adsbygoogle, [data-ad], [id*="ad-"], [class*="ad-"]')) break;
                await new Promise(r => setTimeout(r, 2000));
            }

            const ads = [];
            document.querySelectorAll('iframe[src*="ads"], .adsbygoogle, [data-ad], [id*="ad-"], [class*="ad-"]').forEach((el, i) => {
                const link = el.querySelector('a')?.href || null;
                const img = el.querySelector('img')?.src || null;
                let adType = 'internal';
                const html = el.outerHTML.toLowerCase();

                if (html.includes('googletag') || html.includes('adsbygoogle')) adType = 'google';
                else if (html.includes('pubmatic') || html.includes('pwt')) adType = 'pubmatic';

                ads.push({
                    ad_id: i + 1,
                    ad_type: adType,
                    link: link,
                    image: img,
                    snippet: el.textContent.trim().substring(0, 200)
                });
            });

            window.__AD_DATA__ = { total: ads.length, ads };
            return window.__AD_DATA__;
        } catch(e) {
            return { error: e.message };
        }
    })();
    """


    config2 = CrawlerRunConfig(
        js_code=js_code,
        wait_until="domcontentloaded",
        
        # Key settings for news sites:
        wait_for="js:() => window.__AD_DATA__ !== undefined",  # Wait for your data
        verbose=True, 
        page_timeout= 120000, # 60 s
        cache_mode=CacheMode.DISABLED
        
        # Don't wait for network idle (news sites never idle)
        # wait_for_images=False,  # Skip waiting for all images
    
    )
    config3 = CrawlerRunConfig(
        js_code = """
            return Object.keys(window).filter(k => k.toLowerCase().includes('ad')).slice(0, 20);
        """,
        wait_for="js:() => window.__AD_DATA__ !== undefined",
        wait_until="domcontentloaded",  # don't wait for network idle
        page_timeout=90000,
        verbose=True
    )

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url, config=config2)
        if result.success: 
            save_json(data=result.js_execution_result, outfile=outfile)
            print(f"[+] Saved ad content to: {outfile}")
        else:
            print(f"[-] Crawl failed for {url}: {result.error_message}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crawl a webpage and save as Markdown using crawl4ai")
    parser.add_argument("--url", required=True, help="URL of the webpage to crawl")
    parser.add_argument("--outfile", required=True, help="Path to save the Markdown file")
    args = parser.parse_args()

    asyncio.run(crawl_with_ads(args.url, args.outfile))
