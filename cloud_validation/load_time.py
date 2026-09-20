import json, time, sys, statistics as st
from playwright.sync_api import sync_playwright
B = "http://127.0.0.1:8010"; K = "Cloud-Test-Key-0123456789"
out = {}
with sync_playwright() as p:
    dev = {k: v for k, v in p.devices["Pixel 7"].items() if k != "default_browser_type"}
    b = p.chromium.launch()
    for label, net in (("unthrottled (sandbox loopback)", None), ("4G-class 9 Mbps / 170 ms RTT", (170, 9 * 1024 * 1024 // 8)), ("slow 3G-class 400 kbps / 400 ms RTT", (400, 400 * 1024 // 8))):
        runs = []
        for i in range(3):
            c = b.new_context(**dev); pg = c.new_page()
            if net:
                cdp = c.new_cdp_session(pg); cdp.send("Network.enable"); cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": net[0], "downloadThroughput": net[1], "uploadThroughput": net[1]})
            sizes = []; pg.on("response", lambda r: sizes.append(int(r.headers.get("content-length", 0))))
            t = time.perf_counter(); pg.goto(B + "/m/", wait_until="load"); pg.wait_for_selector(".login, .hero", timeout=90000); ready = (time.perf_counter() - t) * 1000
            nav = pg.evaluate("(()=>{const n=performance.getEntriesByType('navigation')[0];return {dcl:n.domContentLoadedEventEnd,load:n.loadEventEnd}})()")
            runs.append({"interactive_ms": round(ready), "dcl_ms": round(nav["dcl"]), "load_ms": round(nav["load"]), "kb": round(sum(sizes) / 1024, 1), "requests": len(sizes)}); c.close()
        out[label] = {"median_interactive_ms": int(st.median(r["interactive_ms"] for r in runs)), "kb_on_wire": runs[0]["kb"], "requests": runs[0]["requests"], "runs": runs}
    b.close()
json.dump(out, open("load_time_results.json", "w"), indent=1); print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "runs"} for k, v in out.items()}, indent=1))
