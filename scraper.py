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

    async def scroll_page(self, page, max_scrolls: int = 100):
        last_count = 0
        no_new_count = 0
        
        await page.wait_for_timeout(3000)

        for i in range(max_scrolls):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1.5)
            
            for _ in range(2):
                await page.evaluate("window.scrollBy(0, -200)")
                await asyncio.sleep(0.3)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(0.5)

            try:
                await page.evaluate("""() => {
                    document.querySelectorAll('button, a, [role="button"]').forEach(el => {
                        const text = (el.textContent || '').toLowerCase();
                        if (text.includes('load') && text.includes('more')) {
                            el.click();
                        }
                    });
                }""")
                await asyncio.sleep(0.5)
            except:
                pass

            current_count = await page.locator('a[href*="/product/"]').count()

            if current_count > last_count:
                print(f"    Products loaded: {current_count}")
                last_count = current_count
                no_new_count = 0
            else:
                no_new_count += 1
                if no_new_count >= 15:
                    print(f"    No new products after {no_new_count} scrolls. Stopping.")
                    break

        handles = await page.evaluate("""() => {
            const seen = new Set();
            const results = [];
            document.querySelectorAll('a[href*="/product/"]').forEach(a => {
                const href = a.getAttribute('href');
                if (href && href.includes('/product/')) {
                    const handle = href.split('/product/')[1].split('?')[0].split('#')[0];
                    if (handle && !seen.has(handle)) {
                        seen.add(handle);
                        results.push(handle);
                    }
                }
            });
            return results;
        }""")
        
        return handles

    async def dismiss_overlay(self, page):
        try:
            btn = page.locator("button").filter(has_text="CONTINUE IN").first
            await btn.click(timeout=5000)
            await page.wait_for_timeout(2000)
        except:
            pass

    async def _create_context(self, browser):
        return await browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}
        )

    async def scrape_collection_page(self, url: str) -> list[str]:
        product_urls = []
        
        from urllib.parse import urlparse
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        
        locale_path = "/" + "/".join(parsed.path.strip("/").split("/")[:2]) + "/"
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await self._create_context(browser)
            page = await context.new_page()

            try:
                await page.goto(url, timeout=60000)
                await page.wait_for_timeout(5000)

                await self.dismiss_overlay(page)
                
                handles = await self.scroll_page(page)
                
                for handle in handles:
                    full_url = f"{base}{locale_path}product/{handle}"
                    product_urls.append(full_url)

                await context.close()
                await browser.close()
            except Exception as e:
                print(f"Error scraping {url}: {e}")
                await context.close()
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

        # --- Structured data & meta extraction (no page.evaluate) ---
        try:
            html = await page.content()
            soup = BeautifulSoup(html, "html.parser")

            # OG and meta tags (server-rendered, always available)
            if not info.get("image_url"):
                og_image = soup.find("meta", {"property": "og:image"})
                if og_image:
                    info["image_url"] = og_image.get("content", "")

            if not info.get("title"):
                og_title = soup.find("meta", {"property": "og:title"})
                if og_title:
                    info["title"] = og_title.get("content", "")

            if not info.get("description"):
                meta_desc = soup.find("meta", {"name": "description"})
                if meta_desc:
                    info["description"] = meta_desc.get("content", "")

            # Try JSON-LD
            scripts = soup.find_all("script", {"type": "application/ld+json"})
            for script in scripts:
                try:
                    data = json.loads(script.string or script.get_text())
                    if data.get("@type") == "Product":
                        info["title"] = data.get("name", info["title"])
                        info["description"] = data.get("description", info["description"])
                        
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

            url_lower = url.lower()
            if "/woman" in url_lower:
                info["gender"] = "woman"
            elif "/man" in url_lower:
                info["gender"] = "man"
            else:
                info["gender"] = "woman"

        except Exception as e:
            print(f"Error parsing page HTML: {e}")

        # --- Gallery extraction via page.evaluate (can fail if page context is lost) ---
        try:
            # Get first/main product image from gallery or OG meta
            if not info.get("image_url"):
                img_result = await page.evaluate("""() => {
                    const og = document.querySelector('meta[property="og:image"]');
                    if (og) return og.getAttribute('content') || og.content;
                    return null;
                }""")
                if img_result:
                    info["image_url"] = img_result

            # Get additional product images from gallery
            additional_imgs = await page.evaluate("""() => {
                const results = [];
                document.querySelectorAll('img').forEach(img => {
                    const src = img.src || img.dataset?.src || img.dataset?.lazySrc;
                    if (src && src.includes('shopify') && !src.includes('logo') && !src.includes('brand')) {
                        results.push(src);
                    }
                });
                return [...new Set(results)].slice(0, 6);
            }""")
            if additional_imgs and not info.get("image_url"):
                info["image_url"] = additional_imgs[0]
                if len(additional_imgs) > 1:
                    info["additional_images"] = additional_imgs[1:]
            elif additional_imgs and len(additional_imgs) > 1 and not info.get("additional_images"):
                info["additional_images"] = [img for img in additional_imgs if img != info.get("image_url")][:5]

        except Exception as e:
            print(f"Error extracting gallery images: {e}")

        info["metadata"]["url"] = url
        info["metadata"]["gender"] = info["gender"]
        info["metadata"]["scraped_at"] = time.time()

        return info

    async def scrape_product(self, url: str) -> dict:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await self._create_context(browser)
            page = await context.new_page()

            try:
                await page.goto(url, timeout=60000, wait_until="domcontentloaded")
                await page.wait_for_timeout(2000)

                await self.dismiss_overlay(page)

                product_info = await self.extract_product_info(page, url)

                print(f"  Getting text embedding for: {product_info.get('title', 'unknown')[:30]}")
                text_info = f"{product_info.get('title', '')} {product_info.get('brand', '')} {product_info.get('description', '') or ''} {product_info.get('category', '') or ''} {product_info.get('gender', '') or ''} {product_info.get('price', '') or ''}"
                product_info["info_embedding"] = self.embedding_service.get_text_embedding(text_info)

                if product_info.get("image_url"):
                    print(f"  Getting image embedding for: {product_info.get('title', 'unknown')[:30]}")
                    product_info["image_embedding"] = self.embedding_service.get_image_embedding(product_info["image_url"])

                await context.close()
                await browser.close()
                return product_info

            except Exception as e:
                print(f"Error scraping product {url}: {e}")
                await context.close()
                await browser.close()
                return None

    async def run(self, test_mode: bool = False, test_count: int = 3) -> list[dict]:
        all_products = []
        
        for category_url in CATEGORY_URLS:
            print(f"\nScraping category: {category_url}")
            
            try:
                product_urls = await self.scrape_collection_page(category_url)
                print(f"  Found {len(product_urls)} products")
                
                if test_mode:
                    product_urls = product_urls[:test_count]
                    print(f"  [TEST] Limiting to {test_count} products")
                
                for i, url in enumerate(product_urls):
                    print(f"  [{i+1}/{len(product_urls)}] {url}")
                    product = await self.scrape_product(url)
                    if product:
                        all_products.append(product)
                    
                    await asyncio.sleep(0.5)
                    
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