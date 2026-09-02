"""Production quantitative market scanner.

The scanner has two deliberately different clocks:

1. LIVE clock: intraday monitoring during the U.S. regular session.
2. RESEARCH clock: completed daily-bar observations used for historical
   analog evidence and Signal Lab. Intraday observations are never presented
   as completed daily research events.

Default mode requires no proprietary market-data key. Yahoo/yfinance supplies
public history, screening, metadata and listed option chains. FINRA is optional
for authoritative short-interest and Reg SHO enrichment.

Missing data stays missing; estimates are labeled as estimates; rankings are
never presented as probabilities.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "public"
OUT.mkdir(parents=True, exist_ok=True)
ET = ZoneInfo("America/New_York")

EXCLUDED_SECTORS = {"Technology", "Biotechnology", "Software", "Semiconductors", "Internet"}
MIN_PRICE = 2.0
MIN_MARKET_CAP = 300_000_000
MIN_AVG_DOLLAR_VOLUME = 1_000_000
MAX_SQUEEZE_UNIVERSE = 750
FINALISTS_FOR_OPTIONS = 12
ALERT_MIN_SCORE = float(os.getenv("ALERT_MIN_SCORE", "85"))
RESEARCH_SCORE_FLOOR = float(os.getenv("RESEARCH_SCORE_FLOOR", "60"))


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_symbol(value) -> str:
    return str(value or "").strip().upper().replace(".", "-")


def _num(x):
    try:
        y = float(x)
        return y if np.isfinite(y) else None
    except Exception:
        return None


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


def completed_daily(df: pd.DataFrame, as_of_et: datetime | None = None) -> pd.DataFrame:
    """Return only bars whose trading date is complete as of the ET calendar date."""
    x = df.copy()
    if x.empty:
        return x
    idx = pd.to_datetime(x.index, utc=True)
    today_et = (as_of_et or datetime.now(ET)).date()
    dates_et = idx.tz_convert(ET).date
    mask = np.asarray(dates_et) < today_et
    return x.loc[mask].copy()


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
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.rolling(14).mean().iloc[-1])
    atr_frac = atr / px if px > 0 else np.nan
    return {
        "price": px,
        "z20": z20,
        "z50": z50,
        "rsi14": float(rsi(c).iloc[-1]),
        "distance_52w": dist52 * 100,
        "relative_volume": rv,
        "momentum_1d": (px / float(c.iloc[-2]) - 1) * 100 if len(c) >= 2 else np.nan,
        "momentum_3d": (px / float(c.iloc[-4]) - 1) * 100 if len(c) >= 4 else np.nan,
        "momentum_5d": (px / float(c.iloc[-6]) - 1) * 100 if len(c) >= 6 else np.nan,
        "momentum_20d": (px / float(c.iloc[-21]) - 1) * 100 if len(c) >= 21 else np.nan,
        "atr_fraction": atr_frac,
        "avg_volume_20": avgv,
        "sma20": float(sma20.iloc[-1]),
        "sma50": float(sma50.iloc[-1]),
        "sma200": float(sma200.iloc[-1]) if np.isfinite(sma200.iloc[-1]) else np.nan,
    }


def state_signature(df: pd.DataFrame, pos: int) -> np.ndarray | None:
    if pos < 252:
        return None
    c = df["Close"].astype(float)
    h = df["High"].astype(float)
    v = df["Volume"].astype(float)
    sma = c.rolling(20).mean()
    sd = c.rolling(20).std()
    z = (c - sma) / sd
    rr = rsi(c)
    hi = h.rolling(252).max()
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
    for i in range(252, len(df) - horizon):
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
    return (
        str(info.get("sector") or "Unknown"),
        str(info.get("industry") or "Unknown"),
        _num(info.get("marketCap")),
        _num(info.get("floatShares")),
        _num(info.get("averageDailyVolume10Day")) or _num(info.get("averageVolume")),
    )


def free_short_screener() -> list[dict]:
    rows: dict[str, dict] = {}
    try:
        for offset in range(0, MAX_SQUEEZE_UNIVERSE, 250):
            page = yf.screen("most_shorted_stocks", offset=offset, size=250,
                             sortField="short_percentage_of_float.value", sortAsc=False)
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


def load_finra_short() -> dict[str, dict]:
    out: dict[str, dict] = {}
    p = Path(os.getenv("FINRA_SHORT_CSV", "data/finra_short_interest.csv"))
    if not p.exists():
        return out
    try:
        f = pd.read_csv(p)
        for _, row in f.iterrows():
            s = clean_symbol(row.get("ticker"))
            if s:
                out[s] = row.to_dict()
    except Exception as exc:
        print(f"FINRA short-interest CSV unavailable: {exc}")
    return out


def load_finra_reg_sho() -> dict[str, dict]:
    out: dict[str, dict] = {}
    p = Path(os.getenv("FINRA_REG_SHO_CSV", "data/finra_reg_sho_daily.csv"))
    if not p.exists():
        return out
    try:
        f = pd.read_csv(p)
        for _, row in f.iterrows():
            s = clean_symbol(row.get("ticker"))
            if s:
                out[s] = row.to_dict()
    except Exception as exc:
        print(f"FINRA Reg SHO CSV unavailable: {exc}")
    return out


def black_scholes_gamma(spot: float, strike: float, t: float, rate: float, iv: float) -> float:
    if min(spot, strike, t, iv) <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * t) / (iv * math.sqrt(t))
    return norm.pdf(d1) / (spot * iv * math.sqrt(t))


def _years_to_expiry(expiration: str, as_of: datetime | None = None) -> float:
    now = as_of or datetime.now(timezone.utc)
    exp_date = datetime.strptime(str(expiration), "%Y-%m-%d").date()
    close_et = datetime(exp_date.year, exp_date.month, exp_date.day, 16, 0, tzinfo=ET)
    return (close_et.astimezone(timezone.utc) - now).total_seconds() / (365.0 * 24 * 3600)


def options_snapshot(symbol: str, spot: float) -> dict:
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
            bid = pd.to_numeric(frame.get("bid", 0), errors="coerce").replace(0, np.nan)
            ask = pd.to_numeric(frame.get("ask", 0), errors="coerce").replace(0, np.nan)
            mid = (bid + ask) / 2
            spread = ((ask - bid) / mid).replace([np.inf, -np.inf], np.nan).dropna()
            return {"oi": int(oi.sum()), "vol": int(vol.sum()),
                    "spread": float(spread.median()) if not spread.empty else None}

        cl, pl = liquidity(cdf), liquidity(pdf)
        gex_1pct = 0.0
        contracts_priced = 0
        as_of = datetime.now(timezone.utc)
        for exp, cframe, pframe in zip(use_exp, calls, puts):
            t_years = _years_to_expiry(exp, as_of)
            if t_years <= 0:
                continue
            for frame, sign in ((cframe, 1.0), (pframe, -1.0)):
                for _, row in frame.iterrows():
                    strike = _num(row.get("strike"))
                    iv = _num(row.get("impliedVolatility"))
                    oi = _num(row.get("openInterest"))
                    if strike is None or iv is None or oi is None or oi <= 0:
                        continue
                    gamma = black_scholes_gamma(spot, strike, t_years, 0.04, iv)
                    gex_1pct += sign * gamma * spot * spot * 0.01 * 100 * oi
                    contracts_priced += 1
        spreads = [x for x in (cl["spread"], pl["spread"]) if x is not None]
        spread = float(np.mean(spreads)) if spreads else None
        oi_total = cl["oi"] + pl["oi"]
        vol_total = cl["vol"] + pl["vol"]
        spread_score = max(0.0, 1.0 - min(spread, 1.0)) if spread is not None else 0.0
        depth_score = min(1.0, math.log10(max(oi_total, 1)) / 5.0)
        activity_score = min(1.0, math.log10(max(vol_total, 1)) / 4.0)
        status = "PASS" if oi_total >= 500 and vol_total > 0 and spread is not None and spread <= 0.30 else "WEAK"
        return {
            "status": status,
            "expirations_checked": use_exp,
            "call_oi": cl["oi"], "put_oi": pl["oi"],
            "call_volume": cl["vol"], "put_volume": pl["vol"],
            "oi_total": oi_total, "volume_total": vol_total,
            "median_spread_pct": round(spread * 100, 2) if spread is not None else None,
            "call_put_oi_ratio": round(cl["oi"] / max(pl["oi"], 1), 3),
            "call_put_volume_ratio": round(cl["vol"] / max(pl["vol"], 1), 3),
            "net_dollar_gamma_1pct": round(gex_1pct, 0),
            "gamma_contracts_priced": contracts_priced,
            "gamma_sign": "positive" if gex_1pct > 0 else "negative" if gex_1pct < 0 else "flat",
            "gamma_methodology": "Black-Scholes approximation from public OI/IV; call-plus / put-minus; 1% underlying move; not dealer positioning.",
            "gamma_is_context_only": True,
            "liquidity_score": round(100 * (0.45 * spread_score + 0.30 * depth_score + 0.25 * activity_score), 1),
        }
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc)}


def _a_result(symbol, name, item, live, ref, prob, n, outcomes, signal_time, research_date, market_cap, sector, industry, kind):
    ext = np.clip(live["z20"] / 3.0, 0, 1)
    near = np.clip(1 - live["distance_52w"] / 8.0, 0, 1)
    rfac = np.clip((live["rsi14"] - 55) / 25.0, 0, 1)
    rv = np.clip((live["relative_volume"] - 1) / 3.0, 0, 1)
    pf = np.clip((prob - 0.5) / 0.3, 0, 1) if prob is not None else 0.0
    score = 100 * (0.35 * ext + 0.30 * near + 0.15 * rfac + 0.10 * rv + 0.10 * pf)
    ref_sig, ref_prob_n, ref_outcomes = None, n, outcomes
    if kind == "research":
        ref_sig = state_signature(ref, len(ref) - 1) if len(ref) else None
        ref_prob, ref_prob_n, ref_outcomes = historical_analog_probability(ref, ref_sig) if ref_sig is not None else (None, 0, [])
        prob, n, outcomes = ref_prob, ref_prob_n, ref_outcomes
        ext = np.clip(ref["Close"].iloc[-1] if False else (ref_metrics["z20"] / 3.0 if False else 0), 0, 1)
    ci = bootstrap_interval([1.0 if r < 0 else 0.0 for r in outcomes])
    return {
        "ticker": symbol, "name": item.get("name", name or symbol),
        "sector": sector, "industry": industry, "leverage": item.get("leverage"),
        "price": round(live["price"], 4), "score": round(float(score), 1), "reversal_score": round(float(score), 1),
        "z20": round(live["z20"], 2), "z50": round(live["z50"], 2), "rsi14": round(live["rsi14"], 1),
        "distance_52w": round(live["distance_52w"], 2), "relative_volume": round(live["relative_volume"], 2),
        "momentum_5d": round(live["momentum_5d"], 2), "market_cap": market_cap,
        "avg_dollar_volume": round(live["avg_volume_20"] * live["price"]),
        "downside_probability_5d": round(prob * 100, 2) if prob is not None else None,
        "probability_sample": int(n), "probability_ci95": ci,
        "evidence_quality": "STRONG" if n >= 80 else "GOOD" if n >= 40 else "INSUFFICIENT",
        "research_date": research_date, "signal_time": signal_time,
        "observation_kind": kind,
        "options": {"status": "NOT_CHECKED"},
    }


def scan_a(signal_time: str) -> tuple[list[dict], list[dict], list[dict]]:
    try:
        universe = json.loads((ROOT / "scanner" / "leveraged_etfs.json").read_text())
    except Exception:
        universe = []
    live_results, research_results = [], []
    for item in universe:
        symbol = clean_symbol(item.get("symbol"))
        if not symbol:
            continue
        df = history(symbol, "2y")
        if df is None or len(df) < 260:
            continue
        ref = completed_daily(df)
        if len(ref) < 260:
            continue
        sector, industry, market_cap, _, _ = industry_info(symbol)
        if sector in EXCLUDED_SECTORS or industry in EXCLUDED_SECTORS:
            continue
        live = metrics(df); ref_metrics = metrics(ref)
        if live["price"] < MIN_PRICE or live["avg_volume_20"] * live["price"] < MIN_AVG_DOLLAR_VOLUME:
            continue
        current = state_signature(ref, len(ref) - 1)
        prob, n, outcomes = historical_analog_probability(ref, current)
        live_item = _a_result(symbol, symbol, item, live, ref, prob, n, outcomes, signal_time,
                              str(pd.Timestamp(ref.index[-1]).date()), market_cap, sector, industry, "live")
        live_item["historical_reference_is_completed_daily"] = True
        live_results.append(live_item)

        research_current = state_signature(ref, len(ref) - 1)
        rprob, rn, routcomes = historical_analog_probability(ref, research_current)
        r_ext = np.clip(ref_metrics["z20"] / 3.0, 0, 1)
        r_near = np.clip(1 - ref_metrics["distance_52w"] / 8.0, 0, 1)
        r_rfac = np.clip((ref_metrics["rsi14"] - 55) / 25.0, 0, 1)
        r_rv = np.clip((ref_metrics["relative_volume"] - 1) / 3.0, 0, 1)
        r_pf = np.clip((rprob - 0.5) / 0.3, 0, 1) if rprob is not None else 0.0
        rscore = 100 * (0.35 * r_ext + 0.30 * r_near + 0.15 * r_rfac + 0.10 * r_rv + 0.10 * r_pf)
        research_results.append({
            "ticker": symbol, "name": item.get("name", symbol), "sector": sector, "industry": industry,
            "leverage": item.get("leverage"), "price": round(ref_metrics["price"], 4),
            "score": round(float(rscore), 1), "reversal_score": round(float(rscore), 1),
            "z20": round(ref_metrics["z20"], 2), "z50": round(ref_metrics["z50"], 2),
            "rsi14": round(ref_metrics["rsi14"], 1), "distance_52w": round(ref_metrics["distance_52w"], 2),
            "relative_volume": round(ref_metrics["relative_volume"], 2), "momentum_5d": round(ref_metrics["momentum_5d"], 2),
            "market_cap": market_cap, "avg_dollar_volume": round(ref_metrics["avg_volume_20"] * ref_metrics["price"]),
            "downside_probability_5d": round(rprob * 100, 2) if rprob is not None else None,
            "probability_sample": int(rn), "probability_ci95": bootstrap_interval([1.0 if r < 0 else 0.0 for r in routcomes]),
            "evidence_quality": "STRONG" if rn >= 80 else "GOOD" if rn >= 40 else "INSUFFICIENT",
            "research_date": str(pd.Timestamp(ref.index[-1]).date()), "signal_time": signal_time,
            "observation_kind": "completed_daily", "options": {"status": "NOT_CHECKED"},
        })
    live_results = sorted(live_results, key=lambda x: x["score"], reverse=True)
    research_results = sorted(research_results, key=lambda x: x["score"], reverse=True)
    return live_results[:40], live_results, [x for x in research_results if x["score"] >= RESEARCH_SCORE_FLOOR]


def scan_b(signal_time: str) -> tuple[list[dict], list[dict], list[dict]]:
    quotes = free_short_screener()
    if not quotes:
        return [], [], []
    finra = load_finra_short(); reg_sho = load_finra_reg_sho()
    live_results, research_results = [], []
    for q in quotes:
        s = clean_symbol(q.get("symbol"))
        if not s:
            continue
        price = _num(quote_value(q, "regularMarketPrice", "postMarketPrice", "price"))
        mcap = _num(quote_value(q, "marketCap", "intradaymarketcap"))
        if mcap is not None and mcap < MIN_MARKET_CAP:
            continue
        si_pct = _num(quote_value(q, "shortPercentageOfFloat", "shortPctOfFloat", "short_percentage_of_float"))
        if si_pct is not None and si_pct < 1:
            si_pct *= 100
        dtc = _num(quote_value(q, "shortRatio", "daysToCoverShort")); short_shares = _num(quote_value(q, "sharesShort", "shortInterest"))
        short_source = "YAHOO_PUBLIC_SCREENER"
        if s in finra:
            row = finra[s]; short_shares = _num(row.get("short_interest")) or short_shares; dtc = _num(row.get("days_to_cover")) or dtc
            si_change = _num(row.get("si_change_pct")); short_source = "FINRA"
            si_date = row.get("settlement_date")
        else:
            si_change = _num(quote_value(q, "shortInterestChangePercent", "short_interest_percentage_change")); si_date = None
        sector = str(quote_value(q, "sector") or "Unknown"); industry = str(quote_value(q, "industry") or "Unknown")
        if sector == "Unknown" or industry == "Unknown":
            sec2, ind2, mc2, _, _ = industry_info(s); sector, industry = sec2, ind2; mcap = mcap or mc2
        if mcap is not None and mcap < MIN_MARKET_CAP:
            continue
        if sector in EXCLUDED_SECTORS or industry in EXCLUDED_SECTORS:
            continue
        df = history(s, "6mo")
        if df is None or len(df) < 60:
            continue
        ref = completed_daily(df)
        if len(ref) < 30:
            continue
        live = metrics(df); refm = metrics(ref); price = price or live["price"]
        if price < MIN_PRICE:
            continue
        dollar_vol = live["avg_volume_20"] * price
        if dollar_vol < MIN_AVG_DOLLAR_VOLUME:
            continue
        if si_pct is None or si_pct < 5:
            continue
        if live["relative_volume"] < 1.25 or live["momentum_5d"] <= 0:
            continue
        float_shares = _num(quote_value(q, "floatShares")); short_float = (short_shares / float_shares * 100) if short_shares and float_shares else si_pct
        crowd = np.clip((short_float or 0) / 30, 0, 1); dtc_s = np.clip((dtc or 0) / 10, 0, 1)
        change_s = np.clip(max(si_change or 0, 0) / 50, 0, 1); vol_s = np.clip(live["relative_volume"] / 5, 0, 1); mom_s = np.clip(max(live["momentum_5d"], 0) / 15, 0, 1)
        score = 100 * (0.30 * crowd + 0.15 * dtc_s + 0.15 * change_s + 0.22 * vol_s + 0.18 * mom_s)
        rs_reg = reg_sho.get(s)
        reg_ratio = _num(rs_reg.get("short_volume_ratio")) if rs_reg else None
        reg_date = rs_reg.get("reg_sho_date") if rs_reg else None
        item = {
            "ticker": s, "score": round(float(score), 1), "squeeze_score": round(float(score), 1),
            "sector": sector, "industry": industry, "price": round(float(price), 4), "market_cap": mcap,
            "short_float_pct": round(float(short_float), 2) if short_float is not None else None,
            "short_interest": short_shares, "days_to_cover": round(float(dtc), 2) if dtc is not None else None,
            "si_change_pct": round(float(si_change), 2) if si_change is not None else None,
            "short_interest_asof": str(si_date) if si_date not in (None, "nan") else None,
            "relative_volume": round(live["relative_volume"], 2), "momentum_5d": round(live["momentum_5d"], 2),
            "avg_dollar_volume": round(dollar_vol), "short_data_source": short_source,
            "reg_sho_short_volume_ratio": reg_ratio, "reg_sho_asof": str(reg_date) if reg_date not in (None, "nan") else None,
            "reg_sho_is_separate_from_short_interest": True,
            "research_date": str(pd.Timestamp(ref.index[-1]).date()), "signal_time": signal_time,
            "observation_kind": "live", "options": {"status": "NOT_CHECKED"},
        }
        live_results.append(item)

        r_crowd = np.clip((short_float or 0) / 30, 0, 1); r_dtc_s = np.clip((dtc or 0) / 10, 0, 1)
        r_change_s = np.clip(max(si_change or 0, 0) / 50, 0, 1); r_vol_s = np.clip(refm["relative_volume"] / 5, 0, 1); r_mom_s = np.clip(max(refm["momentum_5d"], 0) / 15, 0, 1)
        rscore = 100 * (0.30 * r_crowd + 0.15 * r_dtc_s + 0.15 * r_change_s + 0.22 * r_vol_s + 0.18 * r_mom_s)
        if refm["relative_volume"] >= 1.25 and refm["momentum_5d"] > 0 and rscore >= RESEARCH_SCORE_FLOOR:
            research_results.append({**item, "score": round(float(rscore), 1), "squeeze_score": round(float(rscore), 1),
                                     "price": round(float(refm["price"]), 4), "relative_volume": round(refm["relative_volume"], 2),
                                     "momentum_5d": round(refm["momentum_5d"], 2), "avg_dollar_volume": round(refm["avg_volume_20"] * refm["price"]),
                                     "observation_kind": "completed_daily"})
    live_results = sorted(live_results, key=lambda x: x["score"], reverse=True)
    research_results = sorted(research_results, key=lambda x: x["score"], reverse=True)
    return live_results[:40], live_results, research_results


def enrich_options(items: list[dict]) -> list[dict]:
    for x in items[:FINALISTS_FOR_OPTIONS]:
        x["options"] = options_snapshot(x["ticker"], float(x["price"]))
    return items


def main():
    ts = now_utc()
    a, a_alerts, a_research = scan_a(ts)
    b, b_alerts, b_research = scan_b(ts)
    a = enrich_options(a); b = enrich_options(b)
    research_a = [x for x in a_research if x.get("score", 0) >= RESEARCH_SCORE_FLOOR]
    research_b = [x for x in b_research if x.get("score", 0) >= RESEARCH_SCORE_FLOOR]
    finra_enabled = bool(Path(os.getenv("FINRA_SHORT_CSV", "data/finra_short_interest.csv")).exists())
    reg_enabled = bool(Path(os.getenv("FINRA_REG_SHO_CSV", "data/finra_reg_sho_daily.csv")).exists())
    now_et = datetime.now(ET)
    payload = {
        "schema_version": "3.1",
        "generated_at": ts,
        "generated_at_et": now_et.isoformat(),
        "market_status": "LIVE — REGULAR SESSION" if now_et.weekday() < 5 and 9.5 <= now_et.hour + now_et.minute / 60 <= 16 else "OUTSIDE REGULAR SESSION",
        "status": "LIVE — ZERO-KEY-FIRST",
        "data_sources": {
            "price_history": "yfinance public data",
            "market_screener": "Yahoo/yfinance public screener",
            "company_metadata": "Yahoo/yfinance public info",
            "options": "yfinance public option chains",
            "short_interest": "FINRA when ingested; otherwise Yahoo/yfinance public screener",
            "reg_sho": "FINRA when ingested",
            "finra_short_interest_loaded": finra_enabled,
            "finra_reg_sho_loaded": reg_enabled,
        },
        "scanner_a": a,
        "scanner_b": b,
        "alert_universe_a": [{**x, "options": {"status": "NOT_CHECKED"}} for x in a_alerts],
        "alert_universe_b": [{**x, "options": {"status": "NOT_CHECKED"}} for x in b_alerts],
        "research_observations": {"scanner_a": research_a, "scanner_b": research_b},
        "research_clock": {
            "type": "COMPLETED_DAILY_ONLY",
            "intraday_signals_excluded": True,
            "definition": "Research observations use the last completed daily bar, not the current partial trading day.",
        },
        "signal_lab": "ACTIVE",
        "alerts_enabled": bool(os.getenv("SMTP_HOST") and os.getenv("ALERT_EMAIL_TO")),
        "methodology": {
            "A": "52-week proximity + extension state + RSI + relative volume + leakage-safe historical analogs.",
            "B": "Short crowding + DTC + short-interest change + relative volume + momentum; Reg SHO is separate evidence context.",
            "probability": "Historical conditional frequency on completed daily states; unavailable with fewer than 20 analog observations.",
            "options": "Public chain snapshot; liquidity is finalist-only; gamma is a model-derived 1% move context metric, not dealer positioning.",
        },
        "notes": [
            "Scores are rankings, not probabilities or guarantees.",
            "FINRA short interest is periodic and is never conflated with daily Reg SHO short-sale volume.",
            "The alert universe is broader than the dashboard top-40 view so ranking displacement does not itself invalidate a signal.",
            "Windows notifications should consume the canonical scanner snapshot rather than independently recomputing the strategy.",
        ],
    }
    try:
        from scanner.signal_lab import record_research_observations, write_lab_report
        payload["signal_lab_recorded"] = record_research_observations(payload)
        lab = write_lab_report()
        payload["signal_lab_summary"] = {
            "signals_recorded_total": lab.get("signals_recorded_total", 0),
            "daily_observations": lab.get("daily_observations", 0),
            "pending_outcomes": lab.get("pending_outcomes", 0),
            "outcomes_filled_this_run": lab.get("outcomes_filled_this_run", 0),
            "A": lab.get("A", {}), "B": lab.get("B", {}), "cutoff": lab.get("cutoff"),
        }
    except Exception as exc:
        payload["signal_lab_summary"] = {"status": "ERROR", "error": str(exc)}
    (OUT / "scanner-data.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"scanner_a": len(a), "scanner_b": len(b), "alert_universe_a": len(a_alerts), "alert_universe_b": len(b_alerts), "research_a": len(research_a), "research_b": len(research_b)}))


if __name__ == "__main__":
    main()
