import re
import json
import asyncio
import time
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from bs4 import BeautifulSoup
from config import BASE_URL, CATEGORY_URLS
from embedding_service import EmbeddingService
from database import DatabaseService


class ProductScraper:
    def __init__(self):
        self.base_url = BASE_URL
        self.embedding_service = EmbeddingService()
        self.product_links = []

    async def scroll_page(self, page, max_scrolls: int = 80):
        last_count = 0
        scroll_attempts = 0
        
        # First wait for initial load
        await page.wait_for_timeout(3000)

        for i in range(max_scrolls):
            # Scroll to bottom
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)
            
            # Also try to trigger any "load more" buttons
            try:
                await page.evaluate("""() => {
                    // Click any load more buttons
                    document.querySelectorAll('button, a').forEach(el => {
                        const text = el.textContent.toLowerCase();
                        if (text.includes('load more') || text.includes('ver más') || text.includes('see more')) {
                            el.click();
                        }
                    });
                }""")
            except:
                pass
            
            await asyncio.sleep(1)

            current_count = await page.evaluate("document.querySelectorAll('a[href*=\"/product/\"]').length")

            if current_count > last_count:
                print(f"    Products loaded: {current_count}")
                last_count = current_count
                scroll_attempts = 0
            else:
                scroll_attempts += 1
                if scroll_attempts >= 5:
                    break

        return await page.evaluate("""() => {
            const links = [];
            const seen = new Set();
            document.querySelectorAll('a[href*="/product/"]').forEach(a => {
                const href = a.getAttribute('href');
                if (href && !seen.has(href)) {
                    seen.add(href);
                    links.push(href);
                }
            });
            return links;
        }""")

    async def scrape_collection_page(self, url: str) -> list[str]:
        product_urls = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                await page.goto(url, timeout=60000)
                await page.wait_for_timeout(3000)

                links = await self.scroll_page(page)
                
                # Build full URLs from relative paths
                for link in links:
                    if '/product/' in link:
                        if link.startswith('/'):
                            # Relative URL - prepend base
                            from urllib.parse import urlparse
                            parsed = urlparse(url)
                            full_url = f"{parsed.scheme}://{parsed.netloc}{link}"
                        else:
                            full_url = link.split('?')[0].split('#')[0]
                        product_urls.append(full_url)

                await browser.close()
            except Exception as e:
                print(f"Error scraping {url}: {e}")
                await browser.close()

        return list(set(product_urls))

    async def extract_product_info(self, page, url: str) -> dict:
        info = {
            "product_url": url,
            "title": None,
            "description": None,
            "image_url": None,
            "additional_images": [],
            "categories": [],
            "gender": None,
            "metadata": {},
            "brand": "Eme Studios",
            "price": None,
            "sale": None,
        }

        try:
            page_title = await page.title()
            if page_title:
                info["title"] = page_title.split("|")[0].split("-")[0].strip()
        except:
            pass

        try:
            title_result = await page.evaluate("""() => {
                const titleEl = document.querySelector('h1.product-title') ||
                              document.querySelector('h1[itemprop="name"]') ||
                              document.querySelector('.product-info h1') ||
                              document.querySelector('.product__title') ||
                              document.querySelector('h1');
                if (titleEl) {
                    let text = titleEl.textContent.trim();
                    text = text.replace(/\\s+/g, ' ').trim();
                    return text;
                }
                return null;
            }""")
            if title_result:
                info["title"] = title_result
        except:
            pass

        try:
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            scripts = soup.find_all("script", {"type": "application/ld+json"})
            for script in scripts:
                try:
                    data = json.loads(script.string or script.get_text())
                    if data.get("@type") == "Product":
                        info["title"] = data.get("name", info["title"])
                        info["description"] = data.get("description", "")
                        
                        offers = data.get("offers", {})
                        if isinstance(offers, dict):
                            price = offers.get("price") or offers.get("lowPrice")
                            if price:
                                currency = offers.get("priceCurrency", "EUR")
                                info["price"] = f"{price}{currency}"
                            
                            high_price = offers.get("highPrice")
                            if high_price and high_price != price:
                                info["sale"] = f"{high_price}{currency}"
                        
                        images = data.get("image") or []
                        if images:
                            if isinstance(images, list):
                                info["image_url"] = str(images[0])
                                info["additional_images"] = [str(img) for img in images[1:6]]
                            else:
                                info["image_url"] = str(images)
                        
                        break
                except:
                    continue

            if not info.get("title"):
                og_title = soup.find("meta", {"property": "og:title"})
                if og_title:
                    info["title"] = og_title.get("content", "")

            if not info.get("image_url"):
                og_image = soup.find("meta", {"property": "og:image"})
                if og_image:
                    info["image_url"] = og_image.get("content", "")

            if not info.get("description"):
                meta_desc = soup.find("meta", {"name": "description"})
                if meta_desc:
                    info["description"] = meta_desc.get("content", "")

            url_lower = url.lower()
            if "/woman" in url_lower:
                info["gender"] = "woman"
            elif "/man" in url_lower:
                info["gender"] = "man"
            else:
                info["gender"] = "woman"

        except Exception as e:
            print(f"Error extracting product info: {e}")

        info["metadata"]["url"] = url
        info["metadata"]["gender"] = info["gender"]
        info["metadata"]["scraped_at"] = time.time()

        return info

    async def scrape_product(self, url: str) -> dict:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)

                product_info = await self.extract_product_info(page, url)

                if product_info.get("image_url"):
                    print(f"  Getting embeddings for: {product_info.get('title', 'unknown')[:30]}")
                    product_info["image_embedding"] = self.embedding_service.get_image_embedding(product_info["image_url"])
                    
                    text_info = f"{product_info.get('title', '')} {product_info.get('brand', '')} {product_info.get('description', '') or ''} {product_info.get('category', '') or ''} {product_info.get('gender', '') or ''} {product_info.get('price', '') or ''}"
                    product_info["info_embedding"] = self.embedding_service.get_text_embedding(text_info)

                await browser.close()
                return product_info

            except Exception as e:
                print(f"Error scraping product {url}: {e}")
                await browser.close()
                return None

    async def run(self) -> list[dict]:
        all_products = []
        
        for category_url in CATEGORY_URLS:
            print(f"\nScraping category: {category_url}")
            
            try:
                product_urls = await self.scrape_collection_page(category_url)
                print(f"  Found {len(product_urls)} products")
                
                for i, url in enumerate(product_urls):
                    print(f"  [{i+1}/{len(product_urls)}] {url}")
                    product = await self.scrape_product(url)
                    if product:
                        all_products.append(product)
                    
                    await asyncio.sleep(0.3)
                    
            except Exception as e:
                print(f"Error in category {category_url}: {e}")
                continue
        
        return all_products


if __name__ == "__main__":
    async def main():
        scraper = ProductScraper()
        products = await scraper.run()
        
        print(f"\nScraped {len(products)} products")
        
        if products:
            db = DatabaseService()
            results = db.process_products(products)
            
            print(f"\nResults:")
            print(f"  New: {results.get('new', 0)}")
            print(f"  Updated: {results.get('updated', 0)}")
            print(f"  Skipped: {results.get('skipped', 0)}")
            print(f"  Deleted: {results.get('stale_deleted', 0)}")
            print(f"  Failed: {results.get('failed', 0)}")
    
    asyncio.run(main())