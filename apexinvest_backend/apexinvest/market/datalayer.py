"""Provider-agnostic market-data layer.

The analysis engine should ask THIS module for data — not Yahoo or any specific
provider directly — so that (a) every response carries honest freshness + quality
metadata, and (b) a better feed can be plugged in later by editing one file.

It wraps the real, working sources we have:
  * Yahoo Finance — adjusted daily / weekly / monthly candles and history.
  * TradingView scanner — a delayed *current price* only (no candle history).

And it is honest about what we DON'T have: there is no free/legal real-time or
intraday (1m-4h) EGX feed, so get_ohlcv() for those timeframes returns
``available: False`` with a reason instead of fabricating candles. When a paid,
licensed intraday feed is added, register it here and the engine gets it for free.

Nothing is invented: freshness is computed from the data's own as-of date, and a
timeframe with no real source is reported unavailable, never faked.
"""
from __future__ import annotations

from datetime import date, datetime

from . import feed, tradingview_egx, yahoo_egx

# Timeframes we can truly serve today (daily and up), vs those that need a paid
# intraday feed we don't have. Kept explicit so the app never pretends.
AVAILABLE_TIMEFRAMES = {"1d", "1wk", "1mo"}
INTRADAY_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h", "4h"}
_NO_INTRADAY = ("No free or legal real-time/intraday EGX feed is available. "
                "1m-4h data (and a true 30-minute POC / accumulation-manipulation "
                "structure) require a paid, licensed feed — see the data-source panel.")

# How old (calendar days) an end-of-day close may be before we downgrade it.
# Weekend-tolerant: EGX trades Sun-Thu, so a Thursday close read on Sunday is ~3d.
FRESH_EOD_DAYS = 4        # <= this => "delayed_eod" (a normal last close)
FRESH_HIST_DAYS = 10      # <= this => "historical (lagging)"; beyond => "stale"

FRESHNESS_LABEL = {
    "delayed_eod": "Delayed (end-of-day close)",
    "historical": "Historical (feed lagging recent sessions)",
    "stale": "Stale — do not rely on it",
    "delayed_quote": "Delayed current price (~15 min)",
    "unknown": "Unknown freshness",
}


def _age_days(as_of: str | None) -> int | None:
    if not as_of:
        return None
    try:
        d = datetime.strptime(as_of, "%Y-%m-%d").date()
    except ValueError:
        return None
    return (date.today() - d).days


def _classify_eod(age_days: int | None) -> str:
    if age_days is None:
        return "unknown"
    if age_days <= FRESH_EOD_DAYS:
        return "delayed_eod"
    if age_days <= FRESH_HIST_DAYS:
        return "historical"
    return "stale"


def _quality(n: int, min_bars: int, adjusted: bool, freshness: str) -> dict:
    score, notes = 100, []
    if n < min_bars:
        score -= 30
        notes.append(f"only {n} bars (< {min_bars} wanted for full context)")
    if freshness == "historical":
        score -= 25
        notes.append("feed is a few sessions behind")
    elif freshness == "stale":
        score -= 50
        notes.append("data is stale")
    elif freshness == "unknown":
        score -= 20
        notes.append("could not date the latest bar")
    if not adjusted:
        score -= 10
        notes.append("prices not corporate-action adjusted")
    score = max(0, min(100, score))
    return {"score": score, "note": "; ".join(notes) or "clean, adjusted, sufficient history"}


def _provider_label(meta: dict) -> str:
    """Honest provider label for the data-source panel, derived from whichever
    adapter actually served this meta dict's ``source`` (EODHD or Yahoo) —
    never hardcoded, since ``feed.fetch_daily`` may return either."""
    if "EODHD" in str(meta.get("source") or ""):
        return "EODHD (EGX end-of-day, adjusted)"
    return "Yahoo Finance (EGX end-of-day, adjusted)"


def annotate_daily(meta: dict, n_candles: int, *, range_used: str, reason: str,
                   min_bars: int = 200) -> dict:
    """Attach honest freshness + quality fields to a daily meta dict (from either
    EODHD or Yahoo — see ``_provider_label``). Used by the analysis service so
    the frontend can show the data-source panel."""
    as_of = meta.get("as_of")
    age = _age_days(as_of)
    fresh = _classify_eod(age)
    adjusted = bool(meta.get("adjusted"))
    q = _quality(n_candles, min_bars, adjusted, fresh)
    return {
        **meta,
        "provider": _provider_label(meta),
        "timeframe": "1d",
        "data_type": "historical/end-of-day",
        "range_used": range_used,
        "range_reason": reason,
        "n_candles": n_candles,
        "data_age_days": age,
        "freshness": fresh,
        "freshness_label": FRESHNESS_LABEL.get(fresh, fresh),
        "adjusted": adjusted,
        "enough_history": n_candles >= min_bars,
        "quality_score": q["score"],
        "quality_note": q["note"],
        "is_live": False,      # never true on a free feed — stated explicitly
    }


# --------------------------------------------------------------------------- #
# Public data-layer interface
# --------------------------------------------------------------------------- #
def get_daily(symbol: str, *, lookback: str = "2y", min_bars: int = 200,
              reason: str = "trend, major S/R and higher-timeframe context"):
    """Adjusted daily candles + honest metadata. Provider-aware (EODHD or Yahoo,
    per DATA_PROVIDER / EODHD_API_TOKEN — see market/feed.py). Raises like
    yahoo_egx.fetch_daily / feed.DataProviderError."""
    df, meta = feed.fetch_daily(symbol, lookback=lookback)
    return {"available": True, "candles": df,
            "meta": annotate_daily(meta, len(df), range_used=lookback,
                                   reason=reason, min_bars=min_bars)}


def get_ohlcv(symbol: str, timeframe: str, *, lookback: str = "2y"):
    """Route by timeframe. Daily/weekly -> Yahoo. Intraday -> honestly unavailable."""
    if timeframe in INTRADAY_TIMEFRAMES:
        return {"available": False, "timeframe": timeframe, "reason": _NO_INTRADAY,
                "candles": None, "meta": {"is_live": False, "provider": None}}
    if timeframe not in AVAILABLE_TIMEFRAMES:
        return {"available": False, "timeframe": timeframe,
                "reason": f"Unsupported timeframe '{timeframe}'.", "candles": None, "meta": {}}
    return get_daily(symbol, lookback=lookback,
                     reason="higher-timeframe context" if timeframe != "1d" else
                            "trend, major S/R and higher-timeframe context")


def get_quote(symbol: str) -> dict:
    """Freshest current price we can get: TradingView delayed quote, else Yahoo EOD.
    Freshness is labelled honestly; never presented as real-time."""
    try:
        tv = tradingview_egx.fetch_quote(symbol)
    except Exception:
        tv = None
    if tv and tv.get("price"):
        return {**tv, "freshness": "delayed_quote",
                "freshness_label": FRESHNESS_LABEL["delayed_quote"], "is_live": False}
    try:
        y = yahoo_egx.fetch_quote(symbol)
        fresh = _classify_eod(_age_days(y.get("as_of")))
        return {**y, "source": y.get("source", "Yahoo (EOD)"), "freshness": fresh,
                "freshness_label": FRESHNESS_LABEL.get(fresh, fresh), "is_live": False}
    except Exception as e:
        return {"symbol": symbol.upper(), "price": None, "error": str(e),
                "freshness": "unknown", "is_live": False}


def health(probe_symbol: str = "COMI") -> dict:
    """Honest data-source health: what each provider can serve, and the current
    freshness of the daily feed (probed once). Never reports anything as LIVE."""
    daily_status = {"available": False}
    provider_name = "Yahoo Finance"  # updated below once we know which adapter actually answered
    try:
        d = get_daily(probe_symbol, lookback="1mo", min_bars=15)
        m = d["meta"]
        provider_name = m.get("provider") or provider_name
        daily_status = {"available": True, "as_of": m.get("as_of"),
                        "data_age_days": m.get("data_age_days"),
                        "freshness": m.get("freshness"),
                        "freshness_label": m.get("freshness_label"),
                        "adjusted": m.get("adjusted")}
    except Exception as e:
        daily_status = {"available": False, "error": str(e)[:120]}

    timeframes = {}
    for tf in ("1m", "5m", "15m", "30m", "1h", "4h"):
        timeframes[tf] = {"available": False, "provider": None,
                          "reason": "no free/legal intraday EGX feed"}
    for tf in ("1d", "1wk", "1mo"):
        timeframes[tf] = {"available": True, "provider": provider_name,
                          "data_type": "end-of-day", "is_live": False}

    return {
        "providers": [
            {"name": provider_name, "role": "daily/weekly/monthly, adjusted, history",
             "status": "available" if daily_status.get("available") else "unreachable",
             "timeframes": ["1d", "1wk", "1mo"], "is_live": False, **{"daily": daily_status}},
            {"name": "TradingView (scanner)", "role": "delayed current price only",
             "status": "best-effort", "timeframes": ["quote"], "is_live": False},
        ],
        "timeframes": timeframes,
        "best_for": {"quote": f"TradingView delayed → {provider_name}",
                     "daily": provider_name, "weekly": provider_name,
                     "history": provider_name,
                     "intraday": "NONE — requires a paid licensed feed"},
        "note": ("No free or legal real-time/intraday EGX feed exists. Daily and "
                 "longer history are adjusted end-of-day from Yahoo. Intraday (and a "
                 "true 30-minute POC) need a paid licensed feed. Nothing here is live."),
    }
