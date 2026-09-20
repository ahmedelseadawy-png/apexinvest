"""Dump FULL-PRECISION raw engine values so two Python environments can be compared bit-for-bit.
usage: python raw_indicators.py <backend_dir> <out.json>
Runs the engine's own indicator functions (indicators.py, unmodified) plus the complete analysis result on every
dataset: 28 synthetic + COMI + SWDY fixtures.  Floats are written with repr precision (json), so any 1-ulp
difference between environments is visible."""
import sys, os, json, math
backend, out = sys.argv[1:3]
sys.path.insert(0, backend); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np, pandas as pd, synth
from apexinvest.engines import indicators as ind
from apexinvest.domain import Objective
from apexinvest.market import yahoo_egx
from apexinvest.service import analyze_symbol

def clean(o):
    if isinstance(o, pd.Series): return [clean(x) for x in o.tolist()]
    if isinstance(o, pd.DataFrame): return {str(c): clean(o[c]) for c in o.columns}
    if isinstance(o, dict): return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)): return [clean(x) for x in o]
    if isinstance(o, (np.floating, float)): return "NaN" if math.isnan(o) else ("Inf" if math.isinf(o) else float(o))
    if isinstance(o, (np.integer,)): return int(o)
    if isinstance(o, (np.bool_,)): return bool(o)
    return o

def fixture(name):
    d = json.load(open(f"{backend}/tests/fixtures/{name}.json"))
    rows = ([[c["o"], c["h"], c["l"], c["c"], c["v"]] for c in d["candles"]] if "candles" in d else d["rows"])
    return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"]).astype(float)

sets = list(synth.catalog()) + [("COMI_fixture", fixture("COMI")), ("SWDY_fixture", fixture("SWDY"))]
res = {}
for tag, df in sets:
    df = df.reset_index(drop=True)
    c = df["close"]
    r = {
        "sma20": ind.sma(c, 20), "sma50": ind.sma(c, 50), "ema12": ind.ema(c, 12), "ema26": ind.ema(c, 26),
        "rsi14": ind.rsi(c, 14), "macd": list(ind.macd(c)), "true_range": ind.true_range(df), "atr14": ind.atr(df, 14),
        "adx14": ind.adx(df, 14), "obv": ind.obv(df), "swing_levels": list(ind.swing_levels(df)),
        "vp_poc": ind.volume_profile_poc(df), "volume_profile": ind.volume_profile(df),
        "pivots": list(ind.pivots(df)), "dollar_volume": ind.dollar_volume(df),
    }
    a = {}
    for o in ["swing", "long_term", "day", "income", "analyze"]:
        def fetcher(_s, df=df):
            return df, {"symbol": "T", "currency": "EGP", "timeframe": "1d", "bars": len(df), "last_close": float(df["close"].iloc[-1]),
                        "as_of": None, "source": "raw", "provides": list(yahoo_egx.PROVIDES)}
        x = analyze_symbol("T", Objective(o), fetcher=fetcher); x.pop("candles", None)
        a[o] = x
    r["analysis"] = a
    res[tag] = clean(r)
json.dump(res, open(out, "w"), sort_keys=True)
print("datasets:", len(res), "python", sys.version.split()[0], "pandas", pd.__version__, "numpy", np.__version__)
