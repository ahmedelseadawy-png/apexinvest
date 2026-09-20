from apexinvest.domain import Bias, Objective, Trend
from apexinvest.engines import recommendation as reco
from apexinvest.engines import regime as regime_engine
from apexinvest.engines import strategies as strat
from apexinvest.engines.strategies import StrategyContext


# ---- regime --------------------------------------------------------------- #

def test_regime_uptrend(uptrend):
    r = regime_engine.detect_regime(uptrend)
    assert r.trend == Trend.UP


def test_regime_downtrend(downtrend):
    r = regime_engine.detect_regime(downtrend)
    assert r.trend == Trend.DOWN


def test_regime_sideways(sideways):
    r = regime_engine.detect_regime(sideways)
    assert r.trend == Trend.SIDEWAYS


# ---- strategies ----------------------------------------------------------- #

def test_price_action_long_on_uptrend(uptrend):
    ctx = StrategyContext(candles={"1d": uptrend})
    sig = strat.get("price_action").evaluate(ctx)
    assert sig.bias == Bias.LONG
    assert sig.invalidation < sig.entry_hint  # support below price


def test_momentum_long_on_uptrend(uptrend):
    ctx = StrategyContext(candles={"1d": uptrend}, regime=regime_engine.detect_regime(uptrend))
    sig = strat.get("momentum").evaluate(ctx)
    assert sig.bias == Bias.LONG
    assert sig.quality > 0.5


def test_momentum_short_on_downtrend(downtrend):
    ctx = StrategyContext(candles={"1d": downtrend}, regime=regime_engine.detect_regime(downtrend))
    sig = strat.get("momentum").evaluate(ctx)
    assert sig.bias == Bias.SHORT


def test_strategy_insufficient_data_is_low_quality():
    import pandas as pd
    tiny = pd.DataFrame({"open": [1.0], "high": [1.0], "low": [1.0], "close": [1.0], "volume": [1.0]})
    sig = strat.get("price_action").evaluate(StrategyContext(candles={"1d": tiny}))
    assert sig.bias == Bias.NEUTRAL and sig.quality < 0.3


def test_fundamental_needs_data():
    empty = strat.get("fundamental").evaluate(StrategyContext(candles={}))
    assert empty.quality < 0.3
    good = strat.get("fundamental").evaluate(StrategyContext(
        candles={}, fundamentals={"revenue_growth": 0.2, "net_margin": 0.2, "debt_to_equity": 0.5}))
    assert good.bias == Bias.LONG and good.quality > empty.quality


def test_required_inputs_union():
    inputs = strat.required_inputs_for(["poc", "price_action"])
    assert "volume_profile" in inputs and "daily_chart" in inputs
    assert len(inputs) == len(set(inputs))  # de-duplicated


# ---- recommendation engine ------------------------------------------------ #

def test_recommend_long_term_prefers_fundamental(uptrend):
    ctx = StrategyContext(candles={"1d": uptrend}, regime=regime_engine.detect_regime(uptrend),
                          fundamentals={"revenue_growth": 0.2, "net_margin": 0.2})
    rec = reco.recommend(Objective.LONG_TERM, ctx)
    assert "fundamental" in rec.recommended


def test_recommend_swing_prefers_poc_or_price_action(uptrend):
    ctx = StrategyContext(candles={"1d": uptrend}, regime=regime_engine.detect_regime(uptrend))
    rec = reco.recommend(Objective.SWING, ctx)
    assert set(rec.recommended) & {"poc", "price_action"}
    assert rec.required_inputs  # non-empty


def test_recommend_day_prefers_momentum_or_breakout(uptrend):
    ctx = StrategyContext(candles={"1d": uptrend}, regime=regime_engine.detect_regime(uptrend))
    rec = reco.recommend(Objective.DAY, ctx)
    assert set(rec.recommended) & {"momentum", "breakout"}


def test_recommendation_ranking_is_sorted(uptrend):
    ctx = StrategyContext(candles={"1d": uptrend}, regime=regime_engine.detect_regime(uptrend))
    rec = reco.recommend(Objective.SWING, ctx)
    scores = [s.score for s in rec.ranking]
    assert scores == sorted(scores, reverse=True)
