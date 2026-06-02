#!/bin/bash
# Polygon bulk-pull watchdog
# ==========================
# The pull (polygon_options.py --scope full) occasionally wedges mid-underlying
# with no per-request timeout catching it — it then makes zero progress for hours.
# This watchdog watches the pull's LOG mtime (it prints progress every ~200
# contracts). If the log goes silent for STALL_SEC, the pull is hung → kill +
# restart. The pull is resumable (skips underlyings whose parquet already exists),
# so a restart loses only the in-progress underlying and continues.
#
# Run via a 5-min loop:
#   nohup bash -c 'while true; do bash scripts/poly_watchdog.sh; sleep 300; done' \
#       > /tmp/poly_watchdog_loop.log 2>&1 &

set -u
REPO="/Users/bsannadi/Desktop/bharath/AlpacaTrader"
PY="$REPO/venv/bin/python3.11"
PYPATH="$REPO/venv/lib/python3.11/site-packages"
LOG="/tmp/poly_options_full.log"
WLOG="/tmp/poly_watchdog.log"
STALL_SEC=900            # 15 min of no log output = hung (healthy runs print every ~1-2 min)

ts() { date "+%Y-%m-%d %H:%M:%S"; }
note() { echo "$(ts) $*" >> "$WLOG"; }

start_pull() {
    cd "$REPO" || { note "cd failed"; exit 1; }
    PYTHONPATH="$PYPATH" nohup "$PY" "$REPO/scripts/polygon_options.py" --scope full >> "$LOG" 2>&1 &
    note "(re)started pull pid=$!"
}

if ! pgrep -f "polygon_options.py" >/dev/null 2>&1; then
    note "pull not running — starting"
    start_pull
    exit 0
fi

# Running — check whether it's making progress (log mtime).
if [ ! -f "$LOG" ]; then
    exit 0
fi
age=$(( $(date +%s) - $(stat -f %m "$LOG" 2>/dev/null || echo 0) ))
if [ "$age" -lt "$STALL_SEC" ]; then
    exit 0   # progressing — log written within the window
fi

note "STALLED (${age}s with no log output) — killing + restarting pull"
pkill -9 -f "polygon_options.py" 2>/dev/null
sleep 3
start_pull
exit 0
