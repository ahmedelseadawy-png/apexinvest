"""Entry optimizer — WHERE to buy, not just WHAT the price is.

This is the module the app was missing. The old logic used the *current price*
as the entry, which is wrong: current price and optimal entry are different
questions. This engine answers "where is the best zone to enter, given the
analysis?" and, when the price has run away from that zone, says DO NOT CHASE
instead of forcing a buy at the top.

Everything is derived from the daily candles (this free feed is end-of-day only,
so there is no 30-minute structure here — the profile/levels are honest daily
levels, clearly labelled). Nothing is fabricated: if there is no location that
offers acceptable risk/reward, the result is NO TRADE.

Design (long side — the app is buy-oriented for EGX retail):

  1. Levels from structure: swing pivots -> support/resistance zones; a
     *contextual* volume profile (recent window, not lifetime) -> POC/VAH/VAL/
     HVN/LVN; ATR for buffers and expected move.
  2. Two candidate entries:
       RETEST       — a support/value zone below price you wait to pull back to.
       CONFIRMATION — buy above the breakout/reclaim level once it confirms,
                      used when there is no good pullback support to lean on.
     The engine builds both where possible and keeps the one with the better,
     still-valid risk/reward.
  3. Stop is STRUCTURAL (below the swing low / value low / breakout level that
     defines the setup), buffered by ATR — never an arbitrary percentage unless
     there is no structural level to use.
  4. TP1 / TP2 are real resistances above (swing highs, VAH, prior highs) or a
     measured move when structure is thin — not a fixed percentage.
  5. Expected return and R:R are ALWAYS measured from the recommended entry,
     never from the current price.
  6. Anti-chase: if the price is already well above the optimal zone, status is
     DO NOT CHASE and the plan points back to the zone / confirmation level.
  7. NO TRADE when nothing clears the objective's minimum R:R.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import indicators as ind
from . import structure as structure_engine


@dataclass
class EntryPlan:
    current_price: float
    no_trade: bool
    reason: str
    entry_type: str | None = None                 # "retest" | "confirmation"
    optimal_zone: tuple[float, float] | None = None
    entry_ref: float | None = None                # single price the R:R math uses
    confirmation_entry: float | None = None
    stop: float | None = None
    stop_basis: str = ""
    tp1: float | None = None
    tp2: float | None = None
    expected_return_pct: float | None = None       # to TP1, from entry_ref
    expected_return_tp2_pct: float | None = None
    rr: float | None = None
    chase: str = "ok"                              # "ok" | "do_not_chase"
    est_tp1: str | None = None
    est_tp2: str | None = None
    setup_quality: float = 0.0                     # 0..1, feeds confidence/score
    levels: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        z = list(self.optimal_zone) if self.optimal_zone else None
        return {
            "current_price": _r(self.current_price),
            "no_trade": self.no_trade,
            "reason": self.reason,
            "entry_type": self.entry_type,
            "optimal_zone": [_r(z[0]), _r(z[1])] if z else None,
            "entry_ref": _r(self.entry_ref),
            "confirmation_entry": _r(self.confirmation_entry),
            "stop": _r(self.stop),
            "stop_basis": self.stop_basis,
            "tp1": _r(self.tp1),
            "tp2": _r(self.tp2),
            "expected_return_pct": _r2(self.expected_return_pct),
            "expected_return_tp2_pct": _r2(self.expected_return_tp2_pct),
            "rr": _r2(self.rr),
            "chase": self.chase,
            "est_tp1": self.est_tp1,
            "est_tp2": self.est_tp2,
            "setup_quality": round(self.setup_quality, 3),
            "levels": self.levels,
            "notes": self.notes,
        }


def _dp(price: float) -> int:
    return 2 if price >= 1 else 4


def _r(x):
    return None if x is None else round(float(x), _dp(abs(x)) if x else 2)


def _r2(x):
    return None if x is None else round(float(x), 2)


def _sessions_bucket(sessions: float) -> str:
    """Honest time bucket from an ATR-paced estimate — no fake precision."""
    if sessions <= 3:
        return "1-3 sessions"
    if sessions <= 5:
        return "3-5 sessions"
    if sessions <= 10:
        return "1-2 weeks"
    if sessions <= 20:
        return "2-4 weeks"
    return "1 month+"


def _contextual_window(df: pd.DataFrame, atr_v: float) -> pd.DataFrame:
    """Pick the recent window the volume profile / levels should describe.

    Not the lifetime. We take the most recent stretch that behaves like the
    current setup: from the last significant swing low forward (the base of the
    current leg), bounded to a sensible span so a single ancient low can't drag
    the window back to the whole history. Falls back to a fixed recent lookback
    when no clean pivot exists.
    """
    n = len(df)
    max_span = min(n, 130)                 # ~6 trading months ceiling
    min_span = min(n, 40)                  # need enough bars for a real profile
    _, lows = ind.pivots(df, left=3, right=3)
    if lows:
        # last confirmed swing low, but keep the window within [min_span, max_span]
        last_low_i = lows[-1]["i"]
        span = n - last_low_i
        span = max(min_span, min(span, max_span))
        return df.tail(span)
    return df.tail(max_span)


def _weekly_trend(df: pd.DataFrame) -> str:
    """Higher-timeframe (~weekly) trend proxy from daily bars: the slope of a
    ~6-week EMA plus price's position relative to it. 'up' | 'down' | 'flat'.
    Used to check a daily long agrees with the higher timeframe, not fight it."""
    if len(df) < 40:
        return "flat"
    ema = ind.ema(df["close"], 30).dropna()
    if len(ema) < 12:
        return "flat"
    now, prev = float(ema.iloc[-1]), float(ema.iloc[-10])
    price = float(df["close"].iloc[-1])
    if now > prev and price > now:
        return "up"
    if now < prev and price < now:
        return "down"
    return "flat"


def _trend_template(df: pd.DataFrame) -> dict | None:
    """Minervini/O'Neil trend template — a published, backtested quality screen
    for a healthy uptrend. Returns the fraction of criteria met (0..1) and which,
    or None when there isn't enough history (~200 bars). RS-rank vs the index is
    added separately by the relative-strength layer when available."""
    if len(df) < 200:
        return None
    c = df["close"]
    price = float(c.iloc[-1])
    s50, s150, s200 = ind.last(ind.sma(c, 50)), ind.last(ind.sma(c, 150)), ind.last(ind.sma(c, 200))
    if None in (s50, s150, s200):
        return None
    s200_series = ind.sma(c, 200).dropna()
    s200_prev = float(s200_series.iloc[-22]) if len(s200_series) >= 22 else s200
    hi52 = float(df["high"].tail(252).max())
    lo52 = float(df["low"].tail(252).min())
    checks = {
        "stacked_mas": price > s50 > s150 > s200,   # price>50>150>200
        "ma200_rising": s200 > s200_prev,
        "near_52w_high": price >= hi52 * 0.75,       # within 25% of high
        "above_52w_low": price >= lo52 * 1.30,       # 30%+ above the low
    }
    met = [k for k, v in checks.items() if v]
    return {"pass": all(checks.values()), "score": round(len(met) / len(checks), 2),
            "checks": {k: bool(v) for k, v in checks.items()}}


def optimize_entry(
    df: pd.DataFrame,
    *,
    min_rr: float = 1.8,
    atr_stop_mult: float = 1.0,
    rr_target_floor: float = 2.0,
    chase_atr: float = 0.5,
) -> EntryPlan:
    """Build the long-side entry plan from daily candles.

    min_rr        — reject the setup below this reward:risk (objective-scaled).
    atr_stop_mult — ATR buffer placed beyond the structural stop level.
    rr_target_floor — if structure gives no resistance above, project a measured
                    move of this R multiple for TP1.
    chase_atr     — how far (in ATR) above the zone counts as chasing.
    """
    price = float(df["close"].iloc[-1])
    atr_v = ind.last(ind.atr(df)) or (price * 0.02)

    # Anchor the volume profile to the most recent meaningful structure (Update
    # #2): accumulation -> sweep -> reclaim, NOT the lifetime. detect_structure
    # returns the window and the phase; the profile is read over that window.
    st = structure_engine.detect_structure(df)
    win = st.window(df)
    vp = {"poc": st.poc, "vah": st.vah, "val": st.val, "hvn": st.hvn, "lvn": st.lvn}
    highs, lows = ind.pivots(df, left=3, right=3)
    tol = max(atr_v * 0.6, price * 0.005)

    # ---- Supports below current price ---------------------------------------
    support_prices = [lo["price"] for lo in lows if lo["price"] < price * 1.001]
    for key in ("val", "poc"):
        v = vp.get(key)
        if v is not None and v < price * 1.001:
            support_prices.append(float(v))
    # dynamic support: rising MA(50) if price sits above it
    ma50 = ind.last(ind.sma(df["close"], 50))
    if ma50 is not None and ma50 < price:
        support_prices.append(float(ma50))
    supports = ind.cluster_levels(support_prices, tol)

    # ---- Resistances / overhead reclaim levels above current price ----------
    # POC and VAH count as overhead levels when price sits below them: a confirmed
    # reclaim of the POC (the most-traded price) is a classic bullish trigger, so
    # it must be available as a confirmation entry — not ignored.
    resistance_prices = [hi["price"] for hi in highs if hi["price"] > price * 0.999]
    for key in ("poc", "vah"):
        v = vp.get(key)
        if v is not None and v > price * 0.999:
            resistance_prices.append(float(v))
    resistances = ind.cluster_levels(resistance_prices, tol)

    levels = {
        "poc": _r(vp.get("poc")), "vah": _r(vp.get("vah")), "val": _r(vp.get("val")),
        "hvn": [_r(x) for x in vp.get("hvn", [])][:6],
        "lvn": [_r(x) for x in vp.get("lvn", [])][:6],
        "atr": _r(atr_v),
        "supports": [_r(s["price"]) for s in supports][-4:],
        "resistances": [_r(r["price"]) for r in resistances][:4],
        "profile_bars": int(len(win)),
        "profile_note": "Daily volume profile over the recent structural window "
                        f"({len(win)} bars). End-of-day data — not 30-minute intrabar.",
        # Update #2: the structural phase + how much to trust the POC.
        "phase": st.phase, "phase_label": structure_engine.PHASE_LABEL.get(st.phase, st.phase),
        "poc_confidence": st.poc_confidence,
        "range_low": _r(st.range_low), "range_high": _r(st.range_high),
        "swept": st.swept, "reclaimed": st.reclaimed,
        "distribution_warning": st.distribution_warning,
        "dist_reasons": st.dist_reasons,
    }
    notes: list[str] = []
    if st.distribution_warning:
        notes.append("Early-exit warning: " + " ".join(st.dist_reasons or
                     ["distribution/supply signs near the highs — manage the position, don't wait blindly for TP2."]))
    if st.poc_confidence == "low":
        notes.append("POC confidence LOW — no clean daily accumulation range; treat the value levels as soft.")

    # ---- Candidate A: RETEST at nearest strong support below ----------------
    retest = None
    if supports:
        # strongest nearby support: prefer more touches, then closeness to price
        below = [s for s in supports if s["price"] < price]
        if below:
            best = max(below, key=lambda s: (s["count"], -(price - s["price"])))
            zlo = best["lo"] - atr_v * 0.15
            zhi = best["hi"] + atr_v * 0.15
            if zhi >= price:                      # zone must sit below price
                zhi = price * 0.999
            entry_ref = (zlo + zhi) / 2.0
            stop = zlo - atr_v * atr_stop_mult
            stop_basis = f"below support zone {_r(best['price'])} (buffer {atr_stop_mult:.1f}xATR)"
            retest = _finish_side(price, atr_v, entry_ref, stop, stop_basis, resistances,
                                  vp, min_rr, rr_target_floor, "retest", best["count"])

    # ---- Candidate B: CONFIRMATION above nearest resistance -----------------
    confirmation = None
    if resistances:
        trig = min(resistances, key=lambda r: r["price"])   # nearest overhead level
        entry_ref = trig["hi"] + max(atr_v * 0.1, trig["price"] * 0.002)  # buy above it
        # Stop sits just BELOW the reclaimed / broken level — its invalidation is
        # losing that level back — buffered by ATR. Not the distant base, which
        # would blow the risk out to something untradeable.
        stop = trig["lo"] - atr_v * atr_stop_mult
        poc = vp.get("poc")
        kind = "reclaim" if (poc is not None and abs(trig["price"] - poc) <= tol) else "breakout"
        stop_basis = f"below {kind} level {_r(trig['price'])} (buffer {atr_stop_mult:.1f}xATR)"
        # resistances beyond the trigger become the targets
        above_trig = [r for r in resistances if r["price"] > entry_ref * 1.001]
        confirmation = _finish_side(price, atr_v, entry_ref, stop, stop_basis, above_trig,
                                    vp, min_rr, rr_target_floor, "confirmation", trig["count"])
        if confirmation:
            confirmation.confirmation_entry = _num(entry_ref)

    # ---- Actionability: an entry that sits miles from price is not a plan -----
    # A "retest" 40% below the current price, or a "breakout" 70% above it, is
    # not something anyone can act on — it's a different stock. Only keep an entry
    # whose distance from price is sane; otherwise the honest answer is NO TRADE
    # (the name is usually "extended — wait for a pullback / a fresh base").
    max_pullback = max(0.13 * price, 7 * atr_v)      # how far below price a retest may sit
    max_reach_up = max(0.08 * price, 4 * atr_v)      # how far above price a breakout trigger may sit
    retest_far = retest is not None and retest.entry_ref is not None and \
        (price - retest.entry_ref) > max_pullback
    if retest_far:
        retest = None
    if confirmation is not None and confirmation.confirmation_entry is not None and \
            (confirmation.confirmation_entry - price) > max_reach_up:
        confirmation = None

    # ---- Extension guard: never say "buy even higher" on a stretched stock ----
    # A confirmation (buy-above) entry is only honest when the stock isn't already
    # extended. If price has run far above its value area OR far above the 200-day
    # line, telling the user to buy a break *higher still* is chasing a late move —
    # so the confirmation candidate is withheld (→ a pullback entry, or NO TRADE).
    vah = vp.get("vah")
    ma200 = ind.last(ind.sma(df["close"], 200)) if len(df) >= 200 else None
    lo_ref = float(df["low"].tail(min(len(df), 250)).min())
    run_up = (price / lo_ref - 1.0) if lo_ref else 0.0
    extended_up = (vah is not None and price > vah * 1.12) \
        or (ma200 is not None and price > ma200 * 1.30) \
        or (ma200 is None and run_up > 0.55)     # fallback when <200 bars of history
    if confirmation is not None and extended_up:
        confirmation = None

    # ---- Choose the entry ---------------------------------------------------
    valid = [c for c in (retest, confirmation) if c is not None and c.rr is not None
             and c.rr >= min_rr]
    if not valid:
        best_rej = max([c for c in (retest, confirmation) if c and c.rr is not None],
                       key=lambda c: c.rr, default=None)
        if extended_up and not retest_far:
            reason = ("Price is extended above its value area / 200-day line — buying a "
                      "break higher would be chasing. Wait for a pullback into value or a "
                      "fresh base.")
        elif retest_far:
            nearest = min(supports, key=lambda s: price - s["price"]) if supports else None
            reason = (
                "Price is extended well above the nearest real support"
                + (f" ({_r(nearest['price'])})" if nearest else "")
                + " — there is no low-risk pullback entry here. Wait for a proper "
                  "pullback into value or a fresh base rather than chasing.")
        elif best_rej:
            reason = ("No location offers acceptable reward-to-risk right now "
                      f"(best available ~{best_rej.rr:.1f}:1, need {min_rr:.1f}:1).")
        else:
            reason = ("No clean support to lean on and no confirmed breakout level just "
                      "overhead — there is no low-risk place to enter yet.")
        return EntryPlan(current_price=price, no_trade=True, reason=reason,
                         levels=levels, notes=notes)

    # Prefer a PULLBACK (retest) entry whenever a valid one exists — a better price
    # with support beneath beats paying up for a breakout. Only fall back to a
    # confirmation (buy-above) entry when there is no valid pullback to lean on.
    def score(c: EntryPlan) -> float:
        return c.rr + 0.3 * c.setup_quality

    retest_valid = [c for c in valid if c.entry_type == "retest"]
    pool = retest_valid if retest_valid else valid
    chosen = max(pool, key=score)
    chosen.levels = levels
    # Weak structure -> lower the setup quality (feeds the confidence score).
    chosen.setup_quality = round(
        chosen.setup_quality * {"high": 1.0, "medium": 0.85, "low": 0.6}.get(st.poc_confidence, 0.85), 3)
    chosen.notes = list(chosen.notes) + notes

    # ---- Volume confirmation: a breakout needs participation ----------------
    vol_ratio = 1.0
    if len(df) >= 20:
        base_v = float(df["volume"].tail(20).mean()) or 1.0
        vol_ratio = float(df["volume"].tail(3).mean()) / base_v
    chosen.levels["volume_ratio"] = round(vol_ratio, 2)
    if chosen.entry_type == "confirmation":
        if vol_ratio >= 1.2:
            chosen.setup_quality = round(min(1.0, chosen.setup_quality * 1.1), 3)
            chosen.notes.append(f"Breakout backed by strong volume (~{vol_ratio:.1f}x the 20-day average).")
        elif vol_ratio < 0.8:
            chosen.setup_quality = round(chosen.setup_quality * 0.75, 3)
            chosen.notes.append(f"Caution: breakout on light volume (~{vol_ratio:.1f}x average) — less reliable; wait for a volume expansion.")

    # ---- Higher-timeframe (~weekly) confluence ------------------------------
    wk = _weekly_trend(df)
    chosen.levels["weekly_trend"] = wk
    if wk == "down":
        chosen.setup_quality = round(chosen.setup_quality * 0.8, 3)
        chosen.notes.append("Higher timeframe (~weekly) is down — a daily long fights the bigger trend; size down or wait.")
    elif wk == "up":
        chosen.setup_quality = round(min(1.0, chosen.setup_quality * 1.05), 3)

    # ---- Trend template (Minervini/O'Neil) — a defensible quality nudge -----
    tt = _trend_template(df)
    chosen.levels["trend_template"] = tt
    if tt is not None:
        # scale quality by how many published trend criteria are met (0.9x..1.1x)
        chosen.setup_quality = round(min(1.0, max(0.0, chosen.setup_quality * (0.9 + 0.2 * tt["score"]))), 3)
        if tt["pass"]:
            chosen.notes.append("Passes the trend template (price>50>150>200 MA, 200 rising, near 52-week high).")

    # ---- Anti-chase --------------------------------------------------------
    if chosen.entry_type == "retest" and chosen.optimal_zone:
        zone_hi = chosen.optimal_zone[1]
        if price > zone_hi + chase_atr * atr_v:
            chosen.chase = "do_not_chase"
            chosen.notes.append(
                f"Price ({_r(price)}) is above the optimal buy zone — wait for a pullback "
                f"into {_r(chosen.optimal_zone[0])}-{_r(zone_hi)} rather than chasing. "
                f"If it breaks out instead, use the confirmation entry.")
            # offer a confirmation fallback so the user isn't left with only 'wait'
            if confirmation and confirmation.confirmation_entry:
                chosen.confirmation_entry = confirmation.confirmation_entry
        else:
            chosen.chase = "ok"
            if price >= chosen.optimal_zone[0]:
                chosen.notes.append("Price is inside the optimal buy zone — entering here is valid.")
    else:  # confirmation entry — you're buying a break above, never a chase by construction
        chosen.chase = "ok"
        chosen.notes.append(
            f"Breakout setup: enter only on a confirmed move above {_r(chosen.confirmation_entry)}; "
            "no valid pullback support to lean on below.")

    return chosen


def _finish_side(price, atr_v, entry_ref, stop, stop_basis, resistances, vp,
                 min_rr, rr_target_floor, entry_type, support_count,
                 max_stop_frac: float = 0.14) -> EntryPlan | None:
    """Given a proposed entry & stop, build targets, R:R, return %, time and a
    setup-quality score. Returns None if the geometry is invalid (stop >= entry)
    or the structural stop is unreasonably wide (risk > max_stop_frac of entry) —
    a stop 30-40% away is not a swing plan, it's a different trade, so we pass."""
    risk = entry_ref - stop
    if risk <= 0:
        return None
    if risk / entry_ref > max_stop_frac:
        return None

    # TP1 = nearest real resistance above entry; TP2 = the next one.
    res_above = sorted([r["price"] for r in resistances if r["price"] > entry_ref * 1.005])
    if res_above:
        tp1 = res_above[0]
        tp2 = res_above[1] if len(res_above) > 1 else entry_ref + max(
            (tp1 - entry_ref) * 1.8, rr_target_floor * risk)
    else:
        # No structure above — honest measured move off risk, clearly a projection.
        tp1 = entry_ref + rr_target_floor * risk
        tp2 = entry_ref + (rr_target_floor + 1.2) * risk

    # Make sure TP1 at least meets the objective's min R:R; if the nearest
    # resistance is too close, step to the measured-move floor instead of faking it.
    if (tp1 - entry_ref) / risk < min_rr:
        stretched = entry_ref + min_rr * risk
        # only stretch to a level that isn't already blocked by the very next res
        tp1 = stretched
        if tp2 <= tp1:
            tp2 = entry_ref + (min_rr + 1.0) * risk

    rr = (tp1 - entry_ref) / risk
    exp_ret = (tp1 - entry_ref) / entry_ref * 100.0
    exp_ret2 = (tp2 - entry_ref) / entry_ref * 100.0

    # Time-to-target: distance paced by ATR (expected daily travel), halved to
    # reflect that trending moves cover ground faster than a random walk.
    pace = max(atr_v * 0.6, 1e-9)
    est1 = _sessions_bucket((tp1 - entry_ref) / pace)
    est2 = _sessions_bucket((tp2 - entry_ref) / pace)

    # Setup quality 0..1: reward more support touches, healthy (not huge) R:R,
    # and a stop that isn't absurdly wide relative to price.
    stop_frac = risk / entry_ref
    q_support = min(support_count / 3.0, 1.0)
    q_rr = min(rr / 3.0, 1.0)
    q_stop = 1.0 if stop_frac <= 0.06 else max(0.3, 0.06 / stop_frac)
    quality = round(0.4 * q_support + 0.35 * q_rr + 0.25 * q_stop, 3)

    zone = None
    if entry_type == "retest":
        half = atr_v * 0.25
        zone = (entry_ref - half, min(entry_ref + half, price * 0.999))

    return EntryPlan(
        current_price=price, no_trade=False, reason="",
        entry_type=entry_type, optimal_zone=zone, entry_ref=_num(entry_ref),
        stop=_num(stop), stop_basis=stop_basis,
        tp1=_num(tp1), tp2=_num(tp2),
        expected_return_pct=exp_ret, expected_return_tp2_pct=exp_ret2,
        rr=rr, est_tp1=est1, est_tp2=est2, setup_quality=quality,
    )


def _num(x):
    return None if x is None else float(x)
