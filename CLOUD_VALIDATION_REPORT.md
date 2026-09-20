# ApexInvest — cloud validation report

Date of testing: 2026-09-20 · Project commit: see `git log` (tag `cloud-ready-v1`) · Baseline: tag `original-desktop-baseline`

## 0. Read this first — what was and was not done

| | |
|---|---|
| **Deployed to a public URL?** | **No.** Deploying needs *your* GitHub and Render accounts (and optionally your domain). I have no credentials for them and did not invent any. The project is fully prepared; the exact remaining steps are in `docs/DEPLOY_STEP_BY_STEP.md`. **Public URL: none yet** (it will be `https://<your-service>.onrender.com/m/`). |
| **Tested on a physical Android phone?** | **No.** The Android tests below are an **emulation** (Chromium with a Pixel 7 profile, touch, DPR, Android user-agent, CDP network throttling). They cannot prove the Android install banner, the mobile radio network, on-device fonts/keyboard, or the launcher icon. |
| **Tested against real Yahoo / EODHD / TradingView from a cloud IP?** | **No.** The build environment's network refuses those hosts (confirmed: HTTP 403 from its proxy). All engine comparisons therefore use a deterministic offline data feed that replaces *only* the network fetchers, identically on both sides. Whether Yahoo answers requests from Render's IP range is the largest open operational question (section 8). |
| **Docker image built?** | **No** (no Docker daemon here). Render does not use it. |
| **What "cloud" means in the comparison** | The unmodified project run exactly as Render will run it — clean virtualenv built from `requirements.lock`, the real start-command flags, `APEX_ENV=production`, access-key gate on, real HTTP — against the **original** desktop code in the original local configuration. This is a faithful simulation of the software environment, not the Render machine itself. |

## 1. Deployment architecture

```
Phone ─HTTPS─► https://<service>.onrender.com/m/  ─► FastAPI (uvicorn, 1 worker) ─► existing Python engine ─► data provider
                                                       └ same process also serves the desktop app at / and the API at /v1/*
```
Platform: **Render web service** (`render.yaml` Blueprint, Python 3.11.9, Starter US$7/month or Free), Frankfurt region, health check `/v1/health`. No database, no disk. Reasons, costs, limits: `docs/CLOUD_DEPLOYMENT.md`.

Environment configuration (server side only; `.env.example` lists exactly the variables the code reads): `APEX_ENV=production`, `APEX_ACCESS_KEYS` (you set), `EODHD_API_KEY` (optional), `ALLOWED_ORIGINS` / `PUBLIC_API_BASE` (normally empty).

## 2. What changed, what did not

**Untouched (verified with `git diff original-desktop-baseline`, empty output):** every file in `engines/` (indicators, regime, 9 strategies, structure / volume profile, entry optimizer, stop/TP/R:R, confidence, recommendation, expected move, scanner, portfolio, backtest), `service.py`, `domain.py`, `market/` (all data adapters), `ingest/` (CSV processing) and the desktop UI `frontend_app.html`. No `mobile_engine.py` / `mobile_strategy.py` / JS indicator code exists; the phone does no calculation.

**Added / changed (infrastructure only):**

| File | Change |
|---|---|
| `apexinvest/api/production.py` (new) | CORS policy from env, secret redaction, rate limits, size/shape validation, security headers, no-store, docs off, log without query strings, startup/shutdown logging |
| `apexinvest/api/main.py` | the prototype `CORSMiddleware(allow_origins=["*"])` block now calls `production.cors_settings()` (identical result in local mode) and `production.install(app)` is called once |
| `apexinvest/api/mobile.py` | `GET /m/config.js` (runtime API base; no secrets) |
| `mobile/app.js`, `index.html`, `sw.js` | API base prefix (empty = same origin), key check via header instead of URL, `config.js` script, service-worker cache version bump, dropped the localhost condition |
| `requirements.lock`, `render.yaml`, `.env.example`, `Dockerfile`, `.dockerignore`, `.gitignore` | deployment |
| `tests/test_production.py` | 21 new tests (suite: 167 passing on system packages **and** in a clean venv from the lock file) |
| `docs/…`, `cloud_validation/` | audit, deployment guides, validation harness |

## 3. Local original vs cloud — comparison

Environments:

| | Local original | Cloud (simulated) |
|---|---|---|
| Code | `original-desktop-baseline` (pristine) | this project |
| Python / pandas / numpy | 3.11.15 / 3.0.2 / 2.4.4 (system) | 3.11.15 / 3.0.6 / 2.4.6 (venv from `requirements.lock`) |
| Mode | local, no key | `APEX_ENV=production`, access key required, `--workers 1 --proxy-headers --no-access-log …` |
| Data | identical deterministic offline feed | identical |

**A. API-level comparison (real HTTP), 374 test cases, 4,262 field-group comparisons — 0 differences.**

| Part | Cases | What is compared |
|---|---|---|
| TradingView-style CSV upload (28 datasets × 5 objectives + 8 special files incl. newest-first) | 148, each vs the original engine on the ingested file **and** on the raw DataFrame (288 tests) | indicators, strategy signals, regime, structure/POC/VAH/VAL/S-R, entry, stop, TP1, TP2, R:R, confidence, expected move, final signal |
| Live-feed analysis via `/v1/analyses/auto` (12 tickers × 5 objectives) | 60 | the same 12 groups **plus** the complete JSON body (incl. candles) |
| Endpoints (baseline server vs cloud server) | 26 | scanner (12 horizon/risk combos + full universe), portfolio, backtest ×3, quotes, asset search ×2, health, data-health, upload summary, manual analyze, desktop `/` and `/app` |

Floats are compared exactly (no tolerance). `docs/CLOUD_VALIDATION_DETAIL.csv` lists every comparison.

**B. Raw values, bit-for-bit.** 30 datasets (28 synthetic + the COMI and SWDY fixtures), 15 raw indicator outputs each at full precision (SMA20/50, EMA12/26, RSI14, MACD line/signal/hist, true range, ATR14, ADX14, OBV, swing levels, volume-profile POC/VAH/VAL/HVN/LVN, pivots, dollar volume) **and** the complete analysis for all 5 objectives, dumped as JSON with repr-precision floats and compared with `cmp`:

| Environment compared to the local original | Result |
|---|---|
| Cloud lock-file venv (pandas 3.0.6 / numpy 2.4.6) | byte-identical |
| Deliberately **older** stack (pandas 2.2.3 / numpy 1.26.4) | byte-identical |
| Timezone `Africa/Cairo`, `Pacific/Kiritimati` (UTC+14), `America/Los_Angeles` | byte-identical |

**Differences found: 0.** Causes considered and ruled out: data (identical feed), timezone (tested), floating point (bit-identical), dependency versions (three stacks tested), serialization (exact JSON equality), environment/mode (production vs local), and code change (`git diff` on all engine, service, data and ingestion files is empty). `requirements.lock` is still used so a future cloud build cannot drift.

*Not covered:* real provider data (see section 0). If Yahoo/EODHD return different candles than they did to your PC (for example because of an adjusted-price revision), results follow the data — that is a data difference, not an engine difference.

## 4. Mobile / Android tests — EMULATED, not a physical device

`cloud_validation/android_emulation.py` (Pixel 7 profile, production-mode server with access key): **46 checks, 0 failures**

* homepage `/` (desktop app) loads; `/m/` asks for the key; wrong key refused; right key opens the app; the key is stored only in the browser and never appears in a URL; the page calls only its own origin
* ABUK, CCAP, RAYA, MCRO, IEEC: for each, the phone shows signal, entry, stop, TP1, TP2, R:R, confidence, trend/volatility/liquidity **equal to the engine JSON**; the 9-strategy confluence rows match; support, resistance, POC/VAH/VAL, expected move, RSI/ADX are shown; ticker and price shown
* refresh re-requests the analysis from the server (no stale result)
* TradingView CSV upload → backend → engine → same result as the API; newest-first file accepted; a CSV without OHLC and a text file are refused with a clear message; a 20-candle file gives an honest WAIT with no invented levels (also straight to the API)
* browser closed and reopened (persistent profile): still signed in, analysis freshly fetched; service-worker cache contains only the 9 shell files and **no `/v1` response**
* offline: app shell opens; no stale analysis shown — a clear "can't reach the server" message
* manifest (start_url, scope, standalone, theme, 192/512/maskable icons) and icons reachable; Chromium's own installability check (`Page.getInstallabilityErrors`) returns no errors
* portrait 412×915 and landscape 915×412: no horizontal scroll
* slow network (≈3G: 400 kbps, 400 ms RTT): app opens and analysis completes
* no JavaScript errors (CSP violations would appear here)

Screen matrix (`ui_run/ui_matrix.py`, production server with key; screenshots kept for 390×844 only): **220 screens (5 viewports × 22 screens × EN-dark / AR-light), 0 overflow or clipping defects, 0 undersized touch targets.** The only console messages are the 5 intentional "404" responses from the unknown-ticker screen (one per viewport); there are no CSP violations or script errors.
Desktop app smoke test on the production-mode server (`desktop_smoke.py`): key screen, wrong/right key, AUTO analysis of ABUK shows the engine's entry/stop/TP1/TP2/action — 5/5.

**Not done on a real Android device:** the Chrome "Install app" prompt, the launcher icon, real-network behaviour, on-device keyboard/file picker for the CSV. Steps 10–13 of `DEPLOY_STEP_BY_STEP.md` are the checklist for the first real-phone test.

## 5. Performance (measured on the build machine; provider latency NOT included)

| Measure | Result |
|---|---|
| Mobile shell on the wire | 26 KB (6 requests) |
| Time until the app is usable | 0.1 s loopback · 0.62 s at 9 Mbps/170 ms · 2.3 s at 400 kbps/400 ms |
| `GET /v1/health` | 1.8 ms median |
| Full analysis (`/analyses/auto`, engine only) | 29 ms median, 37 ms p95, 14.5 KB JSON |
| CSV upload → result (160 rows / 1,500 rows) | 35 ms / 59 ms median |
| Scanner, 35-symbol watch-list (refresh) | 1.4 s |
| Backtest COMI (2 y walk-forward) / portfolio of 3 | 0.4 s / 0.08 s |
| Server memory (RSS, 1 worker) | 101 MB idle → 111 MB after analyses + full scan + backtest |
| Boot to healthy | ≈1 s · graceful shutdown: in-flight 1.4 s scan completed with HTTP 200 during SIGTERM; a >20 s job is cancelled at the 20 s limit |

Render's Starter has 0.5 CPU, so expect the engine times to be a few times higher; the real analysis time will include the data provider's response time, which could not be measured here. Optimisation was limited to infrastructure (gzip, revalidation, one worker); the engine was not touched.

## 6. Security checks

Black-box probe of the production-mode server (`security_probe.py`): **38/38 pass** — every `/v1` data route returns 401 without a key and `/v1/health` is public; wrong key 401; `/docs`, `/redoc`, `/openapi.json` are 404; path-traversal and source/config URLs (`/m/../frontend_app.html`, `/.env`, `/render.yaml`, `/m/apexinvest/…`, `requirements.*`) are not served; foreign-origin CORS and preflight refused; API responses `no-store`; server banner hidden; CSP + frame protection on `/m/`; HSTS and `nosniff`; no secret, token, long key or localhost/LAN address in any file the phone downloads; invalid ticker 422, unknown ticker clean 404 JSON, missing file 422, binary garbage 422, 16 MB upload 413, oversized query 414 — none with a stack trace.

Unit tests (21): secret redaction (a realistic `requests` error carrying `?api_token=…` never reaches a browser or a log, including inside 200 bodies from scanner/portfolio), CORS allow-list and default-closed, rate limits and `Retry-After`, throttling of key guessing (a caller with a valid key is never locked out), spoof-proof client-IP for limits, heavy-job concurrency cap, upload cap (Content-Length and chunked), access log without query string, config.js validation, no hard-coded hosts, engine output identical local vs production. Real start command with default limits: 130 calls → 120 allowed, 10 refused.

Repository secret scan: no real credentials found (details in `docs/CLOUD_DEPLOYMENT_AUDIT.md` §5). One issue found and fixed: provider error text (with the EODHD token in the URL) could have been returned to the browser.

## 7. Findings worth knowing

* The **desktop** login (compiled bundle, deliberately not edited) still validates the key with `GET /v1/auth/check?key=…`. It is HTTPS-encrypted and this server never logs query strings, but Render's own request logs may. The mobile app uses a header. Use a key you can rotate.
* Rate-limit counters and the scanner cache are per process (hence 1 worker) and reset on restart.

## 8. Known limitations

1. **Yahoo from a cloud IP is unverified** and may be throttled; mitigation is an EODHD key or CSV import (which needs no provider).
2. EODHD: pricing and exchange code for Egypt should be confirmed with one test call before subscribing (`EODHD_EGX_SUFFIX`); free tier (20 calls/day, 1 year) is too small for this app.
3. Free Render plan sleeps after 15 idle minutes (~1 min wake-up).
4. No physical-device test; Dockerfile untested.
5. Holdings/journal/settings live in each phone's browser storage (per device, not shared, lost if browser data is cleared) — same as the desktop app.

## 9. Remaining manual steps (yours)

1. Create a GitHub repository and publish the project (GitHub Desktop) — `DEPLOY_STEP_BY_STEP.md` steps 1–2.
2. Render → New → Blueprint → select the repo (steps 3–8); when asked, enter `APEX_ACCESS_KEYS` (`name:long-random-key`) and optionally `EODHD_API_KEY`.
3. Open `/v1/health`, then `/m/` on the phone, install to the home screen, analyze ABUK / CCAP / RAYA / MCRO / IEEC and upload a TradingView CSV (steps 9–13). If ABUK says "No market data", Yahoo is refusing the server: add the EODHD key or use the CSV import.
4. Optional: custom domain (DNS steps in the guide).
