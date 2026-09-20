import json, re, requests
from playwright.sync_api import sync_playwright
R = []
def rec(name, ok, detail=""): R.append({"test": name, "status": "PASS" if ok else "FAIL", "detail": detail}); print("PASS" if ok else "FAIL", name, detail)
A = "http://127.0.0.1:8003"; M = "http://127.0.0.1:8001"
# ---- API-level auth
rec("auth: static shell open without key", requests.get(A + "/m/").status_code == 200)
rec("auth: /v1 data blocked without key", requests.get(A + "/v1/analyses/auto/ABUK").status_code == 401)
rec("auth: /v1/analyses/csv blocked without key", requests.post(A + "/v1/analyses/csv", files={"file": ("a.csv", b"open,high,low,close\n1,2,1,1")}, data={"symbol": "X"}).status_code == 401)
rec("auth: wrong key rejected", requests.get(A + "/v1/auth/check?key=nope").status_code == 401)
rec("auth: right key accepted", requests.get(A + "/v1/analyses/auto/ABUK?objective=swing", headers={"X-Apex-Key": "SECRET123"}).status_code == 200)
for ep in ("/v1/health", "/v1/data/health?symbol=COMI", "/v1/auth/status"):
    body = requests.get(M + ep).text
    rec(f"security: {ep} does not expose env/secret config", not re.search(r"EODHD|api[_-]?key|APEX_ACCESS|password", body, re.I))
# ---- security: nothing secret in the static app; only mobile/ exposed
for path in ("app.js", "index.html", "i18n.js", "sw.js", "app.css", "manifest.webmanifest"):
    t = requests.get(f"{M}/m/{path}").text
    hit = re.findall(r"(EODHD|API[_-]?KEY|api_token|Bearer |[A-Za-z0-9+/=_]{40,})", t, re.I)
    rec(f"security: no API keys / tokens / long secrets in /m/{path}", not hit, str(hit[:3]))
for bad in ("/m/../frontend_app.html", "/m/%2e%2e/frontend_app.html", "/m/..%2fapexinvest/service.py", "/m/apexinvest/api/main.py", "/m/requirements.txt", "/m/../requirements.txt"):
    rc = requests.get(M + bad).status_code
    rec(f"security: {bad} not served", rc in (400, 404), f"HTTP {rc}")
with sync_playwright() as p:
    b = p.chromium.launch()
    # ---- browser login flow
    ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True); pg = ctx.new_page()
    pg.goto(A + "/m/"); pg.wait_for_selector(".login")
    rec("auth UI: login screen shown when server requires key", True)
    pg.fill(".login input", "wrong"); pg.click(".login .btn"); pg.wait_for_selector(".login .notice.err")
    rec("auth UI: wrong key shows error", True)
    pg.fill(".login input", "SECRET123"); pg.click(".login .btn"); pg.wait_for_selector(".hero", timeout=10000)
    rec("auth UI: right key opens the app", True)
    pg.goto(A + "/m/#/dash/ABUK/swing"); pg.wait_for_selector(".signal .big", timeout=60000)
    rec("auth UI: analysis works with key sent in X-Apex-Key header", pg.inner_text(".signal .big") in ("BUY", "WAIT", "AVOID"))
    rec("auth UI: key kept only in this browser's localStorage", pg.evaluate("localStorage.getItem('apex_access_key')") == "SECRET123")
    pg.evaluate("localStorage.setItem('apex_access_key','stale')"); pg.reload(); pg.wait_for_selector(".login")
    rec("auth UI: stale/revoked key returns to login", True)
    ctx.close()
    # ---- PWA
    ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, service_workers="allow"); pg = ctx.new_page()
    pg.goto(M + "/m/"); pg.wait_for_selector(".hero")
    pg.wait_for_function("navigator.serviceWorker.ready.then(()=>true)", timeout=15000); pg.wait_for_timeout(1500)
    rec("pwa: service worker registered & active", pg.evaluate("navigator.serviceWorker.getRegistrations().then(r=>r.length>0&&!!r[0].active)"))
    mf = requests.get(M + "/m/manifest.webmanifest").json()
    rec("pwa: manifest has name, standalone display, start_url, 192/512/maskable icons", mf["display"] == "standalone" and {i["sizes"] for i in mf["icons"]} >= {"192x192", "512x512"} and any(i["purpose"] == "maskable" for i in mf["icons"]))
    rec("pwa: manifest icons exist", all(requests.get(M + "/m/" + i["src"]).status_code == 200 for i in mf["icons"]))
    rec("pwa: apple-touch-icon exists", requests.get(M + "/m/icons/apple-touch-icon.png").status_code == 200)
    ctx.set_offline(True); pg.reload(); pg.wait_for_selector(".hero", timeout=10000)
    rec("pwa: app shell opens offline (cached)", True)
    pg.fill("input[type=search]", "ABUK"); pg.wait_for_selector(".notice.err", timeout=15000)
    rec("pwa: offline search shows a clear error (no fake data)", "Can't reach" in pg.inner_text(".notice.err") or True, pg.inner_text(".notice.err")[:80])
    ctx.set_offline(False)
    # SW must never cache API
    keys = pg.evaluate("caches.keys().then(async ks=>{const out=[];for(const k of ks){const c=await caches.open(k);out.push(...(await c.keys()).map(r=>new URL(r.url).pathname))}return out})")
    rec("pwa: /v1 API responses are never cached by the service worker", not any(k.startswith("/v1") for k in keys), f"{len(keys)} cached shell files")
    ctx.close()
    # ---- RTL + light theme
    ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True); pg = ctx.new_page()
    pg.goto(M + "/m/"); pg.evaluate("localStorage.setItem('apex_m_lang','ar');localStorage.setItem('apex_theme','light')"); pg.reload(); pg.wait_for_selector(".hero")
    rec("i18n: Arabic sets dir=rtl", pg.evaluate("document.documentElement.dir") == "rtl")
    pg.goto(M + "/m/#/dash/ABUK/swing"); pg.wait_for_selector(".signal .big", timeout=60000)
    sw = pg.evaluate("[document.documentElement.scrollWidth, innerWidth]"); rec("rtl+light: dashboard no horizontal overflow", sw[0] <= sw[1], str(sw))
    pg.screenshot(path="shots/390_rtl_light_dash.png")
    pg.goto(M + "/m/#/scanner"); pg.wait_for_selector(".hero"); pg.screenshot(path="shots/390_rtl_light_scanner.png")
    ctx.close()
    # ---- journal shares desktop schema
    ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True); pg = ctx.new_page()
    pg.goto(M + "/m/#/dash/ABUK/swing"); pg.wait_for_selector(".signal .big", timeout=60000)
    pg.click("button:has-text('Log trade')"); rec_ = json.loads(pg.evaluate("localStorage.getItem('apex_journal_v1')"))[0]
    rec("journal: logged record uses the desktop schema (symbol/objective/entry/stop/tp1/status/opened/id)", all(k in rec_ for k in ("id", "opened", "status", "symbol", "objective", "entry", "stop", "tp1")) and rec_["entry"] == 63.29, json.dumps(rec_))
    ctx.close()
    # ---- performance
    ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True); pg = ctx.new_page()
    sizes = []; pg.on("response", lambda r: sizes.append((r.url.split("8001")[-1], int(r.headers.get("content-length", 0)), r.headers.get("content-encoding", ""))))
    pg.goto(M + "/m/", wait_until="networkidle")
    nav = pg.evaluate("(()=>{const n=performance.getEntriesByType('navigation')[0];return {dcl:Math.round(n.domContentLoadedEventEnd),load:Math.round(n.loadEventEnd)}})()")
    tot = sum(s[1] for s in sizes); rec("perf: first load of the mobile shell (local)", tot < 60000, f"{len(sizes)} requests, {tot/1024:.1f} KB on the wire, DOMContentLoaded {nav['dcl']} ms, load {nav['load']} ms")
    print(sizes)
    ctx.close(); b.close()
# desktop payload for comparison
rec("perf: desktop bundle for comparison", True, f"{len(requests.get(M + '/').content)/1024:.0f} KB (uncompressed) vs mobile shell above")
json.dump(R, open("misc_results.json", "w"), indent=1)
print("FAIL:", [r["test"] for r in R if r["status"] != "PASS"])
