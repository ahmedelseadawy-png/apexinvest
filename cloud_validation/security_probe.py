"""Black-box security probe of the production-mode server (real HTTP)."""
import sys, re, json, requests
B = sys.argv[1]; KEY = sys.argv[2]; H = {"X-Apex-Key": KEY}; R = []
def rec(n, ok, d=""):
    R.append({"test": n, "status": "PASS" if ok else "FAIL", "detail": str(d)[:300]}); print(("PASS " if ok else "FAIL ") + n, ("[" + str(d)[:150] + "]") if d else "", flush=True)
g = requests.get
for p in ("/v1/analyses/auto/ABUK", "/v1/scan", "/v1/quotes?symbols=COMI", "/v1/assets/search?q=a", "/v1/data/health", "/v1/fundamentals/COMI", "/v1/backtest/COMI", "/v1/portfolio"):
    r = (requests.post if p == "/v1/portfolio" else g)(B + p, **({"json": {"holdings": []}} if p == "/v1/portfolio" else {}))
    rec(f"no key → 401: {p}", r.status_code == 401)
rec("/v1/health is public", g(B + "/v1/health").status_code == 200)
rec("wrong key → 401", g(B + "/v1/quotes?symbols=COMI", headers={"X-Apex-Key": "nope"}).status_code == 401)
rec("right key → 200", g(B + "/v1/quotes?symbols=COMI", headers=H).status_code == 200)
for p in ("/docs", "/redoc", "/openapi.json"): rec(f"API docs hidden: {p}", g(B + p).status_code == 404)
for p in ("/m/../frontend_app.html", "/m/%2e%2e/frontend_app.html", "/m/..%2fapexinvest/service.py", "/m/apexinvest/api/main.py", "/m/requirements.txt", "/m/../requirements.lock", "/.env", "/render.yaml", "/apexinvest/service.py", "/m/.env"):
    rc = g(B + p).status_code; rec(f"source/config not served: {p}", rc in (400, 404) or (rc == 200 and "<html" not in g(B + p).text.lower()[:5000] and False), f"HTTP {rc}")
r = g(B + "/v1/health", headers={"Origin": "https://evil.example"}); rec("CORS: foreign origin gets no Access-Control-Allow-Origin", "access-control-allow-origin" not in r.headers)
r = requests.options(B + "/v1/analyses/csv", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"}); rec("CORS preflight from foreign origin refused", "access-control-allow-origin" not in r.headers, f"HTTP {r.status_code}")
r = g(B + "/v1/analyses/auto/ABUK", headers=H)
rec("API responses are no-store", r.headers.get("cache-control") == "no-store")
rec("server banner hidden", "server" not in {k.lower() for k in r.headers})
m = g(B + "/m/"); rec("CSP + frame protection on /m/", "content-security-policy" in m.headers and m.headers.get("x-frame-options") == "DENY")
rec("HSTS + nosniff", "strict-transport-security" in m.headers and m.headers.get("x-content-type-options") == "nosniff")
bad = []
for f in ("index.html", "app.js", "app.css", "i18n.js", "config.js", "sw.js", "manifest.webmanifest"):
    t = g(B + "/m/" + f).text
    if re.search(r"(EODHD|api[_-]?key|api_token|Bearer |password\s*[:=]|[A-Za-z0-9+/=_]{40,})", t, re.I) or "APEX_ACCESS_KEYS" in t: bad.append(f)
rec("no secrets / tokens / long keys in any file the phone downloads", not bad, bad)
rec("no localhost / LAN address in any mobile file", not any(re.search(r"(127\.0\.0\.1|192\.168\.|10\.\d+\.\d+\.\d+)", g(B + "/m/" + f).text) for f in ("index.html", "app.js", "sw.js", "config.js", "manifest.webmanifest")))
r = g(B + "/v1/analyses/auto/bad%20sym", headers=H); rec("invalid ticker → 422, no stack trace", r.status_code == 422 and "Traceback" not in r.text, r.text[:80])
r = g(B + "/v1/analyses/auto/NOPE", headers=H); rec("unknown ticker → clean 404 JSON", r.status_code == 404 and r.headers["content-type"].startswith("application/json"), r.text[:100])
r = requests.post(B + "/v1/analyses/csv", headers=H, data={"symbol": "X", "objective": "swing"}); rec("missing file → 422 JSON (no trace)", r.status_code == 422 and "Traceback" not in r.text)
r = requests.post(B + "/v1/analyses/csv", headers=H, files={"file": ("big.csv", b"a" * (16 * 1024 * 1024), "text/csv")}, data={"symbol": "X"}); rec("16 MB upload refused (413)", r.status_code == 413, r.text[:80])
r = requests.post(B + "/v1/analyses/csv", headers=H, files={"file": ("x.csv", b"\x00\x01\x02garbage\xff\xfe", "text/csv")}, data={"symbol": "X"}); rec("binary garbage upload → 422, not a crash", r.status_code == 422 and "Traceback" not in r.text, r.text[:100])
r = g(B + "/v1/scan?symbols=" + "A," * 3000, headers=H); rec("oversized query → 414", r.status_code == 414)
json.dump(R, open("security_results.json", "w"), indent=1); print("TOTAL", len(R), "FAIL", sum(x["status"] != "PASS" for x in R))
