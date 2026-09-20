"""Tests for the two-source price cross-validation.

The guarantee: agreeing sources are flagged agree=True, a large gap is flagged
as a warning (never silently reconciled), and bad inputs degrade to unavailable.
"""
from apexinvest.service import _crosscheck_price


def test_agree_on_small_move():
    r = _crosscheck_price(100.0, 103.0)
    assert r["available"] and r["agree"] is True
    assert r["severity"] == "ok"
    assert r["diff_pct"] == 3.0


def test_warn_on_moderate_gap():
    r = _crosscheck_price(100.0, 110.0)
    assert r["agree"] is False
    assert r["severity"] == "warn"


def test_high_on_large_gap():
    r = _crosscheck_price(100.0, 130.0)
    assert r["agree"] is False
    assert r["severity"] == "high"


def test_unavailable_on_bad_input():
    assert _crosscheck_price(0, 10)["available"] is False
    assert _crosscheck_price(10, 0)["available"] is False


def test_never_reconciles_the_numbers():
    # Both original prices are reported unchanged; no averaging/reconciliation.
    r = _crosscheck_price(100.0, 108.0)
    assert r["eod_close"] == 100.0 and r["live_price"] == 108.0
