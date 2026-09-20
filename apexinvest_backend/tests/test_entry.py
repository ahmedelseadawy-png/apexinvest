"""Tests for the entry optimizer (Update #1): optimal buy zone vs current price,
anti-chase, structural stop, TP1/TP2 from structure, and NO TRADE discipline.

The guarantee under test: the engine answers "WHERE is the best place to buy?"
— never "buy at the current price" — and stands aside (NO TRADE) when no
location offers acceptable, actionable risk/reward.
"""
import numpy as np
import pandas as pd

from apexinvest.engines import entry


def _ohlc(closes, highs=None, lows=None, volume=1_000_000.0):
    closes = np.asarray(closes, dtype=float)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    highs = np.maximum(opens, closes) * 1.01 if highs is None else np.asarray(highs, float)
    lows = np.minimum(opens, closes) * 0.99 if lows is None else np.asarray(lows, float)
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes,
                         "volume": np.full(len(closes), volume)})


def _uptrend_pullback():
    """Staircase uptrend that builds a support shelf, ending with a shallow dip
    so the current price sits just above a well-touched support zone."""
    seg, lvl = [], 10.0
    for _ in range(9):
        up = np.linspace(lvl, lvl + 1.2, 12); seg.append(up); lvl = up[-1]
        pb = np.linspace(lvl, lvl - 0.6, 6); seg.append(pb); lvl = pb[-1]
    base = np.concatenate(seg + [np.linspace(lvl, lvl - 0.3, 4)])
    return _ohlc(base)


def _extended():
    """A near-vertical run: price ends far above any real support."""
    base = np.concatenate([np.linspace(8, 10, 40), np.linspace(10, 18, 40)])
    return _ohlc(base)


def _downtrend():
    return _ohlc(np.linspace(20, 10, 80))


# --------------------------------------------------------------------------- #

def test_entry_is_not_the_current_price():
    """The core fix: for a retest setup the recommended entry sits BELOW the
    current price, not at it."""
    ep = entry.optimize_entry(_uptrend_pullback(), min_rr=1.5)
    assert not ep.no_trade
    assert ep.entry_ref is not None
    assert ep.entry_ref < ep.current_price          # entry != current price
    if ep.optimal_zone:
        assert ep.optimal_zone[0] <= ep.entry_ref <= ep.optimal_zone[1]


def test_structural_stop_below_entry():
    ep = entry.optimize_entry(_uptrend_pullback(), min_rr=1.5)
    assert ep.stop is not None and ep.stop < ep.entry_ref
    assert ep.stop_basis                             # names the structural level


def test_targets_and_rr_measured_from_entry_not_price():
    ep = entry.optimize_entry(_uptrend_pullback(), min_rr=1.5)
    assert ep.tp1 is not None and ep.tp2 is not None
    assert ep.tp2 >= ep.tp1 > ep.entry_ref
    # expected return is computed from the entry, not the (higher) current price
    expected = (ep.tp1 - ep.entry_ref) / ep.entry_ref * 100.0
    assert abs(ep.expected_return_pct - expected) < 0.5
    # R:R is (tp1-entry)/(entry-stop)
    rr = (ep.tp1 - ep.entry_ref) / (ep.entry_ref - ep.stop)
    assert abs(ep.rr - rr) < 0.05


def test_anti_chase_when_price_above_zone():
    """When price has run above the optimal zone, status is DO NOT CHASE."""
    ep = entry.optimize_entry(_uptrend_pullback(), min_rr=1.5, chase_atr=0.2)
    if ep.optimal_zone and ep.current_price > ep.optimal_zone[1]:
        assert ep.chase == "do_not_chase"
        assert any("chas" in n.lower() or "pullback" in n.lower() for n in ep.notes)


def test_no_trade_when_extended_far_above_support():
    ep = entry.optimize_entry(_extended(), min_rr=1.8)
    assert ep.no_trade
    assert "extended" in ep.reason.lower() or "pullback" in ep.reason.lower()
    # never emits actionable levels on a NO TRADE
    assert ep.entry_ref is None and ep.stop is None and ep.tp1 is None


def test_no_trade_in_downtrend_no_knife_catching():
    ep = entry.optimize_entry(_downtrend(), min_rr=1.8)
    assert ep.no_trade
    assert ep.entry_ref is None


def test_wide_structural_stop_is_rejected():
    """A stop 30%+ from entry is not a swing plan -> the candidate is dropped."""
    # SWDY-like: long low base then a huge rally, nearest 'support' is the base.
    base = np.concatenate([np.full(50, 20.0) + np.random.default_rng(0).normal(0, 0.2, 50),
                           np.linspace(20, 33, 30)])
    ep = entry.optimize_entry(_ohlc(base), min_rr=1.8)
    # Either NO TRADE, or if a plan exists its stop is within a sane distance.
    if not ep.no_trade:
        assert (ep.entry_ref - ep.stop) / ep.entry_ref <= 0.15


def test_no_trade_emits_context_levels_for_transparency():
    ep = entry.optimize_entry(_extended(), min_rr=1.8)
    assert ep.no_trade
    assert "poc" in ep.levels and "profile_note" in ep.levels


def test_profile_window_is_contextual_not_lifetime():
    """The volume profile describes a recent window, not the whole history."""
    df = _uptrend_pullback()
    ep = entry.optimize_entry(df, min_rr=1.5)
    assert ep.levels["profile_bars"] < len(df)      # a slice, not the lifetime
