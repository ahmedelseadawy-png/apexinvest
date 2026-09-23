"""TradingView Screenshot Analysis — additive visual-confirmation layer.

Adds exactly one new route, ``POST /v1/analyses/screenshot``, on top of the
existing FastAPI app. Nothing existing is changed: this module never calls
EODHD/Yahoo/the CSV ingest path, never touches ``strategies.py``/``risk.py``/
``entry.py``/``regime.py``/``structure.py``, and never writes back into
``analyze_symbol``'s result -- when a symbol is supplied it fetches the
existing analysis purely read-only, for a side-by-side comparison (see
``apexinvest/vision/build.py``).

Source priority: the uploaded screenshot is the PRIMARY source for current
visual technical analysis; any ApexInvest/EODHD data fetched here is
SECONDARY, used only for the comparison + explicit discrepancy check, never
to silently override what the screenshot shows (see ``vision/build.py``).

The image itself is processed in memory only and never persisted or logged.
"""
from __future__ import annotations

import io
import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image
from pydantic import ValidationError

from ..domain import Objective
from ..service import analyze_symbol
from ..vision import build as vbuild
from ..vision import provider as vision_provider
from ..vision.schema import VisionAnalysis

router = APIRouter()
_log = logging.getLogger("apexinvest")

MAX_IMAGE_BYTES = 8 * 1024 * 1024
_ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}

_ERROR_STATUS = {
    "unavailable": 503,
    "auth": 503,
    "model_error": 503,
    "rate_limit": 429,
    "timeout": 504,
    "provider_error": 502,
    "malformed_response": 502,
}


def _sniff_image_format(data: bytes) -> str | None:
    """Validate the actual bytes, not the declared filename/content-type
    (spec section 8) -- rejects SVG/HTML/PDF/executables disguised with an
    image extension. Returns None if the bytes aren't a readable PNG/JPEG/WEBP."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        with Image.open(io.BytesIO(data)) as im2:
            fmt = im2.format
    except Exception:
        return None
    return fmt if fmt in _ALLOWED_FORMATS else None


@router.post("/v1/analyses/screenshot")
async def analyze_screenshot(
    image: UploadFile = File(...),
    symbol: str | None = Form(None),
    timeframe: str | None = Form(None),
    objective: Objective = Form(Objective.SWING),
    position_qty: float | None = Form(None),
    average_price: float | None = Form(None),
):
    data = await image.read()
    if not data:
        raise HTTPException(status_code=422, detail="No image received.")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=422, detail=(
            f"Image too large (max {MAX_IMAGE_BYTES // (1024 * 1024)}MB). "
            "Export a smaller screenshot and try again."))
    img_format = _sniff_image_format(data)
    if img_format is None:
        raise HTTPException(status_code=422, detail=(
            "Chart could not be analyzed. Please upload a clearer TradingView "
            "screenshot (PNG, JPEG, or WEBP)."))

    sym = (symbol or "").strip().upper() or None
    tf = (timeframe or "").strip() or None

    try:
        raw = vision_provider.analyze_chart_image(
            data, img_format, {"symbol": sym, "timeframe": tf, "objective": objective.value})
    except vision_provider.VisionError as e:
        raise HTTPException(status_code=_ERROR_STATUS.get(e.kind, 502), detail=e.message)

    try:
        parsed = VisionAnalysis.model_validate(raw)
    except ValidationError:
        raise HTTPException(status_code=502, detail=(
            "The vision analysis returned an unreadable response. Please try again."))

    # A user-supplied symbol is metadata, not something to override with OCR
    # off the image (spec section 7: "do not blindly trust OCR if the user
    # explicitly supplies the symbol").
    if sym:
        parsed.chart_info.symbol = sym
    if tf and not parsed.chart_info.timeframe:
        parsed.chart_info.timeframe = tf

    # Screenshot analysis must work independently of market data (spec
    # section 28): only fetch the existing engine's view when a symbol was
    # given, and never let a market-data failure break the screenshot result.
    existing: dict | None = None
    if sym:
        try:
            existing = analyze_symbol(sym, objective)
        except Exception:
            existing = None

    comparison = vbuild.compare_with_apexinvest(parsed, existing)
    discrepancy = vbuild.data_discrepancy(parsed, existing)
    position = vbuild.position_view(position_qty, average_price, parsed)

    return {
        "source": "tradingview_screenshot",
        "screenshot": parsed.model_dump(),
        "existing_apexinvest": vbuild.existing_summary(existing),
        "comparison": comparison,
        "data_discrepancy": discrepancy,
        "position": position,
    }
