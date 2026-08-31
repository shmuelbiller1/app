# Quant Scanner — Automated Market Scanner

A GitHub Actions-powered quantitative research scanner for:

- **Scanner A — Leveraged ETF Reversal:** finds leveraged/inverse ETFs near 52-week highs and ranks statistical overextension and historical downside behavior.
- **Scanner B — Short Squeeze Setup:** combines short-interest data with price/volume momentum, float constraints, and options eligibility.
- **Alerts:** optional Discord webhook alerts for high-score candidates.
- **Dashboard:** generates a static HTML report suitable for GitHub Pages.

> **Research only:** scores and probabilities are historical estimates, not guarantees or investment advice.

## Data architecture

```text
Finnhub OHLCV ───────┐
                     ├── Candidate filters ── Scores ── Historical validation ── Dashboard
FINRA short data ────┘                                      │
                                                            └── Alerts
Alpha Vantage options ───── finalist-only options validation ┘
```

Options requests are intentionally made **only after** the cheap price/short-interest filters, which keeps API usage manageable.

## GitHub setup

Add repository secrets under **Settings → Secrets and variables → Actions**:

- `FINNHUB_API_KEY` — required
- `ALPHA_VANTAGE_API_KEY` — optional; used only for finalist options checks
- `DISCORD_WEBHOOK_URL` — optional; enables alerts

Do not put API keys in source code, commits, README files, or browser-side JavaScript.

For FINRA, keep the client secret out of the repository. The FINRA adapter is isolated so its authentication/data-delivery method can be configured safely.

## Run locally

```bash
pip install -r requirements.txt
python scanner.py
```

The scanner produces a JSON data file and an HTML dashboard in `site/`.

## GitHub Actions

The workflow runs on weekdays and also supports manual execution from **Actions → Quant Market Scanner → Run workflow**.

To publish the dashboard, enable **Settings → Pages → Source → GitHub Actions**.

## What the scores mean

### Scanner A

The reversal model uses normalized measures such as:

- distance from moving averages
- volatility-adjusted extension (z-score)
- 52-week-high proximity
- momentum/acceleration
- volatility and volume anomalies
- historical conditional downside frequency

The system should report `P(return < 0 | feature state)` for defined horizons such as 1, 3, 5, and 10 sessions rather than claiming that an ETF *must* reverse.

### Scanner B

The squeeze model evaluates multiple conditions together:

- short interest relative to float
- days to cover
- change in short interest
- relative volume
- price acceleration
- float/liquidity constraints
- options activity when available

Short interest alone is **not** treated as a squeeze signal.

## Next development stages

1. Replace the starter universe with an automatically maintained leveraged/inverse ETF universe.
2. Add robust FINRA ingestion and ticker/identifier reconciliation.
3. Add leakage-safe historical feature snapshots and walk-forward backtesting.
4. Calibrate probabilities rather than treating raw win rates as calibrated probabilities.
5. Add transaction costs, slippage, borrow constraints, and liquidity filters.
6. Add finalist-only options-chain validation.
7. Add dashboard charts, score explanations, and Discord alerts.
