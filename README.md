# pelosi — copy-trade intelligence bot

A Python bot that continuously monitors **public** U.S. House financial-disclosure filings for trades by Nancy Pelosi, collects comprehensive market data for each ticker, and scores each trade for insider-trading indicators before deciding whether to act on it.

> **Legal note** — this bot reads only *publicly available* government data.
> The House financial-disclosure feed is published under U.S. law (STOCK Act, 2012)
> and is freely accessible at <https://disclosures-clerk.house.gov/FinancialDisclosure>.
> Academic research (Ziobrowski et al. 2004 / 2011) has documented systematic
> outperformance by sitting members of Congress; this bot quantifies those signals.

---

## How it works

```
Disclosure feed (housestockwatcher.com)
        │
        ▼
  Filter transactions ──► skip non-Pelosi rows
        │
        ▼
  For each new trade:
    ├── Fetch price / volume history   (yfinance)
    ├── Fetch options chain summary    (yfinance)
    └── Fetch company info / sector    (yfinance)
        │
        ▼
  Compute insider-trading confidence score (0–100)
    ├── Legislative timing          (30 pts)
    ├── Unusual options activity    (25 pts)
    ├── Post-trade performance      (20 pts)
    ├── Committee–sector alignment  (15 pts)
    └── Trade-size anomaly          (10 pts)
        │
        ▼
  Score ≥ MIN_CONFIDENCE_SCORE (default 60)?
    ├── YES → log / act on trade
    └── NO  → skip (not enough evidence)
```

### Scoring factors

| Factor | Weight | Rationale |
|---|---|---|
| **Legislative timing** | 30 | Trades just before bill passage or regulatory announcements are the strongest predictor of an information advantage (Ziobrowski et al. 2004) |
| **Unusual options activity** | 25 | A surge in cheap call options days before a positive catalyst is a classic informed-trading footprint |
| **Post-trade performance** | 20 | Retrospective evidence — strong 30-day appreciation after a disclosed buy is consistent with prior knowledge of a catalyst |
| **Committee alignment** | 15 | Members on committees with jurisdiction over a sector (e.g. House Intelligence → Technology) have non-public regulatory insight |
| **Trade-size anomaly** | 10 | An unusually large trade relative to the member's own history signals elevated conviction |

The bot **will not act** unless all signals combine to a score ≥ `MIN_CONFIDENCE_SCORE`.  This guards against false positives from routine portfolio rebalancing.

---

## Quickstart

```bash
# Install dependencies
pip install -r requirements.txt

# Run a single scan (last 90 days)
python main.py --once

# Run a single scan with verbose output
python main.py --once --verbose

# Override the minimum confidence threshold
python main.py --once --threshold 70

# Run continuously (polls every hour by default)
python main.py
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `TARGET_REP` | `Nancy Pelosi` | Representative name to track |
| `MIN_CONFIDENCE_SCORE` | `60` | Minimum score before acting |
| `SCAN_INTERVAL_SECONDS` | `3600` | Polling frequency (continuous mode) |
| `PRICE_LOOKBACK_DAYS` | `90` | How many days of price history to fetch |

---

## Project layout

```
pelosi_bot/
├── __init__.py        — version
├── config.py          — all tuneable knobs
├── disclosures.py     — fetch & filter House disclosure feed
├── stock_data.py      — price, volume, options, company info (yfinance)
├── insider_score.py   — confidence scoring logic
└── bot.py             — orchestration + scheduler

main.py                — CLI entry point
tests/
├── test_disclosures.py
├── test_insider_score.py
└── test_stock_data.py
```

## Running tests

```bash
pip install pytest
python -m pytest tests/ -v
```

---

## References

* Ziobrowski, A. J. et al. (2004). *Abnormal Returns From the Common Stock Investments of the U.S. Senate*. Journal of Financial and Quantitative Analysis.
* Ziobrowski, A. J. et al. (2011). *Abnormal Returns From the Common Stock Investments of Members of the U.S. House of Representatives*. Business and Politics.
* STOCK Act (Stop Trading on Congressional Knowledge Act), Pub. L. 112-105, 2012.
