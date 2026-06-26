# ii-to-soren

A tool to download your data from [Interactive Investor](https://www.ii.co.uk/) and push it to [Soren](https://www.getsoren.app) for CGT calculations.

It comes with both a **Streamlit web UI** (recommended) and a **CLI** for scripting / automation.

> **Never used GitHub, the terminal, or Python before?** Don't worry — you don't need to know any of it. The **[step-by-step setup](#setup)** below is just *install Python → download this project → double-click a file*. No commands to type. It takes about 10 minutes the first time, and most of that is set up once and never again.

## 🧰 The apps you'll use

You'll touch a few apps during setup. Here's what each one is and where it comes from, so nothing below is a surprise:

| | App | What it is | Do you install it? |
|---|------|------------|--------------------|
| 🐍 | **Python** | The programming language this tool is built on. The tool can't run without it. | Yes — once, in step 1 |
| ⌨️ | **Terminal** (Mac) / **Command Prompt** (Windows) | A black window that pops up when you start the app. Built into your computer — you mostly just watch it. | No — already installed |
| 🌐 | **Web browser** (Chrome, Safari, Edge…) | Where the app's screen opens, and where you log into Interactive Investor. | No — already installed |
| 💷 | **[Interactive Investor](https://www.ii.co.uk/)** | Your investment account. The tool downloads your data from here. | No — you already have an account |
| 🌲 | **[Soren](https://www.getsoren.app)** | Where your data gets sent for Capital Gains Tax calculations. | No — sign up online (optional) |

## What it downloads

| Data | Format | Notes |
|------|--------|-------|
| Portfolio snapshots | CSV | Current holdings, one file per run |
| Cash balances | CSV | Cash position per account |
| Transaction statements | CSV | Chunked by calendar year, per currency |
| Corporate action notifications | PDF | Downloaded from your II document history |

## Setup

There are just **three things to do**: install Python, download this project, then double-click the start file. No typing commands required — pick the guide for your computer below.

<details open>
<summary><strong>🍎 &nbsp;Mac — step by step</strong></summary>

<br>

#### 🐍 Step 1 — Install Python

Python is the engine this tool runs on. To install it: go to [python.org/downloads](https://www.python.org/downloads/), click the big yellow **Download Python** button, open the file that downloads, and click through the installer (the default options are fine).

> Already have Python 3.10 or newer? You can skip this — but if you're not sure, just install it anyway. Installing again does no harm.

#### 📥 Step 2 — Download this project

1. At the top of [this GitHub page](.), click the green **`< > Code`** button.
2. In the menu that drops down, click **Download ZIP**.
3. Find the downloaded ZIP (usually in your **Downloads** folder) and double-click it to unzip. You'll get a folder called **`ii-to-soren-main`**.
4. Drag that folder somewhere easy to find, like your **Desktop**.

#### ▶️ Step 3 — Double-click to start

1. Open the **`ii-to-soren-main`** folder.
2. Double-click the file named **`Start.command`**.

That's it. A black window appears and sets everything up for you (the very first time this takes a minute or two — after that it's quick). Then your 🌐 **web browser** opens automatically showing the app, and it walks you through everything else on screen.

> 🛡️ **First time: "Apple could not verify…" or "unidentified developer"?**
> macOS is cautious about files from the internet. To get past it just once:
> 1. **Right-click** (or hold `Control` and click) `Start.command`, then choose **Open**.
> 2. In the box that pops up, click **Open** again.
>
> After you've done this once, plain double-clicking works from then on.

➡️ **When you're done**, click the black window and press `Ctrl C` (hold Control, tap C) to stop the app, then close the window. **Next time**, you only need this step 3 — just double-click `Start.command` again.

> 🆘 **It says Python wasn't found?** Python isn't installed yet (or the window opened before installation finished). Do step 1, then double-click `Start.command` again.

<br>

<details>
<summary>Prefer to type commands yourself? (optional)</summary>

<br>

If you'd rather not use the double-click launcher, open **Terminal**, drag the project folder in after typing `cd ` (with a trailing space) and press Enter, then run:

```bash
python3 -m pip install -r requirements.txt   # once
python3 -m streamlit run ui.py               # each time
```

</details>

</details>

<details>
<summary><strong>🪟 &nbsp;Windows — step by step</strong></summary>

<br>

#### 🐍 Step 1 — Install Python

Python is the engine this tool runs on.

1. Go to [python.org/downloads](https://www.python.org/downloads/) and click the big yellow **Download Python** button.
2. Open the file that downloads to start the installer.
3. ⚠️ **This is the important bit:** on the very first installer screen, tick the checkbox at the bottom that says **"Add Python to PATH"** *before* you click **Install Now**. If you miss it, the start file won't be able to find Python.

> Already have Python 3.10 or newer? You can skip this — but if you're not sure, install it anyway (and still tick "Add Python to PATH"). Installing again does no harm.

#### 📥 Step 2 — Download this project

1. At the top of [this GitHub page](.), click the green **`< > Code`** button.
2. In the menu that drops down, click **Download ZIP**.
3. Find the downloaded ZIP (usually in your **Downloads** folder), right-click it, and choose **Extract All…**, then **Extract**. You'll get a folder called **`ii-to-soren-main`**.
4. Move that folder somewhere easy to find, like your **Desktop**.

#### ▶️ Step 3 — Double-click to start

1. Open the **`ii-to-soren-main`** folder.
2. Double-click the file named **`Start.bat`**.

That's it. A black window appears and sets everything up for you (the very first time this takes a minute or two — after that it's quick). Then your 🌐 **web browser** opens automatically showing the app, and it walks you through everything else on screen.

> 🛡️ **First time: a blue "Windows protected your PC" box?**
> Windows is cautious about files from the internet. Click **More info**, then **Run anyway**. You only need to do this once.

➡️ **When you're done**, click the black window and press `Ctrl C` (hold Control, tap C) to stop the app, then close the window. **Next time**, you only need this step 3 — just double-click `Start.bat` again.

> 🆘 **It says Python wasn't found?** Python isn't installed, or the **"Add Python to PATH"** box wasn't ticked during install. Re-run the installer from step 1, tick that box, then double-click `Start.bat` again.

<br>

<details>
<summary>Prefer to type commands yourself? (optional)</summary>

<br>

If you'd rather not use the double-click launcher, open the project folder in File Explorer, type `cmd` in the address bar and press Enter, then run:

```
python -m pip install -r requirements.txt   :: once
python -m streamlit run ui.py               :: each time
```

</details>

</details>

## 🔑 Logging into Interactive Investor (the "token")

To download your data, the tool needs proof that you're logged into Interactive Investor. That proof is a long code called a **token**.

**You don't need to understand any of this.** When you first run the app, it shows you a simple **one-click button** (a "bookmarklet") that you drag onto your browser's bookmarks bar. After that, getting a fresh token is a single click whenever the app asks for one. Just follow the on-screen instructions — there's nothing to set up here in advance.

> ⏱️ Tokens expire after about **28 minutes**, so the app will occasionally ask you to click the button again for a fresh one. That's normal.

<details>
<summary>Advanced: grab a token by hand (most people can ignore this)</summary>

<br>

1. Log into [ii.co.uk](https://www.ii.co.uk/) in your browser
2. Open DevTools → **Network** tab
3. Reload any page (e.g. your portfolio)
4. Find any request to `api-prod.ii.co.uk`
5. Copy the `Authorization: Bearer eyJ…` header value

</details>

## 🖥️ Web UI

This is the screen that opens in your browser when you start the app. To open it again another day, just double-click the start file again (`Start.command` on Mac, `Start.bat` on Windows).

```bash
streamlit run ui.py
```

The UI guides you through initial setup and lets you:

- Paste II Bearer tokens for each configured user
- Choose which account(s) to download
- Optionally push to Soren immediately after downloading
- View live output and a success/failure summary

## Command line usage

```bash
# Download everything for all configured users (prompts for token per user)
python ii_download.py

# Single user (substring match on email)
python ii_download.py --user alice

# Portfolio snapshots only
python ii_download.py --portfolio

# Transaction statements only
python ii_download.py --transactions

# Corporate action PDFs only
python ii_download.py --corporate-actions

# Specific account
python ii_download.py --account 1234567

# Pass token directly (useful for scripting)
python ii_download.py --user alice --token "eyJhbG..."

# Override the transaction end date (default: today)
python ii_download.py --to-date 2026-03-01

# Download and push to Soren in one step
python ii_download.py --push

# Push existing downloads to Soren (no II download)
python ii_download.py --push-only

# Push a specific account only
python ii_download.py --push-only --account 1234567

# Verbose API response logging
python ii_download.py --debug
```

## Config format

```yaml
# Random delay between II API requests (seconds) — avoids rate limiting
ii_request_delay:
  min: 1
  max: 3

# Soren integration (only needed for --push / --push-only)
cgt:
  api_url: "https://app.getsoren.app"
  api_key: "tcgt_xxxxxxxxxxxxxxxxxxxx"   # long-lived API key from Settings → API

users:
  - email: "alice@example.com"
    # customer_id is optional — extracted automatically from the Bearer token.
    # Only needed if you want to use a pre-saved token without logging in first.
    # customer_id: "00000000000"
    accounts:
      - id: "1234567"
        name: "ISA"
        start_date: "2024-01-01"   # earliest date to fetch transactions from
        currencies: ["GBP"]

      - id: "7654321"
        name: "Trading"
        start_date: "2023-06-01"
        currencies: ["GBP", "USD"]
        # Optional: per-currency start dates (auto-populated by the setup wizard).
        # Non-GBP currencies default to start_date if this is omitted.
        currency_start_dates:
          USD: "2024-03-15"

  - email: "bob@example.com"
    accounts:
      - id: "9999999"
        name: "SIPP"
        start_date: "2022-01-01"
        currencies: ["GBP"]
```

### Config fields

| Field | Required | Description |
|-------|----------|-------------|
| `users[].email` | Yes | II login email |
| `users[].accounts[].id` | Yes | II account number (visible in the II URL) |
| `users[].accounts[].start_date` | Yes | Earliest transaction date to fetch |
| `users[].accounts[].currencies` | Yes | Currency codes for transaction statements |
| `users[].accounts[].currency_start_dates` | No | Per-currency start date overrides (auto-populated by the setup wizard); non-GBP currencies fall back to `start_date` if omitted |
| `users[].accounts[].name` | No | Friendly name shown in logs |
| `users[].customer_id` | No | II customer ID — auto-extracted from JWT if omitted |
| `ii_request_delay.min/max` | No | Throttle between API calls (seconds). Default: 1–3 |
| `cgt.api_url` | No | Soren API base URL |
| `cgt.api_key` | No | Soren long-lived API key (from Settings → API) |

### Choosing a start date

`start_date` controls how far back the tool fetches GBP transaction history for each account, and is also used as the default start for any non-GBP currency that doesn't have an entry in `currency_start_dates`. **When in doubt, set it earlier rather than later.**

- If it's too early, you'll download a few extra empty or irrelevant rows — no harm done.
- If it's too late, you'll permanently miss transactions that happened before it, which will produce incorrect CGT calculations.

A safe default is the date you opened the account (visible in your II account summary). If you're not sure, pick a date a year or two before you think you first traded. Re-downloading from an earlier start date is always possible — just delete the relevant files from `downloads/` and run again.

### Choosing currencies

`currencies` controls which currency transaction statements are downloaded for each account. Most II accounts only ever transact in GBP, but if you've bought US or other international shares you'll also have a USD (or other) statement. **When in doubt, include more currencies rather than fewer.**

- If you include a currency you've never transacted in, the downloaded file will just be empty — no harm done.
- If you omit a currency you have transacted in, those transactions will be missing entirely from your CGT calculations.

**Auto-detection:** you don't need to list foreign currencies manually. Each time the tool runs, it scans your downloaded GBP statement files for FX conversion rows (e.g. a row like `"9484 AUSTRALIAN DOLLAR .58 S Date 12/08/22"`) and automatically adds any newly found currencies to `account["currencies"]` with a derived start date (`first_conversion_date − 7 days`, but never earlier than `start_date`). The derived start dates are written into `currency_start_dates` in your config. You'll see a yellow log line for each auto-detected currency.

The setup wizard also does this during initial discovery, so if you used the wizard your currencies and `currency_start_dates` will already be populated.

To check which currencies you need manually, log into II, go to **My ii → Statements**, and see which currency tabs appear for each account. Common values are `GBP` and `USD`.

## Output structure

```
downloads/
  alice@example.com/
    1234567/                              ← account ID
      portfolio_2026-04-22.csv           ← today's holdings snapshot
      cash_2026-04-22.csv                ← today's cash balance
      transactions_GBP_2024.csv          ← full calendar year (locked, never re-downloaded)
      transactions_GBP_2025.csv
      transactions_GBP_2026-01-01_2026-04-22.csv   ← current-year partial (refreshed each run)
      corporate_actions/
        12345678_some-corp-action.pdf
        ...
    7654321/
      portfolio_2026-04-22.csv
      transactions_GBP_2023-06-01_2023-12-31.csv   ← mid-year start partial (historic, locked)
      transactions_GBP_2024.csv
      transactions_USD_2024.csv
      ...
```

## Re-run behaviour

| File type | Re-download? |
|-----------|-------------|
| Full calendar-year transaction files (e.g. `transactions_GBP_2024.csv`) | Never — locked once complete |
| Historic mid-year-start partials (e.g. `transactions_GBP_2022-06-01_2022-12-31.csv`) | Never |
| Current-year partial (e.g. `transactions_GBP_2026-01-01_2026-04-22.csv`) | Always — replaced with a fresh download up to today |
| Portfolio / cash snapshots | Always — fresh snapshot each run |
| Corporate action PDFs | Skipped if already downloaded (by filename) |

The current-year partial file is always replaced so that transactions made since the last run are captured. This is safe across the year-end boundary: a Dec 31 partial is replaced on Jan 1 as well.

## Push to Soren

The `--push` and `--push-only` flags upload downloaded files to a [Soren](https://www.getsoren.app) instance.

### CSV files (transactions, portfolio, cash)

1. The tool fetches your Soren account list and maps II account numbers automatically
2. Files already uploaded are skipped (by filename / valuation date)
3. The current-year transaction partial is always replaced with the freshest local version
4. Cash valuations already recorded in the UI don't block portfolio CSV uploads

### Corporate action PDFs

Corporate action PDFs are pushed to the Soren drafts queue for human review:

1. Existing drafts are checked by filename — already-queued files are skipped
2. The server also deduplicates by PDF hash (returns 409 if the same bytes were previously uploaded or approved)
3. Uploaded PDFs appear under **Settings → Corporate actions → Pending review** in the Soren UI, where you can review, tweak auto-parsed fields, and approve or reject each one

### Authentication

The Soren API key is read from (in order of precedence):

1. `CGT_TOKEN` environment variable
2. `cgt.api_key` in `config.yaml`
3. Interactive prompt

A long-lived API key from **Settings → API** in Soren is recommended so you don't need to paste a token each run.

## Interactive Investor API endpoints

All requests are authenticated with a short-lived Bearer JWT (~28 min) obtained via the browser. The base URL is `https://api-prod.ii.co.uk/enrolled/api`.

| # | Method | Path | Returns |
|---|--------|------|---------|
| 1 | GET | `/2/customers/{cid}/accounts/{aid}/portfolio/export` | Portfolio snapshot CSV |
| 2 | GET | `/2/customers/{cid}/accounts/{aid}/portfolio` | Cash balance (JSON) |
| 3 | GET | `/1/customers/{cid}/accounts/{aid}/statements/{ccy}?fromDate=…&toDate=…&sortBy=TRANSACTION_DATE&sortOrder=DESCENDING` | Transaction statement CSV |
| 4 | GET | `/1/customers/{cid}/accounts/{aid}/document-CORPORATE_ACTION_NOTIFICATIONS-summaries?pageNumber={n}&pageSize=50&sortField=PUBLISHED_DATE&sortType=DESCENDING` | Corporate action list (JSON, 1-indexed pagination) |
| 5 | GET | `/1/customers/{cid}/accounts/{aid}/documents/{did}` | Corporate action PDF (requires `accept: application/pdf`) |

**Variables:** `{cid}` = customer ID (auto-extracted from the JWT), `{aid}` = account ID, `{ccy}` = currency code (e.g. `GBP`), `{did}` = document ID from the summaries list.

> These endpoints are undocumented and unofficial. They work as of 2026 but may change without notice.

## Running tests

```bash
pytest test_ii_download.py -v
```

The test suite covers all pure-logic functions (JWT decoding, date chunking, filename parsing, deduplication logic, year-boundary edge cases). Network calls are not tested.

## Security

- `config.yaml` is gitignored — never commit it
- The `downloads/` directory contains your financial data — also gitignored
- Bearer tokens are short-lived (~28 min) and are never written to disk
- The Soren API key is stored only in `config.yaml`

## License

MIT
