import os
import sys
import json
import asyncio
import re
from typing import Optional
from dataclasses import dataclass, asdict
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from supabase import create_client

import torch
from transformers import SiglipModel, SiglipProcessor
from PIL import Image
from io import BytesIO


SUPABASE_URL = "https://yqawmzggcgpeyaaynrjk.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InlxYXdtemdnY2dwZXlhYXlucmprIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc1NTAxMDkyNiwiZXhwIjoyMDcwNTg2OTI2fQ.XtLpxausFriraFJeX27ZzsdQsFv3uQKXBBggoz6P4D4"

BASE_URL = "https://emestudios.com"
CATEGORIES = [
    "/be/en/all-products",
    "/be/en/woman", 
    "/be/en/accessories"
]

MODEL_NAME = "google/siglip-base-patch16-384"


@dataclass
class Product:
    id: str
    source: str
    product_url: str
    image_url: str
    brand: str
    title: str
    description: Optional[str]
    category: Optional[str]
    gender: Optional[str]
    price: Optional[str]
    sale: Optional[str]
    metadata: Optional[str]
    additional_images: Optional[str]
    second_hand: bool = False
    created_at: Optional[str] = None
    image_embedding: Optional[list] = None
    info_embedding: Optional[list] = None


class Embedder:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.processor = None
        self.client = None
        
    async def init(self):
        print(f"Loading {MODEL_NAME}...")
        cache = os.path.expanduser("~/.cache/huggingface/hub")
        
        self.model = SiglipModel.from_pretrained(MODEL_NAME, cache_dir=cache).to(self.device).eval()
        self.processor = SiglipProcessor.from_pretrained(MODEL_NAME, cache_dir=cache)
        self.client = httpx.AsyncClient(timeout=30.0)
        print(f"Loaded! Using {self.device}")
        
    async def close(self):
        if self.client:
            await self.client.aclose()
            
    def _to_list(self, outputs) -> list:
        if hasattr(outputs, 'pooler_output'):
            tensor = outputs.pooler_output
        elif hasattr(outputs, 'last_hidden_state'):
            tensor = outputs.last_hidden_state
        else:
            tensor = outputs[0] if isinstance(outputs, tuple) else outputs
            
        if hasattr(tensor, 'cpu'):
            arr = tensor.cpu().numpy()
        else:
            arr = tensor
            
        if arr.ndim > 1:
            return arr[0].tolist()
        return arr.tolist()
    
    async def get_image_embedding(self, url: str) -> Optional[list]:
        try:
            resp = await self.client.get(url)
            if resp.status_code == 200:
                img = Image.open(BytesIO(resp.content)).convert("RGB")
                inputs = self.processor(images=img, return_tensors="pt").to(self.device)
                with torch.no_grad():
                    out = self.model.get_image_features(**inputs)
                return self._to_list(out)
        except Exception as e:
            print(f"Image embed error: {e}")
        return None
    
    async def get_text_embedding(self, text: str) -> Optional[list]:
        try:
            inputs = self.processor(text=[text], return_tensors="pt", padding=True).to(self.device)
            with torch.no_grad():
                out = self.model.get_text_features(**inputs)
            return self._to_list(out)
        except Exception as e:
            print(f"Text embed error: {e}")
        return None


class EmeStudiosScraper:
    def __init__(self):
        self.browser = None
        self.page = None
        self.context = None
        self.supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        self.embedder = Embedder()
        self.CATEGORIES = CATEGORIES
        
    async def init_browser(self):
        print("Initializing browser...")
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            locale="en-US"
        )
        self.page = await self.context.new_page()
        self.page.set_default_timeout(60000)
        
    async def init(self):
        await self.init_browser()
        await self.embedder.init()
            
    async def close(self):
        if self.browser:
            await self.browser.close()
        await self.embedder.close()
        
    async def scroll_page(self, max_scrolls: int = 50) -> int:
        print("Scrolling to load products...")
        last_count = 0
        no_change = 0
        
        for i in range(max_scrolls):
            await self.page.evaluate("window.scrollBy(0, 1000)")
            await asyncio.sleep(1.5)
            
            count = await self.page.locator("a[href*='/product/']").count()
            
            if count > last_count:
                print(f"  Products loaded: {count}")
                last_count = count
                no_change = 0
            else:
                no_change += 1
                
            if no_change >= 5:
                print(f"No new products after {no_change} scrolls")
                break
                
        return last_count
    
    def parse_price(self, price_text: str, sale_text: Optional[str] = None) -> tuple[str, Optional[str]]:
        prices = []
        
        for text in [price_text, sale_text]:
            if text:
                match = re.search(r'([\d.,]+)\s*([A-Z]{3}|€|$|£|kr|zł|Kč)', text.upper())
                if match:
                    amount = match.group(1).replace(',', '.')
                    currency = match.group(2)
                    if currency == '€':
                        currency = 'EUR'
                    elif currency == '$':
                        currency = 'USD'
                    prices.append(f"{amount}{currency}")
                else:
                    nums = re.findall(r'[\d.]+', text)
                    if nums:
                        prices.append(f"{nums[0]}EUR")
        
        price_str = prices[0] if prices else None
        sale_str = prices[1] if len(prices) > 1 else None
        
        return price_str, sale_str
    
    async def parse_product(self, html: str, url: str) -> Product:
        soup = BeautifulSoup(html, "html.parser")
        
        product_id = ""
        match = re.search(r'/product/([^/?]+)', url)
        if match:
            product_id = match.group(1)
        
        title = ""
        description = ""
        image_url = ""
        additional_images = []
        price_text = ""
        sale_text = ""
        category = ""
        gender = "woman"
        
        scripts = soup.find_all("script", {"type": "application/ld+json"})
        for script in scripts:
            try:
                data = json.loads(script.string or script.get_text())
                if data.get("@type") == "Product" or data.get("@type") == "IndividualProduct":
                    title = data.get("name", "")
                    description = data.get("description", "")[:500] if data.get("description") else ""
                    
                    offers = data.get("offers", {})
                    if isinstance(offers, dict):
                        price = offers.get("price") or offers.get("lowPrice")
                        if price:
                            currency = offers.get("priceCurrency", "EUR")
                            price_text = f"{price}{currency}"
                        
                        high_price = offers.get("highPrice")
                        if high_price and high_price != price:
                            sale_text = f"{high_price}{currency}"
                    
                    images = data.get("image") or []
                    if images:
                        if isinstance(images, list):
                            image_url = str(images[0])
                            additional_images = [str(img) for img in images[1:6]]
                        else:
                            image_url = str(images)
                            
                    break
            except:
                continue
        
        if not title:
            h1 = soup.find("h1")
            if h1:
                title = h1.get_text(strip=True)
        
        if not title:
            og_title = soup.find("meta", {"property": "og:title"})
            if og_title:
                title = og_title.get("content", "")
        
        if not image_url:
            og_image = soup.find("meta", {"property": "og:image"})
            if og_image:
                image_url = og_image.get("content", "")
        
        if not description:
            meta_desc = soup.find("meta", {"name": "description"})
            if meta_desc:
                description = meta_desc.get("content", "")[:500]
        
        price_patterns = [
            (r'€\s*(\d+)', 'EUR'),
            (r'\$\s*(\d+)', 'USD'),
            (r'£\s*(\d+)', 'GBP'),
            (r'(\d+)\s*kr', 'SEK'),
            (r'(\d+)\s*zł', 'PLN'),
            (r'(\d+)\s*Kč', 'CZK'),
        ]
        
        if not price_text:
            for pat, curr in price_patterns:
                match = re.search(pat, html)
                if match:
                    price_text = f"{match.group(1)}{curr}"
                    break
        
        if not price_text:
            price_elem = soup.find("span", {"class": re.compile(r"price", re.I)})
            if price_elem:
                price_text = price_elem.get_text(strip=True)
        
        url_lower = url.lower()
        if "/woman" in url_lower or "woman" in category.lower():
            gender = "woman"
        elif "/man" in url_lower or "man" in category.lower():
            gender = "man"
        elif "woman" not in html.lower() and "/woman" not in url_lower:
            gender = "woman"
        
        category_links = soup.find_all("a", {"class": re.compile(r"breadcrumb|category", re.I)})
        if category_links:
            cats = [c.get_text(strip=True) for c in category_links if c.get_text(strip=True)]
            category = ", ".join(cats[:3])
        
        price_val, sale_val = self.parse_price(price_text, sale_text)
        
        metadata = {
            "url": url,
            "gender": gender,
            "scraped_at": datetime.utcnow().isoformat()
        }
        
        metadata_str = json.dumps(metadata)
        
        additional_str = " , ".join(additional_images) if additional_images else ""
        
        return Product(
            id=f"scraper-emestudios-{product_id}",
            source="scraper-emestudios",
            product_url=url,
            image_url=image_url,
            brand="Eme Studios",
            title=title,
            description=description[:1000] if description else None,
            category=category,
            gender=gender,
            price=price_val,
            sale=sale_val,
            metadata=metadata_str,
            additional_images=additional_str,
            second_hand=False,
            created_at=datetime.utcnow().isoformat()
        )
    
    async def scrape_category(self, category_path: str, limit: int = 0) -> list[Product]:
        """Scrape a category. If limit > 0, only scrape that many products."""
        url = BASE_URL + category_path if category_path.startswith("/") else category_path
        print(f"\n{'='*50}")
        print(f"Scraping: {url}")
        print(f"{'='*50}")
        
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"Error loading page: {e}")
            return []
        
        await asyncio.sleep(3)
        
        await self.scroll_page(max_scrolls=60)
        
        links = await self.page.locator("a[href*='/product/']").evaluate_all(
            "els => [...new Set(els.map(el => el.href))]"
        )
        
        if limit > 0:
            links = links[:limit]
        
        print(f"Found {len(links)} product links")
        
        products = []
        
        for i, link in enumerate(links):
            if not link:
                continue
                
            print(f"[{i+1}/{len(links)}] {link}")
            
            try:
                await self.page.goto(link, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)
                
                html = await self.page.content()
                product = await self.parse_product(html, link)
                
                if product.image_url:
                    product.image_embedding = await self.embedder.get_image_embedding(product.image_url)
                    
                    text_info = f"{product.title} {product.brand} {product.description or ''} {product.category or ''} {product.gender or ''} {product.price or ''}"
                    product.info_embedding = await self.embedder.get_text_embedding(text_info)
                
                products.append(product)
                
            except Exception as e:
                print(f"  Error: {e}")
                continue
                
            await asyncio.sleep(0.3)
        
        return products
    
    async def save_products(self, products: list[Product]):
        print(f"\nSaving {len(products)} products to Supabase...")
        
        for product in products:
            data = asdict(product)
            
            # Convert embeddings to proper format for Supabase
            if product.image_embedding:
                data['image_embedding'] = product.image_embedding
            if product.info_embedding:
                data['info_embedding'] = product.info_embedding
            
            try:
                result = self.supabase.table("products").upsert(
                    data,
                    on_conflict="id"
                ).execute()
                
                if result.data:
                    print(f"  Saved: {product.title[:40]}")
                else:
                    print(f"  Error saving: {product.title[:40]}")
                    
            except Exception as e:
                print(f"  Database error: {e}")
                
            await asyncio.sleep(0.1)
    
    async def run(self, test_mode=False, max_products=None, limit_per_category=0):
        """Run the scraper.
        
        Args:
            test_mode: If True, only scrape 3 products
            max_products: Maximum total products to scrape
            limit_per_category: Limit products per category (for testing)
        """
        await self.init()
        
        all_products = []
        
        for category in self.CATEGORIES:
            if test_mode:
                products = await self.scrape_category(category, limit=3)
            elif limit_per_category > 0:
                products = await self.scrape_category(category, limit=limit_per_category)
            else:
                products = await self.scrape_category(category)
            
            all_products.extend(products)
            print(f"Category {category}: {len(products)} products")
            
            if max_products and len(all_products) >= max_products:
                break
        
        if all_products:
            await self.save_products(all_products)
        
        print(f"\n{'='*50}")
        print(f"COMPLETE! Total products scraped: {len(all_products)}")
        print(f"{'='*50}")
        
        await self.close()
    
    async def scrape_single_product(self, url: str):
        """Scrape a single product URL."""
        await self.init()
        
        print(f"Single product: {url}")
        await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2)
        
        html = await self.page.content()
        product = await self.parse_product(html, url)
        
        if product.image_url:
            product.image_embedding = await self.embedder.get_image_embedding(product.image_url)
            text_info = f"{product.title} {product.brand} {product.description or ''} {product.category or ''} {product.gender or ''} {product.price or ''}"
            product.info_embedding = await self.embedder.get_text_embedding(text_info)
        
        await self.save_products([product])
        print(f"Saved: {product.title}")
        
        await self.close()


async def main():
    scraper = EmeStudiosScraper()
    await scraper.run()


if __name__ == "__main__":
    asyncio.run(main())