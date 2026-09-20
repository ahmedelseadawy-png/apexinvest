"""Tests for the EGX Opportunity Scanner (Update #3).

The defining guarantee: the scanner ranks by trade QUALITY, not raw upside. A
clean, tight, high-probability 7% setup must outrank an extended, weak, wide
18% setup. It must also refuse to force trades (NO TRADE is valid) and filter
weak reward-to-risk.
"""
import numpy as np
import pandas as pd

from apexinvest.engines import scanner


def _candles(last=10.0, n=160, drift=0.003):
    b = last / (1 + drift) ** n * np.cumprod(1 + np.full(n, drift))
    return [{"o": float(x), "h": float(x * 1.02), "l": float(x * 0.98),
             "c": float(x), "v": 3e5} for x in b]


def _plan(action="BUY", entry=9.5, stop=9.0, tp1=10.5, tp2=11.0, rr=2.0, exp=10.0,
          conf=4, chase="ok", etype="retest", pocc="high", sq=0.7):
    return {"action": action, "entry": entry, "stop": stop, "tp1": tp1, "tp2": tp2,
            "rr": rr, "expected_return_pct": exp, "current_price": entry * 1.01,
            "optimal_zone": [entry * 0.99, entry * 1.005], "entry_type": etype,
            "confirmation_entry": None, "est_tp1": "3-5 sessions", "est_tp2": "1-2 weeks",
            "chase": chase, "confidence": {"score": conf},
            "entry_levels": {"poc_confidence": pocc, "setup_quality": sq,
                             "phase": "reclaim", "distribution_warning": False}}


DB = {
    "AAA": _plan(rr=2.6, exp=9, conf=5, pocc="high", sq=0.8),
    "BBB": _plan(rr=1.9, exp=18, conf=3, pocc="low", sq=0.4, chase="do_not_chase"),
    "CCC": _plan(rr=2.2, exp=7, conf=4, pocc="high", sq=0.75, etype="confirmation"),
    "DDD": _plan(action="WAIT"),
    "EEE": _plan(rr=1.5, exp=6, conf=3, pocc="medium", sq=0.5),
}


def _fake_analyze(sym, obj, live_price=False):
    return {"plan": DB[sym], "candles": _candles()}


def _scan(**kw):
    return scanner.scan(list(DB), names={s: s + " Co" for s in DB},
                        analyze=_fake_analyze, use_cache=False, **kw)


def test_quality_beats_raw_upside():
    res = _scan()
    order = [r["symbol"] for r in res["top_overall"]]
    assert order[0] == "AAA"                     # clean 9% beats extended 18%
    assert order.index("AAA") < order.index("BBB")


def test_no_trade_is_counted_and_weak_rr_filtered():
    res = _scan()
    assert res["scanned"] == 5
    syms = {r["symbol"] for r in res["top_overall"]}
    assert "DDD" not in syms                      # WAIT
    assert "EEE" not in syms                      # rr 1.5 < min
    assert res["no_trade"] >= 2


def test_three_rankings_and_picks_present():
    res = _scan()
    for k in ("top_overall", "top_fast", "top_risk_adjusted"):
        assert res[k]
    assert set(res["picks"]) <= {"overall", "fast", "risk_adjusted"}
    assert res["picks"]["overall"]["symbol"] == "AAA"


def test_confirmation_fast_setup_leads_fast_ranking():
    res = _scan()
    assert res["picks"]["fast"]["symbol"] == "CCC"


def test_conservative_risk_is_stricter_than_aggressive():
    con = _scan(risk="conservative")["valid_setups"]
    agg = _scan(risk="aggressive")["valid_setups"]
    assert con <= agg


def test_market_regime_and_rows_have_required_fields():
    res = _scan()
    assert res["market"]["regime"] in ("Bullish", "Neutral", "Bearish", "High risk / volatile")
    row = res["top_overall"][0]
    for k in ("symbol", "company", "current_price", "optimal_zone", "entry", "stop",
              "tp1", "tp2", "expected_return_pct", "rr", "est_tp1", "opportunity_score",
              "risk_level", "model_prob", "ev_pct", "chase"):
        assert k in row


def test_headline_picks_are_distinct():
    # With several valid setups, the three headline cards (overall / fast /
    # risk-adjusted) must be three DIFFERENT stocks, not the same name repeated.
    res = _scan()
    picks = res["picks"]
    syms = [picks[k]["symbol"] for k in ("overall", "fast", "risk_adjusted") if picks.get(k)]
    assert len(syms) == 3
    assert len(set(syms)) == 3, f"picks should be distinct, got {syms}"


def test_coverage_reports_requested_and_unreached_symbols():
    # Honest coverage: a symbol whose data we can't reach is REPORTED as
    # unreached (with which symbol + a reason), never silently dropped. The
    # denominator (`requested`) always accounts for every symbol asked for:
    # requested == scanned + unreached.
    def analyze_with_a_gap(sym, obj, live_price=False):
        if sym == "BBB":
            raise DB_ERR  # simulate "no data reachable" for one name
        return {"plan": DB[sym], "candles": _candles()}

    res = scanner.scan(list(DB), names={s: s + " Co" for s in DB},
                       analyze=analyze_with_a_gap, use_cache=False)
    assert res["requested"] == len(DB)
    assert res["errors"] == 1
    assert res["requested"] == res["scanned"] + len(res["unreached"])
    gap = {u["symbol"] for u in res["unreached"]}
    assert gap == {"BBB"}
    assert res["unreached"][0]["reason"] in ("no_data", "timeout", "rate_limited", "error")
    assert res["unreached"][0]["company"] == "BBB Co"


DB_ERR = __import__("apexinvest.market.yahoo_egx", fromlist=["DataUnavailable"]).DataUnavailable("no data returned")
