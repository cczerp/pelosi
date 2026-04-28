"""CLI entry point for the Pelosi copy-trade bot.

Usage
-----
Run a single scan and exit::

    python main.py --once

Run continuously (polls every SCAN_INTERVAL_SECONDS seconds)::

    python main.py

Override the minimum confidence threshold::

    python main.py --threshold 70

Override the lookback window::

    python main.py --once --days 180
"""

from __future__ import annotations

import argparse
import logging
import sys

import pelosi_bot.config as config
from pelosi_bot.bot import run_continuous, scan_once


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pelosi-bot",
        description=(
            "Monitor Nancy Pelosi's public House financial disclosures, collect"
            " comprehensive stock data, score each trade for insider-trading"
            " indicators, and report trades that exceed the confidence threshold."
        ),
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single scan and exit (default: run continuously)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        metavar="N",
        help="How many days back to look for trades (default: 90)",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        metavar="SCORE",
        help=f"Minimum confidence score to act on (default: {config.MIN_CONFIDENCE_SCORE})",
    )
    parser.add_argument(
        "--rep",
        type=str,
        default=None,
        metavar="NAME",
        help=f"Representative name to track (default: {config.TARGET_REPRESENTATIVE})",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug-level logging",
    )

    args = parser.parse_args(argv)
    _configure_logging(args.verbose)

    # Apply CLI overrides to config module globals
    if args.threshold is not None:
        config.MIN_CONFIDENCE_SCORE = args.threshold
    if args.rep is not None:
        config.TARGET_REPRESENTATIVE = args.rep

    if args.once:
        scan_once(since_days=args.days)
        return 0

    run_continuous()
    return 0  # unreachable in normal operation


if __name__ == "__main__":
    sys.exit(main())
