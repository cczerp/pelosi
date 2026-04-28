"""Insider-trading confidence scoring.

Before the bot takes any action on a detected Pelosi trade, it calculates a
composite confidence score (0–100).  **The bot will not act unless this score
reaches** ``config.MIN_CONFIDENCE_SCORE``.

Each factor is scored 0–10 and then multiplied by its configured weight to
produce a weighted sub-score.  All sub-scores are summed to give the final
100-point composite.

Why these signals?
------------------
Academic research on congressional trading (e.g. Ziobrowski et al., 2004,
2011; Eggers & Hainmueller, 2014) and investigative journalism consistently
find that House members' trades tend to outperform the market.  The factors
below are the most commonly cited explanatory mechanisms:

1. **Legislative timing** — trades clustered just before bill passage,
   committee votes, or regulatory announcements are the strongest single
   predictor.
2. **Unusual options activity** — a sudden spike in cheap call options days
   before a positive catalyst is a classic informed-trading footprint.
3. **Post-trade performance** — strong price appreciation in the 30 days
   following disclosure (compared to a broad-market baseline) is
   retrospective evidence.
4. **Committee alignment** — members on committees with jurisdiction over a
   sector (e.g. Armed Services → defense stocks) have information others
   don't.
5. **Trade-size anomaly** — unusually large trades relative to the member's
   own historical pattern suggest heightened conviction.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from pelosi_bot.config import MIN_CONFIDENCE_SCORE, SCORING_WEIGHTS

logger = logging.getLogger(__name__)


# ── Committee–sector mapping ────────────────────────────────────────────────
# Simplified mapping of House committee names to yfinance sector strings.
# Pelosi's current/historical committee memberships inform which sectors may
# carry information advantages.
COMMITTEE_SECTOR_MAP: dict[str, list[str]] = {
    "Armed Services": ["Industrials", "Aerospace & Defense"],
    "Financial Services": ["Financial Services", "Finance"],
    "Energy and Commerce": ["Energy", "Communication Services", "Technology"],
    "Ways and Means": ["Financial Services", "Finance"],
    "Intelligence": ["Technology", "Communication Services", "Industrials"],
    "Appropriations": [],  # broad, less specific signal
}

# Pelosi's known committee memberships (she is currently Speaker Emerita and
# sits on the House Democratic leadership; historically served on Intelligence
# and Appropriations).
PELOSI_COMMITTEES: list[str] = ["Intelligence", "Appropriations"]


# ── Result dataclass ────────────────────────────────────────────────────────


@dataclass
class ScoreResult:
    """Holds the composite score and a breakdown of sub-scores."""

    ticker: str
    composite_score: float
    sub_scores: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    meets_threshold: bool = False

    def summary(self) -> str:
        threshold_str = (
            "✅ MEETS threshold — action warranted"
            if self.meets_threshold
            else "❌ BELOW threshold — no action taken"
        )
        lines = [
            f"=== Insider-Trading Confidence Score: {self.ticker} ===",
            f"  Composite score : {self.composite_score:.1f} / 100",
            f"  Min threshold   : {MIN_CONFIDENCE_SCORE}",
            f"  Verdict         : {threshold_str}",
            "  Sub-scores:",
        ]
        for factor, score in self.sub_scores.items():
            weight = SCORING_WEIGHTS[factor]
            weighted = score / 10 * weight
            lines.append(f"    {factor:<30s}: raw={score:.1f}/10  weighted={weighted:.1f}/{weight}")
        if self.reasons:
            lines.append("  Supporting evidence:")
            for r in self.reasons:
                lines.append(f"    • {r}")
        return "\n".join(lines)


# ── Individual scoring functions ───────────────────────────────────────────


def score_legislative_timing(transaction: dict[str, Any]) -> tuple[float, list[str]]:
    """Score based on proximity of the trade to legislative events.

    The disclosure feed does not include committee-vote timestamps, so we
    use the gap between ``transaction_date`` and ``disclosure_date`` as a
    proxy: a very short gap (< 5 days) suggests the trade happened just
    before the mandatory 45-day reporting window closed, which itself is a
    well-documented evasion pattern.  A long gap may indicate routine
    portfolio rebalancing.

    Scale:
    - gap ≤ 5 days   → 9
    - gap ≤ 15 days  → 7
    - gap ≤ 30 days  → 5
    - gap ≤ 45 days  → 3
    - gap > 45 days  → 1
    """
    reasons: list[str] = []
    tx_date_raw = transaction.get("transaction_date", "")
    disc_date_raw = transaction.get("disclosure_date", "")

    tx_date = _try_parse(tx_date_raw)
    disc_date = _try_parse(disc_date_raw)

    if tx_date is None or disc_date is None:
        return 3.0, ["Could not parse transaction/disclosure dates — using neutral score"]

    gap = (disc_date - tx_date).days
    if gap < 0:
        gap = 0  # data anomaly guard

    if gap <= 5:
        raw = 9.0
        reasons.append(
            f"Trade disclosed within {gap} day(s) of transaction — unusually fast"
            " disclosure may indicate front-running before a public announcement"
        )
    elif gap <= 15:
        raw = 7.0
        reasons.append(
            f"Trade-to-disclosure gap is {gap} day(s) — shorter than typical"
            " 30–45 day window, suggesting heightened urgency"
        )
    elif gap <= 30:
        raw = 5.0
        reasons.append(f"Trade-to-disclosure gap is {gap} day(s) — within normal range")
    elif gap <= 45:
        raw = 3.0
        reasons.append(f"Trade-to-disclosure gap is {gap} day(s) — near the statutory 45-day limit")
    else:
        raw = 1.0
        reasons.append(
            f"Trade-to-disclosure gap is {gap} day(s) — exceeds 45-day window"
            " (late filing, reduces timing signal)"
        )

    return raw, reasons


def score_unusual_options_activity(
    options_summary: dict[str, Any],
    volume_z: float | None,
) -> tuple[float, list[str]]:
    """Score based on options and volume data.

    Considers:
    - Put/call ratio: ratio < 0.5 (call-heavy) is bullish and unusual
    - Volume z-score: z > 2 indicates a statistically significant spike
    """
    reasons: list[str] = []
    raw = 0.0

    if not options_summary.get("available"):
        return 2.0, ["Options data unavailable — using low default"]

    pcr = options_summary.get("put_call_ratio")
    if pcr is not None:
        if pcr < 0.3:
            raw += 5.0
            reasons.append(
                f"Put/call ratio is {pcr:.2f} — extremely call-heavy positioning"
                " consistent with informed bullish bets"
            )
        elif pcr < 0.5:
            raw += 3.0
            reasons.append(
                f"Put/call ratio is {pcr:.2f} — moderately call-heavy"
            )
        elif pcr > 1.5:
            raw += 1.0
            reasons.append(f"Put/call ratio is {pcr:.2f} — bearish skew, less consistent with buy trade")
        else:
            raw += 2.0
            reasons.append(f"Put/call ratio is {pcr:.2f} — neutral")

    if volume_z is not None:
        if volume_z > 3:
            raw += 5.0
            reasons.append(
                f"Volume z-score is {volume_z:.1f} — extreme spike (>{volume_z:.0f}σ above mean)"
                " strongly suggests informed trading"
            )
        elif volume_z > 2:
            raw += 3.0
            reasons.append(f"Volume z-score is {volume_z:.1f} — notable spike (>2σ)")
        elif volume_z > 1:
            raw += 1.5
            reasons.append(f"Volume z-score is {volume_z:.1f} — slightly elevated volume")
        else:
            reasons.append(f"Volume z-score is {volume_z:.1f} — normal volume")

    return min(raw, 10.0), reasons


def score_post_trade_performance(post_return: float | None) -> tuple[float, list[str]]:
    """Score based on how strongly the stock moved after the trade.

    A large positive return in the 30 days after a *buy* disclosure is
    retrospective evidence of an information advantage.

    Scale (for buys):
    - return ≥ 20%   → 10
    - return ≥ 10%   → 7
    - return ≥  5%   → 5
    - return ≥  0%   → 3
    - return <  0%   → 1
    """
    reasons: list[str] = []

    if post_return is None:
        return 3.0, ["Insufficient price history to compute post-trade return"]

    if post_return >= 20:
        raw = 10.0
        reasons.append(
            f"Stock gained {post_return:.1f}% in 30 days after trade — exceptional"
            " outperformance strongly consistent with informed buying"
        )
    elif post_return >= 10:
        raw = 7.0
        reasons.append(
            f"Stock gained {post_return:.1f}% in 30 days — significant outperformance"
        )
    elif post_return >= 5:
        raw = 5.0
        reasons.append(f"Stock gained {post_return:.1f}% in 30 days — moderate outperformance")
    elif post_return >= 0:
        raw = 3.0
        reasons.append(f"Stock returned {post_return:.1f}% in 30 days — roughly flat")
    else:
        raw = 1.0
        reasons.append(
            f"Stock declined {post_return:.1f}% in 30 days — does not support"
            " an information-advantage thesis for a buy"
        )

    return raw, reasons


def score_committee_alignment(company_info: dict[str, Any]) -> tuple[float, list[str]]:
    """Score based on whether the stock's sector aligns with Pelosi's
    committee memberships.

    Members sitting on committees with oversight of an industry have non-
    public information about that industry's regulatory environment.
    """
    reasons: list[str] = []
    sector: str = (company_info.get("sector") or "").strip()
    industry: str = (company_info.get("industry") or "").strip()

    if not sector:
        return 2.0, ["Sector data unavailable — using low default"]

    for committee in PELOSI_COMMITTEES:
        aligned_sectors = COMMITTEE_SECTOR_MAP.get(committee, [])
        for aligned in aligned_sectors:
            if aligned.lower() in sector.lower() or aligned.lower() in industry.lower():
                reasons.append(
                    f"Sector '{sector}' aligns with Pelosi's '{committee}' committee"
                    " — committee members may have non-public regulatory intelligence"
                )
                return 8.0, reasons

    reasons.append(
        f"Sector '{sector}' does not directly align with known committee memberships"
        " — weaker insider-information pathway"
    )
    return 3.0, reasons


def score_trade_size_anomaly(
    transaction: dict[str, Any],
    all_transactions: list[dict[str, Any]],
) -> tuple[float, list[str]]:
    """Score based on whether this trade is unusually large relative to
    Pelosi's own historical trade sizes.

    The disclosure feed records trade ranges (e.g. '$100,001 - $250,000').
    We extract midpoints and compare the current trade to the historical
    distribution.

    Scale:
    - > 2 std dev above mean → 8
    - > 1 std dev above mean → 5
    - within 1 std dev       → 2
    """
    reasons: list[str] = []
    current_mid = _estimate_trade_midpoint(transaction.get("amount", ""))

    if current_mid is None:
        return 2.0, ["Could not parse trade amount — using low default"]

    historical_mids = [
        m
        for tx in all_transactions
        if (m := _estimate_trade_midpoint(tx.get("amount", ""))) is not None
    ]

    if len(historical_mids) < 5:
        return 2.0, ["Insufficient historical trades to compute size anomaly"]

    import statistics

    mean = statistics.mean(historical_mids)
    stdev = statistics.stdev(historical_mids)

    if stdev == 0:
        return 2.0, ["All historical trades are the same size — no variance to compare"]

    z = (current_mid - mean) / stdev
    reasons.append(
        f"Trade size ~${current_mid:,.0f} vs. historical mean ~${mean:,.0f}"
        f" (z={z:.1f})"
    )

    if z > 2:
        reasons.append("Trade is >2σ larger than historical average — unusually large conviction bet")
        return 8.0, reasons
    if z > 1:
        reasons.append("Trade is >1σ above average — moderately elevated size")
        return 5.0, reasons

    reasons.append("Trade size is within normal historical range")
    return 2.0, reasons


# ── Composite scorer ───────────────────────────────────────────────────────


def compute_confidence_score(
    transaction: dict[str, Any],
    all_transactions: list[dict[str, Any]],
    price_df: Any,
    options_summary: dict[str, Any],
    company_info: dict[str, Any],
    volume_z: float | None = None,
    post_trade_return: float | None = None,
) -> ScoreResult:
    """Calculate the composite insider-trading confidence score.

    Parameters
    ----------
    transaction:
        The specific trade being evaluated.
    all_transactions:
        All of this representative's historical trades (for size comparison).
    price_df:
        Price history DataFrame from :mod:`stock_data`.
    options_summary:
        Options summary dict from :mod:`stock_data`.
    company_info:
        Company info dict from :mod:`stock_data`.
    volume_z:
        Pre-computed volume z-score (pass ``None`` to skip).
    post_trade_return:
        Pre-computed 30-day return (pass ``None`` to skip).
    """
    ticker = (transaction.get("ticker") or "UNKNOWN").strip().upper()

    lt_raw, lt_reasons = score_legislative_timing(transaction)
    uoa_raw, uoa_reasons = score_unusual_options_activity(options_summary, volume_z)
    ptp_raw, ptp_reasons = score_post_trade_performance(post_trade_return)
    ca_raw, ca_reasons = score_committee_alignment(company_info)
    tsa_raw, tsa_reasons = score_trade_size_anomaly(transaction, all_transactions)

    sub_raw = {
        "legislative_timing": lt_raw,
        "unusual_options_activity": uoa_raw,
        "post_trade_performance": ptp_raw,
        "committee_alignment": ca_raw,
        "trade_size_anomaly": tsa_raw,
    }

    composite = sum(
        (sub_raw[factor] / 10.0) * SCORING_WEIGHTS[factor]
        for factor in SCORING_WEIGHTS
    )

    all_reasons = lt_reasons + uoa_reasons + ptp_reasons + ca_reasons + tsa_reasons

    result = ScoreResult(
        ticker=ticker,
        composite_score=round(composite, 2),
        sub_scores=sub_raw,
        reasons=all_reasons,
        meets_threshold=composite >= MIN_CONFIDENCE_SCORE,
    )
    logger.info(
        "Score for %s: %.1f/100 (%s threshold)",
        ticker,
        composite,
        "meets" if result.meets_threshold else "below",
    )
    return result


# ── Utilities ──────────────────────────────────────────────────────────────


def _try_parse(raw: str) -> date | None:
    from datetime import datetime

    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


_AMOUNT_TABLE: dict[str, float] = {
    "$1,001 - $15,000": 8_000,
    "$15,001 - $50,000": 32_500,
    "$50,001 - $100,000": 75_000,
    "$100,001 - $250,000": 175_000,
    "$250,001 - $500,000": 375_000,
    "$500,001 - $1,000,000": 750_000,
    "$1,000,001 - $5,000,000": 3_000_000,
    "$5,000,001 - $25,000,000": 15_000_000,
    "Over $50,000,000": 50_000_000,
}


def _estimate_trade_midpoint(amount_str: str) -> float | None:
    """Map a disclosure amount-range string to an approximate midpoint."""
    cleaned = (amount_str or "").strip()
    return _AMOUNT_TABLE.get(cleaned)
