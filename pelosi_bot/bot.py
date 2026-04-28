"""Main bot orchestration.

The bot:
1. Polls the House Stock Watcher disclosure feed on a configurable schedule.
2. For each new trade by the target representative, gathers full stock data.
3. Computes the insider-trading confidence score.
4. Only logs / acts on trades that meet the minimum confidence threshold.
"""

from __future__ import annotations

import logging
import sys
from datetime import date, timedelta
from typing import Any

import schedule
import time

from pelosi_bot import __version__
from pelosi_bot.config import (
    MIN_CONFIDENCE_SCORE,
    SCAN_INTERVAL_SECONDS,
    TARGET_REPRESENTATIVE,
)
from pelosi_bot.disclosures import fetch_all_transactions, filter_transactions, get_ticker
from pelosi_bot.insider_score import compute_confidence_score
from pelosi_bot.stock_data import (
    compute_post_trade_return,
    compute_volume_z_score,
    fetch_company_info,
    fetch_options_summary,
    fetch_price_history,
)

logger = logging.getLogger(__name__)


# ── Seen-trade cache ────────────────────────────────────────────────────────
# Keeps track of (ticker, transaction_date) pairs already evaluated so the
# bot doesn't re-process them on every scan.
_seen_trades: set[tuple[str, str]] = set()


# ── Core logic ─────────────────────────────────────────────────────────────


def process_transaction(
    transaction: dict[str, Any],
    all_rep_transactions: list[dict[str, Any]],
) -> None:
    """Evaluate a single transaction and log results if threshold is met."""
    ticker = get_ticker(transaction)
    if not ticker:
        logger.debug("Skipping transaction with no ticker: %s", transaction)
        return

    tx_date_raw: str = transaction.get("transaction_date", "")

    # De-duplicate within the current run
    key = (ticker, tx_date_raw)
    if key in _seen_trades:
        return
    _seen_trades.add(key)

    logger.info("Processing trade: %s on %s", ticker, tx_date_raw)

    # ── Gather market data ─────────────────────────────────────────────────
    price_df = fetch_price_history(ticker)
    options_summary = fetch_options_summary(ticker)
    company_info = fetch_company_info(ticker)

    volume_z = compute_volume_z_score(price_df)

    # Parse transaction date for post-trade return computation
    from pelosi_bot.insider_score import _try_parse  # noqa: PLC0415

    tx_date = _try_parse(tx_date_raw)
    post_return = None
    if tx_date is not None:
        post_return = compute_post_trade_return(price_df, tx_date)

    # ── Score ──────────────────────────────────────────────────────────────
    result = compute_confidence_score(
        transaction=transaction,
        all_transactions=all_rep_transactions,
        price_df=price_df,
        options_summary=options_summary,
        company_info=company_info,
        volume_z=volume_z,
        post_trade_return=post_return,
    )

    # ── Output ────────────────────────────────────────────────────────────
    print(result.summary())

    if result.meets_threshold:
        logger.info(
            "FLAGGED: %s scored %.1f — meets threshold (%d). "
            "Recommend further investigation.",
            ticker,
            result.composite_score,
            MIN_CONFIDENCE_SCORE,
        )
    else:
        logger.info(
            "SKIPPED: %s scored %.1f — below threshold (%d). No action taken.",
            ticker,
            result.composite_score,
            MIN_CONFIDENCE_SCORE,
        )


def scan_once(since_days: int = 90) -> None:
    """Perform a single scan of the disclosure feed."""
    logger.info("Starting scan (looking back %d days) ...", since_days)
    since = date.today() - timedelta(days=since_days)

    try:
        all_transactions = fetch_all_transactions()
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to fetch transactions: %s", exc)
        return

    rep_transactions = filter_transactions(all_transactions, since=since)
    logger.info(
        "Found %d transaction(s) for %s since %s",
        len(rep_transactions),
        TARGET_REPRESENTATIVE,
        since,
    )

    for tx in rep_transactions:
        try:
            process_transaction(tx, rep_transactions)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error processing transaction %s: %s", tx, exc)


def run_continuous() -> None:  # pragma: no cover
    """Run the bot on a recurring schedule (blocking)."""
    logger.info("Pelosi Bot v%s starting — scanning every %ds", __version__, SCAN_INTERVAL_SECONDS)
    logger.info("Target representative: %s", TARGET_REPRESENTATIVE)
    logger.info("Minimum confidence threshold: %d/100", MIN_CONFIDENCE_SCORE)

    # Run once immediately, then on schedule
    scan_once()

    schedule.every(SCAN_INTERVAL_SECONDS).seconds.do(scan_once)

    while True:
        schedule.run_pending()
        time.sleep(10)
