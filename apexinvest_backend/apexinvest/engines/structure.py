"""Market-structure engine (Update #2) — daily, honest, transparent.

The old volume profile used the whole lifetime of the stock, which is wrong for
finding a *current* trading setup. This engine identifies the most recent
meaningful structure and anchors the profile to it:

    accumulation  ->  manipulation / liquidity sweep  ->  reclaim / BOS  ->
    markup  ->  distribution

and reports which phase price is in now, plus a POC-confidence that drops to LOW
when there is no clean structure to read (so the app never fabricates a POC it
can't stand behind).

HONEST SCOPE — read this. This runs on **daily** candles, because that is the
only free EGX data we have. It is NOT a 30-minute intraday structure: a true
30-minute accumulation/manipulation profile needs an intraday feed we do not
have, and inventing 30-minute bars would violate the anti-fabrication rule. So
every output here is explicitly a *daily* read, and the exact bar range used is
returned for transparency. When an intraday provider is added (see the data
layer), the same functions run on 30-minute candles unchanged.

Everything is a deterministic function of the candles. No look-ahead: pivots are
only confirmed after their right-hand bars exist, and nothing uses a bar later
than the one being judged.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import indicators as ind

# Phases
ACCUMULATION = "accumulation"
MANIPULATION = "manipulation"
RECLAIM = "reclaim"
MARKUP = "markup"
DISTRIBUTION = "distribution"
UNDEFINED = "undefined"

PHASE_LABEL = {
    ACCUMULATION: "Accumulation (basing)",
    MANIPULATION: "Manipulation / liquidity sweep",
    RECLAIM: "Reclaim / break of structure",
    MARKUP: "Markup (trending up)",
    DISTRIBUTION: "Distribution (supply / topping)",
    UNDEFINED: "No clean structure",
}


@dataclass
class Structure:
    phase: str
    poc_confidence: str                 # "high" | "medium" | "low"
    window_start_i: int
    window_bars: int
    range_low: float | None             # accumulation support (value low)
    range_high: float | None            # accumulation resistance (value high)
    poc: float | None
    vah: float | None
    val: float | None
    hvn: list = field(default_factory=list)
    lvn: list = field(default_factory=list)
    swept: bool = False                 # a liquidity sweep / failed breakdown happened
    sweep_low: float | None = None
    reclaimed: bool = False             # price recovered back above the level it lost
    distribution_warning: bool = False  # supply / topping evidence near highs
    dist_reasons: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    def window(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.iloc[self.window_start_i:]

    def as_dict(self) -> dict:
        def r(x):
            if x is None:
                return None
            dp = 2 if abs(x) >= 1 else 4
            return round(float(x), dp)
        return {
            "phase": self.phase,
            "phase_label": PHASE_LABEL.get(self.phase, self.phase),
            "poc_confidence": self.poc_confidence,
            "window_bars": self.window_bars,
            "range_low": r(self.range_low), "range_high": r(self.range_high),
            "poc": r(self.poc), "vah": r(self.vah), "val": r(self.val),
            "hvn": [r(x) for x in self.hvn][:6], "lvn": [r(x) for x in self.lvn][:6],
            "swept": self.swept, "sweep_low": r(self.sweep_low),
            "reclaimed": self.reclaimed,
            "distribution_warning": self.distribution_warning,
            "dist_reasons": self.dist_reasons,
            "notes": self.notes,
        }


def _window_start(df: pd.DataFrame) -> int:
    """Start of the most recent structural leg: the last confirmed swing low,
    clamped so a single ancient low can't drag the window back to the lifetime,
    and so there are always enough bars for a real profile."""
    n = len(df)
    max_span = min(n, 130)      # ~6 months ceiling
    min_span = min(n, 40)
    _, lows = ind.pivots(df, left=3, right=3)
    if lows:
        span = n - lows[-1]["i"]
        span = max(min_span, min(span, max_span))
        return n - span
    return n - max_span


def detect_structure(df: pd.DataFrame) -> Structure:
    n = len(df)
    if n < 30:
        return Structure(phase=UNDEFINED, poc_confidence="low",
                         window_start_i=0, window_bars=n,
                         range_low=None, range_high=None, poc=None, vah=None, val=None,
                         notes=["Too few bars to read structure."])

    ws = _window_start(df)
    win = df.iloc[ws:]
    wb = len(win)
    atr_v = ind.last(ind.atr(df)) or (float(df["close"].iloc[-1]) * 0.02)
    close = float(df["close"].iloc[-1])

    vp = ind.volume_profile(win, bins=30)
    poc, vah, val = vp.get("poc"), vp.get("vah"), vp.get("val")

    # Accumulation range: the value area is the base's support/resistance band.
    range_low, range_high = val, vah

    # ---- Liquidity sweep / manipulation ------------------------------------
    # A failed breakdown: within the window, price dipped clearly below the value
    # low (or the base support) and then closed back above it. That wick is where
    # stops were swept before the real move.
    swept, sweep_low = False, None
    if val is not None:
        below = win[win["low"] < val * 0.995]
        if len(below):
            sweep_low = float(below["low"].min())
            # reclaimed if, after the lowest sweep bar, price closed back above val
            sweep_i = below["low"].idxmin()
            after = win.loc[sweep_i:]
            if len(after) and float(after["close"].iloc[-1]) > val:
                swept = True

    # ---- Reclaim / break of structure --------------------------------------
    # Reclaimed value (close back inside/above VAL after a sweep) OR broke above
    # the range high (VAH) = break of structure to the upside.
    reclaimed = False
    if swept and val is not None and close >= val:
        reclaimed = True
    broke_out = vah is not None and close > vah

    # ---- Distribution / supply warning near highs --------------------------
    dist, dist_reasons = False, []
    if wb >= 20:
        recent = df.tail(15)
        # OBV divergence: price flat-to-up but OBV rolling over
        obv = ind.obv(df)
        if len(obv) >= 15:
            obv_slope = float(obv.iloc[-1] - obv.iloc[-15])
            px_slope = float(df["close"].iloc[-1] - df["close"].iloc[-15])
            if px_slope >= 0 and obv_slope < 0:
                dist = True; dist_reasons.append("OBV falling while price holds up (supply).")
        # Upper-wick rejections on high volume near the highs
        rng = (recent["high"] - recent["low"]).replace(0, np.nan)
        upper_wick = (recent["high"] - recent[["open", "close"]].max(axis=1)) / rng
        vmean = float(df["volume"].tail(40).mean() or 0.0)
        heavy = recent["volume"] > 1.3 * vmean if vmean else recent["volume"] > 0
        if int(((upper_wick > 0.5) & heavy).sum()) >= 2:
            dist = True; dist_reasons.append("Repeated upper-wick rejections on heavy volume.")
        # Failure to make a new high for a while after a markup
        if vah is not None and close < vah and float(recent["high"].max()) < float(df["high"].tail(40).max()):
            dist_reasons.append("Stalling below prior highs.")

    # ---- Phase classification ----------------------------------------------
    if val is None or vah is None:
        phase = UNDEFINED
    elif broke_out and dist:
        phase = DISTRIBUTION
    elif broke_out:
        phase = MARKUP
    elif close < val * 0.995:
        phase = MANIPULATION            # below value — sweep in progress / weak
    elif swept and reclaimed:
        phase = RECLAIM
    elif val <= close <= vah:
        phase = ACCUMULATION
    else:
        phase = UNDEFINED

    # ---- POC confidence ----------------------------------------------------
    # HIGH when the base is a real range with a concentrated profile; LOW when
    # price trended straight through the window (few swings, diffuse profile) —
    # then the POC is not a meaningful level and we say so.
    highs_w, lows_w = ind.pivots(win, left=2, right=2)
    n_swings = len(highs_w) + len(lows_w)
    band = (vah - val) / close if (vah and val and close) else 1.0
    directional = abs(float(win["close"].iloc[-1]) - float(win["close"].iloc[0])) / max(atr_v, 1e-9)
    span_atr = (float(win["high"].max()) - float(win["low"].min())) / max(atr_v, 1e-9)
    trendiness = directional / max(span_atr, 1e-9)     # ~1 = pure trend, low = ranging

    if n_swings >= 4 and band <= 0.18 and trendiness < 0.6:
        poc_conf = "high"
    elif n_swings >= 2 and trendiness < 0.8:
        poc_conf = "medium"
    else:
        poc_conf = "low"

    notes = [
        f"Daily structure over the last {wb} bars (end-of-day data — not 30-minute intrabar).",
    ]
    if poc_conf == "low":
        notes.append("No clean accumulation range — POC confidence LOW; treat levels as soft.")

    return Structure(
        phase=phase, poc_confidence=poc_conf,
        window_start_i=ws, window_bars=wb,
        range_low=range_low, range_high=range_high,
        poc=poc, vah=vah, val=val, hvn=vp.get("hvn", []), lvn=vp.get("lvn", []),
        swept=swept, sweep_low=sweep_low, reclaimed=reclaimed,
        distribution_warning=dist, dist_reasons=dist_reasons, notes=notes,
    )
