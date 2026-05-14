#!/usr/bin/env python3.11
"""
EOD Journal generator — SPY Auto Trader
========================================
Run manually any time, or automatically after market close:

    venv/bin/python3.11 eod.py

Outputs:
    journals/YYYY-MM-DD.md   — today's journal entry
    ~/.spy_trader/equity_curve.json  — daily equity history (append-only)

Reads:
    ~/.spy_trader/open_positions.json   — positions still open
    ~/.spy_trader/equity_history.json   — intraday equity snapshots (from app)
    ~/Library/Logs/SPYAutoTrader/launcher.log  (or direct log path)
    .env for ALPACA_API_KEY / ALPACA_SECRET_KEY / ANTHROPIC_API_KEY
    Alpaca paper API for account state

No webapp changes required — runs standalone.
"""

from __future__ import annotations

import json
import os
import sys
import re
from datetime import datetime, date, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# ── Load .env manually (no python-dotenv dependency) ──────────────────────────
_REPO = Path(__file__).parent
_ENV_FILE = _REPO / ".env"

def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        if key:
            os.environ[key] = val

_load_env(_ENV_FILE)

ET = ZoneInfo("America/New_York")
TODAY = date.today().isoformat()

# ── Paths ─────────────────────────────────────────────────────────────────────
SPY_DIR        = Path.home() / ".spy_trader"
POSITIONS_FILE = SPY_DIR / "open_positions.json"
EQUITY_FILE    = SPY_DIR / "equity_history.json"
CURVE_FILE     = SPY_DIR / "equity_curve.json"
LOG_FILE       = Path.home() / "Library" / "Logs" / "SPYAutoTrader" / "launcher.log"
ALT_LOG        = _REPO / "logs" / "spy_trader.log"

JOURNALS_DIR   = _REPO / "journals"
JOURNALS_DIR.mkdir(exist_ok=True)
JOURNAL_PATH   = JOURNALS_DIR / f"{TODAY}.md"

# ── Alpaca client ─────────────────────────────────────────────────────────────
def _alpaca_account() -> dict:
    """Return account dict or empty dict on failure."""
    try:
        from alpaca.trading.client import TradingClient
        key    = os.environ.get("ALPACA_API_KEY", "")
        secret = os.environ.get("ALPACA_SECRET_KEY", "")
        if not key or not secret:
            return {}
        client = TradingClient(key, secret, paper=True)
        acct = client.get_account()
        return {
            "equity":          float(acct.equity or 0),
            "cash":            float(acct.cash or 0),
            "buying_power":    float(acct.buying_power or 0),
            "day_pnl":         float(acct.equity or 0) - float(acct.last_equity or 0),
            "last_equity":     float(acct.last_equity or 0),
            "daytrade_count":  int(getattr(acct, "daytrade_count", 0) or 0),
        }
    except Exception as e:
        print(f"[warn] Alpaca account fetch failed: {e}")
        return {}


# ── Open positions ────────────────────────────────────────────────────────────
def _load_open_positions() -> list[dict]:
    if not POSITIONS_FILE.exists():
        return []
    try:
        data = json.loads(POSITIONS_FILE.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


# ── Equity history → intraday drawdown ───────────────────────────────────────
def _intraday_stats() -> dict:
    """Return peak, trough, max_dd_pct from today's equity snapshots."""
    if not EQUITY_FILE.exists():
        return {}
    try:
        history = json.loads(EQUITY_FILE.read_text())
        today_snaps = [e for e in history if e.get("date", "") == TODAY]
        if not today_snaps:
            return {}
        equities = [e["equity"] for e in today_snaps if "equity" in e]
        if not equities:
            return {}
        peak   = max(equities)
        trough = min(equities)
        open_eq = equities[0]
        max_dd = (trough - peak) / peak * 100 if peak else 0.0
        return {"peak": peak, "trough": trough, "open_eq": open_eq,
                "max_dd_pct": max_dd, "snapshots": len(equities)}
    except Exception as e:
        print(f"[warn] equity history parse failed: {e}")
        return {}


# ── Append to equity curve ────────────────────────────────────────────────────
def _append_equity_curve(equity: float) -> None:
    curve: list = []
    if CURVE_FILE.exists():
        try:
            curve = json.loads(CURVE_FILE.read_text())
        except Exception:
            pass
    # replace today's entry if it already exists
    curve = [e for e in curve if e.get("date") != TODAY]
    curve.append({"date": TODAY, "equity": equity})
    curve.sort(key=lambda e: e["date"])
    SPY_DIR.mkdir(exist_ok=True)
    CURVE_FILE.write_text(json.dumps(curve, indent=2))


# ── Rolling drawdown from equity curve ───────────────────────────────────────
def _rolling_dd(days: int) -> float | None:
    if not CURVE_FILE.exists():
        return None
    try:
        curve = json.loads(CURVE_FILE.read_text())
        recent = sorted(curve, key=lambda e: e["date"])[-days:]
        if len(recent) < 2:
            return None
        equities = [e["equity"] for e in recent]
        peak = equities[0]
        worst = 0.0
        for eq in equities:
            peak = max(peak, eq)
            dd = (eq - peak) / peak * 100
            worst = min(worst, dd)
        return worst
    except Exception:
        return None


# ── Parse log for signal/gate counts ─────────────────────────────────────────
_LOG_PATTERNS = {
    "signal":    re.compile(r"bull_score|bear_score|ORB breakout"),
    "order":     re.compile(r"Placing (BUY|SELL) order"),
    "dry_run":   re.compile(r"\[DRY.?RUN\]", re.I),
    "iv_gate":   re.compile(r"IV.?rank.*blocked|IVR.*skip", re.I),
    "vol_gate":  re.compile(r"volume.*skip|vol.gate", re.I),
    "news_veto": re.compile(r"news.*block|news.*veto", re.I),
    "debate_no": re.compile(r"debate.*no|LLM.*no", re.I),
    "debate_ok": re.compile(r"debate.*proceed|LLM.*proceed", re.I),
    "stop":      re.compile(r"stop.?loss.*hit|stop.*trigger", re.I),
    "target1":   re.compile(r"T1.partial|target.1.*hit", re.I),
    "target2":   re.compile(r"T2.*hit|target.2.*hit", re.I),
    "hard_close":re.compile(r"hard.?close|time.?stop", re.I),
}

def _parse_log(log_path: Path) -> dict:
    counts = {k: 0 for k in _LOG_PATTERNS}
    if not log_path.exists():
        return counts
    today_str = TODAY  # "2026-05-13"
    try:
        for line in log_path.read_text(errors="replace").splitlines():
            if today_str not in line:
                continue
            for key, pat in _LOG_PATTERNS.items():
                if pat.search(line):
                    counts[key] += 1
    except Exception as e:
        print(f"[warn] log parse failed: {e}")
    return counts


# ── Closed trades from positions file (is_dry_run aware) ─────────────────────
# The app keeps trades_today in memory; we reconstruct what we can from
# the persisted positions + log. For a richer picture wire up a trades_today
# persistence file (future 📝-M item).
def _closed_trades_from_log(log_path: Path) -> list[dict]:
    """Best-effort: extract closed trade summaries from the log."""
    trades = []
    if not log_path.exists():
        return trades
    close_pat = re.compile(
        r"(?P<sym>[A-Z0-9]+)\s+(?P<dir>CALL|PUT).*"
        r"pnl[_\s]pct[=:]\s*(?P<pnl>[+-]?\d+\.?\d*)",
        re.I
    )
    reason_pat = re.compile(r"reason[=:]\s*(?P<reason>\w+)", re.I)
    today_str = TODAY
    try:
        for line in log_path.read_text(errors="replace").splitlines():
            if today_str not in line:
                continue
            m = close_pat.search(line)
            if m:
                t = {
                    "symbol":    m.group("sym"),
                    "direction": m.group("dir").lower(),
                    "pnl_pct":   float(m.group("pnl")),
                }
                rm = reason_pat.search(line)
                if rm:
                    t["reason"] = rm.group("reason")
                trades.append(t)
    except Exception:
        pass
    return trades


# ── R-multiple stats ──────────────────────────────────────────────────────────
def _trade_stats(trades: list[dict], stop_pct: float = 30.0) -> dict:
    closed = [t for t in trades if not t.get("is_partial")]
    if not closed:
        return {}
    wins   = [t for t in closed if t.get("pnl_pct", 0) > 0]
    loses  = [t for t in closed if t.get("pnl_pct", 0) < 0]
    n      = len(closed)
    win_r  = len(wins) / n * 100
    avg_w  = sum(t["pnl_pct"] for t in wins)  / len(wins)  if wins  else 0
    avg_l  = sum(t["pnl_pct"] for t in loses) / len(loses) if loses else 0
    gw     = sum(t["pnl_pct"] for t in wins)
    gl     = abs(sum(t["pnl_pct"] for t in loses))
    pf     = gw / gl if gl else float("inf")
    exp    = (win_r / 100) * avg_w + (1 - win_r / 100) * avg_l
    r_unit = stop_pct
    avg_r  = (sum(t["pnl_pct"] for t in closed) / n / r_unit) if r_unit else 0

    streak = max_streak = 0
    for t in closed:
        if t.get("pnl_pct", 0) < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    return {
        "n": n, "wins": len(wins), "losses": len(loses),
        "win_rate": win_r, "avg_win": avg_w, "avg_loss": avg_l,
        "gross_wins": gw, "gross_losses": gl,
        "profit_factor": pf, "expectancy": exp, "avg_r": avg_r,
        "max_losing_streak": max_streak,
    }


# ── LLM coaching insight ──────────────────────────────────────────────────────
def _llm_insight(plain_summary: str) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return "_[Set ANTHROPIC_API_KEY in .env to enable AI coaching insights]_"
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        prompt = (
            "You are a quantitative trading coach reviewing a day of automated SPY options trading.\n"
            "Given the stats below, provide exactly:\n"
            "1. What worked today (1-2 bullets)\n"
            "2. What didn't work (1-2 bullets)\n"
            "3. One concrete parameter to tweak tomorrow (name the constant + new value)\n"
            "4. One sentence on discipline / process (not outcomes)\n"
            "Be concise. No preamble. Use bullet points.\n\n"
            f"Stats:\n{plain_summary}"
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=350,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        return f"_[LLM call failed: {e}]_"


# ── Markdown builder ──────────────────────────────────────────────────────────
def _build_journal(
    acct: dict,
    open_pos: list[dict],
    closed_trades: list[dict],
    log_counts: dict,
    intraday: dict,
    five_dd: float | None,
    twenty_dd: float | None,
    stats: dict,
    insight: str,
) -> str:
    now_et = datetime.now(ET).strftime("%Y-%m-%d %H:%M ET")
    day_pnl = acct.get("day_pnl", 0)
    equity  = acct.get("equity", 0)
    last_eq = acct.get("last_equity", 0)
    day_pct = (day_pnl / last_eq * 100) if last_eq else 0

    pf = stats.get("profit_factor", 0)
    pf_str = "∞" if pf == float("inf") else f"{pf:.2f}"

    lines = [
        f"# Trading Journal — {TODAY}",
        f"_Generated: {now_et}_",
        "",
        "---",
        "",
        "## 📊 Account",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Equity | ${equity:,.2f} |",
        f"| Day P&L | ${day_pnl:+,.2f} ({day_pct:+.2f}%) |",
        f"| Cash | ${acct.get('cash', 0):,.2f} |",
        f"| Buying Power | ${acct.get('buying_power', 0):,.2f} |",
        f"| Day Trades Used | {acct.get('daytrade_count', '?')} / 3 PDT |",
    ]

    if intraday:
        lines += [
            f"| Intraday Max DD | {intraday.get('max_dd_pct', 0):.2f}% |",
            f"| Intraday Peak | ${intraday.get('peak', 0):,.2f} |",
        ]
    if five_dd is not None:
        lines.append(f"| 5-Day Rolling DD | {five_dd:.2f}% |")
    if twenty_dd is not None:
        lines.append(f"| 20-Day Rolling DD | {twenty_dd:.2f}% |")

    lines += ["", "---", "", "## 🔄 Trades Closed Today", ""]

    if closed_trades:
        lines.append("| Symbol | Dir | P&L % | Reason |")
        lines.append("|--------|-----|-------|--------|")
        for t in closed_trades:
            lines.append(
                f"| {t.get('symbol','?')} | {t.get('direction','?').upper()} "
                f"| {t.get('pnl_pct', 0):+.1f}% | {t.get('reason', '-')} |"
            )
    else:
        lines.append("_No closed trades found in today's log._")

    if stats:
        lines += [
            "",
            "### Trade Stats",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Closed Trades | {stats['n']} |",
            f"| Win Rate | {stats['win_rate']:.1f}% |",
            f"| Avg Win | {stats['avg_win']:+.1f}% |",
            f"| Avg Loss | {stats['avg_loss']:+.1f}% |",
            f"| Profit Factor | {pf_str} |",
            f"| Expectancy | {stats['expectancy']:+.2f}% / trade |",
            f"| Avg R-Multiple | {stats['avg_r']:+.2f}R |",
            f"| Max Losing Streak | {stats['max_losing_streak']} |",
            f"| Gross Wins | {stats['gross_wins']:+.1f}% |",
            f"| Gross Losses | -{stats['gross_losses']:.1f}% |",
        ]

    lines += ["", "---", "", "## 📂 Open Positions (Carried to Tomorrow)", ""]
    if open_pos:
        lines.append("| Symbol | Dir | Entry $ | Qty | Stop | T1 | T2 | Dry? |")
        lines.append("|--------|-----|---------|-----|------|-----|-----|------|")
        for p in open_pos:
            lines.append(
                f"| {p.get('occ_symbol', '?')} "
                f"| {p.get('direction', '?').upper()} "
                f"| ${p.get('entry_price', 0):.2f} "
                f"| {p.get('remaining', p.get('contracts', 0))} "
                f"| {p.get('stop_pct', 0):.0f}% "
                f"| {p.get('t1_pct', 0):.0f}% "
                f"| {p.get('t2_pct', 0):.0f}% "
                f"| {'✓' if p.get('is_dry_run') else '-'} |"
            )
    else:
        lines.append("_No open positions._")

    lines += ["", "---", "", "## 🤖 System Stats", ""]
    lines += [
        f"| Event | Count |",
        f"|-------|-------|",
        f"| Signals evaluated | {log_counts.get('signal', 0)} |",
        f"| Orders placed | {log_counts.get('order', 0)} |",
        f"| Dry-run fills | {log_counts.get('dry_run', 0)} |",
        f"| IV-rank gates | {log_counts.get('iv_gate', 0)} |",
        f"| Volume gates | {log_counts.get('vol_gate', 0)} |",
        f"| News vetoes | {log_counts.get('news_veto', 0)} |",
        f"| Debate: no | {log_counts.get('debate_no', 0)} |",
        f"| Debate: proceed | {log_counts.get('debate_ok', 0)} |",
        f"| Stop-outs | {log_counts.get('stop', 0)} |",
        f"| T1 partials | {log_counts.get('target1', 0)} |",
        f"| T2 targets | {log_counts.get('target2', 0)} |",
        f"| Hard / time closes | {log_counts.get('hard_close', 0)} |",
    ]

    lines += ["", "---", "", "## 🧠 AI Coaching Insight", "", insight, ""]

    lines += [
        "---",
        "",
        "## ✍️ Notes  _(fill in manually)_",
        "",
        "**What I did well today:**",
        "",
        "> ",
        "",
        "**What I should have done differently:**",
        "",
        "> ",
        "",
        "**Market context / regime:**",
        "",
        "> ",
        "",
        "**One thing to change tomorrow:**",
        "",
        "> ",
        "",
        "---",
        f"_SPY Auto Trader — EOD Journal — {TODAY}_",
    ]

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────
def main(api_key: str = "", secret_key: str = "") -> None:
    # Allow passing keys as CLI args: eod.py <api_key> <secret_key>
    if not api_key and len(sys.argv) >= 3:
        api_key, secret_key = sys.argv[1], sys.argv[2]
    if api_key:
        os.environ["ALPACA_API_KEY"]    = api_key
    if secret_key:
        os.environ["ALPACA_SECRET_KEY"] = secret_key

    print(f"📋 SPY Auto Trader — EOD Journal — {TODAY}")
    print()

    # 1. Account state
    print("→ Fetching Alpaca account...")
    acct = _alpaca_account()
    if acct:
        print(f"   Equity: ${acct['equity']:,.2f}  Day P&L: ${acct['day_pnl']:+,.2f}")
    else:
        print("   [warn] Could not reach Alpaca — account section will be empty")

    # 2. Equity curve
    if acct.get("equity"):
        _append_equity_curve(acct["equity"])
        print(f"   Equity curve updated → {CURVE_FILE}")

    # 3. Open positions
    open_pos = _load_open_positions()
    print(f"→ Open positions: {len(open_pos)}")

    # 4. Intraday stats
    intraday = _intraday_stats()
    if intraday:
        print(f"   Intraday max DD: {intraday['max_dd_pct']:.2f}%")

    # 5. Rolling drawdown
    five_dd   = _rolling_dd(5)
    twenty_dd = _rolling_dd(20)

    # 6. Log parse
    log_path = LOG_FILE if LOG_FILE.exists() else ALT_LOG
    print(f"→ Parsing log: {log_path}")
    log_counts = _parse_log(log_path)

    # 7. Closed trades
    closed_trades = _closed_trades_from_log(log_path)
    print(f"→ Closed trades found in log: {len(closed_trades)}")

    # 8. Stats
    stats = _trade_stats(closed_trades)

    # 9. Plain summary for LLM
    pf = stats.get("profit_factor", 0)
    pf_str = "∞" if pf == float("inf") else f"{pf:.2f}"
    plain_summary = "\n".join([
        f"Date: {TODAY}",
        f"Equity: ${acct.get('equity', 0):,.2f}  Day P&L: ${acct.get('day_pnl', 0):+,.2f} ({(acct.get('day_pnl',0)/acct.get('last_equity',1)*100):+.2f}%)",
        f"Closed trades: {stats.get('n', 0)}  Win rate: {stats.get('win_rate', 0):.1f}%",
        f"Profit factor: {pf_str}  Expectancy: {stats.get('expectancy', 0):+.2f}%  Avg R: {stats.get('avg_r', 0):+.2f}R",
        f"Signals: {log_counts.get('signal',0)}  Orders: {log_counts.get('order',0)}  IV gates: {log_counts.get('iv_gate',0)}  News vetoes: {log_counts.get('news_veto',0)}",
        f"Open positions carried: {len(open_pos)}",
        f"5-day DD: {five_dd:.2f}%" if five_dd is not None else "5-day DD: n/a",
    ])

    # 10. LLM insight
    print("→ Requesting AI coaching insight...")
    insight = _llm_insight(plain_summary)

    # 11. Build + write journal
    md = _build_journal(
        acct, open_pos, closed_trades, log_counts,
        intraday, five_dd, twenty_dd, stats, insight
    )
    JOURNAL_PATH.write_text(md)
    print()
    print(f"✅ Journal written → {JOURNAL_PATH}")
    print()
    print("── Preview ──")
    # Print first 30 lines
    for line in md.splitlines()[:30]:
        print(line)
    print("...")


if __name__ == "__main__":
    main()
