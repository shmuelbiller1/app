"""Quant Scanner research engine.

Design goals:
- real observations only; missing data stays missing;
- signal-time features never use future bars;
- Scanner A = leveraged/inverse ETF overextension + historical analogs;
- Scanner B = short-interest/volume squeeze setup;
- options are finalist-only and explicitly marked when unavailable;
- every emitted signal is persisted for future outcome validation;
- alerts are actually dispatched when configured.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from scanner.research_stats import bootstrap_ci
from scanner.signal_lab import record_signals, write_lab_report

FINNHUB = "https://finnhub.io/api/v1"
EXCLUDED = {"Technology", "Biotechnology", "Software", "Semiconductors", "Internet"}
LEVERAGED = [
    "YANG", "YINN", "NUGT", "DUST", "ERX", "ERY", "FAS", "FAZ", "UCO", "SCO",
    "BOIL", "KOLD", "GUSH", "DRIP", "TNA", "TZA", "TMF", "TMV", "DFEN", "DUG",
    "DIG", "SAA", "SDD", "UDOW", "SDOW",
]

session = requests.Session()
session.headers.update({"User-Agent": "QuantScanner/5.0 research"})


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fh(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    key = os.getenv("FINNHUB_API_KEY")
    if not key:
        return {}
    p = dict(params)
    p["token"] = key
    r = session.get(f"{FINNHUB}/{endpoint}", params=p, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, dict) else {}


def candles(symbol: str, days: int = 420) -> pd.DataFrame | None:
    """Fetch real daily OHLCV. No synthetic fallback values."""
    try:
        df = yf.download(symbol, period=f"{max(days, 60)}d", interval="1d",
                         auto_adjust=False, progress=False, threads=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        needed = {"Close", "Volume"}
        if not needed.issubset(df.columns):
            return None
        out = df[["Close", "Volume"]].copy()
        out = out.rename(columns={"Close": "close", "Volume": "volume"}).dropna()
        out.index = pd.to_datetime(out.index, utc=True)
        return out
    except Exception as exc:
        print(f"history {symbol}: {exc}")
        return None


def profile_ok(symbol: str) -> tuple[bool, str]:
    """Industry filter. If profile data cannot be obtained, do not invent it."""
    try:
        p = fh("stock/profile2", {"symbol": symbol})
        industry = str(p.get("finnhubIndustry") or "Unknown")
        if industry == "Unknown" and os.getenv("ALLOW_UNKNOWN_INDUSTRY", "0") != "1":
            return False, industry
        return industry not in EXCLUDED, industry
    except Exception:
        return False, "Unknown"


def rsi(series: pd.Series, n: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def feature_row(df: pd.DataFrame) -> dict[str, float | None]:
    c, v = df.close, df.volume
    sma20, sd20 = c.rolling(20).mean(), c.rolling(20).std()
    sma50, sd50 = c.rolling(50).mean(), c.rolling(50).std()
    px = float(c.iloc[-1])
    z20 = (px - sma20.iloc[-1]) / sd20.iloc[-1] if sd20.iloc[-1] > 0 else np.nan
    z50 = (px - sma50.iloc[-1]) / sd50.iloc[-1] if sd50.iloc[-1] > 0 else np.nan
    hi = float(c.tail(252).max())
    dist = (hi - px) / hi * 100 if hi > 0 else np.nan
    avg_v20 = float(v.tail(20).mean())
    rv = float(v.iloc[-1] / avg_v20) if avg_v20 > 0 else np.nan
    ret1 = px / float(c.iloc[-2]) - 1
    ret5 = px / float(c.iloc[-6]) - 1 if len(c) >= 6 else np.nan
    ret20 = px / float(c.iloc[-21]) - 1 if len(c) >= 21 else np.nan
    atr_like = float(c.diff().abs().rolling(14).mean().iloc[-1] / px) if len(c) >= 15 else np.nan
    r = rsi(c).iloc[-1]
    return {
        "price": px, "z_score": float(z20), "z50": float(z50), "high_distance": float(dist),
        "rsi": float(r), "relative_volume": rv, "return_1d": float(ret1 * 100),
        "return_5d": float(ret5 * 100) if np.isfinite(ret5) else None,
        "return_20d": float(ret20 * 100) if np.isfinite(ret20) else None,
        "atr_fraction": atr_like, "avg_volume_20": avg_v20,
    }


def state_signature(df: pd.DataFrame, pos: int) -> np.ndarray | None:
    c, v = df.close, df.volume
    sma, sd = c.rolling(20).mean(), c.rolling(20).std()
    z = (c - sma) / sd
    rs = rsi(c)
    hi = c.rolling(252, min_periods=20).max()
    dist = (hi - c) / hi
    rv = v / v.rolling(20).mean()
    if pos >= len(df):
        return None
    sig = np.array([z.iloc[pos], rs.iloc[pos], dist.iloc[pos], rv.iloc[pos]], dtype=float)
    return sig if np.all(np.isfinite(sig)) else None


def historical_probability(
    df: pd.DataFrame,
    current_signature: np.ndarray | None,
    horizon: int = 5,
    tolerances: tuple[float, float, float, float] = (0.45, 10.0, 0.035, 0.90),
    min_samples: int = 20,
) -> tuple[float | None, int, list[float]]:
    """Nearest-state historical probability with strict temporal separation."""
    if current_signature is None:
        return None, 0, []
    outcomes: list[float] = []
    current = np.asarray(current_signature, dtype=float)
    tol = np.asarray(tolerances, dtype=float)
    for pos in range(20, len(df) - horizon):
        sig = state_signature(df, pos)
        if sig is not None and np.all(np.abs(sig - current) <= tol):
            outcomes.append(float(df.close.iloc[pos + horizon] / df.close.iloc[pos] - 1))
    if len(outcomes) < min_samples:
        return None, len(outcomes), outcomes
    return float(np.mean(np.asarray(outcomes) < 0)), len(outcomes), outcomes


def scanner_a(signal_time: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for symbol in LEVERAGED:
        try:
            ok, industry = profile_ok(symbol)
            if not ok:
                continue
            df = candles(symbol)
            if df is None or len(df) < 260:
                continue
            f = feature_row(df)
            sig = state_signature(df, len(df) - 1)
            prob, n, outcomes = historical_probability(df, sig)
            quality = "INSUFFICIENT" if prob is None else ("STRONG" if n >= 80 else "GOOD" if n >= 40 else "LIMITED")

            extension = np.clip(f["z_score"] / 3.0, 0, 1)
            high = np.clip(1 - f["high_distance"] / 8.0, 0, 1)
            rsi_factor = np.clip((f["rsi"] - 55) / 25.0, 0, 1)
            volume_factor = np.clip((f["relative_volume"] - 1) / 3.0, 0, 1)
            probability_factor = np.clip((prob - 0.5) / 0.3, 0, 1) if prob is not None else 0
            score = 100 * (0.30 * extension + 0.25 * high + 0.15 * rsi_factor + 0.10 * volume_factor + 0.20 * probability_factor)

            ci = None
            if len(outcomes) >= 20:
                binary = np.asarray([1.0 if x < 0 else 0.0 for x in outcomes])
                lo, hi = bootstrap_ci(binary, np.mean, n_resamples=500, mean_block=min(7, len(binary)))
                ci = [round(float(lo), 4), round(float(hi), 4)]

            if score < 50:
                continue
            out.append({
                "ticker": symbol, "score": round(float(score), 1),
                "probability": round(prob, 4) if prob is not None else None,
                "probability_ci": ci, "probability_horizon_days": 5,
                "probability_sample": n, "data_quality": quality,
                "price": round(float(f["price"]), 4), "z_score": round(float(f["z_score"]), 2),
                "z50": round(float(f["z50"]), 2), "high_distance": round(float(f["high_distance"]), 2),
                "rsi": round(float(f["rsi"]), 1), "relative_volume": round(float(f["relative_volume"]), 2),
                "return_1d": round(float(f["return_1d"]), 2), "return_5d": f["return_5d"],
                "return_20d": f["return_20d"], "avg_volume_20": round(float(f["avg_volume_20"])),
                "industry": industry, "options": "NOT_CHECKED", "signal_time": signal_time,
            })
        except Exception as exc:
            print("A", symbol, exc)
    return sorted(out, key=lambda x: x["score"], reverse=True)[:20]


def load_finra() -> pd.DataFrame:
    path = os.getenv("FINRA_SHORT_CSV", "data/finra_short_interest.csv")
    return pd.read_csv(path) if os.path.exists(path) else pd.DataFrame()


def load_reg_sho() -> pd.DataFrame:
    path = os.getenv("FINRA_REG_SHO_CSV", "data/finra_reg_sho_daily.csv")
    return pd.read_csv(path) if os.path.exists(path) else pd.DataFrame()


def scanner_b(signal_time: str) -> list[dict[str, Any]]:
    finra, reg = load_finra(), load_reg_sho()
    if finra.empty or not {"ticker", "short_interest", "days_to_cover"}.issubset(finra.columns):
        return []
    reg_map: dict[str, float] = {}
    if not reg.empty and {"ticker", "short_volume_ratio"}.issubset(reg.columns):
        reg_map = reg.groupby("ticker")["short_volume_ratio"].mean().to_dict()

    out: list[dict[str, Any]] = []
    for _, row in finra.iterrows():
        symbol = str(row.ticker).upper().strip()
        try:
            ok, industry = profile_ok(symbol)
            if not ok:
                continue
            df = candles(symbol, 90)
            if df is None or len(df) < 30:
                continue
            f = feature_row(df)
            if f["return_1d"] < 3 or f["relative_volume"] < 1.5:
                continue
            sf = float(row.short_float) if "short_float" in row and pd.notna(row.short_float) else np.nan
            dtc = float(row.days_to_cover) if pd.notna(row.days_to_cover) else np.nan
            sic = float(row.si_change_pct) if "si_change_pct" in row and pd.notna(row.si_change_pct) else np.nan
            sv = float(reg_map[symbol]) if symbol in reg_map else np.nan
            sf_score = np.clip(sf / 30, 0, 1) if np.isfinite(sf) else 0
            dtc_score = np.clip(dtc / 10, 0, 1) if np.isfinite(dtc) else 0
            change_score = np.clip(sic / 50, 0, 1) if np.isfinite(sic) else 0
            vol_score = np.clip(f["relative_volume"] / 5, 0, 1)
            mom_score = np.clip(f["return_1d"] / 15, 0, 1)
            score = 100 * (0.28 * sf_score + 0.18 * dtc_score + 0.18 * change_score + 0.20 * vol_score + 0.16 * mom_score)
            out.append({
                "ticker": symbol, "score": round(float(score), 1),
                "short_float": round(float(sf), 2) if np.isfinite(sf) else None,
                "days_to_cover": round(float(dtc), 2) if np.isfinite(dtc) else None,
                "rel_volume": round(float(f["relative_volume"]), 2),
                "price": round(float(f["price"]), 4), "price_change": round(float(f["return_1d"]), 2),
                "return_5d": f["return_5d"], "si_change_pct": round(float(sic), 2) if np.isfinite(sic) else None,
                "reg_sho_short_volume_ratio": round(float(sv), 4) if np.isfinite(sv) else None,
                "industry": industry, "options": "NOT_CHECKED", "signal_time": signal_time,
            })
        except Exception as exc:
            print("B", symbol, exc)
    return sorted(out, key=lambda x: x["score"], reverse=True)[:20]


def options_check(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate only finalists. Never manufacture options statistics."""
    key = os.getenv("ALPHA_VANTAGE_API_KEY")
    if not key:
        return candidates
    for x in candidates[:10]:
        try:
            r = session.get("https://www.alphavantage.co/query", params={
                "function": "HISTORICAL_OPTIONS", "symbol": x["ticker"], "apikey": key,
            }, timeout=20)
            r.raise_for_status()
            rows = r.json().get("data", [])
            if not rows:
                x["options"] = "NO_DATA"
                continue
            oi = sum(int(float(i.get("open_interest", 0) or 0)) for i in rows[:50])
            volume = sum(int(float(i.get("volume", 0) or 0)) for i in rows[:50])
            x["options_open_interest"] = oi
            x["options_volume"] = volume
            x["options"] = "PASS" if oi >= 500 and volume > 0 else "WEAK"
        except Exception as exc:
            print("options", x["ticker"], exc)
            x["options"] = "ERROR"
    return candidates


def alert(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> bool:
    """Send Discord alerts. State is only a cooldown helper; scanner data remains authoritative."""
    url = os.getenv("DISCORD_WEBHOOK_URL")
    if not url:
        return False
    state_path = "data/alert_state.json"
    os.makedirs("data", exist_ok=True)
    try:
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    except Exception:
        state = {}
    now = time.time()
    cooldown = int(os.getenv("ALERT_COOLDOWN_SECONDS", "14400"))
    fresh = []
    for kind, items in (("A", a), ("B", b)):
        for x in items:
            if float(x.get("score", 0)) < float(os.getenv("ALERT_MIN_SCORE", "85")):
                continue
            k = f"{kind}:{x['ticker']}"
            if now - float(state.get(k, 0)) >= cooldown:
                fresh.append((kind, x))
                state[k] = now
    if not fresh:
        return False
    lines = ["**Quant Scanner — new high-score research signal**"]
    for kind, x in fresh:
        p = f" | P5d={x['probability']:.0%}" if kind == "A" and x.get("probability") is not None else ""
        rv = x.get("relative_volume", x.get("rel_volume", "?"))
        lines.append(f"{kind} **{x['ticker']}** score={x['score']:.1f}{p} | RV={rv}")
    lines.append("Research signal only. Verify source data, liquidity and options before acting.")
    try:
        response = session.post(url, json={"content": "\n".join(lines)}, timeout=15)
        response.raise_for_status()
    except Exception as exc:
        print("alert", exc)
        return False
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    return True


def main() -> None:
    signal_time = utc_now()
    a = options_check(scanner_a(signal_time))
    b = options_check(scanner_b(signal_time))
    payload = {
        "generated_at": signal_time,
        "market_status": "SCANNED",
        "scanner_a": a,
        "scanner_b": b,
        "alerts_enabled": bool(os.getenv("DISCORD_WEBHOOK_URL")),
        "signal_lab": "ACTIVE",
        "methodology": {
            "A": "Historical analog matching on signal-time Z20/RSI/52W-distance/relative-volume; minimum 20 observations; bootstrap CI when available.",
            "B": "Short float + DTC + SI change + relative volume + price momentum; Reg SHO short-volume ratio shown separately as context.",
            "validation": "Every emitted candidate is recorded and later joined to realized +1/+3/+5/+10/+20 session outcomes.",
            "options": "Finalist-only; PASS/WEAK/NO_DATA/ERROR/NOT_CHECKED are explicit.",
            "truth_policy": "No synthetic market values, no fabricated probabilities, and no fallback statistics presented as observations.",
        },
    }
    record_signals(payload)
    lab = write_lab_report()
    payload["signal_lab_summary"] = {
        "signals": lab.get("signals", 0),
        "cutoff": lab.get("cutoff"),
        "outcomes_filled_this_run": lab.get("outcomes_filled_this_run", 0),
        "scanner_a": lab.get("A", {}),
        "scanner_b": lab.get("B", {}),
    }
    alert_sent = alert(a, b)
    payload["alert_sent"] = alert_sent
    os.makedirs("frontend/public", exist_ok=True)
    with open("frontend/public/scanner-data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"Scanner complete: A={len(a)} B={len(b)} | lab signals={lab.get('signals', 0)} | alert={alert_sent}")


if __name__ == "__main__":
    main()
