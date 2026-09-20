import numpy as np
import pandas as pd
import pytest


def _candles(closes, volume=1_000_000.0):
    closes = np.asarray(closes, dtype=float)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    highs = np.maximum(opens, closes) * 1.008
    lows = np.minimum(opens, closes) * 0.992
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": np.full(len(closes), volume),
    })


@pytest.fixture
def uptrend():
    # Steady rise with mild noise -> strong ADX, EMA fast > slow.
    rng = np.random.default_rng(1)
    base = 100 * np.cumprod(1 + np.full(140, 0.006))
    noise = rng.normal(0, 0.25, 140)
    return _candles(base + noise)


@pytest.fixture
def downtrend():
    rng = np.random.default_rng(2)
    base = 200 * np.cumprod(1 + np.full(140, -0.006))
    noise = rng.normal(0, 0.25, 140)
    return _candles(base + noise)


@pytest.fixture
def sideways():
    # Choppy, mean-reverting noise around a flat level: no sustained directional
    # runs -> ADX stays low -> classifier reads SIDEWAYS.
    rng = np.random.default_rng(3)
    base = 100 + rng.normal(0, 0.5, 140)
    return _candles(base)
