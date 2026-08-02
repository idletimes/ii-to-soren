"""Unit tests for ii_download.py pure-logic functions.

Run with:  pytest test_ii_download.py -v
"""

import base64
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
import requests

import ii_download
from ii_download import (
    CGT_MAX_ATTEMPTS,
    II_ALL_CURRENCIES,
    _account_friendly_name,
    _add_2yr,
    _subtract_2yr,
    build_year_chunks,
    ccy_from_tx_filename,
    cgt_fetch_account_map,
    cgt_request,
    cgt_should_skip_transaction,
    cgt_should_skip_valuation,
    decode_jwt_customer_id,
    decode_jwt_payload,
    detect_currencies_from_gbp_csv,
    detect_currencies_from_gbp_rows,
    find_transaction_files,
    is_current_year_partial,
    scan_and_update_currencies,
    transaction_filename,
)


# ── JWT helpers ───────────────────────────────────────────────────────────────

def make_jwt(payload: dict) -> str:
    """Build a fake (unsigned) JWT with the given payload dict."""
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"eyJhbGciOiJSUzI1NiJ9.{encoded}.fakesig"


class TestDecodeJwtPayload:
    def test_returns_dict_for_valid_jwt(self):
        payload = {"sub": "user123", "exp": 9999999999}
        token = make_jwt(payload)
        result = decode_jwt_payload(token)
        assert result == payload

    def test_returns_none_for_garbage(self):
        assert decode_jwt_payload("not-a-jwt") is None

    def test_returns_none_for_empty_string(self):
        assert decode_jwt_payload("") is None

    def test_handles_padding_variants(self):
        # Payload lengths that produce different base64 padding requirements
        for extra in ("", "x", "xx", "xxx"):
            payload = {"key": extra}
            token = make_jwt(payload)
            assert decode_jwt_payload(token) == payload


class TestDecodeJwtCustomerId:
    def test_extracts_cid_claim(self):
        token = make_jwt({"https://onestack.co.uk/cid": "04550560000"})
        assert decode_jwt_customer_id(token) == "04550560000"

    def test_returns_none_when_claim_absent(self):
        token = make_jwt({"sub": "user@example.com"})
        assert decode_jwt_customer_id(token) is None

    def test_returns_none_for_invalid_token(self):
        assert decode_jwt_customer_id("garbage") is None


# ── build_year_chunks ─────────────────────────────────────────────────────────

class TestBuildYearChunks:
    def test_single_full_year(self):
        chunks = build_year_chunks(date(2024, 1, 1), date(2024, 12, 31))
        assert chunks == [(date(2024, 1, 1), date(2024, 12, 31))]

    def test_two_full_years(self):
        chunks = build_year_chunks(date(2023, 1, 1), date(2024, 12, 31))
        assert chunks == [
            (date(2023, 1, 1), date(2023, 12, 31)),
            (date(2024, 1, 1), date(2024, 12, 31)),
        ]

    def test_mid_year_start(self):
        chunks = build_year_chunks(date(2022, 6, 1), date(2022, 12, 31))
        assert chunks == [(date(2022, 6, 1), date(2022, 12, 31))]

    def test_mid_year_start_spanning_two_years(self):
        chunks = build_year_chunks(date(2022, 6, 1), date(2023, 12, 31))
        assert chunks == [
            (date(2022, 6, 1), date(2022, 12, 31)),
            (date(2023, 1, 1), date(2023, 12, 31)),
        ]

    def test_three_years(self):
        chunks = build_year_chunks(date(2022, 1, 1), date(2024, 12, 31))
        assert len(chunks) == 3
        assert chunks[0] == (date(2022, 1, 1), date(2022, 12, 31))
        assert chunks[1] == (date(2023, 1, 1), date(2023, 12, 31))
        assert chunks[2] == (date(2024, 1, 1), date(2024, 12, 31))

    def test_partial_current_year(self):
        chunks = build_year_chunks(date(2026, 1, 1), date(2026, 4, 22))
        assert chunks == [(date(2026, 1, 1), date(2026, 4, 22))]

    def test_empty_range_returns_nothing(self):
        # from == to → while condition false immediately
        chunks = build_year_chunks(date(2024, 4, 22), date(2024, 4, 22))
        assert chunks == []

    def test_dec_31_to_jan_1_boundary(self):
        # Verifies year-end boundary is handled correctly
        chunks = build_year_chunks(date(2024, 1, 1), date(2025, 1, 15))
        assert chunks == [
            (date(2024, 1, 1), date(2024, 12, 31)),
            (date(2025, 1, 1), date(2025, 1, 15)),
        ]


# ── transaction_filename ──────────────────────────────────────────────────────

class TestTransactionFilename:
    def test_full_year(self):
        assert transaction_filename("GBP", date(2024, 1, 1), date(2024, 12, 31)) == "transactions_GBP_2024.csv"

    def test_mid_year_start_partial(self):
        assert transaction_filename("GBP", date(2022, 6, 1), date(2022, 12, 31)) == "transactions_GBP_2022-06-01_2022-12-31.csv"

    def test_current_year_partial(self):
        assert transaction_filename("GBP", date(2026, 1, 1), date(2026, 4, 22)) == "transactions_GBP_2026-01-01_2026-04-22.csv"

    def test_usd_full_year(self):
        assert transaction_filename("USD", date(2023, 1, 1), date(2023, 12, 31)) == "transactions_USD_2023.csv"

    def test_non_jan1_start_is_not_full_year(self):
        # Jan 2 → Dec 31 should NOT be treated as a full-year file
        assert transaction_filename("GBP", date(2024, 1, 2), date(2024, 12, 31)) == "transactions_GBP_2024-01-02_2024-12-31.csv"

    def test_non_dec31_end_is_not_full_year(self):
        assert transaction_filename("GBP", date(2024, 1, 1), date(2024, 12, 30)) == "transactions_GBP_2024-01-01_2024-12-30.csv"


# ── find_transaction_files ────────────────────────────────────────────────────

class TestFindTransactionFiles:
    def test_full_year_file(self, tmp_path):
        (tmp_path / "transactions_GBP_2024.csv").touch()
        results = find_transaction_files(tmp_path, "GBP")
        assert len(results) == 1
        path, start, end, is_full = results[0]
        assert start == date(2024, 1, 1)
        assert end == date(2024, 12, 31)
        assert is_full is True

    def test_date_range_file(self, tmp_path):
        (tmp_path / "transactions_GBP_2026-01-01_2026-04-22.csv").touch()
        results = find_transaction_files(tmp_path, "GBP")
        assert len(results) == 1
        path, start, end, is_full = results[0]
        assert start == date(2026, 1, 1)
        assert end == date(2026, 4, 22)
        assert is_full is False

    def test_mixed_files(self, tmp_path):
        (tmp_path / "transactions_GBP_2023.csv").touch()
        (tmp_path / "transactions_GBP_2024.csv").touch()
        (tmp_path / "transactions_GBP_2026-01-01_2026-04-22.csv").touch()
        results = find_transaction_files(tmp_path, "GBP")
        assert len(results) == 3

    def test_ignores_other_currencies(self, tmp_path):
        (tmp_path / "transactions_GBP_2024.csv").touch()
        (tmp_path / "transactions_USD_2024.csv").touch()
        results = find_transaction_files(tmp_path, "GBP")
        assert len(results) == 1
        assert results[0][0].name == "transactions_GBP_2024.csv"

    def test_ignores_portfolio_files(self, tmp_path):
        (tmp_path / "transactions_GBP_2024.csv").touch()
        (tmp_path / "portfolio_2024-04-22.csv").touch()
        results = find_transaction_files(tmp_path, "GBP")
        assert len(results) == 1

    def test_returns_empty_for_missing_directory(self, tmp_path):
        results = find_transaction_files(tmp_path / "nonexistent", "GBP")
        assert results == []

    def test_mid_year_start_partial(self, tmp_path):
        (tmp_path / "transactions_GBP_2022-06-01_2022-12-31.csv").touch()
        results = find_transaction_files(tmp_path, "GBP")
        assert len(results) == 1
        _, start, end, is_full = results[0]
        assert start == date(2022, 6, 1)
        assert end == date(2022, 12, 31)
        assert is_full is False


# ── is_current_year_partial ───────────────────────────────────────────────────

class TestIsCurrentYearPartial:
    def test_current_year_partial(self):
        today = date.today()
        fname = f"transactions_GBP_{today.year}-01-01_{today.year}-04-22.csv"
        assert is_current_year_partial(fname) is True

    def test_past_year_partial_is_false(self):
        assert is_current_year_partial("transactions_GBP_2022-06-01_2022-12-31.csv") is False

    def test_full_year_file_is_false(self):
        assert is_current_year_partial("transactions_GBP_2024.csv") is False

    def test_portfolio_file_is_false(self):
        assert is_current_year_partial("portfolio_2026-04-22.csv") is False

    def test_garbage_is_false(self):
        assert is_current_year_partial("garbage.csv") is False


# ── ccy_from_tx_filename ──────────────────────────────────────────────────────

class TestCcyFromTxFilename:
    def test_gbp_full_year(self):
        assert ccy_from_tx_filename("transactions_GBP_2024.csv") == "GBP"

    def test_usd_partial(self):
        assert ccy_from_tx_filename("transactions_USD_2026-01-01_2026-04-22.csv") == "USD"

    def test_returns_none_for_non_transaction_file(self):
        assert ccy_from_tx_filename("portfolio_2024-01-01.csv") is None

    def test_returns_none_for_garbage(self):
        assert ccy_from_tx_filename("garbage") is None


# ── cgt_should_skip_transaction ───────────────────────────────────────────────

class TestCgtShouldSkipTransaction:
    def test_skips_when_filename_matches(self):
        uploaded = [{"file_name": "transactions_GBP_2024.csv", "id": 1}]
        assert cgt_should_skip_transaction("transactions_GBP_2024.csv", uploaded) is True

    def test_does_not_skip_when_no_match(self):
        uploaded = [{"file_name": "transactions_GBP_2023.csv", "id": 1}]
        assert cgt_should_skip_transaction("transactions_GBP_2024.csv", uploaded) is False

    def test_does_not_skip_empty_list(self):
        assert cgt_should_skip_transaction("transactions_GBP_2024.csv", []) is False

    def test_matches_exact_filename_only(self):
        uploaded = [{"file_name": "transactions_GBP_2024.csv"}]
        assert cgt_should_skip_transaction("transactions_USD_2024.csv", uploaded) is False


# ── cgt_should_skip_valuation ─────────────────────────────────────────────────

class TestCgtShouldSkipValuation:
    def test_skips_when_investments_valuation_exists(self):
        uploaded = [{"valuation_type": "investments", "valuation_date": "2026-03-26"}]
        assert cgt_should_skip_valuation("2026-03-26", uploaded) is True

    def test_does_not_skip_cash_valuation_same_date(self):
        # Cash valuations (manually entered in UI) must not block portfolio CSV upload
        uploaded = [{"valuation_type": "cash", "valuation_date": "2026-03-26", "file_name": "-", "id": -21}]
        assert cgt_should_skip_valuation("2026-03-26", uploaded) is False

    def test_does_not_skip_when_date_differs(self):
        uploaded = [{"valuation_type": "investments", "valuation_date": "2026-03-25"}]
        assert cgt_should_skip_valuation("2026-03-26", uploaded) is False

    def test_does_not_skip_empty_list(self):
        assert cgt_should_skip_valuation("2026-03-26", []) is False

    def test_skips_with_mixed_types_when_investments_present(self):
        uploaded = [
            {"valuation_type": "cash", "valuation_date": "2026-03-26"},
            {"valuation_type": "investments", "valuation_date": "2026-03-26"},
        ]
        assert cgt_should_skip_valuation("2026-03-26", uploaded) is True


# ── partial-deletion date logic ───────────────────────────────────────────────
# The rule in download_transactions() is:
#   delete partial if: end >= cutoff - timedelta(days=1)
# Tests verify this rule covers the Dec 31 → Jan 1 boundary case.

class TestPartialDeletionCriterion:
    """Tests for the 'should we delete this partial and re-download?' rule.

    Criterion: delete if end.year == cutoff.year
                        OR end == Dec 31 of previous year (Dec 31 → Jan 1 boundary)
    """

    def _should_delete(self, end: date, cutoff: date) -> bool:
        return end.year == cutoff.year or end == date(cutoff.year - 1, 12, 31)

    def test_same_day_partial_is_deleted(self):
        today = date(2026, 4, 22)
        assert self._should_delete(today, today) is True

    def test_recent_current_year_partial_is_deleted(self):
        assert self._should_delete(date(2026, 4, 20), date(2026, 4, 27)) is True

    def test_months_old_current_year_partial_is_deleted(self):
        # Even if we haven't run in months, the current-year partial is still deleted
        assert self._should_delete(date(2026, 1, 15), date(2026, 4, 27)) is True

    def test_dec_31_partial_deleted_on_jan_1(self):
        # The key year-boundary case: a Dec 31 partial must be refreshed on Jan 1
        dec_31 = date(2026, 12, 31)
        jan_1 = date(2027, 1, 1)
        assert self._should_delete(dec_31, jan_1) is True

    def test_old_historic_partial_not_deleted(self):
        # A 2022 mid-year-start partial (end Dec 31 2022) should never be touched
        old_end = date(2022, 12, 31)
        today = date(2026, 4, 22)
        assert self._should_delete(old_end, today) is False

    def test_last_years_dec_31_deleted_anywhere_in_current_year(self):
        # A Dec 31 2025 partial is deleted whenever we run in 2026, not just on Jan 1.
        # That's correct: build_year_chunks will re-download 2025 as a proper locked
        # full-year file, then start a fresh 2026 partial.
        assert self._should_delete(date(2025, 12, 31), date(2026, 4, 27)) is True


# ── Discovery helpers ─────────────────────────────────────────────────────────

class TestIIAllCurrencies:
    def test_contains_gbp(self):
        assert "GBP" in II_ALL_CURRENCIES

    def test_contains_all_nine(self):
        assert set(II_ALL_CURRENCIES) == {"GBP", "USD", "CAD", "EUR", "HKD", "SGD", "AUD", "SEK", "CHF"}

    def test_gbp_is_first(self):
        assert II_ALL_CURRENCIES[0] == "GBP"


class TestSubtract2yr:
    def test_normal_date(self):
        assert _subtract_2yr(date(2026, 4, 28)) == date(2024, 4, 28)

    def test_jan_1(self):
        assert _subtract_2yr(date(2026, 1, 1)) == date(2024, 1, 1)

    def test_dec_31(self):
        assert _subtract_2yr(date(2025, 12, 31)) == date(2023, 12, 31)

    def test_feb_29_leap_year(self):
        # 2024 is a leap year; 2022 is not → clamp to Feb 28
        assert _subtract_2yr(date(2024, 2, 29)) == date(2022, 2, 28)

    def test_feb_28_non_leap(self):
        assert _subtract_2yr(date(2026, 2, 28)) == date(2024, 2, 28)


class TestAdd2yr:
    def test_normal_date(self):
        assert _add_2yr(date(2024, 4, 28)) == date(2026, 4, 28)

    def test_feb_29_leap(self):
        # 2024-02-29 + 2yr = 2026-02-28 (2026 not a leap year)
        assert _add_2yr(date(2024, 2, 29)) == date(2026, 2, 28)

    def test_jan_1(self):
        assert _add_2yr(date(2020, 1, 1)) == date(2022, 1, 1)


class TestAccountFriendlyName:
    def test_isa(self):
        assert _account_friendly_name("ISA", "MR H BLUNDUN", False) == "ISA"

    def test_sipp(self):
        assert _account_friendly_name("SIPP", "MR H BLUNDUN", False) == "SIPP"

    def test_trading(self):
        assert _account_friendly_name("TRADING", "MR H BLUNDUN", False) == "Trading"

    def test_junior_isa_with_initial(self):
        # "MASTER Z BLUNDUN" → "Junior ISA (Z)"
        assert _account_friendly_name("JUNIOR_ISA", "MASTER Z BLUNDUN", True) == "Junior ISA (Z)"

    def test_junior_isa_second_child(self):
        # "MISS S BLUNDUN" → "Junior ISA (S)"
        assert _account_friendly_name("JUNIOR_ISA", "MISS S BLUNDUN", True) == "Junior ISA (S)"

    def test_junior_isa_not_child(self):
        # If childAccount is False, no name disambiguation
        assert _account_friendly_name("JUNIOR_ISA", "MASTER Z BLUNDUN", False) == "Junior ISA"

    def test_unknown_type_falls_back_to_title_case(self):
        assert _account_friendly_name("STOCKS_AND_SHARES", "MR H BLUNDUN", False) == "Stocks And Shares"

    def test_single_word_holder_no_crash(self):
        # Holder name with only one word — should not crash, no disambiguation
        assert _account_friendly_name("JUNIOR_ISA", "BLUNDUN", True) == "Junior ISA"


# ── GBP CSV / JSON currency detection ────────────────────────────────────────

# Realistic GBP CSV header + FX conversion rows (from actual II downloads)
_GBP_CSV_HEADER = "Date,Settlement Date,Symbol,Sedol,Quantity,Price,Description,Reference,Debit,Credit,Running Balance\n"
_GBP_CSV_AUD_ROW = '10/08/2022,12/08/2022,n/a,n/a,9484.0,£0.5858,"9484 AUSTRALIAN DOLLAR          .58 S Date 12/08/22",REF1,"£5,555.87",n/a,"£55,540.83"\n'
_GBP_CSV_USD_ROW = '10/08/2022,12/08/2022,n/a,n/a,7637.0,£0.83033,"7637 U.S. DOLLARS          .83 S Date 12/08/22",REF2,"£6,341.26",n/a,"£61,096.70"\n'
_GBP_CSV_EUR_ROW = '02/12/2024,03/12/2024,n/a,n/a,44.69,£0.81629,"44.69 EURO NoTf     .81 S Date 03/12/24",REF3,n/a,£36.48,£3.89\n'
_GBP_CSV_EUROPEAN_ROW = '15/01/2023,17/01/2023,EUFU,B456TR0,100,£12.50,"100 EUROPEAN EQUITY FUND Del  12.50 S Date 17/01/23",REF4,"£1,250.00",n/a,"£10,000.00"\n'
_GBP_CSV_PLAIN_ROW = '30/12/2024,30/12/2024,ISF,0504245,n/a,n/a,"Div ISHARES FTSE100",REF5,n/a,£41.36,£44.72\n'


class TestDetectCurrenciesFromGbpCsv:
    def test_detects_aud(self):
        csv_text = _GBP_CSV_HEADER + _GBP_CSV_AUD_ROW
        result = detect_currencies_from_gbp_csv(csv_text)
        assert "AUD" in result
        assert result["AUD"] == date(2022, 8, 10)

    def test_detects_usd(self):
        csv_text = _GBP_CSV_HEADER + _GBP_CSV_USD_ROW
        result = detect_currencies_from_gbp_csv(csv_text)
        assert "USD" in result
        assert result["USD"] == date(2022, 8, 10)

    def test_detects_eur(self):
        csv_text = _GBP_CSV_HEADER + _GBP_CSV_EUR_ROW
        result = detect_currencies_from_gbp_csv(csv_text)
        assert "EUR" in result
        assert result["EUR"] == date(2024, 12, 2)

    def test_european_does_not_match_eur(self):
        # "EUROPEAN EQUITY FUND" must NOT be detected as EUR
        csv_text = _GBP_CSV_HEADER + _GBP_CSV_EUROPEAN_ROW
        result = detect_currencies_from_gbp_csv(csv_text)
        assert "EUR" not in result

    def test_plain_row_not_detected(self):
        csv_text = _GBP_CSV_HEADER + _GBP_CSV_PLAIN_ROW
        result = detect_currencies_from_gbp_csv(csv_text)
        assert result == {}

    def test_header_only_returns_empty(self):
        result = detect_currencies_from_gbp_csv(_GBP_CSV_HEADER)
        assert result == {}

    def test_empty_string_returns_empty(self):
        assert detect_currencies_from_gbp_csv("") == {}

    def test_multiple_currencies_detected(self):
        csv_text = _GBP_CSV_HEADER + _GBP_CSV_AUD_ROW + _GBP_CSV_USD_ROW + _GBP_CSV_EUR_ROW
        result = detect_currencies_from_gbp_csv(csv_text)
        assert set(result.keys()) == {"AUD", "USD", "EUR"}

    def test_earliest_date_returned_for_repeated_currency(self):
        # Two USD rows — earliest date wins
        early_usd = '05/03/2021,07/03/2021,n/a,n/a,5000.0,£0.72,"5000 U.S. DOLLARS .72 S Date 07/03/21",REF6,"£3,600.00",n/a,"£50,000.00"\n'
        csv_text = _GBP_CSV_HEADER + _GBP_CSV_USD_ROW + early_usd
        result = detect_currencies_from_gbp_csv(csv_text)
        assert result["USD"] == date(2021, 3, 5)


class TestDetectCurrenciesFromGbpRows:
    def test_detects_aud(self):
        rows = [{"transactionDate": "2022-08-10",
                 "description": "9484 AUSTRALIAN DOLLAR .58 S Date 12/08/22"}]
        result = detect_currencies_from_gbp_rows(rows)
        assert result == {"AUD": date(2022, 8, 10)}

    def test_detects_usd_dollars_plural(self):
        rows = [{"transactionDate": "2022-08-10",
                 "description": "7637 U.S. DOLLARS .83 S Date 12/08/22"}]
        result = detect_currencies_from_gbp_rows(rows)
        assert "USD" in result

    def test_detects_eur(self):
        rows = [{"transactionDate": "2024-12-02",
                 "description": "44.69 EURO NoTf .81 S Date 03/12/24"}]
        result = detect_currencies_from_gbp_rows(rows)
        assert "EUR" in result

    def test_european_does_not_match_eur(self):
        rows = [{"transactionDate": "2023-01-15",
                 "description": "100 EUROPEAN EQUITY FUND Del 12.50 S Date 17/01/23"}]
        result = detect_currencies_from_gbp_rows(rows)
        assert "EUR" not in result

    def test_empty_rows_returns_empty(self):
        assert detect_currencies_from_gbp_rows([]) == {}

    def test_missing_transaction_date_skipped(self):
        rows = [{"description": "9484 AUSTRALIAN DOLLAR .58 S Date 12/08/22"}]
        result = detect_currencies_from_gbp_rows(rows)
        assert result == {}

    def test_earliest_date_wins_across_multiple_rows(self):
        rows = [
            {"transactionDate": "2022-08-10", "description": "7637 U.S. DOLLARS .83 S"},
            {"transactionDate": "2021-03-05", "description": "5000 U.S. DOLLARS .72 S"},
        ]
        result = detect_currencies_from_gbp_rows(rows)
        assert result["USD"] == date(2021, 3, 5)


class TestScanAndUpdateCurrencies:
    def _make_account(self, currencies=None, start_date="2022-01-01"):
        return {
            "id": "1234567",
            "name": "ISA",
            "start_date": start_date,
            "currencies": currencies or ["GBP"],
        }

    def test_adds_aud_from_gbp_file(self, tmp_path):
        csv = _GBP_CSV_HEADER + _GBP_CSV_AUD_ROW
        (tmp_path / "transactions_GBP_2022.csv").write_text(csv, encoding="utf-8")
        account = self._make_account()
        newly = scan_and_update_currencies(account, tmp_path)
        assert newly == ["AUD"]
        assert "AUD" in account["currencies"]

    def test_start_date_is_conversion_minus_7_days(self, tmp_path):
        csv = _GBP_CSV_HEADER + _GBP_CSV_AUD_ROW  # first conversion 2022-08-10
        (tmp_path / "transactions_GBP_2022.csv").write_text(csv, encoding="utf-8")
        account = self._make_account(start_date="2022-01-01")
        scan_and_update_currencies(account, tmp_path)
        aud_start = date.fromisoformat(account["currency_start_dates"]["AUD"])
        assert aud_start == date(2022, 8, 3)  # 2022-08-10 - 7 days

    def test_start_date_clamped_to_account_start(self, tmp_path):
        # If conversion - 7 days < account start, clamp to account start
        csv = _GBP_CSV_HEADER + _GBP_CSV_AUD_ROW  # conversion on 2022-08-10
        (tmp_path / "transactions_GBP_2022.csv").write_text(csv, encoding="utf-8")
        account = self._make_account(start_date="2022-08-08")  # start after (conv - 7)
        scan_and_update_currencies(account, tmp_path)
        aud_start = date.fromisoformat(account["currency_start_dates"]["AUD"])
        assert aud_start == date(2022, 8, 8)

    def test_does_not_add_existing_currency(self, tmp_path):
        csv = _GBP_CSV_HEADER + _GBP_CSV_USD_ROW
        (tmp_path / "transactions_GBP_2022.csv").write_text(csv, encoding="utf-8")
        account = self._make_account(currencies=["GBP", "USD"])
        newly = scan_and_update_currencies(account, tmp_path)
        assert newly == []

    def test_empty_dir_returns_empty(self, tmp_path):
        account = self._make_account()
        newly = scan_and_update_currencies(account, tmp_path)
        assert newly == []
        assert account["currencies"] == ["GBP"]

    def test_no_fx_entries_returns_empty(self, tmp_path):
        csv = _GBP_CSV_HEADER + _GBP_CSV_PLAIN_ROW
        (tmp_path / "transactions_GBP_2024.csv").write_text(csv, encoding="utf-8")
        account = self._make_account()
        newly = scan_and_update_currencies(account, tmp_path)
        assert newly == []

    def test_multiple_files_merged(self, tmp_path):
        # AUD in 2022 file, USD in 2024 file
        (tmp_path / "transactions_GBP_2022.csv").write_text(
            _GBP_CSV_HEADER + _GBP_CSV_AUD_ROW, encoding="utf-8"
        )
        (tmp_path / "transactions_GBP_2024.csv").write_text(
            _GBP_CSV_HEADER + _GBP_CSV_USD_ROW, encoding="utf-8"
        )
        account = self._make_account()
        newly = scan_and_update_currencies(account, tmp_path)
        assert set(newly) == {"AUD", "USD"}
        assert set(account["currencies"]) == {"GBP", "AUD", "USD"}

    def test_gbp_always_first_in_currencies(self, tmp_path):
        csv = _GBP_CSV_HEADER + _GBP_CSV_AUD_ROW
        (tmp_path / "transactions_GBP_2022.csv").write_text(csv, encoding="utf-8")
        account = self._make_account()
        scan_and_update_currencies(account, tmp_path)
        assert account["currencies"][0] == "GBP"


# ── Soren API retries ─────────────────────────────────────────────────────────

class FakeResponse:
    def __init__(self, status_code, headers=None, payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._payload = payload
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        return self._payload


@pytest.fixture
def cgt_calls(monkeypatch):
    """Drive cgt_request with a scripted sequence of responses/exceptions.

    Returns a recorder; append outcomes to `.queue` and read `.slept` after.
    """
    class Recorder:
        def __init__(self):
            self.queue = []
            self.requests = []
            self.slept = []

        def _handle(self, method, url, **kwargs):
            self.requests.append((method, url, kwargs))
            outcome = self.queue.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    rec = Recorder()
    monkeypatch.setattr(ii_download.requests, "request", rec._handle)
    monkeypatch.setattr(ii_download.time, "sleep", rec.slept.append)
    return rec


class TestCgtRequest:

    def test_retries_502_then_succeeds(self, cgt_calls):
        cgt_calls.queue = [FakeResponse(502), FakeResponse(502), FakeResponse(200)]
        resp = cgt_request("GET", "http://soren/api/accounts", "tok")
        assert resp.status_code == 200
        assert len(cgt_calls.requests) == 3
        assert cgt_calls.slept == [2.0, 4.0]

    def test_gives_up_after_max_attempts_returning_last_response(self, cgt_calls):
        cgt_calls.queue = [FakeResponse(503)] * CGT_MAX_ATTEMPTS
        resp = cgt_request("GET", "http://soren/api/accounts", "tok")
        assert resp.status_code == 503
        assert len(cgt_calls.requests) == CGT_MAX_ATTEMPTS
        # One fewer sleep than attempts — no wait after the final failure.
        assert len(cgt_calls.slept) == CGT_MAX_ATTEMPTS - 1

    def test_does_not_retry_client_errors(self, cgt_calls):
        cgt_calls.queue = [FakeResponse(404)]
        resp = cgt_request("GET", "http://soren/api/accounts", "tok")
        assert resp.status_code == 404
        assert len(cgt_calls.requests) == 1
        assert cgt_calls.slept == []

    def test_does_not_retry_success(self, cgt_calls):
        cgt_calls.queue = [FakeResponse(201)]
        assert cgt_request("POST", "http://soren/api/accounts", "tok").status_code == 201
        assert len(cgt_calls.requests) == 1

    def test_retries_connection_error(self, cgt_calls):
        cgt_calls.queue = [requests.ConnectionError("refused"), FakeResponse(200)]
        assert cgt_request("GET", "http://soren/api/accounts", "tok").status_code == 200
        assert len(cgt_calls.requests) == 2

    def test_retries_timeout(self, cgt_calls):
        cgt_calls.queue = [requests.Timeout("slow"), FakeResponse(200)]
        assert cgt_request("GET", "http://soren/api/accounts", "tok").status_code == 200

    def test_returns_none_when_never_reachable(self, cgt_calls):
        cgt_calls.queue = [requests.ConnectionError("refused")] * CGT_MAX_ATTEMPTS
        assert cgt_request("GET", "http://soren/api/accounts", "tok") is None

    def test_honours_numeric_retry_after(self, cgt_calls):
        cgt_calls.queue = [FakeResponse(429, headers={"Retry-After": "5"}), FakeResponse(200)]
        cgt_request("GET", "http://soren/api/accounts", "tok")
        assert cgt_calls.slept == [5.0]

    def test_ignores_unparseable_retry_after(self, cgt_calls):
        cgt_calls.queue = [FakeResponse(503, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
                           FakeResponse(200)]
        cgt_request("GET", "http://soren/api/accounts", "tok")
        assert cgt_calls.slept == [2.0]

    def test_backoff_is_capped(self, cgt_calls):
        cgt_calls.queue = [FakeResponse(502)] * 8
        cgt_request("GET", "http://soren/api/accounts", "tok", attempts=8)
        assert cgt_calls.slept == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0]

    def test_sends_bearer_token_and_timeout(self, cgt_calls):
        cgt_calls.queue = [FakeResponse(200)]
        cgt_request("GET", "http://soren/api/accounts", "tok")
        _, _, kwargs = cgt_calls.requests[0]
        assert kwargs["headers"]["Authorization"] == "Bearer tok"
        assert kwargs["timeout"] == ii_download.CGT_TIMEOUT

    def test_retried_upload_resends_identical_body(self, cgt_calls):
        cgt_calls.queue = [FakeResponse(502), FakeResponse(201)]
        files = {"upload": ("t.csv", b"a,b\n1,2\n", "text/csv")}
        cgt_request("POST", "http://soren/api/accounts/1/files", "tok", files=files)
        first, second = cgt_calls.requests
        assert first[2]["files"] == second[2]["files"]


class TestCgtFetchAccountMap:

    def test_maps_account_number_to_id_after_retry(self, cgt_calls):
        cgt_calls.queue = [
            FakeResponse(502),
            FakeResponse(200, payload=[{"accountNumber": "0970887", "id": 7}]),
        ]
        assert cgt_fetch_account_map("http://soren", "tok") == {"0970887": 7}

    def test_returns_none_when_unreachable(self, cgt_calls):
        cgt_calls.queue = [requests.ConnectionError("refused")] * 6
        assert cgt_fetch_account_map("http://soren", "tok", attempts=6) is None

    def test_returns_none_on_persistent_502(self, cgt_calls):
        cgt_calls.queue = [FakeResponse(502)] * 3
        assert cgt_fetch_account_map("http://soren", "tok", attempts=3) is None
