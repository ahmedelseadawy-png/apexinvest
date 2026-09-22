"""Tests for the Trade Scenarios layer (additive-only feature).

Covers required scenarios D (breakout), E (breakout+retest), F (failed
breakout), G (pullback), H (breakdown), A/L (existing output unchanged),
plus the state-machine and anti-fabrication rules.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apexinvest.domain import Objective
from apexinvest.engines import trade_scenarios as tsc
from apexinvest.market import yahoo_egx
from apexinvest.service import analyze_symbol


def _ohlc(closes, volume=1_000_000.0):
    closes = np.asarray(closes, dtype=float)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    highs = np.maximum(opens, closes) * 1.004
    lows = np.minimum(opens, closes) * 0.996
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes,
                         "volume": np.full(len(closes), volume)})


def _fake_plan(entry_levels=None, **overrides):
    base = {
        "action": "WAIT", "entry_type": None, "confirmation_entry": None,
        "stop": None, "chase": "ok", "entry_levels": entry_levels or {},
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# D. Resistance breakout scenario
# --------------------------------------------------------------------------- #

def _df_below_resistance(n=200, resistance=12.0, price=10.5):
    closes = np.linspace(9.0, price, n)
    return _ohlc(closes)


def test_breakout_scenario_present_with_real_resistance_watching_state():
    df = _df_below_resistance()
    price = float(df["close"].iloc[-1])
    plan = _fake_plan(entry_levels={"resistances": [12.0], "supports": [9.5], "atr": 0.2})
    out = tsc.build(df, price, plan, tc=None)
    assert out["available"] is True
    assert "breakout" in out
    b = out["breakout"]
    assert b["resistance"] == 12.0
    assert "12.0" in b["trigger"] or "12" in b["trigger"]
    assert b["state"] == "WATCHING"       # price hasn't reached resistance yet


def test_breakout_scenario_trigger_matches_actual_resistance_never_invented():
    df = _df_below_resistance(resistance=8.75, price=8.5)
    price = float(df["close"].iloc[-1])
    plan = _fake_plan(entry_levels={"resistances": [8.77], "supports": [], "atr": 0.05})
    out = tsc.build(df, price, plan, tc=None)
    assert out["breakout"]["resistance"] == 8.77


def test_breakout_state_confirmed_after_multiple_closes_above():
    n = 200
    closes = np.concatenate([np.linspace(9.0, 11.9, n - 5), np.full(5, 12.5)])
    df = _ohlc(closes)
    price = float(df["close"].iloc[-1])
    plan = _fake_plan(entry_levels={"resistances": [12.0], "supports": [10.0], "atr": 0.2})
    out = tsc.build(df, price, plan, tc=None)
    assert out["breakout"]["state"] == "CONFIRMED"


# --------------------------------------------------------------------------- #
# E. Breakout + retest scenario
# --------------------------------------------------------------------------- #

def test_breakout_retest_zone_derived_from_resistance_and_atr():
    n = 200
    # Break out, then pull back into a plausible retest band.
    closes = np.concatenate([np.linspace(9.0, 12.5, n - 10), np.linspace(12.5, 12.1, 10)])
    df = _ohlc(closes)
    price = float(df["close"].iloc[-1])
    plan = _fake_plan(entry_levels={"resistances": [12.0], "supports": [10.0], "atr": 0.2,
                                     "reclaimed": True})
    out = tsc.build(df, price, plan, tc=None)
    assert "breakout_retest" in out
    zlo, zhi = out["breakout_retest"]["retest_zone"]
    assert zlo < 12.0 < zhi   # zone straddles the old resistance
    assert out["breakout_retest"]["status"] in ("Testing", "Waiting for confirmation", "Confirmed", "Failed")


def test_retest_not_shown_without_any_breakout_evidence():
    df = _df_below_resistance()
    price = float(df["close"].iloc[-1])
    plan = _fake_plan(entry_levels={"resistances": [12.0], "supports": [9.5], "atr": 0.2,
                                     "reclaimed": False})
    out = tsc.build(df, price, plan, tc=None)
    assert "breakout_retest" not in out   # nothing to retest yet -- must be omitted, not fabricated


# --------------------------------------------------------------------------- #
# F. Failed breakout
# --------------------------------------------------------------------------- #

def test_failed_breakout_detected_when_price_closes_back_below_level():
    n = 200
    closes = np.concatenate([np.linspace(9.0, 9.2, n - 15), np.full(5, 9.5), np.linspace(9.3, 8.9, 10)])
    df = _ohlc(closes)
    price = float(df["close"].iloc[-1])
    plan = _fake_plan(entry_levels={"resistances": [9.3], "supports": [8.5], "atr": 0.1})
    out = tsc.build(df, price, plan, tc=None)
    assert "failed_breakout" in out
    assert out["failed_breakout"]["status"] == "Invalidated"
    assert out["failed_breakout"]["action"] == "No new entry / wait for a new setup."
    assert out["failed_breakout"]["state"] == "FAILED"


def test_no_failed_breakout_when_price_never_broke_above():
    df = _df_below_resistance()
    price = float(df["close"].iloc[-1])
    plan = _fake_plan(entry_levels={"resistances": [12.0], "supports": [9.5], "atr": 0.2})
    out = tsc.build(df, price, plan, tc=None)
    assert "failed_breakout" not in out


# --------------------------------------------------------------------------- #
# G. Pullback scenario
# --------------------------------------------------------------------------- #

def test_pullback_scenario_when_extended_and_do_not_chase():
    df = _df_below_resistance(n=200, price=11.0)
    price = float(df["close"].iloc[-1])
    plan = _fake_plan(chase="do_not_chase",
                       entry_levels={"resistances": [], "supports": [10.0, 9.5], "atr": 0.2,
                                     "val": 9.6, "poc": 9.8})
    out = tsc.build(df, price, plan, tc=None)
    assert "pullback" in out
    zlo, zhi = out["pullback"]["zone"]
    assert zlo == 9.5   # nearest real support, not invented
    assert "previous support" in out["pullback"]["basis"]


def test_no_pullback_when_not_extended():
    df = _df_below_resistance(n=200, price=10.5)
    price = float(df["close"].iloc[-1])
    plan = _fake_plan(chase="ok", entry_levels={"resistances": [12.0], "supports": [10.0], "atr": 0.2})
    out = tsc.build(df, price, plan, tc=None)
    assert "pullback" not in out


def test_no_pullback_when_no_support_exists():
    df = _df_below_resistance(n=200, price=11.0)
    price = float(df["close"].iloc[-1])
    plan = _fake_plan(chase="do_not_chase", entry_levels={"resistances": [], "supports": [], "atr": 0.2})
    out = tsc.build(df, price, plan, tc=None)
    assert "pullback" not in out   # no real support -> omit rather than invent one


# --------------------------------------------------------------------------- #
# H. Breakdown scenario
# --------------------------------------------------------------------------- #

def test_breakdown_scenario_present_with_real_support():
    df = _df_below_resistance(n=200, price=10.5)
    price = float(df["close"].iloc[-1])
    plan = _fake_plan(entry_levels={"resistances": [12.0], "supports": [9.5], "atr": 0.2})
    out = tsc.build(df, price, plan, tc=None)
    assert "breakdown" in out
    assert out["breakdown"]["support"] == 9.5
    assert out["breakdown"]["state"] == "WATCHING"


def test_breakdown_confirmed_after_close_below_support():
    n = 200
    closes = np.concatenate([np.linspace(11.0, 9.6, n - 3), np.full(3, 9.0)])
    df = _ohlc(closes)
    price = float(df["close"].iloc[-1])
    plan = _fake_plan(entry_levels={"resistances": [12.0], "supports": [9.5], "atr": 0.2})
    out = tsc.build(df, price, plan, tc=None)
    assert out["breakdown"]["state"] in ("TRIGGERED", "CONFIRMED")
    assert out["breakdown"]["result"] == "Setup invalidated / avoid new entry"


# --------------------------------------------------------------------------- #
# I. Insufficient data
# --------------------------------------------------------------------------- #

def test_insufficient_data_returns_unavailable_not_fabricated():
    df = _ohlc(np.linspace(10, 10.5, 10))
    out = tsc.build(df, 10.5, None, tc=None)
    assert out["available"] is False
    assert "reason" in out


def test_build_never_raises_on_pathological_input():
    for bad_price in (None, 0, -1):
        out = tsc.build(_df_below_resistance(), bad_price, None, tc=None)
        assert out["available"] is False
    out = tsc.build(pd.DataFrame(), 10.0, None, tc=None)
    assert out["available"] is False
    out = tsc.build(None, 10.0, None, tc=None)
    assert out["available"] is False


def test_no_scenarios_forced_when_no_structure_at_all():
    """A flat, structureless series with no real supports/resistances above
    the noise floor must not force scenario objects into existence."""
    df = _ohlc(np.full(200, 10.0) + np.tile([0.001, -0.001], 100))
    price = float(df["close"].iloc[-1])
    out = tsc.build(df, price, _fake_plan(entry_levels={"resistances": [], "supports": [], "atr": 0.01}), tc=None)
    assert out["available"] is True
    assert "breakout" not in out
    assert "breakdown" not in out
    assert "pullback" not in out
    assert "failed_breakout" not in out


# --------------------------------------------------------------------------- #
# A / L. Existing analysis output unchanged (regression) + backward compat
# --------------------------------------------------------------------------- #

def _fetcher(df, symbol="TEST"):
    def fetch(_sym):
        meta = {"symbol": symbol, "currency": "EGP", "timeframe": "1d",
                "bars": len(df), "last_close": float(df["close"].iloc[-1]),
                "source": "test", "provides": list(yahoo_egx.PROVIDES)}
        return df, meta
    return fetch


def test_trade_scenarios_attached_and_existing_plan_signals_unchanged(monkeypatch):
    df = _df_below_resistance(n=220, price=10.5)
    out_normal = analyze_symbol("TEST", Objective.SWING, fetcher=_fetcher(df))
    assert "trade_scenarios" in out_normal

    monkeypatch.setattr(tsc, "build", lambda *a, **k: {"available": False, "reason": "forced"})
    out_forced = analyze_symbol("TEST", Objective.SWING, fetcher=_fetcher(df))

    assert out_normal["plan"] == out_forced["plan"]
    assert out_normal["signals"] == out_forced["signals"]
    assert out_normal["regime"] == out_forced["regime"]
    assert out_normal["long_term_plan"] == out_forced["long_term_plan"]


def test_backward_compatible_existing_top_level_keys_present():
    df = _df_below_resistance(n=220, price=10.5)
    out = analyze_symbol("TEST", Objective.SWING, fetcher=_fetcher(df))
    pre_existing = {"objective", "mode", "strategies", "regime", "signals", "plan",
                    "disclaimer", "data_source", "candles", "expected_move", "auto",
                    "long_term_plan"}
    assert pre_existing <= set(out.keys())
    assert "trend_confirmation" in out
    assert "trade_scenarios" in out
    assert "wait_context" in out
