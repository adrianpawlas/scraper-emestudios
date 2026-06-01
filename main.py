import asyncio
import sys
import argparse
import traceback
from scraper import ProductScraper
from database import DatabaseService
from config import SOURCE, CATEGORY_URLS
from embedding_service import EmbeddingService


def backfill_missing_embeddings(db: DatabaseService, emb: EmbeddingService, batch_size: int = 500) -> dict:
    """Find products in the database with missing embeddings and regenerate them.
    Loops in batches until all missing products are processed.
    """
    print("\n--- Backfill: Checking for products with missing embeddings ---")
    
    total_checked = 0
    total_updated = 0
    total_failed = 0
    max_iterations = 20  # Safety limit
    iteration = 0
    
    while True:
        iteration += 1
        if iteration > max_iterations:
            print(f"  Reached max iterations ({max_iterations}). Stopping backfill.")
            break
        
        missing_products = db.find_products_missing_embeddings(limit=batch_size)
        
        if not missing_products:
            print("  All products have embeddings. Nothing to backfill.")
            break
        
        print(f"  Products needing backfill in this batch: {len(missing_products)}")
        total_checked += len(missing_products)
        
        updates = []
        for p in missing_products:
            try:
                update = {"id": p["id"]}
                
                if p["_needs_info_embedding"]:
                    title = p.get("title") or ""
                    brand = p.get("brand") or ""
                    description = p.get("description") or ""
                    category = p.get("category") or ""
                    gender = p.get("gender") or ""
                    price = p.get("price") or ""
                    text_info = f"{title} {brand} {description} {category} {gender} {price}"
                    update["info_embedding"] = emb.get_text_embedding(text_info)
                    print(f"    Backfilled info_embedding for {p.get('id', 'unknown')}")
                
                if p["_needs_image_embedding"]:
                    image_url = p.get("image_url")
                    if image_url:
                        update["image_embedding"] = emb.get_image_embedding(image_url)
                        print(f"    Backfilled image_embedding for {p.get('id', 'unknown')}")
                
                if len(update) > 1:  # Has fields beyond just "id"
                    updates.append(update)
                    
            except Exception as e:
                print(f"    Error backfilling embeddings for {p.get('id', 'unknown')}: {e}")
                traceback.print_exc()
                continue
        
        if updates:
            print(f"  Updating {len(updates)} products with new embeddings...")
            result = db.batch_update_embeddings(updates)
            total_updated += result["updated"]
            total_failed += result["failed"]
            print(f"  Updated: {result['updated']}, Failed: {result['failed']}")
            if result.get('errors'):
                for err in result['errors'][:3]:
                    print(f"    Error: {err}")
        
        # If we got fewer than batch_size, we've processed all missing products
        if len(missing_products) < batch_size:
            print("  All missing products processed.")
            break
    
    return {"checked": total_checked, "updated": total_updated, "failed": total_failed}


async def main(test_mode=False, test_count=3, skip_embeddings=False):
    print("=" * 60)
    print("Eme Studios Scraper Starting")
    print(f"Source: {SOURCE}")
    print(f"Skip embeddings: {skip_embeddings}")
    print("=" * 60)

    scraper = ProductScraper()
    db = DatabaseService()

    print("\n[1/3] Scraping products from Eme Studios...")
    products = await scraper.run(test_mode=test_mode, test_count=test_count)

    print(f"\nScraped {len(products)} products")

    print("\n[2/3] Processing and upserting products...")
    results = db.process_products(products)

    print("\n[3/3] Backfilling missing embeddings...")
    if skip_embeddings:
        print("  Skipped (--skip-embeddings flag)")
        backfill_results = {}
    else:
        emb = EmbeddingService()
        backfill_results = backfill_missing_embeddings(db, emb, batch_size=500)

    print("\n[4/4] Run Summary:")
    print(f"  ✓ {results.get('new', 0)} new products added")
    print(f"  ✓ {results.get('updated', 0)} products updated")
    print(f"  ○ {results.get('skipped', 0)} products unchanged (skipped)")
    print(f"  ✓ {results.get('stale_deleted', 0)} stale products deleted")
    
    if backfill_results:
        print(f"  ✓ {backfill_results.get('updated', 0)} embeddings backfilled")
        if backfill_results.get('failed', 0) > 0:
            print(f"  ✗ {backfill_results.get('failed', 0)} embeddings failed to backfill")
    
    if results.get('failed', 0) > 0:
        print(f"  ✗ {results.get('failed', 0)} products failed")

    if results.get('errors'):
        print(f"\nErrors ({len(results['errors'])}):")
        for err in results['errors'][:3]:
            print(f"  - {err}")

    print("\n" + "=" * 60)
    print("Scraping Complete!")
    print("=" * 60)
    
    total_changes = results.get('new', 0) + results.get('updated', 0) + results.get('stale_deleted', 0)
    return total_changes > 0 or results.get('failed', 0) == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Eme Studios Scraper')
    parser.add_argument('--test', action='store_true', help='Run in test mode (limited products)')
    parser.add_argument('--count', type=int, default=3, help='Number of products in test mode')
    parser.add_argument('--skip-embeddings', action='store_true', help='Skip generating embeddings for existing products')
    args = parser.parse_args()
    
    success = asyncio.run(main(test_mode=args.test, test_count=args.count, skip_embeddings=args.skip_embeddings))
    sys.exit(0 if success else 1)