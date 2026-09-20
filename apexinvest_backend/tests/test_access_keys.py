"""Per-person access-key gate.

Guarantees:
  * OFF by default (no env) — the API stays open, so local use is unchanged.
  * When APEX_ACCESS_KEYS is set, /v1/* data calls need a valid key (header or
    query), an invalid/missing key gets 401, and the health/auth endpoints stay
    open so the login screen can load.
  * /v1/auth/check validates a key and returns the person's name (for revoke,
    you just drop their line and redeploy).
"""
from fastapi.testclient import TestClient

from apexinvest.api.main import app, _access_keys

client = TestClient(app)


def test_parse_keys_name_and_bare(monkeypatch):
    monkeypatch.setenv("APEX_ACCESS_KEYS", "sherif:AB12, ahmed=EF34 , ZZ99")
    keys = _access_keys()
    assert keys == {"AB12": "sherif", "EF34": "ahmed", "ZZ99": "ZZ99"}


def test_gate_off_by_default(monkeypatch):
    monkeypatch.delenv("APEX_ACCESS_KEYS", raising=False)
    assert client.get("/v1/auth/status").json()["auth_required"] is False
    # an open API still answers data routes without any key
    assert client.get("/v1/scan", params={"symbols": "COMI"}).status_code in (200, 502)


def test_gate_blocks_without_key(monkeypatch):
    monkeypatch.setenv("APEX_ACCESS_KEYS", "sherif:SECRET1")
    assert client.get("/v1/auth/status").json()["auth_required"] is True
    r = client.get("/v1/scan", params={"symbols": "COMI"})
    assert r.status_code == 401


def test_gate_allows_with_valid_key_header_or_query(monkeypatch):
    monkeypatch.setenv("APEX_ACCESS_KEYS", "sherif:SECRET1")
    # header
    r1 = client.get("/v1/scan", params={"symbols": "COMI"}, headers={"X-Apex-Key": "SECRET1"})
    assert r1.status_code in (200, 502)          # authorised (not 401)
    # query param
    r2 = client.get("/v1/scan", params={"symbols": "COMI", "key": "SECRET1"})
    assert r2.status_code in (200, 502)


def test_auth_check_validates_and_names(monkeypatch):
    monkeypatch.setenv("APEX_ACCESS_KEYS", "sherif:SECRET1")
    assert client.get("/v1/auth/check", params={"key": "SECRET1"}).json()["name"] == "sherif"
    assert client.get("/v1/auth/check", params={"key": "WRONG"}).status_code == 401


def test_health_open_even_when_gated(monkeypatch):
    monkeypatch.setenv("APEX_ACCESS_KEYS", "sherif:SECRET1")
    assert client.get("/v1/health").status_code == 200
