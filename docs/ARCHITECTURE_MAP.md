# ApexInvest — architecture map (audited from the uploaded source)

## Existing system (unchanged)

```
Desktop browser ──► frontend_app.html (React + Tailwind bundle, one 466 KB file, served at / and /app)
                          │  fetch() same-origin
                          ▼
                 FastAPI  apexinvest/api/main.py   (uvicorn, port 8000, opt-in X-Apex-Key gate, CORS *)
                          │
                          ▼
                 service.py  ── analyze() / analyze_symbol() / quotes()
                          │
      ┌───────────────────┼────────────────────────────────────────────────────────────┐
      ▼                   ▼                                                            ▼
 market/  (data)     engines/  (analysis)                                          ingest/files.py
  feed.py  EODHD→Yahoo   indicators.py  regime.py  strategies.py (9 strategies)      CSV / Excel / PDF / TXT
  yahoo_egx.py           structure.py   entry.py (optimize_entry)  risk.py (build_plan)   → candles / fundamentals
  tradingview_egx.py     recommendation.py  expected_move.py  scanner.py               (validation + OHLCV aliases)
  eodhd_egx.py           portfolio.py   backtest.py
  fundamentals.py
  datalayer.py
                          ▼
                 JSON result {objective, strategies, regime, signals[], plan{action, entry, stop, tp1, tp2, rr,
                              confidence, entry_levels…}, expected_move, data_source, auto, candles, fundamentals}
```

| Item | Finding |
|---|---|
| Language / framework | Python 3.11+, FastAPI + uvicorn, pydantic, pandas / numpy |
| Backend | `apexinvest_backend/apexinvest/api/main.py` (all routes), `service.py` (orchestration) |
| Engine | `engines/` — indicators, regime, 9 strategies, structure / volume profile, entry optimizer, risk & targets, confidence, recommendation, expected move, scanner, portfolio, backtest |
| Data sources | Yahoo Finance EOD (free), EODHD (optional, `EODHD_API_KEY`), TradingView quote (price only), Yahoo fundamentals; user uploads (CSV / xlsx / PDF / txt) |
| Database | none — stateless engine; small caches in memory; the desktop UI keeps holdings / journal / settings in the browser's localStorage |
| API layer | REST `/v1/*` — analyses (auto, analyze, requirements), scan (also watch-list mode), portfolio, backtest, quotes, fundamentals, assets/search, uploads, health, auth |
| Desktop wrapper | none — a browser tab; Windows `.bat` launchers start uvicorn and open `http://localhost:8000` |
| Frontend | single compiled React/Tailwind file `frontend_app.html`; sections: asset search → objective → AUTO/MANUAL → result; Scanner, Portfolio, My Watch List, Accuracy (backtest), Journal; EN/AR, dark/light |
| Import / export | uploads via `/v1/uploads` (validation summary only). No export |
| Config | env vars `EODHD_API_KEY`, `EODHD_EGX_SUFFIX`, `APEX_ACCESS_KEYS` (all server-side) |
| Dependencies | `requirements.txt` (numpy, pandas, pydantic, fastapi, uvicorn, python-multipart, openpyxl, pdfplumber, requests, pytest, httpx) |

### Things found during the audit (reported, deliberately NOT changed)

1. The desktop **MANUAL / upload wizard** computes its result with a JavaScript function inside `frontend_app.html` (`Q0`), not with the Python engine. Only the **AUTO** path (`/v1/analyses/auto/{symbol}`) is the real engine. The mobile CSV import therefore goes through the real engine instead of copying that JS.
2. `POST /v1/uploads` returns only a validation summary (row count, kind), not candles — so a CSV could not previously be analyzed by the engine over the API. That is the one gap the thin layer fills.
3. CORS is `*` (prototype setting noted in the code) and the launcher uses `--reload`; both are fine locally, see DEPLOY notes for production.
4. The desktop app loads Tesseract (screenshot OCR) and TradingView chart widgets from public CDNs; these are external resources and not part of the engine.

## Added by the mobile conversion

```
Phone browser ──► /m/  mobile web app  (static HTML + CSS + vanilla JS + PWA manifest + service worker)
                          │  same-origin fetch, X-Apex-Key header only if the server enables the key gate
                          ▼
                 the EXISTING /v1/* endpoints  ──►  the EXISTING engine  ──►  JSON  ──►  mobile dashboard
                          ▲
                 NEW thin route  POST /v1/analyses/csv   (api/mobile.py)
                    = existing ingest.ingest()  →  existing analyze_symbol(fetcher=…)  (identical engine path)
```

* `apexinvest/api/mobile.py` — the only new backend file: the CSV route + static hosting of `mobile/` at `/m` (gzip, always-revalidate).
* `apexinvest/api/main.py` — 13 lines appended at the end to include that router and mount `/m`. Nothing above them was edited.
* `mobile/` — `index.html`, `app.css`, `app.js`, `i18n.js`, `manifest.webmanifest`, `sw.js`, `icons/`.
* Mobile navigation maps only to features that already exist: Analyze (search + objective + AUTO analysis), Scanner, Watchlist (the same 35-symbol list as desktop), Portfolio, More → Trade journal, Validation (backtest), Settings.
