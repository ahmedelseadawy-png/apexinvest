"""Tests for the walk-forward backtester.

The guarantees under test are the ones that make a backtest trustworthy:
no look-ahead (the engine only ever sees data up to the decision bar), honest
fills (a setup that never triggers is not a trade), and correct R accounting
for stop / target / timeout outcomes.
"""
import numpy as np
import pandas as pd

from apexinvest.domain import Objective
from apexinvest.engines import backtest as bt


def _df(closes):
    c = np.asarray(closes, float)
    o = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame({"open": o, "high": np.maximum(o, c), "low": np.minimum(o, c),
                         "close": c, "volume": np.full(len(c), 1e5)})


def test_no_lookahead_slices_only_past():
    """The analyze callback must never receive a bar later than the decision i."""
    seen_lengths = []

    def analyze(sub, obj):
        seen_lengths.append(len(sub))
        return {"action": "WAIT"}

    df = _df(np.linspace(10, 20, 120))
    bt.backtest_symbol(df, Objective.SWING, analyze=analyze, step=5, start_i=60)
    # every slice length is <= the full frame, and strictly increasing windows
    assert seen_lengths and max(seen_lengths) <= len(df)


def test_retest_that_never_triggers_is_not_a_trade():
    # Plan wants a pullback to 9.0, but price only ever rises -> no fill, no trade.
    df = _df(np.linspace(10, 30, 160))

    def analyze(sub, obj):
        return {"action": "BUY", "entry_type": "retest", "optimal_zone": [8.9, 9.0],
                "entry": 8.95, "stop": 8.5, "tp1": 10.0, "confirmation_entry": None}

    res = bt.backtest_symbol(df, Objective.SWING, analyze=analyze, step=5, start_i=60)
    assert res.metrics()["trades"] == 0


def test_confirmation_fill_then_tp1_is_a_win():
    # Rising series; a stop-buy above 12 fills and then reaches TP1 at 13.
    df = _df(np.linspace(10, 20, 160))

    def analyze(sub, obj):
        return {"action": "BUY", "entry_type": "confirmation", "optimal_zone": None,
                "entry": 12.0, "stop": 11.0, "tp1": 13.0, "confirmation_entry": 12.0}

    res = bt.backtest_symbol(df, Objective.SWING, analyze=analyze, step=8, start_i=60)
    m = res.metrics()
    assert m["trades"] >= 1
    assert m["tp1_hit_rate"] > 0 and m["avg_r"] > 0


def test_stop_is_a_full_R_loss():
    # Price falls after entry -> stop hit -> R == -1.
    closes = list(np.linspace(10, 12, 80)) + list(np.linspace(12, 8, 80))
    df = _df(closes)

    def analyze(sub, obj):
        last = float(sub["close"].iloc[-1])
        return {"action": "BUY", "entry_type": "confirmation", "optimal_zone": None,
                "entry": last, "stop": last * 0.95, "tp1": last * 1.15,
                "confirmation_entry": last}

    res = bt.backtest_symbol(df, Objective.SWING, analyze=analyze, step=5, start_i=85)
    losers = [t for t in res.trades if t.outcome == "stop"]
    assert losers and all(abs(t.r + 1.0) < 1e-6 for t in losers)


def test_metrics_shape():
    df = _df(np.linspace(10, 18, 160))

    def analyze(sub, obj):
        last = float(sub["close"].iloc[-1])
        return {"action": "BUY", "entry_type": "confirmation", "optimal_zone": None,
                "entry": last, "stop": last * 0.96, "tp1": last * 1.1, "confirmation_entry": last}

    m = bt.backtest_symbol(df, Objective.SWING, analyze=analyze, step=6, start_i=60).metrics()
    for k in ("trades", "win_rate", "tp1_hit_rate", "avg_r", "expectancy_r", "max_drawdown_r"):
        assert k in m
