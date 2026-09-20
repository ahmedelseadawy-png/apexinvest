"""Portfolio / wallet analysis (Update: 'analyze my positions').

You give it what you already hold — symbol, quantity, average cost — and it runs
each position through the SAME engine and answers the only question that matters
for an open trade: what do I do now? HOLD, ADD, TRIM, or EXIT — with a protective
stop and a reason.

Honest and rule-based (no fabrication, not advice):
  * Unrealised P/L is arithmetic from your average cost and the live price.
  * The action comes from the current structure, not hope: a position that has
    lost its support or whose trend has rolled over is an EXIT, however much you
    like the company; a healthy uptrend above support is a HOLD; a stretched
    winner showing supply is a TRIM (take some, trail the stop); a pullback into
    a fresh buy zone with the thesis intact is where ADD is allowed.
  * A protective stop is always suggested, placed at real structure (nearest
    support / value-area low), so every position has a defined risk.
  * Portfolio level: total value, total unrealised P/L, per-name weight, and a
    concentration warning when one position dominates.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..domain import Objective


def _protective_stop(price: float, lv: dict) -> tuple[float | None, str]:
    """A protective stop for an OPEN position — at real structure below price."""
    atr = lv.get("atr") or price * 0.02
    sups = sorted(s for s in (lv.get("supports") or []) if s is not None and s < price * 0.999)
    if sups:
        s = sups[-1]                                   # nearest support below price
        return round(s - 0.5 * atr, 4), f"below nearest support {s}"
    rl = lv.get("range_low")
    if rl is not None and rl < price:
        return round(rl - 0.5 * atr, 4), f"below the value-area low {rl}"
    return round(price * 0.90, 4), "10% protective stop (no clean support nearby)"


@dataclass
class Position:
    row: dict


def analyze_position(holding: dict, plan: dict, *, weight_pct: float | None = None) -> dict:
    """Turn one holding + its fresh engine plan into an action row."""
    sym = str(holding.get("symbol", "")).upper()
    qty = float(holding.get("qty") or 0)
    avg = float(holding.get("avg_cost") or 0)
    lv = plan.get("entry_levels", {}) or {}
    price = plan.get("current_price")
    if price is None:
        price = avg or 0.0
    price = float(price)

    mv = qty * price
    cost = qty * avg
    pl = mv - cost
    pl_pct = ((price / avg - 1.0) * 100.0) if avg else 0.0

    stop, stop_basis = _protective_stop(price, lv)
    risk_pct = ((price - stop) / price * 100.0) if (stop and price) else None

    action_reco = plan.get("action")            # BUY | WAIT | AVOID from the engine
    chase = plan.get("chase", "ok")
    weekly = lv.get("weekly_trend")
    phase = lv.get("phase")
    distribution = bool(lv.get("distribution_warning"))
    vah = lv.get("val") and lv.get("vah")
    extended = (chase == "do_not_chase") or (lv.get("vah") is not None and price > lv["vah"] * 1.12)
    in_profit = pl_pct > 0
    below_stop = stop is not None and price < stop
    downtrend = action_reco == "AVOID" or weekly == "down"

    # target: the plan's TP1 if it's a live buy, else the nearest overhead level
    target = plan.get("tp1")
    if target is None:
        res = [r for r in (lv.get("resistances") or []) if r and r > price]
        target = min(res) if res else None

    # ---- Decide the action --------------------------------------------------
    if below_stop or (downtrend and not in_profit):
        action = "EXIT"
        reason = ("Price has lost its structural support and/or the trend has turned down. "
                  "Protect capital — this position no longer has a healthy setup.")
    elif distribution or (extended and in_profit and pl_pct >= 8):
        action = "TRIM"
        reason = ("Take partial profit and trail your stop up. " +
                  ("Distribution/supply is showing near the highs." if distribution
                   else "The move is extended above value — lock some in, let a runner ride."))
    elif action_reco == "BUY" and chase == "ok":
        action = "ADD"
        reason = ("The thesis is intact and price is in a buy zone. You may add, as long as "
                  "total position risk stays within your limit.")
    else:
        action = "HOLD"
        reason = (f"Trend intact and above support — hold. Raise your stop toward {stop} "
                  "to protect the position.")

    return {
        "symbol": sym, "company": holding.get("company") or sym,
        "qty": qty, "avg_cost": round(avg, 4), "current_price": round(price, 4),
        "currency": lv.get("currency") or "EGP",
        "market_value": round(mv, 2), "cost_basis": round(cost, 2),
        "unrealized_pl": round(pl, 2), "unrealized_pl_pct": round(pl_pct, 2),
        "weight_pct": round(weight_pct, 1) if weight_pct is not None else None,
        "phase": phase, "phase_label": lv.get("phase_label"),
        "weekly_trend": weekly, "distribution_warning": distribution,
        "plan_action": action_reco, "extended": bool(extended),
        "suggested_stop": stop, "stop_basis": stop_basis,
        "risk_to_stop_pct": round(risk_pct, 2) if risk_pct is not None else None,
        "target": round(target, 4) if target is not None else None,
        "action": action, "action_reason": reason,
    }


def analyze_portfolio(holdings: list[dict], *, objective: Objective = Objective.SWING,
                      analyze=None) -> dict:
    """Analyze a whole wallet. `analyze` is injectable for tests:
    callable(symbol, objective) -> analysis result dict (like analyze_symbol)."""
    if analyze is None:
        from .. import service as _svc

        def analyze(sym, obj):
            return _svc.analyze_symbol(sym, obj)

    rows, errors = [], []
    for h in holdings:
        sym = str(h.get("symbol", "")).strip().upper()
        if not sym or not h.get("qty"):
            continue
        try:
            res = analyze(sym, objective)
            rows.append((h, res.get("plan", {})))
        except Exception as e:
            errors.append({"symbol": sym, "error": str(e)})

    # first pass: market values for weights
    provisional = []
    for h, plan in rows:
        price = plan.get("current_price") or float(h.get("avg_cost") or 0)
        provisional.append(float(h.get("qty") or 0) * float(price or 0))
    total_value = sum(provisional) or 1.0

    positions = []
    for (h, plan), mv in zip(rows, provisional):
        positions.append(analyze_position(h, plan, weight_pct=mv / total_value * 100.0))

    total_cost = sum(p["cost_basis"] for p in positions)
    total_pl = sum(p["unrealized_pl"] for p in positions)
    tv = sum(p["market_value"] for p in positions)

    # concentration warning
    warnings = []
    for p in positions:
        if p["weight_pct"] and p["weight_pct"] > 25:
            warnings.append(f"{p['symbol']} is {p['weight_pct']}% of the book — concentrated; "
                            "consider trimming to manage single-name risk.")

    order = {"EXIT": 0, "TRIM": 1, "ADD": 2, "HOLD": 3}
    positions.sort(key=lambda p: (order.get(p["action"], 9), -(p["weight_pct"] or 0)))

    summary = {
        "positions": len(positions),
        "total_value": round(tv, 2), "total_cost": round(total_cost, 2),
        "total_unrealized_pl": round(total_pl, 2),
        "total_unrealized_pl_pct": round((total_pl / total_cost * 100.0) if total_cost else 0.0, 2),
        "winners": sum(1 for p in positions if p["unrealized_pl"] > 0),
        "losers": sum(1 for p in positions if p["unrealized_pl"] < 0),
        "actions": {a: sum(1 for p in positions if p["action"] == a)
                    for a in ("EXIT", "TRIM", "ADD", "HOLD")},
    }
    return {
        "objective": objective.value,
        "summary": summary, "warnings": warnings, "positions": positions, "errors": errors,
        "note": "Rule-based position management from daily structure. Not financial advice — "
                "you decide your sizing and risk.",
    }
