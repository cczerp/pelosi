"""Unit tests for pelosi_bot.disclosures."""

import pytest
from pelosi_bot.disclosures import _parse_date, filter_transactions, get_ticker
from datetime import date


SAMPLE_TRANSACTIONS = [
    {
        "representative": "Nancy Pelosi",
        "ticker": "NVDA",
        "transaction_date": "2024-01-15",
        "disclosure_date": "2024-01-20",
        "type": "purchase",
        "amount": "$1,000,001 - $5,000,000",
    },
    {
        "representative": "Nancy Pelosi",
        "ticker": "AAPL",
        "transaction_date": "2023-06-01",
        "disclosure_date": "2023-07-10",
        "type": "purchase",
        "amount": "$250,001 - $500,000",
    },
    {
        "representative": "Paul Ryan",
        "ticker": "XOM",
        "transaction_date": "2024-02-01",
        "disclosure_date": "2024-02-28",
        "type": "sale",
        "amount": "$15,001 - $50,000",
    },
]


class TestParseDate:
    def test_iso_format(self):
        assert _parse_date("2024-01-15") == date(2024, 1, 15)

    def test_us_format(self):
        assert _parse_date("01/15/2024") == date(2024, 1, 15)

    def test_slash_iso(self):
        assert _parse_date("2024/01/15") == date(2024, 1, 15)

    def test_invalid_returns_none(self):
        assert _parse_date("not-a-date") is None

    def test_empty_returns_none(self):
        assert _parse_date("") is None


class TestFilterTransactions:
    def test_filters_by_representative(self):
        results = filter_transactions(SAMPLE_TRANSACTIONS)
        assert all("pelosi" in r["representative"].lower() for r in results)
        assert len(results) == 2

    def test_case_insensitive_name_match(self):
        results = filter_transactions(SAMPLE_TRANSACTIONS, representative="nancy pelosi")
        assert len(results) == 2

    def test_since_filter(self):
        results = filter_transactions(SAMPLE_TRANSACTIONS, since=date(2024, 1, 1))
        assert len(results) == 1
        assert results[0]["ticker"] == "NVDA"

    def test_no_match(self):
        results = filter_transactions(SAMPLE_TRANSACTIONS, representative="Unknown Person")
        assert results == []


class TestGetTicker:
    def test_returns_upper(self):
        assert get_ticker({"ticker": "nvda"}) == "NVDA"

    def test_strips_whitespace(self):
        assert get_ticker({"ticker": "  AAPL  "}) == "AAPL"

    def test_empty_returns_none(self):
        assert get_ticker({"ticker": ""}) is None

    def test_missing_key_returns_none(self):
        assert get_ticker({}) is None
