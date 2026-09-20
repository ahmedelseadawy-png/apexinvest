"""Deterministic technical indicators computed from OHLCV candles.

Everything here is a pure function of the input candles. No indicator invents
data: if there aren't enough candles to compute a value it returns NaN rather
than a guess, and callers must handle that.

A "candles" DataFrame has columns: open, high, low, close, volume (float),
indexed 0..n-1 in chronological order (oldest first).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_COLS = ("open", "high", "low", "close", "volume")


def validate_candles(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"candles missing columns: {missing}")
    if len(df) == 0:
        raise ValueError("candles is empty")


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder smoothing == EMA with alpha = 1/period
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - (100 / (1 + rs))
    # When avg_loss == 0 and avg_gain > 0 -> RSI 100; when both 0 -> 50 (flat)
    out = out.where(avg_loss != 0, other=np.where(avg_gain > 0, 100.0, 50.0))
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD: (macd_line, signal_line, histogram). Standard 12/26/9."""
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder)."""
    tr = true_range(df)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average Directional Index — trend strength, 0..100."""
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = true_range(df)
    atr_ = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def swing_levels(df: pd.DataFrame, lookback: int = 20) -> tuple[float, float]:
    """Recent support (min low) and resistance (max high) over lookback bars."""
    window = df.tail(lookback)
    return float(window["low"].min()), float(window["high"].max())


def obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume — accumulation/distribution proxy."""
    direction = np.sign(df["close"].diff().fillna(0.0))
    return (direction * df["volume"]).cumsum()


def volume_profile_poc(df: pd.DataFrame, bins: int = 24) -> dict:
    """Approximate a Volume Profile from candles and return the Point of Control.

    Honest approximation: each candle's volume is assigned to the bin of its
    typical price ((h+l+c)/3). Real volume profiles use intrabar data; this is
    a documented approximation, and provenance reflects that.
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    lo, hi = float(df["low"].min()), float(df["high"].max())
    if hi <= lo:
        return {"poc": float(df["close"].iloc[-1]), "value_area": (lo, hi), "approx": True}
    edges = np.linspace(lo, hi, bins + 1)
    idx = np.clip(np.digitize(typical, edges) - 1, 0, bins - 1)
    vol_by_bin = np.zeros(bins)
    for b, v in zip(idx, df["volume"].to_numpy()):
        vol_by_bin[b] += v
    poc_bin = int(np.argmax(vol_by_bin))
    poc_price = float((edges[poc_bin] + edges[poc_bin + 1]) / 2.0)
    # value area ~ 70% of volume around POC
    order = np.argsort(vol_by_bin)[::-1]
    total = vol_by_bin.sum()
    acc, chosen = 0.0, []
    for b in order:
        acc += vol_by_bin[b]
        chosen.append(b)
        if acc >= 0.70 * total:
            break
    va_lo = float(edges[min(chosen)])
    va_hi = float(edges[max(chosen) + 1])
    return {"poc": poc_price, "value_area": (va_lo, va_hi), "approx": True}


def volume_profile(df: pd.DataFrame, bins: int = 30, value_area_pct: float = 0.70) -> dict:
    """Fuller Volume Profile over the candles given: POC, VAH, VAL, HVN, LVN.

    Contextual by design — pass a *slice* of the candles (e.g. the recent
    accumulation window) rather than the lifetime, so the profile describes the
    current setup, not the whole history. Each candle's volume is spread across
    the three price bins h/l/c touch (a documented approximation; real profiles
    use intrabar prints, which this free daily feed does not provide).

    Returns: poc, vah, val, value_area (val,vah), hvn (list of high-volume node
    prices), lvn (list of low-volume node prices), lo, hi, bins — or approx flags.
    """
    if len(df) == 0:
        return {"poc": None, "vah": None, "val": None, "value_area": None,
                "hvn": [], "lvn": [], "lo": None, "hi": None, "approx": True}
    lo, hi = float(df["low"].min()), float(df["high"].max())
    close_last = float(df["close"].iloc[-1])
    if hi <= lo:
        return {"poc": close_last, "vah": hi, "val": lo, "value_area": (lo, hi),
                "hvn": [close_last], "lvn": [], "lo": lo, "hi": hi, "approx": True}

    edges = np.linspace(lo, hi, bins + 1)
    centers = (edges[:-1] + edges[1:]) / 2.0
    vol_by_bin = np.zeros(bins)
    # Spread each bar's volume across the h/l/c bins it touches (lighter-weight
    # than true intrabar, heavier signal than a single typical-price bin).
    for hgh, low, cls, vol in zip(df["high"], df["low"], df["close"], df["volume"]):
        touched = set()
        for p in (hgh, low, cls, (hgh + low + cls) / 3.0):
            b = int(np.clip(np.digitize(p, edges) - 1, 0, bins - 1))
            touched.add(b)
        share = float(vol) / max(len(touched), 1)
        for b in touched:
            vol_by_bin[b] += share

    total = vol_by_bin.sum()
    poc_bin = int(np.argmax(vol_by_bin))
    poc_price = float(centers[poc_bin])

    # Value area: grow out from the POC bin, always adding the richer neighbour,
    # until ~value_area_pct of volume is enclosed (standard VP construction).
    included = {poc_bin}
    acc = vol_by_bin[poc_bin]
    lo_b = hi_b = poc_bin
    while acc < value_area_pct * total and (lo_b > 0 or hi_b < bins - 1):
        below = vol_by_bin[lo_b - 1] if lo_b > 0 else -1.0
        above = vol_by_bin[hi_b + 1] if hi_b < bins - 1 else -1.0
        if above >= below:
            hi_b += 1; included.add(hi_b); acc += max(above, 0.0)
        else:
            lo_b -= 1; included.add(lo_b); acc += max(below, 0.0)
    val = float(edges[min(included)])
    vah = float(edges[max(included) + 1])

    # HVN / LVN: bins whose volume stands out above / below the mean (skip empties).
    nonzero = vol_by_bin[vol_by_bin > 0]
    mean_v = float(nonzero.mean()) if len(nonzero) else 0.0
    hvn = sorted(float(centers[b]) for b in range(bins) if vol_by_bin[b] >= 1.6 * mean_v)
    lvn = sorted(float(centers[b]) for b in range(bins)
                 if 0 < vol_by_bin[b] <= 0.4 * mean_v)
    return {"poc": poc_price, "vah": vah, "val": val, "value_area": (val, vah),
            "hvn": hvn, "lvn": lvn, "lo": lo, "hi": hi, "bins": bins, "approx": True}


def pivots(df: pd.DataFrame, left: int = 3, right: int = 3) -> tuple[list[dict], list[dict]]:
    """Swing highs and swing lows by fractal rule (a bar higher/lower than the
    `left` bars before and `right` bars after it). Returns (highs, lows) as lists
    of {"i": index, "price": value} oldest-first. The most recent `right` bars
    can't be confirmed as pivots yet and are excluded — honest, no peeking ahead."""
    highs: list[dict] = []
    lows: list[dict] = []
    h = df["high"].to_numpy()
    l = df["low"].to_numpy()
    n = len(df)
    for i in range(left, n - right):
        seg_h = h[i - left:i + right + 1]
        seg_l = l[i - left:i + right + 1]
        if h[i] == seg_h.max() and (seg_h.argmax() == left):
            highs.append({"i": i, "price": float(h[i])})
        if l[i] == seg_l.min() and (seg_l.argmin() == left):
            lows.append({"i": i, "price": float(l[i])})
    return highs, lows


def cluster_levels(prices: list[float], tol: float) -> list[dict]:
    """Group nearby price levels into consolidated zones. `tol` is the absolute
    price distance within which two levels are considered the same zone. Returns
    zones {"price": weighted_center, "count": n, "lo": min, "hi": max} sorted by
    price. More touches = a stronger level (higher count)."""
    if not prices:
        return []
    pts = sorted(prices)
    zones: list[list[float]] = [[pts[0]]]
    for p in pts[1:]:
        if p - zones[-1][-1] <= tol:
            zones[-1].append(p)
        else:
            zones.append([p])
    out = []
    for z in zones:
        out.append({"price": float(sum(z) / len(z)), "count": len(z),
                    "lo": float(min(z)), "hi": float(max(z))})
    return out


def dollar_volume(df: pd.DataFrame, lookback: int = 20) -> float:
    window = df.tail(lookback)
    return float((window["close"] * window["volume"]).mean())


def last(series: pd.Series) -> float | None:
    """Last non-NaN value, or None if the series never computed."""
    s = series.dropna()
    return float(s.iloc[-1]) if len(s) else None
