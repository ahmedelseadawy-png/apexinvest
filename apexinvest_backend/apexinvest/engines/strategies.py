"""Strategy engine: a registry of independent, testable strategy modules.

Each strategy implements the same protocol so new ones plug in without
touching the core. Every level a strategy emits is provenance-tagged, and each
strategy reports its own quality/uncertainty so downstream engines can weigh it
honestly. A strategy with insufficient data returns low quality and NEUTRAL
bias rather than a confident guess.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from ..domain import Bias, Objective, Provenance, RegimeSnapshot, StrategySignal, Trend
from . import indicators as ind


@dataclass
class StrategyContext:
    """Everything a strategy might need. Not all fields are always present."""
    candles: dict[str, pd.DataFrame]          # timeframe -> candles, e.g. {"1d": df, "30m": df}
    regime: RegimeSnapshot | None = None
    fundamentals: dict | None = None          # parsed from uploaded reports
    objective: Objective | None = None

    def primary(self) -> pd.DataFrame | None:
        """The most 'senior' timeframe available (prefer daily)."""
        for tf in ("1d", "1w", "4h", "1h", "30m", "15m", "5m"):
            if tf in self.candles:
                return self.candles[tf]
        return next(iter(self.candles.values()), None)


class Strategy(Protocol):
    id: str
    label: str
    required_inputs: list[str]
    def applicable_to(self, ctx: StrategyContext) -> float: ...
    def evaluate(self, ctx: StrategyContext) -> StrategySignal: ...


# --------------------------------------------------------------------------- #

class PriceAction:
    id = "price_action"
    label = "Price Action"
    # Structure / swing levels are computed from whatever chart is supplied; a
    # daily series is sufficient. Intraday sharpens entry timing but isn't required.
    required_inputs = ["daily_chart"]

    def applicable_to(self, ctx: StrategyContext) -> float:
        return 0.85 if ctx.primary() is not None else 0.0

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        df = ctx.primary()
        if df is None or len(df) < 20:
            return StrategySignal(self.id, Bias.NEUTRAL, 0.1, notes="Not enough candles for structure.")
        support, resistance = ind.swing_levels(df, 20)
        close = float(df["close"].iloc[-1])
        # Higher highs & higher lows over two halves => bullish structure.
        half = len(df) // 2
        hh = df["high"].tail(half).max() > df["high"].head(half).max()
        hl = df["low"].tail(half).min() > df["low"].head(half).min()
        if hh and hl:
            bias, quality = Bias.LONG, 0.8
        elif not hh and not hl:
            bias, quality = Bias.SHORT, 0.7
        else:
            bias, quality = Bias.NEUTRAL, 0.45
        return StrategySignal(
            self.id, bias, quality,
            entry_hint=close, invalidation=support, objective_level=resistance,
            notes=f"Structure {'bullish' if bias == Bias.LONG else 'bearish' if bias == Bias.SHORT else 'mixed'}; "
                  f"support {support:.4g}, resistance {resistance:.4g}.",
            provenance=[Provenance("computed:swing_levels", "20-bar high/low")],
        )


class POC:
    id = "poc"
    label = "POC / Volume Profile"
    # The volume profile / POC is computed from the candles themselves (OHLCV);
    # a daily series with volume is sufficient. Intraday is optional refinement.
    required_inputs = ["daily_chart", "volume_profile", "volume"]

    def applicable_to(self, ctx: StrategyContext) -> float:
        return 0.9 if ctx.primary() is not None else 0.0

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        df = ctx.primary()
        if df is None or len(df) < 20:
            return StrategySignal(self.id, Bias.NEUTRAL, 0.1, notes="Not enough candles for a volume profile.")
        vp = ind.volume_profile_poc(df)
        poc = vp["poc"]
        va_lo, va_hi = vp["value_area"]
        close = float(df["close"].iloc[-1])
        # Trading logic: above POC & value area => bullish acceptance; below => bearish.
        if close > va_hi:
            bias, quality, inval, obj = Bias.LONG, 0.75, poc, va_hi + (va_hi - va_lo)
        elif close < va_lo:
            bias, quality, inval, obj = Bias.SHORT, 0.7, poc, va_lo - (va_hi - va_lo)
        else:
            bias, quality, inval, obj = Bias.NEUTRAL, 0.5, va_lo, va_hi
        return StrategySignal(
            self.id, bias, quality,
            entry_hint=close, invalidation=float(inval), objective_level=float(obj),
            notes=f"POC {poc:.4g}, value area {va_lo:.4g}-{va_hi:.4g}; price {'above' if close>va_hi else 'below' if close<va_lo else 'inside'} value.",
            provenance=[Provenance("computed:volume_profile", "approx from candles", confidence=0.7)],
        )


class Momentum:
    id = "momentum"
    label = "Momentum"
    required_inputs = ["daily_chart", "volume"]

    def applicable_to(self, ctx: StrategyContext) -> float:
        # Momentum shines in trending regimes.
        if ctx.regime and ctx.regime.trend in (Trend.UP, Trend.DOWN):
            return 0.9
        return 0.6

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        df = ctx.primary()
        if df is None or len(df) < 30:
            return StrategySignal(self.id, Bias.NEUTRAL, 0.1, notes="Not enough candles for momentum.")
        rsi_v = ind.last(ind.rsi(df["close"])) or 50.0
        ema_fast = ind.last(ind.ema(df["close"], 12))
        ema_slow = ind.last(ind.ema(df["close"], 26))
        adx_v = ind.last(ind.adx(df)) or 0.0
        close = float(df["close"].iloc[-1])
        support, resistance = ind.swing_levels(df, 20)
        up = ema_fast is not None and ema_slow is not None and ema_fast > ema_slow and rsi_v > 50
        down = ema_fast is not None and ema_slow is not None and ema_fast < ema_slow and rsi_v < 50
        strength = min(adx_v / 40.0, 1.0)  # ADX 40+ => full strength
        if up:
            bias, quality, inval, obj = Bias.LONG, 0.5 + 0.4 * strength, support, resistance
        elif down:
            bias, quality, inval, obj = Bias.SHORT, 0.5 + 0.4 * strength, resistance, support
        else:
            bias, quality, inval, obj = Bias.NEUTRAL, 0.4, support, resistance
        return StrategySignal(
            self.id, bias, round(quality, 3),
            entry_hint=close, invalidation=support if bias == Bias.LONG else resistance,
            objective_level=resistance if bias == Bias.LONG else support,
            notes=f"RSI {rsi_v:.0f}, ADX {adx_v:.0f}, EMA {'12>26' if up else '12<26' if down else 'flat'}.",
            provenance=[Provenance("computed:rsi+ema+adx")],
        )


class Breakout:
    id = "breakout"
    label = "Breakout"
    required_inputs = ["intraday_chart", "volume"]

    def applicable_to(self, ctx: StrategyContext) -> float:
        return 0.8

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        df = ctx.primary()
        if df is None or len(df) < 25:
            return StrategySignal(self.id, Bias.NEUTRAL, 0.1, notes="Not enough candles for a range.")
        support, resistance = ind.swing_levels(df, 20)
        close = float(df["close"].iloc[-1])
        rng = resistance - support
        avg_vol = float(df["volume"].tail(20).mean())
        last_vol = float(df["volume"].iloc[-1])
        vol_expansion = last_vol > 1.3 * avg_vol if avg_vol else False
        near_high = rng > 0 and close >= resistance - 0.1 * rng
        if near_high and vol_expansion:
            bias, quality = Bias.LONG, 0.8
        elif near_high:
            bias, quality = Bias.LONG, 0.55  # at highs but volume not confirming
        else:
            bias, quality = Bias.NEUTRAL, 0.4
        return StrategySignal(
            self.id, bias, quality,
            entry_hint=close, invalidation=support, objective_level=resistance + rng,
            notes=f"Range {support:.4g}-{resistance:.4g}; volume {'expanding' if vol_expansion else 'normal'}.",
            provenance=[Provenance("computed:range+volume")],
        )


class Accumulation:
    id = "accumulation"
    label = "Accumulation"
    required_inputs = ["daily_chart", "volume_profile", "volume"]

    def applicable_to(self, ctx: StrategyContext) -> float:
        return 0.75

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        df = ctx.primary()
        if df is None or len(df) < 30:
            return StrategySignal(self.id, Bias.NEUTRAL, 0.1, notes="Not enough candles for accumulation.")
        o = ind.obv(df)
        obv_slope = float(o.iloc[-1] - o.iloc[-min(20, len(o))])
        support, resistance = ind.swing_levels(df, 30)
        close = float(df["close"].iloc[-1])
        if obv_slope > 0:
            bias, quality = Bias.LONG, 0.7
        elif obv_slope < 0:
            bias, quality = Bias.SHORT, 0.6
        else:
            bias, quality = Bias.NEUTRAL, 0.45
        return StrategySignal(
            self.id, bias, quality,
            entry_hint=close, invalidation=support, objective_level=resistance,
            notes=f"OBV {'rising (accumulation)' if obv_slope>0 else 'falling (distribution)' if obv_slope<0 else 'flat'}.",
            provenance=[Provenance("computed:obv")],
        )


class Fundamental:
    id = "fundamental"
    label = "Fundamental"
    required_inputs = ["financials"]

    def applicable_to(self, ctx: StrategyContext) -> float:
        return 0.9 if ctx.fundamentals else 0.2

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        f = ctx.fundamentals or {}
        # Only score what was actually parsed; never fabricate missing metrics.
        found = {k: v for k, v in f.items() if isinstance(v, (int, float))}
        if not found:
            return StrategySignal(
                self.id, Bias.NEUTRAL, 0.15,
                notes="No parseable financial metrics found — upload a report to enable this.",
                provenance=[Provenance("extracted:financials", "none found", confidence=0.0)],
            )
        score = 0.0
        weights = 0.0
        if "revenue_growth" in found:
            score += 1.0 if found["revenue_growth"] > 0.10 else (0.5 if found["revenue_growth"] > 0 else 0.0)
            weights += 1
        if "net_margin" in found:
            score += 1.0 if found["net_margin"] > 0.15 else (0.5 if found["net_margin"] > 0 else 0.0)
            weights += 1
        if "debt_to_equity" in found:
            score += 1.0 if found["debt_to_equity"] < 1.0 else (0.5 if found["debt_to_equity"] < 2.0 else 0.0)
            weights += 1
        norm = score / weights if weights else 0.0
        bias = Bias.LONG if norm >= 0.66 else (Bias.NEUTRAL if norm >= 0.4 else Bias.SHORT)
        return StrategySignal(
            self.id, bias, round(0.4 + 0.5 * norm, 3),
            notes=f"Fundamental score {norm:.0%} from {len(found)} metric(s).",
            provenance=[Provenance("extracted:financials", f"{sorted(found)}", confidence=0.9)],
        )


class TrendMA:
    id = "trend"
    label = "Trend (Moving Averages)"
    required_inputs = ["daily_chart"]

    def applicable_to(self, ctx: StrategyContext) -> float:
        df = ctx.primary()
        return 0.9 if (df is not None and len(df) >= 50) else (0.5 if df is not None else 0.0)

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        df = ctx.primary()
        if df is None or len(df) < 50:
            return StrategySignal(self.id, Bias.NEUTRAL, 0.15, notes="Not enough history for a moving-average trend.")
        close = float(df["close"].iloc[-1])
        sma50 = ind.last(ind.sma(df["close"], 50))
        sma200 = ind.last(ind.sma(df["close"], 200)) if len(df) >= 200 else None
        support, resistance = ind.swing_levels(df, 30)
        s50 = ind.sma(df["close"], 50).dropna()
        slope = float(s50.iloc[-1] - s50.iloc[-min(10, len(s50))]) if len(s50) >= 2 else 0.0
        long_ok = sma50 is not None and close > sma50 and (sma200 is None or close > sma200) and slope > 0
        short_ok = sma50 is not None and close < sma50 and (sma200 is None or close < sma200) and slope < 0
        strong = long_ok and sma200 is not None and sma50 > sma200
        if long_ok:
            bias, quality = Bias.LONG, 0.85 if strong else 0.65
        elif short_ok:
            bias, quality = Bias.SHORT, 0.7
        else:
            bias, quality = Bias.NEUTRAL, 0.45
        cross = ""
        if sma50 is not None and sma200 is not None:
            cross = " (golden cross)" if sma50 > sma200 else " (death cross)"
        ma_txt = f"MA50 {sma50:.4g}" + (f", MA200 {sma200:.4g}" if sma200 is not None else "")
        return StrategySignal(
            self.id, bias, round(quality, 3),
            entry_hint=close,
            invalidation=(sma50 if (bias == Bias.LONG and sma50 is not None) else support),
            objective_level=resistance,
            notes=f"{'Uptrend' if bias == Bias.LONG else 'Downtrend' if bias == Bias.SHORT else 'No clear trend'}: "
                  f"price {close:.4g} vs {ma_txt}{cross}.",
            provenance=[Provenance("computed:moving_averages", "20/50/200 SMA")],
        )


class MACDStrategy:
    id = "macd"
    label = "MACD"
    required_inputs = ["daily_chart"]

    def applicable_to(self, ctx: StrategyContext) -> float:
        df = ctx.primary()
        return 0.8 if (df is not None and len(df) >= 35) else (0.4 if df is not None else 0.0)

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        df = ctx.primary()
        if df is None or len(df) < 35:
            return StrategySignal(self.id, Bias.NEUTRAL, 0.15, notes="Not enough history for MACD.")
        m, s, h = ind.macd(df["close"])
        ml, sl, hl = ind.last(m), ind.last(s), ind.last(h)
        if ml is None or sl is None or hl is None:
            return StrategySignal(self.id, Bias.NEUTRAL, 0.2, notes="MACD not computable yet.")
        hclean = h.dropna()
        hist_prev = float(hclean.iloc[-min(3, len(hclean))]) if len(hclean) >= 2 else hl
        rising = hl > hist_prev
        close = float(df["close"].iloc[-1])
        support, resistance = ind.swing_levels(df, 20)
        if ml > sl and hl > 0:
            bias, quality = Bias.LONG, 0.75 if rising else 0.6
        elif ml < sl and hl < 0:
            bias, quality = Bias.SHORT, 0.7 if not rising else 0.55
        else:
            bias, quality = Bias.NEUTRAL, 0.45
        return StrategySignal(
            self.id, bias, round(quality, 3),
            entry_hint=close, invalidation=support, objective_level=resistance,
            notes=f"MACD {'above' if ml > sl else 'below'} signal; histogram {'rising' if rising else 'falling'} ({hl:+.3g}).",
            provenance=[Provenance("computed:macd", "12/26/9")],
        )


class RSIStrategy:
    id = "rsi"
    label = "RSI (Momentum)"
    required_inputs = ["daily_chart"]

    def applicable_to(self, ctx: StrategyContext) -> float:
        df = ctx.primary()
        return 0.7 if (df is not None and len(df) >= 20) else (0.3 if df is not None else 0.0)

    def evaluate(self, ctx: StrategyContext) -> StrategySignal:
        df = ctx.primary()
        if df is None or len(df) < 20:
            return StrategySignal(self.id, Bias.NEUTRAL, 0.15, notes="Not enough history for RSI.")
        r = ind.rsi(df["close"])
        rv = ind.last(r)
        if rv is None:
            return StrategySignal(self.id, Bias.NEUTRAL, 0.2, notes="RSI not computable yet.")
        rclean = r.dropna()
        rprev = float(rclean.iloc[-min(4, len(rclean))]) if len(rclean) >= 2 else rv
        rising = rv > rprev
        close = float(df["close"].iloc[-1])
        support, resistance = ind.swing_levels(df, 20)
        if rv >= 70:
            bias, quality, note = Bias.LONG, 0.45, f"RSI {rv:.0f} — strong but overbought; upside momentum, but chase-risk is high."
        elif rv > 55 and rising:
            bias, quality, note = Bias.LONG, 0.7, f"RSI {rv:.0f} and rising — healthy bullish momentum."
        elif rv <= 30:
            bias, quality, note = Bias.LONG, 0.55, f"RSI {rv:.0f} — oversold; a mean-reversion bounce is possible."
        elif rv < 45 and not rising:
            bias, quality, note = Bias.SHORT, 0.6, f"RSI {rv:.0f} and falling — weak momentum."
        else:
            bias, quality, note = Bias.NEUTRAL, 0.45, f"RSI {rv:.0f} — neutral momentum."
        return StrategySignal(
            self.id, bias, round(quality, 3),
            entry_hint=close, invalidation=support, objective_level=resistance,
            notes=note, provenance=[Provenance("computed:rsi", "14-period Wilder")],
        )


REGISTRY: dict[str, Strategy] = {
    s.id: s for s in [
        PriceAction(), POC(), Momentum(), Breakout(), Accumulation(), Fundamental(),
        TrendMA(), MACDStrategy(), RSIStrategy(),
    ]
}


def get(strategy_id: str) -> Strategy:
    if strategy_id not in REGISTRY:
        raise KeyError(f"unknown strategy: {strategy_id}")
    return REGISTRY[strategy_id]


def required_inputs_for(strategy_ids: list[str]) -> list[str]:
    seen: list[str] = []
    for sid in strategy_ids:
        for inp in get(sid).required_inputs:
            if inp not in seen:
                seen.append(inp)
    return seen
