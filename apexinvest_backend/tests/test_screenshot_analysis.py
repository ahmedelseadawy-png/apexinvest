"""Tests for the TradingView Screenshot Analysis layer (additive-only feature).

Covers spec section 26's required scenarios 1-18 plus regression coverage
(19-22): the existing engine's BUY/WAIT/AVOID output is untouched by this
module, and this module never imports the EODHD/market-data path.
"""
from __future__ import annotations

import io

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from apexinvest.api.main import app
from apexinvest.domain import Objective
from apexinvest.market import yahoo_egx
from apexinvest.service import analyze_symbol
from apexinvest.vision import build as vbuild
from apexinvest.vision import provider as vp
from apexinvest.vision.schema import VisionAnalysis

client = TestClient(app)


def _png_bytes(fmt="PNG", size=(12, 12)):
    buf = io.BytesIO()
    Image.new("RGB", size, color=(10, 20, 30)).save(buf, format=fmt)
    return buf.getvalue()


def _upload(data: bytes, filename="chart.png", content_type="image/png", **form):
    files = {"image": (filename, io.BytesIO(data), content_type)}
    return client.post("/v1/analyses/screenshot", files=files, data=form)


def _fake_provider(payload):
    def _fake(image_bytes, fmt, metadata):
        return payload
    return _fake


# --------------------------------------------------------------------------- #
# 1-4. Image upload success / PNG / JPEG / WEBP
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("fmt,content_type", [("PNG", "image/png"), ("JPEG", "image/jpeg"),
                                              ("WEBP", "image/webp")])
def test_upload_success_for_each_supported_format(monkeypatch, fmt, content_type):
    monkeypatch.setattr(vp, "analyze_chart_image", _fake_provider(
        {"chart_info": {"current_visible_price": 10.0}, "final_signal": {"action": "WAIT"}}))
    r = _upload(_png_bytes(fmt=fmt), filename=f"c.{fmt.lower()}", content_type=content_type)
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "tradingview_screenshot"
    assert body["screenshot"]["chart_info"]["current_visible_price"] == 10.0


# --------------------------------------------------------------------------- #
# 5. Invalid image rejected
# --------------------------------------------------------------------------- #

def test_invalid_image_bytes_rejected_422():
    r = _upload(b"not actually an image", filename="fake.png")
    assert r.status_code == 422
    assert "clearer" in r.json()["detail"].lower() or "screenshot" in r.json()["detail"].lower()


def test_disguised_svg_rejected_422():
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    r = _upload(svg, filename="chart.png", content_type="image/png")
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# 6. Oversized image rejected
# --------------------------------------------------------------------------- #

def test_oversized_image_rejected_422(monkeypatch):
    from apexinvest.api import screenshot as screenshot_mod
    monkeypatch.setattr(screenshot_mod, "MAX_IMAGE_BYTES", 100)
    r = _upload(_png_bytes(size=(64, 64)))
    assert r.status_code == 422
    assert "too large" in r.json()["detail"].lower()


# --------------------------------------------------------------------------- #
# 7. Missing image
# --------------------------------------------------------------------------- #

def test_missing_image_rejected():
    r = client.post("/v1/analyses/screenshot", data={"symbol": "COMI"})
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# 8. Vision provider failure modes
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("kind,expected_status", [
    ("unavailable", 503), ("auth", 503), ("model_error", 503), ("rate_limit", 429),
    ("timeout", 504), ("provider_error", 502),
])
def test_vision_provider_failure_modes_map_to_clear_status(monkeypatch, kind, expected_status):
    def _raise(image_bytes, fmt, metadata):
        raise vp.VisionError(kind, f"simulated {kind}")
    monkeypatch.setattr(vp, "analyze_chart_image", _raise)
    r = _upload(_png_bytes())
    assert r.status_code == expected_status
    assert "simulated" in r.json()["detail"]


def test_missing_api_key_reports_unavailable_not_a_crash(monkeypatch):
    monkeypatch.delenv("VISION_API_KEY", raising=False)
    monkeypatch.delenv("VISION_PROVIDER", raising=False)
    r = _upload(_png_bytes())
    assert r.status_code == 503


# --------------------------------------------------------------------------- #
# 9. Malformed AI JSON
# --------------------------------------------------------------------------- #

def test_malformed_ai_json_returns_controlled_error(monkeypatch):
    def _fake(image_bytes, fmt, metadata):
        raise vp.VisionError("malformed_response", "not valid json")
    monkeypatch.setattr(vp, "analyze_chart_image", _fake)
    r = _upload(_png_bytes())
    assert r.status_code == 502


def test_unknown_ai_fields_are_dropped_not_trusted(monkeypatch):
    monkeypatch.setattr(vp, "analyze_chart_image", _fake_provider({
        "chart_info": {"current_visible_price": 5.0},
        "final_signal": {"action": "WAIT"},
        "__inject__": {"strategies": "overwritten"},
        "plan": {"action": "BUY"},   # must never leak into the real plan
    }))
    r = _upload(_png_bytes())
    assert r.status_code == 200
    assert "__inject__" not in r.json()["screenshot"]
    assert "plan" not in r.json()["screenshot"]


# --------------------------------------------------------------------------- #
# 10-11. Missing / supplied symbol (OCR is never trusted over a supplied symbol)
# --------------------------------------------------------------------------- #

def test_missing_symbol_still_analyzes_screenshot_alone(monkeypatch):
    monkeypatch.setattr(vp, "analyze_chart_image", _fake_provider(
        {"chart_info": {"symbol": "COMI", "current_visible_price": 10.0}, "final_signal": {"action": "WAIT"}}))
    r = _upload(_png_bytes())
    assert r.status_code == 200
    assert r.json()["screenshot"]["chart_info"]["symbol"] == "COMI"   # OCR'd value kept
    assert r.json()["existing_apexinvest"] is None


def test_supplied_symbol_overrides_ocr_read_symbol(monkeypatch):
    monkeypatch.setattr(vp, "analyze_chart_image", _fake_provider(
        {"chart_info": {"symbol": "WRONG_OCR_READ", "current_visible_price": 10.0},
         "final_signal": {"action": "WAIT"}}))
    r = _upload(_png_bytes(), symbol="comi")
    assert r.status_code == 200
    assert r.json()["screenshot"]["chart_info"]["symbol"] == "COMI"


# --------------------------------------------------------------------------- #
# 12-13. Screenshot price extraction / unreadable price
# --------------------------------------------------------------------------- #

def test_screenshot_price_extracted_when_present(monkeypatch):
    monkeypatch.setattr(vp, "analyze_chart_image", _fake_provider(
        {"chart_info": {"current_visible_price": 12.16}, "final_signal": {"action": "WAIT"}}))
    r = _upload(_png_bytes())
    assert r.json()["screenshot"]["chart_info"]["current_visible_price"] == 12.16


def test_unreadable_price_stays_null_never_guessed(monkeypatch):
    monkeypatch.setattr(vp, "analyze_chart_image", _fake_provider(
        {"chart_info": {"current_visible_price": None}, "final_signal": {"action": "WAIT"},
         "notes": ["Current price: Not visible / Cannot determine from screenshot."]}))
    r = _upload(_png_bytes())
    body = r.json()
    assert body["screenshot"]["chart_info"]["current_visible_price"] is None
    assert body["data_discrepancy"] is None   # nothing to compare -> not fabricated as "consistent"


# --------------------------------------------------------------------------- #
# 14-17. Breakout / retest / pullback / failed-breakout scenarios pass through
# --------------------------------------------------------------------------- #

def test_breakout_scenario_passes_through_with_no_chase_language(monkeypatch):
    monkeypatch.setattr(vp, "analyze_chart_image", _fake_provider({
        "chart_info": {"current_visible_price": 0.86},
        "final_signal": {"action": "WAIT"},
        "trade_scenarios": {"breakout": {
            "resistance": 0.877, "trigger": "Close above 0.877",
            "confirmation": ["Close above resistance", "Volume confirmation if visible"],
            "status": "Watching"}},
    }))
    r = _upload(_png_bytes())
    b = r.json()["screenshot"]["trade_scenarios"]["breakout"]
    assert b["resistance"] == 0.877 and b["status"] == "Watching"


def test_retest_scenario_passes_through(monkeypatch):
    monkeypatch.setattr(vp, "analyze_chart_image", _fake_provider({
        "chart_info": {"current_visible_price": 0.88},
        "final_signal": {"action": "WAIT"},
        "trade_scenarios": {"breakout_retest": {
            "retest_zone": [0.875, 0.885], "status": "Retesting",
            "confirmation": ["Price holds zone"]}},
    }))
    r = _upload(_png_bytes())
    rt = r.json()["screenshot"]["trade_scenarios"]["breakout_retest"]
    assert rt["retest_zone"] == [0.875, 0.885]


def test_pullback_scenario_passes_through(monkeypatch):
    monkeypatch.setattr(vp, "analyze_chart_image", _fake_provider({
        "chart_info": {"current_visible_price": 13.0},
        "final_signal": {"action": "WAIT"},
        "trade_scenarios": {"pullback": {"zone": [12.0, 12.3], "status": "Watching",
                                         "invalidation": "Below 11.8"}},
    }))
    r = _upload(_png_bytes())
    pb = r.json()["screenshot"]["trade_scenarios"]["pullback"]
    assert pb["zone"] == [12.0, 12.3]


def test_failed_breakout_scenario_never_becomes_sell(monkeypatch):
    monkeypatch.setattr(vp, "analyze_chart_image", _fake_provider({
        "chart_info": {"current_visible_price": 0.86},
        "final_signal": {"action": "WAIT"},
        "trade_scenarios": {"failed_breakout": {
            "level": 0.877, "reason": "Broke above but failed to hold.",
            "status": "Failed", "action": "No new entry / wait for a new setup."}},
    }))
    r = _upload(_png_bytes())
    fb = r.json()["screenshot"]["trade_scenarios"]["failed_breakout"]
    assert fb["status"] == "Failed"
    assert "sell" not in (fb["action"] or "").lower()


# --------------------------------------------------------------------------- #
# 18. Data discrepancy (never silently reconciled)
# --------------------------------------------------------------------------- #

def test_data_discrepancy_flagged_when_prices_disagree():
    vision = VisionAnalysis.model_validate({"chart_info": {"current_visible_price": 12.16}})
    existing = {"plan": {"action": "WAIT"}, "data_source": {"price": 11.95}}
    d = vbuild.data_discrepancy(vision, existing)
    assert d["status"] == "discrepancy"
    assert d["screenshot_price"] == 12.16 and d["external_price"] == 11.95


def test_no_discrepancy_flag_when_prices_agree_closely():
    vision = VisionAnalysis.model_validate({"chart_info": {"current_visible_price": 12.10}})
    existing = {"plan": {"action": "WAIT"}, "data_source": {"price": 12.12}}
    d = vbuild.data_discrepancy(vision, existing)
    assert d["status"] == "consistent"


def test_no_discrepancy_computed_when_one_side_missing():
    vision = VisionAnalysis.model_validate({"chart_info": {"current_visible_price": None}})
    assert vbuild.data_discrepancy(vision, {"plan": {}, "data_source": {"price": 12.0}}) is None
    vision2 = VisionAnalysis.model_validate({"chart_info": {"current_visible_price": 12.0}})
    assert vbuild.data_discrepancy(vision2, None) is None


# --------------------------------------------------------------------------- #
# Comparison / alignment (never overrides the existing signal)
# --------------------------------------------------------------------------- #

def test_alignment_aligned_when_signals_match():
    vision = VisionAnalysis.model_validate({"final_signal": {"action": "BUY"}})
    existing = {"plan": {"action": "BUY"}}
    c = vbuild.compare_with_apexinvest(vision, existing)
    assert c["alignment"] == "Aligned"
    assert existing["plan"]["action"] == "BUY"   # untouched


def test_alignment_diverging_never_changes_existing_plan():
    vision = VisionAnalysis.model_validate({"final_signal": {"action": "AVOID"}})
    existing = {"plan": {"action": "BUY", "entry": 10.0, "stop": 9.0, "target": 12.0}}
    before = dict(existing["plan"])
    c = vbuild.compare_with_apexinvest(vision, existing)
    assert c["alignment"] == "Diverging"
    assert existing["plan"] == before   # comparison never mutates the existing plan


def test_alignment_insufficient_data_without_existing():
    vision = VisionAnalysis.model_validate({"final_signal": {"action": "WAIT"}})
    c = vbuild.compare_with_apexinvest(vision, None)
    assert c["alignment"] == "Insufficient Data"


# --------------------------------------------------------------------------- #
# 19-21. Existing BUY / WAIT / AVOID engine output is unchanged by this feature
# --------------------------------------------------------------------------- #

def _ohlc(closes, volume=1_000_000.0):
    closes = np.asarray(closes, dtype=float)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    highs = np.maximum(opens, closes) * 1.004
    lows = np.minimum(opens, closes) * 0.996
    return pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes,
                         "volume": np.full(len(closes), volume)})


def _fetcher(df, symbol="TEST"):
    def fetch(_sym):
        meta = {"symbol": symbol, "currency": "EGP", "timeframe": "1d", "bars": len(df),
                "last_close": float(df["close"].iloc[-1]), "source": "test",
                "provides": list(yahoo_egx.PROVIDES)}
        return df, meta
    return fetch


@pytest.mark.parametrize("closes,expected_actions", [
    (np.tile([9.6, 10.4, 9.7, 10.3, 9.55, 10.45, 9.65, 10.35], 28), ("BUY", "WAIT")),
    (np.linspace(20.0, 10.0, 220), ("AVOID",)),
])
def test_existing_plan_action_unaffected_by_screenshot_module_import(closes, expected_actions):
    """Merely having apexinvest.vision imported/used elsewhere in the process
    must not change analyze_symbol's own output (import-time side effects,
    global monkeypatching, shared state -- none of that should exist)."""
    df = _ohlc(closes)
    out = analyze_symbol("TEST", Objective.SWING, fetcher=_fetcher(df))
    assert out["plan"]["action"] in expected_actions


# --------------------------------------------------------------------------- #
# 22. This layer never imports the EODHD/market-data path
# --------------------------------------------------------------------------- #

def test_vision_layer_never_imports_eodhd_or_feed():
    import ast
    import inspect

    import apexinvest.api.screenshot as screenshot_mod
    import apexinvest.vision.build as build_mod
    import apexinvest.vision.provider as provider_mod

    forbidden = ("eodhd_egx", "market.feed", "yahoo_egx", "tradingview_egx")
    for mod in (provider_mod, build_mod, screenshot_mod):
        tree = ast.parse(inspect.getsource(mod))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
                imported.update(f"{node.module}.{a.name}" for a in node.names)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
        joined = " ".join(imported)
        assert not any(f in joined for f in forbidden), (mod.__name__, imported)
