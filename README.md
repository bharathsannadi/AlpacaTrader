# SPY Auto Trader

A Flask + SocketIO web dashboard for automated options day-trading using the [Alpaca](https://alpaca.markets) API (paper trading by default).

## Quick start

### Requirements
- Python 3.10+
- A free [Alpaca paper-trading account](https://app.alpaca.markets/signup) — grab your API key + secret from the dashboard

### Steps

```bash
# 1. Clone the repo
git clone https://github.com/bharathsannadi/AlpacaTrader.git
cd AlpacaTrader

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the app
python scripts/app.py
```

Open **http://localhost:5000**, enter your Alpaca API key and secret in the login modal, and click **Connect**.

> No `.env` file is needed — credentials are entered through the UI and never written to disk.

## Features

| Feature | Details |
|---------|---------|
| **Multi-symbol tabs** | SPY, AMZN, GOOG, MSFT, NVDA, META |
| **Morning session** | 9:30–10:00 ET — Opening Range Breakout + Gap Fade |
| **Evening session** | 3:00–3:30 ET — VWAP Momentum |
| **Auto-scheduler** | Sessions fire automatically at market open/close (toggle ON/OFF in UI) |
| **Indicators** | VWAP, EMA 9/21/200, RSI, MACD, Bollinger Bands, ATR |
| **Candlestick chart** | 1D / 5D / 1M / 3M / 1Y / 5Y timeframes |
| **Trade approval modal** | Audio beep + approve/skip before any order is placed |
| **Risk controls** | VIX filter, stop loss %, profit target %, DTE window, 0.5% account risk per trade |
| **Paper / Live toggle** | Defaults to Alpaca paper trading |
| **Drag-drop layout** | Panel positions saved to localStorage |
| **Sleep prevention** | Mac stays awake automatically during active sessions |

## Project structure

```
scripts/
  app.py               Flask + SocketIO server, state management, auto-scheduler
  spy_auto_trader.py   Trading logic, Alpaca API calls, indicator stack
  security.py          Login lockout, input validators, security headers
templates/
  index.html           Dashboard UI
static/
  main.js              Chart, approval modal, drag-drop persistence
  lightweight-charts.js  TradingView charting library
```

## Disclaimer

This project is for educational and paper-trading purposes. Trading options involves substantial risk. Never trade with money you cannot afford to lose.
