"""Fetch and filter House financial-disclosure transactions.

Data source: House Stock Watcher public S3 feed, which aggregates the
official U.S. House of Representatives periodic-transaction report (PTR)
filings.  No API key or authentication is required.

Reference: https://disclosures-clerk.house.gov/FinancialDisclosure
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import requests

from pelosi_bot.config import HOUSE_STOCK_WATCHER_URL, TARGET_REPRESENTATIVE

logger = logging.getLogger(__name__)


# ── Public data helpers ────────────────────────────────────────────────────


def fetch_all_transactions(timeout: int = 30) -> list[dict[str, Any]]:
    """Download all transactions from the House Stock Watcher feed.

    Returns a list of raw disclosure dicts as returned by the feed.
    Raises ``requests.HTTPError`` on a non-2xx response.
    """
    logger.info("Fetching transactions from %s", HOUSE_STOCK_WATCHER_URL)
    response = requests.get(HOUSE_STOCK_WATCHER_URL, timeout=timeout)
    response.raise_for_status()
    return response.json()


def filter_transactions(
    transactions: list[dict[str, Any]],
    representative: str = TARGET_REPRESENTATIVE,
    since: date | None = None,
) -> list[dict[str, Any]]:
    """Return only the transactions belonging to *representative*.

    Parameters
    ----------
    transactions:
        Raw list returned by :func:`fetch_all_transactions`.
    representative:
        Name string to match against the ``representative`` field (case-
        insensitive substring match so minor formatting differences don't
        cause misses).
    since:
        Optional lower bound on ``transaction_date``.  Transactions before
        this date are excluded.
    """
    rep_lower = representative.lower()
    results: list[dict[str, Any]] = []

    for tx in transactions:
        tx_rep: str = tx.get("representative", "")
        if rep_lower not in tx_rep.lower():
            continue

        if since is not None:
            tx_date = _parse_date(tx.get("transaction_date", ""))
            if tx_date is None or tx_date < since:
                continue

        results.append(tx)

    logger.info(
        "Found %d transaction(s) for '%s'%s",
        len(results),
        representative,
        f" since {since}" if since else "",
    )
    return results


def _parse_date(raw: str) -> date | None:
    """Parse a date string from the disclosure feed.  Returns ``None`` on
    failure so callers can handle gracefully."""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def get_ticker(transaction: dict[str, Any]) -> str | None:
    """Extract a clean ticker symbol from a transaction dict.

    The feed stores tickers in a ``ticker`` field; a small amount of
    sanitisation strips whitespace and converts to upper-case.  Returns
    ``None`` when the ticker is blank or cannot be determined.
    """
    raw: str = transaction.get("ticker", "") or ""
    ticker = raw.strip().upper()
    return ticker if ticker else None
