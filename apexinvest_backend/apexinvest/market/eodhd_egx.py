"""EGX market-data adapter — EODHD (licensed, broad coverage incl. small caps).

Yahoo's free feed only carries the liquid EGX names; thin small caps (e.g. CRST)
are missing. EODHD (eodhd.com) covers the Egyptian Exchange far more completely.
This adapter implements the SAME contract as ``yahoo_egx``:

    fetch_daily(symbol, lookback="1y") -> (DataFrame[open,high,low,close,volume], meta)

so it is a drop-in the rest of the app already knows how to use. It stays honest:
end-of-day daily candles only (``PROVIDES`` below), never claimed as real-time,
and it raises the shared ``yahoo_egx.DataUnavailable`` so the API keeps returning
404 for a symbol the feed genuinely has no data for.

Setup (no code change needed):
  * Get an API key from eodhd.com and set the environment variable
    ``EODHD_API_TOKEN`` (or the older ``EODHD_API_KEY`` / ``APEX_EODHD_KEY`` —
    all three are accepted, checked in that order) before starting the backend.
  * EGX symbols use the ``.EGX`` suffix by default (``COMI.EGX``). If EODHD ever
    uses a different exchange code for Egypt, set ``EODHD_EGX_SUFFIX`` to override
    it — no code change required.
When no key is set, ``enabled()`` is False and the app just uses Yahoo as before.
See ``market/feed.py`` for the ``DATA_PROVIDER`` switch that controls whether
EODHD is tried first with a Yahoo fallback (default) or used exclusively.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone

import pandas as pd

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

# Reuse ONE exception type across adapters so the API's 404 handling is uniform.
from .yahoo_egx import DataUnavailable

# Same honest capability set as the Yahoo EOD feed: daily candles only.
PROVIDES: list[str] = ["daily_chart", "volume", "volume_profile"]

_BASE_URL = "https://eodhd.com/api/eod/{sym}"

# lookback string -> approximate number of calendar days for the `from` date.
_LOOKBACK_DAYS = {"1mo": 31, "3mo": 92, "6mo": 183, "ytd": 365,
                  "1y": 366, "2y": 731, "5y": 1827, "10y": 3653}


def api_key() -> str | None:
    return (os.environ.get("EODHD_API_TOKEN") or os.environ.get("EODHD_API_KEY")
            or os.environ.get("APEX_EODHD_KEY") or None)


def enabled() -> bool:
    """True when an API key is configured — otherwise the app falls back to Yahoo."""
    return bool(api_key())


def _suffix() -> str:
    return (os.environ.get("EODHD_EGX_SUFFIX") or "EGX").strip().lstrip(".").upper()


def _eodhd_symbol(symbol: str) -> str:
    base = symbol.strip().upper()
    for suf in (".EGX", ".CA"):
        if base.endswith(suf):
            base = base[: -len(suf)]
    return f"{base}.{_suffix()}"


def _from_date(lookback: str) -> str | None:
    lb = (lookback or "").strip().lower()
    if lb == "max":
        return None
    days = _LOOKBACK_DAYS.get(lb, 731)  # default ~2y
    return (date.today() - timedelta(days=days)).isoformat()


def fetch_daily(symbol: str, lookback: str = "1y", timeout: float = 10.0) -> tuple[pd.DataFrame, dict]:
    """Return (candles, meta) for one EGX symbol from EODHD. Same shape as Yahoo.

    Raises DataUnavailable when the symbol has no data; requests.RequestException
    on network/HTTP errors (caller translates to 502).
    """
    if requests is None:  # pragma: no cover
        raise RuntimeError("The 'requests' package is required: pip install requests")
    key = api_key()
    if not key:
        raise DataUnavailable("EODHD API key not configured (set EODHD_API_KEY)")

    sym = _eodhd_symbol(symbol)
    params = {"api_token": key, "period": "d", "fmt": "json", "order": "a"}
    frm = _from_date(lookback)
    if frm:
        params["from"] = frm
    resp = requests.get(_BASE_URL.format(sym=sym), params=params, timeout=timeout)
    resp.raise_for_status()
    return _parse_eod(resp.json(), symbol.strip().upper().split(".")[0])


def fetch_quote(symbol: str, timeout: float = 8.0) -> dict:
    """Latest close + daily change (end-of-day / delayed), mirroring yahoo_egx."""
    df, meta = fetch_daily(symbol, lookback="1mo", timeout=timeout)
    price = float(df["close"].iloc[-1])
    prev = float(df["close"].iloc[-2]) if len(df) >= 2 else price
    change = ((price - prev) / prev * 100.0) if prev else 0.0
    return {
        "symbol": meta["symbol"], "price": round(price, 4), "prev_close": round(prev, 4),
        "change_pct": round(change, 2), "as_of": meta["as_of"], "currency": meta["currency"],
    }


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_eod(payload, sym: str) -> tuple[pd.DataFrame, dict]:
    """Parse an EODHD EOD JSON array into (DataFrame, meta). Pure — unit-testable
    by handing it a list of bar dicts directly (no network)."""
    if isinstance(payload, dict) and payload.get("error"):
        raise DataUnavailable(f"{sym}: {payload['error']}")
    rows_in = payload if isinstance(payload, list) else []
    if not rows_in:
        raise DataUnavailable(f"{sym}: no data returned by EODHD")

    rows = []
    adjusted = False
    last_date = None
    for bar in rows_in:
        o, h, l, c = _num(bar.get("open")), _num(bar.get("high")), _num(bar.get("low")), _num(bar.get("close"))
        if o is None or h is None or l is None or c is None:
            continue  # skip malformed bars — never invent a close
        ac = _num(bar.get("adjusted_close"))
        factor = (ac / c) if (ac is not None and c) else 1.0
        if abs(factor - 1.0) > 1e-6:
            adjusted = True
        vol = _num(bar.get("volume")) or 0.0
        rows.append((o * factor, h * factor, l * factor, c * factor, vol))
        last_date = bar.get("date") or last_date

    if len(rows) < 2:
        raise DataUnavailable(f"{sym}: not enough candles to analyze")

    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])
    meta = {
        "symbol": sym,
        "currency": "EGP",
        "exchange": "EGX",
        "timeframe": "1d",
        "bars": len(df),
        "last_close": float(df["close"].iloc[-1]),
        "as_of": (str(last_date)[:10] if last_date else
                  datetime.now(tz=timezone.utc).date().isoformat()),
        "source": "EODHD (EGX end-of-day)",
        "delayed": True,
        "adjusted": adjusted,
        "provides": list(PROVIDES),
    }
    return df, meta
