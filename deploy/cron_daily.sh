#!/usr/bin/env bash
# Daily Fantasy pipeline — runs on kv8 via cron.
#   1. pull latest (picks up any board CSVs you committed)
#   2. grade any settled paper entries (batter + pitcher markets)
#   3. log today's entries (if a board was captured)
#   4. rebuild the static dashboard and publish it
#
# Install (on kv8, one-time):
#   git clone https://github.com/mrglennc64/Fantasy.git /opt/fantasy
#   crontab -e  ->  add:
#   #  05:00 grade yesterday, 16:30 ET log+publish today's slate
#   30 20 * * *  /opt/fantasy/deploy/cron_daily.sh >> /var/log/fantasy-cron.log 2>&1
set -euo pipefail

REPO="/opt/fantasy"
WWW="/var/www/fantasy"
PY="$(command -v python3)"
DATE="$(TZ=America/New_York date +%F)"

cd "$REPO"
git pull --quiet --ff-only || echo "git pull skipped"

echo "=== $(date -u) daily run for $DATE ==="
"$PY" pick6/grade.py || echo "grade failed"
"$PY" pick6/log_entries.py "$DATE" || echo "log skipped (no board / already logged)"
"$PY" web/build_site.py "$DATE" "$REPO/web/dist/index.html"

install -o www-data -g www-data -m 644 "$REPO/web/dist/index.html" "$WWW/index.html"
# persist newly graded results back to the repo so the record survives
git add data/pick6_entries.csv 2>/dev/null || true
git -c user.name=fantasy-cron -c user.email=cron@perfecthold.online \
    commit -q -m "cron: grade+log $DATE" 2>/dev/null && git push --quiet || echo "nothing to commit"
echo "=== published https://fantasy.perfecthold.online ==="
