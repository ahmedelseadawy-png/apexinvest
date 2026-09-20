# ApexInvest — cloud deployment (design and decisions)

Goal: open **https://YOUR-DOMAIN/m/** on an Android phone or iPhone with the PC switched off, and get the **same analysis from the same Python engine**.

```
Phone ──HTTPS──► /m/  (mobile web app, PWA)
                   │  same-origin fetch  (X-Apex-Key header)
                   ▼
        ONE cloud web service  ── uvicorn ── FastAPI  apexinvest.api.main:app
                   │                 ├─ /            desktop app (unchanged)
                   │                 ├─ /m/          mobile app
                   │                 └─ /v1/*        API
                   ▼
        existing Python engine (indicators · regime · 9 strategies · structure · volume profile ·
        entry · stop · TP1/TP2 · R:R · confidence · expected move · BUY/WAIT/AVOID)
                   ▼
        Yahoo Finance (free)  or  EODHD (optional key)  or  your TradingView CSV upload
```

One process serves everything, so there is no second server, no database, no CORS and no URL to keep in sync.

## 1. Platform: Render (Web Service) — why

Requirement: something that runs a Python/FastAPI process continuously, gives HTTPS automatically, deploys from GitHub, and does not need the PC.

| Option | Verdict |
|---|---|
| **Render** (chosen) | Runs Python natively (no Docker knowledge needed), free HTTPS `*.onrender.com`, custom domains with automatic certificates, deploys from a GitHub repo, reads the `render.yaml` in this project (one-click "Blueprint"), health checks, rollbacks. Simplest path for a non-programmer. |
| Railway / Fly.io | Also fine and the included `Dockerfile` works on both (Fly needs a `fly.toml`, Railway needs nothing extra). More moving parts for a first deployment; no advantage for this app. |
| AWS / DigitalOcean droplet | Cheapest at scale but you must manage the server, TLS certificates and updates yourself. Not recommended here. |
| Vercel / Netlify / Cloudflare Pages | **Not suitable**: they host static pages / short serverless functions, not a long-running pandas engine. |

### Cost (verified from Render's pricing / docs pages on 2026-09-20 — re-check before you subscribe)

| Instance | Price | Memory / CPU | Behaviour |
|---|---|---|---|
| **Starter — recommended** | **US$7 / month** | 512 MB / 0.5 CPU | always on, no sleeping |
| Free | US$0 | 512 MB | **sleeps after 15 min without traffic; the next request waits about a minute** while it wakes up; 750 free instance-hours per month; no persistent disk (nothing here needs one) |
| Standard | US$25 / month | 2 GB / 1 CPU | only if you serve many people or run heavy backtests often |

Outbound bandwidth is counted per workspace plan (Hobby workspace, US$0: 5 GB/month). A phone visit downloads about 26 KB of app plus about 15 KB per analysis, so this stays far below it.
Data-provider cost is separate (section 6). **Realistic monthly cost: US$7 (Render Starter) + US$0 (Yahoo) — or + about US$20 if you add the EODHD feed.**

**Free vs Starter:** the free plan works for trying it, but the first open after 15 idle minutes takes ~1 minute (the app just looks like it is loading), and every wake-up empties the in-memory scanner cache. For daily use choose Starter.

## 2. What is deployed

* Repository root contains `render.yaml` (Blueprint). Service `apexinvest`, runtime **Python**, `rootDir: apexinvest_backend`, region Frankfurt (closest to Egypt).
* **Python version:** `PYTHON_VERSION=3.11.9` (set in `render.yaml`). The dependency set was validated on Python 3.11.
* **Build command:** `pip install --upgrade pip && pip install -r requirements.lock` — `requirements.lock` pins every package to the versions that were validated, so the cloud build cannot silently drift.
* **Start command:**
  `uvicorn apexinvest.api.main:app --host 0.0.0.0 --port $PORT --workers ${APEX_WORKERS:-1} --proxy-headers --forwarded-allow-ips '*' --no-access-log --no-server-header --timeout-graceful-shutdown 20`
  (no `--reload`; `$PORT` is provided by Render; graceful shutdown lets in-flight requests finish on redeploy).
* **Health check:** `GET /v1/health` (public, returns `{"status":"ok"}`); Render uses it to decide when a new deploy is ready and to replace an instance that stops answering.
* **Auto-deploy:** every push to the repository's `main` branch redeploys; Render switches traffic to the new version only after it passes the health check.
* **HTTPS:** terminated by Render (automatic certificate, HTTP → HTTPS redirect). The app also sends HSTS in production. The PWA needs HTTPS and gets it on both the free `onrender.com` domain and any custom domain.
* **Alternative:** `apexinvest_backend/Dockerfile` (non-root, health check, same start command) for any container host. It could not be built in the environment used to prepare this project (no Docker daemon), so treat it as untested; Render does not use it.

## 3. Environment variables (server side only)

| Variable | Set on Render | Meaning |
|---|---|---|
| `APEX_ENV` | `production` (in `render.yaml`) | turns on CORS lock-down, rate limits, request validation, security headers, no `/docs` |
| `APEX_ACCESS_KEYS` | **you type it** | `name:key` pairs. **Set this.** Without it anyone who finds the URL can use your analysis service (and your data-provider quota). |
| `EODHD_API_KEY` | optional | paid EGX data feed; blank = Yahoo only |
| `EODHD_EGX_SUFFIX` | optional | default `EGX`. See the note in section 6. |
| `ALLOWED_ORIGINS` | leave blank | only for a front end on a *different* host |
| `PUBLIC_API_BASE` | leave blank | only if `/m/` must call an API on a *different* host |
| `APEX_WORKERS` | leave unset (=1) | uvicorn processes |
| `LOG_LEVEL`, `APEX_RL_*`, `APEX_HEAVY_CONCURRENCY`, `APEX_MAX_*`, `APEX_TRUST_PROXY_HOPS` | optional | see `.env.example` |

No secret is in the repository, in the image, or in any JavaScript file the phone downloads. `.env` files are git-ignored.

## 4. Where the domain / API URL is configured

* **Default (recommended): nowhere.** The mobile app calls the same address it was opened from, so `https://apexinvest.onrender.com/m/` and `https://apex.yourdomain.com/m/` both just work. No domain is written into any file.
* **Different host for the API** (rare): set `PUBLIC_API_BASE=https://api.example.com` in the Render dashboard (must be `https://`, no path) **and** put the app's own address in `ALLOWED_ORIGINS=https://app.example.com`. The server publishes it to the phone through `/m/config.js`; you never edit a JavaScript file.
* **Custom domain:** Render → your service → Settings → Custom Domains (see `DEPLOY_STEP_BY_STEP.md`, "Your own domain").

## 5. Scaling, cold start, storage

* **Concurrency.** One worker handles several people fine: the engine work is short (about 30 ms of engine time per stock on the validation machine, plus the market-data fetch) and FastAPI runs each request in a thread pool. Heavy jobs (scanner, portfolio, backtests) are limited to 2 at a time and 6 per minute per person so they cannot exhaust a 512 MB instance (measured: about 110 MB resident memory after running analyses, a full scan and a backtest on one worker); extra requests get a friendly "busy, retry" reply.
* **One worker on purpose.** Two workers would double memory and would give every worker its own scanner cache and its own rate-limit counters. Raise `APEX_WORKERS` only together with a bigger instance.
* **Cold start.** Starter: none. Free: ~1 minute after 15 idle minutes. The app itself boots in about a second.
* **Persistent storage: none needed.** The server keeps no user data. Holdings, journal and settings live in the phone's browser storage (per device). The scanner (≈1 h) and universe-backtest (≈6 h) caches are in memory and are rebuilt after a restart — a cache miss just makes the first scan slower.
* **Updating:** push to GitHub → Render redeploys. Roll back from the service's *Events* tab.

## 6. Market-data limits you must know about

1. **Yahoo Finance (default, no key).** Free and it is the same source the desktop app used from your PC. Yahoo does not publish a guarantee, and requests from cloud data-centre addresses are sometimes throttled or refused (HTTP 429/403). This **could not be tested from the environment used to build this project** (its network blocks Yahoo). If it happens the app says *"No market data for this ticker right now — nothing is invented"* and the TradingView-CSV import keeps working. The fix is the EODHD key below.
2. **EODHD (optional key).** Their public pricing (checked 2026-09-20): a free plan of 20 calls/day limited to the last year (not enough for this app — one scan needs dozens of calls); **EOD Historical Data – All World US$19.99/month, 100,000 calls/day**. Before subscribing, confirm two things with one test call: that your plan includes the Egyptian exchange, and the exchange code EODHD uses for it. The code defaults to `EGX` (so `COMI.EGX`); their exchange page lists Egypt under a different label, so if COMI returns nothing, set `EODHD_EGX_SUFFIX` to the code they show — no code change needed. Get the key at eodhd.com → Dashboard → API token.
3. **TradingView CSV import** uses no external service: the file you upload is the data (daily candles). It always works.
4. **TradingView quote** (price only, used as a cross-check) is unofficial and may be blocked from a cloud address; the app then simply omits it.

## 7. Security summary (details and tests in `CLOUD_VALIDATION_REPORT.md`)

Secrets only in server environment variables · CORS closed by default in production · access-key gate on every `/v1/*` route except health · failed-key throttling · per-IP rate limits · heavy-job concurrency cap · 15 MB upload cap · symbol and query validation · no stack traces or provider URLs/tokens in responses or logs · `Cache-Control: no-store` on all API responses · CSP, HSTS, `nosniff` · public API docs removed · service worker never caches API responses.

## 8. Operating notes

* **Logs:** Render → service → Logs. One line per request (method, path, status, milliseconds) — query strings are never logged.
* **Key rotation:** edit `APEX_ACCESS_KEYS` in the dashboard (Environment) → Save; the service restarts. Everyone with the old key is signed out on their next request.
* **Adding another person:** `ahmed:KEY1,sherif:KEY2`.
* **Local use is unchanged:** the Windows `.bat` launchers still run the original app (without `APEX_ENV`, nothing new is enforced).
