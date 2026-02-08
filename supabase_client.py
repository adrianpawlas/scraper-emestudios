"""Supabase products table insert/upsert."""
import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase import create_client, Client

from config import BRAND, SOURCE, SUPABASE_KEY, SUPABASE_URL


def _product_id(product_url: str) -> str:
    return hashlib.sha256(f"{SOURCE}:{product_url}".encode()).hexdigest()


def _row_from_product(
    product: Dict[str, Any],
    image_embedding: Optional[List[float]],
    info_embedding: Optional[List[float]],
) -> Dict[str, Any]:
    """Build DB row for products table."""
    product_url = product.get("product_url") or ""
    row: Dict[str, Any] = {
        "id": _product_id(product_url),
        "source": SOURCE,
        "product_url": product_url,
        "image_url": product.get("image_url") or "",
        "brand": BRAND,
        "title": product.get("title") or "",
        "description": (product.get("description") or "").strip() or None,
        "category": product.get("category") or None,
        "gender": product.get("gender"),
        "price": product.get("price") or None,
        "sale": product.get("sale") or None,
        "second_hand": False,
        "country": None,
        "metadata": _metadata_string(product),
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "additional_images": product.get("additional_images") or None,
    }
    if image_embedding is not None:
        row["image_embedding"] = image_embedding
    if info_embedding is not None:
        row["info_embedding"] = info_embedding
    return row


def _metadata_string(product: Dict[str, Any]) -> Optional[str]:
    import json
    meta = product.get("metadata")
    if not meta:
        return None
    if isinstance(meta, dict):
        return json.dumps(meta, ensure_ascii=False)
    return str(meta)


def get_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set (e.g. in .env)")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def upsert_products(
    client: Client,
    products: List[Dict[str, Any]],
    image_embeddings: Optional[List[Optional[List[float]]]] = None,
    info_embeddings: Optional[List[Optional[List[float]]]] = None,
) -> None:
    """Upsert products into public.products. Uses (source, product_url) as conflict key."""
    if not products:
        return
    image_embeddings = image_embeddings or [None] * len(products)
    info_embeddings = info_embeddings or [None] * len(products)
    rows = []
    for i, p in enumerate(products):
        ie = image_embeddings[i] if i < len(image_embeddings) else None
        te = info_embeddings[i] if i < len(info_embeddings) else None
        rows.append(_row_from_product(p, ie, te))

    try:
        result = client.table("products").upsert(
            rows,
            on_conflict="source,product_url",
            ignore_duplicates=False,
        ).execute()
        print(f"Upserted {len(result.data)} rows to Supabase.")
    except Exception as e:
        print(f"Supabase upsert error: {e}")
        raise
