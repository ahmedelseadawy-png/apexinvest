"""Mobile UI test matrix: 5 viewports x all screens. Checks horizontal overflow, clipped/overflowing
elements, small touch targets, JS errors, and takes screenshots."""
import sys, json, os
from playwright.sync_api import sync_playwright
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001"
VPS = [("360x800", 360, 800, True), ("390x844", 390, 844, True), ("412x915", 412, 915, True), ("768x1024", 768, 1024, True), ("1366x768", 1366, 768, False)]
CHK = """()=>{
 const W=document.documentElement.clientWidth, out={sw:document.documentElement.scrollWidth,W,clip:[],small:[]};
 const vis=e=>{const r=e.getBoundingClientRect();const cs=getComputedStyle(e);return r.width>0&&r.height>0&&cs.visibility!=='hidden'&&cs.display!=='none'};
 for(const e of document.querySelectorAll('body *')){
   if(!vis(e)) continue; if(e.closest('.seg,.tbl-wrap,canvas,svg')&&!e.classList.contains('seg')&&!e.classList.contains('tbl-wrap')) { if(e.closest('.seg')||e.closest('.tbl-wrap')) continue; }
   const r=e.getBoundingClientRect(); const own=e.closest('.seg,.tbl-wrap'); if(own) continue;
   if(r.right>W+1||r.left<-1) out.clip.push(e.tagName+'.'+String(e.className).slice(0,30)+' L'+Math.round(r.left)+' R'+Math.round(r.right));
 }
 for(const e of document.querySelectorAll('button,a,input:not([type=file]),select,label.upload')){
   if(!vis(e)) continue; const r=e.getBoundingClientRect(); if(r.height<40||r.width<40) out.small.push((e.textContent||e.getAttribute('aria-label')||e.tagName).trim().slice(0,20)+' '+Math.round(r.width)+'x'+Math.round(r.height));
 }
 out.clip=out.clip.slice(0,6); out.small=out.small.slice(0,6); return out}"""
TAG = os.environ.get("MODE", "en-dark"); LANGV, THEMEV = ("ar", "light") if TAG == "ar-light" else ("en", "dark")
results = []; errs = []
def check(pg, name, vp):
    pg.wait_for_timeout(250)
    r = pg.evaluate(CHK); r["overflow_x"] = r["sw"] > r["W"] + 1
    ok = (not r["overflow_x"]) and not r["clip"]
    results.append({"vp": vp, "screen": name, "ok": ok, **r})
    pg.screenshot(path=f"shots/{TAG}_{vp}_{name}.png", full_page=False)
    print(f"{vp:9} {name:22} {'OK ' if ok else 'BAD'} sw={r['sw']}/{r['W']} clip={r['clip']} small={r['small']}", flush=True)

with sync_playwright() as p:
    b = p.chromium.launch()
    for vp, w, hh, mob in VPS:
        ctx = b.new_context(viewport={"width": w, "height": hh}, device_scale_factor=2 if mob else 1, is_mobile=mob, has_touch=mob)
        ctx.add_init_script(f"localStorage.setItem('apex_m_lang','{LANGV}');localStorage.setItem('apex_theme','{THEMEV}');" + (f"localStorage.setItem('apex_access_key','{os.environ['APEX_KEY']}')" if os.environ.get("APEX_KEY") else ""))
        pg = ctx.new_page()
        pg.on("console", lambda m, vp=vp: errs.append((vp, m.type, m.text)) if m.type == "error" else None)
        pg.on("pageerror", lambda e, vp=vp: errs.append((vp, "pageerror", str(e))))
        pg.goto(BASE + "/m/"); pg.wait_for_selector(".hero"); check(pg, "01_analyze", vp)
        pg.fill("input[type=search]", "ra"); pg.wait_for_selector(".item .sym"); check(pg, "02_search", vp)
        pg.goto(BASE + "/m/#/dash/ABUK/swing"); pg.wait_for_selector(".signal .big", timeout=60000); check(pg, "03_dash_buy", vp)
        for tab in ["Strategies", "Structure", "Entry", "Risk", "Indicators", "Chart"]:
            pg.locator("[role=tab]").nth(["Strategies", "Structure", "Entry", "Risk", "Indicators", "Chart"].index(tab) + 1).click(); check(pg, "04_tab_" + tab.lower(), vp)
        pg.goto(BASE + "/m/#/dash/COMI/swing"); pg.wait_for_selector(".signal .big", timeout=60000); check(pg, "05_dash_wait", vp)
        pg.goto(BASE + "/m/#/dash/COMI/long_term"); pg.wait_for_selector(".signal .big", timeout=60000); check(pg, "06_dash_long", vp)
        pg.goto(BASE + "/m/#/dash/NOPE/swing"); pg.wait_for_selector(".notice.err", timeout=30000); check(pg, "07_dash_nodata", vp)
        pg.goto(BASE + "/m/#/scanner"); pg.locator(".btn.primary").first.click(); pg.wait_for_selector("[role=tab]", timeout=120000); check(pg, "08_scanner", vp)
        pg.goto(BASE + "/m/#/watchlist"); pg.locator(".btn.primary").first.click(); pg.wait_for_selector("[role=tab]", timeout=180000); check(pg, "09_watchlist", vp)
        pg.goto(BASE + "/m/#/portfolio"); pg.wait_for_selector(".hero")
        for s_, q_, a_ in [("COMI", "100", "120"), ("ABUK", "50", "70")]:
            ins = pg.locator("main input"); ins.nth(0).fill(s_); ins.nth(1).fill(q_); ins.nth(2).fill(a_); pg.locator("main .btn:not(.primary)").first.click()
        pg.locator("main .btn.primary").click(); pg.wait_for_selector(".kv", timeout=90000); check(pg, "10_portfolio", vp)
        pg.goto(BASE + "/m/#/more"); pg.wait_for_selector(".hero"); check(pg, "11_more", vp)
        pg.goto(BASE + "/m/#/settings"); pg.wait_for_selector(".seg"); check(pg, "12_settings", vp)
        pg.goto(BASE + "/m/#/import"); pg.wait_for_selector(".upload")
        pg.set_input_files("input[type=file]", "data/EGX_COMI, 1D_tv.csv"); pg.wait_for_selector(".state.valid", timeout=30000); check(pg, "13_import_valid", vp)
        pg.click("#anBtn"); pg.wait_for_selector(".signal .big", timeout=60000); check(pg, "14_import_dash", vp)
        pg.goto(BASE + "/m/#/import"); pg.set_input_files("input[type=file]", "data/bad_no_ohlc.csv"); pg.wait_for_selector(".state.error", timeout=30000); check(pg, "15_import_error", vp)
        pg.goto(BASE + "/m/#/journal"); pg.wait_for_selector(".hero, .card"); check(pg, "16_journal", vp)
        pg.goto(BASE + "/m/#/validation"); pg.locator("main .btn.primary").click(); pg.wait_for_selector("table", timeout=240000); check(pg, "17_validation", vp)
        ctx.close()
    b.close()
bad = [r for r in results if not r["ok"]]
small = [r for r in results if r["small"]]
json.dump(results, open(f"ui_matrix_results_{TAG}.json", "w"), indent=1)
print("\nSCREENS:", len(results), "BAD:", len(bad), "with small targets:", len(small), "JS errors:", errs[:5])
