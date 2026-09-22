"""Trade Scenarios layer — ADDITIVE ONLY, explanatory/contextual.

Answers "what happens next" from the CURRENT price and structure: breakout,
breakout+retest, pullback, failed breakout, breakdown. This NEVER issues its
own BUY/WAIT/AVOID or SELL signal, and never overrides the existing one
(risk.py). A "FAILED" or "INVALIDATED" scenario state here is descriptive
context, not a new trading action.

Reuse, not recomputation: every price level here is read from the SAME
entry_levels dict the existing entry optimizer (engines/entry.py) already
computed and attached to the plan (plan["entry_levels"]) -- the nearest
resistance/support, ATR, volume ratio, structure phase, reclaimed/swept
flags, and (when the chosen setup actually is a confirmation-breakout) the
existing confirmation_entry/stop. This guarantees a scenario's numbers can
never disagree with the numbers the risk engine itself is standing behind.
When entry_levels is empty (the risk engine returned WAIT before running the
entry optimizer at all -- e.g. missing data), this module falls back to
reading structure/pivots directly from the candles, same as
engines/long_term_plan.py already does, so scenarios stay available even
though the tradeable-setup gate never fired.

Scenario "state" is a small, explicit state machine (spec section 14):
    WATCHING -> TRIGGERED -> CONFIRMED -> RETESTING -> VALIDATED
                                                     `-> FAILED / INVALIDATED
No probabilities, no invented numbers: a scenario key is entirely omitted
when there isn't real structure to hang it on (spec section 22).
"""
from __future__ import annotations

import pandas as pd

from . import indicators as ind
from . import structure as structure_engine

_MIN_BARS = 30


def _dp(price: float) -> int:
    return 2 if abs(price) >= 1 else 4


def _r(x):
    return None if x is None else round(float(x), _dp(x))


def _fallback_levels(df: pd.DataFrame, price: float) -> dict:
    """Same shape as the subset of entry.py's `levels` this module needs,
    computed independently only when the risk engine didn't run the entry
    optimizer (see module docstring). Mirrors entry.py's own tolerance/window
    choices for consistency, but is a separate read, never mutating theirs."""
    atr_v = ind.last(ind.atr(df)) or (price * 0.02)
    try:
        st = structure_engine.detect_structure(df)
        phase, reclaimed, swept = st.phase, st.reclaimed, st.swept
    except Exception:
        phase, reclaimed, swept = None, False, False
    highs, lows = ind.pivots(df, left=3, right=3)
    tol = max(atr_v * 0.6, price * 0.005)
    res_prices = [h["price"] for h in highs if h["price"] > price * 0.999]
    sup_prices = [l["price"] for l in lows if l["price"] < price * 1.001]
    resistances = sorted(z["price"] for z in ind.cluster_levels(res_prices, tol))
    supports = sorted(z["price"] for z in ind.cluster_levels(sup_prices, tol))
    vol_ratio = None
    if len(df) >= 20:
        base = float(df["volume"].tail(20).mean()) or None
        vol_ratio = float(df["volume"].tail(3).mean()) / base if base else None
    return {
        "atr": atr_v, "resistances": [_r(p) for p in resistances][:4],
        "supports": [_r(p) for p in supports][-4:], "phase": phase,
        "reclaimed": reclaimed, "swept": swept, "volume_ratio": vol_ratio,
        "confirmation_entry": None, "stop": None, "entry_type": None,
    }


def _bars_beyond(closes: pd.Series, level: float, *, above: bool) -> int:
    """How many of the most recent consecutive bars closed beyond `level`."""
    n = 0
    for c in reversed(closes.tolist()):
        ok = (c > level) if above else (c < level)
        if not ok:
            break
        n += 1
    return n


def _breakout_scenario(df, price, atr_v, resistance, plan_dict, tc_hint) -> dict:
    closes = df["close"].astype(float)
    bars_above = _bars_beyond(closes, resistance, above=True)
    if price <= resistance:
        state = "WATCHING"
    elif bars_above == 1:
        state = "TRIGGERED"
    else:
        state = "CONFIRMED"

    entry_type = (plan_dict or {}).get("entry_type")
    confirmation_entry = (plan_dict or {}).get("confirmation_entry")
    stop = (plan_dict or {}).get("stop") if entry_type == "confirmation" else None

    confirmation = ["Price closes above resistance"]
    vol_status = (tc_hint or {}).get("volume_status")
    if vol_status and vol_status != "Unavailable":
        confirmation.append("Volume confirmation (above-average volume on the breakout bar)")
    mom_status = (tc_hint or {}).get("macd_status")
    if mom_status and mom_status != "Unavailable":
        confirmation.append("Momentum confirmation (MACD/RSI supportive)")

    return {
        "resistance": _r(resistance),
        "trigger": f"Close above {_r(resistance)}",
        "confirmation": confirmation,
        "entry": _r(confirmation_entry),
        "entry_note": None if confirmation_entry is not None else
                     "Entry will be set by the entry optimizer once this triggers.",
        "risk_stop": _r(stop),
        "risk_note": None if stop is not None else
                    "Stop will be set by the existing risk engine once this setup is chosen.",
        "state": state,
    }


def _retest_scenario(df, price, atr_v, resistance, breakout_state, reclaimed) -> dict | None:
    if breakout_state == "WATCHING" and not reclaimed:
        return None   # no breakout evidence at all yet -- nothing to retest
    zone_low = resistance - 0.25 * atr_v
    zone_high = resistance + 0.5 * atr_v
    closes = df["close"].astype(float)
    last = float(closes.iloc[-1])

    if zone_low <= last <= zone_high:
        state, status = "RETESTING", "Testing"
    elif last > zone_high:
        # already back above the zone -- did it dip into the zone and hold recently?
        recent = closes.tail(8)
        touched = ((recent >= zone_low) & (recent <= zone_high)).any()
        if touched:
            state, status = "VALIDATED", "Confirmed"
        else:
            state, status = ("CONFIRMED" if breakout_state == "CONFIRMED" else "TRIGGERED"), "Waiting for confirmation"
    else:  # last < zone_low: broke back below the old resistance
        state, status = "FAILED", "Failed"

    return {
        "resistance": _r(resistance),
        "retest_zone": [_r(zone_low), _r(zone_high)],
        "confirmation": ["Price holds the zone", "No confirmed breakdown below the zone",
                         "Volume stabilizes or improves", "Momentum remains supportive"],
        "status": status,
        "state": state,
    }


def _pullback_scenario(df, price, atr_v, supports, entry_levels, plan_dict) -> dict | None:
    extended = (plan_dict or {}).get("chase") == "do_not_chase"
    vah = entry_levels.get("vah")
    if not extended and vah:
        extended = price > vah * 1.05
    if not extended:
        return None
    if not supports:
        return None
    support = supports[-1]
    zone_low, zone_high = support, support + 0.5 * atr_v

    basis_bits = ["previous support"]
    poc, val = entry_levels.get("poc"), entry_levels.get("val")
    if val is not None and zone_low - atr_v * 0.5 <= val <= zone_high + atr_v * 0.5:
        basis_bits.append("VAL")
    if poc is not None and zone_low - atr_v * 0.5 <= poc <= zone_high + atr_v * 0.5:
        basis_bits.append("POC")

    closes = df["close"].astype(float)
    last = float(closes.iloc[-1])
    if zone_low <= last <= zone_high:
        state, status = "RETESTING", "Watch"
    elif last < zone_low * 0.99:
        state, status = "FAILED", "Support broken"
    else:
        state, status = "WATCHING", "Watch"

    return {
        "zone": [_r(zone_low), _r(zone_high)],
        "basis": " / ".join(basis_bits),
        "confirmation": ["Support holds", "Bullish structure resumes", "Momentum stabilizes"],
        "status": status,
        "state": state,
    }


def _failed_breakout_scenario(df, price, level) -> dict | None:
    if level is None:
        return None
    recent = df["close"].astype(float).tail(20)
    broke_above = bool((recent > level).any())
    if not broke_above or price >= level:
        return None
    return {
        "level": _r(level),
        "status": "Invalidated",
        "reason": f"Price reclaimed {_r(level)} temporarily but failed to hold above it.",
        "action": "No new entry / wait for a new setup.",
        "state": "FAILED",
    }


def _breakdown_scenario(df, price, atr_v, support) -> dict | None:
    if support is None:
        return None
    closes = df["close"].astype(float)
    bars_below = _bars_beyond(closes, support, above=False)
    state = "WATCHING" if bars_below == 0 else ("TRIGGERED" if bars_below == 1 else "CONFIRMED")
    return {
        "support": _r(support),
        "trigger": f"Close below {_r(support)}",
        "confirmation": ["Close below support", "Volume confirmation where available",
                         "Momentum deterioration"],
        "result": "Setup invalidated / avoid new entry" if state != "WATCHING" else None,
        "state": state,
    }


def build(df: pd.DataFrame, current_price: float | None, plan_dict: dict | None,
          tc: dict | None = None) -> dict:
    """Build the additive trade_scenarios object. Never raises."""
    try:
        return _build(df, current_price, plan_dict, tc)
    except Exception:
        return {"available": False, "reason": "Insufficient data for trade scenarios."}


def _build(df: pd.DataFrame, current_price, plan_dict, tc) -> dict:
    if df is None or len(df) < _MIN_BARS or current_price is None or current_price <= 0:
        return {"available": False, "reason": "Insufficient data for trade scenarios."}

    price = float(current_price)
    entry_levels = (plan_dict or {}).get("entry_levels") or {}
    levels = entry_levels if entry_levels else _fallback_levels(df, price)

    atr_v = levels.get("atr") or (price * 0.02)
    resistances = [p for p in (levels.get("resistances") or []) if p is not None]
    supports = [p for p in (levels.get("supports") or []) if p is not None]

    out: dict = {"available": True}

    breakout = None
    if resistances:
        breakout = _breakout_scenario(df, price, atr_v, resistances[0], plan_dict, tc)
        out["breakout"] = breakout

    if resistances:
        retest = _retest_scenario(df, price, atr_v, resistances[0],
                                  breakout["state"] if breakout else "WATCHING",
                                  bool(levels.get("reclaimed")))
        if retest:
            out["breakout_retest"] = retest

    pullback = _pullback_scenario(df, price, atr_v, supports, levels, plan_dict)
    if pullback:
        out["pullback"] = pullback

    failed = _failed_breakout_scenario(df, price, resistances[0] if resistances else None)
    if failed:
        out["failed_breakout"] = failed

    if supports:
        breakdown = _breakdown_scenario(df, price, atr_v, supports[-1])
        if breakdown:
            out["breakdown"] = breakdown

    return out
