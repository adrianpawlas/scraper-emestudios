#!/bin/bash
# Eme Studios Scraper - Setup and Automation
# Run this to set up automatic scheduling

SCRIPT_DIR="/Users/adrianpawlas/Finds/Scrapers/scraper-emestudios"
LOG_FILE="$SCRIPT_DIR/scraper.log"
PLIST_FILE="$SCRIPT_DIR/com.emestudios.scraper.plist"

echo "========================================="
echo "Eme Studios Scraper Setup"
echo "========================================="
echo ""

# Ensure log file exists
touch "$LOG_FILE"
echo "Log file: $LOG_FILE"
echo ""

# Check if scraper works
echo "Testing scraper..."
cd "$SCRIPT_DIR"
python3 -c "from src.scraper import EmeStudiosScraper; print('Scraper OK')" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "Scraper module: OK"
else
    echo "ERROR: Scraper module not working"
    exit 1
fi
echo ""

# Menu
echo "Automation Options:"
echo "-----------------"
echo "1. Add cron job (Sundays + Thursdays at 6PM)"
echo "2. Install launchd daemon (requires sudo)"
echo "3. Manual run only"
echo ""
echo -n "Choose [1-3]: "
read choice

case $choice in
    1)
        echo ""
        echo "To add cron job, run:"
        echo "  crontab -e"
        echo ""
        echo "Then add this line:"
        echo "  0 18 * * 0,4 $SCRIPT_DIR/run_scraper.sh >> $LOG_FILE 2>&1"
        echo ""
        echo "Or run this command (may require permissions):"
        echo "  (crontab -l 2>/dev/null; echo '0 18 * * 0,4 $SCRIPT_DIR/run_scraper.sh >> $LOG_FILE 2>&1') | crontab -"
        ;;
    2)
        echo ""
        echo "To install launchd daemon, run:"
        echo "  sudo cp $PLIST_FILE /Library/LaunchDaemons/"
        echo "  sudo launchctl load /Library/LaunchDaemons/com.emestudios.scraper.plist"
        ;;
    3)
        echo ""
        echo "Manual run: python3 run.py"
        ;;
esac

echo ""
echo "Setup complete!"