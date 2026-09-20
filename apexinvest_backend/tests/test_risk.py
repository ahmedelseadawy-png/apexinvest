"""Critical-calculation + anti-fabrication suite for the risk engine.

These are the tests that must pass before shipping: they verify the numbers and
the honesty gates (WAIT on missing data, AVOID on regime conflict).
"""
from apexinvest.domain import Action, Objective
from apexinvest.engines import regime as regime_engine
from apexinvest.engines import risk
from apexinvest.engines import strategies as strat
from apexinvest.engines.strategies import StrategyContext


def _signals(ctx, ids):
    return [strat.get(i).evaluate(ctx) for i in ids]


def test_missing_data_returns_wait(uptrend):
    ctx = StrategyContext(candles={"1d": uptrend}, regime=regime_engine.detect_regime(uptrend))
    plan = risk.build_plan(
        objective=Objective.SWING,
        signals=_signals(ctx, ["poc", "price_action"]),
        primary_candles=uptrend, reference_price=100.0,
        regime=ctx.regime,
        required_inputs=["daily_chart", "intraday_chart", "volume_profile", "volume"],
        provided_inputs=["daily_chart"],   # deliberately incomplete
    )
    assert plan.action == Action.WAIT
    assert "volume_profile" in plan.missing
    assert plan.entry is None  # NO fabricated levels


def test_no_price_returns_wait():
    # No candles, no reference price -> cannot build levels.
    plan = risk.build_plan(
        objective=Objective.SWING, signals=[],
        primary_candles=None, reference_price=None, regime=None,
        required_inputs=[], provided_inputs=[],
    )
    assert plan.action == Action.WAIT
    assert plan.entry is None


def test_downtrend_long_objective_returns_avoid(downtrend):
    ctx = StrategyContext(candles={"1d": downtrend}, regime=regime_engine.detect_regime(downtrend))
    req = ["daily_chart", "intraday_chart"]
    plan = risk.build_plan(
        objective=Objective.SWING,
        signals=_signals(ctx, ["price_action"]),
        primary_candles=downtrend, reference_price=float(downtrend["close"].iloc[-1]),
        regime=ctx.regime, required_inputs=req, provided_inputs=req,
    )
    assert plan.action == Action.AVOID
    assert plan.entry is None


def test_clean_uptrend_returns_buy_with_valid_rr(uptrend):
    ctx = StrategyContext(candles={"1d": uptrend}, regime=regime_engine.detect_regime(uptrend))
    req = strat.required_inputs_for(["price_action", "momentum"])
    plan = risk.build_plan(
        objective=Objective.SWING,
        signals=_signals(ctx, ["price_action", "momentum"]),
        primary_candles=uptrend, reference_price=float(uptrend["close"].iloc[-1]),
        regime=ctx.regime, required_inputs=req, provided_inputs=req,
        timeframes_provided=2,
    )
    assert plan.action == Action.BUY
    assert plan.stop < plan.entry < plan.target       # ordered correctly
    assert plan.rr >= 1.8                              # meets swing minimum
    assert 1 <= plan.confidence_score <= 5


def test_rr_math_is_exact(uptrend):
    ctx = StrategyContext(candles={"1d": uptrend}, regime=regime_engine.detect_regime(uptrend))
    req = strat.required_inputs_for(["price_action"])
    plan = risk.build_plan(
        objective=Objective.SWING,
        signals=_signals(ctx, ["price_action"]),
        primary_candles=uptrend, reference_price=float(uptrend["close"].iloc[-1]),
        regime=ctx.regime, required_inputs=req, provided_inputs=req,
    )
    if plan.action == Action.BUY:
        expected = round((plan.target - plan.entry) / (plan.entry - plan.stop), 2)
        assert abs(plan.rr - expected) <= 0.01        # rr equals its own definition


def test_every_number_has_provenance(uptrend):
    ctx = StrategyContext(candles={"1d": uptrend}, regime=regime_engine.detect_regime(uptrend))
    req = strat.required_inputs_for(["price_action"])
    plan = risk.build_plan(
        objective=Objective.SWING, signals=_signals(ctx, ["price_action"]),
        primary_candles=uptrend, reference_price=float(uptrend["close"].iloc[-1]),
        regime=ctx.regime, required_inputs=req, provided_inputs=req,
    )
    if plan.action == Action.BUY:
        sources = {p.source for p in plan.provenance}
        assert any("entry" in s for s in sources)
        assert any("target" in s for s in sources)


def test_confidence_is_five_named_parts(uptrend):
    ctx = StrategyContext(candles={"1d": uptrend}, regime=regime_engine.detect_regime(uptrend))
    req = strat.required_inputs_for(["price_action"])
    plan = risk.build_plan(
        objective=Objective.SWING, signals=_signals(ctx, ["price_action"]),
        primary_candles=uptrend, reference_price=float(uptrend["close"].iloc[-1]),
        regime=ctx.regime, required_inputs=req, provided_inputs=req,
    )
    keys = {p.key for p in plan.confidence_parts}
    assert keys == {"data_completeness", "timeframe_agreement", "level_clarity", "liquidity", "regime_fit"}
