#!/bin/bash
# Setup automation for Eme Studios Scraper
# Run this script to set up cron jobs

SCRIPT_DIR="/Users/adrianpawlas/Finds/Scrapers/scraper-emestudios"
CRON_LINE="0 18 * * 0,4 $SCRIPT_DIR/run_scraper.sh >> $SCRIPT_DIR/scraper.log 2>&1"

echo "Setting up Eme Studios Scraper automation..."
echo ""

# Check if cron exists
if ! command -v crontab &> /dev/null; then
    echo "ERROR: crontab not found. Please install or use a different scheduler."
    exit 1
fi

# Add cron job
echo "Adding cron job: $CRON_LINE"
echo ""

# Check existing crontab
echo "Current crontab:"
crontab -l 2>/dev/null || echo "(empty)"
echo ""

# The cron job will run:
# - At 18:00 (6PM)
# - On Sundays (0) and Thursdays (4)
# - Every week

echo "To add the cron job manually, run:"
echo "  crontab -e"
echo ""
echo "Then add this line:"
echo "  $CRON_LINE"
echo ""

# Try to add automatically
echo "Attempting to add cron job..."
(crontab -l 2>/dev/null | grep -v "scraper-emestudios"; echo "$CRON_LINE") | crontab -

if [ $? -eq 0 ]; then
    echo "SUCCESS! Cron job added."
    echo "Crontab now contains:"
    crontab -l
else
    echo "Could not add cron job automatically."
    echo "This may require special permissions or use of launchd instead."
fi

echo ""
echo "Setup complete!"