"""FINRA public-credential client for current short-interest research.

Implements FINRA's OAuth2 client-credentials flow and the public Query API
for Consolidated Short Interest + Reg SHO Daily Short Sale Volume.
Credentials are read only from environment variables.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests

FIP_TOKEN_URL = "https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token?grant_type=client_credentials"
API_BASE = "https://api.finra.org"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "QuantScanner/3.0 research"})


def _credentials() -> tuple[str, str]:
    cid = os.getenv("FINRA_CLIENT_ID", "").strip()
    secret = os.getenv("FINRA_CLIENT_SECRET", "").strip()
    if not cid or not secret:
        raise RuntimeError("FINRA_CLIENT_ID and FINRA_CLIENT_SECRET are required")
    return cid, secret


def get_access_token() -> str:
    cid, secret = _credentials()
    r = SESSION.post(FIP_TOKEN_URL, auth=(cid, secret), timeout=20)
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("FINRA token response did not contain access_token")
    return token


def _get_json_dataset(group: str, dataset: str, params: dict[str, Any]) -> tuple[list[dict[str, Any]], requests.structures.CaseInsensitiveDict[str]]:
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "Data-API-Version": "1"}
    r = SESSION.get(f"{API_BASE}/data/group/{group}/name/{dataset}", params=params, headers=headers, timeout=45)
    r.raise_for_status()
    payload = r.json()
    if not isinstance(payload, list):
        raise RuntimeError(f"FINRA dataset {group}/{dataset} returned unexpected payload")
    return payload, r.headers


def _post_json_dataset(group: str, dataset: str, body: dict[str, Any]) -> tuple[list[dict[str, Any]], requests.structures.CaseInsensitiveDict[str]]:
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "Data-API-Version": "1"}
    r = SESSION.post(f"{API_BASE}/data/group/{group}/name/{dataset}", json=body, headers=headers, timeout=60)
    r.raise_for_status()
    payload = r.json()
    if not isinstance(payload, list):
        raise RuntimeError(f"FINRA dataset {group}/{dataset} returned unexpected payload")
    return payload, r.headers


def _latest_date(group: str, dataset: str, field: str) -> str:
    rows, _ = _get_json_dataset(
        group,
        dataset,
        {"limit": 1, "sortFields": f"-{field}", "fields": field},
    )
    if not rows or not rows[0].get(field):
        raise RuntimeError(f"Could not determine latest {field} from FINRA {dataset}")
    return str(rows[0][field]).split(" ")[0]


def _paged_current_date(group: str, dataset: str, date_field: str) -> tuple[list[dict[str, Any]], str]:
    latest = _latest_date(group, dataset, date_field)
    fields = {
        "consolidatedShortInterest": [
            "symbolCode", "issueName", "currentShortPositionQuantity",
            "previousShortPositionQuantity", "averageDailyVolumeQuantity",
            "daysToCoverQuantity", "changePercent", "changePreviousNumber",
            "settlementDate", "marketClassCode", "issuerServicesGroupExchangeCode"
        ],
        "regShoDaily": [
            "securitiesInformationProcessorSymbolIdentifier", "tradeReportDate",
            "shortParQuantity", "shortExemptParQuantity", "totalParQuantity"
        ],
    }[dataset]
    body_base = {
        "limit": 5000,
        "fields": fields,
        "compareFilters": [{"compareType": "equal", "fieldName": date_field, "fieldValue": latest}],
        "sortFields": [f"+{fields[0]}"]
    }
    all_rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        body = dict(body_base)
        body["offset"] = offset
        rows, headers = _post_json_dataset(group, dataset, body)
        all_rows.extend(rows)
        total = int(headers.get("Record-Total", len(all_rows)))
        if not rows or len(all_rows) >= total:
            break
        offset += len(rows)
        if offset > 500_000:
            raise RuntimeError("FINRA pagination reached synchronous offset limit")
    return all_rows, latest


def fetch_current_short_interest() -> tuple[pd.DataFrame, str]:
    rows, asof = _paged_current_date("otcMarket", "consolidatedShortInterest", "settlementDate")
    df = pd.DataFrame(rows)
    if df.empty:
        return df, asof
    df = df.rename(columns={
        "symbolCode": "ticker",
        "currentShortPositionQuantity": "short_interest",
        "previousShortPositionQuantity": "previous_short_interest",
        "averageDailyVolumeQuantity": "average_daily_volume",
        "daysToCoverQuantity": "days_to_cover",
        "changePercent": "si_change_pct",
        "settlementDate": "settlement_date",
    })
    numeric = ["short_interest", "previous_short_interest", "average_daily_volume", "days_to_cover", "si_change_pct"]
    for c in numeric:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["short_float"] = pd.NA  # filled later from equity float data
    df["finra_asof"] = asof
    return df, asof


def fetch_latest_reg_sho() -> tuple[pd.DataFrame, str]:
    rows, asof = _paged_current_date("otcMarket", "regShoDaily", "tradeReportDate")
    df = pd.DataFrame(rows)
    if df.empty:
        return df, asof
    df = df.rename(columns={
        "securitiesInformationProcessorSymbolIdentifier": "ticker",
        "shortParQuantity": "short_volume",
        "shortExemptParQuantity": "short_exempt_volume",
        "totalParQuantity": "total_volume",
        "tradeReportDate": "reg_sho_date",
    })
    for c in ["short_volume", "short_exempt_volume", "total_volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df["short_volume_ratio"] = df["short_volume"] / df["total_volume"].replace(0, pd.NA)
    df["reg_sho_asof"] = asof
    return df, asof


def run_finra_ingest(output_dir: str = "data") -> dict[str, Any]:
    os.makedirs(output_dir, exist_ok=True)
    si, si_date = fetch_current_short_interest()
    rs, rs_date = fetch_latest_reg_sho()
    si.to_csv(os.path.join(output_dir, "finra_short_interest.csv"), index=False)
    rs.to_csv(os.path.join(output_dir, "finra_reg_sho_daily.csv"), index=False)
    return {
        "short_interest_rows": int(len(si)),
        "short_interest_asof": si_date,
        "reg_sho_rows": int(len(rs)),
        "reg_sho_asof": rs_date,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
