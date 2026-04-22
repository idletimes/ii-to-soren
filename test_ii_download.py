"""Unit tests for ii_download.py pure-logic functions.

Run with:  pytest test_ii_download.py -v
"""

import base64
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from ii_download import (
    build_year_chunks,
    ccy_from_tx_filename,
    cgt_should_skip_transaction,
    cgt_should_skip_valuation,
    decode_jwt_customer_id,
    decode_jwt_payload,
    find_transaction_files,
    is_current_year_partial,
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
    """Tests for the 'should we delete this partial and re-download?' rule."""

    def _should_delete(self, end: date, cutoff: date) -> bool:
        return end >= cutoff - timedelta(days=1)

    def test_same_day_partial_is_deleted(self):
        today = date(2026, 4, 22)
        assert self._should_delete(today, today) is True

    def test_yesterday_partial_is_deleted(self):
        today = date(2026, 4, 22)
        assert self._should_delete(today - timedelta(days=1), today) is True

    def test_two_days_ago_partial_is_not_deleted(self):
        today = date(2026, 4, 22)
        assert self._should_delete(today - timedelta(days=2), today) is False

    def test_dec_31_partial_deleted_on_jan_1(self):
        # The key year-boundary case: a Dec 31 partial must be refreshed on Jan 1
        dec_31 = date(2026, 12, 31)
        jan_1 = date(2027, 1, 1)
        assert self._should_delete(dec_31, jan_1) is True

    def test_old_historic_partial_not_deleted(self):
        # A 2022 mid-year-start partial should never be touched
        old_end = date(2022, 12, 31)
        today = date(2026, 4, 22)
        assert self._should_delete(old_end, today) is False
