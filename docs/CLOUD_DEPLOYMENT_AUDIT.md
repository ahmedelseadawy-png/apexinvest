# ApexInvest — cloud deployment audit

Audited from the project's **actual source code** (commit `1466a24`, tag `mobile-web-v1`, on top of the untouched
`original-desktop-baseline`), before any deployment change was made. Nothing here is assumed from the task description:
where the source disagreed with an assumption, the source won (see "Corrections" at the end).

## 1. What exists

| Component | Where (real path) | Notes |
|---|---|---|
| FastAPI app | `apexinvest_backend/apexinvest/api/main.py` → **`apexinvest.api.main:app`** | Every route. Run from the `apexinvest_backend/` folder. |
| Orchestration | `apexinvest/service.py` (`analyze`, `analyze_symbol`, `quotes`) | `analyze_symbol(symbol, objective, fetcher=None)` — the `fetcher` hook is what the CSV route uses. |
| Indicators | `engines/indicators.py` | sma, ema, rsi, macd, true range / ATR, ADX, OBV, swing levels, volume profile (POC / VAH / VAL / HVN / LVN), pivots, level clustering |
| Market regime | `engines/regime.py` | trend / volatility / liquidity |
| 9 strategies | `engines/strategies.py` | price action, trend, momentum, MACD, RSI, POC, breakout, accumulation, fundamental |
| Structure / volume profile | `engines/structure.py`, `indicators.volume_profile` | supports, resistances, phase |
| Entry optimizer | `engines/entry.py` (`optimize_entry`) | |
| Stop, TP1, TP2, R:R, confidence | `engines/risk.py` (`build_plan`) | |
| Final BUY / WAIT / AVOID | `engines/recommendation.py` | |
| Expected move | `engines/expected_move.py` | |
| Scanner / portfolio / backtest | `engines/scanner.py`, `portfolio.py`, `backtest.py` | in-memory caches (scan ~1 h, universe backtest ~6 h) |
| CSV / Excel / PDF ingestion | `ingest/files.py` | OHLCV column aliases + validation |
| Market data | `market/feed.py` (EODHD first if a key is set, else Yahoo), `eodhd_egx.py`, `yahoo_egx.py`, `tradingview_egx.py` (price quote only), `fundamentals.py` (Yahoo), `datalayer.py` (health) | `DataUnavailable` → HTTP 404 (honest "no data") |
| Desktop UI | `frontend_app.html` (compiled React bundle) at `/` and `/app` | same-origin fetch |
| Mobile UI | `mobile/` served at **`/m/`** by `api/mobile.py` | vanilla JS PWA; `POST /v1/analyses/csv` |
| Access keys | `main.py` `AccessKeyMiddleware`, env `APEX_ACCESS_KEYS` | opt-in; header `X-Apex-Key` |
| Existing docs | `docs/ARCHITECTURE_MAP.md`, `MOBILE_README.md`, `MOBILE_TEST_RESULTS.md`, `VALIDATION_REPORT.md` | read; consistent with the source |

There is **no database** and none is needed: the engine is stateless, the only server state is two in-memory caches, and
holdings / journal / settings live in each phone's browser storage.

## 2. Environment variables actually read by the code

Found by searching the whole tree for `os.environ` / `getenv`:

| Variable | File | Purpose |
|---|---|---|
| `APEX_ACCESS_KEYS` | `api/main.py` | per-person keys, `name:key,…`; off when unset |
| `EODHD_API_KEY` (alias `APEX_EODHD_KEY`) | `market/eodhd_egx.py` | optional paid data feed |
| `EODHD_EGX_SUFFIX` | `market/eodhd_egx.py` | default `EGX` |
| *(added for cloud, `api/production.py`)* `APEX_ENV`, `ALLOWED_ORIGINS`, `PUBLIC_API_BASE`, `LOG_LEVEL`, `APEX_RL_HEAVY/ANALYSIS/GENERAL/AUTH`, `APEX_HEAVY_CONCURRENCY`, `APEX_MAX_UPLOAD_MB`, `APEX_MAX_BODY_MB`, `APEX_TRUST_PROXY_HOPS` | `api/production.py` | hosting hardening; all optional |
| `PORT`, `APEX_WORKERS` | start command only | supplied by the host / defaults to 1 |

`.env.example` lists exactly these and nothing else.

## 3. Endpoints, protection and cost

| Route | Auth gate (when `APEX_ACCESS_KEYS` set) | Cost | Production rate bucket |
|---|---|---|---|
| `GET /`, `/app`, `/m/*` (static) | open (they contain no data or secrets) | cheap | — |
| `GET /v1/health` | open (host health check) | trivial | exempt |
| `GET /v1/auth/status`, `/v1/auth/check` | open by design | trivial | 401s throttled |
| `GET /v1/analyses/auto/{symbol}` | **key** | one provider fetch + engine | analysis (40/min/IP) |
| `POST /v1/analyses/analyze`, `/requirements` | **key** | engine on supplied candles | analysis |
| `POST /v1/analyses/csv` *(mobile, new)*, `POST /v1/uploads` | **key** | parse + engine | analysis, 15 MB cap |
| `GET /v1/fundamentals/{symbol}`, `/v1/quotes`, `/v1/assets/search`, `/v1/data/health` | **key** | light / one fetch | analysis / general |
| `GET /v1/scan` | **key** | **heavy** (whole universe, 8 threads) | heavy (6/min) + max 2 concurrent |
| `POST /v1/portfolio` | **key** | **heavy** | heavy |
| `GET /v1/backtest/{symbol}`, `/v1/backtest/universe` | **key** | **heavy** (minutes) | heavy |
| `/docs`, `/redoc`, `/openapi.json` | open in the original | reveals the API map | **removed in production** |

## 4. Findings and what was done about each

| # | Finding (from the source) | Severity | Action |
|---|---|---|---|
| 1 | `CORSMiddleware(allow_origins=["*"])` — a prototype setting (the code comment says to tighten it) | high for internet use | `ALLOWED_ORIGINS`; in production the default is **no cross-origin access** (the server hosts both UIs, so same-origin needs none). `*` is honoured only if literally configured, and logged as a warning. |
| 2 | `feed.py` builds `f"EODHD error: {e}"` and joins it into the 404 detail; `requests` puts the full URL — **including `?api_token=<key>`** — in its exception text. `main.py` also returns `f"market data feed error: {e}"` (502). Scanner and portfolio copy `str(e)` into **200** bodies. A server-side secret could therefore reach a browser. | **high** | Redaction at three layers without touching the engine: (a) HTTP-error handler sanitises `detail`; (b) production guard strips configured secret values and `api_token=` patterns from every JSON body; (c) log filter. Unit-tested with a real-shaped `requests` message. |
| 3 | API docs / OpenAPI public | low | removed in production |
| 4 | Access-key check for the **desktop** login is `GET /v1/auth/check?key=…` (minified bundle); a key in a URL can land in host request logs | low–medium | The desktop bundle is not modified. The server never logs query strings (own access log; uvicorn's is disabled). The **mobile app now validates the key with a header** (`X-Apex-Key`) and never puts it in a URL. Failed attempts are throttled (10/min/IP). Documented as a known limitation. |
| 5 | No request-size / rate limits; scan / backtest can pin a small instance | medium | rate buckets, concurrent-heavy cap, 15 MB upload cap (Content-Length and chunked), 5 MB other bodies, symbol / query-length validation |
| 6 | No security headers; docs open | low | `nosniff`, `Referrer-Policy`, HSTS, frame options, CSP on `/m/`, `Cache-Control: no-store` on every `/v1/*` response |
| 7 | `requirements.txt` is unpinned (`>=`) so a cloud build can drift | medium | `requirements.lock` pinned to the validated set; drift tested (see validation report) |
| 8 | Launchers use `--reload`; the old Dockerfile ran 2 workers as root, no health check | low | production start command has no reload, 1 worker by default, graceful shutdown; Dockerfile rewritten (non-root, health check) |
| 9 | Mobile app used relative same-origin paths only (good) but had no configurable base | — | `window.APEX_CONFIG.API_BASE` from `/m/config.js` (server variable `PUBLIC_API_BASE`, default empty = same origin); no domain is hard-coded anywhere |
| 10 | Yahoo Finance is fetched with no key; from a cloud data-centre IP it may rate-limit or refuse | **operational risk** | cannot be tested from this sandbox (its proxy blocks Yahoo). Mitigations: EODHD key, TradingView-CSV import (needs no network at all). Documented in `CLOUD_DEPLOYMENT.md`. |
| 11 | Desktop MANUAL wizard computes with a JS function (`Q0`), not Python (already in `ARCHITECTURE_MAP.md`) | info | not changed; AUTO and the mobile CSV path use the Python engine |
| 12 | Desktop loads Tesseract / TradingView widgets from public CDNs | info | CSP is therefore applied to `/m/` only, never to the desktop page |

## 5. Secrets and private-URL scan (whole repository, all file types)

Searched for: `api_key`, `token`, `secret`, `password`, `credential`, `bearer`, `authorization`, `192.168.`, `127.0.0.1`,
`localhost`, and every `http(s)://` URL, in source, batch files, docs, tests and scripts.

* **No real credentials found.** The only "secret" strings are test placeholders (`SECRET1`, `demo-key`,
  `SECRET123`) inside tests / validation scripts, and `REM set EODHD_API_KEY=PASTE_YOUR_KEY_HERE` in a `.bat` comment.
* Public data-provider URLs (`query1.finance.yahoo.com`, `scanner.tradingview.com`, `eodhd.com`) are the endpoints
  the adapters call — not private.
* `localhost` / `127.0.0.1` occur only in: local launcher scripts, docs describing local use, test harnesses, the
  service-worker "localhost counts as secure" check, and the desktop bundle's fallback used when the page is opened from
  `file://`. **None of them is in the mobile app's request path** (a test asserts this).
* `.gitignore` now excludes `.env`, `.env.*` (except `.env.example`), `*.pem`, `*.key`, logs.

## 6. Corrections to assumptions

* App path is `apexinvest.api.main:app` and the working directory must be `apexinvest_backend/` (the old Dockerfile agreed).
* CORS is not "already restricted" — it was `*`.
* An access-key gate **does** already exist and is sufficient (per-person keys, revocable by redeploy); no new auth system was invented.
* No Postgres/Supabase/Redis is needed.
