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
MAX_TIME=15                       # per-probe HTTP timeout. Must exceed worst-case
                                  # eventlet-hub stalls (screener yfinance fan-out /
                                  # LLM debate freeze the single hub for several
                                  # seconds). 8s was too tight → false 000s → a
                                  # kill-loop that restarted a healthy app (2026-06-16).

ts() { date "+%Y-%m-%d %H:%M:%S"; }
note() { echo "$(ts) $*" >> "$LOG"; }

# launchd_label <name> — the launchd job that owns a service, or "" if none.
# When a service is launchd-managed with KeepAlive, launchd is the SOLE restart
# authority; the watchdog must only KILL and let KeepAlive relaunch. Doing its
# own nohup relaunch races KeepAlive → two instances collide on the port →
# corrupted responses (http=000) → more kills → loop. (Root cause, 2026-06-16.)
launchd_label() {
    case "$1" in
        main)   echo "com.alpacatrader" ;;
        charts) echo "com.alpacatrader.charts" ;;
        *)      echo "" ;;
    esac
}

# is_launchd_managed <label> — true if the job is currently loaded in launchd.
is_launchd_managed() {
    [ -n "$1" ] && launchctl list "$1" >/dev/null 2>&1
}

# relaunch_cmd <name> — direct relaunch used ONLY when the service is NOT
# launchd-managed (manual / .app launch). Never used while launchd KeepAlive
# owns the service.
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
    code=$(curl -s -o "$bodyfile" -w "%{http_code}" --max-time "$MAX_TIME" "$url" 2>/dev/null)

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
    # LISTENER only. Plain `lsof -ti :PORT` also matches CLIENT connections to
    # the port (e.g. a browser tab on the dashboard), so it would kill innocent
    # client processes and report misleading multi-PID kills. Restrict to the
    # process actually listening. (2026-06-16)
    pids=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null)
    if [ -n "$pids" ]; then
        echo "$pids" | xargs kill -9 2>/dev/null
        note "[$name] killed PIDs: $(echo "$pids" | tr '\n' ' ')"
        sleep 3
    fi
    echo 0 > "$failfile"

    local label
    label=$(launchd_label "$name")
    if is_launchd_managed "$label"; then
        # launchd KeepAlive owns restart. Do NOT relaunch ourselves — that
        # races KeepAlive and collides two instances on the port (the very
        # bug that caused the 2026-06-16 kill-loop). Just wait past the
        # plist ThrottleInterval (10s) and verify; if it's still not back,
        # leave it to launchd rather than spawning a competing instance.
        note "[$name] launchd-managed ($label) — waiting for KeepAlive restart"
        sleep 15
        if curl -s -o /dev/null --max-time "$MAX_TIME" "$url" 2>/dev/null; then
            note "[$name] recovered via launchd KeepAlive"
        else
            note "[$name] still down after KeepAlive window — leaving to launchd (no direct relaunch)"
        fi
        return 0
    fi

    # NOT launchd-managed (manual / .app launch) — we are the only restart
    # authority, so relaunch directly.
    note "[$name] not launchd-managed — relaunching app directly"
    cd "$REPO" || { note "[$name] cd $REPO failed"; return 1; }
    relaunch_cmd "$name"
    return 0
}

check_service main   5000 "http://127.0.0.1:5000/health"
check_service charts 5001 "http://127.0.0.1:5001/health"
exit 0
