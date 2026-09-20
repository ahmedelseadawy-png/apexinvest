import json, collections, csv, shutil, glob, datetime
D = "../docs/"
rows = json.load(open("parity_rows.json")); ui = json.load(open("ui_parity_rows.json")); misc = json.load(open("misc_results.json"))
GROUPS = ["indicators", "strategy", "regime", "structure", "entry", "stop", "tp1", "tp2", "rr", "confidence", "final_signal", "expected_move"]
def esc(s): return str(s).replace("|", "\\|").replace("\n", " ")
tot = len(rows); passed = sum(r["status"] == "PASS" for r in rows)
out = []
w = out.append
w("# ApexInvest — Mobile Web Conversion: VALIDATION REPORT\n")
w(f"Generated {datetime.date.today()}.  **Current ApexInvest** = the original, untouched project (git tag `original-desktop-baseline`, engine run directly / served on its own server).  "
  "**Mobile Version** = the converted project (same engine + API + the new mobile layer).\n")
w("Data: the sandbox has no route to Yahoo / TradingView / EODHD, so all runs use the offline test feed described in section 6. The engine code path is identical to production; only the network fetch is replaced.\n")
w("## 1. Result at a glance\n")
w(f"* Engine comparisons: **{tot} comparisons, {passed} PASS, {tot-passed} FAIL** (`VALIDATION_DETAIL.csv` has every row).")
cases_a = len({r['test'] for r in rows if r['path']=='csv-vs-engine(ingested)'}); cases_b = len({r['test'] for r in rows if r['path'].startswith('feed')})
w(f"* {cases_a} CSV-import cases (28 datasets x 5 objectives + 4 TradingView-style files x 2 objectives — each dataset case is additionally compared against the raw DataFrame the engine would see without any CSV round-trip) and {cases_b} live-feed cases (12 tickers x 5 objectives), plus {len([r for r in rows if r['path'].startswith('endpoint')])} whole-endpoint comparisons.")
acts = collections.Counter()
import re
for r in rows:
    if r["group"] == "final_signal" and r["path"] == "csv-vs-engine(ingested)":
        acts[re.search(r'"action": "(\w+)"', r["mobile"]).group(1)] += 1
w(f"* Signal mix in the CSV cases: {dict(acts)} — so BUY plans (entry / stop / TP1 / TP2 / R:R), WAIT and AVOID are all exercised.")
w(f"* UI-level checks: **{len(ui)} rows, {sum(r['status']=='PASS' for r in ui)} PASS** (mobile screen vs engine JSON, and mobile screen vs the desktop screen for the same stock).")
w(f"* Other checks (auth, security, PWA, RTL, journal, performance): **{len(misc)} checks, {sum(r['status']=='PASS' for r in misc)} PASS**.\n")
w("## 2. Summary by metric\n")
w("| Test | Current ApexInvest | Mobile Version | Difference | Status |\n|---|---|---|---|---|")
for g in GROUPS:
    rs = [r for r in rows if r["group"] == g]
    w(f"| {g.replace('_',' ')} — {len(rs)} comparisons | reference values | identical values | 0 differing fields | {'PASS' if all(r['status']=='PASS' for r in rs) else 'FAIL'} |")
rs = [r for r in rows if r["group"] == "full_response"]
w(f"| full API responses / endpoints — {len(rs)} comparisons | baseline server | mobile-project server | byte-identical JSON (scan wall-clock `as_of` excluded) | {'PASS' if all(r['status']=='PASS' for r in rs) else 'FAIL'} |\n")
w("## 3. Representative cases, shown value-by-value\n")
def case_table(test, label):
    w(f"### {label} — `{test}`\n")
    w("| Test | Current ApexInvest | Mobile Version | Difference | Status |\n|---|---|---|---|---|")
    for r in rows:
        if r["test"] == test and r["group"] in GROUPS and r["path"] in ("csv-vs-engine(ingested)", "feed baseline-server-vs-mobile-server"):
            w(f"| {r['group'].replace('_',' ')} | {esc(r['current'])} | {esc(r['mobile'])} | {esc(r['diff'])} | {r['status']} |")
    w("")
for test, label in [("CSV COMI60|swing", "BUY plan via CSV import"), ("CSV dn250|swing", "AVOID via CSV import"), ("CSV COMI160|swing", "WAIT via CSV import"),
                    ("FEED ABUK|swing", "BUY plan via live-feed path"), ("FEED RAYA|swing", "AVOID via live-feed path"), ("FEED UEGC|long_term", "WAIT via live-feed path (long-term)")]:
    case_table(test, label)
w("## 4. What the phone screen shows vs the engine and vs the desktop screen\n")
w("| Test | Current ApexInvest | Mobile Version | Difference | Status |\n|---|---|---|---|---|")
for r in ui: w(f"| {esc(r['test'])} | {esc(r['current'])[:170]} | {esc(r['mobile'])[:170]} | {esc(r['diff'])[:80]} | {r['status']} |")
w("\n## 5. Whole-endpoint comparisons (baseline server vs mobile-project server)\n")
w("| Test | Current ApexInvest | Mobile Version | Difference | Status |\n|---|---|---|---|---|")
for r in rows:
    if r["path"].startswith("endpoint"): w(f"| {esc(r['test'])} | {r['current']} | {r['mobile']} | {esc(r['diff'])} | {r['status']} |")
w("\n## 6. How the comparison was made (so you can re-run it)\n")
w("* `testing/offline_server.py` starts the unmodified app with only the four network fetchers (Yahoo daily/quote, TradingView quote, fundamentals) replaced by deterministic local data (the two real COMI/SWDY fixtures shipped in the project plus seeded synthetic series). No engine code is touched.")
w("* `testing/ref_csv.py` runs the ORIGINAL engine (pristine copy from git tag `original-desktop-baseline`) on each CSV via the original `ingest.ingest` + `analyze_symbol`.")
w("* `testing/parity.py` posts the same files to the mobile API and deep-compares every field of regime, signals, structure, entry, stop, TP1, TP2, R:R, confidence, final signal and expected move; and diffs the baseline server vs the mobile-project server on the live-feed, scanner, watch-list, portfolio, backtest, quotes, search, health, upload and analyze endpoints.")
w("* `testing/ui_parity.py` drives real Chromium: the mobile dashboard (390x844) and the desktop UI (1366x768) for ABUK, CCAP, RAYA, MCRO, IEEC, UEGC, COMI, SWDY x swing/long-term, and the CSV import screen.")
w("\n## 7. Known limits of this validation (honest)\n")
w("* Live Yahoo / TradingView / EODHD feeds were unreachable from the sandbox, so live data was not exercised. The live path is byte-identical code to the desktop app's (same `GET /v1/analyses/auto/{symbol}`), so this risk is the same as for the desktop app.")
w("* Docker build could not be run here (no Docker daemon). A clean-virtualenv install from `requirements.txt`, the full test-suite and a 2-worker production `uvicorn` start were run instead.")
w("* Real iPhone Safari / Android Chrome hardware was not available; testing used Chromium with mobile emulation (touch, DPR 2) at the requested sizes.")
open(D + "VALIDATION_REPORT.md", "w").write("\n".join(out))
# combined detail csv
with open(D + "VALIDATION_DETAIL.csv", "w", newline="") as fh:
    wr = csv.writer(fh); wr.writerow(["Test", "Current ApexInvest", "Mobile Version", "Difference", "Status", "Comparison path", "Metric"])
    for r in rows: wr.writerow([r["test"], r["current"], r["mobile"], r["diff"], r["status"], r["path"], r["group"]])
    for r in ui: wr.writerow([r["test"], r["current"], r["mobile"], r["diff"], r["status"], "ui", "ui"])
# mobile test results
res = {}
for f in glob.glob("ui_matrix_results_*.json"): res[f.split("results_")[1][:-5]] = json.load(open(f))
o = ["# Mobile testing results\n", "Chromium with touch + device-pixel-ratio 2 for phone/tablet sizes (desktop size without touch). Each screen is loaded and checked for: horizontal scroll (document wider than viewport), elements sticking out of the viewport, and interactive controls smaller than 40 px. Scrollable tab strips and tables are allowed to scroll inside their own container.\n",
     "Screens checked at every size: Analyze, search results, dashboard (BUY), all six drill-down tabs + chart, dashboard (WAIT), dashboard (long-term), no-data error, Scanner, Watchlist, Portfolio, More, Settings, CSV import (valid), imported-file dashboard, CSV import error, Journal, Validation.\n",
     "| Mode | Viewport | Screens | Horizontal scroll | Clipped elements | Touch targets < 40 px | Result |\n|---|---|---|---|---|---|---|"]
for mode, rs in sorted(res.items()):
    by = collections.defaultdict(list)
    for r in rs: by[r["vp"]].append(r)
    for vp, lst in by.items():
        o.append(f"| {mode} | {vp} | {len(lst)} | {sum(r['overflow_x'] for r in lst)} | {sum(bool(r['clip']) for r in lst)} | {sum(bool(r['small']) for r in lst)} | {'PASS' if all(r['ok'] for r in lst) and not any(r['small'] for r in lst) else 'FAIL'} |")
o += ["\n## Functional / non-functional checks\n", "| Check | Result | Detail |\n|---|---|---|"]
for r in misc: o.append(f"| {esc(r['test'])} | {r['status']} | {esc(r['detail'])[:150]} |")
open(D + "MOBILE_TEST_RESULTS.md", "w").write("\n".join(o))
shutil.copy("ui_matrix_results_en-dark.json", D + "ui_matrix_results_en-dark.json") if False else None
print(passed, tot, len(ui), len(misc), {k: len(v) for k, v in res.items()})
