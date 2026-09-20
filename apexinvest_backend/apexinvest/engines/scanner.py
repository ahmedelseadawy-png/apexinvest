"""EGX Opportunity Scanner (Update #3).

Runs the WHOLE supported EGX universe through the SAME analysis engine the app
uses for a single stock, then ranks the results by the QUALITY of the trade —
not by raw upside. A 7% setup with a tight stop, clean structure and good
liquidity ranks ABOVE a 15% setup that is extended, wide-stopped and illiquid.

Core principles (all inherited from the rest of the app):
  * The entry is the OPTIMAL entry from entry.py — never "buy at current price".
    Extended names are penalised (anti-chase), not rewarded for being today's
    biggest gainer.
  * NO TRADE is a valid, common result. The scanner is never forced to produce
    three buys. If nothing is clean, it says so.
  * Nothing is fabricated. Every number comes from daily candles. Model
    probabilities are labelled as estimates, not guarantees.
  * Daily data only (see structure.py) — the "fast" ranking is short-swing on
    daily bars, honestly labelled, not intraday day-trading we can't source.

The opportunity score is a transparent weighted blend of seven 0..1 sub-scores;
the weights are configurable and returned with the result.
"""
from __future__ import annotations

import bisect
import concurrent.futures as cf
import math
import time as _time
from dataclasses import dataclass

import pandas as pd

from ..domain import Objective
from . import indicators as ind

# Default weights (sum to 1.0). Configurable per call.
DEFAULT_WEIGHTS = {
    "expected_return": 0.20,   # upside from the OPTIMAL entry (not current price)
    "setup_quality": 0.25,     # probability / structure quality
    "risk_quality": 0.20,      # how tight & structural the stop is
    "rr": 0.15,                # reward-to-risk
    "time": 0.10,              # expected speed to target
    "liquidity": 0.05,         # tradability
    "momentum": 0.05,          # trend / relative strength
}

HORIZON_OBJECTIVE = {
    "intraday": Objective.SWING,       # no intraday feed -> honest short-swing
    "short_swing": Objective.SWING,
    "medium_swing": Objective.SWING,
    "long_term": Objective.LONG_TERM,
}
RETURN_REF = {Objective.SWING: 12.0, Objective.LONG_TERM: 28.0}  # % that scores ~1.0

# risk-appetite tuning: minimum reward:risk and how much extension is tolerated
RISK_PROFILE = {
    "conservative": {"min_rr": 2.2, "max_stop_frac": 0.08, "chase_penalty": 0.6},
    "balanced":     {"min_rr": 1.8, "max_stop_frac": 0.11, "chase_penalty": 0.75},
    "aggressive":   {"min_rr": 1.6, "max_stop_frac": 0.14, "chase_penalty": 0.9},
}

_BUCKET_SESSIONS = {"1-3 sessions": 2, "3-5 sessions": 4, "1-2 weeks": 8,
                    "2-4 weeks": 15, "1 month+": 25}


def _reason_code(err) -> str:
    """Classify why a symbol could not be analyzed, as a short machine code the
    UI maps to friendly bilingual text. Never fabricates — a symbol we couldn't
    reach is reported as unreached, not silently scored."""
    e = (err or "").lower()
    if not e:
        return "no_data"
    if "not enough" in e or "no data" in e or "dataunavailable" in e or "404" in e or "empty" in e:
        return "no_data"
    if "timeout" in e or "timed out" in e:
        return "timeout"
    if "429" in e or "rate" in e:
        return "rate_limited"
    return "error"


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _turnover(df: pd.DataFrame, lookback: int = 20) -> float:
    w = df.tail(lookback)
    return float((w["close"] * w["volume"]).mean())


def _momentum_20(df: pd.DataFrame) -> float:
    if len(df) < 21:
        return 0.0
    return float(df["close"].iloc[-1] / df["close"].iloc[-21] - 1.0)


def _liquidity_score(turnover: float) -> float:
    # log scale between ~1e5 and ~5e7 EGP average daily turnover
    if turnover <= 0:
        return 0.0
    return _clamp((math.log10(turnover) - 5.0) / (math.log10(5e7) - 5.0))


def _risk_level(stop_frac: float, poc_conf: str) -> str:
    if stop_frac <= 0.05 and poc_conf != "low":
        return "Low"
    if stop_frac <= 0.09:
        return "Medium"
    return "High"


@dataclass
class Scored:
    row: dict
    opportunity: float
    speed: float
    risk_adjusted: float


def score_plan(plan: dict, df: pd.DataFrame, objective: Objective,
               weights: dict, momentum: float) -> Scored | None:
    """Score one BUY plan into an opportunity row. Returns None for non-BUY."""
    if plan.get("action") != "BUY":
        return None
    entry = plan.get("entry"); stop = plan.get("stop"); tp1 = plan.get("tp1")
    rr = plan.get("rr") or 0.0
    exp_ret = plan.get("expected_return_pct") or 0.0
    if not (entry and stop and tp1) or entry <= stop:
        return None

    lv = plan.get("entry_levels", {}) or {}
    poc_conf = lv.get("poc_confidence", "medium")
    setup_q = float(lv.get("setup_quality") or 0.4)
    conf_score = ((plan.get("confidence") or {}).get("score") or 0) / 5.0
    stop_frac = (entry - stop) / entry
    turnover = _turnover(df)
    ref = RETURN_REF.get(objective, 12.0)

    # ---- 0..1 sub-scores ----------------------------------------------------
    s_ret = _clamp(exp_ret / ref)
    s_setup = _clamp(0.6 * setup_q + 0.4 * conf_score)
    s_riskq = _clamp((0.12 - stop_frac) / 0.10, 0.15, 1.0)
    s_rr = _clamp(rr / 3.0)
    sessions = _BUCKET_SESSIONS.get(plan.get("est_tp1"), 8)
    s_time = _clamp(1.0 - (sessions - 2) / 23.0, 0.1, 1.0)
    s_liq = _liquidity_score(turnover)
    s_mom = _clamp((momentum + 0.10) / 0.30)

    w = weights
    opp = 100.0 * (
        w["expected_return"] * s_ret + w["setup_quality"] * s_setup +
        w["risk_quality"] * s_riskq + w["rr"] * s_rr + w["time"] * s_time +
        w["liquidity"] * s_liq + w["momentum"] * s_mom)

    # Entry-style quality. A patient PULLBACK into support (retest) is a
    # better-priced, higher-probability entry than paying up for a breakout, so it
    # is rewarded; a CONFIRMATION (buy-above breakout) is discounted for its lower
    # base win-rate and chase risk. Crucially, a retest that is a "wait for the
    # drop" is PATIENCE, not chasing — it must NOT be penalised (that bug buried
    # every pullback setup and let breakouts fill the whole board).
    chase = plan.get("chase", "ok")
    et = plan.get("entry_type")
    if et == "confirmation":
        opp *= 0.88
    else:                       # retest / pullback into support
        opp *= 1.08

    # model-estimated probability of success (LABELLED as an estimate)
    p = _clamp(0.40 + 0.22 * setup_q + 0.08 * (rr >= 2.0) +
               (0.05 if poc_conf == "high" else -0.05 if poc_conf == "low" else 0.0) +
               0.08 * s_mom, 0.30, 0.72)
    ev_pct = round(p * exp_ret - (1 - p) * stop_frac * 100.0, 2)

    # speed ranking: time + momentum + breakout + liquidity (breakouts are
    # genuinely faster, so this one still leans to confirmation on purpose)
    speed = 100.0 * (0.45 * s_time + 0.25 * s_mom +
                     0.15 * (1.0 if et == "confirmation" else 0.6) + 0.15 * s_liq)
    # risk-adjusted ranking: structure + rr + tight stop + liquidity. A pullback
    # entry (better price, support beneath) is the essence of risk-adjusted, so it
    # is favoured here; a breakout is trimmed.
    risk_adj = 100.0 * (0.35 * s_setup + 0.25 * s_rr + 0.25 * s_riskq + 0.15 * s_liq)
    risk_adj *= 0.9 if et == "confirmation" else 1.1

    row = {
        "symbol": None, "company": None,
        "action": "BUY", "current_price": plan.get("current_price"),
        "optimal_zone": plan.get("optimal_zone"), "entry_type": plan.get("entry_type"),
        "entry": entry, "confirmation_entry": plan.get("confirmation_entry"),
        "stop": stop, "tp1": tp1, "tp2": plan.get("tp2"),
        "expected_return_pct": round(exp_ret, 2), "rr": round(rr, 2),
        "est_tp1": plan.get("est_tp1"), "est_tp2": plan.get("est_tp2"),
        "risk_level": _risk_level(stop_frac, poc_conf),
        "opportunity_score": round(opp, 1),
        "confidence": (plan.get("confidence") or {}).get("score"),
        "chase": chase, "phase": lv.get("phase"), "poc_confidence": poc_conf,
        "model_prob": round(p, 2), "ev_pct": ev_pct,
        "liquidity_egp": round(turnover),
        "distribution_warning": bool(lv.get("distribution_warning")),
        "subscores": {"return": round(s_ret, 2), "setup": round(s_setup, 2),
                      "risk": round(s_riskq, 2), "rr": round(s_rr, 2),
                      "time": round(s_time, 2), "liquidity": round(s_liq, 2),
                      "momentum": round(s_mom, 2)},
    }
    # Three actionable categories: buy the current price (price sits in the zone
    # now), wait for a pullback (price above the zone), or a breakout (buy above).
    row["category"] = ("breakout" if row["entry_type"] == "confirmation"
                       else "wait" if chase == "do_not_chase" else "buy_now")
    return Scored(row=row, opportunity=opp, speed=speed, risk_adjusted=risk_adj)


def _market_regime(breadth_above_ma: float, breadth_up_mom: float,
                   median_atr_pct: float) -> dict:
    strength = round(100 * (0.6 * breadth_above_ma + 0.4 * breadth_up_mom))
    if median_atr_pct >= 0.045 and breadth_above_ma < 0.45:
        regime = "High risk / volatile"
    elif breadth_above_ma >= 0.60:
        regime = "Bullish"
    elif breadth_above_ma <= 0.40:
        regime = "Bearish"
    else:
        regime = "Neutral"
    return {"regime": regime, "strength": strength,
            "breadth_above_ma50": round(breadth_above_ma, 2),
            "breadth_positive_momentum": round(breadth_up_mom, 2),
            "median_atr_pct": round(median_atr_pct, 4)}


# --------------------------------------------------------------------------- #
# Simple daily cache: a full scan hits ~280 symbols, so we cache the result for
# the trading day (keyed by horizon+risk). Cleared on process restart.
# --------------------------------------------------------------------------- #
_CACHE: dict = {}
_CACHE_TTL = 3600.0  # 1 hour


def scan(symbols: list[str], *, names: dict | None = None, horizon: str = "short_swing",
         risk: str = "balanced", weights: dict | None = None, fetcher=None,
         max_workers: int = 12, limit: int | None = None, use_cache: bool = True,
         refresh: bool = False, analyze=None) -> dict:
    """Scan the universe and return ranked opportunities.

    `analyze` is injectable for tests: callable(symbol, objective, live_price) ->
    result dict shaped like service.analyze_symbol's output. In production the
    API passes service.analyze_symbol.
    """
    names = names or {}
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    objective = HORIZON_OBJECTIVE.get(horizon, Objective.SWING)
    profile = RISK_PROFILE.get(risk, RISK_PROFILE["balanced"])
    syms = [s.strip().upper() for s in symbols if s and s.strip()]
    if limit:
        syms = syms[:limit]

    key = (horizon, risk, tuple(sorted(weights.items())), tuple(syms))
    if use_cache and not refresh and analyze is None:
        hit = _CACHE.get(key)
        if hit and (_time.time() - hit["ts"] < _CACHE_TTL):
            return {**hit["result"], "cached": True}

    if analyze is None:
        from .. import service as _svc

        def analyze(sym, obj, live_price=False):
            return _svc.analyze_symbol(sym, obj, live_price=live_price)

    scored: list[Scored] = []
    n_scanned = n_buy = 0
    above_ma = up_mom = 0
    atr_pcts: list[float] = []
    unreached: list[dict] = []   # symbols whose data we could NOT reach (honest coverage)

    def work(sym):
        try:
            res = analyze(sym, objective, live_price=False)
            return sym, res, None
        except Exception as e:  # symbol missing / feed error — never fabricate
            return sym, None, str(e)

    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for sym, res, err in ex.map(work, syms):
            if err or not res:
                unreached.append({"symbol": sym, "company": names.get(sym, sym),
                                  "reason": _reason_code(err)})
                continue
            n_scanned += 1
            plan = res.get("plan", {})
            # breadth stats from the returned candles (real data only)
            cs = res.get("candles") or []
            if cs:
                df = pd.DataFrame(cs).rename(columns={"o": "open", "h": "high",
                                    "l": "low", "c": "close", "v": "volume"})
                close = df["close"]
                ma50 = ind.last(ind.sma(close, 50))
                if ma50 and float(close.iloc[-1]) > ma50:
                    above_ma += 1
                if _momentum_20(df) > 0:
                    up_mom += 1
                atr_v = ind.last(ind.atr(df))
                if atr_v:
                    atr_pcts.append(atr_v / float(close.iloc[-1]))
                sc = score_plan(plan, df, objective, weights, _momentum_20(df))
            else:
                sc = None
            if sc:
                sc.row["symbol"] = sym
                sc.row["company"] = names.get(sym, sym)
                # 3-month (63-session) return for a cross-sectional RS rank below
                r63 = None
                if cs and len(df) >= 64:
                    r63 = float(df["close"].iloc[-1] / df["close"].iloc[-64] - 1.0)
                sc.row["rs_return_63"] = r63
                scored.append(sc)
                n_buy += 1

    # ---- Relative strength: rank each name's 3-month return against the whole
    # scanned universe (the O'Neil/IBD idea) — a true RS rank, no index feed
    # needed. Leaders get a small opportunity bonus, laggards a penalty. ---------
    rvals = sorted(s.row["rs_return_63"] for s in scored if s.row.get("rs_return_63") is not None)
    for s in scored:
        v = s.row.get("rs_return_63")
        if v is None or len(rvals) < 3:
            s.row["rs_rank"] = None
            continue
        rank = round(100 * bisect.bisect_left(rvals, v) / max(len(rvals) - 1, 1))
        s.row["rs_rank"] = rank
        s.opportunity += (rank - 50) / 50.0 * 5.0      # +/-5 points by leadership
        s.row["opportunity_score"] = round(s.opportunity, 1)

    denom = max(n_scanned, 1)
    median_atr = (sorted(atr_pcts)[len(atr_pcts) // 2] if atr_pcts else 0.0)
    market = _market_regime(above_ma / denom, up_mom / denom, median_atr)

    # Regime gate: in a bearish / high-risk tape, demand stronger setups.
    min_rr = profile["min_rr"]
    if market["regime"] in ("Bearish", "High risk / volatile"):
        min_rr = max(min_rr, 2.2)
    kept = [s for s in scored
            if s.row["rr"] >= min_rr
            and (s.row["entry"] - s.row["stop"]) / s.row["entry"] <= profile["max_stop_frac"]]

    top_overall = sorted(kept, key=lambda s: s.opportunity, reverse=True)
    top_fast = sorted(kept, key=lambda s: s.speed, reverse=True)
    top_risk = sorted(kept, key=lambda s: s.risk_adjusted, reverse=True)
    # dedicated lists so the user can ask for one category directly
    def _by(cat):
        return sorted((s for s in kept if s.row.get("category") == cat),
                      key=lambda s: s.opportunity, reverse=True)
    buy_now = _by("buy_now")
    pull = _by("wait")
    brk = _by("breakout")

    def rows(lst, n):
        return [s.row for s in lst[:n]]

    # Three DISTINCT headline picks: overall, then the best *different* name by
    # speed, then the best *different* name by risk-adjusted quality. With a small
    # universe (e.g. a short watch list) the same stock can top several metrics —
    # showing it three times is noise, so we skip names already picked. Only when
    # there aren't enough distinct valid setups does a card repeat (unavoidable).
    picks = {}
    _used = set()
    def _take(ranked):
        for s in ranked:
            if s.row["symbol"] not in _used:
                _used.add(s.row["symbol"])
                return s.row
        return ranked[0].row if ranked else None
    if top_overall:
        picks["overall"] = _take(top_overall)
    if top_fast:
        picks["fast"] = _take(top_fast)
    if top_risk:
        picks["risk_adjusted"] = _take(top_risk)

    result = {
        "as_of": _time.strftime("%Y-%m-%d %H:%M", _time.gmtime()),
        "horizon": horizon, "risk": risk, "weights": weights,
        "objective": objective.value,
        "market": market,
        "requested": len(syms),
        "scanned": n_scanned, "valid_setups": len(kept),
        "no_trade": max(n_scanned - len(kept), 0),
        "errors": len(unreached),          # count (unchanged type)
        "unreached": unreached,            # WHICH symbols had no reachable data + why
        "data_note": "Daily end-of-day data. 'Fast' = short-swing on daily bars, "
                     "not intraday day-trading (no intraday EGX feed).",
        "top10": [s.row for s in top_overall[:10]],
        "top_overall": rows(top_overall, 15),
        "top_fast": rows(top_fast, 10),
        "top_risk_adjusted": rows(top_risk, 10),
        "top_buy_now": rows(buy_now, 15),
        "top_pullbacks": rows(pull, 15),
        "top_breakouts": rows(brk, 15),
        "counts": {"buy_now": len(buy_now), "pullbacks": len(pull), "breakouts": len(brk)},
        "picks": picks,
    }
    if use_cache and analyze is not None:
        pass  # don't cache injected/test runs
    elif use_cache:
        _CACHE[key] = {"ts": _time.time(), "result": result}
    return result
