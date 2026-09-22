"""Trend & Confirmation layer — ADDITIVE ONLY.

This is explicitly NOT a 10th strategy and NEVER feeds the existing
BUY/WAIT/AVOID decision (risk.py). It only *reads* already-computed evidence
(regime.py's RegimeSnapshot, risk.py's TradePlan/entry_levels, and the shared
indicators library) and aggregates it into one transparent "how much does the
technical picture agree with itself" read, plus a plain-language explanation
of what is confirmed, what is missing, and what would change the picture.

METHODOLOGY (confirmation_score, 0-100) — read this before changing weights.

Six evidence groups, each with a fixed weight that sums to 100:

    Structure ......... 25   (market-structure phase: markup/reclaim/accumulation/
                               distribution — from structure.detect_structure)
    Trend / EMA ....... 20   (EMA20/50/200 stack + price position)
    Momentum .......... 20   (RSI + MACD + MACD histogram direction, combined
                               into ONE group deliberately — see below)
    Strength (ADX) .... 15
    Volume ............ 10
    Market alignment .. 10   (stock trend vs EGX30/EGX70 — always "Unavailable"
                               today since no market-context feed exists yet;
                               excluded from scoring until it does, never
                               fabricated)

Momentum groups RSI + MACD + histogram direction together on purpose (per
spec): MACD is itself derived from EMAs, so scoring it as a second
independent "trend" group would double-count the same underlying evidence
the EMA group already used. Keeping it one group with weight 20, not two
groups with combined weight 40, avoids that.

Structure and Trend/EMA each produce a SIGNED lean in [-1, +1] (bearish..
bullish) — these two decide `primary_trend`. Momentum also produces a signed
lean. ADX and Volume are magnitude-only (they have no direction of their
own — a strong ADX or confirming volume is evidence of *something*
happening, not evidence of *which* direction), so they score on their own
merit rather than being direction-gated.

For a signed group, "agreement" with the primary trend is:
    agreement = 0.5                          if primary_trend is Neutral/Mixed
                                              (nothing to confirm or deny —
                                               neutral credit, not zero, so a
                                               single ambiguous read doesn't
                                               collapse the whole score)
    agreement = max(0, lean * primary_sign)  otherwise (0 if it actively
                                              disagrees, up to 1 if fully
                                              aligned)

A group with no data (e.g. <200 bars for EMA200, market context unavailable)
is EXCLUDED from both the achieved total and the possible total — never
scored as a fabricated zero or a free pass.

    confirmation_score = round(100 * sum(agreement_g * weight_g)
                                    / sum(weight_g))   over available groups

confirmation_strength buckets (spec-defined):
    0-29 Weak · 30-49 Low · 50-69 Moderate · 70-84 Strong · 85-100 Very Strong

This score is NOT a probability of profit, an expected return, or a
substitute for BUY/WAIT/AVOID — it only measures how much of the *available*
technical evidence points the same way. Keep that framing in any UI text.
"""
from __future__ import annotations

import pandas as pd

from . import indicators as ind
from . import structure as structure_engine

_MIN_BARS = 30

_WEIGHTS = {
    "structure": 25,
    "trend": 20,
    "momentum": 20,
    "strength": 15,
    "volume": 10,
    "market": 10,
}

_STRENGTH_BUCKETS = [
    (29, "Weak"), (49, "Low"), (69, "Moderate"), (84, "Strong"), (None, "Very Strong"),
]


def _bucket(score: int) -> str:
    for ceiling, label in _STRENGTH_BUCKETS:
        if ceiling is None or score <= ceiling:
            return label
    return _STRENGTH_BUCKETS[-1][1]


def _label_from_sign(sign: float, *, neutral_band: float = 0.15) -> str:
    if sign is None:
        return "Unavailable"
    if sign >= 0.6:
        return "Bullish"
    if sign <= -0.6:
        return "Bearish"
    if -neutral_band <= sign <= neutral_band:
        return "Neutral"
    return "Mixed"


def _agreement(lean, primary_sign: int) -> float:
    if lean is None:
        return None
    if primary_sign == 0:
        return 0.5
    return max(0.0, lean * primary_sign)


def _structure_read(df: pd.DataFrame, entry_levels: dict | None) -> dict:
    """Phase from structure.detect_structure — reused from entry_levels when the
    risk engine already ran (no recomputation), else read independently."""
    if entry_levels and entry_levels.get("phase"):
        phase = entry_levels["phase"]
        dist_warn = bool(entry_levels.get("distribution_warning"))
    else:
        try:
            st = structure_engine.detect_structure(df)
            phase, dist_warn = st.phase, st.distribution_warning
        except Exception:
            phase, dist_warn = None, False

    mapping = {
        "markup": (1.0, "Bullish"),
        "reclaim": (0.7, "Bullish"),
        "accumulation": (0.0, "Neutral"),
        "manipulation": (-0.3, "Mixed"),
        "distribution": (-0.7, "Bearish"),
    }
    if phase in mapping:
        lean, label = mapping[phase]
        if phase == "markup" and dist_warn:
            lean, label = 0.3, "Mixed"   # markup but supply warning -> less clean
        return {"lean": lean, "label": label}
    return {"lean": None, "label": "Unavailable"}


def _ema_read(close: pd.Series) -> dict:
    ema20 = ind.last(ind.ema(close, 20))
    ema50 = ind.last(ind.ema(close, 50))
    ema200 = ind.last(ind.ema(close, 200)) if len(close) >= 200 else None
    price = float(close.iloc[-1])
    if ema20 is None or ema50 is None:
        return {"lean": None, "label": "Unavailable"}
    checks = [price > ema20, ema20 > ema50]
    if ema200 is not None:
        checks.append(ema50 > ema200)
    bulls = sum(checks)
    n = len(checks)
    if bulls == n:
        lean = 1.0
    elif bulls == 0:
        lean = -1.0
    else:
        lean = (bulls / n - 0.5) * 2   # spreads (0..n)/n around 0
    return {"lean": lean, "label": _label_from_sign(lean)}


def _momentum_read(close: pd.Series) -> dict:
    rsi_s = ind.rsi(close, 14)
    rsi = ind.last(rsi_s)
    macd_line, signal_line, hist = ind.macd(close)
    last_macd, last_sig = ind.last(macd_line), ind.last(signal_line)
    hist_valid = hist.dropna()
    last_hist = float(hist_valid.iloc[-1]) if len(hist_valid) else None
    prev_hist = float(hist_valid.iloc[-2]) if len(hist_valid) >= 2 else None

    subs = []
    if rsi is not None:
        subs.append(1.0 if rsi > 55 else (-1.0 if rsi < 45 else 0.0))
    if last_macd is not None and last_sig is not None:
        subs.append(1.0 if last_macd > last_sig else -1.0)
    if last_hist is not None and prev_hist is not None:
        subs.append(1.0 if last_hist > prev_hist else -1.0)

    lean = sum(subs) / len(subs) if subs else None

    # Two SEPARATE display fields (RSI-flavoured vs MACD-flavoured), sharing
    # this one evidence group's weight for scoring -- see module docstring.
    if rsi is None:
        momentum_status = "Unavailable"
    elif rsi >= 70:
        momentum_status = "Overbought"
    elif rsi <= 30:
        momentum_status = "Oversold"
    elif rsi > 55:
        momentum_status = "Improving"
    elif rsi < 45:
        momentum_status = "Weakening"
    else:
        momentum_status = "Neutral"

    if last_macd is None or last_sig is None:
        macd_status = "Unavailable"
    elif last_macd > last_sig and (last_hist is None or last_hist >= 0):
        macd_status = "Bullish"
    elif last_macd < last_sig and (last_hist is None or last_hist <= 0):
        macd_status = "Bearish"
    elif last_hist is not None and prev_hist is not None and last_hist > prev_hist:
        macd_status = "Improving"
    elif last_hist is not None and prev_hist is not None and last_hist < prev_hist:
        macd_status = "Weakening"
    else:
        macd_status = "Neutral"

    return {"lean": lean, "momentum_status": momentum_status, "macd_status": macd_status}


def _adx_read(df: pd.DataFrame, regime_dict: dict | None) -> dict:
    adx = (regime_dict or {}).get("adx")
    if adx is None:
        adx = ind.last(ind.adx(df))
    if adx is None:
        return {"strength": None, "label": "Unavailable"}
    if adx >= 25:
        return {"strength": 1.0, "label": "Strong"}
    if adx >= 20:
        return {"strength": 0.5, "label": "Moderate"}
    return {"strength": 0.0, "label": "Weak"}


def _volume_read(df: pd.DataFrame, entry_levels: dict | None) -> dict:
    ratio = (entry_levels or {}).get("volume_ratio")
    if ratio is None:
        if len(df) < 20:
            ratio = None
        else:
            base = float(df["volume"].tail(20).mean()) or None
            ratio = float(df["volume"].tail(3).mean()) / base if base else None
    if ratio is None:
        return {"strength": None, "label": "Unavailable"}
    if ratio >= 1.2:
        return {"strength": 1.0, "label": "Confirming"}
    if ratio < 0.8:
        return {"strength": 0.0, "label": "Not Confirming"}
    return {"strength": 0.5, "label": "Neutral"}


def _short_term_trend(close: pd.Series) -> str:
    """A more reactive read than primary_trend: EMA20 slope + last-10-bar RSI
    momentum, both short-window. Independent of the primary/EMA200 read."""
    if len(close) < 25:
        return "Unavailable"
    ema20 = ind.ema(close, 20).dropna()
    if len(ema20) < 6:
        return "Unavailable"
    slope_up = float(ema20.iloc[-1]) > float(ema20.iloc[-6])
    rsi = ind.last(ind.rsi(close, 14))
    price_up = float(close.iloc[-1]) > float(close.iloc[-6])
    votes = [slope_up, price_up] + ([rsi > 50] if rsi is not None else [])
    bulls = sum(votes)
    n = len(votes)
    if bulls == n:
        return "Bullish"
    if bulls == 0:
        return "Bearish"
    if n >= 3 and bulls == 1:
        return "Bearish"
    if n >= 3 and bulls == 2:
        return "Bullish"
    return "Mixed"


def build(df: pd.DataFrame, regime_dict: dict | None, plan_dict: dict | None) -> dict:
    """Build the additive Trend & Confirmation object. Never raises."""
    try:
        return _build(df, regime_dict, plan_dict)
    except Exception:
        return {
            "primary_trend": "Unavailable", "short_term_trend": "Unavailable",
            "confirmation_score": None, "confirmation_strength": "Unavailable",
            "structure_status": "Unavailable", "ema_alignment": "Unavailable",
            "momentum_status": "Unavailable", "adx_status": "Unavailable",
            "macd_status": "Unavailable", "volume_status": "Unavailable",
            "market_alignment": "Unavailable",
            "confirmed_factors": [], "missing_factors": [],
            "summary": "Insufficient data to assess trend confirmation.",
        }


def _build(df: pd.DataFrame, regime_dict: dict | None, plan_dict: dict | None) -> dict:
    if df is None or len(df) < _MIN_BARS:
        return {
            "primary_trend": "Unavailable", "short_term_trend": "Unavailable",
            "confirmation_score": None, "confirmation_strength": "Unavailable",
            "structure_status": "Unavailable", "ema_alignment": "Unavailable",
            "momentum_status": "Unavailable", "adx_status": "Unavailable",
            "macd_status": "Unavailable", "volume_status": "Unavailable",
            "market_alignment": "Unavailable",
            "confirmed_factors": [], "missing_factors": [],
            "summary": "Not enough history to assess trend confirmation.",
        }

    close = df["close"].astype(float)
    entry_levels = (plan_dict or {}).get("entry_levels") or {}

    st_read = _structure_read(df, entry_levels)
    ema_read = _ema_read(close)
    mom_read = _momentum_read(close)
    adx_read = _adx_read(df, regime_dict)
    vol_read = _volume_read(df, entry_levels)

    reg_trend = (regime_dict or {}).get("trend")  # "up" | "sideways" | "down" | None
    ema_label = ema_read["label"]
    if ema_label == "Bullish" and reg_trend == "up":
        primary_trend = "Bullish"
    elif ema_label == "Bearish" and reg_trend == "down":
        primary_trend = "Bearish"
    elif ema_label == "Unavailable" and reg_trend is None:
        primary_trend = "Unavailable"
    elif reg_trend == "sideways" and ema_label == "Neutral":
        primary_trend = "Neutral"
    elif ema_label == "Unavailable":
        primary_trend = "Bullish" if reg_trend == "up" else ("Bearish" if reg_trend == "down" else "Neutral")
    else:
        primary_trend = "Mixed"

    primary_sign = {"Bullish": 1, "Bearish": -1}.get(primary_trend, 0)

    groups: dict[str, dict] = {}
    if st_read["lean"] is not None:
        groups["structure"] = {"agreement": _agreement(st_read["lean"], primary_sign)}
    if ema_read["lean"] is not None:
        groups["trend"] = {"agreement": _agreement(ema_read["lean"], primary_sign)}
    if mom_read["lean"] is not None:
        groups["momentum"] = {"agreement": _agreement(mom_read["lean"], primary_sign)}
    if adx_read["strength"] is not None:
        groups["strength"] = {"agreement": adx_read["strength"]}
    if vol_read["strength"] is not None:
        groups["volume"] = {"agreement": vol_read["strength"]}
    # "market" (EGX30/EGX70 alignment) has no data source today -- always
    # excluded from scoring rather than fabricated. See module docstring.

    total_possible = sum(_WEIGHTS[g] for g in groups)
    total_achieved = sum(_WEIGHTS[g] * v["agreement"] for g, v in groups.items())
    score = round(100 * total_achieved / total_possible) if total_possible else None
    strength = _bucket(score) if score is not None else "Unavailable"

    confirmed, missing = [], []
    def _note(name, label, agreement):
        if agreement is None:
            return
        if agreement >= 0.65:
            confirmed.append(f"{name}: {label}")
        elif agreement <= 0.35:
            missing.append(f"{name}: {label}")

    _note("Structure", st_read["label"], groups.get("structure", {}).get("agreement"))
    _note("EMA alignment", ema_read["label"], groups.get("trend", {}).get("agreement"))
    _note("Momentum", mom_read["momentum_status"], groups.get("momentum", {}).get("agreement"))
    _note("ADX", adx_read["label"], groups.get("strength", {}).get("agreement"))
    _note("Volume", vol_read["label"], groups.get("volume", {}).get("agreement"))

    if score is None:
        summary = "Not enough available evidence to assess trend confirmation."
    else:
        bits = []
        if confirmed:
            bits.append("confirmed by " + ", ".join(c.split(":")[0] for c in confirmed[:3]))
        if missing:
            bits.append("not yet confirmed by " + ", ".join(m.split(":")[0] for m in missing[:3]))
        detail = "; ".join(bits) if bits else "a mixed set of signals"
        summary = f"{primary_trend} trend with {strength.lower()} confirmation ({score}/100) — {detail}."

    return {
        "primary_trend": primary_trend,
        "short_term_trend": _short_term_trend(close),
        "confirmation_score": score,
        "confirmation_strength": strength,
        "structure_status": st_read["label"],
        "ema_alignment": ema_label,
        "momentum_status": mom_read["momentum_status"],
        "adx_status": adx_read["label"],
        "macd_status": mom_read["macd_status"],
        "volume_status": vol_read["label"],
        "market_alignment": "Unavailable",
        "confirmed_factors": confirmed,
        "missing_factors": missing,
        "summary": summary,
    }


def compose_wait_context(action: str, tc: dict, scenarios: dict | None) -> dict:
    """Additive "why am I waiting / what would change this" text (spec #7).
    Never touches plan.reason/plan.why -- this is a SEPARATE field built from
    trend_confirmation + trade_scenarios, only populated for WAIT."""
    if action != "WAIT":
        return {"applicable": False, "why": None, "next_trigger": None}

    missing = tc.get("missing_factors") or []
    primary = tc.get("primary_trend", "Unavailable")
    if primary in ("Bullish",) and missing:
        why = f"{primary} setup is developing, but " + missing[0].split(": ", 1)[-1].lower() + " is not yet confirming."
    elif primary in ("Bullish",):
        why = f"{primary} trend is present, but current price does not offer a low-risk entry."
    elif primary == "Mixed":
        why = "The evidence is mixed, so there is no confirmed directional edge yet."
    elif primary == "Bearish":
        why = "The trend is bearish, which works against a new long entry."
    else:
        why = "There is not yet enough confirming evidence for an entry."

    next_trigger = None
    scenarios = scenarios or {}
    for key in ("breakout", "breakout_retest", "pullback"):
        sc = scenarios.get(key)
        if sc and sc.get("trigger"):
            next_trigger = sc["trigger"]
            break
    if next_trigger is None and missing:
        next_trigger = "Improvement in: " + ", ".join(m.split(":")[0] for m in missing[:2])

    return {"applicable": True, "why": why, "next_trigger": next_trigger}
