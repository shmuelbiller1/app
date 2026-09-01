"""Stateful alert layer for the quantitative scanner.

The scanner produces observations; this module decides whether the latest
observation is materially different from the previous one. This prevents a
30-minute cron job from sending the same alert over and over.

Alert states:
- NEW: first observation above the alert threshold
- STRENGTHENING: score increased materially
- INVALIDATED: a previously alerted signal fell below the threshold or
  disappeared from the current candidate set

Scores are rankings, not probabilities. The alert text deliberately exposes
supporting evidence instead of claiming that a squeeze/reversal is certain.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATE_PATH = DATA / "alert_state.json"
SCAN_PATH = ROOT / "frontend" / "public" / "scanner-data.json"

THRESHOLD = float(os.getenv("ALERT_MIN_SCORE", "85"))
CHANGE = float(os.getenv("ALERT_SCORE_CHANGE", "5"))
COOLDOWN = int(os.getenv("ALERT_COOLDOWN_SECONDS", "14400"))


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def describe(kind: str, x: dict) -> str:
    if kind == "A":
        p = x.get("probability")
        ptxt = f" | historical P(down 5d)={p:.0%} n={x.get('probability_sample', 0)}" if isinstance(p, (int, float)) else ""
        return f"z20={x.get('z_score','?')} | RSI={x.get('rsi','?')} | RV={x.get('relative_volume','?')}{ptxt}"
    return f"short float={x.get('short_float','?')}% | DTC={x.get('days_to_cover','?')} | RV={x.get('rel_volume','?')} | 1d={x.get('price_change','?')}%"


def run() -> list[dict]:
    webhook = os.getenv("DISCORD_WEBHOOK_URL")
    scan = load_json(SCAN_PATH, {})
    current: dict[str, dict] = {}
    for kind, key in (("A", "scanner_a"), ("B", "scanner_b")):
        for x in scan.get(key, []) or []:
            ticker = str(x.get("ticker", "")).upper()
            if ticker:
                current[f"{kind}:{ticker}"] = x

    state = load_json(STATE_PATH, {})
    now = time.time()
    events: list[dict] = []

    # New or strengthening signals.
    for key, x in current.items():
        score = float(x.get("score", 0) or 0)
        if score < THRESHOLD:
            continue
        previous = state.get(key, {})
        prev_score = float(previous.get("score", -999) or -999)
        last_alert = float(previous.get("alerted_at", 0) or 0)
        if not previous:
            status = "NEW"
        elif score - prev_score >= CHANGE:
            status = "STRENGTHENING"
        else:
            status = None
        if status and (not previous or now - last_alert >= COOLDOWN):
            events.append({"status": status, "key": key, "ticker": x.get("ticker"), "score": score, "detail": describe(key.split(":",1)[0], x)})
            previous["alerted_at"] = now
        previous["score"] = score
        previous["last_seen"] = now
        previous["above_threshold"] = score >= THRESHOLD
        state[key] = previous

    # Previously important signals that are no longer above threshold.
    for key, previous in list(state.items()):
        if key not in current and previous.get("above_threshold") and now - float(previous.get("last_seen", now)) >= 0:
            events.append({"status": "INVALIDATED", "key": key, "ticker": key.split(":",1)[-1], "score": float(previous.get("score", 0)), "detail": "No longer present in the current candidate set."})
            previous["above_threshold"] = False
            previous["invalidated_at"] = now
            state[key] = previous
        elif key in current:
            score = float(current[key].get("score", 0) or 0)
            if previous.get("above_threshold") and score < THRESHOLD:
                events.append({"status": "INVALIDATED", "key": key, "ticker": current[key].get("ticker"), "score": score, "detail": f"Score fell below {THRESHOLD:.0f}."})
                previous["above_threshold"] = False
                previous["invalidated_at"] = now

    save_json(STATE_PATH, state)

    if not events or not webhook:
        return events

    lines = ["**Quant Scanner — signal state update**"]
    for e in events:
        lines.append(f"{e['status']} | **{e['key']}** | score={e['score']:.1f} | {e['detail']}")
    lines.append("Research signal only — verify live prices, liquidity, source freshness and options before acting.")
    try:
        r = requests.post(webhook, json={"content": "\n".join(lines)}, timeout=15)
        r.raise_for_status()
    except Exception as exc:
        print(f"Discord smart alert failed: {exc}")
    return events


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
