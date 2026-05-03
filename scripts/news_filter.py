"""
news_filter.py — Pre-session news sentiment veto.

check_news_sentiment(symbol) fetches recent headlines via Finnhub (if
FINNHUB_API_KEY is set) or yfinance (free, no key needed), scans for
severity keywords, and returns (vetoed: bool, reason: str).

HIGH-severity keywords → immediate veto (halt, bankruptcy, fraud, etc.)
MEDIUM-severity keywords → veto if >= NEWS_VETO_THRESHOLD hits in window
"""

import os
import time
import logging
from datetime import datetime, timedelta, timezone

import requests
import yfinance as yf

log = logging.getLogger(__name__)

NEWS_LOOKBACK_HOURS = 4       # how far back to scan
NEWS_VETO_THRESHOLD = 3       # medium-severity hits required to veto

NEWS_HIGH_SEVERITY = [
    "trading halt", "halted", "halt trading",
    "bankruptcy", "bankrupt", "chapter 11",
    "fraud", "sec charges", "sec investigation", "sec probe",
    "accounting irregulari", "restatement",
    "delisted", "delisting",
    "fda reject", "fda refuses", "complete response letter",
    "going concern",
    "criminal charges", "indicted", "indictment",
    "emergency", "force majeure",
]

NEWS_MEDIUM_SEVERITY = [
    "miss", "misses", "missed estimates", "below expectations",
    "warning", "warns", "profit warning",
    "downgrade", "downgraded",
    "investigation", "probe",
    "recall",
    "lawsuit", "class action",
    "layoff", "layoffs", "restructuring",
    "guidance cut", "lowered guidance", "cuts guidance",
    "revenue decline", "revenue miss",
    "loss widens", "net loss",
    "margin pressure", "margin compression",
]


def _fetch_finnhub(symbol: str, api_key: str) -> list:
    now_dt    = datetime.now(timezone.utc)
    since_dt  = now_dt - timedelta(hours=NEWS_LOOKBACK_HOURS)
    cutoff_ts = int(since_dt.timestamp())
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={
                "symbol": symbol.replace("/", ""),
                "from":   since_dt.strftime("%Y-%m-%d"),
                "to":     now_dt.strftime("%Y-%m-%d"),
                "token":  api_key,
            },
            timeout=8,
        )
        if resp.status_code != 200:
            log.warning(f"Finnhub news HTTP {resp.status_code} for {symbol}")
            return []
        return [
            item["headline"]
            for item in resp.json()
            if isinstance(item, dict)
            and item.get("datetime", 0) >= cutoff_ts
            and item.get("headline")
        ]
    except Exception as e:
        log.warning(f"Finnhub news fetch failed ({symbol}): {e}")
        return []


def _fetch_yfinance(symbol: str) -> list:
    cutoff = time.time() - NEWS_LOOKBACK_HOURS * 3600
    try:
        news = yf.Ticker(symbol).news or []
        headlines = []
        for item in news:
            if not isinstance(item, dict):
                continue
            if item.get("providerPublishTime", 0) < cutoff:
                continue
            content = item.get("content", {})
            title = (
                content.get("title") if isinstance(content, dict)
                else item.get("title", "")
            ) or ""
            if title:
                headlines.append(title)
        return headlines
    except Exception as e:
        log.warning(f"yfinance news fetch failed ({symbol}): {e}")
        return []


def check_news_sentiment(symbol: str, finnhub_key: str = None) -> tuple:
    """
    Scan recent headlines for symbol.

    Returns (vetoed: bool, reason: str).
    vetoed=True  → caller should skip the session.
    vetoed=False → news looks clean, proceed.
    """
    key = finnhub_key or os.getenv("FINNHUB_API_KEY", "")

    if key:
        headlines = _fetch_finnhub(symbol, key)
        source = "Finnhub"
    else:
        headlines = _fetch_yfinance(symbol)
        source = "yfinance"

    if not headlines:
        log.info(f"News filter ({symbol}): 0 recent headlines via {source} — proceeding")
        return False, "no headlines"

    log.info(f"News filter ({symbol}): {len(headlines)} headline(s) via {source}")

    medium_hits = []
    for hl in headlines:
        hl_lower = hl.lower()
        for kw in NEWS_HIGH_SEVERITY:
            if kw in hl_lower:
                reason = f"HIGH severity '{kw}': {hl[:120]}"
                log.warning(f"News veto ({symbol}): {reason}")
                return True, reason
        for kw in NEWS_MEDIUM_SEVERITY:
            if kw in hl_lower:
                medium_hits.append((kw, hl[:120]))

    if len(medium_hits) >= NEWS_VETO_THRESHOLD:
        kws    = ", ".join(f"'{h[0]}'" for h in medium_hits[:NEWS_VETO_THRESHOLD])
        reason = f"{len(medium_hits)} medium-severity signals ({kws})"
        log.warning(f"News veto ({symbol}): {reason}")
        return True, reason

    if medium_hits:
        log.info(
            f"News filter ({symbol}): {len(medium_hits)} medium hit(s) "
            f"— below threshold of {NEWS_VETO_THRESHOLD}, proceeding"
        )

    return False, "clean"
