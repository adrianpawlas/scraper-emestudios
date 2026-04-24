#!/bin/bash
# Eme Studios Scraper Automation
# 
# Setup: Copy this file to ~/Library/LaunchAgents/com.emestudios.scraper.plist
# Load:  launchctl load ~/Library/LaunchAgents/com.emestudios.scraper.plist
# Unload: launchctl unload ~/Library/LaunchAgents/com.emestudios.scraper.plist
#
# Cron alternative (run on Sundays and Thursdays at 6PM):
# 0 18 * * 0,4 /Users/adrianpawlas/Finds/Scrapers/scraper-emestudios/run_scraper.sh >> /Users/adrianpawlas/Finds/Scrapers/scraper-emestudios/scraper.log 2>&1
#

SCRIPT_DIR="/Users/adrianpawlas/Finds/Scrapers/scraper-emestudios"
LOG_FILE="$SCRIPT_DIR/scraper.log"

# Log function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "=========================================="
log "Starting Eme Studios Scraper (Scheduled)"
log "=========================================="

cd "$SCRIPT_DIR"

# Run the scraper
python3 run.py 2>&1 | tee -a "$LOG_FILE"
EXIT_CODE=${PIPESTATUS[0]}

log "Scraper finished with exit code: $EXIT_CODE"
log "=========================================="

exit $EXIT_CODE