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
from apexinvest.market import datalayer, eodhd_egx, feed, fundamentals, tradingview_egx, yahoo_egx


def _stub_fundamentals(monkeypatch):
    """Fundamentals are fetched unconditionally whenever fetcher=None (a
    separate, best-effort network call unrelated to price/history routing).
    Stub it so live_price=True tests stay hermetic and deterministic."""
    monkeypatch.setattr(fundamentals, "get", lambda symbol, **k: {"available": False, "reason": "test-stub"})

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


# --------------------------------------------------------------------------- #
# Current-price / quote path (scanner + /v1/quotes picker). Same DATA_PROVIDER
# switch as historical OHLCV — this is the follow-up fix: the scanner's
# candle-derived current_price already went through feed.fetch_daily (see
# above), but service.py's separate quote-lookup path (quotes()/_yahoo_quotes,
# used by the /v1/quotes picker) still called yahoo_egx.fetch_quote directly.
# --------------------------------------------------------------------------- #

def _quote(symbol="COMI", price=12.34, prev=12.0):
    return {"symbol": symbol, "price": price, "prev_close": prev,
            "change_pct": round((price - prev) / prev * 100, 2),
            "as_of": "2026-01-06", "currency": "EGP"}


def test_eodhd_and_yahoo_quote_schema_identical(monkeypatch):
    """eodhd_egx.fetch_quote and yahoo_egx.fetch_quote must return the exact
    same key set -- the schema service.quotes() / the /v1/quotes response /
    the picker all depend on never needing to change."""
    monkeypatch.setenv("EODHD_API_TOKEN", "demo-token")
    closes = [10.0, 10.2, 10.5]

    class _Resp:
        def __init__(self, payload):
            self.status_code = 200
            self._payload = payload
        def raise_for_status(self):
            pass
        def json(self):
            return self._payload

    # yahoo_egx and eodhd_egx both `import requests` -- the same module
    # singleton -- so patch/call/unpatch sequentially rather than patching
    # both `.get` attributes at once (the second patch would just overwrite
    # the first, since it's the identical shared object).
    monkeypatch.setattr(yahoo_egx.requests, "get",
                        lambda *a, **k: _Resp(_yahoo_payload(closes)))
    yq = yahoo_egx.fetch_quote("COMI")
    monkeypatch.setattr(eodhd_egx.requests, "get",
                        lambda *a, **k: _Resp(_eodhd_payload(closes)))
    eq = eodhd_egx.fetch_quote("COMI")

    assert set(yq.keys()) == set(eq.keys()) == {
        "symbol", "price", "prev_close", "change_pct", "as_of", "currency",
    }


def test_feed_fetch_quote_data_provider_unset_keeps_existing_auto_behaviour(monkeypatch):
    monkeypatch.delenv("DATA_PROVIDER", raising=False)
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: True)
    monkeypatch.setattr(eodhd_egx, "fetch_quote", lambda sym, timeout=8.0: _quote(sym))
    def yahoo_should_not_run(*a, **k):
        raise AssertionError("Yahoo must not be called when EODHD answers in auto mode")
    monkeypatch.setattr(yahoo_egx, "fetch_quote", yahoo_should_not_run)
    q = feed.fetch_quote("COMI")
    assert q["symbol"] == "COMI"


def test_feed_fetch_quote_eodhd_forced_uses_eodhd_not_yahoo(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "eodhd")
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: True)
    monkeypatch.setattr(eodhd_egx, "fetch_quote", lambda sym, timeout=8.0: _quote(sym))
    def yahoo_should_not_run(*a, **k):
        raise AssertionError("Yahoo quote must never be called when DATA_PROVIDER=eodhd")
    monkeypatch.setattr(yahoo_egx, "fetch_quote", yahoo_should_not_run)
    q = feed.fetch_quote("COMI")
    assert q["symbol"] == "COMI"


def test_feed_fetch_quote_eodhd_forced_failure_raises_controlled_error_no_yahoo_mix(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "eodhd")
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: True)
    def eodhd_fails(*a, **k):
        raise yahoo_egx.DataUnavailable("no data")
    monkeypatch.setattr(eodhd_egx, "fetch_quote", eodhd_fails)
    def yahoo_should_not_run(*a, **k):
        raise AssertionError("Yahoo quote must never be called when DATA_PROVIDER=eodhd")
    monkeypatch.setattr(yahoo_egx, "fetch_quote", yahoo_should_not_run)
    with pytest.raises(feed.DataProviderError):
        feed.fetch_quote("COMI")


def test_feed_fetch_quote_eodhd_forced_without_token_raises_controlled_error(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "eodhd")
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: False)
    with pytest.raises(feed.DataProviderError):
        feed.fetch_quote("COMI")


def test_feed_fetch_quote_yahoo_forced_skips_eodhd(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "yahoo")
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: True)
    def eodhd_should_not_run(*a, **k):
        raise AssertionError("EODHD must never be called when DATA_PROVIDER=yahoo")
    monkeypatch.setattr(eodhd_egx, "fetch_quote", eodhd_should_not_run)
    monkeypatch.setattr(yahoo_egx, "fetch_quote", lambda sym, timeout=8.0: _quote(sym))
    q = feed.fetch_quote("COMI")
    assert q["symbol"] == "COMI"


# ---- service.quotes() / _eod_quotes(): the picker's /v1/quotes path --------

def test_service_quotes_forced_eodhd_skips_tradingview_and_uses_eodhd(monkeypatch):
    """DATA_PROVIDER=eodhd must make service.quotes() a genuine single source
    of truth: TradingView is skipped entirely (not just Yahoo)."""
    monkeypatch.setenv("DATA_PROVIDER", "eodhd")
    def tv_should_not_run(*a, **k):
        raise AssertionError("TradingView must not be called when DATA_PROVIDER=eodhd")
    monkeypatch.setattr(tradingview_egx, "fetch_quotes", tv_should_not_run)
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: True)
    monkeypatch.setattr(eodhd_egx, "fetch_quote", lambda sym, timeout=8.0: _quote(sym))
    def yahoo_should_not_run(*a, **k):
        raise AssertionError("Yahoo quote must never be called when DATA_PROVIDER=eodhd")
    monkeypatch.setattr(yahoo_egx, "fetch_quote", yahoo_should_not_run)

    result = service.quotes(["COMI", "SWDY"])
    assert set(result.keys()) == {"COMI", "SWDY"}


def test_service_quotes_forced_eodhd_failure_omits_symbol_never_yahoo_fallback(monkeypatch):
    """A per-symbol EODHD failure in forced mode must simply omit that symbol
    -- never silently backfill it from Yahoo."""
    monkeypatch.setenv("DATA_PROVIDER", "eodhd")
    def tv_should_not_run(*a, **k):
        raise AssertionError("TradingView must not be called when DATA_PROVIDER=eodhd")
    monkeypatch.setattr(tradingview_egx, "fetch_quotes", tv_should_not_run)
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: True)
    def eodhd_fails(*a, **k):
        raise yahoo_egx.DataUnavailable("no data")
    monkeypatch.setattr(eodhd_egx, "fetch_quote", eodhd_fails)
    def yahoo_should_not_run(*a, **k):
        raise AssertionError("Yahoo quote must never be called when DATA_PROVIDER=eodhd")
    monkeypatch.setattr(yahoo_egx, "fetch_quote", yahoo_should_not_run)

    result = service.quotes(["ZZZZ"])
    assert result == {}


def test_service_quotes_auto_mode_tradingview_first_unchanged(monkeypatch):
    """Default (DATA_PROVIDER unset) must keep the existing TradingView-first
    behaviour byte-for-byte -- this fix must not change it."""
    monkeypatch.delenv("DATA_PROVIDER", raising=False)
    monkeypatch.setattr(tradingview_egx, "fetch_quotes", lambda syms: {"COMI": _quote("COMI")})
    def eod_should_not_run(sym):
        raise AssertionError("EOD fallback must not run for a symbol TradingView already answered")
    result = service.quotes(["COMI"], fetcher=eod_should_not_run)
    assert "COMI" in result


def test_service_quotes_auto_mode_falls_back_to_eod_for_tradingview_misses(monkeypatch):
    monkeypatch.delenv("DATA_PROVIDER", raising=False)
    monkeypatch.setattr(tradingview_egx, "fetch_quotes", lambda syms: {})
    result = service.quotes(["COMI"], fetcher=lambda sym: _quote(sym))
    assert result["COMI"]["symbol"] == "COMI"


def test_service_quotes_response_schema_unchanged_regardless_of_provider(monkeypatch):
    """Same key set whether TradingView, EODHD or Yahoo actually answered --
    the frontend needs zero changes."""
    expected_keys = {"symbol", "price", "prev_close", "change_pct", "as_of", "currency"}

    monkeypatch.setenv("DATA_PROVIDER", "eodhd")
    monkeypatch.setattr(tradingview_egx, "fetch_quotes",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    result = service.quotes(["COMI"], fetcher=lambda sym: _quote(sym))
    assert set(result["COMI"].keys()) == expected_keys

    monkeypatch.delenv("DATA_PROVIDER", raising=False)
    monkeypatch.setattr(tradingview_egx, "fetch_quotes", lambda syms: {})
    result = service.quotes(["COMI"], fetcher=lambda sym: _quote(sym))
    assert set(result["COMI"].keys()) == expected_keys


def test_scanner_current_price_already_bypasses_tradingview_and_yahoo_quote(monkeypatch):
    """The scanner's per-row current_price comes from analyze_symbol's candle
    fetch (feed.fetch_daily), not from service.quotes()/tradingview/yahoo
    quote functions at all -- scan() always calls analyze(..., live_price=False),
    which skips the TradingView/quote overlay block in analyze_symbol entirely.
    This test proves that data flow directly, end to end, under a forced
    EODHD provider."""
    monkeypatch.setenv("DATA_PROVIDER", "eodhd")
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: True)

    closes = [10.0 + 0.05 * i for i in range(220)]
    e_df, e_meta = eodhd_egx._parse_eod(_eodhd_payload(closes), "COMI")
    monkeypatch.setattr(eodhd_egx, "fetch_daily", lambda sym, lookback="1y", timeout=10.0: (e_df, e_meta))

    def tv_should_not_run(*a, **k):
        raise AssertionError("TradingView must not be called for a scan (live_price=False)")
    monkeypatch.setattr(tradingview_egx, "fetch_quote", tv_should_not_run)
    def yahoo_should_not_run(*a, **k):
        raise AssertionError("Yahoo must not be called for a scan under DATA_PROVIDER=eodhd")
    monkeypatch.setattr(yahoo_egx, "fetch_daily", yahoo_should_not_run)
    monkeypatch.setattr(yahoo_egx, "fetch_quote", yahoo_should_not_run)

    out = service.analyze_symbol("COMI", Objective.SWING, live_price=False)
    assert out["plan"]["current_price"] == pytest.approx(closes[-1])
    assert "EODHD" in out["data_source"]["provider"]


# --------------------------------------------------------------------------- #
# analyze_symbol(..., live_price=True): the last remaining current-price
# touchpoint (single-symbol /v1/analyses/auto/{symbol} and portfolio.py --
# never the scanner, which always passes live_price=False, see above).
# --------------------------------------------------------------------------- #

_LONG_CLOSES = [10.0 + 0.05 * i for i in range(220)]


def test_live_price_eodhd_forced_never_calls_tradingview(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "eodhd")
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: True)
    e_df, e_meta = eodhd_egx._parse_eod(_eodhd_payload(_LONG_CLOSES), "COMI")
    monkeypatch.setattr(eodhd_egx, "fetch_daily", lambda sym, lookback="2y", timeout=10.0: (e_df, e_meta))
    monkeypatch.setattr(eodhd_egx, "fetch_quote",
                        lambda sym, timeout=8.0: _quote(sym, price=_LONG_CLOSES[-1] + 0.02,
                                                        prev=_LONG_CLOSES[-2]))
    def tv_should_not_run(*a, **k):
        raise AssertionError("TradingView must never be called when DATA_PROVIDER=eodhd")
    monkeypatch.setattr(tradingview_egx, "fetch_quote", tv_should_not_run)
    _stub_fundamentals(monkeypatch)

    out = service.analyze_symbol("COMI", Objective.SWING, live_price=True)
    assert out["data_source"]["price_source"] is not None


def test_live_price_eodhd_forced_uses_eodhd_quote(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "eodhd")
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: True)
    e_df, e_meta = eodhd_egx._parse_eod(_eodhd_payload(_LONG_CLOSES), "COMI")
    monkeypatch.setattr(eodhd_egx, "fetch_daily", lambda sym, lookback="2y", timeout=10.0: (e_df, e_meta))
    fresher_price = _LONG_CLOSES[-1] + 0.5
    monkeypatch.setattr(eodhd_egx, "fetch_quote",
                        lambda sym, timeout=8.0: _quote(sym, price=fresher_price, prev=_LONG_CLOSES[-2]))
    monkeypatch.setattr(tradingview_egx, "fetch_quote",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    _stub_fundamentals(monkeypatch)

    out = service.analyze_symbol("COMI", Objective.SWING, live_price=True)
    assert out["data_source"]["price"] == pytest.approx(round(fresher_price, 4))
    # The crosscheck wording must be provider-aware, never hardcoded "Yahoo".
    note = out["data_source"]["price_crosscheck"]["note"]
    assert "EODHD" in note
    assert "Yahoo" not in note


def test_live_price_auto_mode_tradingview_first_unchanged(monkeypatch):
    """Default (DATA_PROVIDER unset) must keep the existing TradingView-first
    live-price behaviour byte-for-byte, including the "vs Yahoo EOD" wording
    when Yahoo actually served the EOD close."""
    monkeypatch.delenv("DATA_PROVIDER", raising=False)
    y_df, y_meta = yahoo_egx._parse_chart(_yahoo_payload(_LONG_CLOSES), "COMI")
    monkeypatch.setattr(yahoo_egx, "fetch_daily", lambda sym, lookback="2y", timeout=10.0: (y_df, y_meta))
    tv_price = _LONG_CLOSES[-1] + 0.3
    monkeypatch.setattr(tradingview_egx, "fetch_quote",
                        lambda sym, timeout=8.0: {"symbol": sym, "price": tv_price, "change_pct": 0.1,
                                                  "currency": "EGP", "as_of": "2026-01-06",
                                                  "source": "TradingView (delayed)"})
    def eodhd_should_not_run(*a, **k):
        raise AssertionError("EODHD quote must not run in auto mode when TradingView answers")
    monkeypatch.setattr(eodhd_egx, "fetch_quote", eodhd_should_not_run)
    _stub_fundamentals(monkeypatch)

    out = service.analyze_symbol("COMI", Objective.SWING, live_price=True)
    assert out["data_source"]["price"] == pytest.approx(round(tv_price, 4))
    assert out["data_source"]["price_source"] == "TradingView (delayed)"
    assert "Yahoo EOD" in out["data_source"]["price_crosscheck"]["note"]


def test_live_price_yahoo_mode_still_tries_tradingview_first(monkeypatch):
    """DATA_PROVIDER=yahoo forces Yahoo-only HISTORY (see test_provider_migration
    tests above), but the live-price overlay behaviour is unchanged from auto:
    TradingView is still attempted for freshness."""
    monkeypatch.setenv("DATA_PROVIDER", "yahoo")
    y_df, y_meta = yahoo_egx._parse_chart(_yahoo_payload(_LONG_CLOSES), "COMI")
    monkeypatch.setattr(yahoo_egx, "fetch_daily", lambda sym, lookback="2y", timeout=10.0: (y_df, y_meta))
    tv_price = _LONG_CLOSES[-1] + 0.3
    calls = []
    def tv_fetch(sym, timeout=8.0):
        calls.append(sym)
        return {"symbol": sym, "price": tv_price, "change_pct": 0.1, "currency": "EGP",
                "as_of": "2026-01-06", "source": "TradingView (delayed)"}
    monkeypatch.setattr(tradingview_egx, "fetch_quote", tv_fetch)
    _stub_fundamentals(monkeypatch)

    out = service.analyze_symbol("COMI", Objective.SWING, live_price=True)
    assert calls == ["COMI"]
    assert out["data_source"]["price"] == pytest.approx(round(tv_price, 4))


def test_live_price_response_schema_unchanged_across_modes(monkeypatch):
    """data_source key set is identical whether DATA_PROVIDER is eodhd or
    unset (auto) -- only the VALUES/wording differ (honest labeling), the
    frontend needs zero changes."""
    _stub_fundamentals(monkeypatch)

    monkeypatch.setenv("DATA_PROVIDER", "eodhd")
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: True)
    e_df, e_meta = eodhd_egx._parse_eod(_eodhd_payload(_LONG_CLOSES), "COMI")
    monkeypatch.setattr(eodhd_egx, "fetch_daily", lambda sym, lookback="2y", timeout=10.0: (e_df, e_meta))
    monkeypatch.setattr(eodhd_egx, "fetch_quote",
                        lambda sym, timeout=8.0: _quote(sym, price=_LONG_CLOSES[-1] + 0.1,
                                                        prev=_LONG_CLOSES[-2]))
    monkeypatch.setattr(tradingview_egx, "fetch_quote",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    out_eodhd = service.analyze_symbol("COMI", Objective.SWING, live_price=True)

    monkeypatch.setenv("DATA_PROVIDER", "auto")
    y_df, y_meta = yahoo_egx._parse_chart(_yahoo_payload(_LONG_CLOSES), "COMI")
    monkeypatch.setattr(yahoo_egx, "fetch_daily", lambda sym, lookback="2y", timeout=10.0: (y_df, y_meta))
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: False)
    monkeypatch.setattr(tradingview_egx, "fetch_quote",
                        lambda sym, timeout=8.0: {"symbol": sym, "price": _LONG_CLOSES[-1] + 0.1,
                                                  "change_pct": 0.1, "currency": "EGP",
                                                  "as_of": "2026-01-06", "source": "TradingView (delayed)"})
    out_auto = service.analyze_symbol("COMI", Objective.SWING, live_price=True)

    expected_keys = {"price", "price_source", "price_as_of", "price_crosscheck"}
    assert expected_keys <= set(out_eodhd["data_source"].keys())
    assert expected_keys <= set(out_auto["data_source"].keys())
    assert set(out_eodhd["data_source"]["price_crosscheck"].keys()) == \
           set(out_auto["data_source"]["price_crosscheck"].keys())


# --------------------------------------------------------------------------- #
# Regression: eodhd_egx.fetch_quote() must use the RAW `close`, never
# `adjusted_close`. fetch_daily()/_parse_eod() keep back-adjusting OHLC for
# technical-analysis continuity -- unchanged, verified by the SAME payload.
# --------------------------------------------------------------------------- #

class _FakeQuoteResp:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload
    def raise_for_status(self):
        pass
    def json(self):
        return self._payload


def test_fetch_quote_uses_raw_close_not_adjusted_close(monkeypatch):
    """The exact scenario from the bug report: close=33, adjusted_close=30 --
    the displayed/quoted price must be 33, never 30."""
    monkeypatch.setenv("EODHD_API_TOKEN", "demo-token")
    bars = [
        {"date": "2026-01-05", "open": 33.5, "high": 34.0, "low": 32.8,
         "close": 33.0, "adjusted_close": 30.0, "volume": 50000},
    ]
    monkeypatch.setattr(eodhd_egx.requests, "get", lambda *a, **k: _FakeQuoteResp(bars))

    q = eodhd_egx.fetch_quote("COMI")

    assert q["price"] == 33.0
    assert q["price"] != 30.0
    assert q["symbol"] == "COMI"
    assert q["currency"] == "EGP"
    assert q["as_of"] == "2026-01-05"


def test_fetch_quote_prev_close_and_change_pct_use_raw_closes(monkeypatch):
    """prev_close and change_pct must also come from raw closes, not adjusted
    ones -- proving the fix covers all three quote fields, not just price."""
    monkeypatch.setenv("EODHD_API_TOKEN", "demo-token")
    bars = [
        {"date": "2026-01-05", "open": 32.5, "high": 33.5, "low": 32.0,
         "close": 33.0, "adjusted_close": 30.0, "volume": 50000},
        {"date": "2026-01-06", "open": 33.0, "high": 35.5, "low": 32.9,
         "close": 35.0, "adjusted_close": 31.8, "volume": 51000},
    ]
    monkeypatch.setattr(eodhd_egx.requests, "get", lambda *a, **k: _FakeQuoteResp(bars))

    q = eodhd_egx.fetch_quote("COMI")

    assert q["price"] == 35.0                      # raw last close, not 31.8
    assert q["prev_close"] == 33.0                  # raw previous close, not 30.0
    assert q["change_pct"] == pytest.approx(round((35.0 - 33.0) / 33.0 * 100, 2))
    assert q["as_of"] == "2026-01-06"


def test_fetch_daily_adjustment_unchanged_alongside_fixed_fetch_quote(monkeypatch):
    """Same payload, both functions: fetch_daily's OHLC stays back-adjusted
    (unchanged technical-analysis behaviour) while fetch_quote now returns the
    raw close -- proving the fix did not touch _parse_eod/fetch_daily at all."""
    monkeypatch.setenv("EODHD_API_TOKEN", "demo-token")
    bars = [
        {"date": "2026-01-05", "open": 32.5, "high": 33.5, "low": 32.0,
         "close": 33.0, "adjusted_close": 30.0, "volume": 50000},
        {"date": "2026-01-06", "open": 33.0, "high": 35.5, "low": 32.9,
         "close": 35.0, "adjusted_close": 31.8, "volume": 51000},
    ]
    monkeypatch.setattr(eodhd_egx.requests, "get", lambda *a, **k: _FakeQuoteResp(bars))

    df, meta = eodhd_egx.fetch_daily("COMI")
    assert meta["adjusted"] is True
    assert df["close"].iloc[0] == pytest.approx(30.0)   # back-adjusted, unchanged
    assert df["close"].iloc[-1] == pytest.approx(31.8)  # back-adjusted, unchanged

    monkeypatch.setattr(eodhd_egx.requests, "get", lambda *a, **k: _FakeQuoteResp(bars))
    q = eodhd_egx.fetch_quote("COMI")
    assert q["price"] == 35.0                           # raw, fixed


def test_fetch_quote_no_adjustment_case_unaffected(monkeypatch):
    """When EODHD reports no adjustment at all (close == adjusted_close, the
    common case), the fix changes nothing observable."""
    monkeypatch.setenv("EODHD_API_TOKEN", "demo-token")
    bars = [
        {"date": "2026-01-05", "open": 9.9, "high": 10.2, "low": 9.8,
         "close": 10.0, "adjusted_close": 10.0, "volume": 100000},
        {"date": "2026-01-06", "open": 10.1, "high": 10.4, "low": 10.0,
         "close": 10.2, "adjusted_close": 10.2, "volume": 120000},
    ]
    monkeypatch.setattr(eodhd_egx.requests, "get", lambda *a, **k: _FakeQuoteResp(bars))
    q = eodhd_egx.fetch_quote("COMI")
    assert q["price"] == 10.2
    assert q["prev_close"] == 10.0


def test_feed_fetch_quote_eodhd_forced_returns_raw_price_end_to_end(monkeypatch):
    """End-to-end through feed.fetch_quote() (what service.py/quotes() and the
    live_price overlay actually call): forced DATA_PROVIDER=eodhd must return
    the raw close, and must not touch Yahoo or TradingView."""
    monkeypatch.setenv("DATA_PROVIDER", "eodhd")
    monkeypatch.setenv("EODHD_API_TOKEN", "demo-token")
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: True)
    bars = [
        {"date": "2026-01-05", "open": 32.5, "high": 33.5, "low": 32.0,
         "close": 33.0, "adjusted_close": 30.0, "volume": 50000},
    ]
    monkeypatch.setattr(eodhd_egx.requests, "get", lambda *a, **k: _FakeQuoteResp(bars))
    def yahoo_should_not_run(*a, **k):
        raise AssertionError("Yahoo must never be called when DATA_PROVIDER=eodhd")
    monkeypatch.setattr(yahoo_egx, "fetch_quote", yahoo_should_not_run)
    monkeypatch.setattr(yahoo_egx, "fetch_daily", yahoo_should_not_run)
    def tv_should_not_run(*a, **k):
        raise AssertionError("TradingView must never be called when DATA_PROVIDER=eodhd")
    monkeypatch.setattr(tradingview_egx, "fetch_quote", tv_should_not_run)
    monkeypatch.setattr(tradingview_egx, "fetch_quotes", tv_should_not_run)

    q = feed.fetch_quote("COMI")
    assert q["price"] == 33.0
