import argparse
import asyncio
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, BrowserConfig
from crawl4ai.async_configs import CacheMode

async def crawl_to_markdown(url: str, outfile: str):
    config = CrawlerRunConfig(
        # Force the crawler to wait until images are fully loaded 
        wait_for_images = True,

        # Automatically scroll the page to load lazy content
        scan_full_page = True, 
        # Add delay between scroll steps 
        scroll_delay = 0.5, 
        cache_mode = CacheMode.BYPASS,
        verbose = True
    )
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url, config=config)
        if result.success:
            with open(outfile, "w", encoding="utf-8") as f:
                f.write(result.markdown)
            print(f"[+] Saved markdown to: {outfile}")
        else:
            print(f"[-] Crawl failed for {url}: {result.error_message}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crawl a webpage and save as Markdown using crawl4ai")
    parser.add_argument("--url", required=True, help="URL of the webpage to crawl")
    parser.add_argument("--outfile", required=True, help="Path to save the Markdown file")
    args = parser.parse_args()

    asyncio.run(crawl_to_markdown(args.url, args.outfile))
