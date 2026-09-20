# Put ApexInvest on the internet — step by step (no programming needed)

Result: on your phone you open **one web address**, enter your key, pick a stock, tap **ANALYZE**, and get the same analysis your PC gives — with the PC switched off.

You need: an email address, a computer for the one-time setup (about 30–40 minutes), a bank card (Render's always-on plan is about US$7/month; there is also a free plan that goes to sleep when idle).

> Screens of GitHub and Render change now and then, so a button may be worded slightly differently. The names below are the ones to look for.

**Before you start — choose your key.** This is the password for your ApexInvest. Make one up now, at least 20 characters, letters and numbers only (no spaces, commas or colons), for example `k7Xp29QmZr4TbW8sLc5Vd`. Write the setting down exactly like this and keep it private:

```
ahmed:k7Xp29QmZr4TbW8sLc5Vd
```
(`ahmed` is just a label for you; the part after the colon is the key you will type on the phone.)

---

## Step 1 — Create a GitHub repository (the online folder that holds the program)

1. Go to **github.com** and sign in (or *Sign up* — free).
2. Click the **+** at the top right → **New repository**.
3. Name it `apexinvest`. Choose **Private**. Do **not** tick "Add a README". Click **Create repository**.

## Step 2 — Upload ApexInvest

The project has more than 100 files, so the browser's drag-and-drop upload is not suitable. Use **GitHub Desktop** (free):

1. Install it from **desktop.github.com** and sign in with your GitHub account.
2. Unzip `ApexInvest_Cloud.zip` somewhere (for example the Desktop). You get a folder `ApexInvest`.
3. In GitHub Desktop: **File → Add local repository…** → choose the `ApexInvest` folder → **Add repository**.
4. Click **Publish repository** (top bar), keep **"Keep this code private"** ticked, and click **Publish repository** again.

Check on github.com that your `apexinvest` repository now shows the folders `apexinvest_backend`, `docs` … and the file `render.yaml`.

*(If you use git already: `git remote add origin https://github.com/YOU/apexinvest.git && git push -u origin main`.)*

## Step 3 — Create the cloud service (Render)

1. Go to **render.com** → **Sign up** → choose **Sign up with GitHub** and allow access to your `apexinvest` repository.
2. Add a payment card in **Account Settings → Billing** if you choose the paid plan (skip for the free plan).
3. Click **New +** → **Blueprint**.

## Step 4 — Select the repository

Pick **apexinvest** from the list → **Connect**. Render reads the file `render.yaml` from the repository and shows a service called **apexinvest**.

## Step 5 — Build settings (already filled in for you)

Because you used a Blueprint you don't have to type anything here. For reference, Render will use:

* Root directory: `apexinvest_backend`
* Build command: `pip install --upgrade pip && pip install -r requirements.lock`
* Python version: `3.11.9`

*(Doing it by hand instead: **New + → Web Service** → pick the repository → enter the three values above, Runtime **Python 3**, Instance type **Starter**.)*

## Step 6 — Start command (already filled in)

`uvicorn apexinvest.api.main:app --host 0.0.0.0 --port $PORT --workers ${APEX_WORKERS:-1} --proxy-headers --forwarded-allow-ips '*' --no-access-log --no-server-header --timeout-graceful-shutdown 20`

Health check path: `/v1/health`. *(By hand: paste the command into **Start Command**; open **Advanced** and set **Health Check Path** to `/v1/health`.)*

**Free instead of paid?** In the repository open `render.yaml`, change `plan: starter` to `plan: free` (edit on github.com with the pencil icon → Commit changes). The free plan sleeps after 15 idle minutes and takes about a minute to wake up.

## Step 7 — Add the environment variables (your secrets)

Render asks for the four settings that are left empty in the file:

| Name | What to type |
|---|---|
| `APEX_ACCESS_KEYS` | **required** — the line you prepared, e.g. `ahmed:k7Xp29QmZr4TbW8sLc5Vd`. To allow a second person: `ahmed:KEY1,sherif:KEY2` |
| `EODHD_API_KEY` | optional — leave empty to use the free Yahoo feed. If you bought EODHD, paste its API token (from eodhd.com → Dashboard). See "About market data" below. |
| `ALLOWED_ORIGINS` | leave empty |
| `PUBLIC_API_BASE` | leave empty |

(Later you can change them in Render → your service → **Environment**.) Never put these values in GitHub or in a chat.

## Step 8 — Deploy

Click **Apply** / **Deploy Blueprint**. Render installs the program (2–4 minutes) and shows **Live** in green when it is ready. At the top of the service page you will see your address, like `https://apexinvest.onrender.com` (if that name is taken it adds letters, e.g. `https://apexinvest-x7k2.onrender.com`). **This is your web address — copy it.** It is already HTTPS.

## Step 9 — Test that it is alive

In any browser open `https://YOUR-ADDRESS/v1/health`. You should see:

```
{"status":"ok","service":"apexinvest","version":"0.1.0"}
```

## Step 10 — Open the phone app

Open `https://YOUR-ADDRESS/m/` on your phone. You see **Access key**. Type the key (only the part *after* the colon) → **CONTINUE**. The Analyze screen opens. (The desktop version is at `https://YOUR-ADDRESS/`.)

## Step 11 — Add it to the Android home screen

1. Open `https://YOUR-ADDRESS/m/` in **Chrome** on the phone and sign in.
2. Tap the **⋮** menu (top right) → **Install app** (on some phones: **Add to Home screen**) → **Install**.
3. An **ApexInvest** icon appears with your apps. Open it: it runs full-screen like an app.

iPhone: open the address in **Safari** → **Share** → **Add to Home Screen**.

## Step 12 — Test a stock analysis

Tap a quick ticker (ABUK, CCAP, RAYA, MCRO, IEEC…) or type one → **ANALYZE**. You should see the ticker, price, market regime, final signal (BUY / WAIT / AVOID), entry, stop, TP1, TP2, R:R, confidence and expected move, plus the strategy confluence and support/resistance under the tabs.

*If it says "No market data for this ticker right now":* the free Yahoo source sometimes refuses requests that come from a cloud server. Nothing is invented — use Step 13 (works without any provider) or add an EODHD key (see below).

## Step 13 — Test the TradingView CSV upload

1. In TradingView open the stock's chart, timeframe **1D**.
2. Export the chart data as CSV (TradingView's **Export chart data…** in the chart's menu; availability depends on your TradingView plan; if you can't find it in the phone app, use the TradingView website in Chrome).
3. In ApexInvest tap **IMPORT TRADINGVIEW CSV** → choose the file → wait for **DATA VALID** → type the ticker → **ANALYZE**.

A file that is not a candle export, or has too few candles, is refused with a clear message.

---

## Your own domain (optional)

The free address works forever. If you own a domain (e.g. `yourdomain.com`) and want `https://apex.yourdomain.com/m/`:

1. Render → your service → **Settings → Custom Domains → Add Custom Domain** → type `apex.yourdomain.com`.
2. Render shows the DNS record to create. For a sub-domain like `apex` it is a **CNAME** pointing to `YOUR-SERVICE.onrender.com` (use exactly the values Render displays).
3. Log in where you bought the domain (its **DNS** page) → **Add record** → type **CNAME**, name `apex`, value as shown by Render → Save.
4. Back in Render click **Verify**. DNS can take from a few minutes to a few hours. Render then issues the HTTPS certificate automatically.
5. That's all: **there is nothing to change inside ApexInvest** — the app uses whatever address it was opened from. Open `https://apex.yourdomain.com/m/` and install it again from there.

*(A bare domain like `yourdomain.com` needs an A/ALIAS record instead of a CNAME — use the record values Render shows for it.)*

## About market data

* **Free Yahoo (default):** nothing to set up; it is what the desktop app used. Cloud servers are sometimes refused; then use CSV import or EODHD.
* **EODHD (optional):** eodhd.com → sign up → choose a plan that includes the Egyptian exchange (their "EOD Historical Data – All World" plan was US$19.99/month when this was written; the free plan's 20 calls/day is not enough) → copy the API token → Render → Environment → `EODHD_API_KEY`. If a Cairo ticker such as COMI returns nothing, set `EODHD_EGX_SUFFIX` to the exchange code EODHD shows for Egypt.

## Updating later

Change the files, then in GitHub Desktop **Commit** and **Push** — Render redeploys by itself. If something breaks, Render → **Events** → roll back to the previous deploy.

## If something is wrong

| You see | Do this |
|---|---|
| Render build fails | Render → **Logs**: send the last 20 lines. Check the root directory is `apexinvest_backend`. |
| `/v1/health` doesn't open | wait until the service says **Live**; free plan: wait ~1 minute after idle |
| Key screen rejects your key | type only the part after the colon; check `APEX_ACCESS_KEYS` in Render → Environment |
| "Too many requests" | you hit the abuse limit; wait a minute |
| "The server is busy with another large analysis" | a scan/backtest is already running; retry in a minute |
| "No market data for this ticker" | see Step 12 |
| Phone shows an old version | close the app fully and reopen; the app updates itself when online |
