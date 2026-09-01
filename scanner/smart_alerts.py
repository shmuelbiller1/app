"""Stateful alert delivery for the quantitative scanner.

The scanner produces observations; this module decides whether the latest
observation is materially different from the previous one. This prevents a
30-minute schedule from sending the same alert repeatedly.

Primary transports:
- Pushover: fast phone/desktop push notifications.
- SMTP email: durable alert record and fallback channel.

Alert states:
- NEW: first observation above the alert threshold
- STRENGTHENING: score increased materially
- INVALIDATED: a previously alerted signal fell below the threshold or
  disappeared from the current candidate set

Scores are rankings, not probabilities. The alert text exposes supporting
evidence and data context instead of claiming that a squeeze/reversal is
certain.
"""
from __future__ import annotations

import json
import os
import smtplib
import time
from email.message import EmailMessage
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATE_PATH = DATA / "alert_state.json"
SCAN_PATH = ROOT / "frontend" / "public" / "scanner-data.json"

THRESHOLD = float(os.getenv("ALERT_MIN_SCORE", "85"))
CHANGE = float(os.getenv("ALERT_SCORE_CHANGE", "5"))
COOLDOWN = int(os.getenv("ALERT_COOLDOWN_SECONDS", "14400"))
DASHBOARD_URL = os.getenv("ALERT_DASHBOARD_URL", "")


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
        ptxt = (
            f" | historical P(down 5d)={p:.0%} n={x.get('probability_sample', 0)}"
            if isinstance(p, (int, float))
            else ""
        )
        return (
            f"z20={x.get('z_score', '?')} | RSI={x.get('rsi', '?')} | "
            f"RV={x.get('relative_volume', '?')}{ptxt}"
        )
    return (
        f"short float={x.get('short_float', '?')}% | "
        f"DTC={x.get('days_to_cover', '?')} | "
        f"RV={x.get('rel_volume', x.get('relative_volume', '?'))} | "
        f"1d={x.get('price_change', '?')}%"
    )


def build_messages(events: list[dict]) -> tuple[str, str, str]:
    """Return (subject, plain_text, pushover_message)."""
    if not events:
        return "Quant Scanner — no alert", "No alert events.", "No alert events."

    statuses = {str(e["status"]).upper() for e in events}
    if "NEW" in statuses:
        lead = "NEW"
    elif "STRENGTHENING" in statuses:
        lead = "STRENGTHENING"
    elif "INVALIDATED" in statuses:
        lead = "INVALIDATED"
    else:
        lead = "SIGNAL UPDATE"

    subject = f"Quant Scanner — {lead} — {len(events)} signal{'s' if len(events) != 1 else ''}"
    lines = [
        "Quant Scanner — signal state update",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
    ]
    for e in events:
        lines.append(
            f"{e['status']} | {e['key']} | score={e['score']:.1f} | {e['detail']}"
        )
    lines.extend(
        [
            "",
            "Research signal only — verify live price, liquidity, source freshness and options before acting.",
        ]
    )
    if DASHBOARD_URL:
        lines.extend(["", f"Dashboard: {DASHBOARD_URL}"])
    text = "\n".join(lines)

    # Pushover supports a compact notification; the detailed record remains in email/dashboard.
    push_lines = [f"{e['status']} {e['key']} score {e['score']:.1f}" for e in events]
    push_lines.append("Verify live data before acting.")
    if DASHBOARD_URL:
        push_lines.append(DASHBOARD_URL)
    pushover = "\n".join(push_lines)
    return subject, text, pushover


def send_pushover(subject: str, message: str) -> bool:
    token = os.getenv("PUSHOVER_APP_TOKEN", "").strip()
    user = os.getenv("PUSHOVER_USER_KEY", "").strip()
    if not token or not user:
        return False

    max_priority_score = max((float(v) for v in os.getenv("ALERT_HIGH_PRIORITY_SCORE", "95").split(",") if v.strip()), default=95.0)
    # Use emergency-style attention only for a deliberately configured extreme signal.
    priority = 1 if any(float(e.get("score", 0)) >= max_priority_score for e in []) else 0

    payload = {
        "token": token,
        "user": user,
        "title": subject,
        "message": message,
        "priority": priority,
    }
    if DASHBOARD_URL:
        payload["url"] = DASHBOARD_URL
        payload["url_title"] = "Open scanner dashboard"

    try:
        response = requests.post(
            "https://api.pushover.net/1/messages.json",
            data=payload,
            timeout=15,
        )
        response.raise_for_status()
        result = response.json()
        if result.get("status") != 1:
            raise RuntimeError(f"Pushover returned status={result.get('status')}")
        print("Pushover alert delivered.")
        return True
    except Exception as exc:
        print(f"Pushover alert failed: {exc}")
        return False


def send_email(subject: str, body: str) -> bool:
    host = os.getenv("SMTP_HOST", "").strip()
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    recipients = [x.strip() for x in os.getenv("ALERT_EMAIL_TO", "").split(",") if x.strip()]
    sender = os.getenv("ALERT_EMAIL_FROM", "").strip() or username
    port = int(os.getenv("SMTP_PORT", "587"))
    use_ssl = os.getenv("SMTP_USE_SSL", "0").lower() in {"1", "true", "yes"}
    use_tls = os.getenv("SMTP_USE_TLS", "1").lower() in {"1", "true", "yes"}

    if not host or not username or not password or not recipients or not sender:
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    try:
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=20) as server:
                server.login(username, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=20) as server:
                server.ehlo()
                if use_tls:
                    server.starttls()
                    server.ehlo()
                server.login(username, password)
                server.send_message(message)
        print("Email alert delivered.")
        return True
    except Exception as exc:
        print(f"Email alert failed: {exc}")
        return False


def deliver(events: list[dict]) -> dict[str, bool]:
    subject, email_body, push_body = build_messages(events)
    results = {
        "pushover": send_pushover(subject, push_body),
        "email": send_email(subject, email_body),
    }
    if events and not any(results.values()):
        print("WARNING: alert events exist but no alert transport is configured or reachable.")
    return results


def run() -> list[dict]:
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
        if not previous or not previous.get("above_threshold"):
            status = "NEW"
        elif score - prev_score >= CHANGE:
            status = "STRENGTHENING"
        else:
            status = None
        if status and (not previous or now - last_alert >= COOLDOWN):
            events.append(
                {
                    "status": status,
                    "key": key,
                    "ticker": x.get("ticker"),
                    "score": score,
                    "detail": describe(key.split(":", 1)[0], x),
                }
            )
            previous["alerted_at"] = now
        previous["score"] = score
        previous["last_seen"] = now
        previous["above_threshold"] = score >= THRESHOLD
        state[key] = previous

    # Previously important signals that are no longer above threshold.
    for key, previous in list(state.items()):
        if key not in current and previous.get("above_threshold"):
            events.append(
                {
                    "status": "INVALIDATED",
                    "key": key,
                    "ticker": key.split(":", 1)[-1],
                    "score": float(previous.get("score", 0)),
                    "detail": "No longer present in the current candidate set.",
                }
            )
            previous["above_threshold"] = False
            previous["invalidated_at"] = now
            state[key] = previous
        elif key in current:
            score = float(current[key].get("score", 0) or 0)
            if previous.get("above_threshold") and score < THRESHOLD:
                events.append(
                    {
                        "status": "INVALIDATED",
                        "key": key,
                        "ticker": current[key].get("ticker"),
                        "score": score,
                        "detail": f"Score fell below {THRESHOLD:.0f}.",
                    }
                )
                previous["above_threshold"] = False
                previous["invalidated_at"] = now

    save_json(STATE_PATH, state)

    if events:
        transport_results = deliver(events)
        print(json.dumps({"events": events, "transport_results": transport_results}, indent=2))
    else:
        print("No new alert events.")
    return events


if __name__ == "__main__":
    run()
