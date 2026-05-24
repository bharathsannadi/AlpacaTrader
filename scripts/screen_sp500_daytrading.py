#!/usr/bin/env python3.11
"""
screen_sp500_daytrading.py — Rank S&P 500 stocks for day-trading suitability.

Criteria synthesised from 8 day-trading books:
  • Aziz  "Advanced Techniques in Day Trading"  — Stocks in Play = high relative vol
  • Elder "Come Into My Trading Room"           — high ADV + volatility + price ≥ $20
  • O'Neil Disciple                             — ≥ 350K–500K ADV, prefer millions;
                                                  mid-to-large-cap, institutional quality
  • Livermore  "Trade Like Jesse Livermore"     — leaders of leading industry groups only
  • "A Complete Guide to Day Trading"           — ~600 S&P names trade > 3M shares/day
  • "Master Traders"                            — high-beta sectors: tech/semis/biotech/energy
  • "Trades About to Happen" (Wyckoff)          — price/volume clarity, smooth movers
  • "High Probability Short-Term Trading"       — volatility extremes, ATR expansion

Hard filters (all must pass):
  ADV_30   ≥ 3,000,000 shares/day   (3M — roughly top 600 S&P names)
  ATR_PCT  ≥ 1.5%  average daily range / price (decent intraday room)
  PRICE    ≥ $20   (Elder: "expensive rather than cheap for intraday range")
  MCAP     ≥ $5 B  (institutional quality, tight spreads)

Score (0–100):
  30 pts  ADV          (log-scaled; 3M → 0 pts, 100M+ → 30 pts)
  25 pts  Dollar ATR   (= price × ATR%; 0.50 → 0, $6+ → 25)
  20 pts  ATR%         (1.5% → 0, 4%+ → 20)
  15 pts  Beta         (≥ 1.2 scores; 2.5 = 15 pts)
  10 pts  Sector bonus (tech/semis/biotech/energy/financials → 10)

Output:
  Ranked table printed to stdout + saved to
  ~/Desktop/bharath/AlpacaTrader_Data/daytrading_screen_<date>.csv

Usage:
  venv/bin/python3.11 scripts/screen_sp500_daytrading.py
  venv/bin/python3.11 scripts/screen_sp500_daytrading.py --top 20
  venv/bin/python3.11 scripts/screen_sp500_daytrading.py --min-adv 5000000
"""
from __future__ import annotations
import sys
import math
import argparse
import warnings
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore")

import pandas as pd
import yfinance as yf

# ── output dir ────────────────────────────────────────────────────────────────
OUT_DIR = Path.home() / "Desktop" / "bharath" / "AlpacaTrader_Data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── hard filter defaults (override via CLI) ───────────────────────────────────
DEFAULT_MIN_ADV   = 3_000_000   # shares / day
DEFAULT_MIN_ATR   = 1.5         # % of price
DEFAULT_MIN_PRICE = 20.0        # USD
DEFAULT_MIN_MCAP  = 5_000_000_000  # $5 B

# ── sector bonus mapping ──────────────────────────────────────────────────────
BONUS_SECTORS = {
    "Technology", "Information Technology", "Semiconductors",
    "Semiconductor Equipment", "Software", "Internet",
    "Health Care", "Biotechnology", "Pharmaceuticals",
    "Energy", "Oil, Gas & Consumable Fuels",
    "Financials", "Financial Services", "Banks",
    "Consumer Discretionary", "Industrials",
}

# ── S&P 500 constituents ──────────────────────────────────────────────────────
def sp500_tickers() -> list[str]:
    """Fetch live S&P 500 list from Wikipedia (with browser User-Agent)."""
    try:
        import io
        req = __import__("urllib.request", fromlist=["Request", "urlopen"])
        request = req.Request(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                   "AppleWebKit/537.36 Chrome/124 Safari/537.36"}
        )
        with req.urlopen(request, timeout=20) as r:
            html = r.read().decode("utf-8", errors="replace")
        tables = pd.read_html(io.StringIO(html))
        df = tables[0]
        col = next(c for c in df.columns if "ticker" in c.lower() or "symbol" in c.lower())
        tickers = df[col].str.replace(".", "-", regex=False).tolist()
        tickers = [t.strip() for t in tickers if isinstance(t, str) and t.strip()]
        print(f"[info] Wikipedia: {len(tickers)} S&P 500 tickers loaded")
        return tickers
    except Exception as e:
        print(f"[warn] Wikipedia fetch failed ({e}), falling back to hardcoded list")
        return _hardcoded_sp500()


def _hardcoded_sp500() -> list[str]:
    """Emergency fallback: top 100 liquid S&P 500 names by ADV."""
    return [
        "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","AVGO","GOOG","BRK-B",
        "JPM","LLY","V","UNH","XOM","MA","COST","HD","PG","NFLX",
        "BAC","ABBV","CRM","AMD","KO","MRK","CVX","ACN","PEP","TMO",
        "ORCL","CSCO","ABT","ADBE","WMT","MCD","CAT","TXN","GE","HON",
        "QCOM","IBM","GS","AMGN","NOW","SPGI","BKNG","MS","LOW","UPS",
        "DIS","INTC","AMAT","ISRG","BMY","PFE","DE","MDT","MMC","RTX",
        "LIN","AXP","PM","MU","LRCX","ELV","CB","KLAC","REGN","ADI",
        "SYK","CI","SO","DUK","CMG","APH","MDLZ","VRTX","ZTS","BSX",
        "PANW","SNPS","MCK","ICE","EOG","PLD","COP","CDNS","WM","ITW",
        "NOC","ETN","CME","MSI","HUM","MCHP","PAYX","OKE","PSX","FTNT",
    ]


# ── per-ticker metric fetch ───────────────────────────────────────────────────
def fetch_metrics(ticker: str) -> dict | None:
    """Pull 60-day daily history + info for one ticker. Returns None on error."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="60d", interval="1d", auto_adjust=True, actions=False)
        if hist is None or len(hist) < 15:
            return None

        # --- volume ---
        adv = float(hist["Volume"].tail(30).mean())

        # --- ATR (True Range % of close) ---
        close = hist["Close"]
        high  = hist["High"]
        low   = hist["Low"]
        prev  = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev).abs(),
            (low  - prev).abs(),
        ], axis=1).max(axis=1)
        atr14  = float(tr.tail(14).mean())
        price  = float(close.iloc[-1])
        atr_pct = (atr14 / price) * 100.0 if price > 0 else 0.0

        # --- dollar ATR (how many dollars it moves per day) ---
        dollar_atr = atr14

        # --- info dict (best-effort) ---
        info   = {}
        try:
            info = t.info or {}
        except Exception:
            pass

        mcap   = info.get("marketCap") or info.get("market_cap") or 0
        beta   = info.get("beta") or 1.0
        sector = info.get("sector") or info.get("industry") or ""
        name   = info.get("shortName") or info.get("longName") or ticker

        return {
            "ticker":     ticker,
            "name":       name,
            "price":      round(price, 2),
            "adv_30":     int(adv),
            "atr14":      round(atr14, 2),
            "atr_pct":    round(atr_pct, 2),
            "dollar_atr": round(dollar_atr, 2),
            "beta":       round(float(beta), 2),
            "mcap_b":     round(mcap / 1e9, 1),
            "sector":     sector,
            "name":       name,
        }
    except Exception:
        return None


# ── scoring ───────────────────────────────────────────────────────────────────
def score_row(r: dict) -> float:
    """
    Score 0–100 based on 4 quantitative dimensions + sector bonus.

    ADV          30 pts  log-scale: log10(3M)=6.48 → 0, log10(100M)=8 → 30
    Dollar ATR   25 pts  $0.50 → 0, $6 → 25 (capped)
    ATR%         20 pts  1.5% → 0, 4% → 20 (capped)
    Beta         15 pts  1.0 → 0, 2.5 → 15 (capped; negative beta = 0)
    Sector bonus 10 pts  tech/semis/biotech/energy/financials
    """
    adv_score = 0.0
    adv = r["adv_30"]
    if adv > 0:
        lo, hi = math.log10(3_000_000), math.log10(100_000_000)
        adv_score = min(30.0, max(0.0, (math.log10(adv) - lo) / (hi - lo) * 30))

    datr_score = min(25.0, max(0.0, (r["dollar_atr"] - 0.50) / (6.0 - 0.50) * 25))

    atr_score  = min(20.0, max(0.0, (r["atr_pct"] - 1.5) / (4.0 - 1.5) * 20))

    beta = max(0.0, float(r["beta"]))
    beta_score = min(15.0, max(0.0, (beta - 1.0) / (2.5 - 1.0) * 15))

    sector_score = 10.0 if any(s.lower() in r["sector"].lower()
                                for s in BONUS_SECTORS) else 0.0

    return round(adv_score + datr_score + atr_score + beta_score + sector_score, 1)


# ── main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    p = argparse.ArgumentParser(description="Screen S&P 500 stocks for day trading")
    p.add_argument("--top",      type=int,   default=40,
                   help="Print top N results (default 40)")
    p.add_argument("--min-adv",  type=float, default=DEFAULT_MIN_ADV,
                   help="Min avg daily volume (default 3,000,000)")
    p.add_argument("--min-atr",  type=float, default=DEFAULT_MIN_ATR,
                   help="Min ATR%% (default 1.5)")
    p.add_argument("--min-price",type=float, default=DEFAULT_MIN_PRICE,
                   help="Min price USD (default 20)")
    p.add_argument("--min-mcap", type=float, default=DEFAULT_MIN_MCAP / 1e9,
                   help="Min market cap $B (default 5)")
    args = p.parse_args()

    print("=" * 70)
    print("  S&P 500 Day-Trading Screener")
    print("  Criteria: Books — Aziz, Elder, O'Neil, Livermore, Wyckoff +3 more")
    print(f"  Filters : ADV≥{args.min_adv/1e6:.1f}M  ATR%≥{args.min_atr}%  "
          f"Price≥${args.min_price}  MCap≥${args.min_mcap:.0f}B")
    print("=" * 70)

    tickers = sp500_tickers()
    print(f"\nUniverse: {len(tickers)} S&P 500 tickers  |  fetching data (≈2–4 min)…\n")

    rows: list[dict] = []
    failed = 0
    for i, sym in enumerate(tickers, 1):
        m = fetch_metrics(sym)
        if m is None:
            failed += 1
            continue
        # hard filters
        if m["adv_30"]  < args.min_adv:   continue
        if m["atr_pct"] < args.min_atr:   continue
        if m["price"]   < args.min_price:  continue
        if m["mcap_b"]  < args.min_mcap:   continue
        m["score"] = score_row(m)
        rows.append(m)
        if i % 50 == 0:
            print(f"  … processed {i}/{len(tickers)} tickers  ({len(rows)} pass filters so far)")

    if not rows:
        print("\n[!] No stocks passed the hard filters. Try relaxing --min-adv or --min-atr.")
        return

    df = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
    df.index = df.index + 1   # 1-based rank

    top = df.head(args.top)

    # ── pretty print ──────────────────────────────────────────────────────────
    print(f"\n{'Rank':<5} {'Sym':<7} {'Price':>7} {'ADV(M)':>8} {'ATR14':>6} "
          f"{'ATR%':>6} {'DolATR':>7} {'Beta':>5} {'MCap$B':>7} {'Score':>6}  Sector")
    print("-" * 100)
    for rank, row in top.iterrows():
        adv_m = row["adv_30"] / 1_000_000
        print(f"{rank:<5} {row['ticker']:<7} ${row['price']:>6.2f} {adv_m:>7.1f}M "
              f"{row['atr14']:>6.2f} {row['atr_pct']:>5.1f}% ${row['dollar_atr']:>5.2f} "
              f"{row['beta']:>5.2f} {row['mcap_b']:>6.1f}B {row['score']:>6.1f}  "
              f"{row['sector']}")
    print("-" * 100)
    print(f"\n  Passed filters: {len(df)}  |  Failed/no-data: {failed}  |  "
          f"Showing top {min(args.top, len(df))}")

    # ── save CSV ──────────────────────────────────────────────────────────────
    csv_path = OUT_DIR / f"daytrading_screen_{date.today()}.csv"
    df.to_csv(csv_path, index_label="rank")
    print(f"\n  Full ranked list saved → {csv_path}\n")

    # ── book-sourced rationale for top 10 ─────────────────────────────────────
    print("=" * 70)
    print("  TOP 10 — BOOK RATIONALE")
    print("=" * 70)
    for rank, row in top.head(10).iterrows():
        adv_m  = row["adv_30"] / 1_000_000
        rating = (
            "★★★★★" if row["score"] >= 85 else
            "★★★★☆" if row["score"] >= 70 else
            "★★★☆☆" if row["score"] >= 55 else
            "★★☆☆☆"
        )
        reasons = []
        if row["adv_30"] >= 20_000_000:
            reasons.append(f"elite liquidity ({adv_m:.0f}M ADV) — O'Neill §78")
        elif row["adv_30"] >= 5_000_000:
            reasons.append(f"high liquidity ({adv_m:.1f}M ADV) — O'Neill §78")
        if row["atr_pct"] >= 3.0:
            reasons.append(f"wide daily range ({row['atr_pct']:.1f}% ATR) — Elder p.212")
        elif row["atr_pct"] >= 2.0:
            reasons.append(f"good intraday range ({row['atr_pct']:.1f}% ATR)")
        if row["beta"] >= 1.5:
            reasons.append(f"high-beta ({row['beta']:.1f}x) — Master Traders p.44")
        if row["dollar_atr"] >= 4.0:
            reasons.append(f"${row['dollar_atr']:.2f} avg daily move — Aziz p.31")
        if any(s.lower() in row["sector"].lower() for s in
               {"technology","semiconductor","software","internet"}):
            reasons.append("leading tech/semi sector — Livermore p.47")
        elif any(s.lower() in row["sector"].lower() for s in
                 {"health","biotech","pharma"}):
            reasons.append("high-beta biotech/health sector — Master Traders p.44")
        elif "energy" in row["sector"].lower():
            reasons.append("high-beta energy sector — Master Traders p.44")

        print(f"\n#{rank} {row['ticker']:6s} {rating}  score={row['score']:.1f}")
        print(f"   {row['name']}")
        for r in reasons:
            print(f"   • {r}")

    print()


if __name__ == "__main__":
    main()
