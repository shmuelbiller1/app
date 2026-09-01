"""Windows companion for Quant Scanner.

Runs the zero-key-first scanner locally on a Windows PC during 09:30-16:00
America/New_York, then generates native Windows toast notifications for
NEW, STRENGTHENING, WEAKENING and INVALIDATED research states.

No financial credentials are required. The companion reads the scanner's
current JSON field names directly; it does not use the cloud email transport.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from win11toast import toast
except ImportError:
    toast = None

ET = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = Path(os.getenv("LOCALAPPDATA", Path.home())) / "QuantScanner"
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = STATE_DIR / "desktop_alert_state.json"
LOG_FILE = STATE_DIR / "desktop_agent.log"
INTERVAL = int(os.getenv("SCANNER_INTERVAL_SECONDS", "1800"))
DASHBOARD_URL = os.getenv("SCANNER_DASHBOARD_URL", "https://github.com/shmuelbiller1/app")
SCORE_THRESHOLD = float(os.getenv("DESKTOP_ALERT_MIN_SCORE", "85"))
STRENGTHEN_DELTA = float(os.getenv("DESKTOP_ALERT_SCORE_DELTA", "5"))
WEAKEN_DELTA = float(os.getenv("DESKTOP_ALERT_WEAKEN_DELTA", "7"))
RESET_BELOW = float(os.getenv("DESKTOP_SIGNAL_RESET_SCORE", "70"))


def log(message: str) -> None:
    stamp = datetime.now().isoformat(timespec="seconds")
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {message}\n")


def session_open() -> bool:
    now = datetime.now(ET)
    return now.weekday() < 5 and dtime(9, 30) <= now.time() <= dtime(16, 0)


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def stable_signal_id(kind: str, x: dict) -> str:
    return hashlib.sha256(f"{kind}|{x.get('ticker')}".encode()).hexdigest()[:20]


def describe(kind: str, x: dict) -> str:
    score = float(x.get("score", 0) or 0)
    options = x.get("options") if isinstance(x.get("options"), dict) else {}
    opt = options.get("status", "NOT_CHECKED")
    if kind == "A":
        bits = [
            f"Score {score:.1f}",
            f"52W distance {x.get('distance_52w', '?')}%",
            f"RV {x.get('relative_volume', '?')}x",
            f"RSI {x.get('rsi14', '?')}",
        ]
        p = x.get("downside_probability_5d")
        n = x.get("probability_sample")
        if isinstance(p, (int, float)):
            bits.append(f"5D downside {p:.1f}% (n={n})")
        bits.append(f"Options {opt}")
        return " • ".join(bits)
    return " • ".join([
        f"Score {score:.1f}",
        f"Short/float {x.get('short_float_pct', '?')}%",
        f"DTC {x.get('days_to_cover', '?')}",
        f"RV {x.get('relative_volume', '?')}x",
        f"5D {x.get('momentum_5d', '?')}%",
        f"Options {opt}",
    ])


def notify(title: str, message: str) -> None:
    log(f"NOTIFY: {title} | {message}")
    if toast is None:
        return
    try:
        toast(title, message, on_click=DASHBOARD_URL, duration="long")
    except Exception as exc:
        log(f"toast error: {exc}")


def run_scanner() -> dict | None:
    scanner = ROOT / "scanner" / "run_scanner.py"
    if not scanner.exists():
        log(f"missing scanner: {scanner}")
        return None
    env = os.environ.copy()
    env.pop("DISCORD_WEBHOOK_URL", None)
    result = subprocess.run(
        [sys.executable, str(scanner)], cwd=str(ROOT), env=env,
        capture_output=True, text=True, timeout=15 * 60,
    )
    if result.returncode != 0:
        log(f"scanner failed rc={result.returncode}: {result.stderr[-1500:]}")
        return None
    data_file = ROOT / "frontend" / "public" / "scanner-data.json"
    if not data_file.exists():
        log("scanner finished but scanner-data.json was not produced")
        return None
    try:
        return json.loads(data_file.read_text(encoding="utf-8"))
    except Exception as exc:
        log(f"invalid scanner-data.json: {exc}")
        return None


def process_changes(payload: dict) -> None:
    state = load_state()
    current = {}
    events = []
    for kind, items in (("A", payload.get("scanner_a", [])), ("B", payload.get("scanner_b", []))):
        for x in items:
            score = float(x.get("score", 0) or 0)
            if score < RESET_BELOW:
                continue
            key = stable_signal_id(kind, x)
            current[key] = {"kind": kind, "ticker": x.get("ticker"), "score": score, "seen": time.time()}
            previous = state.get(key)
            if score >= SCORE_THRESHOLD and not previous:
                events.append(("🚨 NEW SIGNAL", kind, x))
            elif previous:
                previous_score = float(previous.get("score", score))
                delta = score - previous_score
                if delta >= STRENGTHEN_DELTA and score >= SCORE_THRESHOLD:
                    events.append(("📈 SIGNAL STRENGTHENING", kind, x))
                elif delta <= -WEAKEN_DELTA and previous_score >= SCORE_THRESHOLD and score < previous_score:
                    events.append(("⚠️ SIGNAL WEAKENING", kind, x))

    for key, previous in state.items():
        if key not in current and float(previous.get("score", 0)) >= SCORE_THRESHOLD:
            events.append((
                f"⚠️ SIGNAL INVALIDATED — {previous.get('ticker', '?')}",
                previous.get("kind", "?"),
                {"ticker": previous.get("ticker"), "score": RESET_BELOW, "options": {"status": "NOT_CHECKED"}},
            ))

    for title, kind, x in events:
        notify(f"{title} | Scanner {kind} | {x.get('ticker', '?')}", describe(kind, x))
    state.update(current)
    save_state(state)


def wait_to_next_half_hour() -> int:
    now = time.time()
    return max(5, int(INTERVAL - (now % INTERVAL)))


def main() -> None:
    log("Quant Scanner Windows companion started")
    if toast is None:
        log("WARNING: win11toast is not installed; desktop notifications are disabled")
    while True:
        try:
            if session_open():
                log("market session open: running scanner")
                payload = run_scanner()
                if payload is not None:
                    process_changes(payload)
            else:
                log("market closed: sleeping")
        except Exception as exc:
            log(f"agent error: {exc}")
        time.sleep(wait_to_next_half_hour())


if __name__ == "__main__":
    main()
