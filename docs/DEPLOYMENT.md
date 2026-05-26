# Deployment

How the AlpacaTrader server runs on a developer Mac. The same setup would work
on a server / cloud VM with minor path adjustments.

---

## Topology

```
┌─────────────────────────┐
│ launchd                 │  user-level agent ~/Library/LaunchAgents/
│  • com.alpacatrader     │──── auto-starts on login + restarts on crash
│  • com.spy_auto_trader  │──── watchdog: kills app if /health fails 3×
│    .watchdog            │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│ scripts/app.py          │  Flask + Socket.IO on 127.0.0.1:5000
│  • _auto_login()        │  reads ALPACA_AUTO_* from .env, connects
│  • price_ticker         │  every 5s
│  • scheduler            │  every 15s — sessions, EOD, screener refresh
│  • position_monitor     │  every 10s — stop-loss/target execution
└──────────┬──────────────┘
           │
           ▼  HTTPS API + WebSocket
┌─────────────────────────┐
│ Alpaca paper trading    │  https://paper-api.alpaca.markets
└─────────────────────────┘
```

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

### 3. Install the launchd agent

```bash
cp deploy/launchd/com.alpacatrader.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.alpacatrader.plist
```

The plist references absolute paths to the venv Python and the project root.
If your project lives elsewhere, edit the plist before copying.

### 4. (Optional) Install the watchdog

```bash
cp com.spy_auto_trader.watchdog.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.spy_auto_trader.watchdog.plist
```

The watchdog polls `http://localhost:5000/health` every minute and `pkill`s
the app process if it returns 503 or times out 3 consecutive times. launchd
then restarts it automatically (`KeepAlive: true`).

### 5. Verify

```bash
# Should return status: ok and logged_in: true
curl -s http://localhost:5000/health

# Open the dashboard
open http://localhost:5000
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

```bash
launchctl unload ~/Library/LaunchAgents/com.alpacatrader.plist
launchctl unload ~/Library/LaunchAgents/com.spy_auto_trader.watchdog.plist
rm ~/Library/LaunchAgents/com.alpacatrader.plist
rm ~/Library/LaunchAgents/com.spy_auto_trader.watchdog.plist
```

The project files and `.env` stay intact — only the OS-level scheduling is
removed.
