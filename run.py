#!/usr/bin/env python3
"""
Eme Studios Scraper - Main Entry Point
"""
import argparse
import asyncio
from src.scraper import EmeStudiosScraper

def main():
    parser = argparse.ArgumentParser(description="Eme Studios Scraper")
    parser.add_argument("--test", action="store_true", help="Run in test mode (3 products)")
    parser.add_argument("--max", type=int, default=None, help="Maximum number of products to scrape")
    parser.add_argument("--url", type=str, help="Scrape a single product URL")
    
    args = parser.parse_args()
    
    scraper = EmeStudiosScraper()
    
    if args.url:
        # Single URL
        asyncio.run(scraper.scrape_single_product(args.url))
    else:
        asyncio.run(scraper.run(
            test_mode=args.test, 
            max_products=args.max
        ))


if __name__ == "__main__":
    main()