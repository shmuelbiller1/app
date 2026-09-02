"""Signal Laboratory: persistent event ledger + walk-forward outcome analysis.

The lab records scanner observations without inventing future outcomes. It keeps
signal counts separate from matured outcome counts so a new installation does
not misleadingly report zero signals merely because no forward horizon has
matured yet.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from scanner.research_stats import bootstrap_ci

DB_PATH = os.getenv("SIGNAL_LAB_DB", "data/signal_lab.sqlite3")
HORIZONS = (1, 3, 5, 10, 20)

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_key TEXT NOT NULL UNIQUE,
    signal_time TEXT NOT NULL,
    scanner TEXT NOT NULL,
    ticker TEXT NOT NULL,
    score REAL,
    probability REAL,
    evidence_quality TEXT,
    feature_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    close_at_signal REAL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_scanner_ticker_time ON signals(scanner, ticker, signal_time);
CREATE TABLE IF NOT EXISTS outcomes (
    signal_id INTEGER NOT NULL,
    horizon INTEGER NOT NULL,
    future_time TEXT,
    future_close REAL,
    return_pct REAL,
    hit_target INTEGER,
    max_favorable_excursion_pct REAL,
    max_adverse_excursion_pct REAL,
    PRIMARY KEY(signal_id, horizon),
    FOREIGN KEY(signal_id) REFERENCES signals(id)
);
CREATE INDEX IF NOT EXISTS idx_outcomes_horizon ON outcomes(horizon);
CREATE TABLE IF NOT EXISTS lab_runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_time TEXT NOT NULL,
    signals_seen INTEGER NOT NULL,
    outcomes_filled INTEGER NOT NULL,
    summary_json TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    c.executescript(SCHEMA)
    return c


def signal_key(scanner: str, ticker: str, signal_time: str) -> str:
    return f"{scanner}|{ticker.upper()}|{signal_time}"


def record_signals(payload: dict[str, Any]) -> int:
    rows: list[tuple[Any, ...]] = []
    now = datetime.now(timezone.utc).isoformat()
    for scanner_name, items in (("A", payload.get("scanner_a", [])), ("B", payload.get("scanner_b", []))):
        for x in items:
            t = str(x.get("ticker", "")).upper()
            ts = str(x.get("signal_time") or payload.get("generated_at") or now)
            if not t:
                continue
            rows.append((
                signal_key(scanner_name, t, ts), ts, scanner_name, t,
                float(x["score"]) if x.get("score") is not None else None,
                float(x["probability"]) if x.get("probability") is not None else None,
                str(x.get("data_quality", "UNKNOWN")),
                json.dumps({k: v for k, v in x.items() if k not in {"ticker", "score", "probability"}}, sort_keys=True, default=str),
                json.dumps({"options": x.get("options"), "industry": x.get("industry")}, sort_keys=True),
                float(x["price"]) if x.get("price") is not None else None,
                now,
            ))
    with connect() as c:
        before = c.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        c.executemany("INSERT OR IGNORE INTO signals(signal_key,signal_time,scanner,ticker,score,probability,evidence_quality,feature_json,metadata_json,close_at_signal,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
        after = c.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    return after - before


def _history(ticker: str) -> pd.DataFrame | None:
    try:
        import yfinance as yf
        df = yf.download(ticker, period="2y", interval="1d", auto_adjust=False, progress=False, threads=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        cols = [c for c in ["Open", "High", "Low", "Close"] if c in df.columns]
        if "Close" not in cols:
            return None
        out = df[cols].dropna().copy()
        out.index = pd.to_datetime(out.index, utc=True)
        return out
    except Exception:
        return None


def _fill_for_signal(row: sqlite3.Row, df: pd.DataFrame, c: sqlite3.Cursor) -> int:
    ts = pd.Timestamp(row["signal_time"])
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    pos = int(df.index.searchsorted(ts, side="right"))
    if pos >= len(df):
        return 0
    entry_close = float(row["close_at_signal"]) if row["close_at_signal"] is not None else float(df["Close"].iloc[pos - 1] if pos > 0 else df["Close"].iloc[pos])
    filled = 0
    for h in HORIZONS:
        if pos + h >= len(df) or c.execute("SELECT 1 FROM outcomes WHERE signal_id=? AND horizon=?", (row["id"], h)).fetchone():
            continue
        window = df.iloc[pos:pos+h+1]
        future_close = float(df["Close"].iloc[pos+h])
        ret = future_close / entry_close - 1.0
        mfe = float(window["High"].max() / entry_close - 1.0) if "High" in window else float(window["Close"].max() / entry_close - 1.0)
        mae = float(window["Low"].min() / entry_close - 1.0) if "Low" in window else float(window["Close"].min() / entry_close - 1.0)
        c.execute("INSERT INTO outcomes(signal_id,horizon,future_time,future_close,return_pct,hit_target,max_favorable_excursion_pct,max_adverse_excursion_pct) VALUES(?,?,?,?,?,?,?,?)", (row["id"], h, df.index[pos+h].isoformat(), future_close, ret*100, int(ret > 0), mfe*100, mae*100))
        filled += 1
    return filled


def fill_outcomes() -> int:
    with connect() as c:
        c.row_factory = sqlite3.Row
        rows = c.execute("SELECT * FROM signals ORDER BY signal_time").fetchall()
        total = 0
        cache: dict[str, pd.DataFrame | None] = {}
        for row in rows:
            if row["ticker"] not in cache:
                cache[row["ticker"]] = _history(row["ticker"])
            if cache[row["ticker"]] is not None:
                total += _fill_for_signal(row, cache[row["ticker"]], c)
    return total


def _metrics(values: np.ndarray) -> dict[str, Any]:
    v = values[np.isfinite(values)]
    if len(v) == 0:
        return {"n": 0}
    binary = (v > 0).astype(float)
    low, high = bootstrap_ci(binary, np.mean, n_resamples=1000, mean_block=min(7, len(v))) if len(v) >= 20 else (None, None)
    return {"n": int(len(v)), "positive_rate": float(binary.mean()), "mean_return_pct": float(v.mean()), "median_return_pct": float(np.median(v)), "best_return_pct": float(v.max()), "worst_return_pct": float(v.min()), "mean_abs_return_pct": float(np.abs(v).mean()), "ci95_positive_rate": [low, high] if low is not None else None}


def summarize(test_fraction: float = 0.30) -> dict[str, Any]:
    with connect() as c:
        signal_counts = pd.read_sql_query("SELECT scanner, COUNT(*) AS n FROM signals GROUP BY scanner", c)
        df = pd.read_sql_query("SELECT s.scanner,s.ticker,s.score,s.probability,s.signal_time,o.horizon,o.return_pct,o.max_favorable_excursion_pct,o.max_adverse_excursion_pct FROM signals s JOIN outcomes o ON o.signal_id=s.id", c)
    total_signals = int(signal_counts["n"].sum()) if not signal_counts.empty else 0
    counts_by_scanner = {str(r.scanner): int(r.n) for r in signal_counts.itertuples()}
    result: dict[str, Any] = {"signals": total_signals, "signals_by_scanner": counts_by_scanner, "matured_outcome_rows": int(len(df)), "horizons": {}}
    if df.empty:
        result["status"] = "COLLECTING_OUTCOMES"
        result["message"] = "Signals are being recorded; no forward outcomes have matured yet."
        return result
    df["signal_time"] = pd.to_datetime(df["signal_time"], utc=True)
    cutoff = df["signal_time"].quantile(1.0 - test_fraction) if len(df) >= 20 else df["signal_time"].max()
    result["cutoff"] = cutoff.isoformat()
    for scanner in ["A", "B"]:
        part = df[df.scanner == scanner]
        result[scanner] = {"all": {}, "out_of_sample": {}}
        for h in HORIZONS:
            hp = part[part.horizon == h]
            result[scanner]["all"][str(h)] = _metrics(hp.return_pct.to_numpy(float))
            result[scanner]["out_of_sample"][str(h)] = _metrics(hp[hp.signal_time >= cutoff].return_pct.to_numpy(float))
        for label, lo, hi in [("60_70",60,70),("70_80",70,80),("80_90",80,90),("90_100",90,100.0001)]:
            bp = part[(part.score >= lo) & (part.score < hi)]
            result[scanner].setdefault("score_buckets", {})[label] = {str(h): _metrics(bp[bp.horizon == h].return_pct.to_numpy(float)) for h in HORIZONS}
    return result


def write_lab_report(path: str = "frontend/public/signal-lab.json") -> dict[str, Any]:
    filled = fill_outcomes()
    summary = summarize()
    summary["outcomes_filled_this_run"] = filled
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    with connect() as c:
        c.execute("INSERT INTO lab_runs(run_time,signals_seen,outcomes_filled,summary_json) VALUES(?,?,?,?)", (summary["generated_at"], summary.get("signals",0), filled, json.dumps(summary, default=str)))
    return summary

if __name__ == "__main__":
    print(json.dumps(write_lab_report(), indent=2))
