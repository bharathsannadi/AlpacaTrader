"""
debate.py — Bull/Bear LLM debate layer.

Before a trade signal is acted on, two Claude Haiku calls argue opposite
sides of the setup. A third "judge" call weighs both and returns:
    (proceed: bool, confidence: float 0–1, summary: str)

If confidence < DEBATE_MIN_CONFIDENCE the signal is suppressed, even if
ORB/VWAP evaluators fired.

Requires ANTHROPIC_API_KEY in environment (or .env).
Adds ~3–8s per signal check (Haiku is fast and cheap).

Usage:
    from debate import run_debate
    proceed, conf, summary = run_debate(symbol, direction, indicators, news_summary, memory_context)
"""

import os
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

DEBATE_MIN_CONFIDENCE = 0.65   # suppress trade if judge confidence < this
DEBATE_MODEL          = "claude-haiku-4-5-20251001"
MAX_TOKENS            = 256    # keep responses tight

# ── Load knowledge base (distilled from 10 options trading books) ─────────────
def _load_kb_rules() -> str:
    """Load the key rules sections from knowledge_base.md for injection into prompts."""
    kb_path = Path(__file__).parent.parent / "knowledge_base.md"
    if not kb_path.exists():
        return ""
    try:
        text = kb_path.read_text()
        # Extract sections 2, 3, 7, 8 (IV rules, timing, mistakes, master rules)
        # Keep it concise — only inject the checklist + key rules so prompts stay fast
        sections = []
        capture = False
        for line in text.splitlines():
            if any(h in line for h in [
                "## 2. IV & Volatility Rules",
                "## 3. Entry & Exit Timing",
                "## 7. Common Mistakes",
                "## 8. Key Rules from the Masters",
                "## 9. Checklist Before Every Trade",
            ]):
                capture = True
            elif line.startswith("## ") and capture:
                # stop at next top-level section not in our list
                if not any(h in line for h in [
                    "## 2.", "## 3.", "## 7.", "## 8.", "## 9."
                ]):
                    capture = False
            if capture:
                sections.append(line)
        extracted = "\n".join(sections[:200])  # cap at ~200 lines to stay within token budget
        return extracted
    except Exception:
        return ""

_KB_RULES = _load_kb_rules()

_KB_PREAMBLE = (
    "You have been trained on 28 professional options & trading books (Natenberg, Passarelli, "
    "Saliba, McMillan, Sinclair, Hull, Schwager, Brooks, Holmes/VSA). Apply these rules strictly:\n"
    "• Buy options only when IV rank < 50%; prefer IVR < 30% for naked long options\n"
    "• Target delta 0.40–0.60 for directional intraday plays\n"
    "• Never enter in first 15 min of session or after 14:00 ET unless very strong signal\n"
    "• 7 DTE options lose ~1/7 of remaining value per day — theta is the enemy; require fast moves\n"
    "• Stop at 50% premium loss; never hold past 80% loss\n"
    "• ORB breakout requires volume confirmation (vol ratio > 1.3) and close above/below ORB level\n"
    "• VWAP cross alone is NOT sufficient — require EMA alignment + volume\n"
    "• Avoid entries when RSI > 70 (overbought for calls) or RSI < 30 (oversold for puts)\n"
    "• VSA Rule: High volume (ratio > 2.0) on an UP bar with narrow spread = distribution by smart money — BEARISH warning for calls\n"
    "• VSA Rule: High volume (ratio > 2.0) on a DOWN bar with narrow spread + closes above mid = accumulation — BULLISH background for calls\n"
    "• Brooks Rule: ORB breakout bar must close in top 25% of bar range (for bull) — weak breakout bars are traps\n"
    "• Brooks Rule: After a climax bar (> 2× ATR), do not chase — exhaustion likely; wait for pullback entry\n"
    "• Sinclair Rule: After VIX spikes > 5 pts in one day, use debit spreads only for 2–3 days (IV is elevated)\n"
    "• Vol trend: If SPY vol ratio on entry bar < 0.8 (below-average), reduce conviction — no institutional backing\n"
    "• Scale out: At +50% premium gain, take partial profits; do not hold full position to +100%\n"
    "• Never open new positions after 3 consecutive intraday losses\n"
) + (_KB_RULES[:1500] if _KB_RULES else "")

_BULL_SYSTEM = (
    "You are a bullish options trader with deep knowledge of Greeks and volatility. "
    "Given a market setup, make the strongest possible bull case in 3–4 sentences. "
    "Reference relevant Greeks (delta, gamma, theta) and IV conditions. "
    "Flag any risks that would make the bull case weaker. "
    "Be specific and concise. End with: Confidence: X% (0–100).\n\n"
    + _KB_PREAMBLE
)

_BEAR_SYSTEM = (
    "You are a bearish options trader with deep knowledge of Greeks and volatility. "
    "Given a market setup, make the strongest possible bear case in 3–4 sentences. "
    "Reference relevant risks (theta decay, IV crush, overextension). "
    "Be specific and concise. End with: Confidence: X% (0–100).\n\n"
    + _KB_PREAMBLE
)

_JUDGE_SYSTEM = (
    "You are a neutral trading judge with expertise in options risk management. "
    "Given a bull argument and a bear argument, decide whether to proceed with the proposed trade direction. "
    "Apply professional options trading standards: Is IV reasonable? Is the setup clean? Is risk/reward justified? "
    "Respond with exactly this JSON (no markdown):\n"
    '{"proceed": true/false, "confidence": 0.00, "reason": "one sentence"}\n'
    "confidence is 0.0–1.0. Only set proceed=true if confidence >= 0.65.\n\n"
    + _KB_PREAMBLE
)


def _fmt_indicators(symbol: str, direction: str, indicators: dict) -> str:
    close = float(indicators.get("close_price", 0) or 0)
    vwap  = float(indicators.get("vwap", close) or close)
    ema9  = float(indicators.get("ema9", close) or close)

    vwap_dev = round((close - vwap) / vwap * 100, 2) if vwap else 0
    ema9_dev = round((close - ema9) / ema9 * 100, 2) if ema9 else 0
    rsi      = indicators.get("rsi", "n/a")
    macd     = indicators.get("macd_hist", "n/a")
    vol      = indicators.get("vol_ratio", "n/a")
    atr      = indicators.get("atr", "n/a")

    return (
        f"Symbol: {symbol} | Proposed direction: {direction.upper()}\n"
        f"Close: ${close:.2f}  VWAP dev: {vwap_dev:+.2f}%  EMA9 dev: {ema9_dev:+.2f}%\n"
        f"RSI: {rsi}  MACD-hist: {macd}  Vol ratio: {vol}  ATR: {atr}"
    )


def run_debate(
    symbol: str,
    direction: str,
    indicators: dict,
    news_summary: str = "",
    memory_context: str = "",
) -> tuple[bool, float, str]:
    """
    Run bull/bear debate and return (proceed, confidence, summary).

    Failure semantics:
      - "Gate is OFF" cases (no API key, client init fails) → fail OPEN with
        (True, 1.0, ...). Caller should already be checking DEBATE_ENABLED.
      - "Gate is ON but broke" cases (any LLM call fails, judge response unparseable)
        → fail CLOSED with (False, 0.0, ...). A risk gate that silently disappears
        on a network blip is no gate at all.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.debug("debate: ANTHROPIC_API_KEY not set — skipping debate (gate OFF)")
        return True, 1.0, "no_api_key"

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    except Exception as e:
        log.warning(f"debate: failed to create Anthropic client: {e} — gate OFF")
        return True, 1.0, f"client_init_failed: {e}"

    setup = _fmt_indicators(symbol, direction, indicators)
    if news_summary:
        setup += f"\nNews: {news_summary}"
    if memory_context:
        setup += f"\n{memory_context}"

    # ── Step 1: Bull agent ────────────────────────────────────────────────────
    bull_arg = _call_llm(client, _BULL_SYSTEM, f"Setup:\n{setup}\n\nMake the bull case.")
    if bull_arg is None:
        log.warning("debate: bull LLM call failed — failing CLOSED (suppressing trade)")
        return False, 0.0, "bull_llm_failed"

    # ── Step 2: Bear agent ────────────────────────────────────────────────────
    bear_arg = _call_llm(client, _BEAR_SYSTEM, f"Setup:\n{setup}\n\nMake the bear case.")
    if bear_arg is None:
        log.warning("debate: bear LLM call failed — failing CLOSED (suppressing trade)")
        return False, 0.0, "bear_llm_failed"

    # ── Step 3: Judge ────────────────────────────────────────────────────────
    judge_prompt = (
        f"Setup:\n{setup}\n\n"
        f"BULL says: {bull_arg}\n\n"
        f"BEAR says: {bear_arg}\n\n"
        f"Proposed direction: {direction.upper()}. Should we proceed?"
    )
    judge_raw = _call_llm(client, _JUDGE_SYSTEM, judge_prompt)
    if judge_raw is None:
        log.warning("debate: judge LLM call failed — failing CLOSED (suppressing trade)")
        return False, 0.0, "judge_llm_failed"

    proceed, confidence, reason = _parse_judge(judge_raw)
    summary = (
        f"Debate ({symbol} {direction.upper()}) conf={confidence:.0%} → "
        f"{'PROCEED' if proceed else 'SUPPRESS'} | {reason}"
    )
    log.info(f"  Bull: {bull_arg[:120]}")
    log.info(f"  Bear: {bear_arg[:120]}")
    log.info(f"  Judge: {summary}")
    return proceed, confidence, summary


def _call_llm(client, system: str, user: str) -> Optional[str]:
    try:
        resp = client.messages.create(
            model=DEBATE_MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        log.warning(f"debate: LLM call failed: {e}")
        return None


def _parse_judge(raw: str) -> tuple[bool, float, str]:
    """Extract (proceed, confidence, reason) from judge JSON response.
    On parse failure: fail CLOSED — a malformed judge is not a green light.
    """
    import json, re
    try:
        # Strip markdown fences if present
        clean = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        data = json.loads(clean)
        proceed    = bool(data.get("proceed", True))
        confidence = float(data.get("confidence", 1.0))
        confidence = max(0.0, min(1.0, confidence))
        reason     = str(data.get("reason", ""))
        return proceed, confidence, reason
    except Exception:
        log.warning(f"debate: could not parse judge response: {raw[:200]} — failing CLOSED")
        return False, 0.0, "judge_parse_failed"
