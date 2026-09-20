"""Thin additive layer for the mobile web app.  NO trading logic lives here.

Two things are added on top of the existing FastAPI app, and nothing existing is
changed:

1. ``POST /v1/analyses/csv`` — CSV import.  The file is parsed by the existing
   ``ingest.ingest`` (same OHLCV column aliases, same validation as
   ``POST /v1/uploads``) and the candles are handed to the existing
   ``service.analyze_symbol`` through its ``fetcher`` hook — i.e. the *identical*
   engine path the live-feed analysis (``GET /v1/analyses/auto/{symbol}``) uses.
   The only thing that differs is where the candles come from.  This route only
   (a) orients the rows oldest -> newest if the file's time column says they are
   newest-first, and (b) relabels the data-source metadata so the UI says the data
   came from the user's file, not from Yahoo.

2. ``/m`` — static hosting of the mobile-first web app (``mobile/`` folder next to
   ``frontend_app.html``), gzip-compressed and served with revalidation so an
   update is never hidden by a stale cache.  The desktop ``/`` and ``/app`` routes
   are untouched.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from ..domain import Objective
from ..ingest import files as ingest
from ..market import yahoo_egx
from ..service import analyze_symbol

router = APIRouter()

_SYMBOL_RE = re.compile(r"^[A-Za-z0-9._\-]{1,16}$")
_TIME_COLS = ("time", "date", "datetime", "timestamp")


def _read_time_bounds(filename: str, data: bytes) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """First and last value of the file's time column (metadata only), or (None, None).

    TradingView exports ``time`` as unix seconds or an ISO string; both are handled.
    Used solely to decide the row order and to label "data as of"."""
    try:
        name = filename.lower()
        if name.endswith((".xlsx", ".xls")):
            raw = pd.read_excel(io.BytesIO(data))
        else:
            raw = pd.read_csv(io.BytesIO(data), sep=None, engine="python")
        col = next((c for c in raw.columns if str(c).strip().lower() in _TIME_COLS), None)
        if col is None:
            return None, None
        s = raw[col].dropna()
        if s.empty:
            return None, None
        if pd.api.types.is_numeric_dtype(s):
            mx = float(s.abs().max())
            unit = "ms" if mx > 1e11 else "s"
            ts = pd.to_datetime(s, unit=unit, utc=True, errors="coerce")
        else:
            ts = pd.to_datetime(s, utc=True, errors="coerce")
        ts = ts.dropna()
        if ts.empty:
            return None, None
        return ts.iloc[0], ts.iloc[-1]
    except Exception:
        return None, None


@router.post("/v1/analyses/csv")
async def analyze_csv(
    file: UploadFile = File(...),
    symbol: str = Form(...),
    objective: Objective = Form(Objective.SWING),
):
    """Analyze an uploaded daily OHLCV file (e.g. a TradingView export) with the
    same engine path as the live-feed analysis. Nothing is invented: a file
    without usable OHLC columns is rejected with the reason."""
    sym = (symbol or "").strip().upper()
    if not _SYMBOL_RE.match(sym):
        raise HTTPException(status_code=422, detail="Enter a ticker (letters/digits), e.g. COMI.")
    data = await file.read()
    filename = file.filename or "upload.csv"
    result = ingest.ingest(filename, data)
    if not result.ok:
        raise HTTPException(status_code=422, detail=result.error)
    if result.kind != "candles" or result.candles is None:
        raise HTTPException(status_code=422, detail=(
            "This file has no Open/High/Low/Close columns, so there are no candles to analyze. "
            "Export the chart data from TradingView (time, open, high, low, close, volume)."))

    df = result.candles.reset_index(drop=True)
    first_ts, last_ts = _read_time_bounds(filename, data)
    order = "as-given"
    if first_ts is not None and last_ts is not None and first_ts > last_ts:
        df = df.iloc[::-1].reset_index(drop=True)          # newest-first file -> oldest-first
        first_ts, last_ts = last_ts, first_ts
        order = "reversed (file was newest-first)"
    elif first_ts is not None:
        order = "oldest-first"
    as_of = last_ts.date().isoformat() if last_ts is not None else None

    def fetcher(_symbol: str):
        meta = {
            "symbol": sym, "currency": "EGP", "exchange": "EGX", "timeframe": "1d",
            "bars": len(df), "last_close": float(df["close"].iloc[-1]),
            "as_of": as_of, "source": f"Imported file: {filename}", "delayed": True,
            "adjusted": False, "provides": list(yahoo_egx.PROVIDES),
        }
        return df, meta

    try:
        out = analyze_symbol(sym, objective, fetcher=fetcher)
    except Exception as e:  # engine/data error -> readable 422, not a crash
        raise HTTPException(status_code=422, detail=f"Could not analyze this file: {e}")

    # Relabel data-source metadata: the service stamps a Yahoo provider label on
    # every daily series; for an imported file that would be untrue.
    ds = out.get("data_source") or {}
    ds["provider"] = "Imported file (user-supplied candles)"
    ds["source"] = f"Imported file: {filename}"
    ds["price_source"] = "last close in the imported file"
    out["data_source"] = ds
    out["csv_import"] = {"filename": filename, "rows": int(len(df)), "order": order, "as_of": as_of}
    return out


# ------------------------------------------------------------------ static /m
_MOBILE_DIR = Path(__file__).resolve().parents[2] / "mobile"


class _RevalidateHeaders:
    """ASGI wrapper: static files are always revalidated (ETag), never served stale."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_wrap(message):
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"cache-control"]
                headers.append((b"cache-control", b"no-cache"))
                message = {**message, "headers": headers}
            await send(message)

        return await self.app(scope, receive, send_wrap)


def build_mobile_app() -> Starlette | None:
    """The static mobile web app (or None if the ``mobile/`` folder is absent)."""
    if not _MOBILE_DIR.is_dir():
        return None
    static = StaticFiles(directory=str(_MOBILE_DIR), html=True)
    return Starlette(
        routes=[Mount("/", app=_RevalidateHeaders(static))],
        middleware=[Middleware(GZipMiddleware, minimum_size=500)],
    )
