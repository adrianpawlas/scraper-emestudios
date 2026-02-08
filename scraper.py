"""Eme Studios category and product scraping with Playwright."""
import re
import time
from typing import List, Optional, Tuple
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright, Page, Browser

from config import (
    BASE_URL,
    CATEGORY_URLS,
    EMBED_IMAGE_URL_PATTERN,
    SCROLL_PAUSE_SEC,
    MAX_SCROLL_ATTEMPTS,
)


def _normalize_product_url(href: str) -> str:
    """Ensure product URL is absolute and in en-at locale if possible."""
    if not href or href.startswith("#") or "javascript:" in href:
        return ""
    url = urljoin(BASE_URL, href)
    # Prefer en-at for consistency
    if "/en-at/" not in url and "/en-" in url:
        url = url.replace("/en-us/", "/en-at/").replace("/en-gb/", "/en-at/")
    if "/products/" not in url:
        return ""
    return url.split("?")[0]


def _is_embed_image_url(url: str) -> bool:
    """True if this image should be used for image_url and image_embedding."""
    if not url:
        return False
    # Match /cdn/shop/files/YYYY_MM_DDEME*.webp
    return bool(re.search(EMBED_IMAGE_URL_PATTERN, url))


def collect_product_urls_from_category(page: Page, category_url: str) -> List[str]:
    """Open category page, handle infinite scroll, return list of product URLs."""
    seen: set[str] = set()
    page.goto(category_url, wait_until="domcontentloaded", timeout=60000)
    time.sleep(2)

    for attempt in range(MAX_SCROLL_ATTEMPTS):
        # Collect links from product cards
        links = page.evaluate("""() => {
            const anchors = document.querySelectorAll('a[href*="/products/"]');
            return Array.from(anchors).map(a => a.href).filter(h => h);
        }""")
        for raw in links:
            url = _normalize_product_url(raw)
            if url:
                seen.add(url)

        # Scroll to bottom to trigger lazy load
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(SCROLL_PAUSE_SEC)

        # Check if new content appeared
        after_links = page.evaluate("""() => {
            const anchors = document.querySelectorAll('a[href*="/products/"]');
            return Array.from(anchors).map(a => a.href).filter(h => h).length;
        }""")
        prev_count = len(seen)
        if after_links and after_links <= prev_count:
            # One more scroll and short wait
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
            links2 = page.evaluate("""() => {
                const anchors = document.querySelectorAll('a[href*="/products/"]');
                return Array.from(anchors).map(a => a.href).filter(h => h);
            }""")
            for raw in links2:
                url = _normalize_product_url(raw)
                if url:
                    seen.add(url)
            if len(seen) <= prev_count:
                break
        if attempt >= 2 and len(seen) == prev_count:
            break

    return list(seen)


def scrape_product_page(page: Page, product_url: str) -> Optional[dict]:
    """Scrape one product page. Returns dict with keys matching DB + raw image list."""
    page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(1)

    data = page.evaluate("""(baseUrl) => {
        const out = { title: null, description: null, category: null, gender: null, price: null, sale: null, imageUrls: [], categories: [], metadata: {} };

        // Title - common selectors
        const titleEl = document.querySelector('h1') || document.querySelector('[class*="product"][class*="title"]') || document.querySelector('meta[property="og:title"]');
        if (titleEl) {
            out.title = titleEl.getAttribute('content') || titleEl.textContent?.trim() || null;
        }

        // Meta description
        const descMeta = document.querySelector('meta[property="og:description"], meta[name="description"]');
        if (descMeta) out.description = descMeta.getAttribute('content')?.trim() || null;

        // All image URLs from img src and srcset, and links to product images
        const imgs = document.querySelectorAll('img[src*="cdn/shop"], img[src*="emestudios"], source[srcset*="cdn/shop"]');
        const urlSet = new Set();
        imgs.forEach(img => {
            const u = img.getAttribute('src') || img.getAttribute('srcset');
            if (u) {
                u.split(/[,\\s]+/).forEach(part => {
                    const url = part.trim().split(' ')[0];
                    if (url && (url.includes('cdn/shop') || url.includes('emestudios'))) {
                        let full = url.startsWith('http') ? url : (baseUrl + (url.startsWith('/') ? url : '/' + url));
                        full = full.split('?')[0];
                        if (full.includes('/files/') || full.includes('/products/')) urlSet.add(full);
                    }
                });
            }
        });
        // Also data attributes and links
        document.querySelectorAll('[data-src*="cdn/shop"], [href*="cdn/shop/files"]').forEach(el => {
            const u = el.getAttribute('data-src') || el.getAttribute('href');
            if (u) {
                let full = u.startsWith('http') ? u : (baseUrl + (u.startsWith('/') ? u : '/' + u));
                full = full.split('?')[0];
                if (full.includes('/files/')) urlSet.add(full);
            }
        });
        out.imageUrls = Array.from(urlSet);

        // Price - look for price elements
        const priceEl = document.querySelector('[class*="price"]') || document.querySelector('meta[property="product:price:amount"]');
        if (priceEl) {
            const content = priceEl.getAttribute('content') || priceEl.textContent?.trim() || '';
            const match = content.replace(/[^\\d.,]/g, '').match(/[\\d.,]+/);
            if (match) out.metadata.priceRaw = content.trim();
        }
        document.querySelectorAll('[class*="price"]').forEach(el => {
            const t = el.textContent?.trim();
            if (t && /\\$|€|USD|EUR|CZK|PLN|\\d+[.,]\\d+/.test(t)) out.metadata.priceRaw = (out.metadata.priceRaw || '') + ' ' + t;
        });

        // Try Shopify product JSON from script tag
        const scripts = document.querySelectorAll('script[type="application/json"], script[type="application/ld+json"]');
        for (const script of scripts) {
            try {
                const json = JSON.parse(script.textContent || '{}');
                if (json instanceof Array) {
                    const productSchema = json.find(x => x['@type'] === 'Product');
                    if (productSchema) {
                        out.title = out.title || productSchema.name;
                        out.description = out.description || productSchema.description;
                        if (productSchema.offers) {
                            const offer = Array.isArray(productSchema.offers) ? productSchema.offers[0] : productSchema.offers;
                            out.price = offer.price || out.metadata.priceRaw;
                            out.metadata.priceCurrency = offer.priceCurrency;
                        }
                        if (productSchema.image) {
                            const imgs = Array.isArray(productSchema.image) ? productSchema.image : [productSchema.image];
                            imgs.forEach(i => {
                                const u = typeof i === 'string' ? i : i.url;
                                if (u) urlSet.add(u.split('?')[0]);
                            });
                        }
                    }
                } else if (json['@type'] === 'Product') {
                    out.title = out.title || json.name;
                    out.description = out.description || json.description;
                    if (json.image) {
                        const imgs = Array.isArray(json.image) ? json.image : [json.image];
                        imgs.forEach(i => { const u = typeof i === 'string' ? i : i.url; if (u) urlSet.add(u.split('?')[0]); });
                    }
                } else if (json.product || json.products) {
                    const p = json.product || (json.products && json.products[0]);
                    if (p) {
                        out.title = out.title || p.title;
                        out.description = out.description || p.description;
                        if (p.variants && p.variants[0]) {
                            const v = p.variants[0];
                            out.price = (v.price || v.price_range?.min) ? String(v.price || v.price_range.min) : out.price;
                            out.metadata.priceCurrency = v.price ? (v.price_currency || 'USD') : out.metadata.price_currency;
                        }
                        if (p.images && p.images.length) {
                            p.images.forEach(img => {
                                const u = typeof img === 'string' ? img : (img.src || img.url);
                                if (u) urlSet.add(u.split('?')[0]);
                            });
                        }
                        if (p.media && p.media.length) {
                            p.media.forEach(m => {
                                if (m.src || m.preview_image?.src) urlSet.add((m.src || m.preview_image.src).split('?')[0]);
                            });
                        }
                        if (p.type) out.category = p.type;
                        if (p.tags) out.metadata.tags = Array.isArray(p.tags) ? p.tags.join(', ') : p.tags;
                    }
                }
            } catch (e) {}
        }
        out.imageUrls = Array.from(urlSet);

        // Category from breadcrumb or meta
        const breadcrumb = document.querySelector('[class*="breadcrumb"] a, nav a[href*="collections"]');
        if (breadcrumb) out.metadata.breadcrumb = breadcrumb.textContent?.trim();
        const catEl = document.querySelector('[class*="category"], .product-type, [class*="product-type"]');
        if (catEl) out.category = out.category || catEl.textContent?.trim();

        return out;
    }""", BASE_URL)

    if not data or not data.get("title"):
        # Retry with simpler title extraction
        title = page.locator("h1").first.text_content()
        if title:
            data = data or {}
            data["title"] = title.strip()

    if not data or not data.get("title"):
        return None

    # Ensure we have at least one image (use og:image if nothing else)
    if not data.get("imageUrls"):
        og_image = page.locator('meta[property="og:image"]').get_attribute("content")
        if og_image:
            data["imageUrls"] = [og_image.split("?")[0]]

    # Split category string by & or comma for "Sweaters & Hoodies" -> "Sweaters, Hoodies"
    category = (data.get("category") or data.get("metadata", {}).get("breadcrumb") or "").strip()
    if category and "&" in category:
        category = ", ".join(s.strip() for s in category.split("&"))
    data["category"] = category or None

    # Price string: build "20.90USD,450CZK" from metadata/price
    price_str = _build_price_string(data)
    data["price"] = price_str
    data["sale"] = data.get("sale") or price_str  # Same as price if on sale; we don't detect sale separately here

    # Gender: infer from category or leave null (unisex)
    data["gender"] = _infer_gender(data)

    return data


def _build_price_string(data: dict) -> str:
    """Build price string like '20.90USD,450CZK' from page data."""
    parts = []
    meta = data.get("metadata") or {}
    price_raw = (data.get("price") or meta.get("priceRaw") or "").strip()
    currency = (meta.get("priceCurrency") or "USD").upper()
    if price_raw:
        num = re.sub(r"[^\d.,]", "", price_raw)
        num = num.replace(",", ".")
        if re.match(r"^\d+\.?\d*$", num):
            parts.append(f"{num}{currency}")
    if not parts and price_raw:
        # Fallback: e.g. "$65" -> 65USD
        m = re.search(r"([\d.,]+)\s*(\$|€|USD|EUR|CZK|PLN)?", price_raw)
        if m:
            amount = m.group(1).replace(",", ".")
            curr = (m.group(2) or "USD").replace("$", "USD").replace("€", "EUR")
            parts.append(f"{amount}{curr}")
    return ",".join(parts) if parts else ""


def _infer_gender(data: dict) -> Optional[str]:
    """Infer 'man', 'woman', or null from category/tags."""
    cat = (data.get("category") or "").lower()
    tags = (data.get("metadata") or {}).get("tags") or ""
    combined = (cat + " " + tags).lower()
    if any(w in combined for w in ["men", "man", "male"]):
        return "man"
    if any(w in combined for w in ["women", "woman", "female"]):
        return "woman"
    return None


def split_embed_and_extra_images(image_urls: List[str]) -> Tuple[Optional[str], List[str]]:
    """Return (embed_image_url, additional_images_list). Embed is the first URL matching EMBED pattern."""
    embed_url: Optional[str] = None
    additional: List[str] = []
    for url in image_urls:
        url = (url or "").strip()
        if not url:
            continue
        if _is_embed_image_url(url):
            if embed_url is None:
                embed_url = url
            else:
                additional.append(url)
        else:
            additional.append(url)
    if embed_url is None and additional:
        embed_url = additional.pop(0)
    return embed_url, additional


def collect_all_product_urls(browser: Browser) -> List[str]:
    """Collect product URLs from all category pages."""
    page = browser.new_page()
    seen: set[str] = set()
    try:
        for cat_url in CATEGORY_URLS:
            urls = collect_product_urls_from_category(page, cat_url)
            for u in urls:
                seen.add(u)
    finally:
        page.close()
    return list(seen)


def run_scraper(headless: bool = True) -> List[dict]:
    """Run full scrape: collect all product URLs, then scrape each product. Returns list of product dicts."""
    all_urls = []
    products = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            all_urls = collect_all_product_urls(browser)
        finally:
            browser.close()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            page = browser.new_page()
            for i, product_url in enumerate(all_urls):
                try:
                    row = scrape_product_page(page, product_url)
                    if row:
                        row["product_url"] = product_url
                        embed_url, extra = split_embed_and_extra_images(row.get("imageUrls") or [])
                        row["image_url"] = embed_url or ""
                        row["additional_images"] = " , ".join(extra) if extra else ""
                        row.pop("imageUrls", None)
                        products.append(row)
                except Exception:
                    continue
            page.close()
        finally:
            browser.close()

    return products
