"""Unified EGX daily-candle feed: EODHD first (broad coverage incl. small caps),
Yahoo as the free fallback.

Everything that needs daily candles (single-symbol analysis, the scanner, the
backtest) goes through ``fetch_daily`` here, so improving coverage is a one-line
switch and the rest of the app is untouched. Same contract as each adapter:

    fetch_daily(symbol, lookback="1y") -> (DataFrame[open,high,low,close,volume], meta)

Behaviour:
  * If an EODHD API key is configured, try EODHD first. If EODHD has no data for
    the symbol OR errors, fall back to Yahoo.
  * If no key is configured, use Yahoo directly (unchanged from before).
  * If NEITHER feed has the symbol, raise ``yahoo_egx.DataUnavailable`` (the API
    turns that into a 404 — honest "no data", never a fabricated plan).
"""
from __future__ import annotations

import pandas as pd

from . import yahoo_egx
from .yahoo_egx import DataUnavailable

try:
    from . import eodhd_egx
except Exception:  # pragma: no cover - adapter import must never break the app
    eodhd_egx = None


def fetch_daily(symbol: str, lookback: str = "1y", timeout: float = 10.0) -> tuple[pd.DataFrame, dict]:
    errors: list[str] = []

    if eodhd_egx is not None and eodhd_egx.enabled():
        try:
            return eodhd_egx.fetch_daily(symbol, lookback=lookback, timeout=timeout)
        except DataUnavailable as e:
            errors.append(f"EODHD: {e}")          # covered symbol? no — try Yahoo
        except Exception as e:                     # network/HTTP/parse — try Yahoo
            errors.append(f"EODHD error: {e}")

    try:
        return yahoo_egx.fetch_daily(symbol, lookback=lookback, timeout=timeout)
    except DataUnavailable as e:
        errors.append(f"Yahoo: {e}")
        raise DataUnavailable("; ".join(errors))   # neither feed has it -> 404
