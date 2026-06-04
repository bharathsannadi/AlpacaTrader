# Deployment

How the AlpacaTrader server runs on a developer Mac. The same setup would work
on a server / cloud VM with minor path adjustments.

---

## Topology

```
┌──────────────────────────────────┐
│ launchd  (~/Library/LaunchAgents/)│  FIVE user-level agents
│  • com.alpacatrader               │── main app, :5000  (RunAtLoad + KeepAlive)
│  • com.alpacatrader.charts        │── charts-only, :5001 (RunAtLoad + KeepAlive)
│  • com.alpacatrader.caffeinate    │── caffeinate -i -s, never idle-sleep
│  • com.alpacatrader.polygon       │── Polygon 5yr archival keep-alive
│  • com.spy_auto_trader.watchdog   │── every 60s, kills app if /health fails 3×
└──────────┬───────────────────────┘
           │
           ▼
┌─────────────────────────┐   ┌─────────────────────────┐
│ scripts/app.py          │   │ scripts/charts_server.py│
│  Flask+Socket.IO :5000  │   │  charts-only      :5001 │
│  • _auto_login()        │   │  • yfinance data        │
│  • price_ticker  (5s)   │   │  • NO Alpaca login      │
│  • scheduler     (15s)  │   └─────────────────────────┘
│  • position_monitor(10s)│
└──────────┬──────────────┘
           │
           ▼  HTTPS API + WebSocket
┌─────────────────────────┐
│ Alpaca paper trading    │  https://paper-api.alpaca.markets
└─────────────────────────┘
```

The watchdog + caffeinate + each agent's `KeepAlive` together make the stack
survive **crash, hang, sleep, and reboot**: KeepAlive restarts a clean exit,
the watchdog kills + relaunches a *hung* process, and caffeinate stops the Mac
from idle-sleeping (which previously froze stop-loss monitoring). RunAtLoad
brings everything back after a reboot.

---

## The five launchd agents

| Agent | What it runs | Port | Keys |
|-------|--------------|------|------|
| `com.alpacatrader` | `scripts/app.py` — main trading app | :5000 | RunAtLoad + KeepAlive |
| `com.alpacatrader.charts` | `scripts/charts_server.py` — charts-only, yfinance, no Alpaca login | :5001 | RunAtLoad + KeepAlive |
| `com.alpacatrader.caffeinate` | `caffeinate -i -s` — Mac never idle-sleeps (1-min idle sleep previously froze stop-loss monitoring) | — | RunAtLoad + KeepAlive |
| `com.alpacatrader.polygon` | `scripts/poly_keepalive.sh` → `poly_watchdog.sh` → `polygon_options.py --scope full` — 5yr archival loop | — | KeepAlive + AbandonProcessGroup |
| `com.spy_auto_trader.watchdog` | `scripts/watchdog.sh` every 60s — monitors BOTH :5000 and :5001; 3 failed `/health` checks → kill → relaunch | — | StartInterval 60 + RunAtLoad |

> ⏳ **Polygon deadline 2026-06-16** — `com.alpacatrader.polygon` archives 5yr
> data under a subscription that expires 2026-06-16. **Unload it after that date.**

---

## First-time setup

### 1. Install dependencies

```bash
cd /Users/bsannadi/Desktop/bharath/AlpacaTrader
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

See [README.md](../README.md#installation) for Python version notes and the
chromadb / Python 3.14 workaround.

### 2. Create `.env`

```bash
cp .env.example .env
chmod 600 .env
# edit .env, fill in your real Alpaca paper API key + secret
```

All three Alpaca env var names need the same key pair — see [CLAUDE.md](../CLAUDE.md#credentials--secrets)
for why this duplication exists (tracked todo to unify).

### 3. Install the launchd agents

Plist copies live in `deploy/launchd/` (under version control). Copy the ones
you want into `~/Library/LaunchAgents/` and `load` them. The main app and
watchdog are the minimum; the others add charts, sleep-prevention, and the
Polygon archival loop.

```bash
# Required: main app (:5000)
cp deploy/launchd/com.alpacatrader.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.alpacatrader.plist

# Recommended: watchdog (monitors :5000 AND :5001, restarts on hang)
cp deploy/launchd/com.spy_auto_trader.watchdog.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.spy_auto_trader.watchdog.plist

# Recommended: keep the Mac awake (idle sleep freezes stop-loss monitoring)
cp deploy/launchd/com.alpacatrader.caffeinate.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.alpacatrader.caffeinate.plist

# Optional: standalone charts-only server (:5001)
cp deploy/launchd/com.alpacatrader.charts.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.alpacatrader.charts.plist

# Optional: Polygon 5yr archival loop (UNLOAD after 2026-06-16 — sub expires)
cp deploy/launchd/com.alpacatrader.polygon.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.alpacatrader.polygon.plist
```

The plists reference absolute paths to the venv Python and the project root.
If your project lives elsewhere, edit the plists before copying.

To unload / check status of any agent:

```bash
launchctl unload ~/Library/LaunchAgents/<label>.plist
launchctl list | grep -E "alpacatrader|spy_auto_trader"   # PID + last exit code
```

### 4. Verify

```bash
# Main app — should return status: ok and logged_in: true
curl -s http://localhost:5000/health

# Charts server — should return status: ok
curl -s http://localhost:5001/health

# Open the dashboard and the charts page
open http://localhost:5000
open http://localhost:5001/charts
```

---

## Updating after a code change

Pull / edit → reload the agent:

```bash
launchctl unload ~/Library/LaunchAgents/com.alpacatrader.plist
launchctl load   ~/Library/LaunchAgents/com.alpacatrader.plist
sleep 12   # allow _auto_login to complete
curl -s http://localhost:5000/health
```

You do NOT need to copy the plist again unless you edited the plist itself.

---

## Logs

| File | Written by | Purpose |
|------|-----------|---------|
| `/tmp/alpacatrader.out.log` | launchd `StandardOutPath` | Server stdout (`print` calls, eventlet WSGI) |
| `/tmp/alpacatrader.err.log` | launchd `StandardErrorPath` | Server stderr (uncaught exceptions, tracebacks) |
| `/tmp/alpacatrader.watchdog.log` | `scripts/watchdog.sh` | Health-check decisions, kill events |
| `spy_trader.log` (project root) | Python `RotatingFileHandler` | Main application log (10MB × 5 rotation) |
| `security.log` (project root) | `security_log` handler | Login attempts, auth failures (5MB × 3 rotation) |
| `errors.log` (project root) | dedicated error handler | ERROR-level only, easier to grep |

For ad-hoc tailing:

```bash
tail -f /tmp/alpacatrader.out.log
tail -f spy_trader.log
```

---

## Stopping permanently

Unload and remove every agent you installed:

```bash
for a in com.alpacatrader com.alpacatrader.charts com.alpacatrader.caffeinate \
         com.alpacatrader.polygon com.spy_auto_trader.watchdog; do
  launchctl unload ~/Library/LaunchAgents/$a.plist 2>/dev/null
  rm -f ~/Library/LaunchAgents/$a.plist
done
```

The project files and `.env` stay intact — only the OS-level scheduling is
removed.

> Note: stop the **watchdog first** before stopping the app, or the watchdog
> will relaunch the app you just unloaded.
