"""Unit tests for pelosi_bot.insider_score."""

import pytest
from datetime import date

from pelosi_bot.insider_score import (
    ScoreResult,
    _estimate_trade_midpoint,
    _try_parse,
    compute_confidence_score,
    score_committee_alignment,
    score_legislative_timing,
    score_post_trade_performance,
    score_trade_size_anomaly,
    score_unusual_options_activity,
)


# ── _try_parse ─────────────────────────────────────────────────────────────


class TestTryParse:
    def test_iso(self):
        assert _try_parse("2024-03-15") == date(2024, 3, 15)

    def test_invalid(self):
        assert _try_parse("bad") is None


# ── _estimate_trade_midpoint ────────────────────────────────────────────────


class TestEstimateTradeMidpoint:
    def test_known_range(self):
        mid = _estimate_trade_midpoint("$100,001 - $250,000")
        assert mid == 175_000

    def test_unknown_range_returns_none(self):
        assert _estimate_trade_midpoint("some garbage") is None

    def test_empty_returns_none(self):
        assert _estimate_trade_midpoint("") is None


# ── score_legislative_timing ────────────────────────────────────────────────


class TestScoreLegislativeTiming:
    def _tx(self, tx_date, disc_date):
        return {"transaction_date": tx_date, "disclosure_date": disc_date}

    def test_very_fast_disclosure(self):
        raw, reasons = score_legislative_timing(self._tx("2024-01-10", "2024-01-13"))
        assert raw == 9.0
        assert any("unusually fast" in r for r in reasons)

    def test_15_day_gap(self):
        raw, _ = score_legislative_timing(self._tx("2024-01-01", "2024-01-14"))
        assert raw == 7.0

    def test_30_day_gap(self):
        raw, _ = score_legislative_timing(self._tx("2024-01-01", "2024-01-25"))
        assert raw == 5.0

    def test_45_day_gap(self):
        raw, _ = score_legislative_timing(self._tx("2024-01-01", "2024-02-10"))
        assert raw == 3.0

    def test_over_45_days(self):
        raw, _ = score_legislative_timing(self._tx("2024-01-01", "2024-03-01"))
        assert raw == 1.0

    def test_missing_dates_neutral(self):
        raw, reasons = score_legislative_timing({})
        assert raw == 3.0
        assert any("Could not parse" in r for r in reasons)


# ── score_unusual_options_activity ─────────────────────────────────────────


class TestScoreUnusualOptionsActivity:
    def test_extreme_call_skew_high_z(self):
        summary = {"available": True, "put_call_ratio": 0.2, "call_volume": 5000, "put_volume": 1000}
        raw, reasons = score_unusual_options_activity(summary, volume_z=3.5)
        assert raw == 10.0

    def test_unavailable_returns_default(self):
        raw, reasons = score_unusual_options_activity({"available": False}, volume_z=None)
        assert raw == 2.0

    def test_neutral_pcr_no_volume(self):
        summary = {"available": True, "put_call_ratio": 0.9, "call_volume": 100, "put_volume": 90}
        raw, _ = score_unusual_options_activity(summary, volume_z=0.5)
        assert raw > 0

    def test_score_capped_at_10(self):
        summary = {"available": True, "put_call_ratio": 0.1, "call_volume": 10000, "put_volume": 500}
        raw, _ = score_unusual_options_activity(summary, volume_z=5.0)
        assert raw <= 10.0


# ── score_post_trade_performance ───────────────────────────────────────────


class TestScorePostTradePerformance:
    def test_20_percent_gain(self):
        raw, _ = score_post_trade_performance(20.0)
        assert raw == 10.0

    def test_10_percent_gain(self):
        raw, _ = score_post_trade_performance(12.0)
        assert raw == 7.0

    def test_5_percent_gain(self):
        raw, _ = score_post_trade_performance(6.0)
        assert raw == 5.0

    def test_flat(self):
        raw, _ = score_post_trade_performance(0.5)
        assert raw == 3.0

    def test_loss(self):
        raw, reasons = score_post_trade_performance(-5.0)
        assert raw == 1.0
        assert any("does not support" in r for r in reasons)

    def test_none_returns_neutral(self):
        raw, reasons = score_post_trade_performance(None)
        assert raw == 3.0
        assert any("Insufficient" in r for r in reasons)


# ── score_committee_alignment ──────────────────────────────────────────────


class TestScoreCommitteeAlignment:
    def test_intelligence_sector_tech(self):
        info = {"sector": "Technology", "industry": "Semiconductors"}
        raw, reasons = score_committee_alignment(info)
        assert raw == 8.0
        assert any("Intelligence" in r for r in reasons)

    def test_unrelated_sector(self):
        info = {"sector": "Consumer Cyclical", "industry": "Retail"}
        raw, _ = score_committee_alignment(info)
        assert raw == 3.0

    def test_no_sector_returns_default(self):
        raw, _ = score_committee_alignment({})
        assert raw == 2.0


# ── score_trade_size_anomaly ───────────────────────────────────────────────


class TestScoreTradeSize:
    def _make_txs(self, amounts):
        return [{"amount": a} for a in amounts]

    def test_large_trade_high_score(self):
        history = self._make_txs(
            ["$15,001 - $50,000"] * 20
            + ["$50,001 - $100,000"] * 5
        )
        big_tx = {"amount": "$1,000,001 - $5,000,000"}
        raw, reasons = score_trade_size_anomaly(big_tx, history)
        assert raw == 8.0

    def test_normal_size_low_score(self):
        amounts = ["$15,001 - $50,000"] * 30
        tx = {"amount": "$15,001 - $50,000"}
        raw, _ = score_trade_size_anomaly(tx, self._make_txs(amounts))
        assert raw == 2.0

    def test_missing_amount_returns_default(self):
        raw, _ = score_trade_size_anomaly({}, [])
        assert raw == 2.0

    def test_too_few_history_returns_default(self):
        raw, _ = score_trade_size_anomaly(
            {"amount": "$100,001 - $250,000"},
            [{"amount": "$15,001 - $50,000"}],
        )
        assert raw == 2.0


# ── compute_confidence_score (integration) ─────────────────────────────────


class TestComputeConfidenceScore:
    def _build_inputs(self, *, post_return=15.0, pcr=0.3, volume_z=3.0, sector="Technology"):
        transaction = {
            "ticker": "NVDA",
            "transaction_date": "2024-01-01",
            "disclosure_date": "2024-01-04",  # 3-day gap → high timing score
            "amount": "$1,000,001 - $5,000,000",
            "type": "purchase",
        }
        all_txs = [
            {"amount": "$15,001 - $50,000"} for _ in range(20)
        ] + [transaction]
        options = {
            "available": True,
            "put_call_ratio": pcr,
            "call_volume": 5000,
            "put_volume": int(5000 * pcr),
            "expiry": "2024-02-16",
        }
        company_info = {"sector": sector, "industry": "Semiconductors"}
        return transaction, all_txs, options, company_info

    def test_high_scoring_trade_meets_threshold(self):
        tx, all_txs, opts, info = self._build_inputs()
        result = compute_confidence_score(
            transaction=tx,
            all_transactions=all_txs,
            price_df=None,
            options_summary=opts,
            company_info=info,
            volume_z=3.0,
            post_trade_return=22.0,
        )
        assert isinstance(result, ScoreResult)
        assert result.composite_score > 0
        assert result.meets_threshold  # should score well above 60

    def test_low_scoring_trade_below_threshold(self):
        tx, all_txs, opts, info = self._build_inputs(
            post_return=-10.0,
            pcr=2.0,
            volume_z=-0.5,
            sector="Consumer Cyclical",
        )
        # Override dates to produce low timing score
        tx = dict(tx, transaction_date="2024-01-01", disclosure_date="2024-03-20")
        result = compute_confidence_score(
            transaction=tx,
            all_transactions=all_txs,
            price_df=None,
            options_summary=opts,
            company_info=info,
            volume_z=-0.5,
            post_trade_return=-10.0,
        )
        assert not result.meets_threshold

    def test_result_has_summary_string(self):
        tx, all_txs, opts, info = self._build_inputs()
        result = compute_confidence_score(
            transaction=tx,
            all_transactions=all_txs,
            price_df=None,
            options_summary=opts,
            company_info=info,
            volume_z=3.0,
            post_trade_return=22.0,
        )
        summary = result.summary()
        assert "NVDA" in summary
        assert "Composite score" in summary
        assert "threshold" in summary.lower()
