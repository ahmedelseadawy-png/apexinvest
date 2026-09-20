"""Market-regime detection from candles.

Classifies the current character of the market into trend / volatility /
liquidity. This feeds the recommendation and risk engines. It computes; it
does not opine.
"""
from __future__ import annotations

import pandas as pd

from ..domain import Bucket, RegimeSnapshot, Trend
from . import indicators as ind


def detect_regime(df: pd.DataFrame) -> RegimeSnapshot:
    ind.validate_candles(df)

    close = df["close"]
    price = float(close.iloc[-1])

    ema_fast = ind.last(ind.ema(close, 20))
    ema_slow = ind.last(ind.ema(close, 50))
    adx_v = ind.last(ind.adx(df)) or 0.0
    atr_v = ind.last(ind.atr(df)) or 0.0
    atr_pct = atr_v / price if price else 0.0

    # Trend: direction from EMA relationship, strength gated by ADX.
    # ADX < 20 => no real trend regardless of EMA => sideways.
    if ema_fast is None or ema_slow is None or adx_v < 20:
        trend = Trend.SIDEWAYS
    elif ema_fast > ema_slow:
        trend = Trend.UP
    else:
        trend = Trend.DOWN

    # Volatility bucket from ATR as a % of price.
    if atr_pct < 0.015:
        vol = Bucket.LOW
    elif atr_pct < 0.04:
        vol = Bucket.MEDIUM
    else:
        vol = Bucket.HIGH

    # Liquidity bucket from average dollar volume.
    dvol = ind.dollar_volume(df)
    if dvol < 1_000_000:
        liq = Bucket.LOW
    elif dvol < 50_000_000:
        liq = Bucket.MEDIUM
    else:
        liq = Bucket.HIGH

    return RegimeSnapshot(
        trend=trend, volatility=vol, liquidity=liq,
        atr=atr_v, atr_pct=atr_pct, adx=adx_v,
    )
