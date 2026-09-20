"""Desktop app (/) regression against the production-mode cloud server: login gate, AUTO analysis, values vs API."""
import sys, json, re, requests
from playwright.sync_api import sync_playwright
B = sys.argv[1]; KEY = sys.argv[2]; H = {"X-Apex-Key": KEY}; R = []
def rec(n, ok, d=""):
    R.append({"test": n, "status": "PASS" if ok else "FAIL", "detail": str(d)[:300]}); print(("PASS " if ok else "FAIL ") + n, d if not ok else "", flush=True)
with sync_playwright() as p:
    b = p.chromium.launch(); ctx = b.new_context(viewport={"width": 1366, "height": 768}); pg = ctx.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(B + "/"); pg.wait_for_timeout(1500)
    rec("desktop app shows the key screen when the server requires a key", pg.locator("input[type=password], input[placeholder*='key' i]").count() > 0 or "key" in pg.inner_text("body").lower(), pg.inner_text("body")[:80].replace("\n", " "))
    inp = pg.locator("input[type=password]").first if pg.locator("input[type=password]").count() else pg.locator("input").first
    inp.fill("wrong-key"); inp.press("Enter"); pg.wait_for_timeout(1200)
    rec("wrong key is refused", pg.locator("input[type=password]").count() > 0 or "invalid" in pg.inner_text("body").lower() or "key" in pg.inner_text("body").lower())
    inp = pg.locator("input[type=password]").first if pg.locator("input[type=password]").count() else pg.locator("input").first
    inp.fill(KEY); inp.press("Enter"); pg.wait_for_timeout(2500)
    rec("right key opens the desktop app", pg.locator("input[type=password]").count() == 0, pg.inner_text("body")[:80].replace("\n", " "))
    pg.fill("input", "ABUK"); pg.wait_for_timeout(500); pg.locator("button:has-text('ABUK')").first.click(); pg.wait_for_timeout(400)
    pg.locator("button:has-text('Swing trade')").first.click(); pg.wait_for_timeout(400)
    pg.locator("button:has-text('AUTO')").first.click(); pg.wait_for_selector("text=DATA SOURCE", timeout=60000); pg.wait_for_timeout(1000)
    txt = pg.inner_text("body"); pl = requests.get(B + "/v1/analyses/auto/ABUK?objective=swing", headers=H).json()["plan"]
    nums = set(x.replace(",", "") for x in re.findall(r"\d[\d,]*\.\d+", txt))
    ok = all((f"{pl[k]:.2f}" in nums) for k in ("entry", "stop", "tp1", "tp2")) and re.search(r"^(BUY|WAIT|AVOID)$", txt, re.M).group(1) == pl["action"]
    rec("desktop AUTO analysis ABUK shows the engine's entry/stop/TP1/TP2/action", ok, f"{pl['action']} {pl['entry']} {pl['stop']} {pl['tp1']} {pl['tp2']}")
    rec("no JavaScript errors on the desktop page", not errs, errs[:2])
    b.close()
json.dump(R, open("desktop_results.json", "w"), indent=1); print("TOTAL", len(R), "FAIL", sum(r["status"] != "PASS" for r in R))
