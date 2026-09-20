"""Company fundamentals for EGX names — best-effort, honest about coverage.

This addresses the app's weakest area: it was a purely *technical* tool with no
view of whether a company is financially sound. This module pulls fundamentals
(P/E, market cap, dividend yield, ROE, debt, revenue growth, margins, sector,
next earnings) from Yahoo's quoteSummary and turns them into a transparent
company-quality score (value / quality / growth / income).

HONESTY:
  * Coverage is partial — Yahoo has good fundamentals for large EGX names, thin
    or none for small ones. When a field is missing it is reported as null and
    excluded from the score; we never invent a fundamental number.
  * If Yahoo can't be reached or returns nothing, get() returns available:False.
    Fundamentals then simply don't factor into the decision (the technical
    engine still runs) — nothing breaks.
  * Yahoo now gates quoteSummary behind a cookie+crumb; we fetch it the standard
    way. If that ever stops working, this degrades to "unavailable", not wrong data.
"""
from __future__ import annotations

import time

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
_MODULES = ("summaryDetail,defaultKeyStatistics,financialData,price,"
            "summaryProfile,calendarEvents")
_CACHE: dict = {}
_TTL = 12 * 3600.0


def _raw(node, key):
    v = (node or {}).get(key)
    if isinstance(v, dict):
        return v.get("raw")
    return v if isinstance(v, (int, float)) else None


def _get_crumb(s):
    try:
        s.get("https://fc.yahoo.com", timeout=8)
    except Exception:
        pass
    r = s.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=8)
    return (r.text or "").strip()


def fetch_fundamentals(symbol: str, timeout: float = 10.0) -> dict:
    """Return a fundamentals dict for one EGX symbol, or {available: False}."""
    if requests is None:
        return {"available": False, "reason": "requests not installed"}
    sym = symbol.strip().upper().removesuffix(".CA")
    s = requests.Session()
    s.headers.update({"User-Agent": _UA, "Accept": "application/json"})
    try:
        crumb = _get_crumb(s)
        url = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{sym}.CA"
        r = s.get(url, params={"modules": _MODULES, "crumb": crumb}, timeout=timeout)
        r.raise_for_status()
        results = ((r.json() or {}).get("quoteSummary") or {}).get("result") or []
    except Exception as e:
        return {"available": False, "reason": f"feed error: {str(e)[:80]}"}
    if not results:
        return {"available": False, "reason": "no fundamentals for this symbol"}
    d = results[0]
    sd, ks = d.get("summaryDetail") or {}, d.get("defaultKeyStatistics") or {}
    fd, pr = d.get("financialData") or {}, d.get("price") or {}
    prof = d.get("summaryProfile") or {}
    cal = d.get("calendarEvents") or {}
    earnings = ((cal.get("earnings") or {}).get("earningsDate") or [{}])
    earn_ts = earnings[0].get("raw") if earnings and isinstance(earnings[0], dict) else None

    out = {
        "available": True, "symbol": sym,
        "name": (pr.get("longName") or pr.get("shortName")),
        "sector": prof.get("sector"), "industry": prof.get("industry"),
        "currency": pr.get("currency") or sd.get("currency") or "EGP",
        "market_cap": _raw(sd, "marketCap") or _raw(pr, "marketCap"),
        "pe": _raw(sd, "trailingPE"), "forward_pe": _raw(ks, "forwardPE"),
        "price_to_book": _raw(ks, "priceToBook") or _raw(sd, "priceToBook"),
        "eps": _raw(ks, "trailingEps"),
        "dividend_yield": _raw(sd, "dividendYield"),
        "roe": _raw(fd, "returnOnEquity"),
        "debt_to_equity": _raw(fd, "debtToEquity"),
        "revenue_growth": _raw(fd, "revenueGrowth"),
        "profit_margin": _raw(fd, "profitMargins"),
        "revenue": _raw(fd, "totalRevenue"),
        "next_earnings": (time.strftime("%Y-%m-%d", time.gmtime(earn_ts)) if earn_ts else None),
    }
    out["quality"] = score_company(out)
    return out


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def score_company(f: dict) -> dict:
    """Transparent 0-100 company-quality score from four pillars. Each pillar is
    scored only from the fields present; missing pillars are excluded (not zeroed),
    and 'coverage' says how much of the picture we actually had."""
    pillars, present = {}, 0

    # Value — reasonable P/E and P/B are better; extreme/negative are worse.
    pe, pb = f.get("pe"), f.get("price_to_book")
    if pe is not None or pb is not None:
        v = []
        if pe is not None:
            # Negative earnings first (loss-making) -> weak, before the positive bands.
            v.append(0.2 if pe <= 0 else 1.0 if pe <= 10 else 0.7 if pe <= 18 else 0.4 if pe <= 30 else 0.15)
        if pb is not None:
            v.append(1.0 if 0 < pb <= 1.5 else 0.7 if pb <= 3 else 0.4 if pb <= 6 else 0.2)
        pillars["value"] = sum(v) / len(v); present += 1

    # Quality — high ROE, low debt.
    roe, de = f.get("roe"), f.get("debt_to_equity")
    if roe is not None or de is not None:
        v = []
        if roe is not None:
            v.append(_clamp(roe / 0.25))          # 25% ROE -> full marks
        if de is not None:
            v.append(1.0 if de <= 50 else 0.7 if de <= 100 else 0.4 if de <= 200 else 0.2)
        pillars["quality"] = sum(v) / len(v); present += 1

    # Growth — revenue growth + margin.
    rg, pm = f.get("revenue_growth"), f.get("profit_margin")
    if rg is not None or pm is not None:
        v = []
        if rg is not None:
            v.append(_clamp((rg + 0.05) / 0.25))  # -5%..+20% -> 0..1
        if pm is not None:
            v.append(_clamp(pm / 0.20))
        pillars["growth"] = sum(v) / len(v); present += 1

    # Income — dividend yield.
    dy = f.get("dividend_yield")
    if dy is not None:
        pillars["income"] = _clamp(dy / 0.08)     # 8% yield -> full marks
        present += 1

    if not pillars:
        return {"score": None, "pillars": {}, "coverage": "none",
                "note": "No fundamental data available for this company."}
    score = round(100 * sum(pillars.values()) / len(pillars))
    cov = "full" if present >= 4 else "partial" if present >= 2 else "thin"
    return {"score": score, "pillars": {k: round(v, 2) for k, v in pillars.items()},
            "coverage": cov,
            "note": f"{present}/4 pillars had data ({cov} coverage)."}


def get(symbol: str, *, use_cache: bool = True) -> dict:
    key = symbol.strip().upper()
    if use_cache:
        hit = _CACHE.get(key)
        if hit and time.time() - hit["ts"] < _TTL:
            return hit["result"]
    res = fetch_fundamentals(symbol)
    if use_cache and res.get("available"):
        _CACHE[key] = {"ts": time.time(), "result": res}
    return res
