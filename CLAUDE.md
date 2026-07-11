# CLAUDE.md

Guidance for Claude Code when working in this repo.

## What this is

A tool that scrapes an authenticated user's Interactive Investor (ii) account data
via ii's private web API and saves it as CSVs, with an optional push to Soren (a
CGT-reporting app). Two front-ends over the same logic:

- **`ii_download.py`** — the CLI and all the actual API/HTTP logic. Single module,
  no package structure.
- **`ui.py`** — a Streamlit UI that shells out to `ii_download.py`. Contains **no
  direct HTTP**; all ii/Soren calls live in `ii_download.py`.
- **`test_ii_download.py`** — unit tests (currency detection, upload de-dup, etc.).
  No HTTP fixtures — nothing captures real ii responses.

## Running it

```bash
pip install -r requirements.txt          # requests, pyyaml, streamlit

streamlit run ui.py                       # UI
python ii_download.py                     # CLI, all users in config.yaml
python ii_download.py --user alice        # filter by email substring / customer id
python ii_download.py --portfolio         # valuations only
python ii_download.py --transactions      # statements only
python ii_download.py --account 1234567   # one account
python ii_download.py --push              # download then push to Soren
python ii_download.py --discover          # auto-detect start dates + currencies

python -m pytest test_ii_download.py      # tests
```

`Start.command` (macOS) / `Start.bat` (Windows) are double-click launchers for the UI.

## Auth

- ii auth is a short-lived **Bearer JWT** the user pastes in (obtained from a logged-in
  ii web session). ~28-minute lifetime. `get_token()` decodes/validates expiry;
  `decode_jwt_customer_id()` pulls the customer id from the token so `customer_id` is
  usually omitted from config.
- Shared request headers come from `make_headers()`: `authorization: Bearer <token>`,
  `ii-consumer-type: web.secure`, plus `origin`/`referer` of `https://www.ii.co.uk`.
- We cannot obtain a token programmatically — the user must supply one.

## ii API endpoints

Base for most calls: `https://api-prod.ii.co.uk/enrolled/api`. The endpoint reference
comment block lives at the top of `ii_download.py` (~line 24). Summary:

| Purpose | Method / path |
|---|---|
| Account list (discovery) | `GET /1/customers/{cid}/accounts` |
| Portfolio snapshot CSV | `GET /2/customers/{cid}/accounts/{aid}/portfolio/export` |
| Cash balance (aggregate) | `GET /2/customers/{cid}/accounts/{aid}/portfolio` → `total.totalCashValue` |
| Transaction statements | `GET /1/customers/{cid}/accounts/{aid}/statements/{ccy}?fromDate=&toDate=` (max 24 months) |
| Corporate action summaries | `GET /1/customers/{cid}/accounts/{aid}/document-CORPORATE_ACTION_NOTIFICATIONS-summaries` (pagination 1-indexed) |
| Corporate action PDF | `GET /1/customers/{cid}/accounts/{aid}/documents/{did}` (accept: application/pdf) |

### Per-currency cash balances (not yet wired into the code)

There is a richer cash endpoint on a **different base path** (`/order/api`, not
`/enrolled/api`):

```
GET https://api-prod.ii.co.uk/order/api/1/customers/{cid}/accounts/{aid}/cash-balances
    ?preferredCurrency=GBP&settlementCurrency=GBP
```

Response shape:

```json
{
  "preferredCurrency": { "code": "GBP", "prefix": "£" },
  "totalInPreferredCurrency": 915.31,
  "results": [
    { "currency": {"code":"GBP"}, "current": 476.12, "pending": 0.0,
      "total": 476.12, "totalInPreferredCurrency": 476.12, "availableToFx": 476.12 }
  ]
}
```

`results[]` is one entry per **native** currency held — `total` is the native balance
(`current + pending`); `totalInPreferredCurrency` is that balance converted.

Findings from live probing:
- `preferredCurrency` **only** changes the conversion column and the top-level total.
  Native `current`/`pending`/`total`/`availableToFx` are identical regardless.
- `settlementCurrency` had **no observable effect** on the response — it's an
  order/settlement param, irrelevant for reading balances.
- Works uniformly across account types (Trading, ISA, SIPP, Junior ISA).
- Decision so far: keep `preferredCurrency=GBP` hardcoded — the native balances (the
  thing we want) don't depend on it, and everything downstream is GBP. Not worth a
  user-facing reporting-currency setting.

The current `download_cash()` still uses the aggregate `/portfolio` endpoint and writes
a single `Cash_GBP` value. Migrating it to `cash-balances` (one row per currency) is a
**pending** task — do not assume it's done. The CSV format for that is intentionally not
yet decided.

## Config

`config.yaml` (gitignored; see `config.example.yaml`) holds `ii_request_delay`, optional
`cgt` (Soren) settings, and a `users[]` list. Each user has `email` and `accounts[]`,
where each account has `id`, `name`, `start_date`, `currencies`, and optionally
`currency_start_dates`. `--discover` populates start dates / currencies automatically by
scanning GBP statement history for FX-conversion rows (see `_GBP_CCY_PATTERNS` and
`detect_currencies_from_gbp_*`).

## Conventions

- Be conservative with the ii API: it's private/undocumented and rate-limited. Keep the
  `ii_throttle()` random delay between calls; don't hammer endpoints in loops.
- Never commit real tokens, `config.yaml`, or downloaded account data. `downloads/` and
  `config.yaml` are gitignored.
- When exploring a new endpoint, save raw responses to the scratchpad, not the repo.
