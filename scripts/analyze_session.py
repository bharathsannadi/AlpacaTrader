#!/usr/bin/env python3
"""
analyze_session.py — Session summary from spy_trader.log

Usage:
    python scripts/analyze_session.py           # today
    python scripts/analyze_session.py 2026-05-07  # specific date

Counts signals fired, no-fire rejections grouped by reason, gate blocks,
news vetoes, and stop/target hits — so you can answer "why no trades?"
in one read.
"""
import re
import sys
import collections
from datetime import datetime
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "spy_trader.log"

PATTERNS = {
    "signal":            re.compile(r"SIGNAL \[(BULL|BEAR)\]\s+(.+)"),
    "orb_nofire":        re.compile(r"ORB no-fire: bull\[([^\]]*)\] \| bear\[([^\]]*)\]"),
    "vwap_nofire":       re.compile(r"VWAP-momentum no-fire: bull\[([^\]]*)\] \| bear\[([^\]]*)\]"),
    "gap_nofire":        re.compile(r"Gap-fade\((up|down)\) no-fire: (.+)"),
    "bar_eval":          re.compile(r"\bINFO\s+\d{2}:\d{2}\s+([A-Z]+)=\$\d"),
    "iv_block":          re.compile(r"IV Rank=([\d.]+)% > \d+% — options overpriced"),
    "iv_warn":           re.compile(r"IVR=([\d.]+)% — elevated"),
    "news_veto":         re.compile(r"News veto"),
    "stale":             re.compile(r"⛔ Stale data:"),
    "daily_loss":        re.compile(r"⛔ Daily loss"),
    "daily_profit":      re.compile(r"💰 Daily profit lock"),
    "global_cooldown":   re.compile(r"Global cooldown.*active"),
    "cooldown":          re.compile(r"Cool-down active"),
    "same_dir_block":    re.compile(r"Same-direction block"),
    "htf_block":         re.compile(r"HTF filter:.*opposes"),
    "portfolio_cap":     re.compile(r"Portfolio risk.*>= max"),
    "sector_cap":        re.compile(r"Sector cap:"),
    "spread_wide":       re.compile(r"Spread \$([\d.]+) \(([\d.]+)% of mid\) too wide"),
    "no_oi":             re.compile(r"no contracts pass OI"),
    "no_expiry":         re.compile(r"No \w+ expiry in DTE range"),
    "size_zero":         re.compile(r"size_contracts: stop-risk"),
    "stop_hit":          re.compile(r"STOP HIT"),
    "target_1":          re.compile(r"TARGET 1 partial"),
    "target_2":          re.compile(r"TARGET 2"),
    "time_stop":         re.compile(r"TIME STOP"),
    "hard_close":        re.compile(r"HARD CLOSE"),
    "vix_block":         re.compile(r"VIX too high"),
    "earnings_warn":     re.compile(r"EARNINGS RISK"),
    "live_vix":          re.compile(r"Live VIX"),
}


def parse(date_str: str):
    counts = collections.Counter()
    signals = []
    nofire_reasons = collections.Counter()  # dominant failing condition
    bars_per_symbol = collections.Counter()
    total_lines = 0

    if not LOG.exists():
        print(f"Log not found: {LOG}")
        sys.exit(1)

    with LOG.open(errors="replace") as fh:
        for line in fh:
            if date_str not in line:
                continue
            total_lines += 1

            for key, pat in PATTERNS.items():
                m = pat.search(line)
                if not m:
                    continue
                counts[key] += 1
                if key == "signal":
                    signals.append((m.group(1), m.group(2).strip()))
                elif key in ("orb_nofire", "vwap_nofire"):
                    bull, bear = m.group(1), m.group(2)
                    # Tally the FIRST failing condition for each side — usually the dominant one
                    for raw in (bull, bear):
                        if raw:
                            first = raw.split(",")[0].strip()
                            # Normalize: strip numeric specifics so we can group
                            norm = re.sub(r"[\d.+-]+", "?", first)
                            nofire_reasons[f"{key.split('_')[0]}: {norm}"] += 1
                elif key == "gap_nofire":
                    raw = m.group(2)
                    first = raw.split(",")[0].strip()
                    norm = re.sub(r"[\d.+-]+", "?", first)
                    nofire_reasons[f"gap: {norm}"] += 1
                elif key == "bar_eval":
                    bars_per_symbol[m.group(1)] += 1

    return counts, signals, nofire_reasons, bars_per_symbol, total_lines


def main():
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
    counts, signals, nofire_reasons, bars_per_symbol, total = parse(date_str)

    print(f"\n── Session summary for {date_str} ──")
    print(f"Total log lines: {total:,}")
    print(f"Bar evaluations: {sum(bars_per_symbol.values()):,}", end="")
    if bars_per_symbol:
        per_sym = "  ".join(f"{s}={c}" for s, c in sorted(bars_per_symbol.items()))
        print(f"   ({per_sym})")
    else:
        print()

    # ── Signals fired
    print(f"\nSIGNALS FIRED: {counts['signal']}")
    for direction, reason in signals[:10]:
        print(f"  [{direction}]  {reason[:90]}")
    if len(signals) > 10:
        print(f"  ... ({len(signals) - 10} more)")

    # ── No-fire (the diagnostic)
    nofire_total = counts["orb_nofire"] + counts["vwap_nofire"] + counts["gap_nofire"]
    print(f"\nNO-FIRE EVALUATIONS: {nofire_total}  "
          f"(orb={counts['orb_nofire']}  vwap={counts['vwap_nofire']}  gap={counts['gap_nofire']})")
    if nofire_reasons:
        print("Top blocking conditions (first failure per evaluator pass):")
        for reason, n in nofire_reasons.most_common(15):
            print(f"  {n:5}  {reason}")

    # ── Gates
    print("\nGATE BLOCKS:")
    gate_keys = [
        ("iv_block",         "IV rank > max"),
        ("iv_warn",          "IV rank elevated (warn)"),
        ("news_veto",        "News veto"),
        ("stale",            "Stale data refused"),
        ("daily_loss",       "Daily loss halt"),
        ("daily_profit",     "Daily profit lock"),
        ("global_cooldown",  "Global cooldown"),
        ("cooldown",         "Per-symbol cooldown"),
        ("same_dir_block",   "Same-direction block (post-stop)"),
        ("htf_block",        "HTF trend filter"),
        ("portfolio_cap",    "Portfolio risk cap"),
        ("sector_cap",       "Sector cap"),
        ("spread_wide",      "Spread too wide"),
        ("no_oi",            "No options pass OI floor"),
        ("no_expiry",        "No expiry in DTE range"),
        ("size_zero",        "Sized to 0 contracts"),
        ("vix_block",        "VIX too high (session blocked)"),
    ]
    any_gate = False
    for key, label in gate_keys:
        if counts[key]:
            print(f"  {counts[key]:5}  {label}")
            any_gate = True
    if not any_gate:
        print("  (none — gates not triggering)")

    # ── Exits
    exits_total = counts["stop_hit"] + counts["target_1"] + counts["target_2"] + counts["time_stop"] + counts["hard_close"]
    if exits_total:
        print(f"\nEXITS: {exits_total}")
        for key, label in [("target_2", "Target 2"), ("target_1", "Target 1 partial"),
                           ("stop_hit", "Stop hit"), ("time_stop", "Time stop"),
                           ("hard_close", "Hard close")]:
            if counts[key]:
                print(f"  {counts[key]:5}  {label}")

    # ── Data freshness signals
    if counts["live_vix"] or counts["earnings_warn"]:
        print("\nDATA / CONTEXT:")
        if counts["live_vix"]:    print(f"  {counts['live_vix']:5}  Live VIX computed from chain")
        if counts["earnings_warn"]: print(f"  {counts['earnings_warn']:5}  Earnings risk warnings")

    print()


if __name__ == "__main__":
    main()
