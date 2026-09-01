"""Runtime hardening adapter for the zero-key scanner.

Thin reliability layer inspired by mature open-source quant/data projects:
retry/backoff, in-process caching, OHLCV validation, strict historical-state
comparability, data-health reporting, and explicit options-GEX caveats.

It does not fabricate missing values and does not change the scanner's scoring
model except for making historical analog states comparable.
"""
from __future__ import annotations

import functools
import json
import random
import time
from pathlib import Path

import numpy as np
import pandas as pd

import scanner.run_scanner as scanner

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "public" / "scanner-data.json"
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 0.75
JITTER_SECONDS = 0.25

_health = {"history_requests": 0, "history_cache_hits": 0, "history_failures": 0,
           "history_invalid": 0, "screen_attempts": 0, "screen_failures": 0}
_history_cache: dict[tuple[str, str], pd.DataFrame | None] = {}
_ORIGINAL_SAFE_INFO = scanner.safe_info
_ORIGINAL_YF_SCREEN = scanner.yf.screen


def _retry(call, label: str):
    last = None
    for attempt in range(MAX_RETRIES):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - provider/network boundary
            last = exc
            if attempt + 1 >= MAX_RETRIES:
                break
            delay = BASE_BACKOFF_SECONDS * (2 ** attempt) + random.uniform(0, JITTER_SECONDS)
            print(f"{label}: transient failure; retry {attempt + 1}/{MAX_RETRIES - 1} in {delay:.2f}s")
            time.sleep(delay)
    raise last


def _validate_ohlcv(df: pd.DataFrame | None, symbol: str) -> pd.DataFrame | None:
    if df is None or df.empty:
        return None
    x = df.copy()
    required = {"Close", "High", "Low", "Volume"}
    if not required.issubset(x.columns):
        return None
    if x.index.has_duplicates or not x.index.is_monotonic_increasing:
        x = x[~x.index.duplicated(keep="last")].sort_index()
    for col in required:
        x[col] = pd.to_numeric(x[col], errors="coerce")
    x = x.dropna(subset=list(required))
    if x.empty:
        return None
    bad = ((x["Close"] <= 0) | (x["High"] <= 0) | (x["Low"] <= 0)
           | (x["High"] < x["Low"]) | (x["High"] < x["Close"])
           | (x["Low"] > x["Close"]) | (x["Volume"] < 0))
    if bool(bad.any()):
        print(f"{symbol}: rejected {int(bad.sum())} invalid OHLCV rows")
        return None
    return x[["Close", "High", "Low", "Volume"]].copy()


@functools.lru_cache(maxsize=1024)
def _cached_info(symbol: str) -> dict:
    try:
        return _ORIGINAL_SAFE_INFO(symbol)
    except Exception:
        return {}


def hardened_history(symbol: str, period: str = "2y") -> pd.DataFrame | None:
    key = (symbol, period)
    _health["history_requests"] += 1
    if key in _history_cache:
        _health["history_cache_hits"] += 1
        cached = _history_cache[key]
        return None if cached is None else cached.copy()

    def fetch():
        raw = scanner.yf.download(symbol, period=period, interval="1d", auto_adjust=False,
                                  progress=False, threads=False)
        return scanner.normalize_history(raw, symbol)

    try:
        data = _retry(fetch, f"history {symbol}")
    except Exception as exc:
        _health["history_failures"] += 1
        print(f"history {symbol}: {exc}")
        _history_cache[key] = None
        return None
    data = _validate_ohlcv(data, symbol)
    if data is None:
        _health["history_invalid"] += 1
    _history_cache[key] = None if data is None else data.copy()
    return None if data is None else data.copy()


def hardened_screen(query, **kwargs):
    _health["screen_attempts"] += 1
    try:
        return _retry(lambda: _ORIGINAL_YF_SCREEN(query, **kwargs), "Yahoo screener")
    except Exception:
        _health["screen_failures"] += 1
        raise


def strict_state_signature(df: pd.DataFrame, pos: int) -> np.ndarray | None:
    """Require a full 252-session high window for historical analogs."""
    if pos < 252:
        return None
    c = pd.to_numeric(df["Close"], errors="coerce")
    h = pd.to_numeric(df["High"], errors="coerce")
    v = pd.to_numeric(df["Volume"], errors="coerce")
    sma = c.rolling(20).mean()
    sd = c.rolling(20).std()
    z = (c - sma) / sd
    rr = scanner.rsi(c)
    hi = h.rolling(252).max()
    dist = (hi - c) / hi
    rv = v / v.rolling(20).mean()
    sig = np.array([z.iloc[pos], rr.iloc[pos], dist.iloc[pos], rv.iloc[pos]], dtype=float)
    return sig if np.all(np.isfinite(sig)) else None


def hardened_signal_history(ticker: str) -> pd.DataFrame | None:
    df = hardened_history(ticker, "2y")
    if df is None:
        return None
    out = df.copy()
    out.index = pd.to_datetime(out.index, utc=True)
    return out


def patch():
    scanner.history = hardened_history
    scanner.safe_info = _cached_info
    scanner.yf.screen = hardened_screen
    scanner.state_signature = strict_state_signature
    import scanner.signal_lab as lab
    lab._history = hardened_signal_history


def _annotate_options():
    if not OUT.exists():
        return
    try:
        payload = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        return
    for key in ("scanner_a", "scanner_b"):
        for item in payload.get(key, []) or []:
            opt = item.get("options")
            if isinstance(opt, dict) and opt.get("net_dollar_gamma") is not None:
                opt["gamma_methodology"] = "Black-Scholes approximation from public OI/IV; call-plus / put-minus convention; not dealer positioning."
                opt["gamma_is_context_only"] = True
    total = _health["history_requests"]
    failures = _health["history_failures"] + _health["history_invalid"]
    payload["data_health"] = {
        **_health,
        "history_problem_rate": round(failures / total, 4) if total else 0.0,
        "health_rule": "No fabricated values; provider problems remain visible. Large degradation should be investigated before acting on rankings.",
    }
    OUT.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def main():
    patch()
    scanner.main()
    _annotate_options()


if __name__ == "__main__":
    main()
