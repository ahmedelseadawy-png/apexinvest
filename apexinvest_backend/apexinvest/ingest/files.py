"""File / document ingest engine.

Real extraction, honest about uncertainty:
  * CSV / Excel with OHLCV-like columns -> a candles DataFrame + provenance.
  * CSV / Excel without OHLCV -> generic table, best-effort financial metrics.
  * PDF -> text + tables (pdfplumber) with page provenance; financial metrics
    only when clearly labelled.
  * Anything unreadable is rejected with a reason. Nothing is fabricated: a
    metric that isn't found is simply absent, not guessed.

Security posture (enforced here + at the API boundary): validate by declared
type, cap size, never execute, and treat all extracted text as data.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

MAX_BYTES = 15 * 1024 * 1024

OHLCV_ALIASES = {
    "open": ["open", "o"],
    "high": ["high", "h"],
    "low": ["low", "l"],
    "close": ["close", "c", "adj close", "adj_close", "close/last"],
    "volume": ["volume", "vol", "v"],
}

# Regexes for best-effort financial metric extraction from text/tables.
_PCT = r"(-?\d+(?:\.\d+)?)\s*%"
FIN_PATTERNS = {
    "revenue_growth": re.compile(r"revenue\s+growth[^%\d\-]*" + _PCT, re.I),
    "net_margin": re.compile(r"net\s+(?:profit\s+)?margin[^%\d\-]*" + _PCT, re.I),
    "debt_to_equity": re.compile(r"debt[\s/\-]*to[\s/\-]*equity[^0-9\-]*(-?\d+(?:\.\d+)?)", re.I),
}


@dataclass
class Extraction:
    kind: str                       # "candles" | "table" | "document" | "rejected"
    ok: bool
    candles: pd.DataFrame | None = None
    fundamentals: dict[str, Any] = field(default_factory=dict)
    text_preview: str = ""
    tables: int = 0
    provenance: list[dict] = field(default_factory=list)
    error: str = ""

    def summary(self) -> dict:
        d = {
            "kind": self.kind, "ok": self.ok, "tables": self.tables,
            "fundamentals": self.fundamentals, "provenance": self.provenance,
            "error": self.error, "text_preview": self.text_preview[:400],
        }
        if self.candles is not None:
            d["candles_rows"] = len(self.candles)
        return d


def _normalize_columns(df: pd.DataFrame) -> dict[str, str]:
    """Map canonical OHLCV name -> actual column name present, if any."""
    lower = {str(c).strip().lower(): c for c in df.columns}
    found = {}
    for canon, aliases in OHLCV_ALIASES.items():
        for a in aliases:
            if a in lower:
                found[canon] = lower[a]
                break
    return found


def _extract_financials_from_text(text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, pat in FIN_PATTERNS.items():
        m = pat.search(text)
        if m:
            val = float(m.group(1))
            out[key] = val / 100.0 if key in ("revenue_growth", "net_margin") else val
    return out


def ingest(filename: str, data: bytes, declared_kind: str | None = None) -> Extraction:
    if len(data) == 0:
        return Extraction("rejected", False, error="File is empty.")
    if len(data) > MAX_BYTES:
        return Extraction("rejected", False, error=f"File exceeds {MAX_BYTES // (1024*1024)} MB limit.")

    name = filename.lower()
    try:
        if name.endswith(".csv") or name.endswith(".tsv"):
            return _ingest_tabular(pd.read_csv(io.BytesIO(data), sep=None, engine="python"), filename)
        if name.endswith((".xlsx", ".xls")):
            return _ingest_tabular(pd.read_excel(io.BytesIO(data)), filename)
        if name.endswith(".pdf"):
            return _ingest_pdf(data, filename)
        if name.endswith((".txt", ".md")):
            text = data.decode("utf-8", errors="replace")
            fin = _extract_financials_from_text(text)
            return Extraction("document", True, fundamentals=fin, text_preview=text,
                              provenance=[{"source": "extracted:text", "detail": filename, "confidence": 0.9}])
        return Extraction("rejected", False, error=f"Unsupported file type: {filename}")
    except Exception as e:  # parsing failure is data, not a crash
        return Extraction("rejected", False, error=f"Could not read file: {type(e).__name__}: {e}")


def _ingest_tabular(df: pd.DataFrame, filename: str) -> Extraction:
    df.columns = [str(c).strip() for c in df.columns]
    cols = _normalize_columns(df)
    if {"open", "high", "low", "close"}.issubset(cols):
        c = df.rename(columns={v: k for k, v in cols.items()})
        keep = ["open", "high", "low", "close"] + (["volume"] if "volume" in cols else [])
        candles = c[keep].apply(pd.to_numeric, errors="coerce").dropna().reset_index(drop=True)
        if "volume" not in candles.columns:
            candles["volume"] = 0.0
        if len(candles) == 0:
            return Extraction("rejected", False, error="OHLCV columns found but no numeric rows.")
        return Extraction(
            "candles", True, candles=candles,
            provenance=[{"source": "extracted:tabular_ohlcv", "detail": f"{filename} ({len(candles)} rows)", "confidence": 0.95}],
        )
    # Generic table -> try financial metrics from a flattened text view.
    flat = df.to_csv(index=False)
    fin = _extract_financials_from_text(flat)
    return Extraction(
        "table", True, fundamentals=fin, tables=1, text_preview=flat[:400],
        provenance=[{"source": "extracted:table", "detail": filename, "confidence": 0.6}],
    )


def _ingest_pdf(data: bytes, filename: str) -> Extraction:
    import pdfplumber
    text_parts: list[str] = []
    table_count = 0
    prov: list[dict] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for i, page in enumerate(pdf.pages):
            t = page.extract_text() or ""
            if t:
                text_parts.append(t)
                prov.append({"source": "extracted:pdf_text", "detail": f"{filename} p.{i+1}", "confidence": 0.85})
            for tbl in page.extract_tables() or []:
                table_count += 1
                for row in tbl:
                    text_parts.append(" ".join(str(x) for x in row if x))
    full = "\n".join(text_parts)
    if not full.strip():
        return Extraction("rejected", False, error="No extractable text (scanned PDF may need OCR).",
                          provenance=prov)
    fin = _extract_financials_from_text(full)
    return Extraction("document", True, fundamentals=fin, tables=table_count,
                      text_preview=full, provenance=prov)
