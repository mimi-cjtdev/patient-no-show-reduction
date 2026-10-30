#!/bin/bash
# Hourly job for cron: backend Google Sheet -> SQLite -> Metabase (app/sync.py), logged to logs/sync.log.
#   15 * * * * "/path/to/patient-no-show-reduction/scripts/hourly_sync.sh"
cd "$(dirname "$0")/.." || exit 1
export PATH="/usr/local/bin:/opt/homebrew/bin:$PATH"     # cron's PATH has no docker (used to refresh Metabase)
mkdir -p logs
.venv/bin/python app/sync.py >> logs/sync.log 2>&1
