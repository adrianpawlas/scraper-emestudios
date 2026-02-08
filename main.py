"""
Eme Studios scraper: scrape products, compute image/text embeddings, upsert to Supabase.
"""
import json
import sys
from typing import List, Optional

from config import SUPABASE_KEY, SUPABASE_URL
from scraper import run_scraper
from embeddings import image_embedding_from_url, text_embedding
from supabase_client import get_client, upsert_products


def _info_text_for_embedding(product: dict) -> str:
    """Build a single text from product fields for info_embedding. Truncate to ~2000 chars for model limits."""
    parts = [
        product.get("title") or "",
        product.get("description") or "",
        product.get("category") or "",
        product.get("gender") or "",
        product.get("price") or "",
        (product.get("sale") or "") if product.get("sale") else "",  # sale only if present
    ]
    meta = product.get("metadata")
    if isinstance(meta, dict):
        parts.append(json.dumps(meta, ensure_ascii=False))
    elif meta:
        parts.append(str(meta))
    text = " ".join(p for p in parts if p).strip() or (product.get("title") or " ")
    return text[:2000] if len(text) > 2000 else text


def main(headless: bool = True, skip_embeddings: bool = False, limit: Optional[int] = None) -> None:
    if limit:
        print(f"Collecting product URLs (limit={limit} products for testing)...")
    else:
        print("Collecting product URLs from category pages...")
    products = run_scraper(headless=headless, limit=limit)
    print(f"Scraped {len(products)} products.")

    if not products:
        print("No products to upload.")
        return

    image_embeddings: List[Optional[List[float]]] = []
    info_embeddings: List[Optional[List[float]]] = []

    if not skip_embeddings:
        print("Computing image and text embeddings...")
        for i, p in enumerate(products):
            img_url = p.get("image_url")
            if img_url:
                emb = image_embedding_from_url(img_url)
                image_embeddings.append(emb)
            else:
                image_embeddings.append(None)
            info_text = _info_text_for_embedding(p)
            try:
                info_embeddings.append(text_embedding(info_text))
            except Exception:
                info_embeddings.append(None)
            if (i + 1) % 10 == 0:
                print(f"  Embedded {i + 1}/{len(products)}")
    else:
        image_embeddings = [None] * len(products)
        info_embeddings = [None] * len(products)

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("SUPABASE_URL or SUPABASE_KEY not set. Skipping upload. Set in .env and run again.")
        return

    print("Upserting to Supabase...")
    client = get_client()
    upsert_products(client, products, image_embeddings, info_embeddings)
    print("Done.")


def _parse_limit() -> Optional[int]:
    for arg in sys.argv:
        if arg.startswith("--limit="):
            try:
                return int(arg.split("=", 1)[1])
            except ValueError:
                pass
    return None


if __name__ == "__main__":
    headless = "--no-headless" not in sys.argv
    skip_embeddings = "--skip-embeddings" in sys.argv
    limit = _parse_limit()
    main(headless=headless, skip_embeddings=skip_embeddings, limit=limit)
