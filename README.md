# SPY Auto Trader

A Flask + SocketIO web dashboard for automated options day-trading using the [Alpaca](https://alpaca.markets) API (paper trading by default).

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your Alpaca API key + secret
python app.py
```

Open **http://localhost:5000** and enter your Alpaca API credentials to connect.

## Features

| Feature | Details |
|---------|---------|
| **Multi-symbol tabs** | SPY, AMZN, GOOG, MSFT, NVDA, META |
| **Morning session** | 9:30–10:00 ET — Opening Range Breakout + Gap Fade |
| **Evening session** | 3:00–3:30 ET — VWAP Momentum |
| **Indicators** | VWAP, EMA 9/21/200, RSI, MACD, Bollinger Bands, ATR |
| **Candlestick chart** | 1D / 5D / 1M / 3M / 1Y / 5Y timeframes (lightweight-charts) |
| **Trade approval modal** | Audio beep + approve/skip before any order is placed |
| **Risk controls** | VIX filter, stop loss %, profit target %, DTE window, 0.5% account risk per trade |
| **Paper / Live toggle** | Defaults to Alpaca paper trading |
| **Drag-drop layout** | Panel positions saved to localStorage |

## Project structure

```
app.py               Flask + SocketIO server, state management, WS auth
spy_auto_trader.py   Trading logic, Alpaca API calls, indicator stack
security.py          Login lockout, input validators, security headers
templates/index.html Dashboard UI
static/main.js       Chart, approval modal, drag-drop persistence
static/lightweight-charts.js  TradingView charting library
```

## Environment variables (`.env`)

| Variable | Description |
|----------|-------------|
| `ALPACA_API_KEY` | Alpaca API key (optional — can enter in UI) |
| `ALPACA_API_SECRET` | Alpaca API secret (optional — can enter in UI) |
| `SECRET_KEY` | Flask session key (auto-generated on first run) |

## Disclaimer

This project is for educational and paper-trading purposes. Trading options involves substantial risk. Never trade with money you cannot afford to lose.
