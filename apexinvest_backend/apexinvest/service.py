"""Application service: orchestrates the engines into one analyze() call.

This is the seam the API and tests both use. It runs the full pipeline:
regime -> strategies -> risk plan, honouring AUTO (recommendation) or MANUAL.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .domain import Objective
from .engines import recommendation as reco
from .engines import regime as regime_engine
from .engines import risk
from .engines import strategies as strat
from .engines.strategies import StrategyContext
from .market import feed, tradingview_egx, yahoo_egx


@dataclass
class AnalyzeInput:
    objective: Objective
    mode: str                                   # "auto" | "manual"
    manual_strategies: list[str] = field(default_factory=list)
    candles: dict[str, pd.DataFrame] = field(default_factory=dict)  # timeframe -> df
    fundamentals: dict | None = None
    reference_price: float | None = None
    provided_inputs: list[str] = field(default_factory=list)


def _build_context(inp: AnalyzeInput) -> StrategyContext:
    reg = None
    primary = None
    for tf in ("1d", "1w", "4h", "1h", "30m", "15m", "5m"):
        if tf in inp.candles:
            primary = inp.candles[tf]
            break
    if primary is None and inp.candles:
        primary = next(iter(inp.candles.values()))
    if primary is not None and len(primary) >= 30:
        reg = regime_engine.detect_regime(primary)
    return StrategyContext(
        candles=inp.candles, regime=reg,
        fundamentals=inp.fundamentals, objective=inp.objective,
    )


def get_requirements(inp: AnalyzeInput) -> dict:
    """Return the strategies to run and the inputs the user must provide."""
    ctx = _build_context(inp)
    if inp.mode == "auto":
        rec = reco.recommend(inp.objective, ctx)
        return {
            "mode": "auto",
            "strategies": rec.recommended,
            "required_inputs": rec.required_inputs,
            "recommendation": rec.as_dict(),
        }
    if not inp.manual_strategies:
        raise ValueError("manual mode requires at least one strategy")
    for s in inp.manual_strategies:
        strat.get(s)  # validate
    return {
        "mode": "manual",
        "strategies": inp.manual_strategies,
        "required_inputs": strat.required_inputs_for(inp.manual_strategies),
        "recommendation": None,
    }


def analyze(inp: AnalyzeInput) -> dict:
    ctx = _build_context(inp)
    req = get_requirements(inp)
    strategy_ids: list[str] = req["strategies"]
    required_inputs: list[str] = req["required_inputs"]

    signals = [strat.get(s).evaluate(ctx) for s in strategy_ids]

    primary_candles = None
    for tf in ("1d", "1w", "4h", "1h", "30m", "15m", "5m"):
        if tf in inp.candles:
            primary_candles = inp.candles[tf]
            break
    if primary_candles is None and inp.candles:
        primary_candles = next(iter(inp.candles.values()))

    ref_price = inp.reference_price
    if ref_price is None and primary_candles is not None and len(primary_candles):
        ref_price = float(primary_candles["close"].iloc[-1])

    plan = risk.build_plan(
        objective=inp.objective,
        signals=signals,
        primary_candles=primary_candles,
        reference_price=ref_price,
        regime=ctx.regime,
        required_inputs=required_inputs,
        provided_inputs=inp.provided_inputs,
        timeframes_provided=len(inp.candles) or 1,
    )

    return {
        "objective": inp.objective.value,
        "mode": inp.mode,
        "strategies": strategy_ids,
        "regime": ctx.regime.as_dict() if ctx.regime else None,
        "signals": [s.as_dict() for s in signals],
        "plan": plan.as_dict(),
        "disclaimer": "Educational decision-support, not financial advice. "
                      "Every value is derived from provided data; do your own research.",
    }


# --------------------------------------------------------------------------- #
# Auto analysis from a market-data feed (no manual upload).
# --------------------------------------------------------------------------- #

def _wait_result(objective: Objective, candles: dict, ref_price: float,
                 reason: str, missing: list[str]) -> dict:
    """Build a normal analyze() result whose plan is WAIT, with a clear reason.
    Runs the pipeline with no declared inputs so the engine itself returns WAIT
    (no fabricated levels), then annotates why."""
    inp = AnalyzeInput(objective=objective, mode="auto", candles=candles,
                       reference_price=ref_price, provided_inputs=[])
    out = analyze(inp)
    out["plan"]["action"] = "WAIT"
    out["plan"]["reason"] = reason
    out["plan"]["missing"] = missing
    return out


def _eod_quotes(symbols: list[str], *, fetcher=None, max_workers: int = 8) -> dict:
    """End-of-day quotes for several symbols via the unified market feed
    (EODHD or Yahoo, per DATA_PROVIDER — see market/feed.py), fetched
    concurrently. Omits misses."""
    import concurrent.futures as cf
    fetch = fetcher or feed.fetch_quote

    def one(sym):
        try:
            return sym, fetch(sym)
        except Exception:
            return sym, None

    out: dict = {}
    if not symbols:
        return out
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for sym, q in ex.map(one, symbols):
            if q:
                out[sym.upper()] = q
    return out


def quotes(symbols: list[str], *, fetcher=None, max_workers: int = 8) -> dict:
    """Latest price + daily change for several EGX symbols.

    Default (DATA_PROVIDER unset/auto, unchanged from before): TradingView is
    tried first (fresher current price); any symbol it doesn't return falls
    back to the unified EOD feed (EODHD if configured, else Yahoo). If
    TradingView is blocked or offline it simply returns nothing and everything
    comes from the EOD feed.

    DATA_PROVIDER=eodhd: EODHD is the single source of truth for price exactly
    as it is for historical OHLCV — TradingView is skipped entirely so no other
    source is ever mixed in, and a symbol EODHD can't answer is simply omitted
    (never silently replaced by Yahoo). Symbols the active source(s) miss are
    always omitted — never faked. Each quote carries its `source` when the
    underlying adapter provides one.
    """
    if not symbols:
        return {}
    syms = [s.strip().upper() for s in symbols if s and s.strip()]

    if feed.provider_mode() == "eodhd":
        return _eod_quotes(syms, fetcher=fetcher, max_workers=max_workers)

    # 1) TradingView (fresher). Never raises; {} if blocked/offline.
    try:
        out = dict(tradingview_egx.fetch_quotes(syms))
    except Exception:
        out = {}

    # 2) EOD fallback (EODHD if configured, else Yahoo) for whatever TradingView didn't cover.
    missing = [s for s in syms if s not in out]
    if missing:
        for sym, q in _eod_quotes(missing, fetcher=fetcher, max_workers=max_workers).items():
            out.setdefault(sym, q)
    return out


def _crosscheck_price(eod_close: float, live_price: float, *, eod_label: str = "EOD") -> dict:
    """Compare two independent price sources (the EOD close vs the freshest
    quote actually used). `eod_label` names whichever adapter served the EOD
    close — EODHD or Yahoo — so the note is honest about the real baseline,
    never hardcoded to one provider. Returns the gap and an agreement flag.
    This never fabricates or reconciles the numbers — it only reports whether
    they agree, so a stale/wrong feed is visible.
    """
    if not eod_close or not live_price or eod_close <= 0:
        return {"available": False}
    diff_pct = round((live_price - eod_close) / eod_close * 100, 2)
    ad = abs(diff_pct)
    # <=6% is a normal single-session move; >6% flags a possible stale/mismatched feed.
    agree = ad <= 6.0
    return {
        "available": True,
        "eod_close": round(eod_close, 4),
        "live_price": round(live_price, 4),
        "diff_pct": diff_pct,
        "agree": agree,
        "severity": "ok" if agree else ("warn" if ad <= 15 else "high"),
        "note": (f"Freshest quote is {diff_pct:+.2f}% vs {eod_label} EOD — "
                 + ("sources agree." if agree
                    else "large gap; one feed may be stale or mismatched. Treat the current price with caution.")),
    }


def _eod_provider_label(meta: dict) -> str:
    """Short, honest name of whichever adapter served this meta dict's EOD
    close (EODHD or Yahoo) — for wording only, never for calculations."""
    return "EODHD" if "EODHD" in str(meta.get("source") or "") else "Yahoo"


def analyze_symbol(symbol: str, objective: Objective, *, fetcher=None,
                   lookback: str = "2y", live_price: bool = True) -> dict:
    """Fetch candles for an EGX symbol and run the full analysis automatically.

    The R:R math is built by the same engine used everywhere; this just supplies
    the candles from a data feed instead of a manual upload. It only runs the
    strategies the feed can honestly satisfy (see yahoo_egx.PROVIDES) and never
    declares data it does not have — so the anti-fabrication guarantee holds.

    `fetcher` is injectable for testing: any callable(symbol) -> (DataFrame, meta).
    Raises yahoo_egx.DataUnavailable / requests errors for the caller to handle.
    """
    if fetcher is not None:
        df, meta = fetcher(symbol)
    else:
        df, meta = feed.fetch_daily(symbol, lookback=lookback)
    provides = set(meta.get("provides") or yahoo_egx.PROVIDES)
    yahoo_close = float(df["close"].iloc[-1])

    # Entry reference = the freshest current price.
    #
    # DATA_PROVIDER=eodhd: EODHD is the single source of truth for ALL price
    # data (history AND current price) — TradingView is never called; the only
    # "fresher" lookup attempted is another EODHD quote via feed.fetch_quote().
    #
    # Default (auto) / DATA_PROVIDER=yahoo: unchanged from before — try
    # TradingView first (often a trading day fresher than the EOD close);
    # fall back to the already-fetched EOD close. The candle HISTORY always
    # stays whatever feed.fetch_daily() returned — TradingView is price-only.
    #
    # Skipped entirely when a test fetcher is injected so tests stay hermetic.
    last = yahoo_close
    meta = {**meta, "price": round(yahoo_close, 4),
            "price_source": meta.get("source"), "price_as_of": meta.get("as_of")}
    if fetcher is None and live_price:
        forced_eodhd = feed.provider_mode() == "eodhd"
        try:
            fresh = feed.fetch_quote(symbol) if forced_eodhd else tradingview_egx.fetch_quote(symbol)
        except Exception:
            fresh = None
        if fresh and fresh.get("price"):
            last = float(fresh["price"])
            meta["price"] = round(last, 4)
            meta["price_source"] = fresh.get("source") or meta.get("source")
            meta["price_as_of"] = fresh.get("as_of")
            # Cross-validate the two independent sources. A large gap between the
            # freshest quote and the EOD close means one feed is stale or wrong;
            # we surface it instead of trusting a single number silently. A normal
            # gap is just one session's move; only a big one is a warning.
            meta["price_crosscheck"] = _crosscheck_price(
                yahoo_close, last, eod_label=_eod_provider_label(meta))

    # Honest freshness + quality metadata via the data layer (source, data age,
    # freshness class, adjusted, range used + reason, quality score). Never "live".
    from .market import datalayer
    meta = datalayer.annotate_daily(
        meta, len(df), range_used=lookback,
        reason="trend, major support/resistance and higher-timeframe context",
        min_bars=200)

    candles = {"1d": df}

    # What AUTO would pick, and which of those this feed can actually feed.
    rec = get_requirements(AnalyzeInput(objective=objective, mode="auto",
                                        candles=candles, reference_price=last))
    wanted = rec["strategies"]
    usable = [s for s in wanted if set(strat.required_inputs_for([s])) <= provides]
    skipped = [s for s in wanted if s not in usable]

    def envelope(core: dict) -> dict:
        core["data_source"] = meta
        # Company fundamentals (best-effort, never fabricated). Purely additive:
        # the technical plan is already built; this attaches a company-quality view
        # so a technically-clean setup on a weak business is visible. Skipped for
        # injected fetchers (hermetic tests) and any failure degrades to unavailable.
        if fetcher is None:
            try:
                from .market import fundamentals as fun
                core["fundamentals"] = fun.get(symbol)
            except Exception:
                core["fundamentals"] = {"available": False, "reason": "unavailable"}
        # Include the candles so the frontend can draw the analysis on real data
        # (last 160 daily bars is plenty for the charts and keeps payload small).
        tail = df.tail(160)
        core["candles"] = [
            {"o": round(float(o), 4), "h": round(float(h), 4), "l": round(float(l), 4),
             "c": round(float(c), 4), "v": float(v)}
            for o, h, l, c, v in zip(tail["open"], tail["high"], tail["low"], tail["close"], tail["volume"])
        ]
        # Expected-move projection from REAL recent volatility (next day + next
        # week, typical/wide bands). Purely additive and always present — it works
        # even when the plan is WAIT (e.g. day-trade), so a user already holding
        # the stock still gets an honest range. Never fabricates a price.
        try:
            from .engines import expected_move as _em
            core["expected_move"] = _em.compute(df, last)
        except Exception:
            core["expected_move"] = None
        # Long-Term Investment Target Engine (additive only — see engines/
        # long_term_plan.py's module docstring). Always attached, regardless of
        # `objective`, so it's backward compatible for any API consumer and the
        # UI can show it whenever it's useful; it never touches the existing
        # BUY/WAIT/AVOID action, which it only reads (never overrides) for
        # `entry_status`. A failure here can never fail the rest of the analysis.
        from .engines import long_term_plan as _ltp
        try:
            ltp = _ltp.build(df, last)
            if ltp.get("enabled"):
                entry_status = core.get("plan", {}).get("action", "WAIT")
                ltp["entry_status"] = entry_status
                ltp["thesis"] = _ltp.thesis_for(ltp["outlook"], entry_status)
            core["long_term_plan"] = ltp
        except Exception:
            core["long_term_plan"] = {"enabled": False, "reason": _ltp.INSUFFICIENT_DATA_MSG}
        core["auto"] = {
            "objective": objective.value,
            "recommended": wanted,
            "used": usable,
            "skipped_need_more": [
                {"strategy": s,
                 "needs": [i for i in strat.required_inputs_for([s]) if i not in provides]}
                for s in skipped
            ],
            "feed_provides": sorted(provides),
        }
        return core

    if len(df) < 30:
        return envelope(_wait_result(objective, candles, last,
            f"Only {len(df)} daily bars available — need ~30+ to build a plan.", []))

    # Day-trading genuinely needs intraday data this end-of-day feed can't supply.
    if objective == Objective.DAY:
        return envelope(_wait_result(objective, candles, last,
            "Day-trading needs intraday data; this feed is end-of-day (daily) only. "
            "Try Swing or Long-term.", ["intraday_chart"]))

    if not usable:
        need = sorted({i for s in wanted for i in strat.required_inputs_for([s])
                       if i not in provides})
        return envelope(_wait_result(objective, candles, last,
            "This objective needs data the free end-of-day feed can't supply "
            f"({', '.join(need)}).", need))

    inp = AnalyzeInput(objective=objective, mode="manual", manual_strategies=usable,
                       candles=candles, reference_price=last,
                       provided_inputs=list(provides))
    return envelope(analyze(inp))
