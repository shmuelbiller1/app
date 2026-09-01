# Quant Scanner — Market-State Discovery & Signal Laboratory

A continuously running quantitative research scanner built around **two specific market states**:

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
- sufficient trading liquidity;
- listed options with meaningful liquidity when the options layer can be queried.

The system is a **research and ranking engine, not an automatic trading system**. A score is not a probability, and a historical probability is not a guarantee of future performance.

---

## Start here — publishing / setup guide

### You do NOT need API keys to use the core scanner

The default scanner runs in **ZERO-KEY MODE** using public Yahoo Finance/yfinance data. That covers:

- historical OHLCV;
- public market screening;
- company metadata when exposed;
- public short-interest fields when exposed;
- listed option chains for finalist checks;
- all local calculations, ranking, historical analog analysis and Signal Laboratory processing.

So a new viewer can clone/publish the project and run the core scanner **without buying or configuring a market-data API**.

### Optional: FINRA enrichment

The only external credential currently used by the scanner for additional market-data authority is FINRA:

```text
FINRA_CLIENT_ID
FINRA_CLIENT_SECRET
```

These are optional. When present, the workflow downloads FINRA short-interest / Reg SHO enrichment and the scanner uses FINRA short-interest fields when available. Without them, Scanner B continues using public Yahoo/yfinance short-interest fields.

### Optional: email alerts

Email is also optional. It is independent of market-data credentials.

Add these GitHub **Repository secrets**:

```text
SMTP_HOST
SMTP_PORT
SMTP_USERNAME
SMTP_PASSWORD
SMTP_USE_TLS
SMTP_USE_SSL
ALERT_EMAIL_FROM
ALERT_EMAIL_TO
```

Recommended common SMTP setup is port `587` with TLS:

```text
SMTP_PORT=587
SMTP_USE_TLS=1
SMTP_USE_SSL=0
```

Do not use TLS and SSL simultaneously. Some mail providers instead use SSL on port `465`; in that case use:

```text
SMTP_PORT=465
SMTP_USE_TLS=0
SMTP_USE_SSL=1
```

`ALERT_DASHBOARD_URL` is optional and should be added as a GitHub **Repository variable**, not a secret, if you want the email to contain a dashboard link.

### Where GitHub secrets go

```text
GitHub repository
  → Settings
  → Secrets and variables
  → Actions
  → Repository secrets
  → New repository secret
```

Add each secret name exactly as shown above and paste the private value into **Value**.

For a public repository, **never put secret values in source code, README files, frontend JavaScript, screenshots, committed `.env` files, or logs**. The repository's `.env.example` contains names only and blank values.

### What is NOT needed

You do **not** need to add:

```text
FINNHUB_API_KEY
ALPHA_VANTAGE_API_KEY
PUSHOVER_APP_TOKEN
PUSHOVER_USER_KEY
DISCORD_WEBHOOK_URL
```

Those are not part of the active cloud scanner configuration. The alert path is SMTP email, and the local Windows companion provides native Windows notifications.

---

## Architecture

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
                    +--> chronological out-of-sample validation
                    |
                    v
             OPTIONS ENRICHMENT
              finalist-only
                    |
             +------+------+
             |             |
             v             v
        DASHBOARD       ALERTS
                       SMTP email
             |
             v
       Windows companion
       (local PC only)
```

The purpose is to answer **"is this market state unusual, and has this kind of state historically mattered?"**, not simply "is RSI high?".

---

## Scanner A — what the result means

The reversal score is a **ranking score**, not a probability.

The model considers:

- 52-week-high proximity;
- volatility-adjusted extension (Z-scores);
- RSI;
- relative volume;
- recent momentum;
- historical analogs built from information available at the historical signal date.

When enough comparable observations exist, the program reports a historical conditional frequency such as:

```text
Reversal score:             89.4 / 100
Historical 5D downside:     68.2%
Comparable observations:    117
95% bootstrap interval:     61.0% — 75.4%
Evidence quality:            STRONG
```

When there are too few comparable cases, the probability is **not fabricated**. It is unavailable/insufficient evidence.

---

## Scanner B — what the result means

The squeeze scanner treats short interest as only one component.

It looks for agreement among:

```text
CROWDING
short interest / float
days to cover
short-interest change when available

BUYING PRESSURE
price momentum
relative volume

TRADEABILITY
market size
average dollar volume
price/liquidity filters

OPTIONS
open interest
option volume
bid/ask spreads
call/put structure
gamma context when calculable
```

FINRA short interest and FINRA Reg SHO / short-sale-volume data are treated as **separate evidence streams** when FINRA enrichment is configured.

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

It reports:

- sample size;
- positive/downside rate;
- mean and median return;
- best/worst outcome;
- maximum favorable excursion;
- maximum adverse excursion;
- bootstrap confidence intervals;
- chronological out-of-sample results;
- score-bucket results.

This prevents a backtest from silently becoming a claimed prediction.

The lab needs accumulated live observations before its out-of-sample statistics become meaningful.

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

**Gamma is model-derived context, not direct dealer-position data.**

---

## Alerts

### GitHub cloud alert: email

The GitHub Actions workflow runs `scanner/smart_alerts.py` after each in-session scan. It keeps state so the same qualifying signal is not emailed every 30 minutes.

Alert states are:

```text
NEW
STRENGTHENING
INVALIDATED
```

The default threshold is score `85`, with a five-point strengthening threshold and a four-hour per-signal cooldown.

Email contains the signal score and supporting evidence. It is explicitly labeled as a research signal, not a trade order.

### Windows desktop alert

The optional `desktop/desktop_agent.py` companion runs the same scanner locally on a Windows PC during the U.S. regular session and can produce native Windows toast notifications for:

```text
NEW SIGNAL
SIGNAL STRENGTHENING
SIGNAL WEAKENING
SIGNAL INVALIDATED
```

The Windows companion does not require market-data API credentials. It uses the same public-data scanner locally.

Install it from Windows with:

```text
desktop/install_windows.ps1
```

The PC must be on for local Windows notifications. Email works independently through GitHub Actions.

---

## GitHub Actions schedule

The workflow runs on a broad UTC schedule and `scanner/session_gate.py` enforces the real U.S. regular-session boundary:

```text
09:30 AM ET → 04:00 PM ET
```

The intended scan interval is approximately 30 minutes. GitHub Actions scheduling is not exchange-grade real-time execution and can occasionally be delayed.

The workflow can also be started manually from:

```text
Actions → Quant Market Scanner → Run workflow
```

---

## Run locally

```bash
pip install -r scanner/requirements.txt
python scanner/run_scanner.py
```

The scanner writes dashboard data to `frontend/public/scanner-data.json` and maintains research history in the Signal Laboratory database.

For Windows desktop notifications:

```text
desktop/install_windows.ps1
```

---

## Data truth rules

This project deliberately avoids several dangerous shortcuts:

1. **No fake probability fallback.** Historical probabilities require enough comparable observations.
2. **No fake options data.** Missing OI, volume, spreads or IV remain missing.
3. **No automatic "52-week high = must fall" assumption.** Scanner A uses conditional historical analogs.
4. **No automatic "high short interest = squeeze" assumption.** Scanner B requires price/volume confirmation and tradeability filters.
5. **No look-ahead in historical analog construction.** A historical signal only uses information available at that historical date.
6. **FINRA short interest and Reg SHO daily short-sale volume remain separate evidence streams.**
7. **Scores are rankings, not probabilities.**
8. **Approximate gamma is not presented as direct dealer positioning.**
9. **Public data can be delayed, stale, incomplete or temporarily unavailable.**

---

## Current limitations

Public market data can be delayed, incomplete, changed, rate-limited, or unavailable. Public short-interest fields may be stale. Options chains can vary in completeness and liquidity. FINRA enrichment depends on valid credentials and successful API access.

GitHub Actions is an automation platform, not a low-latency trading system.

The Signal Laboratory becomes more informative as it accumulates a larger chronological live sample. Initial scores should therefore be treated as research candidates, not validated trading edges.

The system should ultimately be judged by **measured live performance and out-of-sample evidence over time**, not by how impressive its initial rankings look.
