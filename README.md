# Eme Studios Scraper - README

Full scraper for Eme Studios fashion store with image embeddings.

## Installation

```bash
cd /Users/adrianpawlas/Finds/Scrapers/scraper-emestudios
pip install -r requirements.txt
python3 -m playwright install
```

## Usage

### Full scrape (all categories)
```bash
python3 run.py
```

### Test mode (2 products per category)
```bash
python3 run.py --test
```

### Limited products
```bash
python3 run.py --limit 10
```

### Using shell script
```bash
./run_scraper.sh
```

## Automation

### Option 1: Cron (run manually)
```bash
crontab -e
# Add: 0 18 * * 0,4 /Users/adrianpawlas/Finds/Scrapers/scraper-emestudios/run_scraper.sh >> /Users/adrianpawlas/Finds/Scrapers/scraper-emestudios/scraper.log 2>&1
```

### Option 2: LaunchDaemon (requires sudo)
```bash
sudo cp com.emestudios.scraper.plist /Library/LaunchDaemons/
sudo launchctl load /Library/LaunchDaemons/com.emestudios.scraper.plist
```

## Manual Run

You can run the scraper anytime:
```bash
python3 run.py
```

## Output

- Logs: `scraper.log`
- Products are upserted to Supabase "products" table
- 768-dim embeddings for images and text