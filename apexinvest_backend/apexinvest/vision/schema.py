"""Structured schema for a vision provider's chart-screenshot analysis.

Raw AI output is never trusted directly (spec: "never let arbitrary AI-
generated fields enter the existing analysis engine"). Every field the
vision model returns is validated here before it reaches the API response:
unknown keys are dropped (``extra="ignore"``), every field is Optional with
an honest ``None``/empty default, and nothing here computes or infers a
number — a value the model didn't (or couldn't) read from the image simply
stays ``None``, never a guess.

This schema is deliberately generic instead of one-model-shaped: any vision
provider that returns roughly the JSON shape documented in each field can be
plugged in behind ``apexinvest/vision/provider.py`` without changing this
file.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ChartInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")
    symbol: str | None = None
    company: str | None = None
    exchange: str | None = None
    timeframe: str | None = None
    current_visible_price: float | None = None
    chart_type: str | None = None


class DataQuality(BaseModel):
    model_config = ConfigDict(extra="ignore")
    readability: str | None = None            # "high" | "medium" | "low"
    technical_confidence: str | None = None    # "high" | "medium" | "low"


class Trend(BaseModel):
    model_config = ConfigDict(extra="ignore")
    primary: str | None = None
    short_term: str | None = None
    strength: str | None = None


class Structure(BaseModel):
    model_config = ConfigDict(extra="ignore")
    status: str | None = None
    higher_highs: bool | None = None
    higher_lows: bool | None = None
    lower_highs: bool | None = None
    lower_lows: bool | None = None
    break_of_structure: str | None = None


class Levels(BaseModel):
    model_config = ConfigDict(extra="ignore")
    major_support: list[float] = []
    support: list[float] = []
    resistance: list[float] = []
    major_resistance: list[float] = []


class VolumeProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")
    poc: float | None = None
    vah: float | None = None
    val: float | None = None
    hvn: list[float] = []
    lvn: list[float] = []


class TrendConfirmation(BaseModel):
    model_config = ConfigDict(extra="ignore")
    # 0-100 "degree of agreement between visible technical evidence" -- NEVER
    # a probability of profit / win-rate / prediction (spec section 15/28).
    confirmation_score: int | None = None
    confirmed: list[str] = []
    missing: list[str] = []


class ScenarioBlock(BaseModel):
    """One generic trade-scenario block (breakout / retest / pullback / failed
    breakout / breakdown). Fields are a superset; each scenario type only
    fills the ones that apply, the rest stay ``None`` -- never invented."""
    model_config = ConfigDict(extra="ignore")
    resistance: float | None = None
    support: float | None = None
    level: float | None = None
    zone: list[float] | None = None
    retest_zone: list[float] | None = None
    trigger: str | None = None
    confirmation: list[str] = []
    entry: float | None = None
    stop: float | None = None
    tp1: float | None = None
    tp2: float | None = None
    invalidation: str | None = None
    reason: str | None = None
    action: str | None = None
    status: str | None = None      # Watching/Triggered/Confirmed/Retesting/Validated/Failed


class TradeScenarios(BaseModel):
    model_config = ConfigDict(extra="ignore")
    breakout: ScenarioBlock | None = None
    breakout_retest: ScenarioBlock | None = None
    pullback: ScenarioBlock | None = None
    failed_breakout: ScenarioBlock | None = None
    breakdown: ScenarioBlock | None = None


class FinalSignal(BaseModel):
    model_config = ConfigDict(extra="ignore")
    # This is a VISUAL read of the screenshot only -- never the authoritative
    # ApexInvest decision (see apexinvest/vision/build.py's module docstring).
    action: str | None = None      # "BUY" | "WAIT" | "AVOID" | None
    reason: str | None = None
    next_trigger: str | None = None
    invalidation: str | None = None


class VisionAnalysis(BaseModel):
    """Top-level validated shape of one screenshot analysis. ``indicators``
    and ``price_action`` stay free-form descriptive dicts (e.g. {"rsi":
    "Above 50, no divergence visible"}) since indicator readouts are prose,
    not always a single number -- the "never invent a number" rule is
    enforced by the provider's prompt/instructions, not by this schema."""
    model_config = ConfigDict(extra="ignore")
    source: str = "tradingview_screenshot"
    chart_info: ChartInfo = ChartInfo()
    data_quality: DataQuality = DataQuality()
    trend: Trend = Trend()
    structure: Structure = Structure()
    indicators: dict[str, Any] = {}
    levels: Levels = Levels()
    volume_profile: VolumeProfile = VolumeProfile()
    price_action: dict[str, Any] = {}
    trend_confirmation: TrendConfirmation = TrendConfirmation()
    trade_scenarios: TradeScenarios = TradeScenarios()
    final_signal: FinalSignal = FinalSignal()
    notes: list[str] = []
