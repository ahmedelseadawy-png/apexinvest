"""Watch-list scan mode.

`/v1/scan?symbols=...` runs the SAME opportunity-scanner engine but restricted to
the requested EGX symbols (the "My Watch List" view). Two guarantees are tested:
  * only the requested symbols are scanned (and case is normalised), and
  * a symbol that is not a real EGX ticker in our catalog is silently dropped —
    never scanned — which is the anti-fabrication rule applied to the universe.
With no `symbols`, the endpoint scans the whole equity board as before.
"""
from fastapi.testclient import TestClient

from apexinvest.api.main import app
from apexinvest.engines import scanner

client = TestClient(app)


def _capture(monkeypatch):
    """Replace the heavy/network scan() with a stub that records the universe."""
    seen = {}

    def fake_scan(symbols, **kw):
        seen["symbols"] = list(symbols)
        seen["kw"] = kw
        return {"scanned": len(symbols), "top_overall": [], "picks": {},
                "valid_setups": 0, "no_trade": len(symbols), "counts": {},
                "market": {"regime": "TEST", "strength": 0}, "as_of": "2026-01-01"}

    monkeypatch.setattr(scanner, "scan", fake_scan)
    return seen


def test_watchlist_scans_only_requested_symbols(monkeypatch):
    seen = _capture(monkeypatch)
    r = client.get("/v1/scan", params={"symbols": "COMI,SWDY,ETEL"})
    assert r.status_code == 200
    assert seen["symbols"] == ["COMI", "SWDY", "ETEL"]


def test_watchlist_normalises_case_and_drops_unknown(monkeypatch):
    seen = _capture(monkeypatch)
    r = client.get("/v1/scan", params={"symbols": "comi, ZZZZ_NOT_REAL ,swdy"})
    assert r.status_code == 200
    # unknown ticker dropped (never fabricated), real ones kept & upper-cased
    assert seen["symbols"] == ["COMI", "SWDY"]


def test_empty_symbols_falls_back_to_full_universe(monkeypatch):
    seen = _capture(monkeypatch)
    r = client.get("/v1/scan")
    assert r.status_code == 200
    assert len(seen["symbols"]) > 100   # whole EGX equity board, not a short list


def test_watchlist_forwards_horizon_and_risk(monkeypatch):
    seen = _capture(monkeypatch)
    r = client.get("/v1/scan", params={"symbols": "COMI", "horizon": "long_term",
                                       "risk": "aggressive"})
    assert r.status_code == 200
    assert seen["kw"].get("horizon") == "long_term"
    assert seen["kw"].get("risk") == "aggressive"
