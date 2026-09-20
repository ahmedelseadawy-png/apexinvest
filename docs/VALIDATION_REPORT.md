# ApexInvest — Mobile Web Conversion: VALIDATION REPORT

Generated 2026-09-20.  **Current ApexInvest** = the original, untouched project (git tag `original-desktop-baseline`, engine run directly / served on its own server).  **Mobile Version** = the converted project (same engine + API + the new mobile layer).

Data: the sandbox has no route to Yahoo / TradingView / EODHD, so all runs use the offline test feed described in section 6. The engine code path is identical to production; only the network fetch is replaced.

## 1. Result at a glance

* Engine comparisons: **4262 comparisons, 4262 PASS, 0 FAIL** (`VALIDATION_DETAIL.csv` has every row).
* 148 CSV-import cases (28 datasets x 5 objectives + 4 TradingView-style files x 2 objectives — each dataset case is additionally compared against the raw DataFrame the engine would see without any CSV round-trip) and 60 live-feed cases (12 tickers x 5 objectives), plus 26 whole-endpoint comparisons.
* Signal mix in the CSV cases: {'WAIT': 104, 'BUY': 35, 'AVOID': 9} — so BUY plans (entry / stop / TP1 / TP2 / R:R), WAIT and AVOID are all exercised.
* UI-level checks: **35 rows, 35 PASS** (mobile screen vs engine JSON, and mobile screen vs the desktop screen for the same stock).
* Other checks (auth, security, PWA, RTL, journal, performance): **38 checks, 38 PASS**.

## 2. Summary by metric

| Test | Current ApexInvest | Mobile Version | Difference | Status |
|---|---|---|---|---|
| indicators — 348 comparisons | reference values | identical values | 0 differing fields | PASS |
| strategy — 348 comparisons | reference values | identical values | 0 differing fields | PASS |
| regime — 348 comparisons | reference values | identical values | 0 differing fields | PASS |
| structure — 348 comparisons | reference values | identical values | 0 differing fields | PASS |
| entry — 348 comparisons | reference values | identical values | 0 differing fields | PASS |
| stop — 348 comparisons | reference values | identical values | 0 differing fields | PASS |
| tp1 — 348 comparisons | reference values | identical values | 0 differing fields | PASS |
| tp2 — 348 comparisons | reference values | identical values | 0 differing fields | PASS |
| rr — 348 comparisons | reference values | identical values | 0 differing fields | PASS |
| confidence — 348 comparisons | reference values | identical values | 0 differing fields | PASS |
| final signal — 348 comparisons | reference values | identical values | 0 differing fields | PASS |
| expected move — 348 comparisons | reference values | identical values | 0 differing fields | PASS |
| full API responses / endpoints — 86 comparisons | baseline server | mobile-project server | byte-identical JSON (scan wall-clock `as_of` excluded) | PASS |

## 3. Representative cases, shown value-by-value

### BUY plan via CSV import — `CSV COMI60|swing`

| Test | Current ApexInvest | Mobile Version | Difference | Status |
|---|---|---|---|---|
| indicators | {"readings": [["poc", "POC 139.8, value area 127.6-141.5; price inside value."], ["pric... | {"readings": [["poc", "POC 139.8, value area 127.6-141.5; price inside value."], ["pric... | 0 (identical) | PASS |
| strategy | {"auto": {"feed_provides": ["daily_chart", "volume", "volume_profile"], "objective": "s... | {"auto": {"feed_provides": ["daily_chart", "volume", "volume_profile"], "objective": "s... | 0 (identical) | PASS |
| regime | {"adx": 13.69, "atr": 2.098565, "atr_pct": 0.0151, "liquidity": "high", "trend": "sidew... | {"adx": 13.69, "atr": 2.098565, "atr_pct": 0.0151, "liquidity": "high", "trend": "sidew... | 0 (identical) | PASS |
| structure | {"atr": 2.1, "dist_reasons": ["Stalling below prior highs."], "distribution_warning": f... | {"atr": 2.1, "dist_reasons": ["Stalling below prior highs."], "distribution_warning": f... | 0 (identical) | PASS |
| entry | {"chase": "ok", "confirmation_entry": null, "entry": 138.56, "entry_notes": ["Price is ... | {"chase": "ok", "confirmation_entry": null, "entry": 138.56, "entry_notes": ["Price is ... | 0 (identical) | PASS |
| stop | {"stop": 133.79, "stop_basis": "below support zone 138.58 (buffer 2.0xATR)"} | {"stop": 133.79, "stop_basis": "below support zone 138.58 (buffer 2.0xATR)"} | 0 (identical) | PASS |
| tp1 | {"est_tp1": "1-2 weeks", "expected_return_pct": 6.2, "target": 147.16, "tp1": 147.16} | {"est_tp1": "1-2 weeks", "expected_return_pct": 6.2, "target": 147.16, "tp1": 147.16} | 0 (identical) | PASS |
| tp2 | {"est_tp2": "2-4 weeks", "expected_return_tp2_pct": 9.65, "tp2": 151.93} | {"est_tp2": "2-4 weeks", "expected_return_tp2_pct": 9.65, "tp2": 151.93} | 0 (identical) | PASS |
| rr | 1.8 | 1.8 | 0 (identical) | PASS |
| confidence | {"parts": [{"key": "data_completeness", "note": "Share of requested data actually provi... | {"parts": [{"key": "data_completeness", "note": "Share of requested data actually provi... | 0 (identical) | PASS |
| final signal | {"action": "BUY", "reason": "2/3 methods agree; retest entry at 138.04-139.09 gives 1.8... | {"action": "BUY", "reason": "2/3 methods agree; retest entry at 138.04-139.09 gives 1.8... | 0 (identical) | PASS |
| expected move | {"anchor_price": 139.28, "basis": "probable range from the stock's own recent volatilit... | {"anchor_price": 139.28, "basis": "probable range from the stock's own recent volatilit... | 0 (identical) | PASS |

### AVOID via CSV import — `CSV dn250|swing`

| Test | Current ApexInvest | Mobile Version | Difference | Status |
|---|---|---|---|---|
| indicators | {"readings": [["poc", "POC 58.33, value area 46.08-62.42; price below value."], ["price... | {"readings": [["poc", "POC 58.33, value area 46.08-62.42; price below value."], ["price... | 0 (identical) | PASS |
| strategy | {"auto": {"feed_provides": ["daily_chart", "volume", "volume_profile"], "objective": "s... | {"auto": {"feed_provides": ["daily_chart", "volume", "volume_profile"], "objective": "s... | 0 (identical) | PASS |
| regime | {"adx": 23.55, "atr": 1.295572, "atr_pct": 0.0292, "liquidity": "high", "trend": "down"... | {"adx": 23.55, "atr": 1.295572, "atr_pct": 0.0292, "liquidity": "high", "trend": "down"... | 0 (identical) | PASS |
| structure | {} | {} | 0 (identical) | PASS |
| entry | {"chase": "ok", "confirmation_entry": null, "entry": null, "entry_notes": [], "entry_ty... | {"chase": "ok", "confirmation_entry": null, "entry": null, "entry_notes": [], "entry_ty... | 0 (identical) | PASS |
| stop | {"stop": null, "stop_basis": ""} | {"stop": null, "stop_basis": ""} | 0 (identical) | PASS |
| tp1 | {"est_tp1": null, "expected_return_pct": null, "target": null, "tp1": null} | {"est_tp1": null, "expected_return_pct": null, "target": null, "tp1": null} | 0 (identical) | PASS |
| tp2 | {"est_tp2": null, "expected_return_tp2_pct": null, "tp2": null} | {"est_tp2": null, "expected_return_tp2_pct": null, "tp2": null} | 0 (identical) | PASS |
| rr | null | null | 0 (identical) | PASS |
| confidence | {"parts": [{"key": "data_completeness", "note": "Share of requested data actually provi... | {"parts": [{"key": "data_completeness", "note": "Share of requested data actually provi... | 0 (identical) | PASS |
| final signal | {"action": "AVOID", "reason": "A long objective conflicts with a downtrend.", "why": "B... | {"action": "AVOID", "reason": "A long objective conflicts with a downtrend.", "why": "B... | 0 (identical) | PASS |
| expected move | {"anchor_price": 44.38, "basis": "probable range from the stock's own recent volatility... | {"anchor_price": 44.38, "basis": "probable range from the stock's own recent volatility... | 0 (identical) | PASS |

### WAIT via CSV import — `CSV COMI160|swing`

| Test | Current ApexInvest | Mobile Version | Difference | Status |
|---|---|---|---|---|
| indicators | {"readings": [["poc", "POC 132.4, value area 123.6-141.1; price inside value."], ["pric... | {"readings": [["poc", "POC 132.4, value area 123.6-141.1; price inside value."], ["pric... | 0 (identical) | PASS |
| strategy | {"auto": {"feed_provides": ["daily_chart", "volume", "volume_profile"], "objective": "s... | {"auto": {"feed_provides": ["daily_chart", "volume", "volume_profile"], "objective": "s... | 0 (identical) | PASS |
| regime | {"adx": 12.13, "atr": 2.108782, "atr_pct": 0.0151, "liquidity": "high", "trend": "sidew... | {"adx": 12.13, "atr": 2.108782, "atr_pct": 0.0151, "liquidity": "high", "trend": "sidew... | 0 (identical) | PASS |
| structure | {"atr": 2.11, "dist_reasons": ["Stalling below prior highs."], "distribution_warning": ... | {"atr": 2.11, "dist_reasons": ["Stalling below prior highs."], "distribution_warning": ... | 0 (identical) | PASS |
| entry | {"chase": "do_not_chase", "confirmation_entry": null, "entry": null, "entry_notes": [],... | {"chase": "do_not_chase", "confirmation_entry": null, "entry": null, "entry_notes": [],... | 0 (identical) | PASS |
| stop | {"stop": null, "stop_basis": ""} | {"stop": null, "stop_basis": ""} | 0 (identical) | PASS |
| tp1 | {"est_tp1": null, "expected_return_pct": null, "target": null, "tp1": null} | {"est_tp1": null, "expected_return_pct": null, "target": null, "tp1": null} | 0 (identical) | PASS |
| tp2 | {"est_tp2": null, "expected_return_tp2_pct": null, "tp2": null} | {"est_tp2": null, "expected_return_tp2_pct": null, "tp2": null} | 0 (identical) | PASS |
| rr | null | null | 0 (identical) | PASS |
| confidence | {"parts": [{"key": "data_completeness", "note": "Share of requested data actually provi... | {"parts": [{"key": "data_completeness", "note": "Share of requested data actually provi... | 0 (identical) | PASS |
| final signal | {"action": "WAIT", "reason": "Only a partial case (1/2 methods, 4/5, 1.8:1) \u2014 wort... | {"action": "WAIT", "reason": "Only a partial case (1/2 methods, 4/5, 1.8:1) \u2014 wort... | 0 (identical) | PASS |
| expected move | {"anchor_price": 139.28, "basis": "probable range from the stock's own recent volatilit... | {"anchor_price": 139.28, "basis": "probable range from the stock's own recent volatilit... | 0 (identical) | PASS |

### BUY plan via live-feed path — `FEED ABUK|swing`

| Test | Current ApexInvest | Mobile Version | Difference | Status |
|---|---|---|---|---|
| indicators | {"readings": [["poc", "POC 42.12, value area 39.12-53.51; price above value."], ["price... | {"readings": [["poc", "POC 42.12, value area 39.12-53.51; price above value."], ["price... | 0 (identical) | PASS |
| strategy | {"auto": {"feed_provides": ["daily_chart", "volume", "volume_profile"], "objective": "s... | {"auto": {"feed_provides": ["daily_chart", "volume", "volume_profile"], "objective": "s... | 0 (identical) | PASS |
| regime | {"adx": 50.64, "atr": 1.904914, "atr_pct": 0.0319, "liquidity": "high", "trend": "up", ... | {"adx": 50.64, "atr": 1.904914, "atr_pct": 0.0319, "liquidity": "high", "trend": "up", ... | 0 (identical) | PASS |
| structure | {"atr": 1.9, "dist_reasons": [], "distribution_warning": false, "hvn": [52.88, 53.29, 5... | {"atr": 1.9, "dist_reasons": [], "distribution_warning": false, "hvn": [52.88, 53.29, 5... | 0 (identical) | PASS |
| entry | {"chase": "ok", "confirmation_entry": 63.29, "entry": 63.29, "entry_notes": ["Passes th... | {"chase": "ok", "confirmation_entry": 63.29, "entry": 63.29, "entry_notes": ["Passes th... | 0 (identical) | PASS |
| stop | {"stop": 59.29, "stop_basis": "below breakout level 63.1 (buffer 2.0xATR)"} | {"stop": 59.29, "stop_basis": "below breakout level 63.1 (buffer 2.0xATR)"} | 0 (identical) | PASS |
| tp1 | {"est_tp1": "1-2 weeks", "expected_return_pct": 12.64, "target": 71.29, "tp1": 71.29} | {"est_tp1": "1-2 weeks", "expected_return_pct": 12.64, "target": 71.29, "tp1": 71.29} | 0 (identical) | PASS |
| tp2 | {"est_tp2": "2-4 weeks", "expected_return_tp2_pct": 20.23, "tp2": 76.09} | {"est_tp2": "2-4 weeks", "expected_return_tp2_pct": 20.23, "tp2": 76.09} | 0 (identical) | PASS |
| rr | 2.0 | 2.0 | 0 (identical) | PASS |
| confidence | {"parts": [{"key": "data_completeness", "note": "Share of requested data actually provi... | {"parts": [{"key": "data_completeness", "note": "Share of requested data actually provi... | 0 (identical) | PASS |
| final signal | {"action": "BUY", "reason": "5/5 methods agree; confirmation entry at above 63.29 gives... | {"action": "BUY", "reason": "5/5 methods agree; confirmation entry at above 63.29 gives... | 0 (identical) | PASS |
| expected move | {"anchor_price": 59.72, "basis": "probable range from the stock's own recent volatility... | {"anchor_price": 59.72, "basis": "probable range from the stock's own recent volatility... | 0 (identical) | PASS |

### AVOID via live-feed path — `FEED RAYA|swing`

| Test | Current ApexInvest | Mobile Version | Difference | Status |
|---|---|---|---|---|
| indicators | {"readings": [["poc", "POC 6.329, value area 5.207-10.19; price inside value."], ["pric... | {"readings": [["poc", "POC 6.329, value area 5.207-10.19; price inside value."], ["pric... | 0 (identical) | PASS |
| strategy | {"auto": {"feed_provides": ["daily_chart", "volume", "volume_profile"], "objective": "s... | {"auto": {"feed_provides": ["daily_chart", "volume", "volume_profile"], "objective": "s... | 0 (identical) | PASS |
| regime | {"adx": 25.45, "atr": 0.341928, "atr_pct": 0.0369, "liquidity": "medium", "trend": "dow... | {"adx": 25.45, "atr": 0.341928, "atr_pct": 0.0369, "liquidity": "medium", "trend": "dow... | 0 (identical) | PASS |
| structure | {} | {} | 0 (identical) | PASS |
| entry | {"chase": "ok", "confirmation_entry": null, "entry": null, "entry_notes": [], "entry_ty... | {"chase": "ok", "confirmation_entry": null, "entry": null, "entry_notes": [], "entry_ty... | 0 (identical) | PASS |
| stop | {"stop": null, "stop_basis": ""} | {"stop": null, "stop_basis": ""} | 0 (identical) | PASS |
| tp1 | {"est_tp1": null, "expected_return_pct": null, "target": null, "tp1": null} | {"est_tp1": null, "expected_return_pct": null, "target": null, "tp1": null} | 0 (identical) | PASS |
| tp2 | {"est_tp2": null, "expected_return_tp2_pct": null, "tp2": null} | {"est_tp2": null, "expected_return_tp2_pct": null, "tp2": null} | 0 (identical) | PASS |
| rr | null | null | 0 (identical) | PASS |
| confidence | {"parts": [{"key": "data_completeness", "note": "Share of requested data actually provi... | {"parts": [{"key": "data_completeness", "note": "Share of requested data actually provi... | 0 (identical) | PASS |
| final signal | {"action": "AVOID", "reason": "A long objective conflicts with a downtrend.", "why": "B... | {"action": "AVOID", "reason": "A long objective conflicts with a downtrend.", "why": "B... | 0 (identical) | PASS |
| expected move | {"anchor_price": 9.26, "basis": "probable range from the stock's own recent volatility ... | {"anchor_price": 9.26, "basis": "probable range from the stock's own recent volatility ... | 0 (identical) | PASS |

### WAIT via live-feed path (long-term) — `FEED UEGC|long_term`

| Test | Current ApexInvest | Mobile Version | Difference | Status |
|---|---|---|---|---|
| indicators | {"readings": [["trend", "Downtrend: price 168.8 vs MA50 172.9, MA200 186.8 (death cross... | {"readings": [["trend", "Downtrend: price 168.8 vs MA50 172.9, MA200 186.8 (death cross... | 0 (identical) | PASS |
| strategy | {"auto": {"feed_provides": ["daily_chart", "volume", "volume_profile"], "objective": "l... | {"auto": {"feed_provides": ["daily_chart", "volume", "volume_profile"], "objective": "l... | 0 (identical) | PASS |
| regime | {"adx": 13.78, "atr": 4.508803, "atr_pct": 0.0267, "liquidity": "high", "trend": "sidew... | {"adx": 13.78, "atr": 4.508803, "atr_pct": 0.0267, "liquidity": "high", "trend": "sidew... | 0 (identical) | PASS |
| structure | {} | {} | 0 (identical) | PASS |
| entry | {"chase": "ok", "confirmation_entry": null, "entry": null, "entry_notes": [], "entry_ty... | {"chase": "ok", "confirmation_entry": null, "entry": null, "entry_notes": [], "entry_ty... | 0 (identical) | PASS |
| stop | {"stop": null, "stop_basis": ""} | {"stop": null, "stop_basis": ""} | 0 (identical) | PASS |
| tp1 | {"est_tp1": null, "expected_return_pct": null, "target": null, "tp1": null} | {"est_tp1": null, "expected_return_pct": null, "target": null, "tp1": null} | 0 (identical) | PASS |
| tp2 | {"est_tp2": null, "expected_return_tp2_pct": null, "tp2": null} | {"est_tp2": null, "expected_return_tp2_pct": null, "tp2": null} | 0 (identical) | PASS |
| rr | null | null | 0 (identical) | PASS |
| confidence | {"parts": [{"key": "data_completeness", "note": "Share of requested data actually provi... | {"parts": [{"key": "data_completeness", "note": "Share of requested data actually provi... | 0 (identical) | PASS |
| final signal | {"action": "WAIT", "reason": "The recent move is downward, which works against a buy-an... | {"action": "WAIT", "reason": "The recent move is downward, which works against a buy-an... | 0 (identical) | PASS |
| expected move | {"anchor_price": 168.82, "basis": "probable range from the stock's own recent volatilit... | {"anchor_price": 168.82, "basis": "probable range from the stock's own recent volatilit... | 0 (identical) | PASS |

## 4. What the phone screen shows vs the engine and vs the desktop screen

| Test | Current ApexInvest | Mobile Version | Difference | Status |
|---|---|---|---|---|
| MOBILE UI vs engine JSON · ABUK/swing | {"action": "BUY", "ENTRY": "63.29", "STOP": "59.29", "TP1": "71.29", "TP2": "76.09", "R:R": "2.00 : 1", "CONFIDENCE": "5/5", "TREND": "Up", "VOLATILITY": "Medium", "LIQUI | {"action": "BUY", "ENTRY": "63.29", "STOP": "59.29", "TP1": "71.29", "TP2": "76.09", "R:R": "2.00 : 1", "CONFIDENCE": "5/5", "TREND": "Up", "VOLATILITY": "Medium", "LIQUI | 0 | PASS |
| DESKTOP UI vs MOBILE UI · ABUK/swing | desktop shows: action=BUY; numbers found stop,tp1,tp2,entry,poc,vah,val,action,confidence | mobile shows: BUY entry=63.29 stop=59.29 tp1=71.29 tp2=76.09 rr=2.00 : 1 | 0 | PASS |
| MOBILE UI vs engine JSON · ABUK/long_term | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "4/5", "TREND": "Up", "VOLATILITY": "Medium", "LIQUIDITY": "High"} | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "4/5", "TREND": "Up", "VOLATILITY": "Medium", "LIQUIDITY": "High"} | 0 | PASS |
| DESKTOP UI vs MOBILE UI · ABUK/long_term | desktop shows: action=WAIT; numbers found poc,vah,val,action | mobile shows: WAIT entry=— stop=— tp1=— tp2=— rr=— | 0 | PASS |
| MOBILE UI vs engine JSON · CCAP/swing | {"action": "BUY", "ENTRY": "16.02", "STOP": "15.44", "TP1": "17.05", "TP2": "17.17", "R:R": "1.80 : 1", "CONFIDENCE": "4/5", "TREND": "Up", "VOLATILITY": "Medium", "LIQUI | {"action": "BUY", "ENTRY": "16.02", "STOP": "15.44", "TP1": "17.05", "TP2": "17.17", "R:R": "1.80 : 1", "CONFIDENCE": "4/5", "TREND": "Up", "VOLATILITY": "Medium", "LIQUI | 0 | PASS |
| DESKTOP UI vs MOBILE UI · CCAP/swing | desktop shows: action=BUY; numbers found stop,tp1,tp2,entry,poc,vah,val,action,confidence | mobile shows: BUY entry=16.02 stop=15.44 tp1=17.05 tp2=17.17 rr=1.80 : 1 | 0 | PASS |
| MOBILE UI vs engine JSON · CCAP/long_term | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "4/5", "TREND": "Up", "VOLATILITY": "Medium", "LIQUIDITY": "Medium"} | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "4/5", "TREND": "Up", "VOLATILITY": "Medium", "LIQUIDITY": "Medium"} | 0 | PASS |
| DESKTOP UI vs MOBILE UI · CCAP/long_term | desktop shows: action=WAIT; numbers found poc,vah,val,action | mobile shows: WAIT entry=— stop=— tp1=— tp2=— rr=— | 0 | PASS |
| MOBILE UI vs engine JSON · RAYA/swing | {"action": "AVOID", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "3/5", "TREND": "Down", "VOLATILITY": "Medium", "LIQUIDITY": "Medium"} | {"action": "AVOID", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "3/5", "TREND": "Down", "VOLATILITY": "Medium", "LIQUIDITY": "Medium"} | 0 | PASS |
| DESKTOP UI vs MOBILE UI · RAYA/swing | desktop shows: action=AVOID; numbers found action | mobile shows: AVOID entry=— stop=— tp1=— tp2=— rr=— | 0 | PASS |
| MOBILE UI vs engine JSON · RAYA/long_term | {"action": "AVOID", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "3/5", "TREND": "Down", "VOLATILITY": "Medium", "LIQUIDITY": "Medium"} | {"action": "AVOID", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "3/5", "TREND": "Down", "VOLATILITY": "Medium", "LIQUIDITY": "Medium"} | 0 | PASS |
| DESKTOP UI vs MOBILE UI · RAYA/long_term | desktop shows: action=AVOID; numbers found action | mobile shows: AVOID entry=— stop=— tp1=— tp2=— rr=— | 0 | PASS |
| MOBILE UI vs engine JSON · MCRO/swing | {"action": "AVOID", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "3/5", "TREND": "Down", "VOLATILITY": "Medium", "LIQUIDITY": "High"} | {"action": "AVOID", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "3/5", "TREND": "Down", "VOLATILITY": "Medium", "LIQUIDITY": "High"} | 0 | PASS |
| DESKTOP UI vs MOBILE UI · MCRO/swing | desktop shows: action=AVOID; numbers found action | mobile shows: AVOID entry=— stop=— tp1=— tp2=— rr=— | 0 | PASS |
| MOBILE UI vs engine JSON · MCRO/long_term | {"action": "AVOID", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "3/5", "TREND": "Down", "VOLATILITY": "Medium", "LIQUIDITY": "High"} | {"action": "AVOID", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "3/5", "TREND": "Down", "VOLATILITY": "Medium", "LIQUIDITY": "High"} | 0 | PASS |
| DESKTOP UI vs MOBILE UI · MCRO/long_term | desktop shows: action=AVOID; numbers found action | mobile shows: AVOID entry=— stop=— tp1=— tp2=— rr=— | 0 | PASS |
| MOBILE UI vs engine JSON · IEEC/swing | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "3/5", "TREND": "Sideways", "VOLATILITY": "Medium", "LIQUIDITY": "Medium"} | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "3/5", "TREND": "Sideways", "VOLATILITY": "Medium", "LIQUIDITY": "Medium"} | 0 | PASS |
| DESKTOP UI vs MOBILE UI · IEEC/swing | desktop shows: action=WAIT; numbers found action | mobile shows: WAIT entry=— stop=— tp1=— tp2=— rr=— | 0 | PASS |
| MOBILE UI vs engine JSON · IEEC/long_term | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "3/5", "TREND": "Sideways", "VOLATILITY": "Medium", "LIQUIDITY": "Medium"} | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "3/5", "TREND": "Sideways", "VOLATILITY": "Medium", "LIQUIDITY": "Medium"} | 0 | PASS |
| DESKTOP UI vs MOBILE UI · IEEC/long_term | desktop shows: action=WAIT; numbers found action | mobile shows: WAIT entry=— stop=— tp1=— tp2=— rr=— | 0 | PASS |
| MOBILE UI vs engine JSON · UEGC/swing | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "4/5", "TREND": "Sideways", "VOLATILITY": "Medium", "LIQUIDITY": "High"} | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "4/5", "TREND": "Sideways", "VOLATILITY": "Medium", "LIQUIDITY": "High"} | 0 | PASS |
| DESKTOP UI vs MOBILE UI · UEGC/swing | desktop shows: action=WAIT; numbers found action | mobile shows: WAIT entry=— stop=— tp1=— tp2=— rr=— | 0 | PASS |
| MOBILE UI vs engine JSON · UEGC/long_term | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "4/5", "TREND": "Sideways", "VOLATILITY": "Medium", "LIQUIDITY": "High"} | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "4/5", "TREND": "Sideways", "VOLATILITY": "Medium", "LIQUIDITY": "High"} | 0 | PASS |
| DESKTOP UI vs MOBILE UI · UEGC/long_term | desktop shows: action=WAIT; numbers found action | mobile shows: WAIT entry=— stop=— tp1=— tp2=— rr=— | 0 | PASS |
| MOBILE UI vs engine JSON · COMI/swing | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "4/5", "TREND": "Sideways", "VOLATILITY": "Medium", "LIQUIDITY": "High"} | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "4/5", "TREND": "Sideways", "VOLATILITY": "Medium", "LIQUIDITY": "High"} | 0 | PASS |
| DESKTOP UI vs MOBILE UI · COMI/swing | desktop shows: action=WAIT; numbers found poc,vah,val,action | mobile shows: WAIT entry=— stop=— tp1=— tp2=— rr=— | 0 | PASS |
| MOBILE UI vs engine JSON · COMI/long_term | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "4/5", "TREND": "Sideways", "VOLATILITY": "Medium", "LIQUIDITY": "High"} | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "4/5", "TREND": "Sideways", "VOLATILITY": "Medium", "LIQUIDITY": "High"} | 0 | PASS |
| DESKTOP UI vs MOBILE UI · COMI/long_term | desktop shows: action=WAIT; numbers found poc,vah,val,action | mobile shows: WAIT entry=— stop=— tp1=— tp2=— rr=— | 0 | PASS |
| MOBILE UI vs engine JSON · SWDY/swing | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "4/5", "TREND": "Up", "VOLATILITY": "High", "LIQUIDITY": "High"} | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "4/5", "TREND": "Up", "VOLATILITY": "High", "LIQUIDITY": "High"} | 0 | PASS |
| DESKTOP UI vs MOBILE UI · SWDY/swing | desktop shows: action=WAIT; numbers found poc,vah,val,action | mobile shows: WAIT entry=— stop=— tp1=— tp2=— rr=— | 0 | PASS |
| MOBILE UI vs engine JSON · SWDY/long_term | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "4/5", "TREND": "Up", "VOLATILITY": "High", "LIQUIDITY": "High"} | {"action": "WAIT", "ENTRY": "—", "STOP": "—", "TP1": "—", "TP2": "—", "R:R": "—", "CONFIDENCE": "4/5", "TREND": "Up", "VOLATILITY": "High", "LIQUIDITY": "High"} | 0 | PASS |
| DESKTOP UI vs MOBILE UI · SWDY/long_term | desktop shows: action=WAIT; numbers found poc,vah,val,action | mobile shows: WAIT entry=— stop=— tp1=— tp2=— rr=— | 0 | PASS |
| CSV import via UI · EGX_COMI, 1D_tv.csv | API action=WAIT stop=— rows=160 order=oldest-first | UI 'DATA VALID' → WAIT (COMI) | 0 | PASS |
| CSV import via UI · EGX_RAYA, 1D.csv | API action=WAIT stop=— rows=300 order=oldest-first | UI 'DATA VALID' → WAIT (RAYA) | 0 | PASS |
| CSV import via UI · EGX_COMI_newest_first.csv | API action=WAIT stop=— rows=160 order=reversed (file was newest-first) | UI 'DATA VALID' → WAIT (COMI) | 0 | PASS |

## 5. Whole-endpoint comparisons (baseline server vs mobile-project server)

| Test | Current ApexInvest | Mobile Version | Difference | Status |
|---|---|---|---|---|
| SCAN short_swing/balanced (watch-list of 12) | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| SCAN short_swing/conservative (watch-list of 12) | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| SCAN short_swing/aggressive (watch-list of 12) | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| SCAN medium_swing/balanced (watch-list of 12) | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| SCAN medium_swing/conservative (watch-list of 12) | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| SCAN medium_swing/aggressive (watch-list of 12) | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| SCAN long_term/balanced (watch-list of 12) | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| SCAN long_term/conservative (watch-list of 12) | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| SCAN long_term/aggressive (watch-list of 12) | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| SCAN intraday/balanced (watch-list of 12) | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| SCAN intraday/conservative (watch-list of 12) | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| SCAN intraday/aggressive (watch-list of 12) | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| SCAN full universe short_swing/balanced | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| PORTFOLIO | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| BACKTEST COMI swing | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| BACKTEST ABUK long_term | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| BACKTEST universe swing (limit 6) | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| QUOTES | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| ASSETS SEARCH ab | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| ASSETS SEARCH (all) | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| HEALTH | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| DATA HEALTH | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| UPLOAD summary | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| ANALYZE manual (existing endpoint) | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| DESKTOP UI / (frontend_app.html) | HTTP 200 | HTTP 200 | 0 (identical) | PASS |
| DESKTOP UI /app | HTTP 200 | HTTP 200 | 0 (identical) | PASS |

## 6. How the comparison was made (so you can re-run it)

* `testing/offline_server.py` starts the unmodified app with only the four network fetchers (Yahoo daily/quote, TradingView quote, fundamentals) replaced by deterministic local data (the two real COMI/SWDY fixtures shipped in the project plus seeded synthetic series). No engine code is touched.
* `testing/ref_csv.py` runs the ORIGINAL engine (pristine copy from git tag `original-desktop-baseline`) on each CSV via the original `ingest.ingest` + `analyze_symbol`.
* `testing/parity.py` posts the same files to the mobile API and deep-compares every field of regime, signals, structure, entry, stop, TP1, TP2, R:R, confidence, final signal and expected move; and diffs the baseline server vs the mobile-project server on the live-feed, scanner, watch-list, portfolio, backtest, quotes, search, health, upload and analyze endpoints.
* `testing/ui_parity.py` drives real Chromium: the mobile dashboard (390x844) and the desktop UI (1366x768) for ABUK, CCAP, RAYA, MCRO, IEEC, UEGC, COMI, SWDY x swing/long-term, and the CSV import screen.

## 7. Known limits of this validation (honest)

* Live Yahoo / TradingView / EODHD feeds were unreachable from the sandbox, so live data was not exercised. The live path is byte-identical code to the desktop app's (same `GET /v1/analyses/auto/{symbol}`), so this risk is the same as for the desktop app.
* Docker build could not be run here (no Docker daemon). A clean-virtualenv install from `requirements.txt`, the full test-suite and a 2-worker production `uvicorn` start were run instead.
* Real iPhone Safari / Android Chrome hardware was not available; testing used Chromium with mobile emulation (touch, DPR 2) at the requested sizes.