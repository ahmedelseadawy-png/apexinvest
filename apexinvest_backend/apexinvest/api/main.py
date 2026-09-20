"""FastAPI surface for ApexInvest.

Endpoints mirror the blueprint's API architecture (§5). Uploads here are parsed
in-process for the demo; in production the API returns a presigned S3 URL and a
worker runs ingest asynchronously. Every route validates input strictly.
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

# The built frontend, served by the backend so it's reachable at one URL
# (http://localhost:8000/) with no cross-origin fetch at all.
_APP_HTML = Path(__file__).resolve().parents[2] / "frontend_app.html"

from ..domain import Objective
from ..ingest import files as ingest
from ..market import yahoo_egx
from ..service import AnalyzeInput, analyze, analyze_symbol, get_requirements, quotes as svc_quotes

app = FastAPI(title="ApexInvest API", version="0.1.0")

# --------------------------------------------------------------------------
# Access control (per-person keys). OPT-IN: set APEX_ACCESS_KEYS to turn it on.
#   APEX_ACCESS_KEYS="sherif:AB12CD, ahmed:EF34GH"   (name:key, comma-separated)
# When unset/empty the API is OPEN (unchanged local behaviour). When set, every
# /v1/* data call needs a valid key (header X-Apex-Key or ?key=), so the hosted
# app can only be used by people you gave a key to — and you can revoke anyone
# by removing their line and redeploying. Nothing is downloadable, so a user
# can't copy the app or pass it on; a stranger with the link has no key.
# --------------------------------------------------------------------------
import os as _os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse as _JSONResponse

_AUTH_OPEN_PATHS = {"/v1/health", "/v1/auth/status", "/v1/auth/check"}


def _access_keys() -> dict:
    """Parse APEX_ACCESS_KEYS into {key: person_name}. Empty dict => gate off."""
    raw = (_os.environ.get("APEX_ACCESS_KEYS") or "").strip()
    out: dict[str, str] = {}
    if not raw:
        return out
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part or "=" in part:
            sep = ":" if ":" in part else "="
            name, key = (x.strip() for x in part.split(sep, 1))
        else:
            name = key = part
        if key:
            out[key] = name or key
    return out


class AccessKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        keys = _access_keys()
        if keys:
            path = request.url.path
            if path.startswith("/v1/") and path not in _AUTH_OPEN_PATHS:
                provided = (request.headers.get("x-apex-key")
                            or request.query_params.get("key") or "").strip()
                if provided not in keys:
                    return _JSONResponse({"detail": "access key required"}, status_code=401)
        return await call_next(request)


# Register auth FIRST so CORS (added next) stays the OUTERMOST layer — that way
# even a 401 carries CORS headers and the browser can read it.
app.add_middleware(AccessKeyMiddleware)

# Prototype CORS: allow the frontend (any origin, incl. file:// which sends
# Origin: null) to call the API from the browser. Tighten to your real domain
# before production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/v1/auth/status")
def auth_status():
    """Does this server require an access key? (Frontend shows a login if so.)"""
    return {"auth_required": bool(_access_keys())}


@app.get("/v1/auth/check")
def auth_check(key: str = ""):
    """Validate a key and return the person's name. 401 if the key is wrong."""
    keys = _access_keys()
    if not keys:
        return {"ok": True, "auth_required": False, "name": None}
    name = keys.get(key.strip())
    if not name:
        raise HTTPException(status_code=401, detail="invalid access key")
    return {"ok": True, "auth_required": True, "name": name}

ASSETS = [
    {"symbol": "EGX30", "name": "EGX 30 Index", "asset_class": "index", "market": "EGX"},
    {"symbol": "AALR", "name": "General Co. for Land Reclamation Development & Reconstruction", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ABUK", "name": "Abou Kir Fertilizers & Chemical Industries Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ACAMD", "name": "Arab Co. for Asset Management & Development", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ACAP", "name": "A Capital Holding", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ACFR", "name": "Alexandria Company For Refractories", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ACGC", "name": "Arab Cotton Ginning Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ACTF", "name": "Act Financial", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ADCI", "name": "Arab Pharmaceuticals", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ADIB", "name": "Abu Dhabi Islamic Bank-Egypt", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ADPC", "name": "Arab Dairy Products Co. Arab Dairy - Panda", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ADRI", "name": "Arab Development & Real Estate Investment", "asset_class": "equity", "market": "EGX"},
    {"symbol": "AFDI", "name": "Alahly For Development & Investment", "asset_class": "equity", "market": "EGX"},
    {"symbol": "AFMC", "name": "Alexandria Flour Mills Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "AIDC", "name": "Arabia for Investment and Development", "asset_class": "equity", "market": "EGX"},
    {"symbol": "AIFI", "name": "Atlas for Investment & Food Industries SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "AIH", "name": "Arabia Investments Holding SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "AJWA", "name": "Ajwa for Food Industries Co. Egypt", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ALCN", "name": "Alexandria Containers & Goods", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ALEX", "name": "Alexandria Cement Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ALUM", "name": "Arab Aluminum Co. SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "AMER", "name": "Amer Group Holding", "asset_class": "equity", "market": "EGX"},
    {"symbol": "AMES", "name": "Alexandria New Medical Center Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "AMIA", "name": "Arab Moltaqa Investments Company", "asset_class": "equity", "market": "EGX"},
    {"symbol": "AMII", "name": "Arabian Metal Industries and Industrial Investments", "asset_class": "equity", "market": "EGX"},
    {"symbol": "AMOC", "name": "Alexandria Mineral Oils Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "AMPI", "name": "AL Moasher Pay for Electronic Payment and Collection (S.A.E)", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ANCC", "name": "ALNAHDA Industrial Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "APPC", "name": "Advanced Pharmaceutical Packaging Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "APSW", "name": "Arab Polvara Spinning & Weaving Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ARAB", "name": "Arab Developers Holding", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ARCC", "name": "Arabian Cement Company", "asset_class": "equity", "market": "EGX"},
    {"symbol": "AREH", "name": "Egyptian Real Estate Group", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ASCM", "name": "ASEC Co. for Mining", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ASPI", "name": "Aspire Capital Holding for Financial Investments", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ATLC", "name": "Al Tawfeek Leasing Company-A.T.LEASE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ATQA", "name": "Misr National Steel", "asset_class": "equity", "market": "EGX"},
    {"symbol": "AXPH", "name": "Alexandria Company for Pharmaceuticals and Chemical Industries", "asset_class": "equity", "market": "EGX"},
    {"symbol": "BIDI", "name": "El Badr Investment and Development - BID", "asset_class": "equity", "market": "EGX"},
    {"symbol": "BIGP", "name": "ElBarbary Investment Group", "asset_class": "equity", "market": "EGX"},
    {"symbol": "BINV", "name": "B Investments Holding SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "BIOC", "name": "GlaxoSmithKline S.A.E.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "BONY", "name": "Bonyan for Development and Trade", "asset_class": "equity", "market": "EGX"},
    {"symbol": "BTFH", "name": "Beltone Holding", "asset_class": "equity", "market": "EGX"},
    {"symbol": "CAED", "name": "Cairo Educational Services", "asset_class": "equity", "market": "EGX"},
    {"symbol": "CANA", "name": "Suez Canal Bank SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "CCAP", "name": "QALA For Financial Investments", "asset_class": "equity", "market": "EGX"},
    {"symbol": "CCRS", "name": "Gulf Canadian Real Estate Investment Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "CEFM", "name": "Middle Egypt Flour Mills", "asset_class": "equity", "market": "EGX"},
    {"symbol": "CERA", "name": "Arab Ceramic Co. - Ceramica Remas", "asset_class": "equity", "market": "EGX"},
    {"symbol": "CFGH", "name": "Concrete Fashion Group for Commercial and Industrial Investments S.A.E", "asset_class": "equity", "market": "EGX"},
    {"symbol": "CICH", "name": "CI Capital Holding for Financial Investments", "asset_class": "equity", "market": "EGX"},
    {"symbol": "CID", "name": "Chemical Development Industries (CID)", "asset_class": "equity", "market": "EGX"},
    {"symbol": "CIEB", "name": "Credit Agricole Egypt", "asset_class": "equity", "market": "EGX"},
    {"symbol": "CIRA", "name": "Cairo For Investment And Real Estate Developments -CIRA Education", "asset_class": "equity", "market": "EGX"},
    {"symbol": "CLHO", "name": "Cleopatra Hospital Company", "asset_class": "equity", "market": "EGX"},
    {"symbol": "CNFN", "name": "Contact Financial Holding SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "COMI", "name": "Commercial International Bank - Egypt (CIB) S.A.E.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "COPR", "name": "Cooper for Commercial Investment & Real Estate Development", "asset_class": "equity", "market": "EGX"},
    {"symbol": "COSG", "name": "Cairo Oils & Soap", "asset_class": "equity", "market": "EGX"},
    {"symbol": "CPCI", "name": "Kahira Pharmaceuticals & Chemical Industries Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "CPME", "name": "Catalyst Partners Middle East", "asset_class": "equity", "market": "EGX"},
    {"symbol": "CRST", "name": "Creast Mark For Contracting And Real Estate Development", "asset_class": "equity", "market": "EGX"},
    {"symbol": "CSAG", "name": "Canal Shipping Agencies Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "DAPH", "name": "Development & Engineering Consultants", "asset_class": "equity", "market": "EGX"},
    {"symbol": "DCCC", "name": "Damietta Container and Cargo Handling", "asset_class": "equity", "market": "EGX"},
    {"symbol": "DCRC", "name": "Delta Construction & Rebuilding Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "DEIN", "name": "Delta Insurance", "asset_class": "equity", "market": "EGX"},
    {"symbol": "DGTZ", "name": "Digitize for Investment And Technology", "asset_class": "equity", "market": "EGX"},
    {"symbol": "DOMT", "name": "Arabian Food Industries Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "DSCW", "name": "Dice Sports & Casual Wear Manufacturers SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "DTPP", "name": "Delta for Printing & Packaging", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EALR", "name": "El Arabia for Land Reclamation", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EASB", "name": "Egyptian Arabian Company for Securities Brokerage EAC", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EAST", "name": "Eastern Company", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EBSC", "name": "Osool ESB Securities Brokerage", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ECAP", "name": "El Ezz Ceramics & Porcelain Co. (Gemma)", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EDFM", "name": "East Delta Flour Mills Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EEII", "name": "El Arabia Engineering Industries", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EEP", "name": "Egypt Education Platform - EEP", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EFAC", "name": "Egyptian Ferro All Egp10", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EFIC", "name": "Egyptian Financial & Industrial Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EFID", "name": "Edita Food Industries SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EFIH", "name": "e-finance for Digital and Financial Investments S.A.E.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EGAL", "name": "Egypt Aluminum", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EGAS", "name": "Egypt Gas Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EGBE", "name": "Egyptian Gulf Bank", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EGCH", "name": "Egyptian Chemical Industries", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EGOTH", "name": "El Masreyah Touris Egp100", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EGREF", "name": "Egyptians Real Estate Fund", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EGSA", "name": "Egyptian Satellite Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EGTS", "name": "Egyptian for Tourism Resorts", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EGWA", "name": "General Warehouses of Egypt", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EHDR", "name": "Egyptians Housing Development & Reconstruction", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EITP", "name": "Egyptian International Tourism Projects", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ELAB", "name": "Egyptian Linear Alkyl Benzene Company", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ELEC", "name": "Electro Cable Egypt", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ELKA", "name": "El Kahera Housing", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ELNA", "name": "El Nasr for Manufacturing Agricultural Crops", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ELSH", "name": "El-Shams Housing & Development SA", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ELWA", "name": "Elwadi for International Investment & Development", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EMFD", "name": "Emaar Misr for Development SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ENGC", "name": "Industrial Engineering Co. for Construction & Development", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ENPI", "name": "Engineering for the Petroleum and Process Industries", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EOSB", "name": "El Orouba Securities Brokerage", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EPCO", "name": "Egypt for Poultry Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EPPK", "name": "El Ahram Co. for Printing & Packing", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ETEL", "name": "Telecom Egypt", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ETRS", "name": "Egyptian Transport And Commercial Services Co. (Egytrans Nosco)", "asset_class": "equity", "market": "EGX"},
    {"symbol": "EXPA", "name": "Export Development Bank of Egypt", "asset_class": "equity", "market": "EGX"},
    {"symbol": "FAIT", "name": "Faisal Islamic Bank of Egypt", "asset_class": "equity", "market": "EGX"},
    {"symbol": "FCMD", "name": "Future Care For Medical Industries", "asset_class": "equity", "market": "EGX"},
    {"symbol": "FIRE", "name": "First Investment & Real Estate Development", "asset_class": "equity", "market": "EGX"},
    {"symbol": "FNAR", "name": "Al Fanar Contracting Construction Trade Import & Export Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "FTNS", "name": "Fitness Prime", "asset_class": "equity", "market": "EGX"},
    {"symbol": "FWRY", "name": "Fawry For Banking Technology And Electronic Payment", "asset_class": "equity", "market": "EGX"},
    {"symbol": "GBCO", "name": "GB Corp", "asset_class": "equity", "market": "EGX"},
    {"symbol": "GDWA", "name": "Gadwa For Industrial Development", "asset_class": "equity", "market": "EGX"},
    {"symbol": "GEOS", "name": "Geos for trading and contracting", "asset_class": "equity", "market": "EGX"},
    {"symbol": "GGCC", "name": "Giza General Contracting & Real Estate Investment", "asset_class": "equity", "market": "EGX"},
    {"symbol": "GGRN", "name": "Gogreen for Agricultural Investment and Development Company", "asset_class": "equity", "market": "EGX"},
    {"symbol": "GIHD", "name": "Gharbia Islamic Housing Development", "asset_class": "equity", "market": "EGX"},
    {"symbol": "GMCI", "name": "GMC Group for Industrial Commercial & Financial Investments", "asset_class": "equity", "market": "EGX"},
    {"symbol": "GOUR", "name": "Gourmet Egypt.Com Foods", "asset_class": "equity", "market": "EGX"},
    {"symbol": "GPIM", "name": "GPI For Urban Growth", "asset_class": "equity", "market": "EGX"},
    {"symbol": "GPPL", "name": "Golden Pyramids Plaza", "asset_class": "equity", "market": "EGX"},
    {"symbol": "GRCA", "name": "Grand Investment Capital", "asset_class": "equity", "market": "EGX"},
    {"symbol": "GSSC", "name": "General Silos & Storage Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "GTEX", "name": "G-TEX for Commercial and Industrial Investments S.A.E", "asset_class": "equity", "market": "EGX"},
    {"symbol": "GTHE", "name": "Global Telecom Holding S.A.E.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "GTWL", "name": "Golden Textiles & Clothes Wool", "asset_class": "equity", "market": "EGX"},
    {"symbol": "HAVC", "name": "Hassan Allam Investments & Venture Capital S.A.E", "asset_class": "equity", "market": "EGX"},
    {"symbol": "HBCO", "name": "Heibco Npv", "asset_class": "equity", "market": "EGX"},
    {"symbol": "HDBK", "name": "Housing & Development Bank", "asset_class": "equity", "market": "EGX"},
    {"symbol": "HDST", "name": "HEDGESTONE INVESTMENT", "asset_class": "equity", "market": "EGX"},
    {"symbol": "HELI", "name": "Heliopolis Housing", "asset_class": "equity", "market": "EGX"},
    {"symbol": "HRHO", "name": "EFG Holding S.A.E.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "IBCT", "name": "International Business Corp. for Trading & Agencies", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ICFC", "name": "International Co. for Fertilizers & Chemicals", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ICID", "name": "International Company for Investment & Development", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ICLE", "name": "International Co. for Leasing SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "IDRE", "name": "Ismailia Development & Real Estate Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "IEEC", "name": "Industrial & Engineering Enterprises Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "IFAP", "name": "International Agricultural Products", "asset_class": "equity", "market": "EGX"},
    {"symbol": "INEG", "name": "Integrated Engineering Group S.A.E", "asset_class": "equity", "market": "EGX"},
    {"symbol": "INFI", "name": "Ismailia National Food Industries", "asset_class": "equity", "market": "EGX"},
    {"symbol": "IRAX", "name": "El Ezz Aldekhela Steel-Alexandria", "asset_class": "equity", "market": "EGX"},
    {"symbol": "IRON", "name": "Egyptian Iron & Steel", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ISMA", "name": "Ismailia Misr Poultry", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ISMQ", "name": "Iron & Steel for Mines & Quarries", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ISPH", "name": "Ibnsina Pharma", "asset_class": "equity", "market": "EGX"},
    {"symbol": "JUFO", "name": "Juhayna Food Industries", "asset_class": "equity", "market": "EGX"},
    {"symbol": "KABO", "name": "El Nasr Clothing & Textiles Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "KNGC", "name": "EL- Nasr Glass And Crystal", "asset_class": "equity", "market": "EGX"},
    {"symbol": "KORA", "name": "KORRA", "asset_class": "equity", "market": "EGX"},
    {"symbol": "KRDI", "name": "Al Khair River for Development Agriculture Investment and Environmental Services", "asset_class": "equity", "market": "EGX"},
    {"symbol": "KWIN", "name": "El Kahera El Watania Investment", "asset_class": "equity", "market": "EGX"},
    {"symbol": "KZPC", "name": "Kafr El Zayat Pesticides & Chemical Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "LCSW", "name": "Lecico Egypt SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "LKGP", "name": "The Holding Company for Financial Investment - The Lakah Group", "asset_class": "equity", "market": "EGX"},
    {"symbol": "LUTS", "name": "Lotus For Agricultural Investments And Development", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MAAL", "name": "Marseilla Al Masreia Al Khalegeya for Holding Investment", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MASR", "name": "Madinet Masr for Housing & Development", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MBEG", "name": "MB for Engineering & Contracting", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MBSC", "name": "Misr Beni Suef Cement Co. SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MCQE", "name": "Misr Cement Co. (Qena)", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MCRO", "name": "Macro Group Pharmaceutical S.A.E.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MEGM", "name": "Middle East Glass Manufacturing SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MENA", "name": "Mena Touristic & Real Estate Investment", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MEPA", "name": "Medical Packaging Company", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MFPC", "name": "Misr Fertilizers Production Company MOPCO", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MFSC", "name": "Misr Duty Free Shops Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MHOT", "name": "Misr Hotels Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MICH", "name": "Misr Chemical Industries Ltd.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MILS", "name": "North Cairo Mills Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MIPH", "name": "Minapharm Pharmaceuticals", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MISR", "name": "MISR Intercontinental for Granite & Marble", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MITR", "name": "Misr Travel&Touris Egp6", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MLIC", "name": "Misr Life Insurance", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MMAT", "name": "Marsa Marsa Alam for Tourism Development", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MMHC", "name": "El Mamoura Company For Construction & Tourism Development", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MOED", "name": "Egyptian Modern Education Systems", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MOIL", "name": "Maridive & Oil Services SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MOIN", "name": "Mohandes Insurance Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MOSC", "name": "Misr Oils & Soap Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MPCI", "name": "Memphis Pharmaceutical & Chemical Industries", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MPCO", "name": "Mansourah Poultry Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MPRC", "name": "Egyptian Media Production City", "asset_class": "equity", "market": "EGX"},
    {"symbol": "MTIE", "name": "MM Group for Industry & International Trade", "asset_class": "equity", "market": "EGX"},
    {"symbol": "NAHO", "name": "Naeem Holding Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "NARE", "name": "Naeem Real Estate Holding Group", "asset_class": "equity", "market": "EGX"},
    {"symbol": "NBKE", "name": "National Bank of Kuwait - Egypt", "asset_class": "equity", "market": "EGX"},
    {"symbol": "NCCW", "name": "Nasr Co. for Civil Works", "asset_class": "equity", "market": "EGX"},
    {"symbol": "NCGC", "name": "Nile Cotton Ginning", "asset_class": "equity", "market": "EGX"},
    {"symbol": "NDRL", "name": "National Drilling Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "NEDA", "name": "Northern Upper Egypt Development & Agricultural Production", "asset_class": "equity", "market": "EGX"},
    {"symbol": "NFCI", "name": "ELNASR Co For Fertilizers And Chemical Industries", "asset_class": "equity", "market": "EGX"},
    {"symbol": "NHPS", "name": "National Housing for Professional Syndicates", "asset_class": "equity", "market": "EGX"},
    {"symbol": "NINH", "name": "Nozha International Hospital", "asset_class": "equity", "market": "EGX"},
    {"symbol": "NIPH", "name": "El-Nile Co. for Pharmaceuticals & Chemical Industries", "asset_class": "equity", "market": "EGX"},
    {"symbol": "NMIN", "name": "El Nasr Mining Co Egp10", "asset_class": "equity", "market": "EGX"},
    {"symbol": "OBRI", "name": "El Obour Real Estate Investment", "asset_class": "equity", "market": "EGX"},
    {"symbol": "OCAP", "name": "OG Capital For Investments SPAC", "asset_class": "equity", "market": "EGX"},
    {"symbol": "OCDI", "name": "Six of October Development & Investment (SODIC)", "asset_class": "equity", "market": "EGX"},
    {"symbol": "OCPH", "name": "October Pharma Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ODIN", "name": "ODIN Investments", "asset_class": "equity", "market": "EGX"},
    {"symbol": "OFH", "name": "O B Financial Holding", "asset_class": "equity", "market": "EGX"},
    {"symbol": "OIH", "name": "Orascom Investment Holding SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "OLFI", "name": "Obour Land for Food Industries", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ORAS", "name": "Orascom Construction Plc", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ORHD", "name": "Orascom Development Egypt (S.A.E)", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ORWE", "name": "Oriental Weavers Carpet", "asset_class": "equity", "market": "EGX"},
    {"symbol": "PACH", "name": "Paints & Chemical Industries Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "PHAR", "name": "Egyptian International Pharmaceutical Industries Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "PHDC", "name": "Palm Hills Development Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "PHGC", "name": "Premium Healthcare Group", "asset_class": "equity", "market": "EGX"},
    {"symbol": "PHTV", "name": "Pyramisa Hotels", "asset_class": "equity", "market": "EGX"},
    {"symbol": "PMSC", "name": "Petroleum Marine Services Company", "asset_class": "equity", "market": "EGX"},
    {"symbol": "POCO", "name": "Port Said Container And Cargo Handling", "asset_class": "equity", "market": "EGX"},
    {"symbol": "POUL", "name": "Cairo Poultry Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "PRCL", "name": "General Co. for Ceramic & Porcelain Products", "asset_class": "equity", "market": "EGX"},
    {"symbol": "PRDC", "name": "Pioneers Properties for Urban Development", "asset_class": "equity", "market": "EGX"},
    {"symbol": "PRMH", "name": "Prime Holding", "asset_class": "equity", "market": "EGX"},
    {"symbol": "QNBE", "name": "Qatar National Bank", "asset_class": "equity", "market": "EGX"},
    {"symbol": "RACC", "name": "Raya Contact Center", "asset_class": "equity", "market": "EGX"},
    {"symbol": "RAKT", "name": "Rakta Paper Manufacturing", "asset_class": "equity", "market": "EGX"},
    {"symbol": "RAYA", "name": "Raya Holding for Financial Investments SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "RKAZ", "name": "REKAZ Financial Holding", "asset_class": "equity", "market": "EGX"},
    {"symbol": "RMDA", "name": "Tenth of Ramadan Pharmaceutical Industries & Diagnostic-Rameda", "asset_class": "equity", "market": "EGX"},
    {"symbol": "RMTV", "name": "Rowad Misr Tourism Investment", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ROTO", "name": "Rowad Tourism (Al Rowad) Co", "asset_class": "equity", "market": "EGX"},
    {"symbol": "RREI", "name": "Arab Real Estate Investment Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "RTVC", "name": "Remco for Touristic Villages Construction", "asset_class": "equity", "market": "EGX"},
    {"symbol": "RUBX", "name": "Rubex International for Plastic & Acrylic Manufacturing", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SAIB", "name": "Societe Arabe Internationale de Banque", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SAUD", "name": "Al Baraka Bank Egypt", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SCEM", "name": "Sinai Cement Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SCFM", "name": "South Cairo & Giza Mills & Bakeries", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SCTS", "name": "Sues Canal Co. for Technology Settling", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SDTI", "name": "Sharm Dreams Co. for Tourism Investment", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SEIG", "name": "Saudi Egyptian Investment & Finance Co. SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SIEG", "name": "Egyptian Company for Pipes and Cement Products -Siegwart", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SINA", "name": "Sinai Manganese Company", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SIPC", "name": "Sabaa International Company for Pharmaceutial and Chemical Industry", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SKPC", "name": "Sidi Kerir Petrochemicals", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SMFR", "name": "Samad Misr-EGYFERT", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SMPP", "name": "Modern Shorouk Printing & Packaging", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SNFC", "name": "Sharkia National Food", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SNFI", "name": "Souhag National Food Industries", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SPHT", "name": "El Shams Pyramids Co. for Hotels & Touristic Projects SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SPIN", "name": "Alexandria Spinning & Weaving", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SPMD", "name": "Speed Medical SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SUCE", "name": "Suez Cement Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SUGR", "name": "Delta Sugar", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SVCE", "name": "South Valley Cement Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "SWDY", "name": "El Sewedy Electric Company", "asset_class": "equity", "market": "EGX"},
    {"symbol": "TALM", "name": "Taaleem Management Services S.A.E", "asset_class": "equity", "market": "EGX"},
    {"symbol": "TANM", "name": "Tanmiya for Real Estate Investment", "asset_class": "equity", "market": "EGX"},
    {"symbol": "TAQA", "name": "TAQA Arabia", "asset_class": "equity", "market": "EGX"},
    {"symbol": "TMGH", "name": "Talaat Moustafa Group Holding", "asset_class": "equity", "market": "EGX"},
    {"symbol": "TORA", "name": "Tourah Cement Co", "asset_class": "equity", "market": "EGX"},
    {"symbol": "TOUR", "name": "Tourism Urbanization", "asset_class": "equity", "market": "EGX"},
    {"symbol": "TRTO", "name": "TransOceans Tours", "asset_class": "equity", "market": "EGX"},
    {"symbol": "TWSA", "name": "TAWASOA FOR FACTORING", "asset_class": "equity", "market": "EGX"},
    {"symbol": "TYCN", "name": "Tycoon Holding Company For Financial Investments", "asset_class": "equity", "market": "EGX"},
    {"symbol": "UBEE", "name": "United Bank SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "UEFM", "name": "Upper Egypt Flour Mills Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "UEGC", "name": "El-Saeed Contracting & Real Estate Investment Co. SCCD", "asset_class": "equity", "market": "EGX"},
    {"symbol": "UNIP", "name": "Universal Co. for Paper & Packaging Materials-Unipack", "asset_class": "equity", "market": "EGX"},
    {"symbol": "UNIT", "name": "United Housing Construction SA", "asset_class": "equity", "market": "EGX"},
    {"symbol": "UPMS", "name": "Union Pharmacist Company For Medical Services And Investment", "asset_class": "equity", "market": "EGX"},
    {"symbol": "UTOP", "name": "Utopia Real Estate Investment & Tourism SAE", "asset_class": "equity", "market": "EGX"},
    {"symbol": "VALU", "name": "U Consumer Finance S.A.E", "asset_class": "equity", "market": "EGX"},
    {"symbol": "VERT", "name": "Vertika for Industry & Trade", "asset_class": "equity", "market": "EGX"},
    {"symbol": "VLMR", "name": "Valmore Holding", "asset_class": "equity", "market": "EGX"},
    {"symbol": "WATP", "name": "Modern Co. for Water Proofing", "asset_class": "equity", "market": "EGX"},
    {"symbol": "WCDF", "name": "Middle & West Delta Flour Mills Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "WKOL", "name": "Wadi Kom Ombo Land Reclamation", "asset_class": "equity", "market": "EGX"},
    {"symbol": "YAYT", "name": "Spring & Transportation Needs Manufacturing Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ZEOT", "name": "Extracted Oils & Derivatives Co.", "asset_class": "equity", "market": "EGX"},
    {"symbol": "ZMID", "name": "Zahraa Maadi Investment & Development", "asset_class": "equity", "market": "EGX"},
    {"symbol": "AAPL", "name": "Apple Inc.", "asset_class": "equity", "market": "US"},
    {"symbol": "NVDA", "name": "NVIDIA Corp.", "asset_class": "equity", "market": "US"},
    {"symbol": "SPY", "name": "S&P 500 ETF", "asset_class": "etf", "market": "US"},
    {"symbol": "BTC", "name": "Bitcoin", "asset_class": "crypto", "market": "US"},
    {"symbol": "EURUSD", "name": "Euro / US Dollar", "asset_class": "fx", "market": "US"},
]


class Candle(BaseModel):
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class AnalyzeRequest(BaseModel):
    objective: Objective
    mode: str = Field(pattern="^(auto|manual)$")
    manual_strategies: list[str] = []
    candles: dict[str, list[Candle]] = {}       # timeframe -> candles
    fundamentals: dict | None = None
    reference_price: float | None = None
    provided_inputs: list[str] = []


def _to_input(req: AnalyzeRequest) -> AnalyzeInput:
    candles = {
        tf: pd.DataFrame([c.model_dump() for c in rows])
        for tf, rows in req.candles.items() if rows
    }
    return AnalyzeInput(
        objective=req.objective, mode=req.mode,
        manual_strategies=req.manual_strategies, candles=candles,
        fundamentals=req.fundamentals, reference_price=req.reference_price,
        provided_inputs=req.provided_inputs,
    )


@app.get("/", response_class=HTMLResponse)
@app.get("/app", response_class=HTMLResponse)
def serve_app():
    """Serve the ApexInvest frontend from the backend, so AUTO analysis is same-origin."""
    # Never let the browser cache the app shell — otherwise UI updates (new
    # buttons, fixes) silently never reach the user until they clear the cache.
    no_cache = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache", "Expires": "0"}
    if _APP_HTML.exists():
        return FileResponse(str(_APP_HTML), headers=no_cache)
    return HTMLResponse(
        "<h1>ApexInvest API is running.</h1>"
        "<p>The frontend file (frontend_app.html) isn't next to the backend. "
        "API docs are at <a href='/docs'>/docs</a>.</p>",
        status_code=200, headers=no_cache,
    )


@app.get("/v1/quotes")
def get_quotes(symbols: str = ""):
    """Latest end-of-day price + daily change for the given comma-separated EGX
    symbols (e.g. ?symbols=COMI,SWDY,ABUK). Used to keep the picker current."""
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:12]
    if not syms:
        return {"quotes": {}}
    try:
        return {"quotes": svc_quotes(syms)}
    except Exception as e:  # feed error -> 502, picker falls back to snapshot
        raise HTTPException(status_code=502, detail=f"quotes feed error: {e}")


@app.get("/v1/health")
def health():
    return {"status": "ok", "service": "apexinvest", "version": "0.1.0"}


@app.get("/v1/data/health")
def data_health(symbol: str = "COMI"):
    """Honest data-source health: which provider serves each timeframe, the current
    end-of-day freshness, and an explicit statement that no feed here is real-time."""
    from ..market import datalayer
    try:
        return datalayer.health(symbol)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"data health error: {e}")


@app.get("/v1/fundamentals/{symbol}")
def fundamentals_endpoint(symbol: str):
    """Best-effort company fundamentals + a transparent quality score. Returns
    available:False (never fabricated numbers) when Yahoo has no data for the name."""
    from ..market import fundamentals as fun
    try:
        return fun.get(symbol)
    except Exception as e:
        return {"available": False, "reason": f"fundamentals error: {str(e)[:80]}"}


@app.get("/v1/assets/search")
def search_assets(q: str = ""):
    ql = q.lower()
    hits = [a for a in ASSETS if ql in a["symbol"].lower() or ql in a["name"].lower()] if q else ASSETS
    return {"results": hits}


@app.post("/v1/analyses/requirements")
def requirements(req: AnalyzeRequest):
    try:
        return get_requirements(_to_input(req))
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/v1/analyses/analyze")
def run_analysis(req: AnalyzeRequest):
    try:
        return analyze(_to_input(req))
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.get("/v1/scan")
def scan_market(horizon: str = "short_swing", risk: str = "balanced",
                limit: int | None = None, refresh: bool = False,
                symbols: str | None = None):
    """EGX Opportunity Scanner — rank the whole equity universe through the same
    engine by trade QUALITY (not raw upside). horizon: intraday|short_swing|
    medium_swing|long_term; risk: conservative|balanced|aggressive. The first
    scan of the day is slower (fetches every symbol); results are cached ~1h —
    pass refresh=true to recompute."""
    from ..engines import scanner as scan_engine
    names = {a["symbol"]: a["name"] for a in ASSETS}
    known = {a["symbol"] for a in ASSETS}
    not_in_catalog: list[str] = []
    if symbols:
        # Watch-list mode: scan ONLY the requested symbols, through the same
        # engine. Anti-fabrication: never scan an unknown ticker — but report the
        # dropped names so the user knows exactly what wasn't covered.
        req = [t.strip().upper() for t in symbols.split(",") if t.strip()]
        universe = [s for s in req if s in known]
        not_in_catalog = [s for s in req if s not in known]
    else:
        universe = [a["symbol"] for a in ASSETS if a.get("asset_class") == "equity"]
    try:
        result = scan_engine.scan(universe, names=names, horizon=horizon, risk=risk,
                                  limit=limit, refresh=refresh, max_workers=8)
        if not_in_catalog:
            result = {**result, "not_in_catalog": not_in_catalog}
        return result
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"scan error: {e}")


class HoldingIn(BaseModel):
    symbol: str
    qty: float = Field(gt=0)
    avg_cost: float = Field(gt=0)
    company: str | None = None


class PortfolioIn(BaseModel):
    holdings: list[HoldingIn] = Field(default_factory=list)
    objective: Objective = Objective.SWING


@app.post("/v1/portfolio")
def analyze_portfolio_endpoint(req: PortfolioIn):
    """Analyze the positions you already hold and say what to do with each
    (HOLD / ADD / TRIM / EXIT) with a protective stop — through the same engine."""
    from ..engines import portfolio as pf
    names = {a["symbol"]: a["name"] for a in ASSETS}
    holdings = [{"symbol": h.symbol.strip().upper(), "qty": h.qty, "avg_cost": h.avg_cost,
                 "company": h.company or names.get(h.symbol.strip().upper())}
                for h in req.holdings]
    if not holdings:
        return {"summary": {"positions": 0}, "positions": [], "warnings": [], "errors": [],
                "note": "No holdings provided."}
    try:
        return pf.analyze_portfolio(holdings, objective=req.objective)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"portfolio analysis error: {e}")


@app.get("/v1/backtest/universe")
def backtest_universe_endpoint(objective: Objective = Objective.SWING, limit: int = 40):
    """Market-wide walk-forward validation: pooled hit-rate, expectancy, profit
    factor, drawdown — plus a calibration table (does higher confidence => higher
    win-rate?). Heavy: the first run takes a few minutes, then cached ~6h."""
    from ..engines import backtest as bt
    equities = [a["symbol"] for a in ASSETS if a.get("asset_class") == "equity"]
    try:
        return bt.backtest_universe(equities, objective=objective, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"universe backtest error: {e}")


@app.get("/v1/backtest/{symbol}")
def backtest_endpoint(symbol: str, objective: Objective = Objective.SWING,
                      lookback: str = "2y"):
    """Walk-forward backtest of the SAME engine on `symbol`, no look-ahead.
    Returns hit-rate, expectancy (R), profit factor, max drawdown and the trade
    list, plus a buy-and-hold benchmark. Longer lookback = more trades."""
    from ..engines import backtest as bt
    from ..market import feed
    try:
        df, meta = feed.fetch_daily(symbol, lookback=lookback)
    except yahoo_egx.DataUnavailable as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"market data feed error: {e}")
    res = bt.backtest_symbol(df, objective)
    out = res.as_dict(include_trades=True)
    out["symbol"] = symbol.strip().upper()
    out["data_source"] = meta.get("source")
    return out


@app.get("/v1/analyses/auto/{symbol}")
def auto_analyze(symbol: str, objective: Objective = Objective.SWING):
    """Fetch live EGX candles for `symbol` and build the plan automatically —
    no upload. The R:R math is computed by the same engine; this route just
    supplies candles from the market-data feed. `objective` is a query param
    (swing | long_term | day | income | analyze), default swing."""
    try:
        return analyze_symbol(symbol, objective)
    except yahoo_egx.DataUnavailable as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:  # network / feed errors -> 502, not a server crash
        raise HTTPException(status_code=502, detail=f"market data feed error: {e}")


@app.post("/v1/uploads")
async def upload(file: UploadFile = File(...)):
    data = await file.read()
    result = ingest.ingest(file.filename or "upload", data)
    if not result.ok:
        # 422: the file was received but could not be used; message tells the user why.
        raise HTTPException(status_code=422, detail=result.error)
    return result.summary()


# --------------------------------------------------------------------------
# Mobile web app (additive — nothing above is changed). The thin layer lives in
# api/mobile.py: a CSV-import route that feeds the SAME engine path, plus static
# hosting of the mobile-first UI at /m. The desktop UI at / and /app is untouched.
# --------------------------------------------------------------------------
from .mobile import router as _mobile_router, build_mobile_app as _build_mobile_app

app.include_router(_mobile_router)
_mobile_static = _build_mobile_app()
if _mobile_static is not None:
    app.mount("/m", _mobile_static)
