# Eme Studios Scraper

Scrapes product data from [Eme Studios](https://emestudios.com), generates 768‑dim image and text embeddings with **google/siglip-base-patch16-384**, and upserts into a Supabase `products` table.

## Features

- Scrapes category pages with **infinite scroll** (all products from configured collections).
- Extracts per-product: title, description, category, gender, price, sale, images.
- Uses **plain product-on-white** images (CDN URLs matching `.../files/YYYY_MM_DDEME*.webp`) for `image_url` and `image_embedding`; other images go to `additional_images`.
- **Image embeddings**: 768‑dim with SigLIP (same model).
- **Text embeddings** (`info_embedding`): 768‑dim from title, description, category, gender, price, metadata.
- Upserts into Supabase `products` with unique `(source, product_url)`.

## Setup

1. **Clone and install**

   ```bash
   git clone https://github.com/adrianpawlas/scraper-emestudios.git
   cd scraper-emestudios
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   pip install -r requirements.txt
   playwright install chromium
   ```

2. **Environment**

   Copy `.env.example` to `.env` and set:

   - `SUPABASE_URL` – your Supabase project URL  
   - `SUPABASE_KEY` – your Supabase anon or service role key  

3. **Run**

   ```bash
   python main.py
   ```

   - `python main.py --no-headless` – show browser.
   - `python main.py --skip-embeddings` – scrape only, no embeddings (faster for testing).

## Automation (GitHub Actions)

- **Scheduled**: workflow runs every day at **00:00 UTC**.
- **Manual**: open the repo → **Actions** → **Scrape Eme Studios** → **Run workflow**.

In the repo **Settings → Secrets and variables → Actions**, add:

- `SUPABASE_URL` – your Supabase project URL  
- `SUPABASE_KEY` – your Supabase anon or service role key  

## Categories scraped

- All products: `https://emestudios.com/en-at/collections/all-products-old-ef689c`
- Accessories: `https://emestudios.com/en-at/collections/accessories`

Configured in `config.py`.

## Table schema

The scraper fills (at least): `source`, `brand`, `product_url`, `image_url`, `additional_images`, `title`, `description`, `category`, `gender`, `price`, `sale`, `second_hand`, `image_embedding`, `info_embedding`, `metadata`, `created_at`.  
`id` is derived from `source` + `product_url`; upsert uses `(source, product_url)`.
