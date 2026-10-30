#!/bin/bash
# Runs the hourly jobs now and then every hour, for as long as this terminal stays open:
#   1. app/reminders.py  - 72h / 24h reminder emails, unclaimed waitlist offers passed on
#   2. app/sync.py       - Google Sheet -> SQLite -> Metabase (after the reminders, so their log rows sync too)
# The alternative to cron on a Mac where cron can't run: start it in a terminal tab and leave it.
#   scripts/run_every_hour.sh          # Ctrl+C to stop
cd "$(dirname "$0")/.." || exit 1
mkdir -p logs
while true; do
    .venv/bin/python app/reminders.py 2>&1 | tee -a logs/reminders.log
    .venv/bin/python app/sync.py 2>&1 | tee -a logs/sync.log
    echo "next run at $(date -v+1H '+%H:%M')  (Ctrl+C to stop)"
    sleep 3600
done
