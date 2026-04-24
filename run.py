#!/usr/bin/env python3
"""
Eme Studios Scraper - Run Script
Usage:
  python3 run.py           # Full scrape all categories
  python3 run.py --limit N # Limited scrape (N products per category)
  python3 run.py --test    # Test with 2 products per category
"""
import sys
import asyncio
import argparse
from datetime import datetime
from src.scraper import EmeStudiosScraper

def log(msg):
    """Log with timestamp"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

async def main():
    parser = argparse.ArgumentParser(description='Eme Studios Scraper')
    parser.add_argument('--limit', type=int, default=0, help='Max products per category')
    parser.add_argument('--test', action='store_true', help='Test mode with 2 products')
    parser.add_argument('--category', type=str, default=None, help='Single category to scrape')
    args = parser.parse_args()
    
    limit = 2 if args.test else args.limit
    
    log("Starting Eme Studios Scraper")
    log(f"Mode: test={args.test}, limit={limit}")
    
    scraper = EmeStudiosScraper()
    await scraper.init()
    
    total_products = 0
    total_saved = 0
    
    try:
        if args.category:
            # Single category
            products = await scraper.scrape_category(args.category, limit=limit)
            all_products = products
        else:
            # All categories
            all_products = []
            for cat in scraper.CATEGORIES:
                products = await scraper.scrape_category(cat, limit=limit)
                all_products.extend(products)
                log(f"Category {cat}: {len(products)} products")
        
        total_products = len(all_products)
        
        if all_products:
            await scraper.save_products(all_products)
            total_saved = len(all_products)
        
        log(f"COMPLETE! Total: {total_products} products, {total_saved} saved")
        
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        await scraper.close()
    
    return 0

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)