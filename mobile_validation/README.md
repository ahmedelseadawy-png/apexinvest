# mobile_validation — how the mobile conversion was tested

Everything here is test tooling; none of it is needed to run ApexInvest.

Prerequisites: `pip install -r ../apexinvest_backend/requirements.txt playwright requests pillow` and Chromium for Playwright.

1. Baseline (the original, unmodified project):  `cd .. && mkdir -p /tmp/apex_baseline && git archive original-desktop-baseline | tar -x -C /tmp/apex_baseline`
2. Start two offline servers (network fetchers replaced by deterministic local data; engine untouched):
   `BACKEND=/tmp/apex_baseline/apexinvest_backend ./serve.sh offline 8002` (current app)  and  `./serve.sh offline 8001` (mobile project)
3. Engine parity:  `python parity.py`   → `parity_detail.csv`
4. Screen sizes / touch targets / overflow (360x800, 390x844, 412x915, 768x1024, 1366x768):  `MODE=en-dark python ui_matrix.py` and `MODE=ar-light python ui_matrix.py`
5. Mobile screen vs engine vs desktop screen:  `python ui_parity.py`
6. Auth / security / PWA / RTL / performance: start `APEX_ACCESS_KEYS=ahmed:SECRET123 ./serve.sh offline 8003` then `python misc_tests.py`
7. `python make_reports.py` regenerates `../docs/VALIDATION_REPORT.md` and `../docs/MOBILE_TEST_RESULTS.md`.

`data/` holds TradingView-style sample CSVs (unix time, ISO time, newest-first, short file, invalid files). `shots/` has sample screenshots.
