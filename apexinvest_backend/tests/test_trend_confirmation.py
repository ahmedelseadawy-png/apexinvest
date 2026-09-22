"""Tests for the Trend & Confirmation layer (additive-only feature).

Covers required scenarios B, C, I, J from the task spec, plus unit coverage
of the scoring methodology (no double counting, honest "Unavailable" when
data is thin, confirmation_score never used as a probability/return).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from apexinvest.domain import Objective
from apexinvest.engines import regime as regime_engine
from apexinvest.engines import trend_confirmation as tc
from apexinvest.market import yahoo_egx
from apexinvest.service import analyze_symbol


def _ohlc(closes, volume=1_000_000.0):
    closes = np.asarray(closes, dtype=float)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    highs = np.maximum(opens, closes) * 1.004
    lows = np.minimum(opens, closes) * 0.996
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes,
                         "volume": np.full(len(closes), volume)})


def _strong_uptrend(n=260):
    """Clean, steadily rising series -> price>EMA20>EMA50>EMA200, ADX high,
    RSI>55, MACD bullish -- every group should agree (confirmed)."""
    return _ohlc(100.0 * np.cumprod(1 + np.full(n, 0.006)))


def _uptrend_thin_volume():
    """Bullish price structure/EMA/momentum, but the last few bars' volume
    has dried up relative to the recent average -- Volume group should read
    'Not Confirming' while price/trend groups still confirm."""
    n = 260
    closes = 100.0 * np.cumprod(1 + np.full(n, 0.005))
    df = _ohlc(closes)
    vol = np.full(n, 1_000_000.0)
    vol[-3:] = 300_000.0   # sharp recent contraction vs the 20-bar average
    df["volume"] = vol
    return df


def _choppy_flat(n=200):
    rng = np.random.RandomState(7)
    walk = np.cumsum(rng.normal(0, 0.15, n))
    return _ohlc(100.0 + walk - walk.mean())


def _fetcher(df, symbol="TEST"):
    def fetch(_sym):
        meta = {"symbol": symbol, "currency": "EGP", "timeframe": "1d",
                "bars": len(df), "last_close": float(df["close"].iloc[-1]),
                "source": "test", "provides": list(yahoo_egx.PROVIDES)}
        return df, meta
    return fetch


# --------------------------------------------------------------------------- #
# B. Bullish trend with confirmed evidence
# --------------------------------------------------------------------------- #

def test_strong_uptrend_is_bullish_with_high_confirmation():
    df = _strong_uptrend()
    reg = regime_engine.detect_regime(df)
    out = tc.build(df, reg.as_dict(), {"entry_levels": {}})
    assert out["primary_trend"] == "Bullish"
    assert out["ema_alignment"] == "Bullish"
    assert out["confirmation_score"] is not None
    assert out["confirmation_score"] >= 60
    assert out["confirmation_strength"] in ("Moderate", "Strong", "Very Strong")
    assert any("Structure" in c or "EMA" in c for c in out["confirmed_factors"])


# --------------------------------------------------------------------------- #
# C. Bullish trend with missing volume confirmation
# --------------------------------------------------------------------------- #

def test_bullish_trend_with_fading_volume_flags_volume_as_missing():
    df = _uptrend_thin_volume()
    reg = regime_engine.detect_regime(df)
    out = tc.build(df, reg.as_dict(), {"entry_levels": {}})
    assert out["primary_trend"] == "Bullish"
    assert out["volume_status"] == "Not Confirming"
    assert any(m.startswith("Volume") for m in out["missing_factors"])


# --------------------------------------------------------------------------- #
# I. Insufficient data
# --------------------------------------------------------------------------- #

def test_insufficient_bars_returns_unavailable_not_fabricated():
    df = _ohlc(np.linspace(10, 11, 15))   # well under _MIN_BARS
    out = tc.build(df, None, {})
    assert out["primary_trend"] == "Unavailable"
    assert out["confirmation_score"] is None
    assert out["confirmed_factors"] == []
    assert out["missing_factors"] == []


def test_build_never_raises_on_pathological_input():
    for bad in (None, pd.DataFrame()):
        out = tc.build(bad, None, None)
        assert out["primary_trend"] == "Unavailable"


# --------------------------------------------------------------------------- #
# J. Market context unavailable (no EGX30/70 feed exists yet)
# --------------------------------------------------------------------------- #

def test_market_alignment_is_always_unavailable_and_excluded_from_scoring():
    """Market alignment must read 'Unavailable' (no fabricated EGX30/70 read)
    and must not silently zero out or inflate the score -- it's excluded."""
    df = _strong_uptrend()
    reg = regime_engine.detect_regime(df)
    out = tc.build(df, reg.as_dict(), {"entry_levels": {}})
    assert out["market_alignment"] == "Unavailable"
    # Score should still be computable from the other 5 groups.
    assert out["confirmation_score"] is not None


# --------------------------------------------------------------------------- #
# Methodology: no double counting, ambiguous data is neutral not extreme
# --------------------------------------------------------------------------- #

def test_choppy_market_is_neutral_or_mixed_with_moderate_or_lower_score():
    df = _choppy_flat()
    reg = regime_engine.detect_regime(df)
    out = tc.build(df, reg.as_dict(), {"entry_levels": {}})
    assert out["primary_trend"] in ("Neutral", "Mixed", "Unavailable")
    if out["confirmation_score"] is not None:
        assert out["confirmation_score"] <= 70   # never "Very Strong" on genuinely mixed data


def test_confirmation_score_is_bounded_0_100():
    for maker in (_strong_uptrend, _uptrend_thin_volume, _choppy_flat):
        df = maker()
        reg = regime_engine.detect_regime(df)
        out = tc.build(df, reg.as_dict(), {"entry_levels": {}})
        if out["confirmation_score"] is not None:
            assert 0 <= out["confirmation_score"] <= 100


def test_weights_sum_to_100_documented_methodology():
    """Regression guard on the methodology itself: the six evidence groups'
    weights must sum to exactly 100 (spec section 5's 'reasonable caps')."""
    assert sum(tc._WEIGHTS.values()) == 100


def test_momentum_group_is_single_weight_not_double_counted_with_macd_status():
    """macd_status is a separate DISPLAY field but must not add a second
    scoring group on top of 'momentum' -- both derive from the same signed
    lean and share one weight (see module docstring)."""
    assert "macd" not in tc._WEIGHTS
    assert tc._WEIGHTS["momentum"] == 20


# --------------------------------------------------------------------------- #
# Integration through service.analyze_symbol -- always additive
# --------------------------------------------------------------------------- #

def test_trend_confirmation_attached_and_never_alters_existing_plan(monkeypatch):
    df = _strong_uptrend()
    out_normal = analyze_symbol("TEST", Objective.SWING, fetcher=_fetcher(df))
    assert "trend_confirmation" in out_normal
    assert "wait_context" in out_normal

    monkeypatch.setattr(tc, "build", lambda *a, **k: {
        "primary_trend": "Unavailable", "confirmation_score": None,
        "confirmed_factors": [], "missing_factors": []})
    monkeypatch.setattr(tc, "compose_wait_context", lambda *a, **k: {
        "applicable": False, "why": None, "next_trigger": None})
    out_forced = analyze_symbol("TEST", Objective.SWING, fetcher=_fetcher(df))
    assert out_normal["plan"] == out_forced["plan"]
    assert out_normal["signals"] == out_forced["signals"]
    assert out_normal["regime"] == out_forced["regime"]
