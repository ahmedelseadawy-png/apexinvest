"""Tests for the provider-agnostic data layer.

Guarantees: freshness is computed honestly from the data's own as-of date;
intraday timeframes are reported UNAVAILABLE (never faked); nothing is ever
labelled live on the free feed; and quality reflects history sufficiency +
adjustment + freshness.
"""
from datetime import date, timedelta

from apexinvest.market import datalayer as dl


def test_intraday_is_reported_unavailable_not_faked():
    for tf in ("1m", "5m", "15m", "30m", "1h", "4h"):
        r = dl.get_ohlcv("COMI", tf)
        assert r["available"] is False
        assert r["candles"] is None
        assert "intraday" in r["reason"].lower() or "feed" in r["reason"].lower()


def test_daily_freshness_classes():
    today = date.today().isoformat()
    old = (date.today() - timedelta(days=7)).isoformat()
    ancient = (date.today() - timedelta(days=40)).isoformat()
    assert dl.annotate_daily({"as_of": today, "adjusted": True}, 300,
                             range_used="2y", reason="x")["freshness"] == "delayed_eod"
    assert dl.annotate_daily({"as_of": old, "adjusted": True}, 300,
                             range_used="2y", reason="x")["freshness"] == "historical"
    assert dl.annotate_daily({"as_of": ancient, "adjusted": True}, 300,
                             range_used="2y", reason="x")["freshness"] == "stale"
    assert dl.annotate_daily({"as_of": None, "adjusted": True}, 300,
                             range_used="2y", reason="x")["freshness"] == "unknown"


def test_annotate_never_live_and_has_fields():
    m = dl.annotate_daily({"as_of": date.today().isoformat(), "adjusted": True, "source": "Yahoo"},
                          250, range_used="2y", reason="trend context", min_bars=200)
    assert m["is_live"] is False
    for k in ("provider", "timeframe", "data_type", "range_used", "range_reason",
              "n_candles", "freshness", "freshness_label", "adjusted",
              "enough_history", "quality_score"):
        assert k in m
    assert m["enough_history"] is True


def test_quality_penalises_thin_and_unadjusted():
    good = dl.annotate_daily({"as_of": date.today().isoformat(), "adjusted": True}, 300,
                             range_used="2y", reason="x", min_bars=200)["quality_score"]
    thin = dl.annotate_daily({"as_of": date.today().isoformat(), "adjusted": True}, 50,
                             range_used="6mo", reason="x", min_bars=200)["quality_score"]
    unadj = dl.annotate_daily({"as_of": date.today().isoformat(), "adjusted": False}, 300,
                              range_used="2y", reason="x", min_bars=200)["quality_score"]
    assert good > thin and good > unadj


def test_unsupported_timeframe():
    r = dl.get_ohlcv("COMI", "3m")
    assert r["available"] is False
