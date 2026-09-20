"""Core domain types shared across every ApexInvest engine.

These are deliberately small and dependency-free so every engine speaks the
same vocabulary. Money-relevant numbers are plain floats here but are rounded
and provenance-tagged before they ever leave the system (see risk.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AssetClass(str, Enum):
    EQUITY = "equity"
    ETF = "etf"
    CRYPTO = "crypto"
    FX = "fx"


class Objective(str, Enum):
    LONG_TERM = "long_term"
    SWING = "swing"
    DAY = "day"
    INCOME = "income"
    ANALYZE = "analyze"


class Trend(str, Enum):
    UP = "up"
    SIDEWAYS = "sideways"
    DOWN = "down"


class Bucket(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Action(str, Enum):
    BUY = "BUY"
    WAIT = "WAIT"
    AVOID = "AVOID"


class Bias(str, Enum):
    LONG = "long"
    NEUTRAL = "neutral"
    SHORT = "short"


# Horizon metadata per objective: volatility-appropriate stop/target multipliers
# (as multiples of ATR) and a human-readable time estimate. These are the only
# place risk "widths" are defined, so they are auditable in one spot.
OBJECTIVE_META: dict[Objective, dict[str, Any]] = {
    Objective.LONG_TERM: {"atr_stop": 4.0, "min_rr": 2.0, "est_time": "6-18 months", "horizon_days": 400},
    Objective.SWING:     {"atr_stop": 2.0, "min_rr": 1.8, "est_time": "1-3 weeks",   "horizon_days": 15},
    Objective.DAY:       {"atr_stop": 1.2, "min_rr": 1.5, "est_time": "hours-1 day",  "horizon_days": 1},
    Objective.INCOME:    {"atr_stop": 3.5, "min_rr": 1.8, "est_time": "ongoing",      "horizon_days": 365},
    Objective.ANALYZE:   {"atr_stop": 2.5, "min_rr": 1.6, "est_time": "days-weeks",   "horizon_days": 20},
}


@dataclass
class Provenance:
    """Where a value came from. Every emitted number carries one of these so a
    user can audit whether it was computed, extracted, or entered."""
    source: str            # e.g. "computed:atr", "extracted:volume_profile", "entered:price"
    detail: str = ""
    confidence: float = 1.0  # 0..1 reliability of the source (low for fuzzy OCR)

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "detail": self.detail, "confidence": round(self.confidence, 3)}


@dataclass
class StrategySignal:
    """Output of a single strategy module."""
    strategy_id: str
    bias: Bias
    quality: float                      # 0..1 self-assessed signal quality
    entry_hint: float | None = None     # reference price the plan should build around
    invalidation: float | None = None   # level that would prove the idea wrong
    objective_level: float | None = None  # a natural take-profit level, if the strategy sees one
    notes: str = ""
    provenance: list[Provenance] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "bias": self.bias.value,
            "quality": round(self.quality, 3),
            "entry_hint": self.entry_hint,
            "invalidation": self.invalidation,
            "objective_level": self.objective_level,
            "notes": self.notes,
            "provenance": [p.as_dict() for p in self.provenance],
        }


@dataclass
class RegimeSnapshot:
    trend: Trend
    volatility: Bucket
    liquidity: Bucket
    atr: float
    atr_pct: float
    adx: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "trend": self.trend.value,
            "volatility": self.volatility.value,
            "liquidity": self.liquidity.value,
            "atr": round(self.atr, 6),
            "atr_pct": round(self.atr_pct, 4),
            "adx": round(self.adx, 2),
        }
