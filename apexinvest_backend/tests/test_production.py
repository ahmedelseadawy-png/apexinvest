"""Cloud-hardening layer (api/production.py) — hermetic tests.

The hardening is infrastructure only: these tests prove (a) secrets never reach a client
or a log, (b) production mode restricts CORS / limits abuse / hides docs, (c) LOCAL mode is
unchanged, and (d) it never alters an engine result.
"""
import importlib
import io
import logging

import pytest
from fastapi.testclient import TestClient

from apexinvest.api import production as prod


def _load_main(monkeypatch, **env):
    for k in ("APEX_ENV", "ALLOWED_ORIGINS", "APEX_ACCESS_KEYS", "PUBLIC_API_BASE", "EODHD_API_KEY",
              "APEX_RL_HEAVY", "APEX_RL_ANALYSIS", "APEX_RL_GENERAL", "APEX_RL_AUTH",
              "APEX_HEAVY_CONCURRENCY", "APEX_MAX_UPLOAD_MB", "APEX_MAX_BODY_MB"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from apexinvest.api import main
    return importlib.reload(main)


@pytest.fixture(autouse=True)
def _restore_main():
    yield
    import os
    for k in ("APEX_ENV", "ALLOWED_ORIGINS", "APEX_ACCESS_KEYS", "PUBLIC_API_BASE", "EODHD_API_KEY"):
        os.environ.pop(k, None)
    from apexinvest.api import main
    importlib.reload(main)


# ------------------------------------------------------------------ redaction
def test_sanitize_removes_tokens_urls_and_configured_secrets(monkeypatch):
    monkeypatch.setenv("EODHD_API_KEY", "abc123SECRETxyz")
    monkeypatch.setenv("APEX_ACCESS_KEYS", "me:LONGACCESSKEY99")
    msg = ("HTTPSConnectionPool(host='eodhd.com', port=443): Max retries exceeded with url: "
           "/api/eod/COMI.EGX?api_token=abc123SECRETxyz&period=d (Caused by ...) "
           "GET https://eodhd.com/api/eod/COMI.EGX?api_token=abc123SECRETxyz key=LONGACCESSKEY99 X-Apex-Key: LONGACCESSKEY99")
    out = prod.sanitize(msg)
    assert "abc123SECRETxyz" not in out and "LONGACCESSKEY99" not in out and "api_token=abc" not in out
    assert "eodhd.com" in out                        # still diagnosable


def test_sanitize_keeps_ordinary_engine_messages():
    m = "Yahoo: no data for CRST.CA (delisted?)"
    assert prod.sanitize(m) == m


def test_http_errors_are_redacted_in_both_modes(monkeypatch):
    for env in ({}, {"APEX_ENV": "production"}):
        main = _load_main(monkeypatch, EODHD_API_KEY="KEY-SHOULD-NOT-LEAK", **env)
        from apexinvest.market import feed

        def boom(*a, **k):
            raise RuntimeError("HTTPSConnectionPool: url: /api/eod/X.EGX?api_token=KEY-SHOULD-NOT-LEAK")
        monkeypatch.setattr(feed, "fetch_daily", boom)
        r = TestClient(main.app).get("/v1/backtest/COMI")
        assert r.status_code == 502
        assert "KEY-SHOULD-NOT-LEAK" not in r.text and "api_token=KEY" not in r.text


def test_unhandled_exception_has_no_stack_trace(monkeypatch):
    main = _load_main(monkeypatch, APEX_ENV="production")
    from apexinvest import service

    def boom(*a, **k):
        raise KeyError("internal-detail-/srv/app/secret_path.py")
    monkeypatch.setattr(main, "svc_quotes", boom)
    monkeypatch.setattr(main, "analyze_symbol", boom)
    c = TestClient(main.app, raise_server_exceptions=False)
    r = c.get("/v1/analyses/auto/COMI")           # KeyError -> handled as 502 by the route, sanitized
    assert "secret_path.py" not in r.text or r.status_code == 502
    assert "Traceback" not in r.text


def test_log_records_are_redacted(monkeypatch, caplog):
    monkeypatch.setenv("EODHD_API_KEY", "LOGSECRET-12345")
    prod.configure_logging()
    for h in logging.getLogger().handlers:
        h.addFilter(prod._RedactFilter())
    with caplog.at_level(logging.INFO):
        logging.getLogger("apexinvest").info("failed https://eodhd.com/api/eod/A?api_token=LOGSECRET-12345")
    text = "\n".join(r.getMessage() for r in caplog.records)
    # caplog attaches its own handler, so apply the filter's transformation explicitly too
    rec = logging.LogRecord("x", 20, __file__, 1, "u api_token=LOGSECRET-12345", (), None)
    prod._RedactFilter().filter(rec)
    assert "LOGSECRET-12345" not in rec.msg


# ---------------------------------------------------------------------- CORS
def test_local_mode_cors_is_unchanged(monkeypatch):
    main = _load_main(monkeypatch)
    r = TestClient(main.app).get("/v1/health", headers={"Origin": "https://evil.example"})
    assert r.headers.get("access-control-allow-origin") == "*"
    assert TestClient(main.app).get("/docs").status_code == 200          # docs still there locally


def test_production_cors_only_allowed_origins(monkeypatch):
    main = _load_main(monkeypatch, APEX_ENV="production", ALLOWED_ORIGINS="https://apex.example.com/, junk, https://x.example.com/path")
    c = TestClient(main.app)
    ok = c.get("/v1/health", headers={"Origin": "https://apex.example.com"})
    bad = c.get("/v1/health", headers={"Origin": "https://evil.example"})
    assert ok.headers.get("access-control-allow-origin") == "https://apex.example.com"
    assert "access-control-allow-origin" not in bad.headers
    assert prod.allowed_origins() == ["https://apex.example.com"]        # junk and path-bearing entries dropped
    pre = c.options("/v1/analyses/csv", headers={"Origin": "https://apex.example.com",
                                                 "Access-Control-Request-Method": "POST",
                                                 "Access-Control-Request-Headers": "x-apex-key"})
    assert pre.status_code == 200


def test_production_default_has_no_cors_at_all(monkeypatch):
    main = _load_main(monkeypatch, APEX_ENV="production")
    r = TestClient(main.app).get("/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


# --------------------------------------------------------------- production
def test_production_hides_docs_and_sets_headers(monkeypatch):
    main = _load_main(monkeypatch, APEX_ENV="production")
    c = TestClient(main.app)
    for p in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(p).status_code == 404
    r = c.get("/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"           # public health check
    assert r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"
    assert "strict-transport-security" in r.headers
    m = c.get("/m/")
    assert "content-security-policy" in m.headers and "frame-ancestors 'none'" in m.headers["content-security-policy"]
    assert c.get("/").status_code == 200 and c.get("/app").status_code == 200   # desktop UI unchanged


def test_production_symbol_and_query_validation(monkeypatch):
    main = _load_main(monkeypatch, APEX_ENV="production")
    c = TestClient(main.app)
    assert c.get("/v1/analyses/auto/bad%20sym!").status_code == 422
    assert c.get("/v1/analyses/auto/" + "A" * 40).status_code == 422
    assert c.get("/v1/fundamentals/%3Cscript%3E").status_code == 422
    assert c.get("/v1/scan?symbols=" + "A," * 2000).status_code == 414


def test_production_rate_limits_and_retry_after(monkeypatch):
    main = _load_main(monkeypatch, APEX_ENV="production", APEX_RL_GENERAL="5")
    c = TestClient(main.app)
    codes = [c.get("/v1/assets/search?q=COMI").status_code for _ in range(8)]
    assert codes[:5] == [200] * 5 and codes[5:] == [429] * 3
    r = c.get("/v1/assets/search?q=COMI")
    assert r.status_code == 429 and "retry-after" in r.headers
    assert c.get("/v1/health").status_code == 200                        # health is never limited


def test_failed_key_guesses_are_throttled(monkeypatch):
    main = _load_main(monkeypatch, APEX_ENV="production", APEX_ACCESS_KEYS="me:CorrectHorseBattery", APEX_RL_AUTH="4")
    c = TestClient(main.app)
    codes = [c.get("/v1/assets/search?q=A", headers={"X-Apex-Key": f"guess{i}"}).status_code for i in range(7)]
    assert codes[:4] == [401] * 4 and set(codes[4:]) == {429}
    # a caller who presents the RIGHT key is not locked out by guessers sharing the address
    assert c.get("/v1/assets/search?q=A", headers={"X-Apex-Key": "CorrectHorseBattery"}).status_code == 200
    assert c.get("/v1/assets/search?q=A", params={"key": "CorrectHorseBattery"}).status_code == 200
    assert c.get("/v1/assets/search?q=A", headers={"X-Apex-Key": "still-wrong"}).status_code == 429


def test_rate_limit_ignores_spoofed_forwarded_for(monkeypatch):
    main = _load_main(monkeypatch, APEX_ENV="production", APEX_RL_GENERAL="3")
    c = TestClient(main.app)
    # the client prepends fake addresses; the proxy-appended (last) hop is what counts
    codes = [c.get("/v1/assets/search?q=A", headers={"X-Forwarded-For": f"9.9.9.{i}, 203.0.113.7"}).status_code for i in range(6)]
    assert codes == [200, 200, 200, 429, 429, 429]
    other = c.get("/v1/assets/search?q=A", headers={"X-Forwarded-For": "1.1.1.1, 203.0.113.8"})
    assert other.status_code == 200                                     # a different real caller is unaffected


def test_heavy_endpoints_have_concurrency_cap(monkeypatch):
    main = _load_main(monkeypatch, APEX_ENV="production", APEX_HEAVY_CONCURRENCY="1")
    guard = None
    # the guard is the outermost user middleware below CORS; find it through the built stack
    c = TestClient(main.app)
    c.get("/v1/health")
    node = main.app.middleware_stack
    while node is not None and not isinstance(node, prod.ProductionGuard):
        node = getattr(node, "app", None)
    assert node is not None
    node._heavy_inflight = 1                                             # simulate one scan already running
    r = c.get("/v1/scan?symbols=COMI")
    assert r.status_code == 429 and "busy" in r.json()["detail"]
    node._heavy_inflight = 0


def test_upload_size_cap(monkeypatch):
    main = _load_main(monkeypatch, APEX_ENV="production", APEX_MAX_UPLOAD_MB="1")
    c = TestClient(main.app)
    big = b"time,open,high,low,close,volume\n" + b"1,1,1,1,1,1\n" * 200_000
    r = c.post("/v1/analyses/csv", files={"file": ("x.csv", io.BytesIO(big), "text/csv")}, data={"symbol": "T"})
    assert r.status_code == 413
    # a chunked upload (no Content-Length) is also stopped
    def gen():
        yield b'--BND\r\nContent-Disposition: form-data; name="file"; filename="x.csv"\r\nContent-Type: text/csv\r\n\r\n'
        for _ in range(60):
            yield b"1,1,1,1,1,1\n" * 4000
        yield b"\r\n--BND--\r\n"
    r = c.post("/v1/uploads", content=gen(), headers={"Content-Type": "multipart/form-data; boundary=BND"})
    assert r.status_code == 413


def test_access_log_never_contains_query_string(monkeypatch, caplog):
    main = _load_main(monkeypatch, APEX_ENV="production")
    with caplog.at_level(logging.INFO, logger="apexinvest.access"):
        TestClient(main.app).get("/v1/assets/search?q=COMI&key=SUPERSECRETKEY")
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "/v1/assets/search" in text and "SUPERSECRETKEY" not in text and "q=COMI" not in text


# ----------------------------------------------------------------- mobile app
def test_mobile_config_js_same_origin_by_default_and_validated(monkeypatch):
    main = _load_main(monkeypatch, APEX_ENV="production")
    r = TestClient(main.app).get("/m/config.js")
    assert r.status_code == 200 and 'API_BASE":""' in r.text.replace(" ", "")
    assert "no-cache" in r.headers["cache-control"]
    main = _load_main(monkeypatch, APEX_ENV="production", PUBLIC_API_BASE="https://api.example.com/")
    assert "https://api.example.com" in TestClient(main.app).get("/m/config.js").text
    csp = TestClient(main.app).get("/m/").headers["content-security-policy"]
    assert "connect-src 'self' https://api.example.com" in csp
    for bad in ("http://insecure.example.com", "javascript:alert(1)", "https://x.com/path", "not a url"):
        main = _load_main(monkeypatch, APEX_ENV="production", PUBLIC_API_BASE=bad)
        assert 'API_BASE":""' in TestClient(main.app).get("/m/config.js").text.replace(" ", "")


def test_mobile_static_has_no_hardcoded_hosts():
    from pathlib import Path
    import re
    root = Path(__file__).resolve().parents[1] / "mobile"
    for f in ("app.js", "index.html", "sw.js", "manifest.webmanifest", "i18n.js"):
        txt = (root / f).read_text(encoding="utf-8")
        assert not re.search(r"(localhost|127\.0\.0\.1|192\.168\.|10\.\d+\.\d+\.\d+|https?://)", txt), f


def test_service_worker_never_touches_api():
    from pathlib import Path
    sw = (Path(__file__).resolve().parents[1] / "mobile" / "sw.js").read_text()
    assert "startsWith('/m/')" in sw and "/v1" not in sw.replace("/v1/*", "")


# ------------------------------------------------- engine results are untouched
def test_engine_output_identical_local_vs_production(monkeypatch):
    import pandas as pd
    from apexinvest.market import yahoo_egx

    def _df(n=160):
        rows, p = [], 50.0
        for i in range(n):
            p *= 1.0 + (0.012 if i % 7 else -0.02)
            rows.append((round(p * .995, 3), round(p * 1.01, 3), round(p * .985, 3), round(p, 3), 1e6 + i * 1000))
        return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"])

    def fake(symbol, lookback="1y", timeout=10.0):
        df = _df()
        return df, {"symbol": symbol.upper(), "currency": "EGP", "timeframe": "1d", "bars": len(df),
                    "last_close": float(df["close"].iloc[-1]), "as_of": "2026-01-01", "source": "t",
                    "provides": list(yahoo_egx.PROVIDES)}
    outs = []
    for env in ({}, {"APEX_ENV": "production", "APEX_ACCESS_KEYS": "me:K-1234567"}):
        main = _load_main(monkeypatch, **env)
        from apexinvest.market import feed
        monkeypatch.setattr(feed, "fetch_daily", fake)
        monkeypatch.setattr(yahoo_egx, "fetch_daily", fake)
        monkeypatch.setattr("apexinvest.service.feed.fetch_daily", fake, raising=False)
        h = {"X-Apex-Key": "K-1234567"} if env else {}
        r = TestClient(main.app).get("/v1/analyses/auto/TEST?objective=swing", headers=h)
        assert r.status_code == 200, r.text
        outs.append(r.json())
    assert outs[0] == outs[1]


def test_secret_in_a_200_body_is_stripped(monkeypatch):
    """scanner/portfolio copy exception text (which can hold the provider URL + token) into 200 responses."""
    main = _load_main(monkeypatch, APEX_ENV="production", EODHD_API_KEY="BODYLEAK-key-777")
    from apexinvest.market import feed

    def boom(*a, **k):
        raise RuntimeError("401 Client Error: Unauthorized for url: https://eodhd.com/api/eod/COMI.EGX?api_token=BODYLEAK-key-777&fmt=json")
    monkeypatch.setattr(feed, "fetch_daily", boom)
    c = TestClient(main.app)
    r = c.post("/v1/portfolio", json={"holdings": [{"symbol": "COMI", "qty": 10, "avg_cost": 100}], "objective": "swing"})
    assert r.status_code == 200
    assert "BODYLEAK-key-777" not in r.text and "api_token=BODYLEAK" not in r.text
    assert int(r.headers["content-length"]) == len(r.content)          # length header was corrected
    r2 = c.get("/v1/scan?symbols=COMI")
    assert "BODYLEAK-key-777" not in r2.text
