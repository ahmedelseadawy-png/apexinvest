"""Yahoo -> EODHD data-source migration: provider-level tests.

Scope: data-source wiring only (market/feed.py, market/eodhd_egx.py,
market/datalayer.py, and the one fetch-closure line in engines/backtest.py).
Nothing here touches indicators, strategies, regime, structure, entry, risk,
TP, confluence, confidence or BUY/WAIT/AVOID logic — see test_engines.py,
test_indicators.py, test_structure.py, test_entry.py, test_risk.py etc. for
those, all of which pass unchanged.

The purpose of the schema/engine tests below is explicitly NOT to prove Yahoo
and EODHD produce identical trading signals from their own live data (they
can legitimately differ) — it's to prove the ENGINE receives the exact same
normalized DataFrame[open,high,low,close,volume] + meta contract from either
adapter, and therefore computes identically on identical inputs.

Hermetic throughout: pure parsers are called directly, and network calls are
monkeypatched at the `requests` boundary. Nothing here touches the network.
"""
from __future__ import annotations

import pandas as pd
import pytest
import requests

from apexinvest import service
from apexinvest.domain import Objective
from apexinvest.market import datalayer, eodhd_egx, feed, yahoo_egx

EGX_TEST_SYMBOLS = ["COMI", "SWDY", "ABUK", "HRHO", "TMGH"]  # >= 5 EGX symbols, per spec

REQUIRED_META_KEYS = {
    "symbol", "currency", "exchange", "timeframe", "bars", "last_close",
    "as_of", "source", "delayed", "adjusted", "provides",
}


def _yahoo_payload(closes: list[float]) -> dict:
    n = len(closes)
    return {
        "chart": {
            "result": [{
                "meta": {"currency": "EGP", "exchangeName": "EGX"},
                "timestamp": [1_700_000_000 + i * 86400 for i in range(n)],
                "indicators": {
                    "quote": [{
                        "open": [c - 0.1 for c in closes],
                        "high": [c + 0.2 for c in closes],
                        "low": [c - 0.2 for c in closes],
                        "close": list(closes),
                        "volume": [100_000 + i for i in range(n)],
                    }],
                    "adjclose": [{"adjclose": list(closes)}],
                },
            }],
        },
    }


def _eodhd_payload(closes: list[float], start: str = "2026-01-01") -> list[dict]:
    start_ts = pd.Timestamp(start)
    rows = []
    for i, c in enumerate(closes):
        d = (start_ts + pd.Timedelta(days=i)).date().isoformat()
        rows.append({"date": d, "open": c - 0.1, "high": c + 0.2, "low": c - 0.2,
                     "close": c, "adjusted_close": c, "volume": 100_000 + i})
    return rows


# --------------------------------------------------------------------------- #
# Schema parity: EODHD normalized output must match Yahoo's, column for column.
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("symbol", EGX_TEST_SYMBOLS)
def test_schema_parity_yahoo_vs_eodhd(symbol):
    """Same closes fed through both adapters' pure parsers -> identical
    DataFrame schema, identical meta key set, identical declared capabilities."""
    closes = [10.0, 10.2, 10.5, 10.3, 10.6, 10.8, 10.7, 10.9, 11.0, 11.2]

    y_df, y_meta = yahoo_egx._parse_chart(_yahoo_payload(closes), symbol)
    e_df, e_meta = eodhd_egx._parse_eod(_eodhd_payload(closes), symbol)

    assert list(y_df.columns) == list(e_df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(y_df) == len(e_df) == len(closes)

    assert REQUIRED_META_KEYS <= set(y_meta.keys())
    assert REQUIRED_META_KEYS <= set(e_meta.keys())

    assert y_meta["provides"] == e_meta["provides"] == ["daily_chart", "volume", "volume_profile"]
    assert y_meta["currency"] == e_meta["currency"] == "EGP"

    for col in ("open", "high", "low", "close", "volume"):
        assert y_df[col].tolist() == pytest.approx(e_df[col].tolist())


@pytest.mark.parametrize("symbol", EGX_TEST_SYMBOLS)
def test_analysis_engine_identical_output_yahoo_vs_eodhd_dataset(symbol):
    """The engine's calculated output (regime, strategies, plan, entry, risk,
    TP, confidence, candles, expected_move) is byte-identical whether the same
    candles arrive via the Yahoo-shaped or the EODHD-shaped adapter — proving
    the engine only ever consumes the normalized schema. `data_source` is
    excluded from the comparison since its provider label is SUPPOSED to
    differ (that's the honesty fix, not a bug)."""
    closes = [10.0 + 0.05 * i + (0.3 if i % 7 == 0 else 0.0) for i in range(220)]

    y_df, y_meta = yahoo_egx._parse_chart(_yahoo_payload(closes), symbol)
    e_df, e_meta = eodhd_egx._parse_eod(_eodhd_payload(closes), symbol)

    def fetcher_for(df, meta):
        return lambda _sym: (df, meta)

    out_yahoo = service.analyze_symbol(symbol, Objective.SWING, fetcher=fetcher_for(y_df, y_meta))
    out_eodhd = service.analyze_symbol(symbol, Objective.SWING, fetcher=fetcher_for(e_df, e_meta))

    def engine_view(out):
        d = dict(out)
        d.pop("data_source", None)
        return d

    assert engine_view(out_yahoo) == engine_view(out_eodhd)

    # And confirm the two data_source blocks DO differ exactly where expected:
    # honest provider labeling, nothing else silently different.
    assert "EODHD" in out_eodhd["data_source"]["provider"]
    assert "Yahoo" in out_yahoo["data_source"]["provider"]


# --------------------------------------------------------------------------- #
# EODHD_API_TOKEN env var (new canonical name; old names still accepted).
# --------------------------------------------------------------------------- #

def test_eodhd_api_token_env_var_recognized(monkeypatch):
    monkeypatch.delenv("EODHD_API_TOKEN", raising=False)
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    monkeypatch.delenv("APEX_EODHD_KEY", raising=False)
    assert eodhd_egx.enabled() is False

    monkeypatch.setenv("EODHD_API_TOKEN", "new-canonical-token")
    assert eodhd_egx.enabled() is True
    assert eodhd_egx.api_key() == "new-canonical-token"


def test_eodhd_api_token_takes_precedence_over_legacy_names(monkeypatch):
    monkeypatch.setenv("EODHD_API_TOKEN", "token-wins")
    monkeypatch.setenv("EODHD_API_KEY", "legacy-key")
    assert eodhd_egx.api_key() == "token-wins"


def test_legacy_eodhd_api_key_still_works(monkeypatch):
    """Backward compatible: render.yaml / existing deployments set EODHD_API_KEY."""
    monkeypatch.delenv("EODHD_API_TOKEN", raising=False)
    monkeypatch.setenv("EODHD_API_KEY", "legacy-key")
    assert eodhd_egx.enabled() is True
    assert eodhd_egx.api_key() == "legacy-key"


# --------------------------------------------------------------------------- #
# DATA_PROVIDER switch.
# --------------------------------------------------------------------------- #

def _df():
    return pd.DataFrame({"open": [1, 2], "high": [2, 3], "low": [1, 1],
                         "close": [2, 3], "volume": [10, 20]})


def test_data_provider_unset_keeps_existing_auto_behaviour(monkeypatch):
    """Default (no DATA_PROVIDER set) must be byte-identical to the pre-existing
    EODHD-first/Yahoo-fallback behaviour — this migration must not change it."""
    monkeypatch.delenv("DATA_PROVIDER", raising=False)
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: True)
    monkeypatch.setattr(eodhd_egx, "fetch_daily",
                        lambda sym, lookback="1y", timeout=10.0: (_df(), {"source": "EODHD (EGX end-of-day)"}))
    def yahoo_should_not_run(*a, **k):
        raise AssertionError("Yahoo must not be called when EODHD has the symbol")
    monkeypatch.setattr(yahoo_egx, "fetch_daily", yahoo_should_not_run)
    df, meta = feed.fetch_daily("COMI")
    assert "EODHD" in meta["source"]


def test_data_provider_eodhd_forced_success(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "eodhd")
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: True)
    monkeypatch.setattr(eodhd_egx, "fetch_daily",
                        lambda sym, lookback="1y", timeout=10.0: (_df(), {"source": "EODHD (EGX end-of-day)"}))
    def yahoo_should_not_run(*a, **k):
        raise AssertionError("Yahoo must never be called when DATA_PROVIDER=eodhd")
    monkeypatch.setattr(yahoo_egx, "fetch_daily", yahoo_should_not_run)
    df, meta = feed.fetch_daily("COMI")
    assert "EODHD" in meta["source"]


def test_data_provider_eodhd_forced_failure_raises_controlled_error_no_yahoo_mix(monkeypatch):
    """Forced EODHD mode must NOT silently fall back to Yahoo on failure — it
    must raise a controlled DataProviderError instead."""
    monkeypatch.setenv("DATA_PROVIDER", "eodhd")
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: True)
    def eodhd_fails(*a, **k):
        raise yahoo_egx.DataUnavailable("CRST.EGX: no data")
    monkeypatch.setattr(eodhd_egx, "fetch_daily", eodhd_fails)
    def yahoo_should_not_run(*a, **k):
        raise AssertionError("Yahoo must never be called when DATA_PROVIDER=eodhd")
    monkeypatch.setattr(yahoo_egx, "fetch_daily", yahoo_should_not_run)

    with pytest.raises(feed.DataProviderError):
        feed.fetch_daily("CRST")


def test_data_provider_eodhd_forced_without_token_raises_controlled_error(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "eodhd")
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: False)
    with pytest.raises(feed.DataProviderError):
        feed.fetch_daily("COMI")


def test_data_provider_yahoo_forced_skips_eodhd_even_if_configured(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "yahoo")
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: True)
    def eodhd_should_not_run(*a, **k):
        raise AssertionError("EODHD must never be called when DATA_PROVIDER=yahoo")
    monkeypatch.setattr(eodhd_egx, "fetch_daily", eodhd_should_not_run)
    monkeypatch.setattr(yahoo_egx, "fetch_daily",
                        lambda sym, lookback="1y", timeout=10.0: (_df(), {"source": "Yahoo Finance (EGX end-of-day, .CA)"}))
    df, meta = feed.fetch_daily("COMI")
    assert "Yahoo" in meta["source"]


# --------------------------------------------------------------------------- #
# Required failure scenarios: missing symbol, insufficient history, timeout,
# invalid token — all at the EODHD adapter boundary (mocked `requests`, no
# network), and via the forced-provider feed routing.
# --------------------------------------------------------------------------- #

class _FakeResponse:
    def __init__(self, status_code=200, payload=None, http_error=None):
        self.status_code = status_code
        self._payload = payload
        self._http_error = http_error

    def raise_for_status(self):
        if self._http_error:
            raise self._http_error

    def json(self):
        return self._payload


def test_eodhd_missing_symbol_raises_data_unavailable(monkeypatch):
    monkeypatch.setenv("EODHD_API_TOKEN", "demo-token")
    monkeypatch.setattr(eodhd_egx.requests, "get",
                        lambda url, params=None, timeout=None: _FakeResponse(200, payload=[]))
    with pytest.raises(yahoo_egx.DataUnavailable):
        eodhd_egx.fetch_daily("ZZZZ")


def test_eodhd_insufficient_history_raises_data_unavailable(monkeypatch):
    monkeypatch.setenv("EODHD_API_TOKEN", "demo-token")
    one_bar = _eodhd_payload([10.0])  # only 1 candle -- below the 2-bar minimum
    monkeypatch.setattr(eodhd_egx.requests, "get",
                        lambda url, params=None, timeout=None: _FakeResponse(200, payload=one_bar))
    with pytest.raises(yahoo_egx.DataUnavailable, match="not enough candles"):
        eodhd_egx.fetch_daily("SHORTHIST")


def test_eodhd_api_timeout_propagates_and_auto_mode_falls_back_to_yahoo(monkeypatch):
    monkeypatch.delenv("DATA_PROVIDER", raising=False)
    monkeypatch.setenv("EODHD_API_TOKEN", "demo-token")

    def timeout_get(url, params=None, timeout=None):
        raise requests.exceptions.Timeout("EODHD did not respond in time")
    monkeypatch.setattr(eodhd_egx.requests, "get", timeout_get)
    monkeypatch.setattr(yahoo_egx, "fetch_daily",
                        lambda sym, lookback="1y", timeout=10.0: (_df(), {"source": "Yahoo Finance (EGX end-of-day, .CA)"}))

    # auto mode: EODHD timeout -> honest fallback to Yahoo (existing architecture).
    df, meta = feed.fetch_daily("COMI")
    assert "Yahoo" in meta["source"]


def test_eodhd_api_timeout_forced_mode_raises_controlled_error(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "eodhd")
    monkeypatch.setenv("EODHD_API_TOKEN", "demo-token")

    def timeout_get(url, params=None, timeout=None):
        raise requests.exceptions.Timeout("EODHD did not respond in time")
    monkeypatch.setattr(eodhd_egx.requests, "get", timeout_get)

    with pytest.raises(feed.DataProviderError):
        feed.fetch_daily("COMI")


def test_eodhd_invalid_token_raises_http_error(monkeypatch):
    monkeypatch.setenv("EODHD_API_TOKEN", "invalid-token")
    unauthorized = requests.exceptions.HTTPError("401 Client Error: Unauthorized")
    monkeypatch.setattr(eodhd_egx.requests, "get",
                        lambda url, params=None, timeout=None: _FakeResponse(401, http_error=unauthorized))
    with pytest.raises(requests.exceptions.HTTPError):
        eodhd_egx.fetch_daily("COMI")


def test_eodhd_invalid_token_forced_mode_raises_controlled_error(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "eodhd")
    monkeypatch.setenv("EODHD_API_TOKEN", "invalid-token")
    unauthorized = requests.exceptions.HTTPError("401 Client Error: Unauthorized")
    monkeypatch.setattr(eodhd_egx.requests, "get",
                        lambda url, params=None, timeout=None: _FakeResponse(401, http_error=unauthorized))
    with pytest.raises(feed.DataProviderError):
        feed.fetch_daily("COMI")


# --------------------------------------------------------------------------- #
# datalayer: honest provider labeling + provider-aware routing.
# --------------------------------------------------------------------------- #

def test_datalayer_provider_label_reflects_eodhd_source():
    m = datalayer.annotate_daily({"as_of": "2026-01-01", "adjusted": True,
                                  "source": "EODHD (EGX end-of-day)"},
                                 250, range_used="2y", reason="x")
    assert m["provider"] == "EODHD (EGX end-of-day, adjusted)"


def test_datalayer_provider_label_reflects_yahoo_source():
    m = datalayer.annotate_daily({"as_of": "2026-01-01", "adjusted": True,
                                  "source": "Yahoo Finance (EGX end-of-day, .CA)"},
                                 250, range_used="2y", reason="x")
    assert m["provider"] == "Yahoo Finance (EGX end-of-day, adjusted)"


def test_datalayer_get_daily_is_provider_aware(monkeypatch):
    """datalayer.get_daily must go through the unified feed (EODHD/Yahoo per
    DATA_PROVIDER), not call yahoo_egx directly -- so /v1/data/health reports
    the truth about which provider is actually serving data."""
    monkeypatch.setattr(feed, "fetch_daily",
                        lambda sym, lookback="2y", timeout=10.0: (_df(), {
                            "as_of": "2026-01-01", "adjusted": True,
                            "source": "EODHD (EGX end-of-day)",
                        }))
    result = datalayer.get_daily("COMI", min_bars=1)
    assert result["available"] is True
    assert result["meta"]["provider"] == "EODHD (EGX end-of-day, adjusted)"
