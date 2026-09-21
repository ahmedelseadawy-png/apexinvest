"""Unified EGX market-data feed: Yahoo is the default/primary provider. EODHD
is available only when explicitly selected — it is NOT used for normal
operation, even if an EODHD token happens to be configured. (Reverted from a
brief EODHD-first default after the configured EODHD account started hitting
its daily quota (HTTP 402) under normal load, e.g. full-universe scans — see
git history around "Restore Yahoo as default market data provider".)

Covers BOTH historical daily candles and the latest current/quote price — the
same DATA_PROVIDER switch governs both. Everything that needs daily candles
(single-symbol analysis, the scanner, the backtest) goes through
``fetch_daily`` here, and everything that needs a current price/quote goes
through ``fetch_quote``, so changing the provider is a one-line switch and the
rest of the app is untouched. Same contract as each adapter:

    fetch_daily(symbol, lookback="1y") -> (DataFrame[open,high,low,close,volume], meta)
    fetch_quote(symbol) -> {symbol, price, prev_close, change_pct, as_of, currency}

Behaviour is controlled by the optional ``DATA_PROVIDER`` environment variable
(identical rules for both functions):

  * unset / ``auto`` (default) / ``yahoo`` — Yahoo only. This is normal
    operation: EODHD is never called here, regardless of whether an EODHD
    token is configured. If Yahoo has no data for the symbol, raise
    ``yahoo_egx.DataUnavailable`` (the API turns that into a 404 — honest
    "no data", never a fabricated plan).
  * ``eodhd`` — EODHD only, opt-in. No Yahoo fallback: a failure raises
    ``DataProviderError`` (a ``DataUnavailable`` subclass, so it still becomes
    a clean 404) instead of silently substituting Yahoo data. Use this only
    when you deliberately want EODHD's broader small-cap coverage and have
    quota for it.
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


def provider_mode() -> str:
    """Public accessor for other modules (e.g. service.py's quote routing) that
    need to know whether a single provider is being forced."""
    return _provider_mode()


def fetch_daily(symbol: str, lookback: str = "1y", timeout: float = 10.0) -> tuple[pd.DataFrame, dict]:
    mode = _provider_mode()

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

    # "auto" (default/unset) and "yahoo": Yahoo is the primary/default
    # provider for normal operation. EODHD is opt-in only (DATA_PROVIDER=
    # eodhd) — no EODHD call happens here, even if a token is configured.
    return yahoo_egx.fetch_daily(symbol, lookback=lookback, timeout=timeout)


def fetch_quote(symbol: str, timeout: float = 8.0) -> dict:
    """Latest close + daily change for one EGX symbol. Same DATA_PROVIDER
    switch and fallback rules as ``fetch_daily`` (see module docstring).
    Returns {symbol, price, prev_close, change_pct, as_of, currency} — the
    exact same shape from either adapter, so callers never need to branch on
    which provider actually answered."""
    mode = _provider_mode()

    if mode == "eodhd":
        if eodhd_egx is None or not eodhd_egx.enabled():
            raise DataProviderError(
                "DATA_PROVIDER=eodhd but no EODHD token is configured (set EODHD_API_TOKEN)."
            )
        try:
            return eodhd_egx.fetch_quote(symbol, timeout=timeout)
        except DataUnavailable as e:
            raise DataProviderError(f"EODHD: {e}") from e
        except Exception as e:                      # network/HTTP/timeout/parse
            raise DataProviderError(f"EODHD error: {e}") from e

    # "auto" (default/unset) and "yahoo": Yahoo is the primary/default
    # provider for normal operation. EODHD is opt-in only (DATA_PROVIDER=
    # eodhd) — no EODHD call happens here, even if a token is configured.
    return yahoo_egx.fetch_quote(symbol, timeout=timeout)
