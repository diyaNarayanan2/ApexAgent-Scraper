import os 
import argparse
import asyncio
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, BrowserConfig
from crawl4ai.async_configs import CacheMode
import json
import base64


async def crawl_full(url: str, filename: str):
    folder_path = "result_full"
    js_manage_url = """
    """
    full_folder = os.path.join(folder_path, f"{filename}")
    os.makedirs(full_folder, exist_ok=True)
    file_path = os.path.join(full_folder, f"{filename}_md.md")


    config1 = CrawlerRunConfig(
        js_code= js_manage_url, 
        wait_until="domcontentloaded",
        verbose=True,
        page_timeout=120000,
        wait_for_images=True, 
        screenshot=True, 
        pdf=True,
        capture_mhtml=True
    )
    async with AsyncWebCrawler() as crawler: 
        result = await crawler.arun(url=url, config=config1)
        if result.success: 
            print("Result is successfully scraped")
            with open(file_path, "w", encoding="utf-8") as f: 
                f.write(result.markdown)
            print(f"[+] Saved markdown to: {filename} folder")

            html_path = os.path.join(full_folder, f"{filename}_html.html")
            with open(html_path, "w") as f: 
                f.write(result.html)
            print(f"Saved html to {html_path}")

            images = result.media.get("images", [])
            img_path = os.path.join(full_folder, f"{filename}_imgs.json")
            with open(img_path, "w") as f: 
                json.dump(images, f, indent=2)
            print(f"{len(images)} images saved to {img_path}")
            # non images media?

            internal_links = result.links.get("internal", [])
            external_links = result.links.get("external", [])
            link_path = os.path.join(full_folder, f"{filename}_links.json")
            with open(link_path, "w") as f: 
                json.dump(
                    {'internal': internal_links, 'external': external_links},
                    f,
                    indent=2
                )
            print(f"Found {len(internal_links)} internal and {len(external_links)} external links")
            print(f"Links saved to {link_path}")
            
            shot_path = os.path.join(full_folder, f"{filename}_screenshot.png")
            with open(shot_path, "wb") as f: 
                f.write(base64.b64decode(result.screenshot))
            print(f"Screenshot saved to {shot_path}")

            mhtml_path = os.path.join(full_folder, f"{filename}_mhtml.mhtml")
            with open(mhtml_path, "w", encoding="utf-8") as f: 
                f.write(result.mhtml)
            print(f"MHTML saved to {mhtml_path}")



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crawl a url and save the full result across multiple files")
    parser.add_argument("--url", required=True, help="URL of the webpage to be scraped")
    parser.add_argument("--filename", required=True, help="Name of the folder in output where the full result should be stored")
    args = parser.parse_args()

    asyncio.run(crawl_full(args.url, args.filename))



