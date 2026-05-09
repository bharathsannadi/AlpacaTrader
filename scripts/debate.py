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
from typing import Optional

log = logging.getLogger(__name__)

DEBATE_MIN_CONFIDENCE = 0.65   # suppress trade if judge confidence < this
DEBATE_MODEL          = "claude-haiku-4-5-20251001"
MAX_TOKENS            = 256    # keep responses tight

_BULL_SYSTEM = """\
You are a bullish options trader. Given a market setup, make the strongest \
possible bull case in 3–4 sentences. Focus on momentum, support levels, and \
risk/reward. Be specific and concise. End with: Confidence: X% (0–100)."""

_BEAR_SYSTEM = """\
You are a bearish options trader. Given a market setup, make the strongest \
possible bear case in 3–4 sentences. Focus on resistance, overextension, and \
downside risk. Be specific and concise. End with: Confidence: X% (0–100)."""

_JUDGE_SYSTEM = """\
You are a neutral trading judge. Given a bull argument and a bear argument for \
the same setup, decide whether to proceed with the proposed trade direction. \
Respond with exactly this JSON (no markdown):
{"proceed": true/false, "confidence": 0.00, "reason": "one sentence"}
confidence is 0.0–1.0. Only set proceed=true if confidence >= 0.65."""


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
