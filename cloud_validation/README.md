# cloud_validation — reproducing the cloud tests

TEST-ONLY tooling (never part of the product). It proves the cloud build gives the same results as the original.

1. `python -m venv /tmp/venv_lock && /tmp/venv_lock/bin/pip install -r ../apexinvest_backend/requirements.lock`
2. Baseline (original code): `git archive original-desktop-baseline apexinvest_backend | tar -x -C /tmp/baseline`
   then `BACKEND=/tmp/baseline/apexinvest_backend ../mobile_validation/serve.sh offline 8002`
3. Cloud-equivalent server (production mode, real start-command flags, offline data): `./run_cloud_sim.sh start 8010 1`
   (`NOKEYS=1` disables the key gate; `VENV=` picks the virtualenv)
4. `python cloud_parity.py` — 374 cases, exact comparison, writes `cloud_parity_detail.csv`
5. `python raw_indicators.py <backend_dir> out.json` under different interpreters / `TZ=` values, then `cmp` the outputs
6. `python android_emulation.py http://127.0.0.1:8010 <key>` (EMULATED Pixel 7), `python desktop_smoke.py …`, `python security_probe.py …`
7. `python perf.py`, `python load_time.py`; `ui_run/ui_matrix.py` (set `APEX_KEY`, `MODE=en-dark|ar-light`) for the 5-viewport screen matrix

`cloud_sim_app.py` imports the unmodified product app after replacing ONLY the network fetchers (the sandbox cannot reach Yahoo/TradingView/EODHD).
