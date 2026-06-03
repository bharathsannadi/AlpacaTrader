#!/bin/bash
# SPY Auto Trader — health watchdog
# =================================
# launchd KeepAlive restarts a DEAD process. It CANNOT detect a HUNG one —
# Flask still answers HTTP while the position_monitor thread is wedged
# (deadlock / eventlet stall) → stops never fire → positions silently
# exposed. This watchdog hits the *meaningful* /health endpoint (which
# returns 503 when the monitor loop is stale) and, on repeated failure,
# kills the app so it gets restarted clean.
#
# Restart path:
#   - If the app runs under launchd (com.spy_auto_trader.plist loaded),
#     KeepAlive(Crashed=true) relaunches it automatically after the kill.
#   - Otherwise (manual / macOS .app launch) this script relaunches it
#     itself so a hung process self-heals regardless of how it was started.
#
# Run via com.spy_auto_trader.watchdog.plist (every 60s) or cron.
# Idempotent and safe to run repeatedly.

set -u
REPO="/Users/bsannadi/Desktop/bharath/AlpacaTrader"
PY="$REPO/venv/bin/python3.11"
URL="http://127.0.0.1:5000/health"
LOG="/tmp/alpacatrader.watchdog.log"
FAIL_FILE="/tmp/alpacatrader.watchdog.failcount"
MAX_FAILS=3                       # consecutive bad checks before acting (~3 min @ 60s)

ts() { date "+%Y-%m-%d %H:%M:%S"; }
note() { echo "$(ts) $*" >> "$LOG"; }

# HTTP code: 200 = healthy, 503 = hung (degraded), 000 = down/refused
code=$(curl -s -o /tmp/alpacatrader.watchdog.body -w "%{http_code}" --max-time 8 "$URL" 2>/dev/null)

if [ "$code" = "200" ]; then
    # Healthy — reset the failure counter and exit quietly.
    echo 0 > "$FAIL_FILE" 2>/dev/null
    exit 0
fi

# Unhealthy (503 hung, or 000 down). Increment consecutive-fail counter.
fails=$(cat "$FAIL_FILE" 2>/dev/null || echo 0)
fails=$((fails + 1))
echo "$fails" > "$FAIL_FILE"
body=$(cat /tmp/alpacatrader.watchdog.body 2>/dev/null | head -c 200)
note "UNHEALTHY http=$code fail=$fails/$MAX_FAILS body=$body"

if [ "$fails" -lt "$MAX_FAILS" ]; then
    exit 0   # not yet — give it another cycle (avoids acting on a blip)
fi

# Threshold hit — kill the wedged process. launchd KeepAlive (or the
# relaunch below) brings up a clean one.
note "THRESHOLD HIT — killing app on :5000 (hung or down for ${MAX_FAILS} checks)"
PIDS=$(lsof -ti :5000 2>/dev/null)
if [ -n "$PIDS" ]; then
    echo "$PIDS" | xargs kill -9 2>/dev/null
    note "killed PIDs: $PIDS"
    sleep 3
fi
echo 0 > "$FAIL_FILE"

# If launchd owns it, KeepAlive will relaunch — give it a moment, then verify.
sleep 5
if curl -s -o /dev/null --max-time 5 "$URL" 2>/dev/null; then
    note "recovered (launchd KeepAlive or already back up)"
    exit 0
fi

# Not back (manual / .app launch — no launchd). Relaunch ourselves.
# Must mirror the known-good invocation: the venv site-packages on PYTHONPATH
# (Homebrew vs venv split) and --paper. The single-instance guard in app.py
# makes a relaunch safe even if something else also brings one up.
note "no auto-restart detected — relaunching app directly"
cd "$REPO" || { note "cd $REPO failed"; exit 1; }
PYTHONPATH="$REPO/venv/lib/python3.11/site-packages" \
    nohup "$PY" -u "$REPO/scripts/app.py" --paper >> "$REPO/logs/app.log" 2>&1 &
note "relaunched app pid=$!"
exit 0
