"""Vision provider abstraction for TradingView screenshot analysis.

The repo has no existing AI/vision integration (checked before adding this:
no OpenAI/Anthropic SDK, no provider abstraction anywhere in the codebase),
so this is a small, dependency-free HTTP client (reuses ``requests``,
already a project dependency) behind one function: ``analyze_chart_image``.

Configuration is entirely via environment variables, mirroring how
``market/feed.py`` reads ``DATA_PROVIDER``/the EODHD token -- no secrets in
code, nothing committed:

    VISION_PROVIDER   "anthropic" | "openai"   (unset/empty => feature disabled)
    VISION_API_KEY    the provider's API key    (never logged, never returned)
    VISION_MODEL      optional model override (each provider has a default)

This module NEVER touches the EODHD adapter, market/feed.py, or any of the
existing engines -- it only ever sends the screenshot bytes to the
configured AI vision endpoint and returns that provider's raw parsed JSON
(as a plain dict) for ``apexinvest/vision/schema.py`` to validate. On any
failure it raises ``VisionError`` with a machine-readable ``kind`` so the
API layer can map it to a clear, specific user-facing error (spec section
23) instead of a generic 500.
"""
from __future__ import annotations

import base64
import json
import os
import re

import requests

from . import prompt as prompt_mod

_TIMEOUT_SECONDS = 45
_DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"
_DEFAULT_OPENAI_MODEL = "gpt-4o"

_MEDIA_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


class VisionError(Exception):
    """kind is one of: unavailable | auth | rate_limit | timeout | provider_error |
    malformed_response -- used by the API layer to pick the right HTTP status
    and message; never exposes the raw provider error body (may contain
    account/billing details) to the client."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


def _extract_json(text: str) -> dict:
    """The instructions ask for a bare JSON object, but some models still wrap
    it in a ```json ... ``` fence or add a stray sentence -- find the first
    top-level {...} block rather than failing on strict-parse alone."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass
    brace = re.search(r"\{.*\}", text, re.S)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass
    raise VisionError("malformed_response", "The vision provider's response was not valid JSON.")


def _call_anthropic(image_b64: str, media_type: str, metadata: dict, api_key: str) -> dict:
    model = os.environ.get("VISION_MODEL") or _DEFAULT_ANTHROPIC_MODEL
    body = {
        "model": model,
        "max_tokens": 4096,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                {"type": "text", "text": prompt_mod.INSTRUCTIONS + "\n\n" + prompt_mod.build_user_context(metadata)},
            ],
        }],
    }
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json=body, timeout=_TIMEOUT_SECONDS,
        )
    except requests.Timeout:
        raise VisionError("timeout", "The vision provider timed out.")
    except requests.RequestException as e:
        raise VisionError("provider_error", f"Could not reach the vision provider: {e}")
    _raise_for_status(resp)
    data = resp.json()
    try:
        text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
    except Exception:
        raise VisionError("malformed_response", "The vision provider's response had an unexpected shape.")
    if not text:
        raise VisionError("malformed_response", "The vision provider returned an empty response.")
    return _extract_json(text)


def _call_openai(image_b64: str, media_type: str, metadata: dict, api_key: str) -> dict:
    model = os.environ.get("VISION_MODEL") or _DEFAULT_OPENAI_MODEL
    body = {
        "model": model,
        "max_tokens": 4096,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_mod.INSTRUCTIONS + "\n\n" + prompt_mod.build_user_context(metadata)},
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_b64}"}},
            ],
        }],
    }
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "content-type": "application/json"},
            json=body, timeout=_TIMEOUT_SECONDS,
        )
    except requests.Timeout:
        raise VisionError("timeout", "The vision provider timed out.")
    except requests.RequestException as e:
        raise VisionError("provider_error", f"Could not reach the vision provider: {e}")
    _raise_for_status(resp)
    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except Exception:
        raise VisionError("malformed_response", "The vision provider's response had an unexpected shape.")
    if not text:
        raise VisionError("malformed_response", "The vision provider returned an empty response.")
    return _extract_json(text)


def _raise_for_status(resp: "requests.Response") -> None:
    if resp.status_code == 200:
        return
    if resp.status_code in (401, 403):
        raise VisionError("auth", "The vision provider rejected the configured API key.")
    if resp.status_code == 429:
        raise VisionError("rate_limit", "The vision provider is rate-limiting requests. Try again shortly.")
    if resp.status_code in (408, 504):
        raise VisionError("timeout", "The vision provider timed out.")
    raise VisionError("provider_error", f"The vision provider returned HTTP {resp.status_code}.")


_PROVIDERS = {"anthropic": _call_anthropic, "openai": _call_openai}


def analyze_chart_image(image_bytes: bytes, image_format: str, metadata: dict) -> dict:
    """Send the screenshot to the configured vision provider and return its
    raw parsed JSON (not yet validated -- see schema.py). Never sends the
    image anywhere else (no EODHD/Yahoo/CSV code path is touched). Raises
    VisionError on any failure; never raises a bare/unhandled exception."""
    provider = (os.environ.get("VISION_PROVIDER") or "").strip().lower()
    api_key = (os.environ.get("VISION_API_KEY") or "").strip()
    if not provider or not api_key:
        raise VisionError("unavailable", "TradingView screenshot analysis is not configured on this server.")
    call = _PROVIDERS.get(provider)
    if call is None:
        raise VisionError("unavailable", f"Unknown VISION_PROVIDER '{provider}'.")
    media_type = _MEDIA_TYPES.get(image_format)
    if media_type is None:
        raise VisionError("provider_error", f"Unsupported image format '{image_format}'.")
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    return call(image_b64, media_type, metadata, api_key)
