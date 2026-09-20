"""New methods (Trend / MACD / RSI) and the confluence panel."""
from apexinvest.domain import Bias, Objective
from apexinvest.engines import indicators as ind
from apexinvest.engines import recommendation as reco
from apexinvest.engines import regime as regime_engine
from apexinvest.engines import strategies as strat
from apexinvest.engines.strategies import StrategyContext


def _ctx(df):
    return StrategyContext(candles={"1d": df}, regime=regime_engine.detect_regime(df))


def test_new_methods_registered():
    for sid in ("trend", "macd", "rsi"):
        assert sid in strat.REGISTRY


def test_macd_indicator_computes(uptrend):
    m, s, h = ind.macd(uptrend["close"])
    assert ind.last(m) is not None and ind.last(s) is not None and ind.last(h) is not None


def test_trend_is_bullish_on_uptrend(uptrend):
    assert strat.get("trend").evaluate(_ctx(uptrend)).bias == Bias.LONG


def test_macd_not_bearish_on_uptrend(uptrend):
    assert strat.get("macd").evaluate(_ctx(uptrend)).bias in (Bias.LONG, Bias.NEUTRAL)


def test_rsi_signal_valid(uptrend):
    sig = strat.get("rsi").evaluate(_ctx(uptrend))
    assert sig.bias in (Bias.LONG, Bias.NEUTRAL, Bias.SHORT) and 0.0 <= sig.quality <= 1.0


def test_swing_panel_is_multi_method(uptrend):
    rec = reco.recommend(Objective.SWING, _ctx(uptrend))
    # A professional reads several confirming methods, not one.
    assert len(rec.recommended) >= 3
    assert "price_action" in rec.recommended and "trend" in rec.recommended


def test_longterm_panel_includes_trend_and_accumulation(uptrend):
    rec = reco.recommend(Objective.LONG_TERM, _ctx(uptrend))
    assert "trend" in rec.recommended and "accumulation" in rec.recommended
