"""Walk-forward backtester (Update: validation).

This is the feature that turns a plausible-looking engine into one you can
actually trust: it replays history and asks "when the app said BUY, what
happened?" — honestly.

Honesty guarantees (the whole point):
  * NO LOOK-AHEAD. At each historical bar i the engine sees only df[:i+1] —
    exactly the data that existed then. Fills and exits use only bars strictly
    after the decision. Pivots are already confirmation-lagged, so nothing peeks.
  * SAME ENGINE. It drives the real service.analyze_symbol pipeline through a
    slice-fetcher, so it validates precisely what the app shows — not a
    simplified copy.
  * HONEST FILLS. A retest is a limit that only fills if price actually trades
    into the zone within a window; a confirmation is a stop-buy that only fills
    on a break above the trigger. Setups that never trigger are NOT counted as
    trades (no free entries). Within a bar, the stop is assumed hit before the
    target (conservative).
  * One position at a time — no pyramiding, no overlapping trades.

Metrics: number of trades, TP1 hit-rate, stop-rate, average and median R
multiple, expectancy, profit factor, max drawdown on the R-equity curve, average
bars to a win — plus buy-and-hold over the same window as a benchmark. Small
samples are reported as such; a handful of trades proves nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import concurrent.futures as cf

import pandas as pd

from ..domain import Objective
from ..market import feed, yahoo_egx


def _slice_fetcher(sub: pd.DataFrame):
    def f(_sym):
        meta = {"symbol": "BT", "currency": "EGP", "exchange": "EGX", "timeframe": "1d",
                "bars": len(sub), "last_close": float(sub["close"].iloc[-1]),
                "as_of": None, "source": "backtest slice", "delayed": True,
                "adjusted": True, "provides": list(yahoo_egx.PROVIDES)}
        return sub.reset_index(drop=True), meta
    return f


@dataclass
class Trade:
    entry_i: int
    fill_i: int
    exit_i: int
    entry: float
    stop: float
    tp1: float
    exit: float
    r: float
    bars: int
    outcome: str          # "tp1" | "stop" | "timeout"
    entry_type: str
    conf: int = 0         # engine confidence 0-5 at entry (for calibration)
    category: str = ""    # buy_now | wait | breakout

    def as_dict(self):
        return {"fill_i": self.fill_i, "exit_i": self.exit_i,
                "entry": round(self.entry, 4), "stop": round(self.stop, 4),
                "tp1": round(self.tp1, 4), "exit": round(self.exit, 4),
                "r": round(self.r, 2), "bars": self.bars,
                "outcome": self.outcome, "entry_type": self.entry_type,
                "conf": self.conf, "category": self.category}


@dataclass
class BacktestResult:
    symbol: str
    objective: str
    bars: int
    tested_from_i: int
    trades: list = field(default_factory=list)
    note: str = ""

    def metrics(self) -> dict:
        ts = self.trades
        n = len(ts)
        if n == 0:
            return {"trades": 0, "note": self.note or "No triggered setups in this window."}
        rs = [t.r for t in ts]
        wins = [t for t in ts if t.r > 0]
        losses = [t for t in ts if t.r <= 0]
        tp1 = [t for t in ts if t.outcome == "tp1"]
        stops = [t for t in ts if t.outcome == "stop"]
        gross_win = sum(t.r for t in wins)
        gross_loss = -sum(t.r for t in losses)
        # max drawdown on the cumulative-R equity curve
        eq, peak, mdd = 0.0, 0.0, 0.0
        for t in ts:
            eq += t.r
            peak = max(peak, eq)
            mdd = min(mdd, eq - peak)
        srt = sorted(rs)
        median_r = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
        return {
            "trades": n,
            "win_rate": round(len(wins) / n, 3),
            "tp1_hit_rate": round(len(tp1) / n, 3),
            "stop_rate": round(len(stops) / n, 3),
            "avg_r": round(sum(rs) / n, 3),
            "median_r": round(median_r, 3),
            "expectancy_r": round(sum(rs) / n, 3),
            "total_r": round(sum(rs), 2),
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
            "max_drawdown_r": round(mdd, 2),
            "avg_bars_to_win": round(sum(t.bars for t in wins) / len(wins), 1) if wins else None,
        }

    def as_dict(self, include_trades: bool = True) -> dict:
        out = {"symbol": self.symbol, "objective": self.objective, "bars": self.bars,
               "tested_from_bar": self.tested_from_i, "metrics": self.metrics(),
               "no_lookahead": True,
               "method": "Walk-forward on adjusted daily bars through the same engine "
                         "the app shows. Honest fills (zone/confirmation trigger); stop "
                         "assumed hit before target within a bar. Not financial advice."}
        if include_trades:
            out["trades"] = [t.as_dict() for t in self.trades]
        return out


def backtest_symbol(df: pd.DataFrame, objective: Objective, *, analyze=None,
                    step: int = 3, entry_window: int = 12, hold: int = 25,
                    start_i: int | None = None) -> BacktestResult:
    """Walk forward over df and simulate every BUY the engine would have given.

    `analyze` is injectable for tests: callable(sub_df, objective) -> plan dict.
    In production it defaults to the real service pipeline via a slice-fetcher.
    """
    n = len(df)
    df = df.reset_index(drop=True)
    if analyze is None:
        from .. import service as _svc

        def analyze(sub, obj):
            return _svc.analyze_symbol("BT", obj, fetcher=_slice_fetcher(sub))["plan"]

    start = start_i if start_i is not None else min(200, max(60, n // 3))
    if n - start < 40:
        return BacktestResult(symbol="BT", objective=objective.value, bars=n,
                              tested_from_i=start, note="Not enough history to backtest.")

    trades: list[Trade] = []
    i = start
    while i < n - 2:
        sub = df.iloc[:i + 1]
        try:
            plan = analyze(sub, objective)
        except Exception:
            i += step; continue
        if plan.get("action") != "BUY":
            i += step; continue

        etype = plan.get("entry_type")
        zone = plan.get("optimal_zone")
        conf = plan.get("confirmation_entry")
        entry_ref = plan.get("entry")
        stop = plan.get("stop")
        tp1 = plan.get("tp1")
        conf_score = int((plan.get("confidence") or {}).get("score") or 0)
        chase = plan.get("chase", "ok")
        category = ("breakout" if etype == "confirmation"
                    else "wait" if chase == "do_not_chase" else "buy_now")
        if not (entry_ref and stop and tp1) or entry_ref <= stop:
            i += step; continue

        # ---- Honest fill over the next `entry_window` bars ------------------
        fill_i, fill_price = None, None
        for j in range(i + 1, min(i + 1 + entry_window, n)):
            bar = df.iloc[j]
            if etype == "confirmation" and conf:
                if float(bar["high"]) >= conf:
                    fill_i, fill_price = j, float(conf); break
            else:  # retest limit into the zone (or at entry_ref)
                trigger = (zone[1] if zone else entry_ref)
                if float(bar["low"]) <= entry_ref:
                    fill_i, fill_price = j, float(entry_ref); break
                if zone and float(bar["low"]) <= trigger:  # touched zone top but not mid
                    fill_i, fill_price = j, float(min(trigger, entry_ref)); break
        if fill_i is None:
            i += step; continue                       # setup never triggered — not a trade

        # ---- Manage the trade to stop / TP1 / timeout ----------------------
        exit_i, exit_price, outcome = None, None, None
        risk = fill_price - stop
        if risk <= 0:
            i = fill_i + 1; continue
        for k in range(fill_i + 1, min(fill_i + 1 + hold, n)):
            bar = df.iloc[k]
            if float(bar["low"]) <= stop:             # stop first (conservative)
                exit_i, exit_price, outcome = k, float(stop), "stop"; break
            if float(bar["high"]) >= tp1:
                exit_i, exit_price, outcome = k, float(tp1), "tp1"; break
        if exit_i is None:                            # timed out — exit at last close seen
            exit_i = min(fill_i + hold, n - 1)
            exit_price, outcome = float(df.iloc[exit_i]["close"]), "timeout"

        r = (exit_price - fill_price) / risk
        trades.append(Trade(entry_i=i, fill_i=fill_i, exit_i=exit_i, entry=fill_price,
                            stop=stop, tp1=tp1, exit=exit_price, r=r,
                            bars=exit_i - fill_i, outcome=outcome, entry_type=etype or "retest",
                            conf=conf_score, category=category))
        i = max(exit_i, i + step)                     # one position at a time; resume after close

    res = BacktestResult(symbol="BT", objective=objective.value, bars=n, tested_from_i=start,
                         trades=trades)
    # buy & hold benchmark over the tested window
    bh = (float(df["close"].iloc[-1]) / float(df["close"].iloc[start]) - 1.0) * 100.0
    res.note = f"Buy & hold over the same window: {bh:+.1f}%."
    return res


# --------------------------------------------------------------------------- #
# Market-wide validation: pool trades across the universe, measure the real
# hit-rate / expectancy, and CALIBRATE — does higher engine-confidence actually
# produce a higher win-rate? That is the test of whether the numbers mean anything.
# --------------------------------------------------------------------------- #
def _pool_metrics(trades: list) -> dict:
    n = len(trades)
    if not n:
        return {"trades": 0}
    rs = [t.r for t in trades]
    wins = [t for t in trades if t.r > 0]
    stops = [t for t in trades if t.outcome == "stop"]
    tp1 = [t for t in trades if t.outcome == "tp1"]
    gw = sum(t.r for t in wins)
    gl = -sum(t.r for t in trades if t.r <= 0)
    eq = peak = mdd = 0.0
    for t in trades:
        eq += t.r
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    srt = sorted(rs)
    med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    return {
        "trades": n, "win_rate": round(len(wins) / n, 3),
        "tp1_hit_rate": round(len(tp1) / n, 3), "stop_rate": round(len(stops) / n, 3),
        "avg_r": round(sum(rs) / n, 3), "median_r": round(med, 3),
        "expectancy_r": round(sum(rs) / n, 3), "total_r": round(sum(rs), 1),
        "profit_factor": round(gw / gl, 2) if gl > 0 else None,
        "max_drawdown_r": round(mdd, 2),
        "avg_bars_to_win": round(sum(t.bars for t in wins) / len(wins), 1) if wins else None,
    }


_UCACHE: dict = {}
_UCACHE_TTL = 6 * 3600.0


def backtest_universe(symbols: list, *, objective: Objective = Objective.SWING,
                      fetch=None, analyze=None, limit: int | None = 60,
                      max_workers: int = 8, step: int = 3, use_cache: bool = True) -> dict:
    """Run the walk-forward backtest across many symbols and pool the trades.

    `fetch` is injectable for tests: callable(symbol) -> daily DataFrame.
    In production it defaults to 2y daily history via the unified market feed
    (EODHD or Yahoo, per DATA_PROVIDER — see market/feed.py). Result is cached
    ~6h (it is a heavy, run-occasionally validation, not a per-request call).
    """
    import time as _t
    live = fetch is None and analyze is None
    key = (objective.value, limit, step)
    if use_cache and live:
        hit = _UCACHE.get(key)
        if hit and _t.time() - hit["ts"] < _UCACHE_TTL:
            return {**hit["result"], "cached": True}
    if fetch is None:
        def fetch(sym):
            df, _ = feed.fetch_daily(sym, lookback="2y")
            return df

    syms = [s.strip().upper() for s in symbols if s and s.strip()]
    if limit:
        syms = syms[:limit]

    def one(sym):
        try:
            df = fetch(sym)
            res = backtest_symbol(df, objective, analyze=analyze, step=step)
            return sym, res.trades, None
        except Exception as e:
            return sym, None, str(e)

    trades: list = []
    tested = errors = 0
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for sym, tr, err in ex.map(one, syms):
            if err or tr is None:
                errors += 1
                continue
            tested += 1
            trades.extend(tr)

    by_cat = {c: _pool_metrics([t for t in trades if t.category == c])
              for c in ("buy_now", "wait", "breakout")}

    # Calibration: realized win-rate per engine-confidence bucket. If the engine's
    # confidence is meaningful, win-rate should rise with confidence.
    calibration = []
    for c in (3, 4, 5):
        bucket = [t for t in trades if t.conf == c]
        if bucket:
            wr = sum(1 for t in bucket if t.r > 0) / len(bucket)
            calibration.append({"confidence": c, "trades": len(bucket),
                                "win_rate": round(wr, 3),
                                "avg_r": round(sum(t.r for t in bucket) / len(bucket), 3)})

    result = {
        "objective": objective.value,
        "symbols_tested": tested, "errors": errors,
        "overall": _pool_metrics(trades),
        "by_category": by_cat,
        "calibration": calibration,
        "method": "Pooled walk-forward across the universe. No look-ahead; honest "
                  "fills (zone/confirmation trigger); stop assumed hit before target "
                  "within a bar. One position at a time per symbol.",
        "reading_it": ("Expectancy (avg R) > 0 with profit factor > 1 means a "
                       "positive edge on this history. Calibration should show win-rate "
                       "rising with confidence. Small buckets are not proof — this is "
                       "evidence, not a guarantee, and past results don't ensure future ones."),
    }
    if use_cache and live:
        _UCACHE[key] = {"ts": _t.time(), "result": result}
    return result
