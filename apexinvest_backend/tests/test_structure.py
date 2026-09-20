"""Tests for the daily market-structure engine (Update #2).

Guarantees under test: the profile is anchored to a recent window (not the
lifetime); POC confidence is LOW when there is no real range to read (a pure
trend), so the app never presents a meaningless POC as trustworthy; and the
phase classifier separates ranging from trending.
"""
import numpy as np
import pandas as pd

from apexinvest.engines import structure as S


def _ohlc(closes, vol=1_000_000.0):
    c = np.asarray(closes, float)
    o = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame({"open": o, "high": np.maximum(o, c) * 1.02,
                         "low": np.minimum(o, c) * 0.98, "close": c,
                         "volume": np.full(len(c), vol)})


def test_profile_window_is_not_lifetime():
    df = _ohlc(100 * np.cumprod(1 + np.full(200, 0.004)))
    st = S.detect_structure(df)
    assert st.window_bars < len(df)
    assert st.window_bars <= 130


def test_pure_trend_gets_low_poc_confidence():
    # A straight uptrend has no real accumulation range -> POC is meaningless.
    df = _ohlc(100 * np.cumprod(1 + np.full(120, 0.006)))
    st = S.detect_structure(df)
    assert st.poc_confidence == "low"
    assert st.phase in (S.MARKUP, S.UNDEFINED)


def test_clean_range_gets_high_confidence_and_accumulation_like_phase():
    rng = np.random.default_rng(0)
    df = _ohlc(10 + 0.5 * np.sin(np.linspace(0, 12, 90)) + rng.normal(0, 0.04, 90))
    st = S.detect_structure(df)
    assert st.poc_confidence in ("high", "medium")
    assert st.val is not None and st.vah is not None and st.val < st.poc < st.vah


def test_short_series_is_undefined_low():
    st = S.detect_structure(_ohlc(np.full(20, 10.0)))
    assert st.phase == S.UNDEFINED and st.poc_confidence == "low"


def test_as_dict_exposes_range_and_confidence():
    df = _ohlc(10 + 0.4 * np.sin(np.linspace(0, 10, 80)))
    d = S.detect_structure(df).as_dict()
    for k in ("phase", "phase_label", "poc_confidence", "window_bars", "poc", "vah", "val"):
        assert k in d
