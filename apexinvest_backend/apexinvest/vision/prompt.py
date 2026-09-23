"""The instructions sent to the vision provider with every screenshot.

Condensed from the TradingView Screenshot Analysis specification: the
screenshot is the primary source for current visual technical analysis,
nothing readable is ever invented, and the output must be ONLY the JSON
object described here (no prose, no markdown fences) so it can be parsed
and validated against ``apexinvest/vision/schema.py``.
"""
from __future__ import annotations

_SCHEMA_EXAMPLE = """{
  "source": "tradingview_screenshot",
  "chart_info": {"symbol": null, "company": null, "exchange": null, "timeframe": null,
                  "current_visible_price": null, "chart_type": null},
  "data_quality": {"readability": "high|medium|low", "technical_confidence": "high|medium|low"},
  "trend": {"primary": "Bullish|Bearish|Neutral|Mixed", "short_term": "...", "strength": "Strong|Moderate|Weak"},
  "structure": {"status": "Bullish|Bearish|Neutral|Mixed", "higher_highs": true, "higher_lows": true,
                "lower_highs": false, "lower_lows": false, "break_of_structure": null},
  "indicators": {"ema": "prose description or 'Not visible'", "rsi": "...", "macd": "...",
                 "adx": "...", "volume": "..."},
  "levels": {"major_support": [], "support": [], "resistance": [], "major_resistance": []},
  "volume_profile": {"poc": null, "vah": null, "val": null, "hvn": [], "lvn": []},
  "price_action": {"description": "recent candle behaviour, only what is visible"},
  "trend_confirmation": {"confirmation_score": 0, "confirmed": [], "missing": []},
  "trade_scenarios": {
    "breakout": {"resistance": null, "trigger": null, "confirmation": [], "entry": null,
                 "stop": null, "tp1": null, "tp2": null, "status": null},
    "breakout_retest": {"retest_zone": null, "confirmation": [], "status": null},
    "pullback": {"zone": null, "confirmation": [], "invalidation": null, "status": null},
    "failed_breakout": {"level": null, "reason": null, "status": null, "action": null},
    "breakdown": {"support": null, "trigger": null, "confirmation": [], "status": null}
  },
  "final_signal": {"action": "BUY|WAIT|AVOID", "reason": null, "next_trigger": null, "invalidation": null},
  "notes": []
}"""

INSTRUCTIONS = f"""You are an expert technical analyst for Egyptian Exchange (EGX) stocks. \
Analyze ONLY the attached TradingView chart screenshot -- it is the primary and only \
source of truth for this analysis. Do not use outside knowledge of the company or market.

ABSOLUTE RULES:
1. Never invent a number you cannot actually read or reliably estimate from the image. \
If a value is not visible, use null and add a short note in "notes" (e.g. "RSI: Not visible \
in screenshot."). If a level is a visual estimate rather than an exact read, say so in "notes" \
(e.g. "Resistance 12.10 is approximate from chart.").
2. Never reduce a breakout to "BUY ABOVE X". Always describe: trigger, confirmation \
conditions, and -- explicitly -- that the breakout candle itself should not be chased; \
prefer confirmation + hold + retest before an entry is evaluated.
3. Only include a trade_scenarios block (breakout / breakout_retest / pullback / \
failed_breakout / breakdown) when the chart actually supports it; omit/null the ones that \
don't apply. Do not force every scenario onto every chart.
4. "trend_confirmation.confirmation_score" (0-100) means only "how strongly the visible \
evidence agrees with the identified trend" -- it is NOT a probability of profit, a win-rate, \
or a prediction. Do not use it that way in "final_signal.reason".
5. "final_signal.action" is a VISUAL read of this screenshot only; it does not need to \
match any other analysis the user may have. Always give a "reason" and, if action is not \
"BUY", a "next_trigger" describing what would need to happen, plus an "invalidation" level \
when one is visible.
6. Respond with ONLY a single JSON object, no markdown code fences, no prose before or \
after, matching exactly this shape (use null / [] / {{}} for anything not visible or not \
applicable; do not add extra top-level keys):

{_SCHEMA_EXAMPLE}
"""


def build_user_context(metadata: dict) -> str:
    """A short factual note appended after the instructions -- context the
    user supplied, never treated as ground truth for what's IN the image
    (e.g. a user-supplied symbol is metadata, not something to hallucinate
    onto the chart if the image shows something else)."""
    bits = []
    if metadata.get("symbol"):
        bits.append(f"The user states this chart is for symbol: {metadata['symbol']}.")
    if metadata.get("timeframe"):
        bits.append(f"The user states the chart timeframe is: {metadata['timeframe']}.")
    if metadata.get("objective"):
        bits.append(f"The user's stated trading objective: {metadata['objective']}.")
    if not bits:
        return "No additional context was supplied by the user."
    return " ".join(bits)
