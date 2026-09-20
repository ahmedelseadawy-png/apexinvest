"""Unified EGX daily-candle feed: EODHD first (broad coverage incl. small caps),
Yahoo as the free fallback.

Everything that needs daily candles (single-symbol analysis, the scanner, the
backtest) goes through ``fetch_daily`` here, so improving coverage is a one-line
switch and the rest of the app is untouched. Same contract as each adapter:

    fetch_daily(symbol, lookback="1y") -> (DataFrame[open,high,low,close,volume], meta)

Behaviour is controlled by the optional ``DATA_PROVIDER`` environment variable:

  * unset / ``auto`` (default, unchanged from before) — if an EODHD API key is
    configured, try EODHD first; if EODHD has no data for the symbol OR errors,
    fall back to Yahoo. If no key is configured, use Yahoo directly. If NEITHER
    feed has the symbol, raise ``yahoo_egx.DataUnavailable`` (the API turns that
    into a 404 — honest "no data", never a fabricated plan).
  * ``eodhd`` — EODHD only. No Yahoo fallback: a failure raises
    ``DataProviderError`` (a ``DataUnavailable`` subclass, so it still becomes a
    clean 404) instead of silently substituting Yahoo data.
  * ``yahoo`` — Yahoo only, even if an EODHD key is configured.
"""
from __future__ import annotations

import os

import pandas as pd

from . import yahoo_egx
from .yahoo_egx import DataUnavailable

try:
    from . import eodhd_egx
except Exception:  # pragma: no cover - adapter import must never break the app
    eodhd_egx = None


class DataProviderError(DataUnavailable):
    """Raised when DATA_PROVIDER forces a single provider and it fails — never
    silently mixes in the other provider's data in that mode."""


def _provider_mode() -> str:
    return (os.environ.get("DATA_PROVIDER") or "auto").strip().lower()


def fetch_daily(symbol: str, lookback: str = "1y", timeout: float = 10.0) -> tuple[pd.DataFrame, dict]:
    mode = _provider_mode()

    if mode == "yahoo":
        return yahoo_egx.fetch_daily(symbol, lookback=lookback, timeout=timeout)

    if mode == "eodhd":
        if eodhd_egx is None or not eodhd_egx.enabled():
            raise DataProviderError(
                "DATA_PROVIDER=eodhd but no EODHD token is configured (set EODHD_API_TOKEN)."
            )
        try:
            return eodhd_egx.fetch_daily(symbol, lookback=lookback, timeout=timeout)
        except DataUnavailable as e:
            raise DataProviderError(f"EODHD: {e}") from e
        except Exception as e:                      # network/HTTP/timeout/parse
            raise DataProviderError(f"EODHD error: {e}") from e

    # mode == "auto" (or any unrecognised value): existing behaviour, unchanged.
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
