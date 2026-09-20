"""Auto-analysis-from-feed tests (offline).

The market adapter is exercised without any network by (a) parsing a synthetic
Yahoo payload and (b) injecting a fake fetcher into analyze_symbol. This keeps
CI hermetic while proving the R:R math is built automatically from candles.
"""
import pandas as pd

from apexinvest.domain import Objective
from apexinvest.market import yahoo_egx
from apexinvest.service import analyze_symbol


def _uptrend(n=140, start=100.0, step=1.004):
    rows, p = [], start
    for _ in range(n):
        p *= step
        rows.append((p * 0.999, p * 1.006, p * 0.994, p, 1_000_000.0))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])


def _flat(n=140, price=100.0):
    rows = []
    for i in range(n):
        c = price + (0.3 if i % 2 else -0.3)   # tiny chop, no trend
        rows.append((price, c + 0.4, c - 0.4, c, 1_000_000.0))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])


def _fetcher(df, symbol="TEST"):
    def fetch(_sym):
        meta = {"symbol": symbol, "currency": "EGP", "timeframe": "1d",
                "bars": len(df), "last_close": float(df["close"].iloc[-1]),
                "source": "test", "provides": list(yahoo_egx.PROVIDES)}
        return df, meta
    return fetch


# ---- adapter parsing -------------------------------------------------------

def test_parse_chart_skips_gaps_and_reads_meta():
    payload = {"chart": {"error": None, "result": [{
        "meta": {"currency": "EGP", "exchangeName": "EGX"},
        "timestamp": [1, 2, 3, 4],
        "indicators": {"quote": [{
            "open": [10, None, 11, 12], "high": [10.5, None, 11.5, 12.5],
            "low": [9.5, None, 10.5, 11.5], "close": [10.2, None, 11.2, 12.2],
            "volume": [100, None, 200, 300],
        }]},
    }]}}
    df, meta = yahoo_egx._parse_chart(payload, "COMI")
    assert len(df) == 3                     # the null bar is dropped, not invented
    assert meta["currency"] == "EGP" and meta["timeframe"] == "1d"
    assert meta["provides"] == ["daily_chart", "volume", "volume_profile"]


def test_parse_chart_no_data_raises():
    import pytest
    with pytest.raises(yahoo_egx.DataUnavailable):
        yahoo_egx._parse_chart({"chart": {"result": []}}, "XXXX")


def test_yahoo_404_is_no_data_not_a_server_error(monkeypatch):
    # A symbol Yahoo doesn't carry (e.g. VLMR small cap) returns HTTP 404. That
    # must surface as DataUnavailable ("no free data for this stock"), so the API
    # returns a clean 404 the UI shows honestly — NOT a raw HTTPError/502 that the
    # UI would mislabel as "backend offline".
    import pytest

    class _Resp:
        status_code = 404
        def raise_for_status(self):
            raise AssertionError("should short-circuit on 404 before raise_for_status")
        def json(self):
            raise AssertionError("should not parse a 404 body")

    monkeypatch.setattr(yahoo_egx, "requests", type("R", (), {"get": staticmethod(lambda *a, **k: _Resp())}))
    with pytest.raises(yahoo_egx.DataUnavailable):
        yahoo_egx.fetch_daily("VLMR")


# ---- auto analysis --------------------------------------------------------

def test_auto_swing_uptrend_builds_rr_automatically():
    out = analyze_symbol("TEST", Objective.SWING, fetcher=_fetcher(_uptrend()))
    plan = out["plan"]
    assert plan["action"] == "BUY"
    assert plan["stop"] < plan["entry"] < plan["target"]
    # R:R is really computed, not asserted blindly
    rr = round((plan["target"] - plan["entry"]) / (plan["entry"] - plan["stop"]), 2)
    assert abs(rr - plan["rr"]) < 0.05
    # provenance + honest strategy accounting are attached
    assert out["data_source"]["source"] == "test"
    assert out["auto"]["used"] and out["auto"]["feed_provides"] == sorted(yahoo_egx.PROVIDES)


def test_auto_sideways_waits_no_fabrication():
    out = analyze_symbol("TEST", Objective.SWING, fetcher=_fetcher(_flat()))
    assert out["plan"]["action"] == "WAIT"
    assert out["plan"]["entry"] is None      # never invents a level


def test_auto_day_objective_waits_for_intraday():
    out = analyze_symbol("TEST", Objective.DAY, fetcher=_fetcher(_uptrend()))
    assert out["plan"]["action"] == "WAIT"
    assert "intraday" in out["plan"]["reason"].lower()


def test_auto_insufficient_history_waits():
    out = analyze_symbol("TEST", Objective.SWING, fetcher=_fetcher(_uptrend(n=12)))
    assert out["plan"]["action"] == "WAIT"
    assert "bars" in out["plan"]["reason"].lower()
