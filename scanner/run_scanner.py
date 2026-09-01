"""Zero-key-first quantitative market scanner.

Default mode requires NO proprietary API keys:
- yfinance public endpoints provide historical OHLCV, a market screener,
  company metadata and listed option chains.
- FINRA is an optional authoritative enrichment for short-interest data.

The calculations are local Python calculations. Missing provider data is
reported as missing; the scanner does not fabricate values.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "public"
OUT.mkdir(parents=True, exist_ok=True)

EXCLUDED_SECTORS = {
    "Technology", "Biotechnology", "Software", "Semiconductors", "Internet",
}
MIN_PRICE = 2.0
MIN_MARKET_CAP = 300_000_000
MIN_AVG_DOLLAR_VOLUME = 1_000_000
MAX_SQUEEZE_UNIVERSE = 750
FINALISTS_FOR_OPTIONS = 12


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_symbol(value) -> str:
    return str(value or "").strip().upper().replace(".", "-")


def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    d = series.diff()
    up = d.clip(lower=0)
    down = -d.clip(upper=0)
    ag = up.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    al = down.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def normalize_history(df: pd.DataFrame, symbol: str = "") -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    x = df.copy()
    if isinstance(x.columns, pd.MultiIndex):
        if symbol:
            try:
                x = x.xs(symbol, axis=1, level=-1)
            except Exception:
                x.columns = x.columns.get_level_values(0)
        else:
            x.columns = x.columns.get_level_values(0)
    required = {"Close", "High", "Low", "Volume"}
    if not required.issubset(set(x.columns)):
        return None
    return x[["Close", "High", "Low", "Volume"]].dropna().copy()


def history(symbol: str, period: str = "2y") -> pd.DataFrame | None:
    try:
        return normalize_history(
            yf.download(symbol, period=period, interval="1d", auto_adjust=False,
                        progress=False, threads=False), symbol
        )
    except Exception as exc:
        print(f"history {symbol}: {exc}")
        return None


def metrics(df: pd.DataFrame) -> dict[str, float]:
    c = df["Close"].astype(float)
    h = df["High"].astype(float)
    l = df["Low"].astype(float)
    v = df["Volume"].astype(float)
    sma20 = c.rolling(20).mean()
    sd20 = c.rolling(20).std()
    sma50 = c.rolling(50).mean()
    sd50 = c.rolling(50).std()
    sma200 = c.rolling(200).mean()
    px = float(c.iloc[-1])
    z20 = (px - float(sma20.iloc[-1])) / float(sd20.iloc[-1]) if sd20.iloc[-1] > 0 else 0.0
    z50 = (px - float(sma50.iloc[-1])) / float(sd50.iloc[-1]) if sd50.iloc[-1] > 0 else 0.0
    hi52 = float(h.tail(252).max())
    dist52 = (hi52 - px) / hi52 if hi52 > 0 else 1.0
    avgv = float(v.tail(20).mean())
    rv = float(v.iloc[-1] / avgv) if avgv > 0 else 0.0
    atr = float(pd.concat([
        h - l,
        (h - c.shift()).abs(),
        (l - c.shift()).abs(),
    ], axis=1).max(axis=1).rolling(14).mean().iloc[-1])
    atr_frac = atr / px if px > 0 else np.nan
    ret1 = px / float(c.iloc[-2]) - 1 if len(c) >= 2 else np.nan
    ret3 = px / float(c.iloc[-4]) - 1 if len(c) >= 4 else np.nan
    ret5 = px / float(c.iloc[-6]) - 1 if len(c) >= 6 else np.nan
    ret20 = px / float(c.iloc[-21]) - 1 if len(c) >= 21 else np.nan
    return {
        "price": px,
        "z20": z20,
        "z50": z50,
        "rsi14": float(rsi(c).iloc[-1]),
        "distance_52w": dist52 * 100,
        "relative_volume": rv,
        "momentum_1d": ret1 * 100,
        "momentum_3d": ret3 * 100,
        "momentum_5d": ret5 * 100,
        "momentum_20d": ret20 * 100,
        "atr_fraction": atr_frac,
        "avg_volume_20": avgv,
        "sma20": float(sma20.iloc[-1]),
        "sma50": float(sma50.iloc[-1]),
        "sma200": float(sma200.iloc[-1]) if np.isfinite(sma200.iloc[-1]) else np.nan,
    }


def state_signature(df: pd.DataFrame, pos: int) -> np.ndarray | None:
    if pos < 20:
        return None
    c = df["Close"].astype(float)
    h = df["High"].astype(float)
    v = df["Volume"].astype(float)
    sma = c.rolling(20).mean()
    sd = c.rolling(20).std()
    z = (c - sma) / sd
    rr = rsi(c)
    hi = h.rolling(252, min_periods=20).max()
    dist = (hi - c) / hi
    rv = v / v.rolling(20).mean()
    sig = np.array([z.iloc[pos], rr.iloc[pos], dist.iloc[pos], rv.iloc[pos]], dtype=float)
    return sig if np.all(np.isfinite(sig)) else None


def historical_analog_probability(df: pd.DataFrame, current: np.ndarray | None,
                                  horizon: int = 5, min_samples: int = 20):
    if current is None:
        return None, 0, []
    tol = np.array([0.50, 10.0, 0.04, 1.0], dtype=float)
    outcomes: list[float] = []
    for i in range(20, len(df) - horizon):
        sig = state_signature(df, i)
        if sig is not None and np.all(np.abs(sig - current) <= tol):
            outcomes.append(float(df["Close"].iloc[i + horizon] / df["Close"].iloc[i] - 1))
    if len(outcomes) < min_samples:
        return None, len(outcomes), outcomes
    return float(np.mean(np.asarray(outcomes) < 0)), len(outcomes), outcomes


def bootstrap_interval(binary: list[float], n_resamples: int = 500) -> list[float] | None:
    if len(binary) < 20:
        return None
    rng = np.random.default_rng(42)
    a = np.asarray(binary, dtype=float)
    means = [float(rng.choice(a, size=len(a), replace=True).mean()) for _ in range(n_resamples)]
    return [round(float(np.percentile(means, 2.5)), 4), round(float(np.percentile(means, 97.5)), 4)]


def safe_info(symbol: str) -> dict:
    try:
        info = yf.Ticker(symbol).get_info()
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


def industry_info(symbol: str) -> tuple[str, str, float | None, float | None, float | None]:
    info = safe_info(symbol)
    sector = str(info.get("sector") or "Unknown")
    industry = str(info.get("industry") or "Unknown")
    market_cap = _num(info.get("marketCap"))
    shares = _num(info.get("floatShares"))
    avgvol = _num(info.get("averageDailyVolume10Day")) or _num(info.get("averageVolume"))
    return sector, industry, market_cap, shares, avgvol


def _num(x):
    try:
        y = float(x)
        return y if np.isfinite(y) else None
    except Exception:
        return None


def free_short_screener() -> list[dict]:
    """Use Yahoo's public most-shorted-stocks screener; no credential required."""
    rows: dict[str, dict] = {}
    try:
        for offset in range(0, MAX_SQUEEZE_UNIVERSE, 250):
            page = yf.screen(
                "most_shorted_stocks", offset=offset, size=250,
                sortField="short_percentage_of_float.value", sortAsc=False,
            )
            quotes = page.get("quotes", []) if isinstance(page, dict) else []
            if not quotes:
                break
            for q in quotes:
                s = clean_symbol(q.get("symbol"))
                if s:
                    rows[s] = q
            if len(quotes) < 250:
                break
    except Exception as exc:
        print(f"Yahoo short screener unavailable: {exc}")
    return list(rows.values())


def quote_value(q: dict, *keys):
    for k in keys:
        if k in q and q[k] not in (None, ""):
            return q[k]
    return None


def black_scholes_gamma(spot: float, strike: float, t: float, rate: float, iv: float) -> float:
    if min(spot, strike, t, iv) <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * t) / (iv * math.sqrt(t))
    return norm.pdf(d1) / (spot * iv * math.sqrt(t))


def options_snapshot(symbol: str, spot: float) -> dict:
    """Public yfinance options data, finalist-only. No API key."""
    try:
        t = yf.Ticker(symbol)
        expirations = list(t.options or [])
        if not expirations:
            return {"status": "NO_OPTIONS"}
        use_exp = expirations[:3]
        calls, puts = [], []
        for exp in use_exp:
            chain = t.option_chain(exp)
            calls.append(chain.calls.copy())
            puts.append(chain.puts.copy())
        cdf = pd.concat(calls, ignore_index=True) if calls else pd.DataFrame()
        pdf = pd.concat(puts, ignore_index=True) if puts else pd.DataFrame()
        if cdf.empty and pdf.empty:
            return {"status": "NO_DATA"}

        def liquidity(frame):
            if frame.empty:
                return {"oi": 0, "vol": 0, "spread": None}
            oi = pd.to_numeric(frame.get("openInterest", 0), errors="coerce").fillna(0)
            vol = pd.to_numeric(frame.get("volume", 0), errors="coerce").fillna(0)
            bid = pd.to_numeric(frame.get("bid", 0), errors="coerce").fillna(0)
            ask = pd.to_numeric(frame.get("ask", 0), errors="coerce").fillna(0)
            mid = (bid + ask) / 2
            spread = ((ask - bid) / mid.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).dropna()
            return {
                "oi": int(oi.sum()), "vol": int(vol.sum()),
                "spread": float(spread.median()) if not spread.empty else None,
            }

        cl, pl = liquidity(cdf), liquidity(pdf)
        gex = 0.0
        for frame, sign in ((cdf, 1.0), (pdf, -1.0)):
            for _, r in frame.iterrows():
                strike = _num(r.get("strike")); iv = _num(r.get("impliedVolatility")); oi = _num(r.get("openInterest"))
                if not strike or not iv or not oi:
                    continue
                gamma = black_scholes_gamma(spot, strike, 30 / 365, 0.04, iv)
                gex += sign * gamma * spot * spot * 100 * oi
        spread_candidates = [x for x in [cl["spread"], pl["spread"]] if x is not None]
        spread = float(np.mean(spread_candidates)) if spread_candidates else None
        oi_total = cl["oi"] + pl["oi"]
        vol_total = cl["vol"] + pl["vol"]
        spread_score = max(0.0, 1.0 - min(spread or 1.0, 1.0))
        depth_score = min(1.0, math.log10(max(oi_total, 1)) / 5.0)
        activity_score = min(1.0, math.log10(max(vol_total, 1)) / 4.0)
        return {
            "status": "PASS" if oi_total >= 500 and vol_total > 0 and (spread is None or spread <= 0.30) else "WEAK",
            "expirations_checked": use_exp,
            "call_oi": cl["oi"], "put_oi": pl["oi"],
            "call_volume": cl["vol"], "put_volume": pl["vol"],
            "oi_total": oi_total, "volume_total": vol_total,
            "median_spread_pct": round(spread * 100, 2) if spread is not None else None,
            "call_put_oi_ratio": round(cl["oi"] / max(pl["oi"], 1), 3),
            "call_put_volume_ratio": round(cl["vol"] / max(pl["vol"], 1), 3),
            "net_dollar_gamma": round(gex, 0),
            "gamma_sign": "positive" if gex > 0 else "negative" if gex < 0 else "flat",
            "liquidity_score": round(100 * (0.45 * spread_score + 0.30 * depth_score + 0.25 * activity_score), 1),
        }
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc)}


def scan_a(signal_time: str) -> list[dict]:
    try:
        universe = json.loads((ROOT / "scanner" / "leveraged_etfs.json").read_text())
    except Exception:
        universe = []
    results = []
    for item in universe:
        symbol = clean_symbol(item.get("symbol"))
        if not symbol:
            continue
        df = history(symbol, "2y")
        if df is None or len(df) < 260:
            continue
        sector, industry, market_cap, _, _ = industry_info(symbol)
        if sector in EXCLUDED_SECTORS or industry in EXCLUDED_SECTORS:
            continue
        f = metrics(df)
        if f["price"] < MIN_PRICE or f["avg_volume_20"] * f["price"] < MIN_AVG_DOLLAR_VOLUME:
            continue
        current = state_signature(df, len(df) - 1)
        prob, n, outcomes = historical_analog_probability(df, current)
        ext = np.clip(f["z20"] / 3.0, 0, 1)
        near = np.clip(1 - f["distance_52w"] / 8.0, 0, 1)
        rfac = np.clip((f["rsi14"] - 55) / 25.0, 0, 1)
        rv = np.clip((f["relative_volume"] - 1) / 3.0, 0, 1)
        pf = np.clip((prob - 0.5) / 0.3, 0, 1) if prob is not None else 0
        score = 100 * (0.35 * ext + 0.30 * near + 0.15 * rfac + 0.10 * rv + 0.10 * pf)
        ci = bootstrap_interval([1.0 if r < 0 else 0.0 for r in outcomes])
        results.append({
            "ticker": symbol, "name": item.get("name", symbol), "sector": sector,
            "industry": industry, "leverage": item.get("leverage"), "price": round(f["price"], 4),
            "score": round(float(score), 1), "reversal_score": round(float(score), 1),
            "z20": round(f["z20"], 2), "z50": round(f["z50"], 2), "rsi14": round(f["rsi14"], 1),
            "distance_52w": round(f["distance_52w"], 2), "relative_volume": round(f["relative_volume"], 2),
            "momentum_5d": round(f["momentum_5d"], 2), "market_cap": market_cap,
            "avg_dollar_volume": round(f["avg_volume_20"] * f["price"]),
            "downside_probability_5d": round(prob * 100, 2) if prob is not None else None,
            "probability_sample": n, "probability_ci95": ci,
            "evidence_quality": "STRONG" if n >= 80 else "GOOD" if n >= 40 else "INSUFFICIENT",
            "options": {"status": "NOT_CHECKED"}, "signal_time": signal_time,
        })
    return sorted(results, key=lambda x: x["score"], reverse=True)[:40]


def scan_b(signal_time: str) -> list[dict]:
    quotes = free_short_screener()
    if not quotes:
        return []
    finra = {}
    try:
        p = os.getenv("FINRA_SHORT_CSV", "data/finra_short_interest.csv")
        if Path(p).exists():
            f = pd.read_csv(p)
            for _, r in f.iterrows():
                finra[clean_symbol(r.get("ticker"))] = r.to_dict()
    except Exception:
        pass
    candidates = []
    for q in quotes:
        s = clean_symbol(q.get("symbol"))
        if not s:
            continue
        price = _num(quote_value(q, "regularMarketPrice", "postMarketPrice", "price"))
        mcap = _num(quote_value(q, "marketCap", "intradaymarketcap"))
        si_pct = _num(quote_value(q, "shortPercentageOfFloat", "shortPctOfFloat", "short_percentage_of_float"))
        if si_pct is not None and si_pct < 1:
            si_pct *= 100
        dtc = _num(quote_value(q, "shortRatio", "daysToCoverShort"))
        short_shares = _num(quote_value(q, "sharesShort", "shortInterest"))
        if s in finra:
            r = finra[s]
            short_shares = _num(r.get("short_interest")) or short_shares
            dtc = _num(r.get("days_to_cover")) or dtc
            si_change = _num(r.get("si_change_pct"))
        else:
            si_change = _num(quote_value(q, "shortInterestChangePercent", "short_interest_percentage_change"))
        sector = str(quote_value(q, "sector") or "Unknown")
        industry = str(quote_value(q, "industry") or "Unknown")
        if sector == "Unknown" or industry == "Unknown":
            sec2, ind2, mc2, _, _ = industry_info(s)
            sector, industry = sec2, ind2
            mcap = mcap or mc2
        if sector in EXCLUDED_SECTORS or industry in EXCLUDED_SECTORS:
            continue
        df = history(s, "6mo")
        if df is None or len(df) < 30:
            continue
        f = metrics(df)
        price = price or f["price"]
        if not price or price < MIN_PRICE:
            continue
        dollar_vol = f["avg_volume_20"] * price
        if dollar_vol < MIN_AVG_DOLLAR_VOLUME:
            continue
        if si_pct is None or si_pct < 5:
            continue
        if f["relative_volume"] < 1.25 or f["momentum_5d"] <= 0:
            continue
        float_shares = _num(quote_value(q, "floatShares"))
        short_float = (short_shares / float_shares * 100) if short_shares and float_shares else si_pct
        crowd = np.clip((short_float or 0) / 30, 0, 1)
        dtc_s = np.clip((dtc or 0) / 10, 0, 1)
        change_s = np.clip(max(si_change or 0, 0) / 50, 0, 1)
        vol_s = np.clip(f["relative_volume"] / 5, 0, 1)
        mom_s = np.clip(max(f["momentum_5d"], 0) / 15, 0, 1)
        score = 100 * (0.30 * crowd + 0.15 * dtc_s + 0.15 * change_s + 0.22 * vol_s + 0.18 * mom_s)
        candidates.append({
            "ticker": s, "score": round(float(score), 1), "squeeze_score": round(float(score), 1),
            "sector": sector, "industry": industry, "price": round(float(price), 4),
            "market_cap": mcap, "short_float_pct": round(float(short_float), 2) if short_float is not None else None,
            "short_interest": short_shares, "days_to_cover": round(float(dtc), 2) if dtc is not None else None,
            "si_change_pct": round(float(si_change), 2) if si_change is not None else None,
            "relative_volume": round(f["relative_volume"], 2), "momentum_5d": round(f["momentum_5d"], 2),
            "avg_dollar_volume": round(dollar_vol), "options": {"status": "NOT_CHECKED"},
            "short_data_source": "FINRA" if s in finra else "YAHOO_PUBLIC_SCREENER",
            "signal_time": signal_time,
        })
    return sorted(candidates, key=lambda x: x["score"], reverse=True)[:40]


def enrich_options(items: list[dict]) -> list[dict]:
    for x in items[:FINALISTS_FOR_OPTIONS]:
        x["options"] = options_snapshot(x["ticker"], float(x["price"]))
    return items


def main():
    ts = now_utc()
    a = enrich_options(scan_a(ts))
    b = enrich_options(scan_b(ts))
    payload = {
        "generated_at": ts,
        "status": "LIVE — ZERO-KEY MODE",
        "data_sources": {
            "price_history": "yfinance public data",
            "market_screener": "Yahoo/yfinance public screener",
            "company_metadata": "Yahoo/yfinance public info",
            "options": "yfinance public option chains",
            "short_interest": "FINRA when configured; otherwise Yahoo/yfinance public screener",
            "finra": bool(os.getenv("FINRA_CLIENT_ID") and os.getenv("FINRA_CLIENT_SECRET")),
        },
        "scanner_a": a,
        "scanner_b": b,
        "signal_lab": "ACTIVE",
        "alerts_enabled": bool(os.getenv("SMTP_HOST") and os.getenv("ALERT_EMAIL_TO")),
        "methodology": {
            "A": "52-week proximity + extension state + RSI + relative volume + leakage-safe historical analogs.",
            "B": "Short crowding + DTC + short-interest change + relative volume + momentum; options are finalist enrichment.",
            "probability": "Historical conditional frequency only; unavailable when fewer than 20 comparable observations.",
            "options": "Actual public chain snapshot; no fabricated OI, IV, spread, or gamma values.",
        },
        "notes": [
            "ZERO-KEY MODE is fully usable without FINRA credentials.",
            "Yahoo/yfinance short-interest values are provider data and may be stale; FINRA overrides them when available.",
            "Scores are rankings, not probabilities or guarantees.",
            "Email alerts are delivered by scanner/smart_alerts.py from GitHub Actions; the local Windows companion provides native desktop alerts.",
        ],
    }
    try:
        from scanner.signal_lab import record_signals, write_lab_report
        record_signals(payload)
        lab = write_lab_report()
        payload["signal_lab_summary"] = {
            "signals": lab.get("signals", 0),
            "cutoff": lab.get("cutoff"),
            "outcomes_filled_this_run": lab.get("outcomes_filled_this_run", 0),
            "scanner_a": lab.get("A", {}),
            "scanner_b": lab.get("B", {}),
        }
    except Exception as exc:
        payload["signal_lab_summary"] = {"status": "ERROR", "error": str(exc)}
    (OUT / "scanner-data.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"scanner_a": len(a), "scanner_b": len(b), "zero_key_mode": True}))


if __name__ == "__main__":
    main()
