"""UI-level parity: what the MOBILE dashboard displays vs (a) the engine JSON and (b) what the DESKTOP UI displays."""
import re, json, sys, requests
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8001"; CUR = "http://127.0.0.1:8002"   # 8002 = pristine baseline server
SYMS = ["ABUK", "CCAP", "RAYA", "MCRO", "IEEC", "UEGC", "COMI", "SWDY"]; OBJS = ["swing", "long_term"]
OBJ_BTN = {"swing": "Swing trade", "long_term": "Grow long-term"}
def f2(v):
    if v is None: return "—"
    d = 4 if abs(v) < 1 else 2
    s = f"{v:,.{d}f}"
    if d == 4 and s.endswith("00"): s = s[:-2]
    return s
def nums(text): return set(x.replace(",", "") for x in re.findall(r"\d[\d,]*\.\d+", text))
rows = []; bad = 0
with sync_playwright() as p:
    b = p.chromium.launch()
    mctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True); mp = mctx.new_page()
    dctx = b.new_context(viewport={"width": 1366, "height": 768}); dp = dctx.new_page()
    for sym in SYMS:
        for o in OBJS:
            j = requests.get(f"{CUR}/v1/analyses/auto/{sym}?objective={o}").json(); pl = j["plan"]
            # ---- mobile
            mp.goto(f"{BASE}/m/#/dash/{sym}/{o}"); mp.wait_for_selector(".signal .big", timeout=60000)
            m = mp.evaluate("""()=>{const o={};o.action=document.querySelector('.signal .big').textContent;
              for(const c of document.querySelectorAll('.card')){const h=c.querySelector(':scope>h3');if(!h)continue;const t=h.textContent.trim();
                if(t==='TRADE PLAN'||t==='MARKET REGIME'){for(const d of c.querySelectorAll('.kv>div')){const l=d.querySelector('.lbl'),v=d.querySelector('.v');if(l&&v)o[l.textContent.trim().toUpperCase()]=v.textContent.trim()}}
                if(t==='CONFLUENCE'){o.conf=[...c.querySelectorAll('.crow')].map(r=>[r.querySelector('.nm').firstChild.textContent,(r.querySelector('.pill')||{}).textContent])}}
              return o}""")
            z = pl.get("optimal_zone"); tp1 = pl.get("tp1") if pl.get("tp1") is not None else pl.get("target")
            exp = {"action": pl["action"], "ENTRY": f2(pl["entry"]) if pl.get("entry") is not None else (f"{f2(z[0])}–{f2(z[1])}" if z else "—"),
                   "STOP": f2(pl.get("stop")), "TP1": f2(tp1), "TP2": f2(pl.get("tp2")), "R:R": f"{pl['rr']:.2f} : 1" if pl.get("rr") is not None else "—",
                   "CONFIDENCE": f"{pl['confidence']['score']}/5", "TREND": (j["regime"]["trend"] or "").capitalize(), "VOLATILITY": j["regime"]["volatility"].capitalize(), "LIQUIDITY": j["regime"]["liquidity"].capitalize()}
            ok_m = all(m.get(k) == v for k, v in exp.items())
            miss = {k: (m.get(k), v) for k, v in exp.items() if m.get(k) != v}
            # confluence: every engine signal shown with matching bias
            sigmap = {s["strategy_id"]: s["bias"] for s in j["signals"]}
            lab = {"price_action": "Price Action", "trend": "Trend", "momentum": "Momentum", "macd": "MACD", "rsi": "RSI", "poc": "POC", "breakout": "Breakout", "accumulation": "Accumulation", "fundamental": "Fundamental"}
            conf_ok = all(any(r[0] == lab[k] and r[1] == bias.capitalize() for r in m["conf"]) for k, bias in sigmap.items())
            rows.append({"test": f"MOBILE UI vs engine JSON · {sym}/{o}", "current": json.dumps(exp, ensure_ascii=False), "mobile": json.dumps({k: m.get(k) for k in exp}, ensure_ascii=False), "diff": "0" if ok_m and conf_ok else f"{miss} conf_ok={conf_ok}", "status": "PASS" if ok_m and conf_ok else "FAIL"})
            # ---- desktop UI
            dp.goto(BASE + "/"); dp.wait_for_timeout(1200)
            dp.fill("input", sym); dp.wait_for_timeout(500)
            dp.locator(f"button:has-text('{sym}')").first.click(); dp.wait_for_timeout(400)
            dp.locator(f"button:has-text('{OBJ_BTN[o]}')").first.click(); dp.wait_for_timeout(400)
            dp.locator("button:has-text('AUTO')").first.click(); dp.wait_for_selector("text=DATA SOURCE", timeout=60000); dp.wait_for_timeout(1200)
            dtext = dp.inner_text("body"); dn = nums(dtext)
            checks = {}
            for k, v in (("stop", pl.get("stop")), ("tp1", tp1), ("tp2", pl.get("tp2")), ("entry", pl.get("entry")), ("poc", pl["entry_levels"].get("poc")), ("vah", pl["entry_levels"].get("vah")), ("val", pl["entry_levels"].get("val"))):
                if v is not None: checks[k] = (f"{v:.2f}" in dn) or (f"{v:.4f}".rstrip("0") in dn)
            d_act = re.search(r"^(BUY|WAIT|AVOID)$", dtext, re.M); checks["action"] = bool(d_act) and d_act.group(1) == pl["action"]
            if pl["action"] == "BUY": checks["confidence"] = f"Confidence {pl['confidence']['score']}/5" in dtext
            good = all(checks.values())
            rows.append({"test": f"DESKTOP UI vs MOBILE UI · {sym}/{o}", "current": f"desktop shows: action={d_act.group(1) if d_act else None}; numbers found " + ",".join(k for k, v in checks.items() if v), "mobile": f"mobile shows: {m['action']} entry={m.get('ENTRY')} stop={m.get('STOP')} tp1={m.get('TP1')} tp2={m.get('TP2')} rr={m.get('R:R')}", "diff": "0" if good else str({k: v for k, v in checks.items() if not v}), "status": "PASS" if good else "FAIL"})
            print(rows[-2]["status"], rows[-1]["status"], sym, o, pl["action"], flush=True)
    # ---- CSV import through the UI vs engine JSON
    mp.goto(BASE + "/m/#/import")
    for fn, o in (("data/EGX_COMI, 1D_tv.csv", "swing"), ("data/EGX_RAYA, 1D.csv", "swing"), ("data/EGX_COMI_newest_first.csv", "swing")):
        mp.goto(BASE + "/m/#/import"); mp.reload(); mp.wait_for_selector(".upload")
        mp.set_input_files("input[type=file]", fn); mp.wait_for_selector(".state.valid", timeout=30000)
        st_txt = mp.inner_text(".state"); mp.click("#anBtn"); mp.wait_for_selector(".signal .big", timeout=60000)
        act = mp.inner_text(".signal .big"); tick = mp.inner_text(".head .tk")
        with open(fn, "rb") as fh: jr = requests.post(BASE + "/v1/analyses/csv", files={"file": (fn.split('/')[-1], fh, "text/csv")}, data={"symbol": tick, "objective": o}).json()
        stp = mp.evaluate("()=>[...document.querySelectorAll('.kv>div')].map(d=>d.textContent)")
        good = act == jr["plan"]["action"] and f2(jr["plan"].get("stop")) in " ".join(stp) and "DATA VALID" in st_txt
        rows.append({"test": f"CSV import via UI · {fn.split('/')[-1]}", "current": f"API action={jr['plan']['action']} stop={f2(jr['plan'].get('stop'))} rows={jr['csv_import']['rows']} order={jr['csv_import']['order']}", "mobile": f"UI '{st_txt.splitlines()[0]}' → {act} ({tick})", "diff": "0" if good else "MISMATCH", "status": "PASS" if good else "FAIL"})
        print(rows[-1]["status"], fn, flush=True)
    b.close()
json.dump(rows, open("ui_parity_rows.json", "w"), indent=1)
print("UI parity rows:", len(rows), "FAIL:", sum(r["status"] != "PASS" for r in rows))
for r in rows:
    if r["status"] != "PASS": print(r["test"], r["diff"][:300])
