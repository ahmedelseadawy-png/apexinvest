"""EGX market-data adapter (free, end-of-day).

Fetches daily OHLCV candles for an Egyptian Exchange symbol from Yahoo Finance,
which lists EGX stocks with a ``.CA`` suffix (e.g. ``COMI.CA``, ``SWDY.CA``).

This is the honest, no-account data path for the prototype:

  * It is **end-of-day / delayed and unofficial** — good for swing and
    long-term analysis (which is what the engine builds), NOT for intraday /
    day-trading, and a few small names may be missing.
  * It returns **daily candles only** — Yahoo does not serve intraday history
    for EGX. ``PROVIDES`` below states exactly what an EOD daily series can
    legitimately satisfy, so the engine never claims data it does not have.

To move to a licensed real-time feed later, implement the same
``fetch_daily(symbol) -> (DataFrame, meta)`` contract against that provider and
swap it in; nothing else in the app needs to change.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

try:  # requests is the only extra dependency this adapter needs
    import requests
except ImportError:  # pragma: no cover - surfaced clearly at call time
    requests = None

# What a daily OHLCV series can HONESTLY satisfy. Intraday_chart and financials
# are deliberately absent — this feed does not provide them.
PROVIDES: list[str] = ["daily_chart", "volume", "volume_profile"]

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}.CA"
_HEADERS = {"User-Agent": "Mozilla/5.0 (ApexInvest data adapter)"}


class DataUnavailable(RuntimeError):
    """Raised when the feed returns no usable candles for a symbol."""


# Yahoo's chart API only accepts these range values — anything else can make it
# return an error or empty payload (that is what silently broke live analysis when
# an "18mo" range slipped in). We normalise to the nearest valid one so a bad
# range can never take the feed down again.
_VALID_RANGES = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}


def _norm_range(lookback: str) -> str:
    lb = (lookback or "").strip().lower()
    if lb in _VALID_RANGES:
        return lb
    # map a "<N>mo" or "<N>y" to the nearest valid bucket
    try:
        if lb.endswith("mo"):
            m = int(lb[:-2])
            return "6mo" if m <= 6 else "1y" if m <= 12 else "2y"
        if lb.endswith("y"):
            y = int(lb[:-1])
            return "1y" if y <= 1 else "2y" if y <= 2 else "5y"
    except ValueError:
        pass
    return "2y"


def fetch_daily(symbol: str, lookback: str = "1y", timeout: float = 10.0) -> tuple[pd.DataFrame, dict]:
    """Return (candles, meta) for one EGX symbol.

    candles: DataFrame with columns open, high, low, close, volume (daily).
    meta:    dict describing the source, currency, timeframe, as-of date.
    Raises DataUnavailable if the symbol has no data; requests.RequestException
    on network/HTTP errors (let the caller translate to a 502).
    """
    if requests is None:  # pragma: no cover
        raise RuntimeError("The 'requests' package is required: pip install requests")

    sym = symbol.strip().upper().removesuffix(".CA")
    resp = requests.get(
        _CHART_URL.format(sym=sym),
        params={"range": _norm_range(lookback), "interval": "1d"},
        headers=_HEADERS,
        timeout=timeout,
    )
    # Yahoo answers 404 (and sometimes 400) for a ticker it simply doesn't carry
    # — common for thin EGX small caps like VLMR. That is "no data for this
    # symbol", NOT a backend/feed fault: raise DataUnavailable so the API returns
    # a clean 404 ("no free data for this stock") instead of a scary 502 that the
    # UI would mislabel as "backend offline". Real server faults (5xx) still
    # raise below and surface as a genuine feed error.
    if resp.status_code in (400, 404):
        raise DataUnavailable(f"{sym}.CA: not covered by the free Yahoo feed")
    resp.raise_for_status()
    payload = resp.json()
    return _parse_chart(payload, sym)


def fetch_quote(symbol: str, timeout: float = 8.0) -> dict:
    """Latest price + daily change for one EGX symbol (end-of-day / delayed).

    Returns {symbol, price, prev_close, change_pct, as_of, currency}. Raises
    DataUnavailable / requests errors like fetch_daily.
    """
    df, meta = fetch_daily(symbol, lookback="5d", timeout=timeout)
    price = float(df["close"].iloc[-1])
    prev = float(df["close"].iloc[-2]) if len(df) >= 2 else price
    change = ((price - prev) / prev * 100.0) if prev else 0.0
    return {
        "symbol": meta["symbol"], "price": round(price, 4), "prev_close": round(prev, 4),
        "change_pct": round(change, 2), "as_of": meta["as_of"], "currency": meta["currency"],
    }


def _parse_chart(payload: dict, sym: str) -> tuple[pd.DataFrame, dict]:
    """Parse a Yahoo v8 chart payload into (DataFrame, meta). Pure — unit-testable
    without the network by handing it a payload dict directly."""
    chart = (payload or {}).get("chart") or {}
    if chart.get("error"):
        raise DataUnavailable(f"{sym}.CA: {chart['error']}")
    results = chart.get("result") or []
    if not results:
        raise DataUnavailable(f"{sym}.CA: no data returned by the feed")

    res = results[0]
    meta_in = res.get("meta") or {}
    stamps = res.get("timestamp") or []
    indic = res.get("indicators") or {}
    quote = (indic.get("quote") or [{}])[0]
    o, h, l, c = quote.get("open", []), quote.get("high", []), quote.get("low", []), quote.get("close", [])
    v = quote.get("volume", [])
    # Adjusted close (splits + dividends). Back-adjusting OHLC by the adjclose/close
    # ratio makes the series CONTINUOUS across corporate actions, so moving
    # averages, volume-profile POC and breakout levels are not silently corrupted
    # around each dividend or bonus/split. EGX names pay/adjust often, so this
    # matters. Falls back to raw prices when Yahoo omits adjclose.
    adj = ((indic.get("adjclose") or [{}])[0] or {}).get("adjclose", [])
    adjusted = False

    rows = []
    last_valid_ts = None  # timestamp of the last bar that actually has a close
    for i in range(len(stamps)):
        oi, hi, li, ci = _at(o, i), _at(h, i), _at(l, i), _at(c, i)
        if oi is None or hi is None or li is None or ci is None:
            continue  # skip holidays / not-yet-posted sessions — never invent a close
        ai = _at(adj, i)
        factor = (float(ai) / float(ci)) if (ai is not None and ci) else 1.0
        if abs(factor - 1.0) > 1e-6:
            adjusted = True
        rows.append((float(oi) * factor, float(hi) * factor, float(li) * factor,
                     float(ci) * factor, float(_at(v, i) or 0.0)))
        last_valid_ts = stamps[i]

    if len(rows) < 2:
        raise DataUnavailable(f"{sym}.CA: not enough candles to analyze")

    df = pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])
    # as_of is the date of the price we actually show — the last bar WITH a close.
    # (Yahoo often adds an empty slot for the newest session before its close is
    # posted; dating the price to that empty slot would overstate freshness.)
    meta = {
        "symbol": sym,
        "currency": meta_in.get("currency", "EGP"),
        "exchange": meta_in.get("exchangeName", "EGX"),
        "timeframe": "1d",
        "bars": len(df),
        "last_close": float(df["close"].iloc[-1]),
        "as_of": (
            datetime.fromtimestamp(last_valid_ts, tz=timezone.utc).date().isoformat()
            if last_valid_ts else None
        ),
        "source": "Yahoo Finance (EGX end-of-day, .CA)",
        "delayed": True,
        "adjusted": adjusted,
        "provides": list(PROVIDES),
    }
    return df, meta


def _at(seq, i):
    return seq[i] if seq and i < len(seq) else None
