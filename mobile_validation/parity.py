"""Engine parity validation: CURRENT ApexInvest (pristine baseline) vs MOBILE version (modified project).
Part A: CSV import path (POST /v1/analyses/csv) vs baseline engine on the same file.
Part B: live-feed endpoints, baseline server (8002) vs mobile-project server (8001): identical JSON expected.
"""
import sys, os, json, pickle, subprocess, math, csv, itertools, urllib.request, urllib.parse
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synth, requests

M = "http://127.0.0.1:8001"; BASE_SRV = "http://127.0.0.1:8002"
BASEDIR = os.environ.get("APEX_BASELINE", "/tmp/apex_baseline/apexinvest_backend")   # git archive original-desktop-baseline
OBJS = ["swing", "long_term", "day", "income", "analyze"]
os.makedirs("data/parity", exist_ok=True)

# ---------------- datasets -> TradingView-style CSV files
cat = synth.catalog()
t0 = pd.Timestamp("2024-01-01", tz="UTC")
manifest, meta = [], {}
for tag, df in cat:
    df = df.reset_index(drop=True)
    ts = [int((t0 + pd.Timedelta(days=i)).timestamp()) for i in range(len(df))]
    out = df.copy(); out.insert(0, "time", ts); out = out.rename(columns={"volume": "Volume"})
    fn = f"data/parity/{tag}.csv"; out.to_csv(fn, index=False)
    pk = f"data/parity/{tag}.pkl"; pickle.dump(df, open(pk, "wb"))
    for o in OBJS:
        t = f"{tag}|{o}"
        manifest.append({"tag": t, "file": os.path.abspath(fn), "symbol": "TEST", "objective": o, "direct_pickle": os.path.abspath(pk)})
# extra special files
specials = [("EGX_COMI_newest_first", "data/EGX_COMI_newest_first.csv", True), ("EGX_COMI, 1D_tv", "data/EGX_COMI, 1D_tv.csv", False),
            ("EGX_RAYA, 1D", "data/EGX_RAYA, 1D.csv", False), ("short_20bars", "data/short_20bars.csv", False)]
for tag, fn, rev in specials:
    for o in ["swing", "long_term"]:
        manifest.append({"tag": f"{tag}|{o}", "file": os.path.abspath(fn), "symbol": "TEST", "objective": o, "reverse": rev})
json.dump(manifest, open("data/parity/manifest.json", "w"))
subprocess.run([sys.executable, "ref_csv.py", BASEDIR, "data/parity/manifest.json", "data/parity/ref_out.json"], check=True)
ref = json.load(open("data/parity/ref_out.json"))

# ---------------- helpers
def walk(a, b, path=""):
    """yield (path, a, b) for every differing leaf; return max abs numeric diff separately"""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b: yield (f"{path}.{k}", a.get(k, "<missing>"), b.get(k, "<missing>"))
            else: yield from walk(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b): yield (path + ".len", len(a), len(b)); return
        for i, (x, y) in enumerate(zip(a, b)): yield from walk(x, y, f"{path}[{i}]")
    else:
        if a != b and not (isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b)):
            yield (path, a, b)
def maxdiff(a, b):
    m = 0.0
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k in b: m = max(m, maxdiff(a[k], b[k]))
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for x, y in zip(a, b): m = max(m, maxdiff(x, y))
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        m = abs(a - b)
    return m
GROUPS = {
  "indicators": lambda r: {"regime_adx_atr": [r["regime"] and r["regime"].get(k) for k in ("adx", "atr", "atr_pct")] if r.get("regime") else None,
                            "readings": [(s["strategy_id"], s["notes"]) for s in r["signals"]]},
  "strategy":   lambda r: {"used": r["strategies"], "signals": r["signals"], "auto": r.get("auto")},
  "regime":     lambda r: r.get("regime"),
  "structure":  lambda r: r["plan"].get("entry_levels"),
  "entry":      lambda r: {k: r["plan"].get(k) for k in ("entry", "entry_type", "optimal_zone", "confirmation_entry", "chase", "entry_notes")},
  "stop":       lambda r: {k: r["plan"].get(k) for k in ("stop", "stop_basis")},
  "tp1":        lambda r: {k: r["plan"].get(k) for k in ("tp1", "target", "expected_return_pct", "est_tp1")},
  "tp2":        lambda r: {k: r["plan"].get(k) for k in ("tp2", "expected_return_tp2_pct", "est_tp2")},
  "rr":         lambda r: r["plan"].get("rr"),
  "confidence": lambda r: r["plan"].get("confidence"),
  "final_signal": lambda r: {"action": r["plan"].get("action"), "reason": r["plan"].get("reason"), "why": r["plan"].get("why")},
  "expected_move": lambda r: r.get("expected_move"),
}
def short(v):
    s = json.dumps(v, default=str, sort_keys=True); return s if len(s) <= 90 else s[:87] + "..."

rows, casesum = [], []
def compare_case(test, cur, mob, kind):
    diffs_total = 0
    for g, f in GROUPS.items():
        a, b = f(cur), f(mob)
        d = list(walk(a, b)); md = maxdiff(a, b)
        st = "PASS" if not d else "FAIL"
        diffs_total += len(d)
        rows.append({"test": test, "path": kind, "group": g, "current": short(a), "mobile": short(b), "diff": ("0 (identical)" if not d else f"{len(d)} diffs, max|Δ|={md:g}; e.g. {d[0][0]}: {short(d[0][1])} vs {short(d[0][2])}"), "status": st})
    casesum.append((test, kind, diffs_total))

# ---------------- Part A: CSV path
s = requests.Session()
nA = 0
for c in manifest:
    fn = c["file"]; tag = c["tag"]
    with open(fn, "rb") as fh:
        r = s.post(M + "/v1/analyses/csv", files={"file": (os.path.basename(fn), fh, "text/csv")}, data={"symbol": c["symbol"], "objective": c["objective"]})
    assert r.status_code == 200, (tag, r.status_code, r.text[:200])
    mob = r.json(); mob.pop("candles", None); mob.pop("data_source", None); mob.pop("csv_import", None)
    compare_case(f"CSV {tag}", ref[tag]["ingested"], mob, "csv-vs-engine(ingested)")
    if "direct" in ref[tag]:
        compare_case(f"CSV {tag} [vs raw DataFrame]", ref[tag]["direct"], mob, "csv-vs-engine(raw df)")
    nA += 1

# ---------------- Part B: HTTP feed endpoints, baseline server vs mobile-project server
def both(path, method="GET", **kw):
    files = kw.pop("files", None)
    def mk():
        return {"files": {k: (v[0], v[1] if isinstance(v[1], bytes) else v[1].read(), v[2]) for k, v in files.items()}} if files else {}
    fk = mk() if files else {}
    if files:
        raw = {k: v for k, v in fk["files"].items()}
        a = requests.request(method, BASE_SRV + path, files=raw, **kw); b = requests.request(method, M + path, files=raw, **kw)
    else:
        a = requests.request(method, BASE_SRV + path, **kw); b = requests.request(method, M + path, **kw)
    return a, b
SYMS = ["ABUK", "CCAP", "RAYA", "MCRO", "IEEC", "UEGC", "COMI", "SWDY", "EGX30", "FWRY", "ETEL", "TAQA"]
nB = 0
for sym in SYMS:
    for o in OBJS:
        a, b = both(f"/v1/analyses/auto/{sym}?objective={o}")
        assert a.status_code == b.status_code == 200, (sym, o, a.status_code, b.status_code)
        ja, jb = a.json(), b.json()
        compare_case(f"FEED {sym}|{o}", {k: v for k, v in ja.items() if k not in ("candles",)}, {k: v for k, v in jb.items() if k not in ("candles",)}, "feed baseline-server-vs-mobile-server")
        # also compare full JSON incl. data_source & candles
        d = list(walk(ja, jb)); rows.append({"test": f"FEED {sym}|{o}", "path": "full JSON", "group": "full_response", "current": f"{len(json.dumps(ja))} bytes", "mobile": f"{len(json.dumps(jb))} bytes", "diff": "0 (byte-identical)" if not d else f"{len(d)} diffs e.g. {d[0][0]}", "status": "PASS" if not d else "FAIL"})
        nB += 1
other = []
def cmp_http(name, path, method="GET", **kw):
    a, b = both(path, method, **kw)
    ja = a.json() if a.headers.get("content-type", "").startswith("application/json") else a.text
    jb = b.json() if b.headers.get("content-type", "").startswith("application/json") else b.text
    if name.startswith("SCAN") and isinstance(ja, dict) and isinstance(jb, dict):
        ja.pop("as_of", None); jb.pop("as_of", None)   # wall-clock time of the scan run, not engine output
    d = list(walk(ja, jb)) if a.status_code == b.status_code else [("status", a.status_code, b.status_code)]
    rows.append({"test": name, "path": "endpoint baseline-vs-mobile", "group": "full_response", "current": f"HTTP {a.status_code}", "mobile": f"HTTP {b.status_code}", "diff": "0 (identical)" if not d else f"{len(d)} diffs e.g. {d[0]}", "status": "PASS" if not d else "FAIL"})
    casesum.append((name, "endpoint", len(d)))
for hz, rk in itertools.product(["short_swing", "medium_swing", "long_term", "intraday"], ["balanced", "conservative", "aggressive"]):
    cmp_http(f"SCAN {hz}/{rk} (watch-list of 12)", f"/v1/scan?horizon={hz}&risk={rk}&symbols=" + ",".join(SYMS))
cmp_http("SCAN full universe short_swing/balanced", "/v1/scan?horizon=short_swing&risk=balanced&limit=10")
cmp_http("PORTFOLIO", "/v1/portfolio", "POST", json={"holdings": [{"symbol": "COMI", "qty": 100, "avg_cost": 120}, {"symbol": "ABUK", "qty": 50, "avg_cost": 70}, {"symbol": "RAYA", "qty": 300, "avg_cost": 9.5}], "objective": "swing"})
cmp_http("BACKTEST COMI swing", "/v1/backtest/COMI?objective=swing"); cmp_http("BACKTEST ABUK long_term", "/v1/backtest/ABUK?objective=long_term")
cmp_http("BACKTEST universe swing (limit 6)", "/v1/backtest/universe?objective=swing&limit=6")
cmp_http("QUOTES", "/v1/quotes?symbols=COMI,ABUK,CCAP,RAYA,MCRO,IEEC,UEGC")
cmp_http("ASSETS SEARCH ab", "/v1/assets/search?q=ab"); cmp_http("ASSETS SEARCH (all)", "/v1/assets/search")
cmp_http("HEALTH", "/v1/health"); cmp_http("DATA HEALTH", "/v1/data/health?symbol=COMI")
cmp_http("UPLOAD summary", "/v1/uploads", "POST", files={"file": ("EGX_COMI.csv", open("data/EGX_COMI, 1D_tv.csv", "rb"), "text/csv")})
cmp_http("ANALYZE manual (existing endpoint)", "/v1/analyses/analyze", "POST", json={"objective": "swing", "mode": "auto", "candles": {"1d": [{"open": c["o"], "high": c["h"], "low": c["l"], "close": c["c"], "volume": c["v"]} for c in json.load(open(os.path.join(os.environ.get("APEX_BACKEND", "../apexinvest_backend"), "tests/fixtures/COMI.json")))["candles"]]}, "reference_price": 139.28})
cmp_http("DESKTOP UI / (frontend_app.html)", "/"); cmp_http("DESKTOP UI /app", "/app")

json.dump(rows, open("parity_rows.json", "w"))
with open("parity_detail.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=["test", "path", "group", "current", "mobile", "diff", "status"]); w.writeheader(); w.writerows(rows)
fails = [r for r in rows if r["status"] != "PASS"]
print(f"Part A cases: {nA}  Part B feed cases: {nB}  rows: {len(rows)}  FAIL rows: {len(fails)}")
for r in fails[:15]: print("FAIL", r["test"], r["group"], r["diff"][:200])
