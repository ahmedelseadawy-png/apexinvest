"""Combine a validated screenshot analysis with the existing ApexInvest engine
output -- comparison only, never a merge. Nothing here writes back into the
``analyze_symbol`` result or changes ``plan.action``; the existing BUY/WAIT/
AVOID signal is read-only input to this module (spec sections 16-18: this
must never become a second recommendation engine).
"""
from __future__ import annotations

from .schema import VisionAnalysis

_DISCREPANCY_PCT_THRESHOLD = 1.0   # >1% difference is flagged as significant


def existing_summary(existing: dict | None) -> dict | None:
    """A small, display-sized summary of the existing engine's own result --
    never the full payload, and never modified."""
    if not existing:
        return None
    plan = existing.get("plan") or {}
    ds = existing.get("data_source") or {}
    return {
        "action": plan.get("action"),
        "entry": plan.get("entry"),
        "stop": plan.get("stop"),
        "target": plan.get("target"),
        "price": ds.get("price") or ds.get("last_close"),
        "price_as_of": ds.get("price_as_of") or ds.get("as_of"),
        "provider": ds.get("price_source") or ds.get("source"),
    }


def data_discrepancy(vision: VisionAnalysis, existing: dict | None) -> dict | None:
    """Never silently reconciled (spec section 4): if both a screenshot price
    and an existing/EODHD price are available and they disagree by more than
    the threshold, report it explicitly. Returns None only when there is
    nothing to compare (one side missing) or the two agree closely."""
    screenshot_price = vision.chart_info.current_visible_price
    if screenshot_price is None or not existing:
        return None
    ds = existing.get("data_source") or {}
    external_price = ds.get("price") or ds.get("last_close")
    if not external_price:
        return None
    external_price = float(external_price)
    if external_price == 0:
        return None
    diff_pct = abs(screenshot_price - external_price) / external_price * 100.0
    status = "discrepancy" if diff_pct > _DISCREPANCY_PCT_THRESHOLD else "consistent"
    return {
        "screenshot_price": round(screenshot_price, 4),
        "external_price": round(external_price, 4),
        "difference_pct": round(diff_pct, 2),
        "status": status,
    }


def _normalize_action(action: str | None) -> str | None:
    if not action:
        return None
    a = action.strip().upper()
    return a if a in ("BUY", "WAIT", "AVOID") else None


def compare_with_apexinvest(vision: VisionAnalysis, existing: dict | None) -> dict:
    """Side-by-side comparison + an ``alignment`` read. This is descriptive
    only -- it never changes ``existing["plan"]["action"]`` and the caller
    must not feed this back into the existing engine (spec section 16-18)."""
    screenshot_action = _normalize_action(vision.final_signal.action)
    if not existing:
        return {
            "apexinvest_signal": None,
            "screenshot_visual_signal": screenshot_action,
            "alignment": "Insufficient Data",
            "explanation": "No ApexInvest/EODHD analysis was available for comparison "
                           "(no symbol supplied, or the market-data fetch failed).",
        }
    existing_action = _normalize_action((existing.get("plan") or {}).get("action"))
    if existing_action is None or screenshot_action is None:
        return {
            "apexinvest_signal": existing_action,
            "screenshot_visual_signal": screenshot_action,
            "alignment": "Insufficient Data",
            "explanation": "One of the two signals could not be determined, so alignment "
                           "cannot be assessed.",
        }
    if existing_action == screenshot_action:
        alignment = "Aligned"
        explanation = f"Both the ApexInvest engine and the screenshot read {existing_action}."
    elif {existing_action, screenshot_action} == {"WAIT", "BUY"}:
        alignment = "Developing"
        explanation = ("The screenshot shows a bullish picture developing while the ApexInvest "
                       "engine is still WAIT (or vice versa) -- treat this as a heads-up, not a "
                       "signal to act ahead of engine confirmation.")
    else:
        alignment = "Diverging"
        explanation = (f"ApexInvest reads {existing_action} while the screenshot reads "
                       f"{screenshot_action}. The existing ApexInvest signal remains authoritative; "
                       "this divergence is shown for context only.")
    return {
        "apexinvest_signal": existing_action,
        "screenshot_visual_signal": screenshot_action,
        "alignment": alignment,
        "explanation": explanation,
    }


def position_view(qty: float | None, avg_price: float | None, vision: VisionAnalysis) -> dict | None:
    """Optional, separate from the existing risk engine (spec section 31):
    simple P/L + distance-to-level context from whatever the screenshot
    actually shows. Never invents a level; each field is None when the
    screenshot doesn't provide the corresponding level."""
    if not qty or not avg_price:
        return None
    price = vision.chart_info.current_visible_price
    out: dict = {"quantity": qty, "average_price": avg_price, "current_price": price}
    if price is not None:
        out["unrealized_pl_pct"] = round((price - avg_price) / avg_price * 100.0, 2)
        out["unrealized_pl"] = round((price - avg_price) * qty, 2)
        supports = sorted(vision.levels.support + vision.levels.major_support)
        resistances = sorted(vision.levels.resistance + vision.levels.major_resistance)
        nearest_support = max([s for s in supports if s < price], default=None)
        nearest_resistance = min([r for r in resistances if r > price], default=None)
        out["distance_to_support_pct"] = (
            round((price - nearest_support) / price * 100.0, 2) if nearest_support else None)
        out["distance_to_resistance_pct"] = (
            round((nearest_resistance - price) / price * 100.0, 2) if nearest_resistance else None)
    else:
        out["unrealized_pl_pct"] = None
        out["unrealized_pl"] = None
        out["distance_to_support_pct"] = None
        out["distance_to_resistance_pct"] = None
    return out
