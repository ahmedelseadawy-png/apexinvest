"""Tests for company fundamentals scoring and parsing.

Network is never touched here: we drive score_company() directly and feed
fetch_fundamentals() a mocked quoteSummary payload via a fake requests.Session,
so the parsing path is exercised without Yahoo.
"""
import types

from apexinvest.market import fundamentals as fun


# ---- score_company: pillar math & coverage -------------------------------

def test_score_none_when_no_data():
    r = fun.score_company({})
    assert r["score"] is None
    assert r["coverage"] == "none"


def test_score_full_coverage_high_quality():
    f = {
        "pe": 8, "price_to_book": 1.2,          # cheap value
        "roe": 0.30, "debt_to_equity": 30,       # high quality
        "revenue_growth": 0.20, "profit_margin": 0.25,  # strong growth
        "dividend_yield": 0.08,                   # full income
    }
    r = fun.score_company(f)
    assert r["coverage"] == "full"
    assert set(r["pillars"]) == {"value", "quality", "growth", "income"}
    assert r["score"] >= 90


def test_score_partial_excludes_missing_pillars():
    # Only value + quality present -> partial, income/growth absent.
    f = {"pe": 12, "price_to_book": 2.0, "roe": 0.15, "debt_to_equity": 80}
    r = fun.score_company(f)
    assert r["coverage"] == "partial"
    assert set(r["pillars"]) == {"value", "quality"}
    assert r["score"] is not None


def test_missing_field_not_treated_as_zero():
    # A company with only a dividend yield should not be dragged down by the
    # value/quality/growth pillars it has no data for.
    f = {"dividend_yield": 0.08}
    r = fun.score_company(f)
    assert r["pillars"] == {"income": 1.0}
    assert r["score"] == 100
    assert r["coverage"] == "thin"


def test_negative_pe_is_penalised_not_crashed():
    f = {"pe": -5, "price_to_book": 4}
    r = fun.score_company(f)
    assert r["pillars"]["value"] < 0.5


# ---- fetch_fundamentals: parsing via mocked session ----------------------

class _FakeResp:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


class _FakeSession:
    """Minimal stand-in for requests.Session covering the calls we make."""
    def __init__(self, payload):
        self._payload = payload
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        if "getcrumb" in url:
            return _FakeResp(text="fakecrumb")
        if "fc.yahoo.com" in url:
            return _FakeResp()
        return _FakeResp(payload=self._payload)


_SAMPLE = {
    "quoteSummary": {
        "result": [{
            "summaryDetail": {
                "marketCap": {"raw": 5.0e10},
                "trailingPE": {"raw": 9.5},
                "dividendYield": {"raw": 0.06},
            },
            "defaultKeyStatistics": {
                "forwardPE": {"raw": 7.8},
                "priceToBook": {"raw": 1.3},
                "trailingEps": {"raw": 4.2},
            },
            "financialData": {
                "returnOnEquity": {"raw": 0.28},
                "debtToEquity": {"raw": 40.0},
                "revenueGrowth": {"raw": 0.18},
                "profitMargins": {"raw": 0.22},
                "totalRevenue": {"raw": 3.0e10},
            },
            "price": {"longName": "Commercial International Bank", "currency": "EGP"},
            "summaryProfile": {"sector": "Financial Services", "industry": "Banks"},
            "calendarEvents": {"earnings": {"earningsDate": [{"raw": 1_760_000_000}]}},
        }]
    }
}


def test_fetch_parses_mocked_payload(monkeypatch):
    monkeypatch.setattr(fun.requests, "Session", lambda: _FakeSession(_SAMPLE))
    out = fun.fetch_fundamentals("COMI")
    assert out["available"] is True
    assert out["symbol"] == "COMI"
    assert out["name"] == "Commercial International Bank"
    assert out["sector"] == "Financial Services"
    assert abs(out["pe"] - 9.5) < 1e-9
    assert abs(out["roe"] - 0.28) < 1e-9
    assert out["market_cap"] == 5.0e10
    assert out["next_earnings"]  # formatted date string
    assert out["quality"]["coverage"] == "full"
    assert out["quality"]["score"] >= 80


def test_fetch_handles_empty_result(monkeypatch):
    monkeypatch.setattr(fun.requests, "Session",
                        lambda: _FakeSession({"quoteSummary": {"result": []}}))
    out = fun.fetch_fundamentals("NOPE")
    assert out["available"] is False
    assert "reason" in out
