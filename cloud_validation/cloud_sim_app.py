"""TEST-ONLY module (never part of the product): the cloud app with ONLY the network fetchers stubbed.

The sandbox cannot reach Yahoo / TradingView / EODHD, so to run the *production start command* here we
point uvicorn at this module instead of `apexinvest.api.main:app`:

    uvicorn cloud_sim_app:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers ...

It imports the UNMODIFIED product app (`from apexinvest.api.main import app`) after replacing only the
data fetchers with deterministic local datasets (identical to mobile_validation/offline_server.py).
No engine, middleware or route code is touched.  Env APEX_BACKEND_DIR selects which backend tree to load.
"""
import os, sys, json, hashlib, datetime as dt
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.environ.get("APEX_BACKEND_DIR") or os.path.join(HERE, "..", "apexinvest_backend")
BACKEND = os.path.abspath(BACKEND)
sys.path.insert(0, BACKEND); sys.path.insert(0, HERE)
import pandas as pd
import synth
from apexinvest.market import feed, yahoo_egx, tradingview_egx, fundamentals
from apexinvest.market.yahoo_egx import DataUnavailable

def _load(name):
    d = json.load(open(f"{BACKEND}/tests/fixtures/{name}.json"))
    rows = ([[c["o"], c["h"], c["l"], c["c"], c["v"]] for c in d["candles"]] if "candles" in d else d["rows"])
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"]).astype(float)

DATA = {"COMI": _load("COMI"), "SWDY": _load("SWDY")}
def series_for(sym):
    if sym in DATA: return DATA[sym]
    h = int(hashlib.md5(sym.encode()).hexdigest(), 16)
    drift = [0.0012, -0.001, 0.0, 0.0006, -0.0004, 0.0018][h % 6]
    vol = [0.012, 0.016, 0.02][(h >> 3) % 3]
    px = [12.0, 35.0, 80.0, 4.5, 150.0][(h >> 5) % 5]
    df = synth.synth(300, h % 10000, drift, vol, px)
    DATA[sym] = df
    return df

_KNOWN = None
def _known():
    global _KNOWN
    if _KNOWN is None:
        from apexinvest.api import main
        _KNOWN = {a["symbol"] for a in main.ASSETS if a.get("asset_class") == "equity"} | {"EGX30", "COMI", "SWDY"}
    return _KNOWN

AS_OF = os.environ.get("SIM_AS_OF") or (dt.date.today() - dt.timedelta(days=1)).isoformat()
def fake_fetch_daily(symbol, lookback="1y", timeout=10.0):
    s = symbol.strip().upper().removesuffix(".CA")
    if s not in _known() or s == "NOPE":
        raise DataUnavailable(f"{s}: no data (offline test feed)")
    df = series_for(s)
    meta = {"symbol": s, "currency": "EGP", "exchange": "EGX", "timeframe": "1d", "bars": len(df),
            "last_close": float(df["close"].iloc[-1]), "as_of": AS_OF,
            "source": "OFFLINE TEST FEED (deterministic local data)", "delayed": True, "adjusted": False,
            "provides": list(yahoo_egx.PROVIDES)}
    return df.copy(), meta
def fake_quote(symbol, timeout=8.0):
    df, m = fake_fetch_daily(symbol)
    c = df["close"]; prev = float(c.iloc[-2])
    return {"symbol": m["symbol"], "price": float(c.iloc[-1]), "prev_close": prev,
            "change_pct": round((float(c.iloc[-1]) - prev) / prev * 100, 2), "as_of": AS_OF, "currency": "EGP",
            "source": "OFFLINE TEST FEED"}

feed.fetch_daily = fake_fetch_daily
yahoo_egx.fetch_daily = fake_fetch_daily
yahoo_egx.fetch_quote = fake_quote
tradingview_egx.fetch_quote = lambda s, *a, **k: None
tradingview_egx.fetch_quotes = lambda syms, *a, **k: {}
fundamentals.get = lambda s, **k: {"available": False, "reason": "offline test feed"}

from apexinvest.api.main import app   # the real, unmodified product app
