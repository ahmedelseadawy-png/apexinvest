import io

import pandas as pd
from fastapi.testclient import TestClient

from apexinvest.api.main import app
from apexinvest.ingest import files as ingest

client = TestClient(app)


# ---- ingest --------------------------------------------------------------- #

def test_ingest_ohlcv_csv():
    df = pd.DataFrame({
        "Open": [10, 11], "High": [12, 13], "Low": [9, 10],
        "Close": [11, 12], "Volume": [1000, 1100],
    })
    data = df.to_csv(index=False).encode()
    res = ingest.ingest("prices.csv", data)
    assert res.ok and res.kind == "candles"
    assert res.candles is not None and len(res.candles) == 2


def test_ingest_financial_text_extracts_metrics():
    text = "Annual report. Revenue growth 18%. Net margin 22%. Debt-to-equity 0.4."
    res = ingest.ingest("report.txt", text.encode())
    assert res.ok
    assert res.fundamentals.get("revenue_growth") == 0.18
    assert res.fundamentals.get("net_margin") == 0.22
    assert res.fundamentals.get("debt_to_equity") == 0.4


def test_ingest_empty_rejected():
    res = ingest.ingest("x.csv", b"")
    assert not res.ok and "empty" in res.error.lower()


def test_ingest_oversize_rejected():
    big = b"x" * (ingest.MAX_BYTES + 1)
    res = ingest.ingest("big.csv", big)
    assert not res.ok and "limit" in res.error.lower()


def test_ingest_unsupported_type_rejected():
    res = ingest.ingest("evil.exe", b"MZ\x00\x00binary")
    assert not res.ok and "unsupported" in res.error.lower()


def test_ingest_does_not_fabricate_missing_metrics():
    res = ingest.ingest("notes.txt", b"Just some prose with no financial figures.")
    assert res.ok and res.fundamentals == {}   # nothing invented


# ---- API ------------------------------------------------------------------ #

def test_health():
    r = client.get("/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_asset_search():
    r = client.get("/v1/assets/search", params={"q": "app"})
    assert r.status_code == 200
    assert any(a["symbol"] == "AAPL" for a in r.json()["results"])


def _candle_payload(n=140, start=100.0, step=0.006):
    rows = []
    c = start
    for _ in range(n):
        o = c
        c = c * (1 + step)
        rows.append({"open": o, "high": max(o, c) * 1.008, "low": min(o, c) * 0.992,
                     "close": c, "volume": 1_000_000})
    return rows


def test_requirements_auto():
    r = client.post("/v1/analyses/requirements", json={
        "objective": "swing", "mode": "auto",
        "candles": {"1d": _candle_payload()},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "auto" and body["strategies"] and body["required_inputs"]


def test_analyze_end_to_end_buy():
    payload = {
        "objective": "swing", "mode": "manual",
        "manual_strategies": ["price_action", "momentum"],
        "candles": {"1d": _candle_payload()},
        "provided_inputs": ["daily_chart", "intraday_chart", "volume"],
    }
    r = client.post("/v1/analyses/analyze", json=payload)
    assert r.status_code == 200
    plan = r.json()["plan"]
    assert plan["action"] in ("BUY", "WAIT")
    if plan["action"] == "BUY":
        assert plan["stop"] < plan["entry"] < plan["target"]


def test_analyze_missing_data_wait():
    payload = {
        "objective": "swing", "mode": "manual",
        "manual_strategies": ["poc"],
        "candles": {"1d": _candle_payload()},
        "provided_inputs": ["daily_chart"],   # poc needs more
    }
    r = client.post("/v1/analyses/analyze", json=payload)
    assert r.status_code == 200
    assert r.json()["plan"]["action"] == "WAIT"


def test_analyze_invalid_strategy_422():
    r = client.post("/v1/analyses/analyze", json={
        "objective": "swing", "mode": "manual", "manual_strategies": ["nonsense"],
        "candles": {"1d": _candle_payload()},
    })
    assert r.status_code == 422


def test_upload_csv_endpoint():
    df = pd.DataFrame({"Open": [1, 2], "High": [2, 3], "Low": [1, 1], "Close": [2, 3], "Volume": [10, 20]})
    files = {"file": ("p.csv", io.BytesIO(df.to_csv(index=False).encode()), "text/csv")}
    r = client.post("/v1/uploads", files=files)
    assert r.status_code == 200 and r.json()["kind"] == "candles"


def test_upload_rejected_returns_422():
    files = {"file": ("evil.exe", io.BytesIO(b"binary"), "application/octet-stream")}
    r = client.post("/v1/uploads", files=files)
    assert r.status_code == 422
