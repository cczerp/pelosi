"""Configuration for the Pelosi bot.

All tuneable knobs live here so the rest of the code stays clean.
"""

import os

# ── Disclosure feed ────────────────────────────────────────────────────────
# Public JSON feed maintained by House Stock Watcher (housestockwatcher.com).
# This is derived from official U.S. House financial-disclosure filings and
# is freely available without authentication.
HOUSE_STOCK_WATCHER_URL = "https://house-stock-watcher-data.s3-us-west-2.amazonaws.com/data/all_transactions.json"

# Representative name to track (as it appears in the disclosure data).
TARGET_REPRESENTATIVE = os.getenv("TARGET_REP", "Nancy Pelosi")

# ── Insider-trading confidence score ──────────────────────────────────────
# The bot will NOT act on a trade unless the composite score reaches this
# threshold.  Scores are 0–100; the default of 60 requires several
# corroborating signals before any trade is flagged.
MIN_CONFIDENCE_SCORE = int(os.getenv("MIN_CONFIDENCE_SCORE", "60"))

# ── Scan frequency ────────────────────────────────────────────────────────
# How often (in seconds) to poll the disclosure feed.
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "3600"))  # 1 h

# ── Lookback windows (trading days) ────────────────────────────────────────
PRICE_LOOKBACK_DAYS = int(os.getenv("PRICE_LOOKBACK_DAYS", "90"))
NEWS_LOOKBACK_DAYS = int(os.getenv("NEWS_LOOKBACK_DAYS", "30"))

# ── Scoring weights (must sum to 100) ─────────────────────────────────────
# Each component contributes a weighted score that is summed to produce the
# final confidence score.
SCORING_WEIGHTS: dict = {
    # How close to major legislation/committee activity was the trade?
    "legislative_timing": 30,
    # Unusually large option flow or volume spike before the disclosure?
    "unusual_options_activity": 25,
    # How quickly and strongly did the stock move after the trade?
    "post_trade_performance": 20,
    # Does the stock's sector align with Pelosi's committee assignments?
    "committee_alignment": 15,
    # Is the trade size anomalously large relative to past Pelosi trades?
    "trade_size_anomaly": 10,
}

assert sum(SCORING_WEIGHTS.values()) == 100, "Scoring weights must sum to 100"
