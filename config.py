"""Configuration and constants."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

SOURCE = "scraper"
BRAND = "Eme Studios"

# Category URLs to scrape
CATEGORY_URLS = [
    "https://emestudios.com/en-at/collections/all-products-old-ef689c",
    "https://emestudios.com/en-at/collections/accessories",
]

# Regex pattern for "plain product on white" images (cdn/shop/files/YYYY_MM_DDEME*.webp)
# These get image_embedding; all other product images go to additional_images.
EMBED_IMAGE_URL_PATTERN = r"/cdn/shop/files/\d{4}_\d{2}_\d{2}EME\d+\.webp"

# Scroll / wait
SCROLL_PAUSE_SEC = 5
MAX_SCROLL_ATTEMPTS = 50

# HuggingFace model for 768-dim image and text embeddings
EMBEDDING_MODEL = "google/siglip-base-patch16-384"

# Base URL for resolving relative links
BASE_URL = "https://emestudios.com"
