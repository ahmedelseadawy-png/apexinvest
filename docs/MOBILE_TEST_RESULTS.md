# Mobile testing results

Chromium with touch + device-pixel-ratio 2 for phone/tablet sizes (desktop size without touch). Each screen is loaded and checked for: horizontal scroll (document wider than viewport), elements sticking out of the viewport, and interactive controls smaller than 40 px. Scrollable tab strips and tables are allowed to scroll inside their own container.

Screens checked at every size: Analyze, search results, dashboard (BUY), all six drill-down tabs + chart, dashboard (WAIT), dashboard (long-term), no-data error, Scanner, Watchlist, Portfolio, More, Settings, CSV import (valid), imported-file dashboard, CSV import error, Journal, Validation.

| Mode | Viewport | Screens | Horizontal scroll | Clipped elements | Touch targets < 40 px | Result |
|---|---|---|---|---|---|---|
| ar-light | 360x800 | 22 | 0 | 0 | 0 | PASS |
| ar-light | 390x844 | 22 | 0 | 0 | 0 | PASS |
| ar-light | 412x915 | 22 | 0 | 0 | 0 | PASS |
| ar-light | 768x1024 | 22 | 0 | 0 | 0 | PASS |
| ar-light | 1366x768 | 22 | 0 | 0 | 0 | PASS |
| en-dark | 360x800 | 22 | 0 | 0 | 0 | PASS |
| en-dark | 390x844 | 22 | 0 | 0 | 0 | PASS |
| en-dark | 412x915 | 22 | 0 | 0 | 0 | PASS |
| en-dark | 768x1024 | 22 | 0 | 0 | 0 | PASS |
| en-dark | 1366x768 | 22 | 0 | 0 | 0 | PASS |

## Functional / non-functional checks

| Check | Result | Detail |
|---|---|---|
| auth: static shell open without key | PASS |  |
| auth: /v1 data blocked without key | PASS |  |
| auth: /v1/analyses/csv blocked without key | PASS |  |
| auth: wrong key rejected | PASS |  |
| auth: right key accepted | PASS |  |
| security: /v1/health does not expose env/secret config | PASS |  |
| security: /v1/data/health?symbol=COMI does not expose env/secret config | PASS |  |
| security: /v1/auth/status does not expose env/secret config | PASS |  |
| security: no API keys / tokens / long secrets in /m/app.js | PASS | [] |
| security: no API keys / tokens / long secrets in /m/index.html | PASS | [] |
| security: no API keys / tokens / long secrets in /m/i18n.js | PASS | [] |
| security: no API keys / tokens / long secrets in /m/sw.js | PASS | [] |
| security: no API keys / tokens / long secrets in /m/app.css | PASS | [] |
| security: no API keys / tokens / long secrets in /m/manifest.webmanifest | PASS | [] |
| security: /m/../frontend_app.html not served | PASS | HTTP 404 |
| security: /m/%2e%2e/frontend_app.html not served | PASS | HTTP 404 |
| security: /m/..%2fapexinvest/service.py not served | PASS | HTTP 404 |
| security: /m/apexinvest/api/main.py not served | PASS | HTTP 404 |
| security: /m/requirements.txt not served | PASS | HTTP 404 |
| security: /m/../requirements.txt not served | PASS | HTTP 404 |
| auth UI: login screen shown when server requires key | PASS |  |
| auth UI: wrong key shows error | PASS |  |
| auth UI: right key opens the app | PASS |  |
| auth UI: analysis works with key sent in X-Apex-Key header | PASS |  |
| auth UI: key kept only in this browser's localStorage | PASS |  |
| auth UI: stale/revoked key returns to login | PASS |  |
| pwa: service worker registered & active | PASS |  |
| pwa: manifest has name, standalone display, start_url, 192/512/maskable icons | PASS |  |
| pwa: manifest icons exist | PASS |  |
| pwa: apple-touch-icon exists | PASS |  |
| pwa: app shell opens offline (cached) | PASS |  |
| pwa: offline search shows a clear error (no fake data) | PASS | Can't reach the ApexInvest server. Check your connection and retry. |
| pwa: /v1 API responses are never cached by the service worker | PASS | 8 cached shell files |
| i18n: Arabic sets dir=rtl | PASS |  |
| rtl+light: dashboard no horizontal overflow | PASS | [390, 390] |
| journal: logged record uses the desktop schema (symbol/objective/entry/stop/tp1/status/opened/id) | PASS | {"id": "1789923605606-ivpap", "opened": "2026-09-20", "status": "open", "symbol": "ABUK", "objective": "Swing", "entry": 63.29, "stop": 59.29, "tp1":  |
| perf: first load of the mobile shell (local) | PASS | 5 requests, 26.0 KB on the wire, DOMContentLoaded 42 ms, load 42 ms |
| perf: desktop bundle for comparison | PASS | 466 KB (uncompressed) vs mobile shell above |