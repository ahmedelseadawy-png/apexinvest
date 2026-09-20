"""EODHD adapter + unified feed fallback.

Hermetic: the parser is pure (fed a mock EODHD payload) and the feed-routing
tests monkeypatch the adapters, so nothing hits the network.
"""
import pandas as pd
import pytest

from apexinvest.market import eodhd_egx, feed, yahoo_egx


SAMPLE = [
    {"date": "2026-01-02", "open": 3.0, "high": 3.2, "low": 2.9, "close": 3.1, "adjusted_close": 3.1, "volume": 100000},
    {"date": "2026-01-05", "open": 3.1, "high": 3.3, "low": 3.0, "close": 3.25, "adjusted_close": 3.25, "volume": 120000},
    {"date": "2026-01-06", "open": 3.25, "high": 3.4, "low": 3.2, "close": 3.35, "adjusted_close": 3.35, "volume": 90000},
]


def test_parse_ok_shape_and_meta():
    df, meta = eodhd_egx._parse_eod(SAMPLE, "CRST")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 3
    assert meta["symbol"] == "CRST" and meta["currency"] == "EGP"
    assert "EODHD" in meta["source"] and meta["delayed"] is True
    assert meta["as_of"] == "2026-01-06"
    assert meta["provides"] == ["daily_chart", "volume", "volume_profile"]


def test_parse_empty_raises_dataunavailable():
    with pytest.raises(yahoo_egx.DataUnavailable):
        eodhd_egx._parse_eod([], "CRST")


def test_parse_error_payload_raises():
    with pytest.raises(yahoo_egx.DataUnavailable):
        eodhd_egx._parse_eod({"error": "Symbol not found"}, "ZZZZ")


def test_backadjust_applied_when_adjusted_close_differs():
    bars = [
        {"date": "2026-01-02", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "adjusted_close": 5.0, "volume": 1},
        {"date": "2026-01-03", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "adjusted_close": 5.0, "volume": 1},
    ]
    df, meta = eodhd_egx._parse_eod(bars, "TEST")
    assert meta["adjusted"] is True
    assert df["close"].iloc[-1] == pytest.approx(5.0)   # 10 * (5/10)


def test_symbol_mapping_defaults_to_egx_suffix(monkeypatch):
    monkeypatch.delenv("EODHD_EGX_SUFFIX", raising=False)
    assert eodhd_egx._eodhd_symbol("comi") == "COMI.EGX"
    assert eodhd_egx._eodhd_symbol("CRST.CA") == "CRST.EGX"
    monkeypatch.setenv("EODHD_EGX_SUFFIX", "CA")
    assert eodhd_egx._eodhd_symbol("COMI") == "COMI.CA"


def test_enabled_reflects_env(monkeypatch):
    monkeypatch.delenv("EODHD_API_KEY", raising=False)
    monkeypatch.delenv("APEX_EODHD_KEY", raising=False)
    assert eodhd_egx.enabled() is False
    monkeypatch.setenv("EODHD_API_KEY", "demo-key")
    assert eodhd_egx.enabled() is True


# ---- unified feed routing ---------------------------------------------------

def _df():
    return pd.DataFrame({"open": [1, 2], "high": [2, 3], "low": [1, 1],
                         "close": [2, 3], "volume": [10, 20]})


def test_feed_uses_eodhd_when_enabled(monkeypatch):
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: True)
    monkeypatch.setattr(eodhd_egx, "fetch_daily",
                        lambda sym, lookback="1y", timeout=10.0: (_df(), {"source": "EODHD (EGX end-of-day)"}))
    def yahoo_should_not_run(*a, **k):
        raise AssertionError("Yahoo must not be called when EODHD has the symbol")
    monkeypatch.setattr(yahoo_egx, "fetch_daily", yahoo_should_not_run)
    df, meta = feed.fetch_daily("COMI")
    assert "EODHD" in meta["source"] and len(df) == 2


def test_feed_falls_back_to_yahoo_when_eodhd_has_no_data(monkeypatch):
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: True)
    def eodhd_nodata(*a, **k):
        raise yahoo_egx.DataUnavailable("CRST.EGX: no data")
    monkeypatch.setattr(eodhd_egx, "fetch_daily", eodhd_nodata)
    monkeypatch.setattr(yahoo_egx, "fetch_daily",
                        lambda sym, lookback="1y", timeout=10.0: (_df(), {"source": "Yahoo Finance (EGX end-of-day, .CA)"}))
    df, meta = feed.fetch_daily("CRST")
    assert "Yahoo" in meta["source"]


def test_feed_uses_yahoo_when_eodhd_disabled(monkeypatch):
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: False)
    monkeypatch.setattr(yahoo_egx, "fetch_daily",
                        lambda sym, lookback="1y", timeout=10.0: (_df(), {"source": "Yahoo Finance (EGX end-of-day, .CA)"}))
    df, meta = feed.fetch_daily("COMI")
    assert "Yahoo" in meta["source"]


def test_feed_raises_when_neither_feed_has_data(monkeypatch):
    monkeypatch.setattr(eodhd_egx, "enabled", lambda: True)
    monkeypatch.setattr(eodhd_egx, "fetch_daily",
                        lambda *a, **k: (_ for _ in ()).throw(yahoo_egx.DataUnavailable("no eodhd")))
    monkeypatch.setattr(yahoo_egx, "fetch_daily",
                        lambda *a, **k: (_ for _ in ()).throw(yahoo_egx.DataUnavailable("no yahoo")))
    with pytest.raises(yahoo_egx.DataUnavailable):
        feed.fetch_daily("ZZZZ")
