# Quant Scanner — Market-State Discovery & Signal Laboratory

A continuously running quantitative research scanner designed around **two specific market states**:

### Scanner A — Leveraged-Fund Reversal
Finds leveraged/inverse ETFs that are:

- near or making a 52-week high;
- statistically overextended;
- liquid enough to matter;
- outside the configured technology/biotechnology exclusions;
- supported by historical comparable states that can be tested for subsequent downside.

### Scanner B — Options-Eligible Short-Squeeze Setup
Finds non-tech/non-biotech stocks and ETFs with combinations of:

- elevated short interest / short float;
- days-to-cover / crowded positioning;
- rising short-interest evidence when available;
- accelerating price and volume;
- sufficient company and trading liquidity;
- listed options with meaningful liquidity when the options layer can be queried.

The system is a **research and ranking engine, not an automatic trading system**. A score is not a probability, and a historical probability is not a guarantee of future performance.

---

## The important part: ZERO-KEY MODE

The scanner is designed to work **without proprietary API keys**.

The default research path uses public `yfinance` / Yahoo Finance data for:

- historical OHLCV;
- market screening;
- company metadata when exposed;
- public short-interest fields when exposed;
- listed option chains for finalist checks.

The calculations themselves are local Python calculations. The program does not require Finnhub, Alpha Vantage, or FINRA just to run the core scanning engine.

Optional providers improve coverage and authority when their credentials are available:

| Provider | Secret | Role | Required? |
|---|---|---|---|
| Finnhub | `FINNHUB_API_KEY` | supplemental company/market data | **No** |
| Alpha Vantage | `ALPHA_VANTAGE_API_KEY` | supplemental options data | **No** |
| FINRA | `FINRA_CLIENT_ID` + `FINRA_CLIENT_SECRET` | authoritative short-interest / Reg SHO enrichment | **No** |
| Discord | `DISCORD_WEBHOOK_URL` | alerts | **No** |

**Missing data is never replaced with fake numbers.** The dashboard reports when a field or provider is unavailable.

---

## What the scanner actually does

```text
PUBLIC / OPTIONAL DATA
        |
        v
UNIVERSE DISCOVERY
        |
        +-------------------------+
        |                         |
        v                         v
 SCANNER A                   SCANNER B
 Leveraged ETF               Short-Squeeze
 Reversal State              State Detector
        |                         |
        +-----------+-------------+
                    v
             CANDIDATE RANKING
                    |
                    v
          HISTORICAL EVIDENCE
                    |
                    +--> comparable historical states
                    +--> +1 / +3 / +5 / +10 / +20 outcomes
                    +--> bootstrap uncertainty
                    +--> out-of-sample validation
                    |
                    v
             OPTIONS ENRICHMENT
              finalist-only
                    |
                    v
              DASHBOARD + ALERTS
```

The purpose is to answer **"is this market state unusual, and has this kind of state historically mattered?"**, not simply "is RSI high?".

---

## Scanner A — what the result means

The reversal score is a **ranking score**, not a probability.

The model considers features including:

- 52-week-high proximity;
- distance from 20/50-day trend;
- volatility-adjusted extension (Z-score);
- RSI;
- relative volume;
- recent momentum;
- historical analogs.

When enough comparable historical observations exist, the program reports something like:

```text
Reversal score:             89.4 / 100
Historical 5D downside:     68.2%
Comparable observations:    117
95% bootstrap interval:     61.0% — 75.4%
Evidence quality:            STRONG
```

When there are too few comparable cases, the probability is **not fabricated**. It is shown as unavailable/insufficient evidence.

---

## Scanner B — what the result means

The squeeze scanner treats short interest as only one component.

It looks for agreement among:

```text
CROWDING
short interest / float
short interest change
days to cover

BUYING PRESSURE
price momentum
relative volume
volume acceleration

TRADEABILITY
market cap
average dollar volume
float / size

OPTIONS
open interest
option volume
bid/ask spreads
call/put structure
gamma context when calculable
```

FINRA short interest and FINRA Reg SHO / short-sale-volume data are treated as **separate evidence streams** when those optional data are available.

A high short-interest number by itself does not trigger the strongest alert.

---

## Signal Laboratory

Every emitted candidate can become a persistent research event.

The laboratory records the signal state at time `t` and later attaches actual market outcomes:

```text
Signal at t
   |
   +--> +1 trading session
   +--> +3
   +--> +5
   +--> +10
   +--> +20
```

It then reports:

- sample size;
- positive/downside rate;
- mean return;
- median return;
- best/worst outcome;
- maximum favorable excursion;
- maximum adverse excursion;
- bootstrap confidence intervals;
- chronological out-of-sample results;
- score-bucket results.

This prevents the application from silently turning a backtest into a claimed prediction.

---

## Options layer

Options are deliberately checked **after** the cheap market filters.

The scanner can inspect finalist option chains for:

- expirations;
- call/put open interest;
- call/put volume;
- bid/ask spreads;
- option liquidity;
- implied volatility when supplied by the source;
- approximate dollar gamma when the chain provides the required fields.

The application labels the options state explicitly:

```text
PASS
WEAK
NO_OPTIONS
NO_DATA
ERROR
NOT_CHECKED
```

It does not turn missing options information into a fake PASS.

---

## Alerts

Alerts are **optional** and currently use Discord.

The alert secret is:

```text
DISCORD_WEBHOOK_URL
```

The alert engine is intended to notify you about meaningful state changes rather than spam the same ticker every scan. A candidate can be represented as:

```text
NEW
STRENGTHENING
```

and the alert state includes cooldown logic.

An example alert is conceptually:

```text
NEW | B HTZ | score=88.7
short/float=24.1% | DTC=6.2 | options=PASS
```

or for Scanner A:

```text
NEW | A XYZ | score=91.2
P5d-down=71.4% | n=126 | options=PASS
```

**Alerts are research notifications, not trade orders.**

---

## GitHub Actions schedule

The GitHub Actions workflow is intended to run repeatedly during the U.S. regular equity session, with the Python process enforcing the real New York trading window.

Target session:

```text
09:30 AM ET  →  04:00 PM ET
```

The schedule is approximately every 30 minutes. GitHub Actions is a scheduled automation system, so execution can occasionally be delayed; it is not an exchange-grade real-time feed.

---

## Secrets — what users should add

### You can run the core scanner with **nothing** in Secrets.

For the best optional enrichment, add:

```text
FINRA_CLIENT_ID
FINRA_CLIENT_SECRET
```

These improve Scanner B with FINRA short-interest/Reg SHO enrichment.

Optional supplemental providers:

```text
FINNHUB_API_KEY
ALPHA_VANTAGE_API_KEY
```

Optional alerts:

```text
DISCORD_WEBHOOK_URL
```

### Where to add them

In GitHub:

```text
Repository
  -> Settings
  -> Secrets and variables
  -> Actions
  -> Repository secrets
  -> New repository secret
```

Add the **name exactly as shown above**, then paste the private value into the Value field.

Never put secret values in:

- source code;
- the README;
- browser/frontend code;
- committed `.env` files;
- screenshots or logs.

The repository includes an `.env.example` template with blank values for local development.

---

## Run locally

```bash
pip install -r scanner/requirements.txt
python scanner/run_scanner.py
```

The scanner writes the dashboard data into `frontend/public/` and the Signal Laboratory maintains its research history separately.

---

## Why this is different from a normal stock screener

A normal screener might say:

> RSI > 70, therefore short.

This project tries to say:

> This security is in a statistically unusual state; here are the independent pieces of evidence; here is how often comparable historical states produced the requested outcome; here is the uncertainty; here is the out-of-sample result; and here is whether the security/options are actually tradeable.

That distinction is the core design goal.

---

## Current limitations

Public market data can be delayed, incomplete, changed, or unavailable. Public short-interest data may be stale. Options data can vary in completeness and liquidity. Approximate gamma is a model-derived context metric, not direct dealer-position data.

The Signal Laboratory needs accumulated historical observations before its out-of-sample statistics become meaningful.

The system should therefore be judged by **measured live performance over time**, not by how impressive its initial scores look.
