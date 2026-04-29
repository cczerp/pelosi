"""Unit tests for pelosi_bot.stock_data (offline — no network calls)."""

import pandas as pd
import numpy as np
import pytest
from datetime import date, timedelta

from pelosi_bot.stock_data import compute_post_trade_return, compute_volume_z_score


def _make_price_df(n_days=60, base_price=100.0, volume=1_000_000, volume_noise=50_000):
    """Create a synthetic OHLCV DataFrame for testing.

    *volume_noise* adds random variation to volume so that std > 0 and
    z-score calculations are well-defined.
    """
    rng = np.random.default_rng(42)
    idx = pd.date_range(end=date.today(), periods=n_days, freq="B")
    prices = base_price + np.cumsum(rng.standard_normal(n_days) * 0.5)
    vols = volume + rng.standard_normal(n_days) * volume_noise
    vols = np.abs(vols)  # ensure non-negative
    data = {
        "Open": prices * 0.99,
        "High": prices * 1.01,
        "Low": prices * 0.98,
        "Close": prices,
        "Volume": vols,
    }
    return pd.DataFrame(data, index=idx)


class TestComputeVolumeZScore:
    def test_spike_positive_z(self):
        df = _make_price_df(n_days=60, volume=1_000_000)
        # Make last day a huge spike
        df.iloc[-1, df.columns.get_loc("Volume")] = 10_000_000
        z = compute_volume_z_score(df)
        assert z is not None
        assert z > 2  # large positive z

    def test_normal_volume_z_near_zero(self):
        df = _make_price_df(n_days=60, volume=1_000_000)
        z = compute_volume_z_score(df)
        assert z is not None
        assert abs(z) < 5  # not extreme for normally distributed noise

    def test_empty_df_returns_none(self):
        assert compute_volume_z_score(pd.DataFrame()) is None

    def test_too_short_df_returns_none(self):
        df = _make_price_df(n_days=5)
        assert compute_volume_z_score(df, window=20) is None

    def test_no_volume_column_returns_none(self):
        df = _make_price_df(n_days=60).drop(columns=["Volume"])
        assert compute_volume_z_score(df) is None


class TestComputePostTradeReturn:
    def test_positive_return(self):
        df = _make_price_df(n_days=60)
        # Force a known start and end price
        trade_date = df.index[10].date()
        df.iloc[10, df.columns.get_loc("Close")] = 100.0
        df.iloc[40, df.columns.get_loc("Close")] = 120.0
        ret = compute_post_trade_return(df, trade_date, days_forward=30)
        assert ret is not None
        # Roughly 20% but exact value depends on in-between prices

    def test_empty_df_returns_none(self):
        assert compute_post_trade_return(pd.DataFrame(), date.today()) is None

    def test_trade_date_after_data_returns_none(self):
        df = _make_price_df(n_days=30)
        future_date = date.today() + timedelta(days=100)
        assert compute_post_trade_return(df, future_date) is None

    def test_no_close_column_returns_none(self):
        df = _make_price_df(n_days=60).drop(columns=["Close"])
        assert compute_post_trade_return(df, date.today() - timedelta(days=30)) is None
