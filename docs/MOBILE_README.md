# ApexInvest — mobile web app: run, deploy, use

The mobile app is a normal web page served by the same backend as the desktop app:

* Desktop UI (unchanged):   `http://localhost:8000/`
* **Mobile UI:**            `http://localhost:8000/m/`
* API + docs (unchanged):   `http://localhost:8000/docs`

## Run locally

```bash
cd apexinvest_backend
pip install -r requirements.txt
python -m uvicorn apexinvest.api.main:app --port 8000        # add --reload while developing
```
Windows: double-click `Run ApexInvest.bat` as before, then open `http://localhost:8000/m/`.

### Open it on your phone (same Wi-Fi)
Double-click **`Run ApexInvest (Phone access).bat`** (starts the same engine listening on the network and prints your PC's address), then on the phone open `http://<PC-address>:8000/m/`.
Manual equivalent: `python -m uvicorn apexinvest.api.main:app --host 0.0.0.0 --port 8000`.
Protect it with a key when it is reachable by others: `APEX_ACCESS_KEYS="me:a-long-secret"` (the mobile app shows a key screen; the desktop app already supports this).

### Install it like an app (PWA)
Needs HTTPS (or `localhost`): Android Chrome → menu → *Install app*; iPhone Safari → Share → *Add to Home Screen*. The service worker caches only the app shell; analysis results always come live from the engine.

## Deploy (public HTTPS)

Any host that runs a Python web process or a Docker container works (Render, Railway, Fly.io, a VPS behind Caddy/nginx).

```bash
cd apexinvest_backend
docker build -t apexinvest .
docker run -p 8000:8000 -e APEX_ACCESS_KEYS="me:long-secret" -e EODHD_API_KEY="..." apexinvest
```
* Start command (no Docker): `uvicorn apexinvest.api.main:app --host 0.0.0.0 --port $PORT --workers 2 --proxy-headers`
* Put TLS in front (the host usually does). The mobile app is same-origin, so no CORS setup is needed.
* Secrets (`EODHD_API_KEY`, `APEX_ACCESS_KEYS`) are environment variables on the server only; the browser never receives them. Set `APEX_ACCESS_KEYS` for any internet-facing deployment.
* Before going public, tighten the prototype `allow_origins=["*"]` CORS setting in `api/main.py` to your domain (unchanged from the original; the mobile app does not need it).
* Health check URL: `/v1/health`.

## Using the mobile app

1. **Analyze** — search a ticker (ABUK, CCAP, RAYA, MCRO, IEEC, UEGC…), pick an objective, tap ANALYZE → dashboard: ticker, price, last update, FINAL SIGNAL, MARKET REGIME, TRADE PLAN (Entry, Stop, TP1, TP2, R:R, Confidence), CONFLUENCE. Drill down with the tabs: Details · Strategies · Structure · Entry · Risk · Indicators · Chart.
2. **IMPORT TRADINGVIEW CSV** — export daily (1D) candles from TradingView, tap the button, choose the file → *VALIDATING DATA…* → *DATA VALID* / *DATA ERROR* → **ANALYZE**. Accepted columns: time, open, high, low, close, volume (any TradingView extra columns are ignored). Files ordered newest-first are re-oriented automatically. Nothing is invented: a file without OHLC columns is rejected with the reason; fewer than 30 bars gives WAIT.
3. **Scanner / Watchlist / Portfolio / Trade journal / Validation / Settings** — the same features as the desktop app. Holdings, journal, theme, account size and risk % are stored on the device (same browser keys as desktop, so both UIs on one device share them).

## Tests
```bash
cd apexinvest_backend && python -m pytest -q      # 146 tests (138 original + 8 for the mobile layer)
```
The browser / parity validation suite is in `mobile_validation/` (see its README) and its results are in `docs/VALIDATION_REPORT.md` and `docs/MOBILE_TEST_RESULTS.md`.


## Cloud deployment (phone works with the PC off)

See `docs/DEPLOY_STEP_BY_STEP.md` (non-programmer guide), `docs/CLOUD_DEPLOYMENT.md` (design, cost, limits) and
`docs/CLOUD_DEPLOYMENT_AUDIT.md`. Results of the cloud-vs-local comparison: `CLOUD_VALIDATION_REPORT.md`.
