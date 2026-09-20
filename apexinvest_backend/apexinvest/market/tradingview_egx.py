"""TradingView quote adapter — fresher *current price* (personal use).

TradingView's public screener endpoint returns the latest (delayed) close for
EGX symbols, often a trading day fresher than the free Yahoo EOD feed (which can
leave the newest session's close empty). It is used ONLY as a best-effort
current-price source, with Yahoo as the reliable fallback.

IMPORTANT / honest scoping:
  * This endpoint is UNOFFICIAL and using it programmatically is against
    TradingView's Terms of Service. It is fine for a personal prototype but is
    NOT suitable for an app you share or publish. If it ever blocks or changes,
    every call here simply returns {} and the app falls back to Yahoo.
  * It provides a price only — never candle history. All analysis history still
    comes from Yahoo.
"""
from __future__ import annotations

from datetime import date

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

_URL = "https://scanner.tradingview.com/egypt/scan"
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"),
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
}


def fetch_quotes(symbols: list[str], timeout: float = 8.0) -> dict:
    """Return {SYMBOL: {symbol, price, change_pct, currency, as_of, source}} for
    the EGX symbols TradingView knows. Returns {} on ANY error (blocked, offline,
    format change) so the caller falls back to Yahoo — never raises, never fakes."""
    if requests is None or not symbols:
        return {}
    tickers = [f"EGX:{s.strip().upper().removesuffix('.CA')}" for s in symbols if s.strip()]
    body = {"symbols": {"tickers": tickers, "query": {"types": []}},
            "columns": ["close", "change", "currency"]}
    try:
        r = requests.post(_URL, json=body, headers=_HEADERS, timeout=timeout)
        r.raise_for_status()
        rows = (r.json() or {}).get("data") or []
    except Exception:
        return {}

    today = date.today().isoformat()
    out: dict = {}
    for row in rows:
        sym = (row.get("s") or "").split(":")[-1].upper()
        d = row.get("d") or []
        if not sym or not d or d[0] is None:
            continue
        price = float(d[0])
        change = float(d[1]) if len(d) > 1 and d[1] is not None else 0.0
        ccy = d[2] if len(d) > 2 and d[2] else "EGP"
        out[sym] = {
            "symbol": sym, "price": round(price, 4), "change_pct": round(change, 2),
            "currency": ccy, "as_of": today, "source": "TradingView (delayed)",
        }
    return out


def fetch_quote(symbol: str, timeout: float = 8.0) -> dict | None:
    """Single-symbol convenience; None if TradingView doesn't return it."""
    q = fetch_quotes([symbol], timeout=timeout)
    return q.get(symbol.strip().upper().removesuffix(".CA"))
