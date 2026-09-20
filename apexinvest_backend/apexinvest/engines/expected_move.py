"""Expected-move projection — an HONEST forward price range from a stock's own
recent volatility. Anti-fabrication: no price is invented. The range is the
current price scaled by the standard deviation of its REAL daily returns, and
the week is that daily sigma scaled by sqrt(5) trading days. We report a typical
band (~68%, +/-1 sigma) and a wide band (~95%, +/-2 sigma) for the next day and
the next week — never a single "predicted" price, and direction is NOT forecast
(the band is symmetric around the current price, the honest random-walk default).

Contract:
    compute(df[, current_price][, lookback]) -> dict | None
        df: DataFrame with a 'close' column (real daily candles).
        Returns None when there isn't enough real data to measure volatility.
"""
from __future__ import annotations

import math

import pandas as pd

TRADING_DAYS_WEEK = 5
_MIN_BARS = 12          # need a minimum history to measure volatility at all
_MIN_RETURNS = 10


def _band(price: float, sigma: float) -> dict:
    """One horizon's low/high at +/-1 sigma (typical) and +/-2 sigma (wide).
    Lows are floored at 0 — a share price cannot go negative."""
    return {
        "typical_pct": round(sigma * 100, 2),
        "wide_pct": round(2 * sigma * 100, 2),
        "typical_low": round(max(price * (1 - sigma), 0.0), 4),
        "typical_high": round(price * (1 + sigma), 4),
        "wide_low": round(max(price * (1 - 2 * sigma), 0.0), 4),
        "wide_high": round(price * (1 + 2 * sigma), 4),
    }


def compute(df: "pd.DataFrame", current_price: float | None = None,
            lookback: int = 20) -> dict | None:
    """Expected next-day and next-week range from real recent volatility.

    Pure and testable: hand it a DataFrame of real candles. Returns None (never a
    guess) when the history is too short to measure volatility honestly.
    """
    if df is None or len(df) < _MIN_BARS or "close" not in df:
        return None
    close = df["close"].astype(float)
    rets = close.pct_change().dropna()
    if len(rets) < _MIN_RETURNS:
        return None
    window = rets.tail(lookback)
    sigma_d = float(window.std(ddof=1))
    if not (sigma_d > 0) or math.isnan(sigma_d):
        return None

    price = float(current_price) if current_price else float(close.iloc[-1])
    if not (price > 0):
        return None
    sigma_w = sigma_d * math.sqrt(TRADING_DAYS_WEEK)

    return {
        "anchor_price": round(price, 4),
        "sigma_daily_pct": round(sigma_d * 100, 2),
        "sigma_weekly_pct": round(sigma_w * 100, 2),
        "n_obs": int(len(window)),
        "method": "historical daily volatility (sigma of returns); week = daily x sqrt(5)",
        "basis": ("probable range from the stock's own recent volatility — not a "
                  "prediction, and direction is not forecast"),
        "confidence": {"typical": 68, "wide": 95},   # ~1 sigma / ~2 sigma, normal approx
        "day": _band(price, sigma_d),
        "week": _band(price, sigma_w),
    }
