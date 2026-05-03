# SPY Auto Trader

A Flask + SocketIO web dashboard for automated options day-trading using the [Alpaca](https://alpaca.markets) API. Trades SPY, AMZN, GOOG, MSFT, NVDA, and META options with morning ORB + evening VWAP sessions, an LLM-powered bull/bear debate gate, ChromaDB trade memory, and a news pre-filter.

Paper trading is on by default — no real money at risk until you explicitly switch to live mode.

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| **Python 3.10 – 3.13** | 3.14 works but requires a workaround for `chromadb` (see below) |
| **Alpaca account** | Free paper-trading account at [app.alpaca.markets](https://app.alpaca.markets/signup) — grab your Paper API key + secret |
| **Git** | To clone the repo |
| **macOS / Linux** | Windows works but `caffeinate` (sleep prevention) is macOS-only and will be skipped |

**Optional — for the Bull/Bear debate feature:**
- An [Anthropic API key](https://console.anthropic.com) (`ANTHROPIC_API_KEY`) — uses Claude Haiku 4.5 (~$0.001 per signal check)

**Optional — for the news pre-filter feature:**
- A free [Finnhub API key](https://finnhub.io) (`FINNHUB_API_KEY`) — falls back to yfinance (no key needed) if omitted

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/bharathsannadi/AlpacaTrader.git
cd AlpacaTrader
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows
```

### 3. Install dependencies

**Python 3.10 – 3.13 (standard):**
```bash
pip install -r requirements.txt
```

**Python 3.14 — chromadb workaround** (`onnxruntime` has no 3.14 wheel yet):
```bash
pip install -r requirements.txt --ignore-requires-python || true
pip install chromadb --no-deps
pip install overrides typing_extensions pydantic posthog \
    opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc \
    grpcio httpx bcrypt build importlib-resources jsonschema mmh3 orjson \
    pybase64 "pydantic-settings>=2.0" pypika pyyaml tenacity tokenizers \
    tqdm typer "uvicorn[standard]"
```

> The app uses a custom numpy-based embedder for chromadb, so `onnxruntime` is not needed at runtime.

### 4. (Optional) Create a `.env` file

Create a `.env` file in the project root to enable optional features:

```env
# Required only for the Bull/Bear debate gate (Feature 3)
ANTHROPIC_API_KEY=sk-ant-...

# Required only for the Finnhub news pre-filter (falls back to yfinance if absent)
FINNHUB_API_KEY=your_key_here
```

Alpaca credentials are entered through the login UI and are never written to disk.

---

## Running the server

```bash
source venv/bin/activate
python scripts/app.py
```

Open **[http://localhost:5000](http://localhost:5000)** in your browser.

The server binds to `127.0.0.1` (localhost only) — it is not reachable from other machines by default. Two log files are written to the project root: `spy_trader.log` and `security.log`.

---

## First login

1. Open [http://localhost:5000](http://localhost:5000)
2. Enter your **Alpaca Paper API Key** and **API Secret** in the login modal
3. Leave **Paper mode** toggled ON (default)
4. Click **Connect**

The dashboard will show your account equity, buying power, and live prices once connected.

---

## Configuration

All settings are adjustable from the dashboard UI without restarting the server.

### Trading parameters (Config card)

| Setting | Default | Description |
|---------|---------|-------------|
| **VIX max** | 30 | Sessions are skipped if VIX is above this level |
| **Stop loss** | 50% | Exit if option premium drops by this % |
| **Profit target** | 75% | Exit when option premium gains this % |
| **DTE min / max** | 7 / 14 | Days-to-expiry window for option selection |
| **Morning end** | 10:00 ET | Morning session cutoff time |
| **Evening end** | 15:30 ET | Evening session cutoff time |

### Intelligence toggles (Auto-schedule card)

| Toggle | Default | Description |
|--------|---------|-------------|
| **Auto-schedule** | ON | Automatically starts morning (9:30 ET) and evening (3:00 ET) sessions on weekdays |
| **News filter** | ON | Vetoes a session if bearish headlines are detected before it starts |
| **Trade memory** | ON | Surfaces similar past setups (ChromaDB) before each signal fires |
| **Bull/Bear debate** | OFF | Runs a 3-call LLM debate (bull agent → bear agent → judge) before placing any order. Requires `ANTHROPIC_API_KEY` in `.env` |

### Dry run vs live trading

- **Dry run ON** (default): signals fire, the approval modal appears, but no orders are submitted to Alpaca
- **Dry run OFF**: real paper orders are placed after you approve the modal
- Switch to **live mode** in the login modal only when you are ready to trade real money

---

## Features

| Feature | Details |
|---------|---------|
| **Multi-symbol tabs** | SPY, AMZN, GOOG, MSFT, NVDA, META |
| **Morning session** | 9:30–10:00 ET — Opening Range Breakout + Gap Fade |
| **Evening session** | 3:00–3:30 ET — VWAP Momentum |
| **Auto-scheduler** | Sessions fire automatically at market open/close |
| **Indicators** | VWAP, EMA 9/21/200, RSI, MACD, Bollinger Bands, ATR |
| **Candlestick chart** | 1D / 5D / 1M / 3M / 1Y / 5Y timeframes with signal markers |
| **Trade approval modal** | Audio beep + approve/skip before any order is placed |
| **Risk controls** | VIX filter, stop loss, profit target, DTE window, 0.5% account risk per trade |
| **News pre-filter** | Finnhub / yfinance headline scan vetoes sessions on bad news |
| **Trade memory** | ChromaDB stores past trade outcomes; retrieves similar setups as context |
| **Bull/Bear debate** | Three Claude Haiku calls gate each signal with a confidence score |
| **Paper / Live toggle** | Defaults to Alpaca paper trading |
| **Drag-drop layout** | Panel positions saved to localStorage |
| **Sleep prevention** | Mac stays awake automatically during active sessions (caffeinate) |

---

## Project structure

```
scripts/
  app.py               Flask + SocketIO server, state management, auto-scheduler
  spy_auto_trader.py   Trading logic, Alpaca API calls, indicator stack
  security.py          Login lockout, input validators, security headers
  news_filter.py       Finnhub / yfinance headline scan → veto flag
  trade_memory.py      ChromaDB trade memory with custom numpy embedder
  debate.py            Bull/Bear LLM debate layer (Claude Haiku)
templates/
  index.html           Dashboard UI
static/
  main.js              Chart, approval modal, drag-drop persistence
  lightweight-charts.js  TradingView charting library
```

---

## Troubleshooting

**Port 5000 already in use:**
```bash
lsof -ti:5000 | xargs kill -9
python scripts/app.py
```

**Chart shows no data / 0 bars:**
The app tries Alpaca feeds in order (IEX → SIP → default → yfinance). Check `spy_trader.log` for `"returned 0 bars"` lines. If all Alpaca feeds fail, yfinance is used as a final fallback.

**Session never triggers a signal:**
Common causes: VIX above max, volume ratio below 1.5×, RSI in oversold/overbought zone, or the news filter vetoed the session. Check `spy_trader.log` for details.

**Bull/Bear debate toggle has no effect:**
Requires `ANTHROPIC_API_KEY` set in `.env`. The toggle will show ON in the UI but `init_debate()` logs a warning and leaves the gate disabled if the key is missing.

**Login fails after several attempts:**
The security layer locks out an IP for 15 minutes after 5 failed login attempts. Wait 15 minutes or restart the server to clear the lockout.

---

## Disclaimer

This project is for educational and paper-trading purposes only. Trading options involves substantial risk of loss. Never trade with money you cannot afford to lose.
