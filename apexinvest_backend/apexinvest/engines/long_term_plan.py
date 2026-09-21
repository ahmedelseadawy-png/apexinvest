"""Long-Term Investment Target Engine — ADDITIVE ONLY.

This module never touches the existing 9 strategies, the BUY/WAIT/AVOID risk
engine, market-regime detection, the entry optimizer, or confidence scoring.
It only *reads* their pure outputs (regime.detect_regime, structure.detect_structure
and the shared indicators library) to build a genuinely separate, longer-horizon
view of the SAME candles: a multi-month roadmap (targets, accumulation zones,
invalidation) that sits alongside — never replaces — the existing short-term
plan.

Why a separate read of structure, instead of reusing entry.py/structure.py's
window: those engines deliberately anchor to the *current* short-term leg
(~130 daily bars max) for a tradeable setup. A long-term investment thesis
needs the opposite: swing highs/lows over as much history as is available, so
this module looks at the FULL candle history handed to it.

Anti-fabrication, same rule as the rest of the app: every target/zone/level is
derived from an actual pivot, volume-profile level, or moving average found in
the data. When there isn't enough real structure for a given target, it is
OMITTED — never invented. When there isn't enough history at all, the whole
plan reports enabled=False with an honest reason; it never raises, so a single
symbol's long-term read can never fail the rest of the analysis.

Contract:
    build(df, current_price) -> dict   (see LONG_TERM_PLAN keys below)
"""
from __future__ import annotations

import pandas as pd

from . import indicators as ind
from . import regime as regime_engine
from . import structure as structure_engine

_MIN_BARS = 60           # need a real multi-month base to say anything honest
_MIN_BARS_MAJOR_TARGET = 250   # ~1 trading year, for the optional 4th target

INSUFFICIENT_DATA_MSG = "Long-term targets cannot be calculated reliably from the available data."

# Coarse, user-facing horizon buckets for the overall investment_horizon (the
# three the product spec calls out explicitly) and finer per-target buckets.
_OVERALL_BUCKETS = [(6, "3–6 months", 3, 6),
                     (12, "6–12 months", 6, 12),
                     (None, "12–18 months", 12, 18)]
_TARGET_BUCKETS = [
    (2, "1–2 months", 1, 2),
    (4, "2–4 months", 2, 4),
    (7, "4–7 months", 4, 7),
    (12, "7–12 months", 7, 12),
    (18, "12–18 months", 12, 18),
    (None, "18+ months", 18, 24),
]


def _dp(price: float) -> int:
    return 2 if abs(price) >= 1 else 4


def _r(x):
    return None if x is None else round(float(x), _dp(x))


def _estimate_months(distance: float, atr_v: float) -> float:
    """Honest, non-precise pacing: same ATR-per-session assumption entry.py
    uses for its short-term time-to-target, converted to months (~21 trading
    sessions/month). This is explicitly a rough pace, not a prediction."""
    pace = max(atr_v * 0.6, 1e-9)
    sessions = distance / pace
    return sessions / 21.0


def _bucket(months: float, table: list[tuple]) -> tuple[int, int, str]:
    for ceiling, label, lo, hi in table:
        if ceiling is None or months <= ceiling:
            return lo, hi, label
    lo, hi, label = table[-1][2], table[-1][3], table[-1][1]
    return lo, hi, label


def _confidence_from_touches(count: int) -> str:
    if count >= 3:
        return "HIGH"
    if count == 2:
        return "MEDIUM"
    return "LOW"


def _outlook(df: pd.DataFrame, price: float, ema50, ema200, n_targets_above: int) -> tuple[str, list[str]]:
    """Transparent additive scoring (mirrors the spirit of risk.py's confidence
    rubric, but is a wholly separate, non-conflicting read): a few named,
    auditable signals, summed, mapped to Constructive/Neutral/Weak. This NEVER
    feeds or overrides the existing BUY/WAIT/AVOID decision."""
    score = 0
    reasons: list[str] = []
    try:
        reg = regime_engine.detect_regime(df) if len(df) >= 30 else None
    except Exception:
        reg = None

    if reg is not None:
        if reg.trend.value == "up":
            score += 1; reasons.append("medium-term trend is up")
        elif reg.trend.value == "down":
            score -= 1; reasons.append("medium-term trend is down")
    if ema200 is not None:
        if price > ema200:
            score += 1; reasons.append("price is above the 200-day EMA")
        else:
            score -= 1; reasons.append("price is below the 200-day EMA")
    if ema50 is not None and ema200 is not None:
        if ema50 > ema200:
            score += 1; reasons.append("50-day EMA is above the 200-day EMA")
        else:
            score -= 1; reasons.append("50-day EMA is below the 200-day EMA")
    if n_targets_above >= 2:
        score += 1; reasons.append(f"{n_targets_above} real resistance levels found above price")
    elif n_targets_above == 0:
        score -= 1; reasons.append("no real resistance structure found above price")

    if score >= 3:
        return "Constructive", reasons
    if score <= -1:
        return "Weak", reasons
    return "Neutral", reasons


def thesis_for(outlook: str, entry_status: str) -> str:
    """Public: combine the long-term outlook with the (unmodified, existing)
    entry_status into one honest sentence. See module docstring — section 5 of
    the spec: WAIT must never be read as "bad for long-term", it can simply
    mean the thesis is fine but today's entry timing isn't."""
    if outlook == "Constructive" and entry_status == "WAIT":
        return ("The higher-timeframe structure remains constructive, but the current price "
                "does not offer sufficient reward-to-risk for a new entry.")
    if outlook == "Constructive" and entry_status == "BUY":
        return "The higher-timeframe structure is constructive and the current setup offers an actionable entry."
    if outlook == "Constructive" and entry_status == "AVOID":
        return ("The higher-timeframe structure looks constructive on price alone, but current "
                "conditions argue against a new entry right now.")
    if outlook == "Weak":
        return ("The higher-timeframe structure is weak — the technical case for a long-term "
                "position is not supported right now, independent of today's entry timing.")
    return ("The higher-timeframe structure is mixed; there isn't a clear long-term technical "
            "edge from price structure alone right now.")


def build(df: pd.DataFrame, current_price: float | None) -> dict:
    """Build the additive long-term investment plan. Never raises: any
    unexpected condition degrades to enabled=False rather than breaking the
    caller's analysis."""
    try:
        return _build(df, current_price)
    except Exception:
        return {"enabled": False, "reason": INSUFFICIENT_DATA_MSG}


def _build(df: pd.DataFrame, current_price: float | None) -> dict:
    if df is None or len(df) < _MIN_BARS or current_price is None or current_price <= 0:
        return {"enabled": False, "reason": INSUFFICIENT_DATA_MSG}

    price = float(current_price)
    atr_v = ind.last(ind.atr(df)) or (price * 0.02)
    ema50 = ind.last(ind.ema(df["close"], 50))
    ema200 = ind.last(ind.ema(df["close"], 200)) if len(df) >= 200 else None

    highs, lows = ind.pivots(df, left=3, right=3)
    tol = max(atr_v * 1.5, price * 0.01)

    # ---- Long-term resistances (targets) over the FULL history --------------
    res_prices = [h["price"] for h in highs if h["price"] > price * 1.001]
    resistances = ind.cluster_levels(res_prices, tol)
    resistances.sort(key=lambda z: z["price"])

    targets: list[dict] = []
    for zone in resistances[:3]:
        months = _estimate_months(zone["price"] - price, atr_v)
        lo_m, hi_m, label = _bucket(months, _TARGET_BUCKETS)
        targets.append({
            "target_price": _r(zone["price"]),
            "expected_return_pct": round((zone["price"] / price - 1) * 100, 2),
            "estimated_horizon_min_months": lo_m,
            "estimated_horizon_max_months": hi_m,
            "estimated_horizon_label": label,
            "basis": (f"major resistance ({zone['count']} prior swing-high touch"
                      f"{'es' if zone['count'] != 1 else ''})" if zone['count'] >= 2
                      else "nearest meaningful resistance"),
            "confidence": _confidence_from_touches(zone["count"]),
        })

    # ---- Optional 4th ("major") target: a real, more distant resistance -----
    if len(df) >= _MIN_BARS_MAJOR_TARGET and len(resistances) >= 4:
        zone = resistances[3]
        months = _estimate_months(zone["price"] - price, atr_v)
        lo_m, hi_m, label = _bucket(months, _TARGET_BUCKETS)
        targets.append({
            "target_price": _r(zone["price"]),
            "expected_return_pct": round((zone["price"] / price - 1) * 100, 2),
            "estimated_horizon_min_months": lo_m,
            "estimated_horizon_max_months": hi_m,
            "estimated_horizon_label": label,
            "basis": "higher-timeframe structural target (major, longer-dated resistance)",
            "confidence": _confidence_from_touches(zone["count"]),
        })

    # ---- Fallback measured-move target when real structure is thin ----------
    # Only added when there is a genuine, already-computed base (structure.py's
    # own accumulation range) to measure from -- never a bare percentage guess.
    if len(targets) < 3:
        try:
            st = structure_engine.detect_structure(df)
        except Exception:
            st = None
        if st is not None and st.range_low is not None and st.range_high is not None:
            base_size = st.range_high - st.range_low
            if base_size > 0:
                measured = max(st.range_high, price) + base_size
                if measured > price * 1.02 and not any(
                        abs(t["target_price"] - measured) <= tol for t in targets):
                    months = _estimate_months(measured - price, atr_v)
                    lo_m, hi_m, label = _bucket(months, _TARGET_BUCKETS)
                    targets.append({
                        "target_price": _r(measured),
                        "expected_return_pct": round((measured / price - 1) * 100, 2),
                        "estimated_horizon_min_months": lo_m,
                        "estimated_horizon_max_months": hi_m,
                        "estimated_horizon_label": label,
                        "basis": "measured move / major structure (projected from the current base — not a confirmed resistance)",
                        "confidence": "LOW",
                    })

    targets.sort(key=lambda t: t["target_price"])
    targets = targets[:4]

    # ---- Accumulation zones ---------------------------------------------------
    sup_prices = [l["price"] for l in lows if l["price"] < price * 0.999]
    if ema50 is not None and ema50 < price:
        sup_prices.append(float(ema50))
    if ema200 is not None and ema200 < price:
        sup_prices.append(float(ema200))
    supports = ind.cluster_levels(sup_prices, tol)
    supports.sort(key=lambda z: -z["price"])   # nearest to price first

    accumulation_zones: list[dict] = []
    if supports:
        nearest = supports[0]
        basis_bits = [f"{nearest['count']} prior swing-low touch{'es' if nearest['count'] != 1 else ''}"]
        if ema50 is not None and nearest["lo"] <= ema50 <= nearest["hi"]:
            basis_bits.append("50-day EMA confluence")
        if ema200 is not None and nearest["lo"] <= ema200 <= nearest["hi"]:
            basis_bits.append("200-day EMA confluence")
        accumulation_zones.append({
            "zone_low": _r(nearest["lo"]), "zone_high": _r(nearest["hi"]),
            "basis": "major support (" + ", ".join(basis_bits) + ")",
            "confidence": _confidence_from_touches(nearest["count"]),
        })

    try:
        st2 = structure_engine.detect_structure(df)
    except Exception:
        st2 = None
    if st2 is not None and st2.val is not None and st2.vah is not None and st2.val < price:
        already_covered = any(z["zone_low"] <= st2.val <= z["zone_high"] for z in accumulation_zones)
        if not already_covered:
            accumulation_zones.append({
                "zone_low": _r(st2.val), "zone_high": _r(min(st2.vah, price)),
                "basis": f"value area / POC ({st2.poc_confidence} confidence structural read)",
                "confidence": st2.poc_confidence.upper(),
            })

    # ---- Long-term invalidation ------------------------------------------------
    invalidation = None
    invalidation_anchor = None
    invalidation_basis_bits = []
    if supports:
        invalidation_anchor = supports[-1]["lo"]   # the deepest/lowest support cluster found
        invalidation_basis_bits.append("major structural support")
    if ema200 is not None and (invalidation_anchor is None or ema200 < invalidation_anchor):
        invalidation_anchor = min(ema200, invalidation_anchor) if invalidation_anchor is not None else ema200
        invalidation_basis_bits.append("the 200-day EMA")
    if invalidation_anchor is not None:
        inv_price = invalidation_anchor - atr_v * 0.5
        invalidation = {
            "price": _r(inv_price),
            "basis": "Below " + " and ".join(invalidation_basis_bits),
            "confidence": "HIGH" if (supports and supports[-1]["count"] >= 2) or ema200 is not None else "MEDIUM",
        }

    # ---- Outlook + horizon ------------------------------------------------------
    outlook, outlook_reasons = _outlook(df, price, ema50, ema200, len(targets))

    if targets:
        max_hi = max(t["estimated_horizon_max_months"] for t in targets)
        h_lo, h_hi, h_label = _bucket(max_hi, _OVERALL_BUCKETS)
        horizon_confidence = "HIGH" if len(targets) >= 2 and any(
            t["confidence"] == "HIGH" for t in targets) else ("MEDIUM" if targets else "LOW")
    else:
        h_lo, h_hi, h_label = 12, 18, "12–18 months"
        horizon_confidence = "LOW"

    horizon = {
        "min_months": h_lo, "max_months": h_hi, "label": h_label,
        "confidence": horizon_confidence,
    }

    notes = []
    if not targets:
        notes.append(INSUFFICIENT_DATA_MSG)

    return {
        "enabled": True,
        "outlook": outlook,
        "outlook_reasons": outlook_reasons,
        "horizon": horizon,
        "accumulation_zones": accumulation_zones,
        "targets": [
            {k: v for k, v in t.items() if k not in ("estimated_horizon_label",)}
            for t in targets
        ],
        "invalidation": invalidation,
        "notes": notes,
    }
