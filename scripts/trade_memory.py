"""
trade_memory.py — ChromaDB-backed persistent trade memory.

Records each trade entry with its indicator snapshot as a vector document.
Before a signal fires, retrieve_similar() surfaces the N most similar past
setups with their outcomes, giving the session pattern-recognition context.

Storage: ~/.spy_trader/memory/  (ChromaDB persistent SQLite + HNSW index)

Usage:
    memory = TradeMemory()
    trade_id = memory.record("SPY", "bull", indicators_dict, entry_price=585.20)
    memory.update_outcome(trade_id, outcome_pct=+34.0, hold_minutes=18.0)
    summary = memory.retrieve_similar("SPY", "bull", indicators_dict)
    log.info(summary)
"""

import os
import re
import logging
import numpy as np
from datetime import datetime, timezone

log = logging.getLogger(__name__)

MEMORY_DIR      = os.path.expanduser("~/.spy_trader/memory")
COLLECTION_NAME = "trade_memory"
RETRIEVE_N      = 5
EMBED_DIM       = 8   # fixed vector length: [dir, vwap_dev, ema9_dev, rsi, macd_hist, vol_ratio, atr, padding]


def _indicators_to_text(symbol: str, direction: str, indicators: dict) -> str:
    """Normalise indicator snapshot into a text document for embedding.

    Uses relative deviations (price vs VWAP, price vs EMA9) rather than
    absolute prices so similarity is about market structure, not price level.
    """
    close = float(indicators.get("close_price", 0) or 0)
    vwap  = float(indicators.get("vwap",  close) or close)
    ema9  = float(indicators.get("ema9",  close) or close)

    vwap_dev = round((close - vwap) / vwap * 100, 3) if vwap else 0
    ema9_dev = round((close - ema9) / ema9 * 100, 3) if ema9 else 0

    parts = [f"{symbol} {direction}"]
    parts.append(f"vwap_dev={vwap_dev:.3f}pct")
    parts.append(f"ema9_dev={ema9_dev:.3f}pct")

    for key in ("rsi", "macd_hist", "vol_ratio", "atr"):
        val = indicators.get(key)
        if val is not None:
            try:
                parts.append(f"{key}={float(val):.4f}")
            except (TypeError, ValueError):
                pass

    return " ".join(parts)


class _IndicatorEmbedder:
    """Lightweight embedding function for structured indicator text.
    Extracts numeric features directly — no onnxruntime needed.

    Feature vector (EMBED_DIM=8):
      [direction_sign, vwap_dev, ema9_dev, rsi_norm, macd_hist, vol_ratio_norm, atr_norm, 0]
    """

    @staticmethod
    def name() -> str:
        return "indicator_embedder"

    @staticmethod
    def build_from_config(config: dict) -> "_IndicatorEmbedder":
        return _IndicatorEmbedder()

    def get_config(self) -> dict:
        return {}

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in input]

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self.__call__(input)

    @staticmethod
    def _embed(text: str) -> list[float]:
        direction = 1.0 if "bull" in text else (-1.0 if "bear" in text else 0.0)

        nums: dict[str, float] = {}
        for match in re.finditer(r'(\w+)=([-+]?\d*\.?\d+)', text):
            try:
                nums[match.group(1)] = float(match.group(2))
            except ValueError:
                pass

        vwap_dev  = nums.get("vwap_dev",  0.0)
        ema9_dev  = nums.get("ema9_dev",  0.0)
        rsi_norm  = (nums.get("rsi", 50.0) - 50.0) / 50.0
        macd_hist = nums.get("macd_hist", 0.0)
        vol_ratio = nums.get("vol_ratio", 1.0) - 1.0
        atr_norm  = nums.get("atr", 0.0)

        vec = np.array([direction, vwap_dev, ema9_dev, rsi_norm,
                        macd_hist, vol_ratio, atr_norm, 0.0], dtype=float)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec.tolist()


class TradeMemory:
    def __init__(self, enabled: bool = True):
        self._enabled = enabled
        self._client = None
        self._collection = None
        if enabled:
            self._init()

    def _init(self) -> None:
        try:
            import chromadb
            os.makedirs(MEMORY_DIR, exist_ok=True)
            self._client = chromadb.PersistentClient(path=MEMORY_DIR)
            self._collection = self._client.get_or_create_collection(
                name=COLLECTION_NAME,
                embedding_function=_IndicatorEmbedder(),
                metadata={"hnsw:space": "cosine"},
            )
            n = self._collection.count()
            log.info(f"TradeMemory: ready — {n} past trade(s) in {MEMORY_DIR}")
        except ImportError:
            log.warning("TradeMemory: chromadb not installed — run: pip install chromadb")
            self._enabled = False
        except Exception as e:
            log.warning(f"TradeMemory: init failed: {e}")
            self._enabled = False

    # ── Write ─────────────────────────────────────────────────────────────────

    def record(
        self,
        symbol: str,
        direction: str,
        indicators: dict,
        entry_price: float,
        trade_id: str = None,
        is_dry_run: bool = False,
    ) -> str:
        """Store a trade entry. Returns trade_id for later outcome update.

        is_dry_run=True flags the record so retrieve_similar filters it out
        by default — dry-run P&L is theoretical (mid-based, no slippage) and
        shouldn't pollute the learning loop for real trades. The data is kept
        so dry-run outcomes can still be reviewed separately.
        """
        if not self._enabled or self._collection is None:
            return ""
        try:
            ts  = datetime.now(timezone.utc).isoformat()
            tid = trade_id or f"{symbol}_{ts.replace(':', '-')}"
            doc = _indicators_to_text(symbol, direction, indicators)
            self._collection.add(
                documents=[doc],
                metadatas=[{
                    "symbol":        symbol,
                    "direction":     direction,
                    "entry_price":   float(entry_price),
                    "outcome_pct":   0.0,
                    "hold_minutes":  0.0,
                    "outcome_known": False,
                    "is_dry_run":    bool(is_dry_run),
                    "timestamp":     ts,
                }],
                ids=[tid],
            )
            tag = " [dry-run]" if is_dry_run else ""
            log.info(f"TradeMemory: recorded entry{tag} — {tid}")
            return tid
        except Exception as e:
            log.warning(f"TradeMemory.record failed: {e}")
            return ""

    def update_outcome(
        self, trade_id: str, outcome_pct: float, hold_minutes: float
    ) -> None:
        """Update a stored trade with its realised P&L."""
        if not self._enabled or not trade_id or self._collection is None:
            return
        try:
            self._collection.update(
                ids=[trade_id],
                metadatas=[{
                    "outcome_pct":   round(outcome_pct, 2),
                    "hold_minutes":  round(hold_minutes, 1),
                    "outcome_known": True,
                }],
            )
            sign = "+" if outcome_pct >= 0 else ""
            log.info(f"TradeMemory: outcome updated {trade_id} → {sign}{outcome_pct:.1f}% in {hold_minutes:.0f}min")
        except Exception as e:
            log.warning(f"TradeMemory.update_outcome failed: {e}")

    # ── Read ──────────────────────────────────────────────────────────────────

    def retrieve_similar(
        self,
        symbol: str,
        direction: str,
        indicators: dict,
        n: int = RETRIEVE_N,
        include_dry_run: bool = False,
    ) -> str:
        """
        Find the N most similar past setups and return a log-ready summary.
        Returns "" if memory is empty or disabled.

        Dry-run records are excluded by default — theoretical fills don't
        inform real-trade decisions. Set include_dry_run=True to inspect them.
        """
        if not self._enabled or self._collection is None:
            return ""
        try:
            total = self._collection.count()
            if total == 0:
                return ""

            query     = _indicators_to_text(symbol, direction, indicators)
            n_results = min(n, total)

            # Build where clause: filter by symbol once enough data + exclude
            # dry-run records unless explicitly requested.
            conds = []
            if total >= 20:
                conds.append({"symbol": symbol})
            if not include_dry_run:
                # $ne True covers both False and records predating the flag
                conds.append({"is_dry_run": {"$ne": True}})
            if len(conds) > 1:
                where = {"$and": conds}
            elif conds:
                where = conds[0]
            else:
                where = None
            results = self._collection.query(
                query_texts=[query],
                n_results=n_results,
                where=where,
            )

            if not results or not results.get("metadatas"):
                return ""

            lines = [
                f"Memory: {n_results} similar {symbol} {direction.upper()} setups "
                f"(of {total} total trades):"
            ]
            for meta, dist in zip(
                results["metadatas"][0], results["distances"][0]
            ):
                similarity = round((1 - dist) * 100, 1)
                if meta.get("outcome_known"):
                    pct  = meta["outcome_pct"]
                    mins = meta.get("hold_minutes", 0)
                    sign = "+" if pct >= 0 else ""
                    outcome = f"{sign}{pct:.1f}% in {mins:.0f}min"
                    icon = "✓" if pct > 0 else "✗"
                else:
                    outcome = "outcome pending"
                    icon = "·"
                lines.append(
                    f"  {icon} [{similarity}% match] {meta['direction'].upper()} "
                    f"@ ${meta['entry_price']:.2f} → {outcome}"
                )
            return "\n".join(lines)
        except Exception as e:
            log.warning(f"TradeMemory.retrieve_similar failed: {e}")
            return ""

    @property
    def count(self) -> int:
        if self._collection is None:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0
