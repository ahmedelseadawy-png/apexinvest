"""Tests for the Long-Term Investment Target Engine (additive-only feature).

Two layers:
  * Unit tests directly against `engines.long_term_plan.build()` on synthetic
    candles with KNOWN swing highs/lows, so target prices, return math and
    horizon buckets can be checked exactly.
  * Integration tests through `service.analyze_symbol()` proving the feature
    is purely additive: the existing plan/signals/regime/expected_move outputs
    are byte-for-byte identical whether or not the long-term plan succeeds.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apexinvest.domain import Objective
from apexinvest.engines import long_term_plan as ltp
from apexinvest.market import yahoo_egx
from apexinvest.service import analyze_symbol


def _ohlc(closes, volume=1_000_000.0):
    closes = np.asarray(closes, dtype=float)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    highs = np.maximum(opens, closes) * 1.003
    lows = np.minimum(opens, closes) * 0.997
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes,
                         "volume": np.full(len(closes), volume)})


def _peak(level_from, level_to, level_from2, n_up=10, n_down=10):
    """One clean rally-and-pullback leg: from -> to -> back toward from2."""
    return np.concatenate([
        np.linspace(level_from, level_to, n_up),
        np.linspace(level_to, level_from2, n_down),
    ])


def _structured_series():
    """Base chop around 9.5-10.5 (repeated touches -> a real support cluster),
    then two rallies that both peak at 12.0 (a twice-touched resistance), then
    one rally to 14.0 (a single-touch resistance), ending well below all of
    them at ~10.8 so every peak is a real, confirmable pivot high and there is
    genuine room (and real supports) below current price. ~260 bars total so
    the optional 4th/major-target and 200-EMA paths are also exercised."""
    base = np.tile(np.array([9.6, 10.4, 9.7, 10.3, 9.55, 10.45, 9.65, 10.35]), 12)  # 96 bars of chop
    leg1 = _peak(10.35, 12.0, 10.5, n_up=8, n_down=8)     # touch #1 of the 12.0 level
    leg2 = _peak(10.5, 12.0, 10.6, n_up=8, n_down=8)      # touch #2 of the 12.0 level
    leg3 = _peak(10.6, 14.0, 10.8, n_up=10, n_down=10)    # single touch of 14.0
    # Settle well below every peak, with tiny realistic noise (not a dead-flat
    # line) so downstream real-volatility features (expected_move) stay honest.
    pad = 10.8 + np.tile([0.02, -0.02, 0.015, -0.01], 15)
    return np.concatenate([base, leg1, leg2, leg3, pad])


def _df():
    return _ohlc(_structured_series())


def _short_df(n=40):
    """Too few bars for a reliable long-term read (below ltp._MIN_BARS)."""
    return _ohlc(np.linspace(10.0, 10.5, n))


# --------------------------------------------------------------------------- #
# 1. Unit tests directly on long_term_plan.build()
# --------------------------------------------------------------------------- #

def test_enabled_true_with_sufficient_history():
    df = _df()
    price = float(df["close"].iloc[-1])
    out = ltp.build(df, price)
    assert out["enabled"] is True


def test_disabled_with_insufficient_history_gives_honest_reason():
    """#7 insufficient data does not crash, and does not fabricate a plan."""
    df = _short_df()
    price = float(df["close"].iloc[-1])
    out = ltp.build(df, price)
    assert out["enabled"] is False
    assert out["reason"] == ltp.INSUFFICIENT_DATA_MSG


def test_build_never_raises_on_pathological_input():
    """#7 (robustness edge cases): empty/near-empty/garbage input degrades to
    enabled=False instead of raising."""
    for bad_price in (None, 0, -5):
        out = ltp.build(_df(), bad_price)
        assert out["enabled"] is False
    out = ltp.build(pd.DataFrame(), 10.0)
    assert out["enabled"] is False
    out = ltp.build(None, 10.0)
    assert out["enabled"] is False


def test_targets_are_derived_from_actual_pivot_structure():
    """#2 targets come from real swing highs in the data, not invented values."""
    df = _df()
    price = float(df["close"].iloc[-1])
    out = ltp.build(df, price)
    assert out["targets"], "expected at least one real target from the constructed peaks"
    target_prices = [t["target_price"] for t in out["targets"]]
    # The two known pivot highs (12.0 twice, 14.0 once) must be among the targets,
    # not some unrelated fabricated number.
    assert any(abs(p - 12.0) < 0.5 for p in target_prices)
    assert any(abs(p - 14.0) < 0.5 for p in target_prices)
    # The twice-touched 12.0 level must be reported as higher-confidence /
    # "major resistance" with its touch count, not treated the same as a
    # single-touch level.
    t12 = next(t for t in out["targets"] if abs(t["target_price"] - 12.0) < 0.5)
    assert "major resistance" in t12["basis"]
    assert t12["confidence"] in ("MEDIUM", "HIGH")


def test_return_percentages_are_mathematically_correct():
    """#3 expected_return_pct == (target/price - 1) * 100 for every target."""
    df = _df()
    price = float(df["close"].iloc[-1])
    out = ltp.build(df, price)
    assert out["targets"]
    for t in out["targets"]:
        expected = round((t["target_price"] / price - 1) * 100, 2)
        assert t["expected_return_pct"] == pytest.approx(expected, abs=0.05)
        assert t["expected_return_pct"] > 0     # only upside long-term targets


def test_target_horizons_are_ranges_not_fake_precision():
    """#4 horizons are (min_months, max_months) integer ranges, never a single
    fake-precise number of days."""
    df = _df()
    price = float(df["close"].iloc[-1])
    out = ltp.build(df, price)
    assert out["targets"]
    for t in out["targets"]:
        lo, hi = t["estimated_horizon_min_months"], t["estimated_horizon_max_months"]
        assert isinstance(lo, int) and isinstance(hi, int)
        assert 0 < lo < hi
    horizon = out["horizon"]
    assert isinstance(horizon["min_months"], int) and isinstance(horizon["max_months"], int)
    assert horizon["min_months"] < horizon["max_months"]
    assert "–" in horizon["label"] or "+" in horizon["label"]   # "X–Y months" or "18+ months"


def test_accumulation_zones_present_with_sufficient_structure():
    """#5 a real, repeatedly-touched support base produces an accumulation zone."""
    df = _df()
    price = float(df["close"].iloc[-1])
    out = ltp.build(df, price)
    assert out["accumulation_zones"], "expected at least one accumulation zone from the chop base"
    for z in out["accumulation_zones"]:
        assert z["zone_low"] <= z["zone_high"]
        assert z["zone_high"] < price       # a zone to accumulate IN must be below current price
        assert z["basis"]
        assert z["confidence"] in ("LOW", "MEDIUM", "HIGH")


def test_invalidation_generated_when_structural_support_exists():
    """#6 invalidation is a real level below the accumulation zone(s), not the
    same thing as the short-term stop."""
    df = _df()
    price = float(df["close"].iloc[-1])
    out = ltp.build(df, price)
    inv = out["invalidation"]
    assert inv is not None
    assert inv["price"] < price
    if out["accumulation_zones"]:
        assert inv["price"] <= min(z["zone_low"] for z in out["accumulation_zones"]) + 1e-6
    assert inv["basis"]
    assert inv["confidence"] in ("LOW", "MEDIUM", "HIGH")


def test_no_unsupported_targets_when_no_structure_above_price():
    """Spec: 'If there is insufficient structure for a target, omit it rather
    than inventing one.' A pure uptrend with NO pullback/no prior high above
    the current (all-time-high) price must not fabricate resistance targets."""
    breakout_high = _ohlc(np.linspace(10.0, 20.0, 220))   # monotonic new-high grind
    price = float(breakout_high["close"].iloc[-1])
    out = ltp.build(breakout_high, price)
    assert out["enabled"] is True
    for t in out["targets"]:
        assert t["basis"].startswith("measured move")   # only a labelled projection, never a bare pivot claim


# --------------------------------------------------------------------------- #
# Integration: additive-only guarantee through service.analyze_symbol()
# --------------------------------------------------------------------------- #

def _fetcher(df, symbol="TEST"):
    def fetch(_sym):
        meta = {"symbol": symbol, "currency": "EGP", "timeframe": "1d",
                "bars": len(df), "last_close": float(df["close"].iloc[-1]),
                "source": "test", "provides": list(yahoo_egx.PROVIDES)}
        return df, meta
    return fetch


def test_long_term_objective_creates_long_term_plan():
    """#1"""
    df = _df()
    out = analyze_symbol("TEST", Objective.LONG_TERM, fetcher=_fetcher(df))
    assert "long_term_plan" in out
    assert out["long_term_plan"]["enabled"] is True
    assert out["long_term_plan"]["entry_status"] == out["plan"]["action"]
    assert set(out["long_term_plan"]["horizon"].keys()) == {"min_months", "max_months", "label", "confidence"}


def test_insufficient_data_does_not_crash_analysis():
    """#7 — end to end: a symbol with too little history for a long-term read
    still returns a complete, valid analysis; only long_term_plan degrades."""
    df = _short_df()
    out = analyze_symbol("TEST", Objective.LONG_TERM, fetcher=_fetcher(df))
    assert out["long_term_plan"]["enabled"] is False
    assert out["long_term_plan"]["reason"] == ltp.INSUFFICIENT_DATA_MSG
    assert "plan" in out and "action" in out["plan"]      # rest of the analysis is intact


def test_existing_plan_and_signals_unchanged_by_long_term_plan_outcome(monkeypatch):
    """#8 + #9: force long_term_plan to fail/degrade vs. succeed on the exact
    same candles, and prove the existing plan (BUY/WAIT/AVOID + all its
    fields) and the 9 strategies' signals are byte-for-byte identical either
    way -- this feature cannot influence them."""
    df = _df()

    out_normal = analyze_symbol("TEST", Objective.SWING, fetcher=_fetcher(df))

    monkeypatch.setattr(ltp, "build",
                        lambda *a, **k: {"enabled": False, "reason": "forced failure for test"})
    out_forced_disabled = analyze_symbol("TEST", Objective.SWING, fetcher=_fetcher(df))

    assert out_normal["plan"] == out_forced_disabled["plan"]
    assert out_normal["signals"] == out_forced_disabled["signals"]
    assert out_normal["regime"] == out_forced_disabled["regime"]
    # And the only thing that actually changed is long_term_plan itself.
    assert out_normal["long_term_plan"] != out_forced_disabled["long_term_plan"]
    assert out_forced_disabled["long_term_plan"]["enabled"] is False


def test_existing_short_term_objectives_remain_unchanged(monkeypatch):
    """#10 — SWING/INCOME/ANALYZE objectives are untouched by this feature:
    long_term_plan is attached but never alters their plan/signals."""
    df = _df()
    for objective in (Objective.SWING, Objective.INCOME, Objective.ANALYZE):
        out = analyze_symbol("TEST", objective, fetcher=_fetcher(df))
        assert out["objective"] == objective.value
        assert "long_term_plan" in out               # additive field present regardless
        assert "action" in out["plan"]                # existing plan shape untouched
        assert out["plan"]["action"] in ("BUY", "WAIT", "AVOID")


def test_expected_move_still_available_alongside_long_term_plan():
    """#11 — Next Day / Next Week expected move is unaffected and still present."""
    df = _df()
    out = analyze_symbol("TEST", Objective.LONG_TERM, fetcher=_fetcher(df))
    em = out["expected_move"]
    assert em is not None
    assert "day" in em and "week" in em
    assert "long_term_plan" in out    # both coexist


def test_long_term_plan_is_backward_compatible_additive_field():
    """#12 — every pre-existing top-level key from analyze_symbol's response
    is still present and long_term_plan is purely an ADDITION, not a
    replacement of any of them."""
    df = _df()
    out = analyze_symbol("TEST", Objective.SWING, fetcher=_fetcher(df))
    # "fundamentals" is intentionally omitted here: it's only attached when no
    # test fetcher is injected (see service.py's envelope()) -- unrelated to
    # this feature, and unaffected by it either way.
    pre_existing_keys = {
        "objective", "mode", "strategies", "regime", "signals", "plan",
        "disclaimer", "data_source", "candles", "expected_move", "auto",
    }
    assert pre_existing_keys <= set(out.keys())
    assert "long_term_plan" in out
    assert isinstance(out["long_term_plan"], dict)
    assert "enabled" in out["long_term_plan"]
