#!/usr/bin/env python3
"""CLI tool to download CSV files from Interactive Investor (ii.co.uk)."""

import argparse
import base64
import getpass
import json
import os
import random
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
import yaml

BASE_URL = "https://api-prod.ii.co.uk/enrolled/api"
DOWNLOADS_DIR = Path("downloads")
CONFIG_FILE = Path("config.yaml")

# ── Interactive Investor API endpoints used ───────────────────────────────────
#
# All requests require:
#   Authorization: Bearer <token>   (short-lived JWT, ~28 min, obtained via browser)
#   accept: application/json        (except the PDF download, which needs application/pdf)
#
# Variables:
#   {cid}  — customer ID (extracted from JWT claim https://onestack.co.uk/cid)
#   {aid}  — account ID (e.g. "0970887")
#   {ccy}  — currency code (e.g. "GBP", "USD")
#   {did}  — document ID (integer, from the summaries list)
#
# 1. Portfolio snapshot (CSV)
#    GET /2/customers/{cid}/accounts/{aid}/portfolio/export
#    → CSV of current holdings
#
# 2. Cash balance (JSON)
#    GET /2/customers/{cid}/accounts/{aid}/portfolio
#    → JSON; cash extracted from response["account"]["totalCashValue"] / ["currency"]
#
# 3. Transaction statement (CSV)
#    GET /1/customers/{cid}/accounts/{aid}/statements/{ccy}
#        ?fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD
#        &sortBy=TRANSACTION_DATE&sortOrder=DESCENDING
#    → CSV of transactions for the given currency and date range
#
# 4. Corporate action notification summaries (JSON, paginated)
#    GET /1/customers/{cid}/accounts/{aid}/document-CORPORATE_ACTION_NOTIFICATIONS-summaries
#        ?pageNumber={n}&pageSize=50&sortField=PUBLISHED_DATE&sortType=DESCENDING
#    → JSON; pagination is 1-indexed (pageNumber=0 returns 400)
#    → Each item has: documentId, publishedDate, company, …
#
# 5. Corporate action PDF download
#    GET /1/customers/{cid}/accounts/{aid}/documents/{did}
#    Headers: accept: application/pdf   ← must be pdf, not json (json returns 406)
#    → Raw PDF bytes
#
# ─────────────────────────────────────────────────────────────────────────────

# ANSI colours
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"


def colour(text, code):
    if sys.stdout.isatty():
        return f"{code}{text}{RESET}"
    return text


def load_config(path=CONFIG_FILE):
    if not path.exists():
        print(colour(f"Config file not found: {path}", RED))
        print("Create a config.yaml — see README for format.")
        sys.exit(1)
    with open(path) as f:
        return yaml.safe_load(f)


def decode_jwt_payload(token):
    """Decode JWT payload without verification. Returns dict or None."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return None


def decode_jwt_exp(token):
    """Decode JWT expiry without verification."""
    data = decode_jwt_payload(token)
    try:
        return datetime.fromtimestamp(data["exp"])
    except Exception:
        return None


def decode_jwt_customer_id(token):
    """Extract II customer ID from JWT (https://onestack.co.uk/cid claim)."""
    data = decode_jwt_payload(token)
    if data:
        return data.get("https://onestack.co.uk/cid")
    return None


def get_token(email, token_arg=None):
    """Get bearer token from arg or prompt."""
    token = token_arg
    if not token:
        token = getpass.getpass(f"Paste Bearer token for {email}: ")
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:]

    exp = decode_jwt_exp(token)
    if exp:
        if exp < datetime.now():
            print(colour(f"  Token expired at {exp.strftime('%H:%M:%S')} — please get a fresh one.", RED))
            sys.exit(1)
        remaining = (exp - datetime.now()).total_seconds()
        mins = int(remaining // 60)
        print(colour(f"  Token valid for ~{mins} minutes (expires {exp.strftime('%H:%M:%S')})", GREEN))
    else:
        print(colour("  Invalid token — could not be decoded. Please paste a fresh token.", RED))
        sys.exit(1)

    return token


def ii_throttle(config):
    """Sleep for a random delay between II API calls."""
    delay = config.get("ii_request_delay", {})
    min_s = delay.get("min", 1)
    max_s = delay.get("max", 3)
    if max_s > 0:
        wait = random.uniform(min_s, max_s)
        time.sleep(wait)


def make_headers(token):
    return {
        "accept": "text/csv",
        "authorization": f"Bearer {token}",
        "ii-consumer-type": "web.secure",
        "origin": "https://www.ii.co.uk",
        "referer": "https://www.ii.co.uk/",
    }


def download_portfolio(customer_id, account, token, user_dir, config):
    """Download current portfolio valuation CSV."""
    account_id = account["id"]
    account_name = account.get("name", account_id)
    today = date.today().isoformat()

    out_dir = user_dir / account_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"portfolio_{today}.csv"

    url = f"{BASE_URL}/2/customers/{customer_id}/accounts/{account_id}/portfolio/export"
    print(f"  Downloading portfolio for {account_name} ({account_id})...", end=" ")

    ii_throttle(config)
    resp = requests.get(url, headers=make_headers(token))
    if resp.status_code in (401, 403):
        print(colour("AUTH FAILED — token expired or invalid", RED))
        return "error"
    if resp.status_code != 200:
        print(colour(f"HTTP {resp.status_code}", RED))
        print(colour(f"    Response: {resp.text[:500]}", RED))
        return "error"

    out_file.write_text(resp.content.decode('utf-8-sig').replace('\ufeff', ''), encoding='utf-8')
    print(colour(f"saved → {out_file}", GREEN))
    return "downloaded"


def download_cash(customer_id, account, token, user_dir, config):
    """Download cash balance from the portfolio JSON endpoint and save as cash_YYYY-MM-DD.csv."""
    account_id = account["id"]
    account_name = account.get("name", account_id)
    today = date.today().isoformat()

    out_dir = user_dir / account_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"cash_{today}.csv"

    url = f"{BASE_URL}/2/customers/{customer_id}/accounts/{account_id}/portfolio"
    print(f"  Downloading cash balance for {account_name} ({account_id})...", end=" ")

    ii_throttle(config)
    headers = {**make_headers(token), "accept": "application/json"}
    resp = requests.get(url, headers=headers)
    if resp.status_code in (401, 403):
        print(colour("AUTH FAILED — token expired or invalid", RED))
        return "error"
    if resp.status_code != 200:
        print(colour(f"HTTP {resp.status_code}", RED))
        print(colour(f"    Response: {resp.text[:500]}", RED))
        return "error"

    total = resp.json().get("total", {})
    cash_value = total.get("totalCashValue")
    currency = total.get("currency", {}).get("code", "GBP")

    if cash_value is None:
        print(colour("no cash data in response", YELLOW))
        return "error"

    out_file.write_text(f"Cash_{currency}\n{cash_value}\n", encoding="utf-8")
    print(colour(f"saved → {out_file}  ({currency} {cash_value})", GREEN))
    return "downloaded"


def build_year_chunks(from_date, to_date):
    """Split a date range into calendar-year-aligned chunks.

    Historic years:  from_date (or Jan 1) → Dec 31
    Current year:    Jan 1 (or from_date) → today
    """
    chunks = []
    current = from_date

    while current < to_date:
        if current.year < to_date.year:
            # Historic year: run to Dec 31
            year_end = date(current.year, 12, 31)
            chunks.append((current, year_end))
            current = date(current.year + 1, 1, 1)
        else:
            # Current (partial) year: run to today
            chunks.append((current, to_date))
            current = to_date

    return chunks


def transaction_filename(ccy, chunk_from, chunk_to):
    """Generate a clear filename for a transaction chunk.

    Historic full year:   transactions_GBP_2024.csv
    Historic partial:     transactions_GBP_2022-06-01_2022-12-31.csv
    Current year:         transactions_GBP_2026-01-01_2026-02-27.csv
    """
    is_full_year = (
        chunk_from.month == 1 and chunk_from.day == 1
        and chunk_to.month == 12 and chunk_to.day == 31
    )
    if is_full_year:
        return f"transactions_{ccy}_{chunk_from.year}.csv"
    else:
        return f"transactions_{ccy}_{chunk_from.isoformat()}_{chunk_to.isoformat()}.csv"


def find_transaction_files(account_dir, ccy):
    """Find all transaction files for a currency, returning (path, start, end, is_full_year).

    Handles both naming formats:
      transactions_GBP_2024.csv                    → full year
      transactions_GBP_2024-01-01_2024-12-31.csv   → date range
    """
    files = []
    if not account_dir.exists():
        return files

    range_pattern = re.compile(
        rf"^transactions_{ccy}_(\d{{4}}-\d{{2}}-\d{{2}})_(\d{{4}}-\d{{2}}-\d{{2}})\.csv$"
    )
    year_pattern = re.compile(
        rf"^transactions_{ccy}_(\d{{4}})\.csv$"
    )

    for f in account_dir.iterdir():
        m = range_pattern.match(f.name)
        if m:
            start = date.fromisoformat(m.group(1))
            end = date.fromisoformat(m.group(2))
            files.append((f, start, end, False))
            continue
        m = year_pattern.match(f.name)
        if m:
            year = int(m.group(1))
            files.append((f, date(year, 1, 1), date(year, 12, 31), True))

    return files


def download_transactions(customer_id, account, token, user_dir, config):
    """Download transaction statement CSVs for each currency.

    Re-run logic:
    - Full-year files (historic, complete) are never re-downloaded.
    - Partial current-year files are deleted and re-fetched up to the cutoff date,
      so transactions that posted after the last run are captured.
    """
    account_id = account["id"]
    account_name = account.get("name", account_id)
    currencies = account.get("currencies", ["GBP"])
    start_date = account.get("start_date", "2024-01-01")
    today = date.today()
    # Download up to today so today's transactions match today's portfolio snapshot.
    # The current-year partial is always replaced on the next run, so there's no
    # risk of a permanently-stale file (including across the Dec 31 → Jan 1 boundary).
    cutoff = config.get("_to_date", today)
    results = []

    out_dir = user_dir / account_id
    out_dir.mkdir(parents=True, exist_ok=True)

    for ccy in currencies:
        existing = find_transaction_files(out_dir, ccy)

        # Find the latest full-year end date (these are locked in)
        latest_complete = None
        for _, _, end, is_full in existing:
            if is_full:
                if latest_complete is None or end > latest_complete:
                    latest_complete = end

        # Delete any current-year partial so it gets re-fetched as a single unified
        # file up to today.  Also catches the Dec 31 → Jan 1 boundary: on Jan 1
        # the Dec 31 partial from last year is refreshed even though its year
        # differs from today's.  Older historic partials (e.g. a mid-year start
        # in 2022 ending 2022-12-31) are safely left alone.
        for fpath, start, end, is_full in existing:
            if not is_full and (end.year == cutoff.year or end == date(cutoff.year - 1, 12, 31)):
                print(f"  Transactions {account_name}/{ccy}: replacing {fpath.name} (refreshing to {cutoff.isoformat()})")
                fpath.unlink()

        # Re-scan after cleanup to determine where to start from
        existing = find_transaction_files(out_dir, ccy)
        latest_end = None
        for _, _, end, _ in existing:
            if latest_end is None or end > latest_end:
                latest_end = end

        if latest_end:
            from_date = latest_end + timedelta(days=1)
        else:
            from_date = date.fromisoformat(start_date)

        if from_date >= cutoff:
            print(f"  Transactions {account_name}/{ccy}: " + colour("up to date", YELLOW))
            results.append("skipped")
            continue

        chunks = build_year_chunks(from_date, cutoff)
        ccy_ok = True

        for chunk_from, chunk_to in chunks:
            fname = transaction_filename(ccy, chunk_from, chunk_to)
            out_file = out_dir / fname

            # Skip if file already exists (e.g. full-year file from previous run)
            if out_file.exists():
                print(f"  Transactions {account_name}/{ccy} ({fname}): " + colour("exists", YELLOW))
                continue

            url = (
                f"{BASE_URL}/1/customers/{customer_id}/accounts/{account_id}"
                f"/statements/{ccy}?fromDate={chunk_from.isoformat()}&toDate={chunk_to.isoformat()}"
                f"&sortBy=TRANSACTION_DATE&sortOrder=DESCENDING"
            )
            print(f"  Transactions {account_name}/{ccy} ({fname})...", end=" ")

            ii_throttle(config)
            resp = requests.get(url, headers=make_headers(token))
            if resp.status_code in (401, 403):
                print(colour("AUTH FAILED", RED))
                ccy_ok = False
                break
            if resp.status_code != 200:
                print(colour(f"HTTP {resp.status_code}", RED))
                print(colour(f"    Response: {resp.text[:500]}", RED))
                ccy_ok = False
                break

            out_file.write_text(resp.content.decode('utf-8-sig').replace('\ufeff', ''), encoding='utf-8')
            print(colour(f"saved → {out_file}", GREEN))

        results.append("downloaded" if ccy_ok else "error")

    return results


def download_corporate_actions(customer_id, account, token, user_dir, config):
    """Download corporate action notification PDFs for an account.

    Saves to downloads/<email>/<account_id>/corporate_actions/.
    Already-downloaded files are skipped; new ones are fetched.
    """
    account_id = account["id"]
    account_name = account.get("name", account_id)

    out_dir = user_dir / account_id / "corporate_actions"
    out_dir.mkdir(parents=True, exist_ok=True)

    list_headers = {**make_headers(token), "accept": "application/json"}
    pdf_headers  = {**make_headers(token), "accept": "application/pdf"}

    # Fetch all pages (1-indexed — pageNumber=0 returns 400)
    all_docs = []
    page = 1
    while True:
        url = (
            f"{BASE_URL}/1/customers/{customer_id}/accounts/{account_id}"
            f"/document-CORPORATE_ACTION_NOTIFICATIONS-summaries"
            f"?pageNumber={page}&pageSize=50&sortField=PUBLISHED_DATE&sortType=DESCENDING"
        )
        ii_throttle(config)
        resp = requests.get(url, headers=list_headers)
        if resp.status_code in (401, 403):
            print(colour(f"  Corporate actions {account_name}: AUTH FAILED", RED))
            return "error"
        if resp.status_code != 200:
            print(colour(f"  Corporate actions {account_name}: HTTP {resp.status_code}", RED))
            return "error"
        data = resp.json()
        all_docs.extend(data.get("results", []))
        if page >= data.get("totalNumberOfPages", 1):
            break
        page += 1

    if not all_docs:
        print(f"  Corporate actions {account_name}: " + colour("none found", YELLOW))
        return "skipped"

    new_count = 0
    for doc in all_docs:
        doc_id  = doc["documentId"]
        pub     = doc.get("publishedDate", "unknown")
        company = re.sub(r"[^\w]", "_", doc.get("company", "unknown")).strip("_")[:60]
        fname   = f"{pub}_{doc_id}_{company}.pdf"
        out_file = out_dir / fname

        if out_file.exists():
            continue

        url = f"{BASE_URL}/1/customers/{customer_id}/accounts/{account_id}/documents/{doc_id}"
        print(f"  Corporate actions {account_name} ({fname})...", end=" ")
        ii_throttle(config)
        resp = requests.get(url, headers=pdf_headers)
        if resp.status_code in (401, 403):
            print(colour("AUTH FAILED", RED))
            return "error"
        if resp.status_code != 200:
            print(colour(f"HTTP {resp.status_code}", RED))
            continue

        out_file.write_bytes(resp.content)
        print(colour(f"saved → {out_file}", GREEN))
        new_count += 1

    if new_count == 0:
        print(f"  Corporate actions {account_name}: " + colour("up to date", YELLOW))
        return "skipped"
    return "downloaded"


# ── Push to Soren ──────────────────────────────────────────────────────

def cgt_fetch_account_map(api_url, cgt_token):
    """Fetch Soren accounts and build accountNumber → cgt_id mapping."""
    resp = requests.get(
        f"{api_url}/api/accounts",
        headers={"Authorization": f"Bearer {cgt_token}"},
    )
    if resp.status_code != 200:
        print(colour(f"  CGT API error listing accounts: HTTP {resp.status_code}", RED))
        print(colour(f"    {resp.text[:500]}", RED))
        return None
    accounts = resp.json()
    return {a["accountNumber"]: a["id"] for a in accounts}


def cgt_fetch_uploaded_files(api_url, cgt_token, cgt_account_id, debug=False):
    """Fetch list of already-uploaded files for a Soren account."""
    resp = requests.get(
        f"{api_url}/api/accounts/{cgt_account_id}/files",
        headers={"Authorization": f"Bearer {cgt_token}"},
    )
    if resp.status_code != 200:
        return {"transactions": [], "valuations": []}
    data = resp.json()
    if debug:
        print(f"    [debug] GET /api/accounts/{cgt_account_id}/files → {json.dumps(data, indent=2)}")
    return data


def cgt_should_skip_transaction(file_name, uploaded_transactions):
    """Check if a transaction file has already been uploaded (by filename)."""
    for t in uploaded_transactions:
        if t.get("file_name") == file_name:
            return True
    return False


def is_current_year_partial(filename):
    """True if this is a current-year partial transaction file (not a full-year file)."""
    m = re.match(r"^transactions_[A-Z]+_\d{4}-\d{2}-\d{2}_(\d{4})-\d{2}-\d{2}\.csv$", filename)
    return bool(m and int(m.group(1)) == date.today().year)


def ccy_from_tx_filename(filename):
    """Extract currency code from a transaction filename."""
    m = re.match(r"^transactions_([A-Z]+)_", filename)
    return m.group(1) if m else None


def cgt_fetch_corporate_action_drafts(api_url, cgt_token):
    """Return the list of pending corporate-action drafts for this user."""
    resp = requests.get(
        f"{api_url}/api/corporate-action-drafts",
        headers={"Authorization": f"Bearer {cgt_token}"},
    )
    if resp.status_code == 200:
        return resp.json()
    return []


def cgt_upload_corporate_action_pdf(api_url, cgt_token, file_path):
    """Upload a corporate-action PDF to the Soren drafts queue.

    Returns:
        'uploaded'  – 201 Created
        'duplicate' – 409 (exact bytes already present; treat as success)
        'error'     – anything else
    """
    with open(file_path, "rb") as f:
        resp = requests.post(
            f"{api_url}/api/corporate-action-drafts",
            headers={"Authorization": f"Bearer {cgt_token}"},
            files={"file": (file_path.name, f, "application/pdf")},
            data={"source": "api"},
        )
    if resp.status_code == 201:
        return "uploaded"
    if resp.status_code == 409:
        return "duplicate"
    print(colour(f"HTTP {resp.status_code}", RED))
    print(colour(f"    {resp.text[:500]}", RED))
    return "error"


def cgt_delete_file(api_url, cgt_token, cgt_account_id, file_id):
    """Delete a file from the Soren API by its ID."""
    resp = requests.delete(
        f"{api_url}/api/accounts/{cgt_account_id}/files/{file_id}",
        headers={"Authorization": f"Bearer {cgt_token}"},
    )
    return resp.status_code in (200, 204)


def cgt_should_skip_valuation(valuation_date_str, uploaded_valuations):
    """Check if an investments valuation for this date already exists.

    Ignores cash valuations (manually entered via UI) — only investments-type
    uploads should block re-uploading a portfolio CSV.
    """
    for v in uploaded_valuations:
        if v.get("valuation_type") == "investments" and v.get("valuation_date") == valuation_date_str:
            return True
    return False


def cgt_upload_file(api_url, cgt_token, cgt_account_id, file_path, file_type, valuation_date=None):
    """Upload a CSV file to the Soren API."""
    data = {"file_type": file_type}
    if valuation_date:
        data["valuation_date"] = valuation_date

    content = file_path.read_bytes().replace(b'\xef\xbb\xbf', b'')
    resp = requests.post(
        f"{api_url}/api/accounts/{cgt_account_id}/files",
        headers={"Authorization": f"Bearer {cgt_token}"},
        data=data,
        files={"upload": (file_path.name, content, "text/csv")},
    )

    if resp.status_code in (200, 201):
        return True
    else:
        print(colour(f"HTTP {resp.status_code}", RED))
        print(colour(f"    {resp.text[:500]}", RED))
        return False


def push_to_cgt(config, account_filter=None, user_emails=None, debug=False):
    """Push downloaded CSV files to the Soren API."""
    cgt_config = config.get("cgt", {})
    api_url = cgt_config.get("api_url")
    if not api_url:
        print(colour("No cgt.api_url in config — cannot push.", RED))
        return

    cgt_token = (
        os.environ.get("CGT_TOKEN")
        or cgt_config.get("api_key")
        or getpass.getpass("Paste Soren Bearer token: ").strip()
    )
    if cgt_token.lower().startswith("bearer "):
        cgt_token = cgt_token[7:]

    print()
    print(colour(BOLD + "Fetching Soren account mapping..." + RESET, BOLD))
    account_map = cgt_fetch_account_map(api_url, cgt_token)
    if account_map is None:
        return

    summary = []

    # Walk all user download directories
    if not DOWNLOADS_DIR.exists():
        print(colour("No downloads directory found — download first.", RED))
        return

    for user_dir in sorted(DOWNLOADS_DIR.iterdir()):
        if not user_dir.is_dir():
            continue
        if user_emails is not None and user_dir.name not in user_emails:
            continue

        print(colour(f"\n{'='*60}", BOLD))
        print(colour(f" Pushing: {user_dir.name}", BOLD))
        print(colour(f"{'='*60}", BOLD))

        # Fetch corporate-action drafts once per user (endpoint is user-scoped).
        # We track by filename so we never re-upload a PDF that's already queued
        # or was already approved (409 byte-hash check handles the latter).
        existing_draft_names = {
            d.get("pdfFileName") for d in cgt_fetch_corporate_action_drafts(api_url, cgt_token)
        }

        for account_dir in sorted(user_dir.iterdir()):
            if not account_dir.is_dir():
                continue

            ii_account_id = account_dir.name
            if account_filter and ii_account_id != account_filter:
                continue

            cgt_id = account_map.get(ii_account_id)
            if cgt_id is None:
                print(colour(f"  Account {ii_account_id}: no matching Soren account — skipping", YELLOW))
                continue

            # Fetch what's already uploaded
            uploaded = cgt_fetch_uploaded_files(api_url, cgt_token, cgt_id, debug=debug)
            uploaded_tx = uploaded.get("transactions", [])
            uploaded_val = uploaded.get("valuations", [])

            # Push transactions first (securities get richer info from transaction data)
            for csv_file in sorted(account_dir.glob("transactions_*.csv")):
                fname = csv_file.name

                # Skip header-only files (no transaction data)
                lines = csv_file.read_text().strip().splitlines()
                if len(lines) <= 1:
                    print(f"  {ii_account_id}/{fname}: " + colour("skipping — no data rows (header only)", YELLOW))
                    summary.append(("Push transactions", f"{ii_account_id}/{fname}", "skipped", "header only"))
                    continue

                if is_current_year_partial(fname):
                    # Delete any stale current-year partials for this currency from Soren,
                    # then upload unconditionally — the local file is always the freshest version.
                    # Iterate over a copy and remove deleted entries so a second current-year
                    # partial for the same currency doesn't trigger a double-delete.
                    ccy = ccy_from_tx_filename(fname)
                    for tx in list(uploaded_tx):
                        tx_fname = tx.get("file_name", "")
                        if is_current_year_partial(tx_fname) and ccy_from_tx_filename(tx_fname) == ccy:
                            print(f"  {ii_account_id}/{tx_fname}: " + colour("deleting stale partial from Soren...", YELLOW), end=" ")
                            if cgt_delete_file(api_url, cgt_token, cgt_id, tx["id"]):
                                print(colour("deleted", GREEN))
                                summary.append(("Push transactions", f"{ii_account_id}/{tx_fname}", "deleted"))
                                uploaded_tx.remove(tx)
                            else:
                                print(colour("delete failed", RED))
                                summary.append(("Push transactions", f"{ii_account_id}/{tx_fname}", "error"))
                else:
                    if cgt_should_skip_transaction(fname, uploaded_tx):
                        print(f"  {ii_account_id}/{fname}: " + colour("already uploaded", YELLOW))
                        summary.append(("Push transactions", f"{ii_account_id}/{fname}", "skipped", "already uploaded"))
                        continue

                print(f"  {ii_account_id}/{fname}...", end=" ")
                if cgt_upload_file(api_url, cgt_token, cgt_id, csv_file, "transactions"):
                    print(colour("pushed", GREEN))
                    summary.append(("Push transactions", f"{ii_account_id}/{fname}", "pushed"))
                else:
                    summary.append(("Push transactions", f"{ii_account_id}/{fname}", "error"))

            # Then push cash balances
            for csv_file in sorted(account_dir.glob("cash_*.csv")):
                fname = csv_file.name
                m = re.match(r"^cash_(\d{4}-\d{2}-\d{2})\.csv$", fname)
                if not m:
                    continue
                val_date = m.group(1)

                # Skip if already uploaded (match by filename)
                if any(v.get("file_name") == fname for v in uploaded_val):
                    print(f"  {ii_account_id}/{fname}: " + colour("already uploaded", YELLOW))
                    summary.append(("Push cash", f"{ii_account_id}/{fname}", "skipped", "already uploaded"))
                    continue

                print(f"  {ii_account_id}/{fname}...", end=" ")
                if cgt_upload_file(api_url, cgt_token, cgt_id, csv_file, "valuations", val_date):
                    print(colour("pushed", GREEN))
                    summary.append(("Push cash", f"{ii_account_id}/{fname}", "pushed"))
                else:
                    summary.append(("Push cash", f"{ii_account_id}/{fname}", "error"))

            # Then push investment valuations
            for csv_file in sorted(account_dir.glob("portfolio_*.csv")):
                fname = csv_file.name
                m = re.match(r"^portfolio_(\d{4}-\d{2}-\d{2})\.csv$", fname)
                if not m:
                    continue
                val_date = m.group(1)

                if cgt_should_skip_valuation(val_date, uploaded_val):
                    print(f"  {ii_account_id}/{fname}: " + colour("already uploaded", YELLOW))
                    summary.append(("Push valuation", f"{ii_account_id}/{fname}", "skipped", "already uploaded"))
                    continue

                print(f"  {ii_account_id}/{fname}...", end=" ")
                if cgt_upload_file(api_url, cgt_token, cgt_id, csv_file, "valuations", val_date):
                    print(colour("pushed", GREEN))
                    summary.append(("Push valuation", f"{ii_account_id}/{fname}", "pushed"))
                else:
                    summary.append(("Push valuation", f"{ii_account_id}/{fname}", "error"))

            # Push corporate action PDFs
            ca_dir = account_dir / "corporate_actions"
            if ca_dir.is_dir():
                for pdf_file in sorted(ca_dir.glob("*.pdf")):
                    fname = pdf_file.name
                    if fname in existing_draft_names:
                        print(f"  {ii_account_id}/{fname}: " + colour("already in drafts", YELLOW))
                        summary.append(("Push corp action", f"{ii_account_id}/{fname}", "skipped", "already in drafts"))
                        continue
                    print(f"  {ii_account_id}/{fname}...", end=" ")
                    result = cgt_upload_corporate_action_pdf(api_url, cgt_token, pdf_file)
                    if result == "uploaded":
                        existing_draft_names.add(fname)
                        print(colour("pushed to drafts", GREEN))
                        summary.append(("Push corp action", f"{ii_account_id}/{fname}", "pushed", ""))
                    elif result == "duplicate":
                        existing_draft_names.add(fname)
                        print(colour("duplicate — skipped", YELLOW))
                        summary.append(("Push corp action", f"{ii_account_id}/{fname}", "skipped", "duplicate"))
                    else:
                        summary.append(("Push corp action", f"{ii_account_id}/{fname}", "error"))

    # Summary — show actions individually, collapse skips into counts
    print(colour(f"\n{'='*60}", BOLD))
    print(colour(" Push Summary", BOLD))
    print(colour(f"{'='*60}", BOLD))

    had_errors = False
    skip_counts = {}  # reason → count

    for entry in summary:
        dtype, label, status = entry[0], entry[1], entry[2]
        reason = entry[3] if len(entry) > 3 else ""

        if status == "skipped":
            skip_counts[reason] = skip_counts.get(reason, 0) + 1
            continue

        if status == "pushed":
            icon = colour("OK  ", GREEN)
        elif status == "deleted":
            icon = colour("DEL ", YELLOW)
        else:
            icon = colour("FAIL", RED)
            had_errors = True
        print(f"  [{icon}] {dtype}: {label}")

    if skip_counts:
        print(colour(f"\n  Skipped (no action needed):", YELLOW))
        for reason, count in sorted(skip_counts.items()):
            print(f"    {count:3d}  {reason}")

    if had_errors:
        sys.exit(1)


def resolve_users(config, user_filter):
    """Return the list of users to process, filtered by --user if given."""
    users = config.get("users", [])
    if not users:
        print(colour("No users found in config.", RED))
        sys.exit(1)

    if user_filter:
        matched = [u for u in users if user_filter in u["email"]]
        if not matched:
            print(colour(f"No user matching '{user_filter}' in config.", RED))
            print("Available users:")
            for u in users:
                print(f"  {u['email']}")
            sys.exit(1)
        return matched

    return users


def main():
    parser = argparse.ArgumentParser(
        description="Download CSV files from Interactive Investor (ii.co.uk)"
    )
    parser.add_argument("--user", type=str, help="Filter by user email (substring match) or customer ID")
    parser.add_argument("--portfolio", action="store_true", help="Download portfolio valuations only")
    parser.add_argument("--transactions", action="store_true", help="Download transaction statements only")
    parser.add_argument("--account", type=str, help="Download for a specific account ID only")
    parser.add_argument("--token", type=str, help="Bearer token (skip prompt — only works for single user)")
    parser.add_argument("--to-date", type=str, help="Transaction end date (YYYY-MM-DD). Defaults to yesterday")
    parser.add_argument("--push", action="store_true", help="Push downloaded CSVs to Soren API")
    parser.add_argument("--push-only", action="store_true", help="Push to Soren without downloading first")
    parser.add_argument("--config", type=str, default=str(CONFIG_FILE), help="Path to config file")
    parser.add_argument("--debug", action="store_true", help="Print raw Soren API responses for debugging")
    args = parser.parse_args()

    config = load_config(Path(args.config))

    # Stash the to-date override in config for download_transactions to pick up
    if args.to_date:
        config["_to_date"] = date.fromisoformat(args.to_date)

    # Push-only mode: skip downloads entirely
    if args.push_only:
        push_to_cgt(config, args.account, debug=args.debug)
        return

    do_portfolio = args.portfolio or (not args.portfolio and not args.transactions)
    do_transactions = args.transactions or (not args.portfolio and not args.transactions)

    users = resolve_users(config, args.user)

    summary = []

    for user in users:
        email = user["email"]
        accounts = user["accounts"]

        print(colour(f"\n{'='*60}", BOLD))
        print(colour(f" {email}", BOLD))
        print(colour(f"{'='*60}", BOLD))

        if args.account:
            accounts = [a for a in accounts if a["id"] == args.account]
            if not accounts:
                print(colour(f"  Account {args.account} not found for this user — skipping.", YELLOW))
                continue

        token = get_token(email, args.token)
        customer_id = decode_jwt_customer_id(token) or user.get("customer_id", "")
        if not customer_id:
            print(colour("  Could not determine customer ID from token — skipping.", RED))
            continue
        print()

        user_dir = DOWNLOADS_DIR / email

        if do_portfolio:
            print(colour("  Portfolio valuations", BOLD))
            for account in accounts:
                result = download_portfolio(customer_id, account, token, user_dir, config)
                summary.append((email, "Portfolio", account.get("name", account["id"]), result))
            print(colour("  Cash balances", BOLD))
            for account in accounts:
                result = download_cash(customer_id, account, token, user_dir, config)
                summary.append((email, "Cash", account.get("name", account["id"]), result))
            print(colour("  Corporate action PDFs", BOLD))
            for account in accounts:
                result = download_corporate_actions(customer_id, account, token, user_dir, config)
                summary.append((email, "Corporate Actions", account.get("name", account["id"]), result))
            print()

        if do_transactions:
            print(colour("  Transaction statements", BOLD))
            for account in accounts:
                results = download_transactions(customer_id, account, token, user_dir, config)
                for i, ccy in enumerate(account.get("currencies", ["GBP"])):
                    status = results[i] if i < len(results) else "error"
                    summary.append((email, "Transactions", f"{account.get('name', account['id'])}/{ccy}", status))
            print()

    # Summary
    print(colour(f"\n{'='*60}", BOLD))
    print(colour(" Summary", BOLD))
    print(colour(f"{'='*60}", BOLD))
    current_email = None
    for email, dtype, label, status in summary:
        if email != current_email:
            print(f"\n  {email}:")
            current_email = email
        if status == "downloaded":
            icon = colour("OK", GREEN)
        elif status == "skipped":
            icon = colour("SKIP", YELLOW)
        else:
            icon = colour("FAIL", RED)
        print(f"    [{icon}] {dtype}: {label}")

    had_errors = any(s == "error" for _, _, _, s in summary)

    # Push to Soren if requested — scoped to the same users that were downloaded
    if args.push:
        push_to_cgt(config, args.account,
                    user_emails=[u["email"] for u in users],
                    debug=args.debug)

    if had_errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
