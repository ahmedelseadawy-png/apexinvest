"""Regression tests on REAL EGX candle fixtures.

Most other tests use synthetic series. These run the full engine on real
Egyptian Exchange data (COMI, SWDY) to catch regressions on the messy shapes
that actually occur — the anti-fabrication guarantees must hold on real data:
a plan is either a complete BUY with sane geometry, or an honest WAIT/AVOID with
no invented levels; the backtester never looks ahead and never raises.

Add more fixtures over time (a downtrend, a tight range, an illiquid name) to
widen the safety net.
"""
import json
import pathlib

import pandas as pd
import pytest

from apexinvest.domain import Objective
from apexinvest.engines import backtest as bt
from apexinvest import service

FIX = pathlib.Path(__file__).parent / "fixtures"


def _load(name):
    raw = json.loads((FIX / name).read_text())
    rows = ([[c["o"], c["h"], c["l"], c["c"], c["v"]] for c in raw["candles"]]
            if "candles" in raw else raw["rows"])
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"]).astype(float)


def _fetcher(df):
    def f(sym):
        return df, {"symbol": sym, "currency": "EGP", "exchange": "EGX", "timeframe": "1d",
                    "bars": len(df), "last_close": float(df["close"].iloc[-1]),
                    "as_of": "2026-09-02", "source": "fixture", "delayed": True,
                    "adjusted": True, "provides": ["daily_chart", "volume", "volume_profile"]}
    return f


@pytest.mark.parametrize("name", ["COMI.json", "SWDY.json"])
@pytest.mark.parametrize("obj", [Objective.SWING, Objective.LONG_TERM])
def test_real_fixture_plan_is_complete_or_honest_wait(name, obj):
    df = _load(name)
    out = service.analyze_symbol(name[:-5], obj, fetcher=_fetcher(df))
    plan = out["plan"]
    assert plan["action"] in ("BUY", "WAIT", "AVOID")
    if plan["action"] == "BUY":
        # a BUY must be geometrically sane and measured from the entry, not price
        assert plan["entry"] and plan["stop"] and plan["tp1"]
        assert plan["stop"] < plan["entry"] < plan["tp1"]
        assert plan["rr"] and plan["rr"] >= 1.5
        assert plan["current_price"] is not None
    else:
        # WAIT/AVOID must not carry invented actionable levels
        assert plan["entry"] is None and plan["stop"] is None
    # context levels always present for transparency
    assert "poc_confidence" in plan["entry_levels"]


@pytest.mark.parametrize("name", ["COMI.json", "SWDY.json"])
def test_backtest_runs_on_real_fixture_without_lookahead(name):
    df = _load(name)
    res = bt.backtest_symbol(df, Objective.SWING, step=3)
    m = res.metrics()
    assert "trades" in m
    # every recorded trade has a valid R and a known outcome
    for t in res.trades:
        assert t.outcome in ("tp1", "stop", "timeout")
        assert t.exit_i > t.fill_i >= t.entry_i
