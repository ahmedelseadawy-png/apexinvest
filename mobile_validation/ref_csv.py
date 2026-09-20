"""Reference runner: executes the ORIGINAL (baseline) engine, unmodified, on candles.
usage: ref_csv.py <baseline_backend_dir> <manifest.json> <out.json>"""
import sys, json, pickle
backend, manifest, out = sys.argv[1:4]
sys.path.insert(0, backend)
import pandas as pd
from apexinvest.domain import Objective
from apexinvest.ingest import files as ingest
from apexinvest.market import yahoo_egx
from apexinvest.service import analyze_symbol

def run(df, sym, obj):
    def fetcher(_s):
        return df, {"symbol": sym, "currency": "EGP", "timeframe": "1d", "bars": len(df), "last_close": float(df["close"].iloc[-1]),
                    "as_of": None, "source": "ref", "provides": list(yahoo_egx.PROVIDES)}
    r = analyze_symbol(sym, Objective(obj), fetcher=fetcher)
    r.pop("candles", None); r.pop("data_source", None)
    return r

res = {}
for c in json.load(open(manifest)):
    data = open(c["file"], "rb").read()
    ing = ingest.ingest(c["file"].split("/")[-1], data)
    df = ing.candles.reset_index(drop=True)
    if c.get("reverse"): df = df.iloc[::-1].reset_index(drop=True)
    entry = {"ingested": run(df, c["symbol"], c["objective"])}
    if c.get("direct_pickle"):
        entry["direct"] = run(pickle.load(open(c["direct_pickle"], "rb")), c["symbol"], c["objective"])
    res[c["tag"]] = entry
json.dump(res, open(out, "w"), default=float)
print("ref cases:", len(res))
