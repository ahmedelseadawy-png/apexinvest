"""Expected-move projection: an honest volatility-based range, never a guess.

The guarantees tested:
  * the range comes from the stock's REAL daily-return volatility (sigma),
  * the week band is the day band scaled by sqrt(5),
  * the wide band (~95%) is wider than the typical band (~68%),
  * the range is anchored to the price we pass (current price, not entry),
  * lows never go negative, and
  * with too little history it returns None instead of fabricating a range.
"""
import math

import numpy as np
import pandas as pd

from apexinvest.engines import expected_move as em


def _df_from_returns(returns, start=100.0):
    closes = [start]
    for r in returns:
        closes.append(closes[-1] * (1 + r))
    n = len(closes)
    return pd.DataFrame({"open": closes, "high": [c * 1.01 for c in closes],
                         "low": [c * 0.99 for c in closes], "close": closes,
                         "volume": [1e5] * n})


def test_returns_none_when_history_too_short():
    df = _df_from_returns([0.01] * 3)
    assert em.compute(df) is None


def test_sigma_matches_the_real_returns():
    # Alternating +2% / -2% returns -> daily sigma ~ 2% (ddof=1 over the window).
    r = [0.02, -0.02] * 15
    res = em.compute(_df_from_returns(r), lookback=20)
    assert res is not None
    assert abs(res["sigma_daily_pct"] - 2.0) < 0.15
    # week sigma is the daily sigma scaled by sqrt(5)
    assert abs(res["sigma_weekly_pct"] - res["sigma_daily_pct"] * math.sqrt(5)) < 0.05


def test_bands_ordered_and_anchored_to_current_price():
    res = em.compute(_df_from_returns([0.01, -0.01] * 20), current_price=1.72)
    assert res["anchor_price"] == 1.72
    d = res["day"]
    assert d["wide_low"] < d["typical_low"] < 1.72 < d["typical_high"] < d["wide_high"]
    # the week range is wider than the day range around the same anchor
    assert res["week"]["typical_high"] > d["typical_high"]
    assert res["week"]["typical_low"] < d["typical_low"]


def test_lows_never_negative_on_extreme_volatility():
    # Huge swings so 2-sigma would push a naive low below zero.
    r = [0.6, -0.5] * 20
    res = em.compute(_df_from_returns(r), current_price=1.0)
    assert res["day"]["wide_low"] >= 0.0
    assert res["week"]["wide_low"] >= 0.0


def test_direction_is_not_predicted_band_is_symmetric():
    res = em.compute(_df_from_returns([0.015, -0.015] * 20), current_price=10.0)
    d = res["day"]
    # symmetric around the anchor (a random-walk range, not a directional call)
    assert abs((d["typical_high"] - 10.0) - (10.0 - d["typical_low"])) < 1e-6
