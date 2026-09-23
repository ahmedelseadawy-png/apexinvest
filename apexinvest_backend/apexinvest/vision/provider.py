"""Vision provider abstraction for TradingView screenshot analysis.

Anthropic is the default/recommended provider (calls go through the official
``anthropic`` Python SDK, not raw HTTP -- see the client construction in
``_call_anthropic``). OpenAI remains available as a secondary option behind
the same interface, reached over plain HTTP since no OpenAI SDK is otherwise
used in this project.

Configuration is entirely via environment variables, mirroring how
``market/feed.py`` reads ``DATA_PROVIDER``/the EODHD token -- no secrets in
code, nothing committed:

    VISION_PROVIDER   "anthropic" | "openai"   (unset/empty => feature disabled)
    VISION_API_KEY    the provider's API key    (never logged, never returned)
    VISION_MODEL      optional model override (each provider has a current,
                       non-deprecated default -- see _DEFAULT_ANTHROPIC_MODEL)

This module NEVER touches the EODHD adapter, market/feed.py, or any of the
existing engines -- it only ever sends the screenshot bytes to the
configured AI vision endpoint and returns that provider's raw parsed JSON
(as a plain dict) for ``apexinvest/vision/schema.py`` to validate. On any
failure it raises ``VisionError`` with a machine-readable ``kind`` so the
API layer can map it to a clear, specific user-facing error (spec section
23) instead of a generic 500 -- including a dedicated ``model_error`` kind
when VISION_MODEL is set to something the provider rejects (unknown/
deprecated/inaccessible model id), so a bad model config never looks like a
generic outage.
"""
from __future__ import annotations

import base64
import json
import os
import re

import anthropic
import requests

from . import prompt as prompt_mod

_TIMEOUT_SECONDS = 45
# claude-opus-5 verified against Anthropic's official docs on 2026-09-23:
# https://platform.claude.com/docs/en/models/opus-5/overview -- exact Claude
# API model ID, status "Active (legacy)" (not deprecated/retired; retirement
# not sooner than 2027-07-24), input->output "Text and images -> text"
# (vision-capable), available on the Claude API (Messages API) among other
# platforms. Anthropic's current flagship recommendation is Claude Opus 5.5
# (claude-opus-5-5); claude-opus-5 remains fully supported and is kept here
# as the shipped default -- override per-deployment with VISION_MODEL, e.g.
# claude-opus-5-5 for the latest flagship, or claude-sonnet-5 /
# claude-haiku-4-5 for lower cost (both verified real, current model IDs at
# https://platform.claude.com/docs/en/about-claude/models/overview).
_DEFAULT_ANTHROPIC_MODEL = "claude-opus-5"
_DEFAULT_OPENAI_MODEL = "gpt-4o"
_DEFAULT_MODELS = {"anthropic": _DEFAULT_ANTHROPIC_MODEL, "openai": _DEFAULT_OPENAI_MODEL}

_MEDIA_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}


class VisionError(Exception):
    """kind is one of: unavailable | auth | model_error | rate_limit | timeout |
    provider_error | malformed_response -- used by the API layer to pick the
    right HTTP status and message; never exposes the raw provider error body
    (may contain account/billing details) to the client."""

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


def _call_anthropic(image_b64: str, media_type: str, metadata: dict, api_key: str, model: str) -> dict:
    """Sends the screenshot to Anthropic as an image content block via the
    official SDK (client.messages.create) and returns the parsed JSON text
    response. Every SDK exception is mapped to a specific VisionError kind
    (never a bare/unhandled exception) so a misconfigured VISION_MODEL or
    VISION_API_KEY produces a clear, actionable message rather than a
    generic failure."""
    client = anthropic.Anthropic(api_key=api_key, timeout=_TIMEOUT_SECONDS, max_retries=2)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                    {"type": "text", "text": prompt_mod.INSTRUCTIONS + "\n\n" + prompt_mod.build_user_context(metadata)},
                ],
            }],
        )
    except anthropic.NotFoundError:
        raise VisionError("model_error", (
            f"The configured VISION_MODEL '{model}' was not found or is not available to this "
            "account. Check VISION_MODEL against Anthropic's current model list."))
    except anthropic.AuthenticationError:
        raise VisionError("auth", "The vision provider rejected the configured VISION_API_KEY.")
    except anthropic.PermissionDeniedError:
        raise VisionError("auth", (
            f"The configured VISION_API_KEY does not have permission to use model '{model}'."))
    except anthropic.RateLimitError:
        raise VisionError("rate_limit", "The vision provider is rate-limiting requests. Try again shortly.")
    except anthropic.APITimeoutError:
        raise VisionError("timeout", "The vision provider timed out.")
    except anthropic.APIConnectionError as e:
        raise VisionError("provider_error", f"Could not reach the vision provider: {e}")
    except anthropic.APIStatusError as e:
        raise VisionError("provider_error", f"The vision provider returned HTTP {e.status_code}.")

    text = "".join(block.text for block in response.content if block.type == "text")
    if not text:
        raise VisionError("malformed_response", "The vision provider returned an empty response.")
    return _extract_json(text)


def _call_openai(image_b64: str, media_type: str, metadata: dict, api_key: str, model: str) -> dict:
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
    _raise_for_status(resp, model)
    data = resp.json()
    try:
        text = data["choices"][0]["message"]["content"]
    except Exception:
        raise VisionError("malformed_response", "The vision provider's response had an unexpected shape.")
    if not text:
        raise VisionError("malformed_response", "The vision provider returned an empty response.")
    return _extract_json(text)


def _raise_for_status(resp: "requests.Response", model: str) -> None:
    if resp.status_code == 200:
        return
    if resp.status_code == 404:
        raise VisionError("model_error", (
            f"The configured VISION_MODEL '{model}' was not found or is not available to this account."))
    if resp.status_code in (401, 403):
        raise VisionError("auth", "The vision provider rejected the configured API key.")
    if resp.status_code == 429:
        raise VisionError("rate_limit", "The vision provider is rate-limiting requests. Try again shortly.")
    if resp.status_code in (408, 504):
        raise VisionError("timeout", "The vision provider timed out.")
    raise VisionError("provider_error", f"The vision provider returned HTTP {resp.status_code}.")


_PROVIDERS = {"anthropic": _call_anthropic, "openai": _call_openai}


def _resolve_model(provider: str) -> str:
    """VISION_MODEL is always optional: unset/blank falls back to a current,
    non-deprecated default for the selected provider (spec: never guess an
    obsolete model, and a missing VISION_MODEL must never break the feature).
    An explicitly-set but wrong model is instead caught at call time and
    raised as a clear 'model_error' (see _call_anthropic/_raise_for_status)."""
    configured = (os.environ.get("VISION_MODEL") or "").strip()
    return configured or _DEFAULT_MODELS[provider]


def analyze_chart_image(image_bytes: bytes, image_format: str, metadata: dict) -> dict:
    """Send the screenshot to the configured vision provider and return its
    raw parsed JSON (not yet validated -- see schema.py). Never sends the
    image anywhere else (no EODHD/Yahoo/CSV code path is touched). Raises
    VisionError with a specific, actionable message on any configuration
    problem (missing/unknown provider, missing API key, bad model) or
    provider failure; never raises a bare/unhandled exception."""
    provider = (os.environ.get("VISION_PROVIDER") or "").strip().lower()
    if not provider:
        raise VisionError("unavailable", (
            "TradingView screenshot analysis is not configured on this server "
            "(VISION_PROVIDER is not set)."))
    call = _PROVIDERS.get(provider)
    if call is None:
        raise VisionError("unavailable", (
            f"Unknown VISION_PROVIDER '{provider}'. Supported providers: "
            f"{', '.join(sorted(_PROVIDERS))}."))
    api_key = (os.environ.get("VISION_API_KEY") or "").strip()
    if not api_key:
        raise VisionError("unavailable", (
            f"TradingView screenshot analysis is not configured: VISION_API_KEY is missing "
            f"for VISION_PROVIDER={provider}. Set it as a server-side secret."))
    media_type = _MEDIA_TYPES.get(image_format)
    if media_type is None:
        raise VisionError("provider_error", f"Unsupported image format '{image_format}'.")
    model = _resolve_model(provider)
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    return call(image_b64, media_type, metadata, api_key, model)
