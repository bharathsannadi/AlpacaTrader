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
# Covers two services:
#   - main trading app   :5000  (com.alpacatrader)
#   - standalone charts  :5001  (com.alpacatrader.charts)
# Each is checked independently with its own consecutive-fail counter.
#
# Restart path (per service):
#   - If the service runs under launchd (its .plist loaded), KeepAlive
#     relaunches it automatically after the kill.
#   - Otherwise (manual / macOS .app launch) this script relaunches it
#     itself so a hung process self-heals regardless of how it was started.
#
# Run via com.spy_auto_trader.watchdog.plist (every 60s) or cron.
# Idempotent and safe to run repeatedly.

set -u
REPO="/Users/bsannadi/Desktop/bharath/AlpacaTrader"
PY="$REPO/venv/bin/python3.11"
PYPATH="$REPO/venv/lib/python3.11/site-packages"
LOG="/tmp/alpacatrader.watchdog.log"
MAX_FAILS=3                       # consecutive bad checks before acting (~3 min @ 60s)

ts() { date "+%Y-%m-%d %H:%M:%S"; }
note() { echo "$(ts) $*" >> "$LOG"; }

# relaunch_cmd <name> — direct relaunch used only when launchd KeepAlive
# didn't bring the service back (manual / .app launch).
relaunch_cmd() {
    case "$1" in
        main)
            PYTHONPATH="$PYPATH" nohup "$PY" -u "$REPO/scripts/app.py" --paper \
                >> "$REPO/logs/app.log" 2>&1 &
            note "[main] relaunched app pid=$!" ;;
        charts)
            PYTHONPATH="$PYPATH" CHARTS_PORT=5001 nohup "$PY" -u "$REPO/scripts/charts_server.py" \
                >> "$REPO/logs/charts_server.log" 2>&1 &
            note "[charts] relaunched app pid=$!" ;;
    esac
}

# check_service <name> <port> <url>
# HTTP code: 200 = healthy, 503 = hung (degraded), 000 = down/refused
check_service() {
    local name="$1" port="$2" url="$3"
    local failfile="/tmp/alpacatrader.watchdog.${name}.failcount"
    local bodyfile="/tmp/alpacatrader.watchdog.${name}.body"

    local code
    code=$(curl -s -o "$bodyfile" -w "%{http_code}" --max-time 8 "$url" 2>/dev/null)

    if [ "$code" = "200" ]; then
        echo 0 > "$failfile" 2>/dev/null   # healthy — reset counter
        return 0
    fi

    # Unhealthy (503 hung, or 000 down). Increment consecutive-fail counter.
    local fails
    fails=$(cat "$failfile" 2>/dev/null || echo 0)
    fails=$((fails + 1))
    echo "$fails" > "$failfile"
    local body
    body=$(head -c 200 "$bodyfile" 2>/dev/null)
    note "[$name] UNHEALTHY http=$code fail=$fails/$MAX_FAILS body=$body"

    [ "$fails" -lt "$MAX_FAILS" ] && return 0   # not yet — avoid acting on a blip

    # Threshold hit — kill the wedged process. launchd KeepAlive (or the
    # relaunch below) brings up a clean one.
    note "[$name] THRESHOLD HIT — killing app on :$port (hung or down for ${MAX_FAILS} checks)"
    local pids
    pids=$(lsof -ti :"$port" 2>/dev/null)
    if [ -n "$pids" ]; then
        echo "$pids" | xargs kill -9 2>/dev/null
        note "[$name] killed PIDs: $(echo "$pids" | tr '\n' ' ')"
        sleep 3
    fi
    echo 0 > "$failfile"

    # If launchd owns it, KeepAlive will relaunch — give it a moment, verify.
    sleep 5
    if curl -s -o /dev/null --max-time 5 "$url" 2>/dev/null; then
        note "[$name] recovered (launchd KeepAlive or already back up)"
        return 0
    fi

    # Not back (manual / .app launch — no launchd). Relaunch ourselves.
    note "[$name] no auto-restart detected — relaunching app directly"
    cd "$REPO" || { note "[$name] cd $REPO failed"; return 1; }
    relaunch_cmd "$name"
    return 0
}

check_service main   5000 "http://127.0.0.1:5000/health"
check_service charts 5001 "http://127.0.0.1:5001/health"
exit 0
