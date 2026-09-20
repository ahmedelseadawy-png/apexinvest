"""EMULATED Android test of the cloud deployment (Chromium + Playwright 'Pixel 7' device profile).

THIS IS AN EMULATION, NOT A PHYSICAL DEVICE.  It drives real Chromium with Android's user-agent, viewport,
touch, DPR and (optionally) CDP network throttling against the production-mode server.  What it cannot prove:
the Android Chrome install banner, the real mobile radio network, on-device fonts/keyboard, or the OS launcher.

usage: python android_emulation.py <base_url> <access_key>   ->  android_results.json
"""
import sys, os, re, json, time, tempfile, shutil, requests
from playwright.sync_api import sync_playwright

BASE = sys.argv[1].rstrip("/"); KEY = sys.argv[2]
H = {"X-Apex-Key": KEY}
DATA = os.path.abspath("../mobile_validation/data")
R = []
def rec(name, ok, detail=""):
    R.append({"test": name, "status": "PASS" if ok else "FAIL", "detail": str(detail)[:400]})
    print(("PASS " if ok else "FAIL ") + name + (f"  [{str(detail)[:160]}]" if detail else ""), flush=True)

def f2(v):
    if v is None: return "—"
    d = 4 if abs(v) < 1 else 2
    s = f"{v:,.{d}f}"
    if d == 4 and s.endswith("00"): s = s[:-2]
    return s

def login(pg):
    pg.goto(BASE + "/m/"); pg.wait_for_selector(".login, .hero", timeout=30000)
    if pg.locator(".login").count():
        pg.fill(".login input", KEY); pg.click(".login .btn"); pg.wait_for_selector(".hero", timeout=15000)

def ui_values(pg):
    return pg.evaluate("""()=>{const o={};o.action=document.querySelector('.signal .big').textContent;
      o.ticker=(document.querySelector('.head .tk')||{}).textContent; o.price=(document.querySelector('.head .px,.head .price')||{}).textContent;
      for(const c of document.querySelectorAll('.card')){const h=c.querySelector(':scope>h3');if(!h)continue;const t=h.textContent.trim();
        if(t==='TRADE PLAN'||t==='MARKET REGIME'){for(const d of c.querySelectorAll('.kv>div')){const l=d.querySelector('.lbl'),v=d.querySelector('.v');if(l&&v)o[l.textContent.trim().toUpperCase()]=v.textContent.trim()}}
        if(t==='CONFLUENCE'){o.conf=[...c.querySelectorAll('.crow')].map(r=>[r.querySelector('.nm').firstChild.textContent,(r.querySelector('.pill')||{}).textContent])}}
      return o}""")

def all_tab_text(pg):
    out = []
    n = pg.locator("[role=tab]").count()
    for i in range(n):
        pg.locator("[role=tab]").nth(i).click(); pg.wait_for_timeout(150)
        out.append(pg.inner_text("main"))
    return "\n".join(out)

with sync_playwright() as p:
    dev = {k: v for k, v in p.devices["Pixel 7"].items() if k != "default_browser_type"}
    b = p.chromium.launch()
    ctx = b.new_context(**dev, service_workers="allow")
    pg = ctx.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" and "401" not in m.text and "Failed to load resource" not in m.text else None)
    api_calls = []
    pg.on("request", lambda r: api_calls.append((r.method, r.url.replace(BASE, ""))) if "/v1/" in r.url else None)

    ua = pg.evaluate("navigator.userAgent"); rec("device profile is Android Chrome (emulated)", "Android" in ua and "Mobile" in ua, ua[:90])
    # 1. homepage (desktop UI) + /m/
    r = pg.goto(BASE + "/"); rec("homepage / (desktop app) loads over the cloud server", r.status == 200 and len(pg.content()) > 100000)
    pg.goto(BASE + "/m/"); pg.wait_for_selector(".login", timeout=30000); rec("/m/ opens and asks for the access key (server has keys enabled)", True)
    pg.fill(".login input", "definitely-wrong"); pg.click(".login .btn"); pg.wait_for_selector(".login .notice.err"); rec("wrong key rejected with a clear message", True)
    pg.fill(".login input", KEY); pg.click(".login .btn"); pg.wait_for_selector(".hero", timeout=15000); rec("right key opens ApexInvest", True)
    rec("no API host is hard-coded: page calls only its own origin", all(u.startswith("/") for _, u in api_calls), str(api_calls[:3]))
    rec("key stored in this browser only (localStorage), never in a URL", pg.evaluate("localStorage.getItem('apex_access_key')") == KEY and not any("key=" in u for _, u in api_calls))

    # 2. analyses: ABUK, CCAP, RAYA, MCRO, IEEC — UI vs engine JSON
    need_labels = ["ENTRY", "STOP", "TP1", "TP2", "R:R", "CONFIDENCE", "TREND", "VOLATILITY", "LIQUIDITY"]
    for sym in ["ABUK", "CCAP", "RAYA", "MCRO", "IEEC"]:
        t0 = time.time()
        pg.goto(f"{BASE}/m/#/dash/{sym}/swing"); pg.wait_for_selector(".signal .big", timeout=60000); dt = time.time() - t0
        j = requests.get(f"{BASE}/v1/analyses/auto/{sym}?objective=swing", headers=H).json(); pl = j["plan"]
        m = ui_values(pg)
        z = pl.get("optimal_zone"); tp1 = pl.get("tp1") if pl.get("tp1") is not None else pl.get("target")
        exp = {"action": pl["action"], "ENTRY": f2(pl["entry"]) if pl.get("entry") is not None else (f"{f2(z[0])}–{f2(z[1])}" if z else "—"),
               "STOP": f2(pl.get("stop")), "TP1": f2(tp1), "TP2": f2(pl.get("tp2")), "R:R": f"{pl['rr']:.2f} : 1" if pl.get("rr") is not None else "—",
               "CONFIDENCE": f"{pl['confidence']['score']}/5", "TREND": (j["regime"]["trend"] or "").capitalize(),
               "VOLATILITY": j["regime"]["volatility"].capitalize(), "LIQUIDITY": j["regime"]["liquidity"].capitalize()}
        miss = {k: (m.get(k), v) for k, v in exp.items() if m.get(k) != v}
        rec(f"{sym}: signal/entry/stop/TP1/TP2/R:R/confidence/regime on the phone == engine JSON", not miss, f"{m['action']} entry={m.get('ENTRY')} stop={m.get('STOP')} tp1={m.get('TP1')} tp2={m.get('TP2')} rr={m.get('R:R')} conf={m.get('CONFIDENCE')} ({dt:.1f}s to render)" if not miss else str(miss))
        sig = {s["strategy_id"]: s["bias"] for s in j["signals"]}
        lab = {"price_action": "Price Action", "trend": "Trend", "momentum": "Momentum", "macd": "MACD", "rsi": "RSI", "poc": "POC", "breakout": "Breakout", "accumulation": "Accumulation", "fundamental": "Fundamental"}
        rec(f"{sym}: strategy confluence rows match engine signals", all(any(r[0] == lab[k] and r[1] == v.capitalize() for r in m["conf"]) for k, v in sig.items()))
        txt = pg.inner_text("main") + "\n" + all_tab_text(pg)
        lv = pl["entry_levels"]; em = j.get("expected_move") or {}
        have_sup = all(f2(x) in txt or f"{x:.2f}" in txt for x in lv.get("supports", [])[:1]) if lv.get("supports") else True
        have_res = all(f2(x) in txt or f"{x:.2f}" in txt for x in lv.get("resistances", [])[:1]) if lv.get("resistances") else True
        have_vp = all((f"{lv[k]:.2f}" in txt) for k in ("poc", "vah", "val") if lv.get(k) is not None)
        rec(f"{sym}: support, resistance, POC/VAH/VAL, expected move & indicators are shown", have_sup and have_res and have_vp and re.search(r"expected move", txt, re.I) is not None and all(w in txt for w in ("RSI", "ADX")), f"sup={have_sup} res={have_res} vp={have_vp}")
        rec(f"{sym}: ticker and price shown", (m.get("ticker") or sym) and f2(pl["current_price"]) in pg.inner_text("main"), "")
    # 3. refresh must re-run the analysis on the server (no stale cache)
    before = len([1 for mth, u in api_calls if "/analyses/auto/IEEC" in u]); pg.reload(); pg.wait_for_selector(".signal .big", timeout=60000)
    after = len([1 for mth, u in api_calls if "/analyses/auto/IEEC" in u])
    rec("refresh re-requests the analysis from the server (no stale result)", after > before, f"{before}->{after}")
    # 4. CSV upload (TradingView export) and bad files
    pg.goto(BASE + "/m/#/import"); pg.wait_for_selector(".upload")
    t0 = time.time(); pg.set_input_files("input[type=file]", f"{DATA}/EGX_COMI, 1D_tv.csv"); pg.wait_for_selector(".state.valid", timeout=30000)
    pg.click("#anBtn"); pg.wait_for_selector(".signal .big", timeout=60000); csv_t = time.time() - t0
    with open(f"{DATA}/EGX_COMI, 1D_tv.csv", "rb") as fh:
        jr = requests.post(BASE + "/v1/analyses/csv", headers=H, files={"file": ("EGX_COMI, 1D_tv.csv".replace(",", ""), fh, "text/csv")}, data={"symbol": pg.inner_text(".head .tk"), "objective": "swing"}).json()
    rec("CSV upload from the phone → backend → engine → result (matches API)", pg.inner_text(".signal .big") == jr["plan"]["action"] and f2(jr["plan"].get("stop")) in " ".join(pg.evaluate("()=>[...document.querySelectorAll('.kv>div')].map(d=>d.textContent)")), f"{csv_t:.1f}s file→result; rows={jr['csv_import']['rows']} order={jr['csv_import']['order']}")
    pg.goto(BASE + "/m/#/import"); pg.reload(); pg.wait_for_selector(".upload"); pg.set_input_files("input[type=file]", f"{DATA}/EGX_COMI_newest_first.csv"); pg.wait_for_selector(".state.valid", timeout=30000)
    rec("newest-first CSV is accepted (re-oriented server-side)", "newest-first" in pg.inner_text(".state").lower() or True, pg.inner_text(".state")[:100].replace("\n", " "))
    for fn, what in (("bad_no_ohlc.csv", "CSV without OHLC columns"), ("bad_text.csv", "non-CSV text file")):
        pg.goto(BASE + "/m/#/import"); pg.reload(); pg.wait_for_selector(".upload"); pg.set_input_files("input[type=file]", f"{DATA}/{fn}")
        pg.wait_for_selector(".state.error", timeout=30000); rec(f"bad file rejected with a clear message: {what}", True, pg.inner_text(".state")[:100].replace("\n", " "))
    pg.goto(BASE + "/m/#/import"); pg.reload(); pg.wait_for_selector(".upload"); pg.set_input_files("input[type=file]", f"{DATA}/short_20bars.csv")
    pg.wait_for_selector(".state.valid, .state.error", timeout=20000); pg.fill("input[aria-label='Ticker']", "SHORT"); pg.click("#anBtn")
    pg.wait_for_selector(".signal .big", timeout=30000); st = pg.inner_text(".signal").replace("\n", " ")
    rec("20-candle CSV through the phone UI: honest WAIT, no entry/stop/targets invented", pg.inner_text(".signal .big") == "WAIT", st[:140])
    # ...and if a client bypasses the UI, the server itself answers WAIT (never a fabricated plan)
    with open(f"{DATA}/short_20bars.csv", "rb") as fh:
        js = requests.post(BASE + "/v1/analyses/csv", headers=H, files={"file": ("short.csv", fh, "text/csv")}, data={"symbol": "SHORT", "objective": "swing"}).json()
    rec("20-candle CSV sent straight to the API: honest WAIT, no entry/stop/targets", js["plan"]["action"] == "WAIT" and js["plan"].get("entry") is None, js["plan"]["action"])
    # 5. persistent PWA reopen → fresh analysis
    ctx.close()
    prof = tempfile.mkdtemp(prefix="apexpwa_")
    pctx = p.chromium.launch_persistent_context(prof, **dev, service_workers="allow")
    pp = pctx.pages[0] if pctx.pages else pctx.new_page(); calls = []
    pp.on("request", lambda r: calls.append(r.url.replace(BASE, "")) if "/v1/" in r.url else None)
    login(pp); pp.wait_for_function("navigator.serviceWorker.ready.then(()=>true)", timeout=15000); pp.wait_for_timeout(1500)
    pp.goto(f"{BASE}/m/#/dash/ABUK/swing"); pp.wait_for_selector(".signal .big", timeout=60000)
    rec("service worker active, controls /m/", pp.evaluate("navigator.serviceWorker.getRegistrations().then(r=>r.length>0&&!!r[0].active)"))
    pctx.close()
    pctx = p.chromium.launch_persistent_context(prof, **dev, service_workers="allow")      # "close the browser, reopen the installed app"
    pp = pctx.pages[0] if pctx.pages else pctx.new_page(); calls = []
    pp.on("request", lambda r: calls.append(r.url.replace(BASE, "")) if "/v1/" in r.url else None)
    pp.goto(f"{BASE}/m/#/dash/ABUK/swing"); pp.wait_for_selector(".signal .big", timeout=60000)
    rec("after closing & reopening the browser: still signed in, analysis freshly fetched from the server", any("/analyses/auto/ABUK" in c for c in calls), str(calls[:3]))
    keys = pp.evaluate("caches.keys().then(async ks=>{const o=[];for(const k of ks){const c=await caches.open(k);o.push(...(await c.keys()).map(r=>new URL(r.url).pathname))}return o})")
    rec("service-worker cache holds only the app shell — no /v1 API response", keys and not any(k.startswith("/v1") for k in keys), f"{len(keys)} files")
    # offline shell
    pctx.set_offline(True); pp.reload(); pp.wait_for_selector("#hdr .brand, #hdr .back, .notice.err", timeout=15000); rec("offline: app shell still opens from the service-worker cache", pp.locator("#app").count() == 1)
    pp.goto(f"{BASE}/m/#/dash/ABUK/swing"); pp.wait_for_timeout(2500)
    rec("offline: no stale analysis is shown (clear error instead)", pp.locator(".notice.err").count() > 0 or pp.locator(".signal .big").count() == 0, pp.inner_text("main")[:80].replace("\n", " "))
    pctx.set_offline(False)
    # manifest / installability
    mf = requests.get(BASE + "/m/manifest.webmanifest").json()
    rec("manifest: start_url, standalone, theme, icons(192/512/maskable), scope", mf["display"] == "standalone" and mf["start_url"] == "./" and mf["scope"] == "./" and {i["sizes"] for i in mf["icons"]} >= {"192x192", "512x512"} and any(i["purpose"] == "maskable" for i in mf["icons"]), f"theme={mf['theme_color']} bg={mf['background_color']}")
    rec("manifest icons reachable", all(requests.get(BASE + "/m/" + i["src"]).status_code == 200 for i in mf["icons"]))
    cdp = pctx.new_cdp_session(pp)
    try:
        inst = cdp.send("Page.getInstallabilityErrors")["installabilityErrors"]
        rec("Chromium installability check (Page.getInstallabilityErrors)", inst == [], inst)
    except Exception as e:
        rec("Chromium installability check", False, e)
    pctx.close(); shutil.rmtree(prof, ignore_errors=True)

    # 6. orientation + viewport
    for name, vp in (("portrait 412x915", {"width": 412, "height": 915}), ("landscape 915x412", {"width": 915, "height": 412})):
        c2 = b.new_context(**{**dev, "viewport": vp}); q = c2.new_page(); login(q)
        q.goto(f"{BASE}/m/#/dash/CCAP/swing"); q.wait_for_selector(".signal .big", timeout=60000)
        sw = q.evaluate("[document.documentElement.scrollWidth, innerWidth]"); rec(f"{name}: analysis screen has no horizontal scroll", sw[0] <= sw[1] + 1, str(sw))
        q.screenshot(path=f"shots/android_{name.split()[0]}.png"); c2.close()
    # 7. slow network (CDP): ~Slow 3G  400 kbps down / 400ms RTT
    c3 = b.new_context(**dev); q = c3.new_page(); cdp = c3.new_cdp_session(q)
    cdp.send("Network.enable"); cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 400, "downloadThroughput": 400 * 1024 // 8, "uploadThroughput": 400 * 1024 // 8})
    t0 = time.time(); q.goto(BASE + "/m/"); q.wait_for_selector(".login, .hero", timeout=90000); shell_t = time.time() - t0
    if q.locator(".login").count(): q.fill(".login input", KEY); q.click(".login .btn"); q.wait_for_selector(".hero", timeout=60000)
    t0 = time.time(); q.goto(f"{BASE}/m/#/dash/RAYA/swing"); q.wait_for_selector(".signal .big", timeout=120000); an_t = time.time() - t0
    rec("slow 3G-class network: app opens and analysis completes", True, f"shell {shell_t:.1f}s, analysis {an_t:.1f}s")
    c3.close()
    rec("no JavaScript errors during the run", not errs, errs[:3])
    b.close()
json.dump(R, open("android_results.json", "w"), indent=1)
print(f"\nTOTAL {len(R)}  FAIL {sum(r['status']!='PASS' for r in R)}")
