"""Strategy Recommendation Engine — the product's differentiator.

Turns AUTO into a defensible recommendation via transparent weighted scoring,
not a black box. For each strategy it combines:
  - fit to the current situation      (strategy.applicable_to)
  - fit to the objective's horizon    (a small, visible table)
  - data availability                 (do we have / can the user provide inputs)
It then picks a complementary blend (1-2 strategies) and returns the exact
inputs the user must upload, plus a human-readable rationale.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain import Objective, RegimeSnapshot, Trend
from . import strategies as strat
from .strategies import StrategyContext

# How well each method suits each objective's time horizon (0..1). Auditable.
# Methods scoring >= PANEL_MIN are run together as a confluence panel.
HORIZON_FIT: dict[Objective, dict[str, float]] = {
    Objective.LONG_TERM: {"fundamental": 1.0, "trend": 0.9, "accumulation": 0.9, "macd": 0.6, "price_action": 0.5, "rsi": 0.45, "poc": 0.4, "momentum": 0.3, "breakout": 0.2},
    Objective.SWING:     {"poc": 1.0, "price_action": 0.95, "trend": 0.8, "macd": 0.8, "rsi": 0.75, "momentum": 0.7, "breakout": 0.7, "accumulation": 0.5, "fundamental": 0.3},
    Objective.DAY:       {"momentum": 1.0, "breakout": 0.95, "macd": 0.7, "rsi": 0.7, "price_action": 0.7, "poc": 0.6, "trend": 0.5, "accumulation": 0.2, "fundamental": 0.0},
    Objective.INCOME:    {"fundamental": 1.0, "accumulation": 0.7, "trend": 0.6, "price_action": 0.4, "poc": 0.3, "macd": 0.3, "rsi": 0.3, "momentum": 0.2, "breakout": 0.1},
    Objective.ANALYZE:   {"price_action": 0.9, "trend": 0.85, "macd": 0.85, "momentum": 0.85, "poc": 0.7, "rsi": 0.7, "breakout": 0.6, "accumulation": 0.6, "fundamental": 0.5},
}

# A method must suit the horizon at least this much to join the panel, which is
# capped at PANEL_MAX (ranked by score) so results stay confluence-based, not noisy.
PANEL_MIN = 0.55
PANEL_MAX = 6

WEIGHTS = {"fit": 0.45, "horizon": 0.40, "data": 0.15}


@dataclass
class ScoredStrategy:
    id: str
    label: str
    score: float
    parts: dict[str, float]
    required_inputs: list[str]


@dataclass
class Recommendation:
    recommended: list[str]
    rationale: str
    required_inputs: list[str]
    ranking: list[ScoredStrategy] = field(default_factory=list)
    context: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "recommended": self.recommended,
            "rationale": self.rationale,
            "required_inputs": self.required_inputs,
            "ranking": [
                {"id": s.id, "label": s.label, "score": round(s.score, 3), "parts": {k: round(v, 3) for k, v in s.parts.items()}}
                for s in self.ranking
            ],
            "context": self.context,
        }


def _data_availability(strategy_id: str, ctx: StrategyContext) -> float:
    """1.0 if the strategy's needs are already met by provided data; else a
    fraction reflecting how much is present. Uploadable inputs still count
    partially because the user can supply them."""
    s = strat.get(strategy_id)
    if not s.required_inputs:
        return 1.0
    have = 0
    for inp in s.required_inputs:
        if inp == "financials" and ctx.fundamentals:
            have += 1
        elif inp in ("daily_chart", "intraday_chart", "volume", "volume_profile") and ctx.candles:
            have += 1
    # Anything not yet provided is uploadable -> count as 0.5 (available on request).
    return max(have / len(s.required_inputs), 0.5)


def recommend(objective: Objective, ctx: StrategyContext) -> Recommendation:
    regime: RegimeSnapshot | None = ctx.regime
    ranking: list[ScoredStrategy] = []
    for sid, s in strat.REGISTRY.items():
        fit = s.applicable_to(ctx)
        horizon = HORIZON_FIT[objective].get(sid, 0.3)
        data = _data_availability(sid, ctx)
        score = WEIGHTS["fit"] * fit + WEIGHTS["horizon"] * horizon + WEIGHTS["data"] * data
        ranking.append(ScoredStrategy(
            id=sid, label=s.label, score=score,
            parts={"fit": fit, "horizon": horizon, "data": data},
            required_inputs=list(s.required_inputs),
        ))
    ranking.sort(key=lambda x: x.score, reverse=True)

    # Confluence panel: every method that suits this horizon (HORIZON_FIT >=
    # PANEL_MIN), ranked by score, capped at PANEL_MAX. A single dominant method
    # is never enough — a professional reads several confirming signals together.
    hfit = HORIZON_FIT[objective]
    blend = [r.id for r in ranking if hfit.get(r.id, 0.3) >= PANEL_MIN][:PANEL_MAX]
    if not blend:
        blend = [ranking[0].id]

    required = strat.required_inputs_for(blend)
    labels = ", ".join(strat.get(b).label for b in blend)
    regime_txt = f"a {regime.trend.value} / {regime.volatility.value}-volatility market" if regime else "the available data"
    rationale = (
        f"For a {objective.value.replace('_', ' ')} objective in {regime_txt}, ApexInvest runs a "
        f"panel of {len(blend)} confirming methods — {labels} — and looks for agreement (confluence) "
        f"rather than trusting any single signal."
    )

    return Recommendation(
        recommended=blend,
        rationale=rationale,
        required_inputs=required,
        ranking=ranking,
        context=(regime.as_dict() if regime else {}),
    )
