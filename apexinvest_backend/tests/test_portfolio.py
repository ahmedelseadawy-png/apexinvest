"""Tests for portfolio / wallet position management.

The engine must give the RIGHT action for the situation: EXIT when a position
has lost its structure, TRIM a stretched winner showing supply, HOLD a healthy
one, and always attach a protective stop and honest P/L.
"""
from apexinvest.domain import Objective
from apexinvest.engines import portfolio as pf


def _plan(action="WAIT", price=10.0, weekly="up", dist=False, chase="ok",
          supports=(9.0,), vah=10.5, tp1=None):
    return {"action": action, "current_price": price, "chase": chase, "tp1": tp1,
            "entry_levels": {"weekly_trend": weekly, "distribution_warning": dist,
                             "supports": list(supports), "vah": vah, "val": 9.2,
                             "range_low": 9.0, "atr": 0.2, "phase": "markup",
                             "resistances": [11.0]}}


def test_pl_math_is_correct():
    hold = {"symbol": "X", "qty": 100, "avg_cost": 8.0}
    row = pf.analyze_position(hold, _plan(price=10.0))
    assert row["market_value"] == 1000.0
    assert row["cost_basis"] == 800.0
    assert row["unrealized_pl"] == 200.0
    assert round(row["unrealized_pl_pct"], 1) == 25.0


def test_exit_when_below_support_or_downtrend():
    # price under the protective stop -> EXIT
    row = pf.analyze_position({"symbol": "X", "qty": 10, "avg_cost": 12},
                              _plan(price=8.4, supports=(9.0,), weekly="down"))
    assert row["action"] == "EXIT"


def test_trim_a_stretched_winner_with_distribution():
    row = pf.analyze_position({"symbol": "X", "qty": 10, "avg_cost": 8},
                              _plan(price=11.0, dist=True, chase="do_not_chase"))
    assert row["action"] == "TRIM"


def test_hold_healthy_position_has_stop():
    row = pf.analyze_position({"symbol": "X", "qty": 10, "avg_cost": 9.5},
                              _plan(action="WAIT", price=10.0, weekly="up"))
    assert row["action"] in ("HOLD", "ADD")
    assert row["suggested_stop"] is not None and row["suggested_stop"] < 10.0


def test_add_when_engine_says_buy_and_not_chasing():
    row = pf.analyze_position({"symbol": "X", "qty": 10, "avg_cost": 9.0},
                              _plan(action="BUY", price=9.6, chase="ok", tp1=11.0))
    assert row["action"] == "ADD"


def test_portfolio_rollup_and_weights():
    holds = [{"symbol": "AAA", "qty": 100, "avg_cost": 8}, {"symbol": "BBB", "qty": 50, "avg_cost": 20}]
    plans = {"AAA": _plan(price=10.0, weekly="up"), "BBB": _plan(price=18.0, weekly="down", supports=(21.0,))}

    def analyze(sym, obj):
        return {"plan": plans[sym]}

    out = pf.analyze_portfolio(holds, analyze=analyze)
    assert out["summary"]["positions"] == 2
    assert out["summary"]["winners"] == 1 and out["summary"]["losers"] == 1
    w = sum(p["weight_pct"] for p in out["positions"])
    assert 99.0 <= w <= 101.0
    # BBB is under water and downtrending -> should be EXIT and sorted first
    assert out["positions"][0]["action"] == "EXIT"
