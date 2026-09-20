"""Timings + memory of the production-mode server (sandbox CPU; stubbed market data => NO provider latency included)."""
import os, sys, time, json, statistics as st, requests
B = "http://127.0.0.1:8010"; H = {"X-Apex-Key": "Cloud-Test-Key-0123456789"}
pid = int(open("cloud.8010.pid").read())
def rss():
    for l in open(f"/proc/{pid}/status"):
        if l.startswith("VmRSS"): return int(l.split()[1]) / 1024
def timeit(name, fn, n=15):
    ts = []
    for _ in range(n):
        t = time.perf_counter(); r = fn(); ts.append((time.perf_counter() - t) * 1000); assert r.status_code == 200, (name, r.status_code, r.text[:100])
    ts.sort(); return {"test": name, "n": n, "median_ms": round(st.median(ts), 1), "p95_ms": round(ts[int(0.95 * (n - 1))], 1), "max_ms": round(ts[-1], 1)}
out = {"rss_mb_idle": round(rss(), 1)}
s = requests.Session()
res = []
res.append(timeit("GET /v1/health", lambda: s.get(B + "/v1/health")))
res.append(timeit("GET /m/ (mobile shell HTML, gzip)", lambda: s.get(B + "/m/", headers={"Accept-Encoding": "gzip"})))
syms = ["ABUK", "CCAP", "RAYA", "MCRO", "IEEC", "COMI", "SWDY", "UEGC", "ETEL", "FWRY"]
i = [0]
def an():
    i[0] += 1; return s.get(B + f"/v1/analyses/auto/{syms[i[0] % len(syms)]}?objective=swing", headers=H)
res.append(timeit("GET /v1/analyses/auto/{symbol} (full engine, stubbed feed)", an, 30))
csvp = "../mobile_validation/data/EGX_COMI, 1D_tv.csv"; raw = open(csvp, "rb").read()
res.append(timeit("POST /v1/analyses/csv (160-row TradingView export)", lambda: s.post(B + "/v1/analyses/csv", headers=H, files={"file": ("EGX_COMI.csv", raw, "text/csv")}, data={"symbol": "COMI", "objective": "swing"}), 20))
big = b"time,open,high,low,close,Volume\n" + b"".join(f"{1700000000+i*86400},{100+i*0.1:.2f},{101+i*0.1:.2f},{99+i*0.1:.2f},{100.5+i*0.1:.2f},{1000000+i}\n".encode() for i in range(1500))
res.append(timeit("POST /v1/analyses/csv (1,500-row export, ~6 years)", lambda: s.post(B + "/v1/analyses/csv", headers=H, files={"file": ("BIG.csv", big, "text/csv")}, data={"symbol": "BIG", "objective": "swing"}), 10))
out["rss_mb_after_analyses"] = round(rss(), 1)
wl = "VLMR,SVCE,MCRO,BONY,ELEC,NCCW,ALUM,EFID,CIRA,UEGC,ETEL,OCDI,RAYA,ETRS,EXPA,SAUD,CIEB,TAQA,COSG,CCAP,ELKA,FWRY,COPR,HELI,JUFO,DOMT,KRDI,GBCO,MASR,MOED,MHOT,ADPC,ORWE,AMER,COMI"
t = time.perf_counter(); r = s.get(B + f"/v1/scan?horizon=short_swing&risk=balanced&symbols={wl}&refresh=true", headers=H); res.append({"test": "GET /v1/scan (35-symbol watch-list, refresh)", "n": 1, "median_ms": round((time.perf_counter() - t) * 1000, 1), "status": r.status_code})
t = time.perf_counter(); r = s.get(B + "/v1/scan?horizon=short_swing&risk=balanced&limit=10&refresh=true", headers=H); res.append({"test": "GET /v1/scan (whole EGX universe, refresh)", "n": 1, "median_ms": round((time.perf_counter() - t) * 1000, 1), "status": r.status_code})
out["rss_mb_after_scan"] = round(rss(), 1)
t = time.perf_counter(); r = s.get(B + "/v1/backtest/COMI?objective=swing", headers=H); res.append({"test": "GET /v1/backtest/COMI (2y walk-forward)", "n": 1, "median_ms": round((time.perf_counter() - t) * 1000, 1), "status": r.status_code})
t = time.perf_counter(); r = s.post(B + "/v1/portfolio", headers=H, json={"holdings": [{"symbol": "COMI", "qty": 100, "avg_cost": 120}, {"symbol": "ABUK", "qty": 50, "avg_cost": 70}, {"symbol": "RAYA", "qty": 300, "avg_cost": 9.5}], "objective": "swing"}); res.append({"test": "POST /v1/portfolio (3 holdings)", "n": 1, "median_ms": round((time.perf_counter() - t) * 1000, 1), "status": r.status_code})
out["rss_mb_after_backtest"] = round(rss(), 1)
# payload sizes
r = s.get(B + "/v1/analyses/auto/ABUK", headers=H); out["analysis_json_kb"] = round(len(r.content) / 1024, 1)
for f in ("index.html", "app.js", "app.css", "i18n.js", "config.js", "sw.js"):
    a = s.get(B + "/m/" + f, headers={"Accept-Encoding": "gzip"}); out[f"m/{f}_wire_kb"] = round(int(a.headers.get("content-length", len(a.content))) / 1024, 1)
out["results"] = res
json.dump(out, open("perf_results.json", "w"), indent=1); print(json.dumps(out, indent=1))
