# ii-csv-downloader

A tool to download your data from [Interactive Investor](https://www.ii.co.uk/) and push it to a [tradeCGT](https://tradecgt.com) instance for CGT calculations.

It comes with both a **Streamlit web UI** (recommended) and a **CLI** for scripting / automation.

## What it downloads

| Data | Format | Notes |
|------|--------|-------|
| Portfolio snapshots | CSV | Current holdings, one file per run |
| Cash balances | CSV | Cash position per account |
| Transaction statements | CSV | Chunked by calendar year, per currency |
| Corporate action notifications | PDF | Downloaded from your II document history |

## Setup

**Requirements:** Python 3.10+

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml
```

Then edit `config.yaml` with your details — see [Config format](#config-format) below.

`config.yaml` is gitignored and should never be committed.

## Getting an II Bearer token

The II API requires an authenticated session token. The easiest way to get one is via the **bookmarklet** — a one-click button you add to your browser's bookmarks bar that copies the token for you.

When you first run the UI (`streamlit run ui.py`) it walks you through bookmarklet setup automatically.

Alternatively, you can get a token manually:

1. Log into [ii.co.uk](https://www.ii.co.uk/) in your browser
2. Open DevTools → **Network** tab
3. Reload any page (e.g. your portfolio)
4. Find any request to `api-prod.ii.co.uk`
5. Copy the `Authorization: Bearer eyJ…` header value

Tokens expire after ~28 minutes.

## Web UI

```bash
streamlit run ui.py
```

The UI guides you through initial setup and lets you:

- Paste II Bearer tokens for each configured user
- Choose which account(s) to download
- Optionally push to tradeCGT immediately after downloading
- View live output and a success/failure summary

## CLI usage

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

# Download and push to tradeCGT in one step
python ii_download.py --push

# Push existing downloads to tradeCGT (no II download)
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

# tradeCGT integration (only needed for --push / --push-only)
cgt:
  api_url: "https://your.tradecgt.instance"
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
| `users[].accounts[].name` | No | Friendly name shown in logs |
| `users[].customer_id` | No | II customer ID — auto-extracted from JWT if omitted |
| `ii_request_delay.min/max` | No | Throttle between API calls (seconds). Default: 1–3 |
| `cgt.api_url` | No | tradeCGT API base URL |
| `cgt.api_key` | No | tradeCGT long-lived API key (from Settings → API) |

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

## Push to tradeCGT

The `--push` and `--push-only` flags upload downloaded files to a [tradeCGT](https://tradecgt.com) instance.

### CSV files (transactions, portfolio, cash)

1. The tool fetches your tradeCGT account list and maps II account numbers automatically
2. Files already uploaded are skipped (by filename / valuation date)
3. The current-year transaction partial is always replaced with the freshest local version
4. Cash valuations already recorded in the UI don't block portfolio CSV uploads

### Corporate action PDFs

Corporate action PDFs are pushed to the tradeCGT drafts queue for human review:

1. Existing drafts are checked by filename — already-queued files are skipped
2. The server also deduplicates by PDF hash (returns 409 if the same bytes were previously uploaded or approved)
3. Uploaded PDFs appear under **Settings → Corporate actions → Pending review** in the tradeCGT UI, where you can review, tweak auto-parsed fields, and approve or reject each one

### Authentication

The tradeCGT API key is read from (in order of precedence):

1. `CGT_TOKEN` environment variable
2. `cgt.api_key` in `config.yaml`
3. Interactive prompt

A long-lived API key from **Settings → API** in tradeCGT is recommended so you don't need to paste a token each run.

## Running tests

```bash
pytest test_ii_download.py -v
```

The test suite covers all pure-logic functions (JWT decoding, date chunking, filename parsing, deduplication logic, year-boundary edge cases). Network calls are not tested.

## Security

- `config.yaml` is gitignored — never commit it
- The `downloads/` directory contains your financial data — also gitignored
- Bearer tokens are short-lived (~28 min) and are never written to disk
- The tradeCGT API key is stored only in `config.yaml`

## License

MIT
