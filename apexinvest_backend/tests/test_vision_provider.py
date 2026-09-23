"""Tests for the Anthropic-backed vision provider configuration and the
official SDK call path (apexinvest/vision/provider.py).

Covers: Anthropic as default/recommended provider, the current-model
default, missing API key, missing/invalid model, and a successful mocked
Anthropic vision response sent through the official `anthropic` SDK. Also
reconfirms (imported from test_screenshot_analysis's fixtures) that the
existing ApexInvest engine output is unaffected by anything here.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from apexinvest.vision import provider as vp


def _fake_response(text: str):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def _api_error(cls, status_code, message="error"):
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    if cls is anthropic.APITimeoutError:
        return cls(request=req)
    if cls is anthropic.APIConnectionError:
        return cls(message=message, request=req)
    resp = httpx2.Response(status_code, request=req,
                           json={"type": "error", "error": {"type": "x", "message": message}})
    return cls(message, response=resp, body=None)


# --------------------------------------------------------------------------- #
# Anthropic is the default/recommended provider + current-model default
# --------------------------------------------------------------------------- #

def test_anthropic_is_the_recommended_default_model():
    assert vp._DEFAULT_ANTHROPIC_MODEL == "claude-opus-5"
    assert vp._resolve_model("anthropic") == "claude-opus-5"


def test_vision_model_env_override_takes_precedence(monkeypatch):
    monkeypatch.setenv("VISION_MODEL", "claude-sonnet-5")
    assert vp._resolve_model("anthropic") == "claude-sonnet-5"


def test_blank_vision_model_falls_back_to_default_not_an_error(monkeypatch):
    monkeypatch.setenv("VISION_MODEL", "   ")
    assert vp._resolve_model("anthropic") == vp._DEFAULT_ANTHROPIC_MODEL


# --------------------------------------------------------------------------- #
# Configuration errors -- clear, specific, never a bare crash
# --------------------------------------------------------------------------- #

def test_missing_provider_is_a_clear_unavailable_error(monkeypatch):
    monkeypatch.delenv("VISION_PROVIDER", raising=False)
    monkeypatch.delenv("VISION_API_KEY", raising=False)
    with pytest.raises(vp.VisionError) as exc:
        vp.analyze_chart_image(b"x", "PNG", {})
    assert exc.value.kind == "unavailable"
    assert "VISION_PROVIDER" in exc.value.message


def test_unknown_provider_is_a_clear_unavailable_error(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "not-a-real-provider")
    monkeypatch.setenv("VISION_API_KEY", "sk-whatever")
    with pytest.raises(vp.VisionError) as exc:
        vp.analyze_chart_image(b"x", "PNG", {})
    assert exc.value.kind == "unavailable"
    assert "not-a-real-provider" in exc.value.message


def test_missing_api_key_is_a_clear_unavailable_error(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "anthropic")
    monkeypatch.delenv("VISION_API_KEY", raising=False)
    with pytest.raises(vp.VisionError) as exc:
        vp.analyze_chart_image(b"x", "PNG", {})
    assert exc.value.kind == "unavailable"
    assert "VISION_API_KEY" in exc.value.message


def test_invalid_model_maps_to_model_error(monkeypatch):
    """A model Anthropic rejects (typo'd / deprecated / inaccessible) must
    surface as a distinct, actionable 'model_error' -- not a generic outage."""
    monkeypatch.setenv("VISION_PROVIDER", "anthropic")
    monkeypatch.setenv("VISION_API_KEY", "sk-test-key")
    monkeypatch.setenv("VISION_MODEL", "claude-totally-made-up")

    class FakeMessages:
        def create(self, **kwargs):
            assert kwargs["model"] == "claude-totally-made-up"
            raise _api_error(anthropic.NotFoundError, 404, "model: claude-totally-made-up")

    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    with pytest.raises(vp.VisionError) as exc:
        vp.analyze_chart_image(b"x", "PNG", {})
    assert exc.value.kind == "model_error"
    assert "claude-totally-made-up" in exc.value.message


def test_invalid_api_key_maps_to_auth_error(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "anthropic")
    monkeypatch.setenv("VISION_API_KEY", "sk-bad-key")

    class FakeMessages:
        def create(self, **kwargs):
            raise _api_error(anthropic.AuthenticationError, 401, "invalid x-api-key")

    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    with pytest.raises(vp.VisionError) as exc:
        vp.analyze_chart_image(b"x", "PNG", {})
    assert exc.value.kind == "auth"


@pytest.mark.parametrize("cls,status,kind", [
    (anthropic.RateLimitError, 429, "rate_limit"),
    (anthropic.APIStatusError, 500, "provider_error"),
])
def test_other_anthropic_failures_map_to_expected_kinds(monkeypatch, cls, status, kind):
    monkeypatch.setenv("VISION_PROVIDER", "anthropic")
    monkeypatch.setenv("VISION_API_KEY", "sk-test-key")

    class FakeMessages:
        def create(self, **kwargs):
            raise _api_error(cls, status)

    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    with pytest.raises(vp.VisionError) as exc:
        vp.analyze_chart_image(b"x", "PNG", {})
    assert exc.value.kind == kind


def test_timeout_maps_to_timeout_kind(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "anthropic")
    monkeypatch.setenv("VISION_API_KEY", "sk-test-key")

    class FakeMessages:
        def create(self, **kwargs):
            raise _api_error(anthropic.APITimeoutError, None)

    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    with pytest.raises(vp.VisionError) as exc:
        vp.analyze_chart_image(b"x", "PNG", {})
    assert exc.value.kind == "timeout"


# --------------------------------------------------------------------------- #
# Successful mocked Anthropic vision response, through the official SDK path
# --------------------------------------------------------------------------- #

def test_successful_mocked_anthropic_vision_response_sends_image_and_parses_json(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "anthropic")
    monkeypatch.setenv("VISION_API_KEY", "sk-test-key")
    monkeypatch.setenv("VISION_MODEL", "claude-opus-5")
    captured = {}

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            payload = {"chart_info": {"current_visible_price": 12.16},
                       "final_signal": {"action": "WAIT"}}
            return _fake_response(json.dumps(payload))

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)

    result = vp.analyze_chart_image(b"\x89PNGfakebytes", "PNG", {"symbol": "COMI"})

    assert result["chart_info"]["current_visible_price"] == 12.16
    assert captured["client_kwargs"]["api_key"] == "sk-test-key"
    assert captured["model"] == "claude-opus-5"
    content = captured["messages"][0]["content"]
    image_block = next(b for b in content if b["type"] == "image")
    assert image_block["source"]["type"] == "base64"
    assert image_block["source"]["media_type"] == "image/png"
    import base64
    assert base64.b64decode(image_block["source"]["data"]) == b"\x89PNGfakebytes"
    text_block = next(b for b in content if b["type"] == "text")
    assert "COMI" in text_block["text"]


def test_malformed_json_response_is_a_clear_error(monkeypatch):
    monkeypatch.setenv("VISION_PROVIDER", "anthropic")
    monkeypatch.setenv("VISION_API_KEY", "sk-test-key")

    class FakeMessages:
        def create(self, **kwargs):
            return _fake_response("not json at all, sorry")

    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    with pytest.raises(vp.VisionError) as exc:
        vp.analyze_chart_image(b"x", "PNG", {})
    assert exc.value.kind == "malformed_response"
