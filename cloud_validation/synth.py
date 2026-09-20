import numpy as np, pandas as pd

def synth(n, seed, drift=0.0004, vol=0.018, px0=40.0, vol_mean=800000, dp=2, zero_vol=0.02, regime=None):
    rng = np.random.default_rng(seed)
    d = np.full(n, drift)
    if regime:   # list of (start_frac, drift) segments
        for f, dr in regime: d[int(f * n):] = dr
    ret = d + vol * rng.standard_normal(n)
    close = px0 * np.exp(np.cumsum(ret))
    prev = np.concatenate([[px0], close[:-1]])
    opn = prev * (1 + 0.003 * rng.standard_normal(n))
    hi = np.maximum(opn, close) * (1 + np.abs(rng.normal(0, vol * 0.5, n)))
    lo = np.minimum(opn, close) * (1 - np.abs(rng.normal(0, vol * 0.5, n)))
    v = vol_mean * np.exp(rng.normal(0, 0.6, n)) * (1 + 6 * np.abs(ret) / max(vol, 1e-9) * 0.2)
    v[rng.random(n) < zero_vol] = 0
    df = pd.DataFrame({"open": opn, "high": hi, "low": lo, "close": close, "volume": np.round(v)})
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].round(dp)
    df["high"] = df[["high", "open", "close"]].max(axis=1)
    df["low"] = df[["low", "open", "close"]].min(axis=1)
    return df.astype(float)

def catalog():
    """(tag, DataFrame) cases used by the validation harness"""
    import json, os
    B = os.environ.get("APEX_BACKEND", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "apexinvest_backend"))
    def load_fixture(name):
        raw = json.load(open(os.path.join(B, "tests", "fixtures", name + ".json")))
        rows = ([[c["o"], c["h"], c["l"], c["c"], c["v"]] for c in raw["candles"]] if "candles" in raw else raw["rows"])
        return pd.DataFrame(rows, columns=["open", "high", "low", "close", "volume"]).astype(float)
    cases = []
    for nm in ("COMI", "SWDY"):
        full = load_fixture(nm)
        for n in (len(full), 130, 90, 60, 45, 30, 25):
            cases.append((f"{nm}{n}", full.tail(n).reset_index(drop=True)))
    specs = [
        ("up250", 250, 11, 0.0012, 0.015, 35.0), ("dn250", 250, 12, -0.0012, 0.016, 60.0), ("side300", 300, 13, 0.0, 0.010, 18.0),
        ("volat200", 200, 14, 0.0003, 0.035, 12.0), ("up480", 480, 15, 0.0008, 0.014, 25.0), ("dn480", 480, 16, -0.0007, 0.017, 90.0),
        ("mixed400", 400, 17, 0.0, 0.016, 45.0), ("pen150", 150, 18, 0.0005, 0.025, 0.85), ("hiprice300", 300, 19, 0.0006, 0.012, 240.0),
        ("lowvol220", 220, 20, 0.0004, 0.006, 32.0), ("up120", 120, 21, 0.0018, 0.013, 22.0), ("dn80", 80, 22, -0.002, 0.02, 30.0),
    ]
    for tag, n, seed, dr, vo, px in specs:
        dp = 4 if px < 1 else 2
        cases.append((tag, synth(n, seed, dr, vo, px, dp=dp)))
    cases.append(("reg350", synth(350, 23, 0.0, 0.015, 30.0, regime=[(0, 0.001), (0.5, -0.001), (0.8, 0.002)])))
    cases.append(("reg300b", synth(300, 24, 0.0, 0.014, 55.0, regime=[(0, -0.001), (0.4, 0.0015), (0.85, -0.0005)])))
    return cases
