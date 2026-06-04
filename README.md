# SPY Auto Trader

> ⚠️ **Honest status (2026-05-19):** this began as the options day-trader described below. After ~$108 of real Polygon data and rigorous backtesting, **no validated edge exists** for that strategy: naked options disproven (PF 0.92), intraday shares marginal/cost-fragile (PF 1.09@3bp, dies@5bp), Tier-1 (H-REGIME+H-RUN+vol-universe) and Tier-2 (Connors) both failed/inapplicable in the intraday frame. **System is in advisory/research mode; no real-money trading is approved on any symbol.** What it now is: a pro-grade validation apparatus, a codified knowledge base ([knowledge_base.md](knowledge_base.md), 12 sections + 9 master entries), and a permanent 4.2 GB Polygon stock cache covering the S&P 500. The decision fork ahead is **frame-shift to daily bars (Path A) or stop and accept as research (Path B)** — see [CONTEXT.md](CONTEXT.md) and [ANALYSIS_LOG.md](ANALYSIS_LOG.md) 2026-05-19 strategic synthesis.

A Flask + SocketIO web dashboard for automated options day-trading using the [Alpaca](https://alpaca.markets) API. *(As-built; not currently auto-trading — see status above.)* Trades SPY, AMZN, GOOG, MSFT, NVDA, and META options with an all-day session combining ORB + VWAP momentum + trend continuation + mean reversion strategies, an LLM-powered bull/bear debate gate (28-book knowledge base), ChromaDB trade memory, news pre-filter, and full position persistence with two-way Alpaca reconcile across restarts.

Paper trading is on by default — no real money at risk until you explicitly switch to live mode. Also ships as a native macOS app bundle (`SPY Auto Trader.app`).

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

The server binds to `127.0.0.1` (localhost only) — it is not reachable from other machines by default. Two log files are written to the project root: `auto_trader.log` and `security.log`.

**Charts-only server (port 5001):** a decoupled, login-free charts server runs
separately at **[http://localhost:5001/charts](http://localhost:5001/charts)**
(`scripts/charts_server.py`, yfinance data, no Alpaca login). Start it directly
with `python scripts/charts_server.py`, or let launchd manage it (see
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)). The main app uses **:5000**, the
charts server uses **:5001**.

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

### Trading parameters (Settings → Configuration card)

| Setting | Default | Description |
|---------|---------|-------------|
| **VIX max** | 30 | Sessions are skipped if VIX is above this level |
| **Stop loss** | 40% | Exit if option premium drops by this % |
| **Profit target** | 100% (T2) | T1 partial close at +50%, T2 full close at +100% |
| **DTE min / max** | 7 / 14 | Days-to-expiry window for option selection |
| **Session end** | 15:45 ET | All-day session cutoff time |
| **Risk per trade** | 0.5% | Per-trade risk sizing |

### Intelligence toggles (Settings → Automation card)

| Toggle | Default | Description |
|--------|---------|-------------|
| **Auto-schedule** | ON | Automatically starts all-day sessions for every symbol at 9:30 ET on weekdays. Retries any symbol not running on every scheduler tick. |
| **News filter** | ON | Vetoes a session if bearish headlines are detected before it starts |
| **Trade memory** | ON | Surfaces similar past setups (ChromaDB) before each signal fires |
| **Bull/Bear debate** | ON | Runs a 3-call LLM debate (bull agent → bear agent → judge) before placing any order. Requires `ANTHROPIC_API_KEY` in `.env`. Knowledge base distilled from 28 options trading books is injected into prompts. |
| **Auto-trade** | ON | Skip the approval modal — fire approved signals immediately |

### Dry run vs live trading

- **Dry run** (default ON, operator directive 2026-05-31): second-layer safety on top of paper mode — no order is sent at all. Combined with the armed-by-default Auto-Execute + the KB-principles/debate gate, this means the system evaluates and logs "would-have-been" trades without placing anything until you explicitly turn dry-run off.
- **Paper mode** (default ON): real Alpaca paper orders, no real money. **This is the intended operating mode.**
- Switch to **live mode** in the login modal only when you are ready to trade real money — and only after the readiness gates in `TODO.md` 🎯-P3 pass.

---

## Features

| Feature | Details |
|---------|---------|
| **Merged KB-driven picks** (NEW 2026-06-04) | "Shown == traded." The screener is ONE KB-ranked pick list (`data["picks"]`, built by `app._build_picks`, flag `MERGED_PICKS_ENABLED = True`) that drives BOTH the UI display and both auto-exec lanes. Each symbol is ROUTED to stock OR option (`router.route_for_pick`, KB §5/§2) and trades once via its route. Ranking is by KB-match descending. New **⭐ Picks** tab (primary), legacy Stocks/Options tabs kept. Flip the flag to `False` for the old two-list behavior. |
| **Equal-dollar sizing** (NEW 2026-06-04) | Options are sized to as many contracts as fit ~$600 (`qty = OPT_HARD_MAX_USD // per_contract_cost` in `execute_screener_option`); stocks to ~$5000/position (`app._stock_qty_for`, `STOCK_TARGET_USD = 5000`). Supersedes fixed-10-shares / fixed-1-contract. |
| **Tab-based UI** | ⚙ Settings (default) · ⭐ Picks (primary) · Stocks / Options · SPY/AMZN/GOOG/MSFT/NVDA/META (full-screen charts) · 📊 Backtest · 📋 Log (closed trades now appear here as `CLOSED` / `OPTION EXIT` lines — the old Notes/Closed-Trades panel is retired) |
| **All-day session** | 9:30–15:45 ET — ORB breakout + Gap fade + VWAP momentum + trend continuation + mean reversion |
| **Auto-scheduler** | All 6 symbols fire at market open. Retries any symbol not currently running on every poll. |
| **Indicators** | VWAP, EMA 9/21/200, RSI, MACD, Bollinger Bands, ATR |
| **Candlestick chart** | 1m / 5m / 15m / 30m / 1h / 1D bars · 1D / 5D / 1M / 3M / 1Y / 5Y ranges with signal markers |
| **Trade approval modal** | Audio beep + approve/skip (skipped when Auto-trade is ON) |
| **Risk controls** | VIX filter, stop loss (40%), T1 partial (50%) → T2 full (100%), breakeven ratchet at +30%, trailing stop after T1, DTE 7-14, 0.5% per-trade / 3% portfolio risk cap |
| **News pre-filter** | Finnhub / yfinance headline scan vetoes sessions on bad news |
| **Trade memory** | ChromaDB stores past trade outcomes (real + dry-run); retrieves similar setups as context |
| **Bull/Bear debate** | Three Claude Haiku calls (bull → bear → judge) gate each signal. 28-book knowledge base injected into prompts. Singleton client avoids file-descriptor exhaustion. |
| **Position persistence** | `_open_positions` persisted to `~/.spy_trader/open_positions.json` on every mutation. Two-way Alpaca reconcile on restart (adds orphans, removes stale). Manual `⟳ Sync Positions` button for on-demand resync. |
| **Backtest panel** | Interactive backtest UI: pick symbols + lookback (7-180d) → run + view edge metrics |
| **Option exit ladder** | Live option exits: +80% TP / −50% SL / 90-min stall time-stop (`screener_executor.OPT_TAKE_PROFIT_PCT` / `OPT_STOP_LOSS_PCT` / `OPT_STALL_MINUTES`, applied in `_manage_option_positions`). Optional dynamic stop (breakeven+trail via exit_engine) behind `OPT_DYNAMIC_EXIT_ENABLED` (default OFF). |
| **§9 liquidity ranking** | `kb_principles.score_option_candidate` hard-floors a confirmed-illiquid contract below the 60% KB gate (one-sided gate) so illiquid picks never rank or show as a top BUY. |
| **Native macOS app** | `SPY Auto Trader.app` bundle with gradient bar-chart icon. Install to `/Applications`. |
| **Paper / Live toggle** | Defaults to Alpaca paper trading |
| **Emergency flatten-all** | One-click confirmation modal closes every open position immediately |
| **Sleep prevention** | Mac stays awake automatically during active sessions (caffeinate) |

---

## Project structure

```
CLAUDE.md              Claude Code agent guidance — read this first if editing
.env.example           Documented credential template (copy to .env, chmod 600)

scripts/
  app.py               Flask + SocketIO server, state, _build_picks, _auto_login
  spy_auto_trader.py   Trading logic, Alpaca API calls, indicator stack
  daily_trader.py      Connors RSI(2) daily-bar strategy
  screener_engine.py   Multi-strategy live screener
  screener_executor.py Options order placement + caps/exit constants (manual + auto)
  router.py            KB §5/§2 stock-vs-option route_for_pick
  risk_brain.py        Sleeves / caps / sizing (OPT_PER_TRADE_MAX_USD, OPT_WEEK_MAX_USD)
  kb_principles.py     KB scoring + §9 liquidity floor + calibrate() seam
  charts_server.py     Standalone charts-only server, port 5001 (yfinance, no login)
  watchdog.sh          Health-check watchdog — monitors :5000 AND :5001
  poly_keepalive.sh    Polygon 5yr archival keep-alive loop (→ poly_watchdog.sh)
  security.py          Login lockout, input validators, security headers
  news_filter.py       Finnhub / yfinance headline scan → veto flag
  trade_memory.py      ChromaDB trade memory with custom numpy embedder
  debate.py            Bull/Bear LLM debate layer (Claude Haiku)

templates/index.html   Dashboard UI (single template; ⭐ Picks tab)
static/main.js         Chart, screener, picks, backtest, approval modal

docs/
  README.md            Index of operational docs
  DEPLOYMENT.md        First-time setup, the 5 launchd agents, ports 5000/5001
  AUTO_EXECUTE.md      Merged picks, caps, equal-dollar sizing, safety rails
  RUNBOOK.md           Daily ops, troubleshooting, "why isn't it trading?"

deploy/launchd/        launchd plist templates, under version control — 5 agents:
                       com.alpacatrader (app :5000), .charts (:5001), .caffeinate,
                       .polygon, and com.spy_auto_trader.watchdog

data/                  Runtime state (gitignored) — auto_exec_state.json etc.
```

---

## Headless trading (NEW)

The server can now auto-start at machine boot and trade options without any
browser interaction:

1. `_auto_login` reads `ALPACA_AUTO_*` from `.env` and connects to Alpaca on startup
2. The screener auto-refreshes every 90s during market hours and rebuilds the
   merged KB-ranked pick list (`_build_picks`)
3. If **Auto-Execute** is armed (Settings → Automation), the merged picks are
   auto-placed via their route (stock or option) through `screener_executor`,
   respecting (all reconciled to "same as paper" 2026-06-04):
   - Options: **$600** HARD ceiling per trade for ALL options *including ETFs*
     (`screener_executor.OPT_HARD_MAX_USD` / `OPT_HARD_MAX_USD_ETF`); sized to
     as many contracts as fit ~$600 (equal-dollar)
   - Stocks: sized to ~**$5000**/position (`STOCK_TARGET_USD`)
   - **5** orders per day cap (`MAX_AUTO_EXEC_PER_DAY`)
   - **5** concurrent option positions (`OPT_MAX_OPEN`)
   - Rolling-week **$3000** options cap / per-trade **$600**
     (`risk_brain.OPT_WEEK_MAX_USD` / `OPT_PER_TRADE_MAX_USD`)
   - One execution per symbol per day (persisted across restarts)
   - 2% daily loss circuit breaker (auto-disarms on breach)
   - Naked-leg rollback if a debit-spread STO fails

Full details in [`docs/AUTO_EXECUTE.md`](docs/AUTO_EXECUTE.md). Default is
disarmed — you have to click the button in the UI to enable it.

---

## Troubleshooting

**Port 5000 already in use:**
```bash
lsof -ti:5000 | xargs kill -9
python scripts/app.py
```

**Chart shows no data / 0 bars:**
The app tries Alpaca feeds in order (IEX → SIP → default → yfinance). Check `auto_trader.log` for `"returned 0 bars"` lines. If all Alpaca feeds fail, yfinance is used as a final fallback.

**Session never triggers a signal:**
Common causes: VIX above max, volume ratio below 1.5×, RSI in oversold/overbought zone, or the news filter vetoed the session. Check `auto_trader.log` for details.

**Bull/Bear debate toggle has no effect:**
Requires `ANTHROPIC_API_KEY` set in `.env`. The toggle will show ON in the UI but `init_debate()` logs a warning and leaves the gate disabled if the key is missing.

**Login fails after several attempts:**
The security layer locks out an IP for 15 minutes after 5 failed login attempts. Wait 15 minutes or restart the server to clear the lockout.

---

## Disclaimer

This project is for educational and paper-trading purposes only. Trading options involves substantial risk of loss. Never trade with money you cannot afford to lose.
