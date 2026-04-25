import asyncio
import sys
import argparse
from scraper import ProductScraper
from database import DatabaseService
from config import SOURCE, CATEGORY_URLS


async def main(test_mode=False, test_count=3, skip_embeddings=False):
    print("=" * 60)
    print("Eme Studios Scraper Starting")
    print(f"Source: {SOURCE}")
    print(f"Skip embeddings: {skip_embeddings}")
    print("=" * 60)

    scraper = ProductScraper()
    db = DatabaseService()

    print("\n[1/3] Scraping products from Eme Studios...")
    products = await scraper.run()

    print(f"\nScraped {len(products)} products")

    if test_mode and len(products) > test_count:
        print(f"\n[TEST] Limiting to {test_count} products for testing...")
        products = products[:test_count]

    print("\n[2/3] Processing and upserting products...")
    results = db.process_products(products)

    print("\n[3/3] Run Summary:")
    print(f"  ✓ {results.get('new', 0)} new products added")
    print(f"  ✓ {results.get('updated', 0)} products updated")
    print(f"  ○ {results.get('skipped', 0)} products unchanged (skipped)")
    print(f"  ✓ {results.get('stale_deleted', 0)} stale products deleted")
    
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