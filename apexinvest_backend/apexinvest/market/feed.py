"""Unified EGX market-data feed: EODHD is the ONLY production market-data
provider, for both historical daily candles and the latest current/quote
price. Yahoo has been fully removed from the production fetch path (see git
history around "Restore EODHD as default market data provider") — it is
never called here, whatever ``DATA_PROVIDER`` is set to, and there is no
Yahoo fallback on an EODHD failure.

Everything that needs daily candles (single-symbol analysis, the scanner, the
backtest) goes through ``fetch_daily`` here, and everything that needs a
current price/quote goes through ``fetch_quote``. Same contract either way:

    fetch_daily(symbol, lookback="1y") -> (DataFrame[open,high,low,close,volume], meta)
    fetch_quote(symbol) -> {symbol, price, prev_close, change_pct, as_of, currency}

``DATA_PROVIDER`` is still read (``provider_mode()``) so other modules (e.g.
service.py's quote routing, which uses it to decide whether to skip the
TradingView overlay for a genuine single-source-of-truth mode) can tell
whether EODHD is explicitly forced via ``DATA_PROVIDER=eodhd`` vs. left at the
default (unset / ``auto``). As far as this module's own fetch behaviour goes,
though, every value resolves to the same place: EODHD only. A missing token
or an EODHD failure raises ``DataProviderError`` (a ``DataUnavailable``
subclass, so it still becomes a clean 404) — never a silent Yahoo
substitution.
"""
from __future__ import annotations

import os

import pandas as pd

# DataUnavailable is defined once in yahoo_egx and reused as the shared base
# exception across adapters. This import is NOT a Yahoo data-fetch call --
# Yahoo's fetch_daily/fetch_quote are never invoked from this module.
from .yahoo_egx import DataUnavailable

try:
    from . import eodhd_egx
except Exception:  # pragma: no cover - adapter import must never break the app
    eodhd_egx = None


class DataProviderError(DataUnavailable):
    """Raised when EODHD — the only production provider — fails or is
    unconfigured. Never silently substitutes Yahoo data."""


def _provider_mode() -> str:
    return (os.environ.get("DATA_PROVIDER") or "auto").strip().lower()


def provider_mode() -> str:
    """Public accessor for other modules (e.g. service.py's quote routing) that
    need to know whether EODHD is explicitly forced."""
    return _provider_mode()


def _require_eodhd() -> None:
    if eodhd_egx is None or not eodhd_egx.enabled():
        raise DataProviderError(
            "No EODHD token is configured (set EODHD_API_TOKEN). EODHD is the "
            "only production market-data provider."
        )


def fetch_daily(symbol: str, lookback: str = "1y", timeout: float = 10.0) -> tuple[pd.DataFrame, dict]:
    _require_eodhd()
    try:
        return eodhd_egx.fetch_daily(symbol, lookback=lookback, timeout=timeout)
    except DataUnavailable as e:
        raise DataProviderError(f"EODHD: {e}") from e
    except Exception as e:                      # network/HTTP/timeout/parse
        raise DataProviderError(f"EODHD error: {e}") from e


def fetch_quote(symbol: str, timeout: float = 8.0) -> dict:
    """Latest close + daily change for one EGX symbol. Returns
    {symbol, price, prev_close, change_pct, as_of, currency}."""
    _require_eodhd()
    try:
        return eodhd_egx.fetch_quote(symbol, timeout=timeout)
    except DataUnavailable as e:
        raise DataProviderError(f"EODHD: {e}") from e
    except Exception as e:                      # network/HTTP/timeout/parse
        raise DataProviderError(f"EODHD error: {e}") from e
