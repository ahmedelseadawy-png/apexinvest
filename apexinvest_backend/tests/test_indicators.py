import numpy as np
import pandas as pd
import pytest

from apexinvest.engines import indicators as ind


def test_sma_known_values():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    out = ind.sma(s, 3).tolist()
    assert np.isnan(out[0]) and np.isnan(out[1])
    assert out[2] == pytest.approx(2.0)
    assert out[3] == pytest.approx(3.0)
    assert out[4] == pytest.approx(4.0)


def test_ema_last_reasonable():
    s = pd.Series(range(1, 51), dtype=float)
    assert ind.last(ind.ema(s, 10)) == pytest.approx(45.6, abs=1.5)


def test_rsi_all_up_is_100():
    s = pd.Series(range(1, 40), dtype=float)  # strictly increasing
    assert ind.last(ind.rsi(s)) == pytest.approx(100.0)


def test_rsi_bounded():
    rng = np.random.default_rng(0)
    s = pd.Series(100 + rng.normal(0, 1, 200).cumsum())
    vals = ind.rsi(s).dropna()
    assert (vals >= 0).all() and (vals <= 100).all()


def test_atr_positive(uptrend):
    a = ind.last(ind.atr(uptrend))
    assert a is not None and a > 0


def test_adx_strong_on_trend(uptrend, sideways):
    trend_adx = ind.last(ind.adx(uptrend))
    flat_adx = ind.last(ind.adx(sideways))
    assert trend_adx > 20
    assert flat_adx < trend_adx


def test_poc_targets_high_volume_price():
    # Concentrate volume at price ~50 and confirm POC lands near it.
    closes = [10, 20, 50, 50, 50, 50, 80, 90]
    df = pd.DataFrame({
        "open": closes, "high": [c * 1.01 for c in closes],
        "low": [c * 0.99 for c in closes], "close": closes,
        "volume": [1, 1, 100, 100, 100, 100, 1, 1],
    }).astype(float)
    vp = ind.volume_profile_poc(df, bins=10)
    assert abs(vp["poc"] - 50) < 12


def test_validate_candles_raises_on_missing():
    with pytest.raises(ValueError):
        ind.validate_candles(pd.DataFrame({"open": [1.0]}))


def test_last_returns_none_when_all_nan():
    assert ind.last(pd.Series([np.nan, np.nan])) is None
