"""Unified EGX market-data feed: EODHD first (broad coverage incl. small caps),
Yahoo as the free fallback. Covers BOTH historical daily candles and the
latest current/quote price — the same DATA_PROVIDER switch governs both, so a
forced provider is a genuine single source of truth for price as well as
history, not just history.

Everything that needs daily candles (single-symbol analysis, the scanner, the
backtest) goes through ``fetch_daily`` here, and everything that needs a
current price/quote goes through ``fetch_quote``, so improving coverage is a
one-line switch and the rest of the app is untouched. Same contract as each
adapter:

    fetch_daily(symbol, lookback="1y") -> (DataFrame[open,high,low,close,volume], meta)
    fetch_quote(symbol) -> {symbol, price, prev_close, change_pct, as_of, currency}

Behaviour is controlled by the optional ``DATA_PROVIDER`` environment variable
(identical rules for both functions):

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


def provider_mode() -> str:
    """Public accessor for other modules (e.g. service.py's quote routing) that
    need to know whether a single provider is being forced."""
    return _provider_mode()


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


def fetch_quote(symbol: str, timeout: float = 8.0) -> dict:
    """Latest close + daily change for one EGX symbol. Same DATA_PROVIDER
    switch and fallback rules as ``fetch_daily`` (see module docstring).
    Returns {symbol, price, prev_close, change_pct, as_of, currency} — the
    exact same shape from either adapter, so callers never need to branch on
    which provider actually answered."""
    mode = _provider_mode()

    if mode == "yahoo":
        return yahoo_egx.fetch_quote(symbol, timeout=timeout)

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

    # mode == "auto" (or any unrecognised value): same fallback shape as fetch_daily.
    errors: list[str] = []

    if eodhd_egx is not None and eodhd_egx.enabled():
        try:
            return eodhd_egx.fetch_quote(symbol, timeout=timeout)
        except DataUnavailable as e:
            errors.append(f"EODHD: {e}")
        except Exception as e:
            errors.append(f"EODHD error: {e}")

    try:
        return yahoo_egx.fetch_quote(symbol, timeout=timeout)
    except DataUnavailable as e:
        errors.append(f"Yahoo: {e}")
        raise DataUnavailable("; ".join(errors))
