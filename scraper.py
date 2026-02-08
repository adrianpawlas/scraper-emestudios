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


def _normalize_image_url(url: str) -> Optional[str]:
    """Normalize image URL to avoid double domain (emestudios.com//emestudios.com/...)."""
    if not url or not isinstance(url, str):
        return None
    url = url.strip().split("?")[0]
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return BASE_URL.rstrip("/") + url
    if "cdn/shop/files/" in url:
        idx = url.index("cdn/shop/files/")
        return BASE_URL.rstrip("/") + "/" + url[idx:]
    if "emestudios.com" in url:
        idx = url.index("emestudios.com") + 14
        path = url[idx:].lstrip("/") or ""
        return BASE_URL.rstrip("/") + "/" + path
    return BASE_URL.rstrip("/") + "/" + url.lstrip("/")


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


def collect_product_urls_from_category(
    page: Page, category_url: str, max_urls: Optional[int] = None
) -> List[str]:
    """Open category page, handle infinite scroll, return list of product URLs.
    If max_urls is set, stop once we have at least that many (faster for testing)."""
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
        if max_urls is not None and len(seen) >= max_urls:
            return list(seen)[:max_urls]

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
        const out = { title: null, description: null, category: null, gender: null, price: null, sale: null, compareAtPrice: null, imageUrls: [], categories: [], metadata: {} };

        // Normalize image URL - avoid double domain (emestudios.com//emestudios.com/...)
        function normalizeImageUrl(u) {
            if (!u) return null;
            u = String(u).trim().split('?')[0];
            if (u.startsWith('http://') || u.startsWith('https://')) return u;
            if (u.startsWith('//')) return 'https:' + u;
            if (u.startsWith('/')) return baseUrl.replace(/\\/$/, '') + u;
            if (u.includes('cdn/shop/files/')) {
                const idx = u.indexOf('cdn/shop/files/');
                return baseUrl.replace(/\\/$/, '') + '/' + u.substring(idx);
            }
            if (u.includes('emestudios.com')) {
                const i = u.indexOf('emestudios.com') + 14;
                const path = u.substring(i).replace(/^\\/+/, '/') || '/';
                return baseUrl.replace(/\\/$/, '') + path;
            }
            return baseUrl.replace(/\\/$/, '') + '/' + u.replace(/^\\/+/, '');
        }

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
                        const full = normalizeImageUrl(url);
                        if (full && (full.includes('/files/') || full.includes('/products/'))) urlSet.add(full);
                    }
                });
            }
        });
        // Also data attributes and links
        document.querySelectorAll('[data-src*="cdn/shop"], [href*="cdn/shop/files"]').forEach(el => {
            const u = el.getAttribute('data-src') || el.getAttribute('href');
            if (u) {
                const full = normalizeImageUrl(u);
                if (full && full.includes('/files/')) urlSet.add(full);
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
                                const full = normalizeImageUrl(u);
                                if (full) urlSet.add(full);
                            });
                        }
                    }
                } else if (json['@type'] === 'Product') {
                    out.title = out.title || json.name;
                    out.description = out.description || json.description;
                    if (json.image) {
                        const imgs = Array.isArray(json.image) ? json.image : [json.image];
                        imgs.forEach(i => { const u = typeof i === 'string' ? i : i.url; const full = normalizeImageUrl(u); if (full) urlSet.add(full); });
                    }
                } else if (json.product || json.products) {
                    const p = json.product || (json.products && json.products[0]);
                    if (p) {
                        out.title = out.title || p.title;
                        out.description = out.description || p.description;
                        if (p.variants && p.variants[0]) {
                            const v = p.variants[0];
                            out.price = (v.price || v.price_range?.min) ? String(v.price || v.price_range.min) : out.price;
                            out.compareAtPrice = (v.compare_at_price != null && v.compare_at_price !== '') ? String(v.compare_at_price) : null;
                            out.metadata.priceCurrency = v.price ? (v.price_currency || 'USD') : out.metadata.price_currency;
                        }
                        if (p.images && p.images.length) {
                            p.images.forEach(img => {
                                const u = typeof img === 'string' ? img : (img.src || img.url);
                                const full = normalizeImageUrl(u);
                                if (full) urlSet.add(full);
                            });
                        }
                        if (p.media && p.media.length) {
                            p.media.forEach(m => {
                                const u = m.src || (m.preview_image && m.preview_image.src);
                                const full = normalizeImageUrl(u);
                                if (full) urlSet.add(full);
                            });
                        }
                        if (p.type) out.category = p.type;
                        if (p.tags) out.metadata.tags = Array.isArray(p.tags) ? p.tags.join(', ') : p.tags;
                        if (p.vendor) out.metadata.vendor = p.vendor;
                        if (p.handle) out.metadata.handle = p.handle;
                        if (p.collections && p.collections.length) out.metadata.collections = p.collections.map(c => c.title || c.handle || '').join(', ');
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
            data["imageUrls"] = [_normalize_image_url(og_image)]

    # Normalize all image URLs in Python (in case any slipped through)
    urls = data.get("imageUrls") or []
    data["imageUrls"] = [_normalize_image_url(u) for u in urls if _normalize_image_url(u)]

    # Split category string by & or comma for "Sweaters & Hoodies" -> "Sweaters, Hoodies"
    category = (data.get("category") or data.get("metadata", {}).get("breadcrumb") or "").strip()
    if category and "&" in category:
        category = ", ".join(s.strip() for s in category.split("&"))
    data["category"] = category or None

    # Price and sale: build from metadata/price; sale only when compare_at_price > price
    price_str, sale_str = _build_price_and_sale(data)
    data["price"] = price_str
    data["sale"] = sale_str  # None if no sale; sale price only when compare_at_price > price

    # Gender: infer from category, tags, handle, collections
    data["gender"] = _infer_gender(data)

    return data


def _normalize_amount(amount_str: str) -> Optional[float]:
    """Parse amount; if Shopify cents (large int, no decimal), divide by 100."""
    if not amount_str:
        return None
    num = re.sub(r"[^\d.,]", "", amount_str).replace(",", ".")
    if not re.match(r"^\d+\.?\d*$", num):
        return None
    val = float(num)
    # Shopify stores price in cents: 8900 = $89.00; treat as cents if >= 100 and no decimal
    if val >= 100 and "." not in num and val == int(val):
        val = val / 100.0
    return val


def _build_price_and_sale(data: dict) -> Tuple[str, Optional[str]]:
    """Build (price_str, sale_str). Sale is only set when compare_at_price > price."""
    meta = data.get("metadata") or {}
    currency = (meta.get("priceCurrency") or "USD").upper()
    price_raw = (data.get("price") or meta.get("priceRaw") or "").strip()
    compare_raw = (data.get("compareAtPrice") or "").strip()

    price_val = _normalize_amount(price_raw)
    compare_val = _normalize_amount(compare_raw) if compare_raw else None

    if price_val is None and price_raw:
        m = re.search(r"([\d.,]+)\s*(\$|€|USD|EUR|CZK|PLN)?", price_raw)
        if m:
            price_val = _normalize_amount(m.group(1))
            if m.group(2):
                currency = (m.group(2) or "USD").replace("$", "USD").replace("€", "EUR").upper()

    if price_val is None:
        return ("", None)

    # Sale only when compare_at_price exists and is greater than price
    if compare_val is not None and compare_val > price_val:
        price_str = f"{compare_val:.2f}".rstrip("0").rstrip(".") + currency
        sale_str = f"{price_val:.2f}".rstrip("0").rstrip(".") + currency
        return (price_str, sale_str)

    price_str = f"{price_val:.2f}".rstrip("0").rstrip(".") + currency
    return (price_str, None)


def _infer_gender(data: dict) -> Optional[str]:
    """Infer 'man', 'woman', or null from category, tags, handle, collections."""
    meta = data.get("metadata") or {}
    cat = (data.get("category") or "").lower()
    tags = (meta.get("tags") or "").lower()
    handle = (meta.get("handle") or "").lower()
    collections = (meta.get("collections") or "").lower()
    vendor = (meta.get("vendor") or "").lower()
    combined = " ".join([cat, tags, handle, collections, vendor])

    if any(w in combined for w in ["men", "man", "male", "mens", "men's"]):
        return "man"
    if any(w in combined for w in ["women", "woman", "female", "womens", "women's", "ladies"]):
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


def collect_all_product_urls(browser: Browser, max_urls: Optional[int] = None) -> List[str]:
    """Collect product URLs from all category pages. If max_urls set, stop when we have enough."""
    page = browser.new_page()
    seen: set[str] = set()
    try:
        for cat_url in CATEGORY_URLS:
            urls = collect_product_urls_from_category(page, cat_url, max_urls=max_urls)
            for u in urls:
                seen.add(u)
            if max_urls is not None and len(seen) >= max_urls:
                break
    finally:
        page.close()
    result = list(seen)
    if max_urls is not None:
        result = result[:max_urls]
    return result


def run_scraper(headless: bool = True, limit: Optional[int] = None) -> List[dict]:
    """Run full scrape: collect all product URLs, then scrape each product. Returns list of product dicts.
    If limit is set, only the first `limit` product URLs are scraped (faster for testing)."""
    all_urls = []
    products = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            all_urls = collect_all_product_urls(browser, max_urls=limit)
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
