"""Risk engine — the single source of ENTRY / STOP / TARGET / R:R / CONFIDENCE.

This is where the anti-fabrication rule is *enforced*, not just intended:

  * Every number is derived from strategy signals + candle-based ATR. Nothing
    is invented.
  * If required data is missing, or no reference price exists, or the regime
    conflicts with the objective, the engine returns WAIT / AVOID with reasons
    instead of manufacturing a plan.
  * CONFIDENCE is a transparent rubric (five named sub-scores), never a
    probability of profit.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..domain import (
    Action, Bias, Bucket, Objective, OBJECTIVE_META, Provenance, RegimeSnapshot, Trend,
)
from ..domain import StrategySignal
from . import indicators as ind
from . import entry as entry_engine


@dataclass
class ConfidencePart:
    key: str
    value: float
    note: str


@dataclass
class TradePlan:
    action: Action
    reason: str
    why: str
    entry: float | None = None                    # = entry_ref (the price R:R uses)
    stop: float | None = None
    target: float | None = None                   # = tp1 (kept for back-compat)
    rr: float | None = None
    est_time: str | None = None
    confidence_score: int = 0
    confidence_parts: list[ConfidencePart] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    provenance: list[Provenance] = field(default_factory=list)
    # ---- entry-optimizer fields (WHERE to buy, not just the current price) ----
    current_price: float | None = None
    optimal_zone: list[float] | None = None
    entry_type: str | None = None                 # "retest" | "confirmation"
    confirmation_entry: float | None = None
    stop_basis: str = ""
    tp1: float | None = None
    tp2: float | None = None
    expected_return_pct: float | None = None
    expected_return_tp2_pct: float | None = None
    chase: str = "ok"                             # "ok" | "do_not_chase"
    est_tp1: str | None = None
    est_tp2: str | None = None
    entry_levels: dict = field(default_factory=dict)
    entry_notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "action": self.action.value,
            "reason": self.reason,
            "why": self.why,
            "entry": self.entry,
            "stop": self.stop,
            "target": self.target,
            "rr": self.rr,
            "est_time": self.est_time,
            "confidence": {
                "score": self.confidence_score,
                "parts": [{"key": p.key, "value": round(p.value, 3), "note": p.note} for p in self.confidence_parts],
            },
            "missing": self.missing,
            "provenance": [p.as_dict() for p in self.provenance],
            # entry-optimizer surface
            "current_price": self.current_price,
            "optimal_zone": self.optimal_zone,
            "entry_type": self.entry_type,
            "confirmation_entry": self.confirmation_entry,
            "stop_basis": self.stop_basis,
            "tp1": self.tp1,
            "tp2": self.tp2,
            "expected_return_pct": self.expected_return_pct,
            "expected_return_tp2_pct": self.expected_return_tp2_pct,
            "chase": self.chase,
            "est_tp1": self.est_tp1,
            "est_tp2": self.est_tp2,
            "entry_levels": self.entry_levels,
            "entry_notes": self.entry_notes,
        }


def _round_px(price: float) -> int:
    return 2 if price >= 1 else 4


def _confidence(data_completeness: float, timeframe_agreement: float,
                level_clarity: float, regime: RegimeSnapshot | None,
                bias: Bias) -> tuple[int, list[ConfidencePart]]:
    liquidity = {Bucket.LOW: 0.4, Bucket.MEDIUM: 0.7, Bucket.HIGH: 0.95}.get(
        regime.liquidity if regime else Bucket.MEDIUM, 0.7)
    # Regime fit: does the trade direction agree with the trend?
    if regime is None:
        regime_fit = 0.6
    elif regime.trend == Trend.SIDEWAYS:
        regime_fit = 0.6
    elif (regime.trend == Trend.UP and bias == Bias.LONG) or (regime.trend == Trend.DOWN and bias == Bias.SHORT):
        regime_fit = 0.9
    else:
        regime_fit = 0.3
    parts = [
        ConfidencePart("data_completeness", data_completeness, "Share of requested data actually provided."),
        ConfidencePart("timeframe_agreement", timeframe_agreement, "Do the timeframes point the same way."),
        ConfidencePart("level_clarity", level_clarity, "How clean the entry/stop levels are."),
        ConfidencePart("liquidity", liquidity, "How tradable the asset is (from market data)."),
        ConfidencePart("regime_fit", regime_fit, "Does the plan agree with the current trend."),
    ]
    avg = sum(p.value for p in parts) / len(parts)
    return round(avg * 5), parts


def build_plan(
    *,
    objective: Objective,
    signals: list[StrategySignal],
    primary_candles: pd.DataFrame | None,
    reference_price: float | None,
    regime: RegimeSnapshot | None,
    required_inputs: list[str],
    provided_inputs: list[str],
    timeframes_provided: int = 1,
) -> TradePlan:
    meta = OBJECTIVE_META[objective]
    missing = [i for i in required_inputs if i not in provided_inputs]
    data_completeness = (len(required_inputs) - len(missing)) / len(required_inputs) if required_inputs else 1.0

    # ---- Gate 1: missing data -> WAIT (do not fabricate) --------------------
    if missing:
        score, parts = _confidence(data_completeness, 0.5, 0.4, regime, Bias.NEUTRAL)
        return TradePlan(
            action=Action.WAIT,
            reason="Some required data is missing.",
            why="ApexInvest builds levels only from data you provide. Add the items listed and re-run.",
            confidence_score=score, confidence_parts=parts, missing=[i for i in missing],
        )

    # ---- Gate 2: objective conflicts with the market regime -> AVOID --------
    # Buying to hold *up* while the market trends *down* is a conflict between
    # the goal and the regime, independent of any momentary signal.
    longish = objective in (Objective.LONG_TERM, Objective.SWING, Objective.INCOME)
    if regime and regime.trend == Trend.DOWN and longish:
        score, parts = _confidence(data_completeness, 0.5, 0.5, regime, Bias.LONG)
        return TradePlan(
            action=Action.AVOID,
            reason="A long objective conflicts with a downtrend.",
            why="Buying into a falling market fights the regime. Stand aside until the trend stabilises.",
            confidence_score=score, confidence_parts=parts,
        )

    # ---- Determine the dominant signal --------------------------------------
    usable = [s for s in signals if s.quality >= 0.3 and s.bias != Bias.NEUTRAL]
    if not usable:
        score, parts = _confidence(data_completeness, 0.5, 0.4, regime, Bias.NEUTRAL)
        return TradePlan(
            action=Action.WAIT,
            reason="No strategy produced a confident directional signal.",
            why="The setup is unclear right now. Waiting for a cleaner signal is the honest call.",
            confidence_score=score, confidence_parts=parts,
        )
    primary = max(usable, key=lambda s: s.quality)
    bias = primary.bias

    # Timeframe agreement: fraction of usable signals sharing the dominant bias.
    same = sum(1 for s in usable if s.bias == bias)
    timeframe_agreement = same / len(usable)

    # ---- Gate 3: signal points down while the objective is long -> WAIT -----
    if bias == Bias.SHORT and longish:
        score, parts = _confidence(data_completeness, timeframe_agreement, 0.5, regime, bias)
        return TradePlan(
            action=Action.WAIT,
            reason="The recent move is downward, which works against a buy-and-hold goal.",
            why="You're aiming to hold for gains, but the price is currently sliding. The honest call is "
                "to wait for the trend to turn back up before committing — no buy plan is forced.",
            confidence_score=score, confidence_parts=parts,
        )

    # ---- Confluence: how many directional methods agree with the plan -------
    agree_ids = [s.strategy_id for s in usable if s.bias == bias]
    n_agree, n_dir = len(agree_ids), len(usable)
    confluence = f"{n_agree} of {n_dir} method{'s' if n_dir != 1 else ''} agree ({', '.join(agree_ids)})."
    majority = (n_agree / n_dir) >= 0.6 if n_dir else False
    enough = n_agree >= 2 or (n_dir == 1 and primary.quality >= 0.7)
    confluent = majority and enough

    min_rr = meta["min_rr"]

    # ---- Entry OPTIMIZATION -------------------------------------------------
    # The old engine used the current price as the entry. That is wrong: the
    # current price and the optimal entry are different questions. The entry
    # optimizer answers "WHERE is the best place to buy, given the structure?"
    # and returns NO TRADE / DO NOT CHASE instead of forcing a buy at the top.
    if primary_candles is None or len(primary_candles) < 30:
        score, parts = _confidence(data_completeness, timeframe_agreement, 0.4, regime, bias)
        return TradePlan(
            action=Action.WAIT,
            reason="Not enough price history to locate a structural entry.",
            why="Optimal entry, structural stop and targets are built from candles. "
                "Need ~30+ daily bars; fewer are available.",
            confidence_score=score, confidence_parts=parts,
            current_price=reference_price,
        )

    ep = entry_engine.optimize_entry(
        primary_candles, min_rr=min_rr, atr_stop_mult=meta.get("atr_stop", 1.0))
    ed = ep.as_dict()
    cp = ed["current_price"]                     # already rounded to the tick

    # No location clears the bar -> WAIT / NO TRADE. Show context levels (POC,
    # value area, supports) for transparency, but no actionable trade levels.
    if ep.no_trade:
        score, parts = _confidence(data_completeness, timeframe_agreement,
                                   0.4, regime, bias)
        return TradePlan(
            action=Action.WAIT,
            reason=ep.reason,
            why=f"{confluence} No entry with acceptable risk is available, so the honest "
                "call is to stand aside rather than force a trade.",
            confidence_score=score, confidence_parts=parts,
            current_price=cp, entry_levels=ed["levels"], chase=ed["chase"],
        )

    # A valid structural setup exists. Confidence uses the setup quality as the
    # level-clarity sub-score, so a clean base with tight risk scores higher.
    level_clarity = round(0.4 + 0.5 * ep.setup_quality, 3)
    score, parts = _confidence(data_completeness, timeframe_agreement, level_clarity, regime, bias)

    # BUY only when the reward:risk clears the bar, confidence is adequate AND a
    # majority of methods concur. Otherwise WAIT — never a forced buy.
    tradeable = ep.rr is not None and ep.rr >= min_rr and score >= 3 and confluent
    action = Action.BUY if tradeable else Action.WAIT

    common = dict(
        current_price=cp,
        optimal_zone=ed["optimal_zone"], entry_type=ed["entry_type"],
        confirmation_entry=ed["confirmation_entry"], stop_basis=ed["stop_basis"],
        tp1=ed["tp1"], tp2=ed["tp2"],
        expected_return_pct=ed["expected_return_pct"],
        expected_return_tp2_pct=ed["expected_return_tp2_pct"],
        chase=ed["chase"], est_tp1=ed["est_tp1"], est_tp2=ed["est_tp2"],
        entry_levels={**ed["levels"], "setup_quality": ed["setup_quality"]},
        entry_notes=ed["notes"],
    )

    if not tradeable:
        reason = (f"Only a partial case ({n_agree}/{n_dir} methods, {score}/5, "
                  f"{ep.rr:.1f}:1) — worth waiting for a cleaner setup.")
        why = (f"{confluence} A structural entry exists ({ed['entry_type']}), but the "
               "method agreement, reward-to-risk or confidence is below the bar for this "
               "objective — so no buy is forced.")
        # WAIT means no plan: show current price + context levels only, never a
        # half-built set of trade numbers the app isn't standing behind.
        return TradePlan(
            action=Action.WAIT, reason=reason, why=why,
            confidence_score=score, confidence_parts=parts,
            current_price=cp, entry_levels=ed["levels"], chase=ed["chase"],
        )

    chase_note = " — but DO NOT CHASE: wait for the zone." if ep.chase == "do_not_chase" else ""
    zone_txt = (f"{ed['optimal_zone'][0]}-{ed['optimal_zone'][1]}" if ed["optimal_zone"]
                else f"above {ed['confirmation_entry']}")
    reason = (f"{n_agree}/{n_dir} methods agree; {ed['entry_type']} entry at {zone_txt} "
              f"gives {ep.rr:.1f}:1 to {ed['tp1']}{chase_note}")
    why = (f"{confluence} {primary.notes} Enter {zone_txt} (not the current {cp}); risk to "
           f"{ed['stop']} ({ed['stop_basis']}), targets {ed['tp1']} / {ed['tp2']} — "
           f"{ep.rr:.1f}:1, about {ed['est_tp1']} to TP1.")

    return TradePlan(
        action=Action.BUY, reason=reason, why=why,
        entry=ed["entry_ref"], stop=ed["stop"], target=ed["tp1"], rr=ed["rr"],
        est_time=ed["est_tp1"] or meta["est_time"],
        confidence_score=score, confidence_parts=parts, **common,
        provenance=[
            Provenance("computed:optimal_entry",
                       f"{ed['entry_type']} entry {ed['entry_ref']} from structure (not current price {cp})"),
            Provenance("computed:structural_stop", ed["stop_basis"]),
            Provenance("computed:targets", f"TP1 {ed['tp1']}, TP2 {ed['tp2']} from resistances/measured move"),
            *primary.provenance,
        ],
    )
