#!/usr/bin/env python3
"""CLI tool to download CSV files from Interactive Investor (ii.co.uk)."""

import argparse
import base64
import getpass
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
import yaml

BASE_URL = "https://api-prod.ii.co.uk/enrolled/api"
DOWNLOADS_DIR = Path("downloads")
CONFIG_FILE = Path("config.yaml")

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


def decode_jwt_exp(token):
    """Decode JWT expiry without verification."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return datetime.fromtimestamp(data["exp"])
    except Exception:
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
        print(colour("  Could not decode token expiry — proceeding anyway.", YELLOW))

    return token


def make_headers(token):
    return {
        "accept": "text/csv",
        "authorization": f"Bearer {token}",
        "ii-consumer-type": "web.secure",
        "origin": "https://www.ii.co.uk",
        "referer": "https://www.ii.co.uk/",
    }


def download_portfolio(customer_id, account, token, user_dir):
    """Download current portfolio valuation CSV."""
    account_id = account["id"]
    account_name = account.get("name", account_id)
    today = date.today().isoformat()

    out_dir = user_dir / account_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"portfolio_{today}.csv"

    url = f"{BASE_URL}/2/customers/{customer_id}/accounts/{account_id}/portfolio/export"
    print(f"  Downloading portfolio for {account_name} ({account_id})...", end=" ")

    resp = requests.get(url, headers=make_headers(token))
    if resp.status_code in (401, 403):
        print(colour("AUTH FAILED — token expired or invalid", RED))
        return "error"
    if resp.status_code != 200:
        print(colour(f"HTTP {resp.status_code}", RED))
        print(colour(f"    Response: {resp.text[:500]}", RED))
        return "error"

    out_file.write_text(resp.text)
    print(colour(f"saved → {out_file}", GREEN))
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


def download_transactions(customer_id, account, token, user_dir):
    """Download transaction statement CSVs for each currency.

    Re-run logic:
    - Full-year files (historic, complete) are never re-downloaded.
    - Partial current-year files are deleted and re-fetched with today's date,
      so transactions that posted after the last run are captured.
    """
    account_id = account["id"]
    account_name = account.get("name", account_id)
    currencies = account.get("currencies", ["GBP"])
    start_date = account.get("start_date", "2024-01-01")
    today = date.today()
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

        # Find and remove any partial (non-full-year) files that we'll re-download
        # We keep partials from historic years (e.g. 2022-06-01_2022-12-31 for a mid-year start)
        for fpath, start, end, is_full in existing:
            if not is_full and end.year == today.year:
                # Current-year partial — delete so we re-fetch with today's date
                print(f"  Transactions {account_name}/{ccy}: replacing {fpath.name} (refreshing to today)")
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

        if from_date >= today:
            print(f"  Transactions {account_name}/{ccy}: " + colour("up to date", YELLOW))
            results.append("skipped")
            continue

        chunks = build_year_chunks(from_date, today)
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

            out_file.write_text(resp.text)
            print(colour(f"saved → {out_file}", GREEN))

        results.append("downloaded" if ccy_ok else "error")

    return results


def resolve_users(config, user_filter):
    """Return the list of users to process, filtered by --user if given."""
    users = config.get("users", [])
    if not users:
        print(colour("No users found in config.", RED))
        sys.exit(1)

    if user_filter:
        matched = [u for u in users if user_filter in u["email"] or user_filter == u["customer_id"]]
        if not matched:
            print(colour(f"No user matching '{user_filter}' in config.", RED))
            print("Available users:")
            for u in users:
                print(f"  {u['email']} ({u['customer_id']})")
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
    parser.add_argument("--config", type=str, default=str(CONFIG_FILE), help="Path to config file")
    args = parser.parse_args()

    do_portfolio = args.portfolio or (not args.portfolio and not args.transactions)
    do_transactions = args.transactions or (not args.portfolio and not args.transactions)

    config = load_config(Path(args.config))
    users = resolve_users(config, args.user)

    summary = []

    for user in users:
        email = user["email"]
        customer_id = user["customer_id"]
        accounts = user["accounts"]

        print(colour(f"\n{'='*60}", BOLD))
        print(colour(f" {email} (customer {customer_id})", BOLD))
        print(colour(f"{'='*60}", BOLD))

        if args.account:
            accounts = [a for a in accounts if a["id"] == args.account]
            if not accounts:
                print(colour(f"  Account {args.account} not found for this user — skipping.", YELLOW))
                continue

        token = get_token(email, args.token)
        print()

        user_dir = DOWNLOADS_DIR / email

        if do_portfolio:
            print(colour("  Portfolio valuations", BOLD))
            for account in accounts:
                result = download_portfolio(customer_id, account, token, user_dir)
                summary.append((email, "Portfolio", account.get("name", account["id"]), result))
            print()

        if do_transactions:
            print(colour("  Transaction statements", BOLD))
            for account in accounts:
                results = download_transactions(customer_id, account, token, user_dir)
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


if __name__ == "__main__":
    main()
