# ii-csv-downloader

CLI tool to download CSV exports from [Interactive Investor](https://www.ii.co.uk/) — portfolio valuations and transaction statements — and optionally push them to a [tradeCGT](https://github.com/idletimes/trade-cgt) API.

## Features

- **Portfolio snapshots** — current holdings as CSV, one per account
- **Transaction statements** — historic statements by currency, chunked into calendar-year files
- **Multi-user** — supports multiple II logins in one config
- **Incremental** — tracks what's already downloaded; only fetches new data
- **Current-year refresh** — re-downloads the current year's partial file on each run to capture recent transactions
- **Push to tradeCGT** — upload downloaded CSVs to the tradeCGT API, with duplicate detection
- **Rate limiting** — configurable random delay between II API requests

## Setup

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml
```

Edit `config.yaml` with your details (see below for format).

## Getting a Bearer token

The II API requires an authenticated session token. To get one:

1. Log into [ii.co.uk](https://www.ii.co.uk/) in your browser
2. Open DevTools (F12) → **Network** tab
3. Navigate to any page (e.g. your portfolio)
4. Find a request to `api-prod.ii.co.uk`
5. Copy the `Authorization` header value (the `Bearer eyJ...` part)

Tokens expire after ~28 minutes.

## Usage

```bash
# Download everything (prompts for token per user)
python ii_download.py

# Single user (substring match on email)
python ii_download.py --user harry

# Portfolio valuations only
python ii_download.py --portfolio

# Transaction statements only
python ii_download.py --transactions

# Specific account
python ii_download.py --user harry --account 0970887

# Pass token directly (single user only)
python ii_download.py --user harry --token "eyJhbG..."

# Download and push to tradeCGT
python ii_download.py --push

# Push existing downloads to tradeCGT (no II download)
python ii_download.py --push-only

# Push a specific account only
python ii_download.py --push-only --account 0970887
```

## Config format

```yaml
# Random delay (seconds) between II API requests to avoid rate limiting
ii_request_delay:
  min: 1
  max: 3

# tradeCGT API for pushing uploaded files
cgt:
  api_url: "http://localhost:8000"

users:
  - email: "you@example.com"
    customer_id: "00000000000"
    accounts:
      - id: "1234567"
        name: "ISA"
        start_date: "2024-01-01"
        currencies: ["GBP"]

      - id: "7654321"
        name: "Trading"
        start_date: "2023-06-01"
        currencies: ["GBP", "USD"]
```

- **customer_id** — your II customer number (visible in API URLs)
- **start_date** — earliest date to pull transactions from
- **currencies** — which currency statements to download per account
- **ii_request_delay** — random delay range (seconds) between II API calls; set `max: 0` to disable
- **cgt.api_url** — tradeCGT API base URL (only needed for `--push`)

## Output structure

```
downloads/
  you@example.com/
    1234567/
      portfolio_2026-02-27.csv
      transactions_GBP_2024.csv
      transactions_GBP_2025.csv
      transactions_GBP_2026-01-01_2026-02-27.csv
    7654321/
      portfolio_2026-02-27.csv
      transactions_GBP_2023-06-01_2023-12-31.csv
      transactions_GBP_2024.csv
      transactions_GBP_2025.csv
      transactions_GBP_2026-01-01_2026-02-27.csv
      transactions_USD_2023-06-01_2023-12-31.csv
      transactions_USD_2024.csv
      ...
```

## Re-run behaviour

- **Full calendar year files** (e.g. `transactions_GBP_2024.csv`) are never re-downloaded
- **Current year partials** (e.g. `transactions_GBP_2026-01-01_2026-02-15.csv`) are replaced with a fresh download up to today
- **Portfolio files** are always downloaded fresh (snapshot of current holdings)

## Push to tradeCGT

The `--push` and `--push-only` flags upload downloaded CSVs to a tradeCGT API instance. The tool:

1. Fetches the account list from tradeCGT and auto-maps by II account number
2. Checks what's already been uploaded (by valuation date or filename)
3. Uploads only new files

You'll be prompted for a tradeCGT Bearer token (separate from the II token).
