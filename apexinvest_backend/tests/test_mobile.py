"""Mobile web layer (api/mobile.py) — hermetic tests.

Guarantees:
  * CSV import feeds the SAME engine path as the live-feed analysis: the result equals
    analyze_symbol() run directly on the same candles (engine sections identical).
  * A newest-first file is re-oriented, an invalid file is rejected with a reason, nothing is invented.
  * The mobile app is served at /m, the desktop UI at / and /app is untouched, and the
    access-key gate still protects the new /v1 route while the static shell stays open.
"""
import io

import pandas as pd
from fastapi.testclient import TestClient

from apexinvest.api.main import app
from apexinvest.domain import Objective
from apexinvest.market import yahoo_egx
from apexinvest.service import analyze_symbol

client = TestClient(app)


def _series(n=140, start=100.0, step=1.004):
    rows, p = [], start
    for _ in range(n):
        p *= step
        rows.append((round(p * 0.999, 2), round(p * 1.006, 2), round(p * 0.994, 2), round(p, 2), 1_000_000.0))
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])


def _csv(df, time_col=True, descending=False):
    d = df.copy()
    if time_col:
        d.insert(0, "time", [1_700_000_000 + i * 86400 for i in range(len(d))])
    d = d.rename(columns={"volume": "Volume"})
    if descending:
        d = d.iloc[::-1]
    return d.to_csv(index=False).encode()


def _post(content, symbol="TEST", objective="swing", name="EGX_TEST, 1D.csv"):
    return client.post("/v1/analyses/csv", files={"file": (name, io.BytesIO(content), "text/csv")},
                       data={"symbol": symbol, "objective": objective})


def _engine(df, objective="swing"):
    def fetcher(_s):
        return df, {"symbol": "TEST", "currency": "EGP", "timeframe": "1d", "bars": len(df),
                    "last_close": float(df["close"].iloc[-1]), "as_of": None, "source": "t",
                    "provides": list(yahoo_egx.PROVIDES)}
    r = analyze_symbol("TEST", Objective(objective), fetcher=fetcher)
    r.pop("candles", None); r.pop("data_source", None)
    return r


def test_csv_result_equals_engine_direct():
    df = _series()
    for obj in ("swing", "long_term", "income", "analyze", "day"):
        r = _post(_csv(df), objective=obj)
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("candles", "data_source", "csv_import"):
            body.pop(k)
        assert body == _engine(df, obj)


def test_csv_newest_first_is_reoriented():
    df = _series()
    asc = _post(_csv(df)).json()
    desc = _post(_csv(df, descending=True)).json()
    assert desc["csv_import"]["order"].startswith("reversed")
    assert desc["plan"] == asc["plan"] and desc["signals"] == asc["signals"]


def test_csv_relabels_data_source():
    ds = _post(_csv(_series())).json()["data_source"]
    assert "Yahoo" not in ds["provider"] and ds["is_live"] is False


def test_csv_without_ohlc_is_rejected_with_reason():
    r = _post(b"name,value\nfoo,1\nbar,2\n")
    assert r.status_code == 422 and "Open/High/Low/Close" in r.json()["detail"]


def test_csv_bad_symbol_and_unreadable_file():
    assert _post(_csv(_series()), symbol="bad symbol!").status_code == 422
    assert _post(b"", name="x.csv").status_code == 422


def test_csv_short_history_is_wait_not_invented():
    r = _post(_csv(_series(20)))
    assert r.status_code == 200 and r.json()["plan"]["action"] == "WAIT"


def test_mobile_app_served_and_desktop_untouched():
    r = client.get("/m/")
    assert r.status_code == 200 and "ApexInvest" in r.text
    assert client.get("/m/manifest.webmanifest").status_code == 200
    assert client.get("/m/sw.js").status_code == 200
    assert client.get("/m/../frontend_app.html").status_code in (404, 400)
    assert client.get("/m/apexinvest/service.py").status_code == 404      # only mobile/ is exposed
    d = client.get("/")
    assert d.status_code == 200 and len(d.text) > 100_000                   # desktop bundle still served
    assert client.get("/app").status_code == 200


def test_access_gate_protects_csv_route_but_not_static_shell(monkeypatch):
    monkeypatch.setenv("APEX_ACCESS_KEYS", "ahmed:K1")
    assert client.get("/m/").status_code == 200
    assert _post(_csv(_series())).status_code == 401
    r = client.post("/v1/analyses/csv", files={"file": ("a.csv", io.BytesIO(_csv(_series())), "text/csv")},
                    data={"symbol": "T", "objective": "swing"}, headers={"X-Apex-Key": "K1"})
    assert r.status_code == 200
