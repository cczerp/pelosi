"""Collect comprehensive market data for a given ticker.

Uses *yfinance* to pull price/volume history and basic options chain
information — both are freely available without an API key.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import pandas as pd
import yfinance as yf

from pelosi_bot.config import PRICE_LOOKBACK_DAYS

logger = logging.getLogger(__name__)


# ── Price / volume ─────────────────────────────────────────────────────────


def fetch_price_history(
    ticker: str,
    lookback_days: int = PRICE_LOOKBACK_DAYS,
) -> pd.DataFrame:
    """Return a DataFrame of daily OHLCV data for *ticker*.

    Columns: Open, High, Low, Close, Volume (plus Dividends and Stock Splits
    from yfinance).  The DataFrame index is a ``DatetimeIndex``.

    Returns an empty DataFrame when no data can be retrieved (e.g., invalid
    ticker or network issue).
    """
    end = date.today()
    start = end - timedelta(days=lookback_days)
    try:
        df = yf.download(ticker, start=str(start), end=str(end), progress=False, auto_adjust=True)
        if df.empty:
            logger.warning("No price data returned for %s", ticker)
        return df
    except Exception as exc:  # noqa: BLE001
        logger.error("Error fetching price history for %s: %s", ticker, exc)
        return pd.DataFrame()


def compute_volume_z_score(price_df: pd.DataFrame, window: int = 20) -> float | None:
    """Compute the z-score of the most-recent day's volume relative to the
    trailing *window*-day mean/std.

    A high positive z-score (e.g. > 2) indicates unusual volume activity
    that may accompany informed trading.

    Returns ``None`` when the DataFrame is too short or lacks a ``Volume``
    column.
    """
    if price_df.empty or "Volume" not in price_df.columns:
        return None
    vol = price_df["Volume"].dropna()
    if len(vol) < window + 1:
        return None
    rolling = vol.iloc[-(window + 1) : -1]
    mean = rolling.mean()
    std = rolling.std()
    if std == 0:
        return None
    last_vol = vol.iloc[-1]
    return float((last_vol - mean) / std)


def compute_post_trade_return(
    price_df: pd.DataFrame,
    trade_date: date,
    days_forward: int = 30,
) -> float | None:
    """Compute the percentage price return starting from *trade_date* over
    the next *days_forward* trading days.

    Returns ``None`` when insufficient data is available.
    """
    if price_df.empty or "Close" not in price_df.columns:
        return None

    close = price_df["Close"].dropna()
    close.index = pd.to_datetime(close.index)

    # Find the first close on or after trade_date
    after = close[close.index >= pd.Timestamp(trade_date)]
    if after.empty:
        return None
    start_price = after.iloc[0]

    end_slice = after.iloc[:days_forward]
    if len(end_slice) < 2:
        return None
    end_price = end_slice.iloc[-1]

    return float((end_price - start_price) / start_price * 100)


# ── Options activity ───────────────────────────────────────────────────────


def fetch_options_summary(ticker: str) -> dict[str, Any]:
    """Return a summary dict of the nearest-expiry options chain.

    Keys returned:
    - ``call_volume``: total call volume across all strikes
    - ``put_volume``: total put volume across all strikes
    - ``put_call_ratio``: put / call volume ratio (None if calls == 0)
    - ``expiry``: expiry date string used
    - ``available``: bool — False when no options data could be retrieved

    A low put/call ratio (many calls, few puts) on the nearest expiry is one
    indicator of unusual bullish positioning.
    """
    summary: dict[str, Any] = {
        "call_volume": None,
        "put_volume": None,
        "put_call_ratio": None,
        "expiry": None,
        "available": False,
    }
    try:
        tk = yf.Ticker(ticker)
        expiries = tk.options
        if not expiries:
            return summary
        nearest = expiries[0]
        chain = tk.option_chain(nearest)
        call_vol = int(chain.calls["volume"].sum())
        put_vol = int(chain.puts["volume"].sum())
        summary.update(
            {
                "call_volume": call_vol,
                "put_volume": put_vol,
                "put_call_ratio": (put_vol / call_vol) if call_vol > 0 else None,
                "expiry": nearest,
                "available": True,
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not fetch options for %s: %s", ticker, exc)
    return summary


# ── Company info ────────────────────────────────────────────────────────────


def fetch_company_info(ticker: str) -> dict[str, Any]:
    """Return basic company metadata (sector, industry, market cap, etc.)
    via yfinance's ``Ticker.info`` property.

    Returns an empty dict on failure.
    """
    try:
        return yf.Ticker(ticker).info or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not fetch company info for %s: %s", ticker, exc)
        return {}
