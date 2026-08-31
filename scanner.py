"""Quant Scanner research engine.

Two independent scanners:
A) Leveraged/inverse ETF overextension/reversal candidates.
B) Short-interest squeeze candidates.

Design goals:
- use free market history locally (yfinance) instead of relying on premium candles;
- never turn a sparse sample into a fake probability;
- separate signal strength from data quality;
- keep options validation finalist-only and explicitly optional;
- emit enough evidence that every alert can be audited.
"""
import json, os, time
from datetime import datetime, timezone
import requests
import pandas as pd
import numpy as np
import yfinance as yf

FINNHUB = "https://finnhub.io/api/v1"
EXCLUDED = {"Technology", "Biotechnology", "Software", "Semiconductors"}
# Deliberately excludes SOXL/SOXS and LABU/LABD because their underlying exposure
# is technology/biotechnology and the requested universe is non-tech/non-biotech.
LEVERAGED = [
    "YANG","YINN","NUGT","DUST","ERX","ERY","FAS","FAZ","UCO","SCO",
    "BOIL","KOLD","GUSH","DRIP","TNA","TZA","TMF","TMV"
]

session = requests.Session()
session.headers.update({"User-Agent": "QuantScanner/2.0 research"})


def fh(endpoint, params):
    key = os.getenv("FINNHUB_API_KEY")
    if not key:
        return {}
    p = dict(params); p["token"] = key
    r = session.get(f"{FINNHUB}/{endpoint}", params=p, timeout=20)
    r.raise_for_status()
    return r.json()


def candles(symbol, days=400):
    """Free daily OHLCV history. Yahoo is a data source, not a signal source."""
    try:
        df = yf.download(symbol, period=f"{max(days, 60)}d", interval="1d", auto_adjust=False,
                         progress=False, threads=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        needed = {"Close", "Volume"}
        if not needed.issubset(df.columns):
            return None
        out = df[["Close", "Volume"]].copy().rename(columns={"Close":"close", "Volume":"volume"})
        out = out.dropna()
        out.index = pd.to_datetime(out.index, utc=True)
        return out.reset_index(names="date")
    except Exception as e:
        print("history", symbol, e)
        return None


def profile_ok(symbol):
    """Industry filter is best-effort; missing classification is not silently treated as safe."""
    try:
        p = fh("stock/profile2", {"symbol": symbol})
        industry = p.get("finnhubIndustry", "Unknown")
        if industry == "Unknown" and os.getenv("ALLOW_UNKNOWN_INDUSTRY", "0") != "1":
            return False, industry
        return industry not in EXCLUDED, industry
    except Exception:
        return False, "Unknown"


def rsi(series, n=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def feature_row(df):
    c, v = df.close, df.volume
    sma20 = c.rolling(20).mean(); sd20 = c.rolling(20).std()
    z = (c.iloc[-1] - sma20.iloc[-1]) / sd20.iloc[-1] if sd20.iloc[-1] else np.nan
    hi52 = c.tail(252).max(); px = c.iloc[-1]
    dist = (hi52 - px) / hi52 * 100 if hi52 else np.nan
    rrsi = rsi(c).iloc[-1]
    relvol = v.iloc[-1] / v.tail(20).mean() if v.tail(20).mean() else np.nan
    ret1 = (px / c.iloc[-2] - 1) * 100
    ret5 = (px / c.iloc[-6] - 1) * 100 if len(c) >= 6 else np.nan
    return {"price":float(px), "z_score":float(z), "high_distance":float(dist),
            "rsi":float(rrsi), "relative_volume":float(relvol),
            "return_1d":float(ret1), "return_5d":float(ret5),
            "avg_volume_20":float(v.tail(20).mean())}


def historical_probability(df, z_now, horizon=5, bandwidth=0.35, min_samples=20):
    """Walk-forward conditional frequency. No future observations are used to define a match."""
    c = df.close
    sma = c.rolling(20).mean(); sd = c.rolling(20).std()
    z = (c - sma) / sd
    outcomes = []
    for pos in range(20, len(df) - horizon):
        zi = z.iloc[pos]
        if pd.isna(zi) or abs(float(zi) - z_now) > bandwidth:
            continue
        # The state is measured at pos; only subsequent bars determine the outcome.
        future_ret = c.iloc[pos+horizon] / c.iloc[pos] - 1
        outcomes.append(bool(future_ret < 0))
    if len(outcomes) < min_samples:
        return None, len(outcomes)
    return float(np.mean(outcomes)), len(outcomes)


def scanner_a():
    out = []
    for symbol in LEVERAGED:
        try:
            ok, industry = profile_ok(symbol)
            if not ok:
                continue
            df = candles(symbol, 400)
            if df is None or len(df) < 100:
                continue
            f = feature_row(df)
            prob, n = historical_probability(df, f["z_score"])
            # Do not invent a probability. A missing estimate is reported as unavailable.
            if prob is None:
                probability = None
                prob_component = 0
                quality = "LOW_SAMPLE"
            else:
                probability = round(prob, 4)
                prob_component = probability * 20
                quality = "GOOD" if n >= 40 else "LIMITED"

            zc = min(max(f["z_score"] / 3.0, 0), 1) * 35
            hc = max(0, min(1, 1 - f["high_distance"] / 10)) * 25
            rc = max(0, min(1, (f["rsi"] - 55) / 25)) * 15
            vc = max(0, min(1, (f["relative_volume"] - 1) / 3)) * 5
            score = zc + hc + rc + vc + prob_component
            if score >= 50:
                out.append({
                    "ticker":symbol, "score":round(score,1), "probability":probability,
                    "probability_horizon_days":5, "probability_sample":n,
                    "data_quality":quality, "z_score":round(f["z_score"],2),
                    "high_distance":round(f["high_distance"],2), "rsi":round(f["rsi"],1),
                    "relative_volume":round(f["relative_volume"],2),
                    "return_1d":round(f["return_1d"],2), "return_5d":round(f["return_5d"],2),
                    "avg_volume_20":round(f["avg_volume_20"]), "industry":industry,
                    "options":"NOT_CHECKED"
                })
        except Exception as e:
            print("A", symbol, e)
    return sorted(out, key=lambda x:x["score"], reverse=True)[:20]


def load_finra():
    path = os.getenv("FINRA_SHORT_CSV", "data/finra_short_interest.csv")
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path)


def scanner_b():
    finra = load_finra()
    if finra.empty:
        return []
    required = {"ticker", "short_float", "days_to_cover"}
    if not required.issubset(finra.columns):
        print("FINRA file missing required columns", required - set(finra.columns))
        return []
    out=[]
    for _, row in finra.iterrows():
        symbol=str(row.ticker).upper().strip()
        try:
            ok, industry=profile_ok(symbol)
            if not ok: continue
            df=candles(symbol,90)
            if df is None or len(df)<30: continue
            f=feature_row(df)
            # Require both price and volume confirmation; high SI alone is not a squeeze.
            if f["return_1d"] < 3 or f["relative_volume"] < 1.5: continue
            sf=float(row.short_float); dtc=float(row.days_to_cover)
            si_change=float(row.si_change_pct) if "si_change_pct" in row and pd.notna(row.si_change_pct) else 0
            # Independent normalized factors, each 0..1, so no unit dominates by accident.
            sf_score=min(max(sf,0)/30,1)
            dtc_score=min(max(dtc,0)/10,1)
            change_score=min(max(si_change,0)/50,1)
            vol_score=min(max(f["relative_volume"],0)/5,1)
            momentum_score=min(max(f["return_1d"],0)/15,1)
            raw=.30*sf_score+.20*dtc_score+.20*change_score+.20*vol_score+.10*momentum_score
            out.append({"ticker":symbol,"score":round(raw*100,1),"short_float":round(sf,2),
                        "days_to_cover":round(dtc,2),"rel_volume":round(f["relative_volume"],2),
                        "price_change":round(f["return_1d"],2),"return_5d":round(f["return_5d"],2),
                        "si_change_pct":round(si_change,2),"industry":industry,
                        "options":"NOT_CHECKED"})
        except Exception as e: print("B",symbol,e)
    return sorted(out,key=lambda x:x["score"],reverse=True)[:20]


def options_check(candidates):
    """Optional finalist check. Never treats missing options data as proof of liquidity."""
    key=os.getenv("ALPHA_VANTAGE_API_KEY")
    if not key:
        return candidates
    for x in candidates[:10]:
        try:
            r=session.get("https://www.alphavantage.co/query",params={
                "function":"HISTORICAL_OPTIONS","symbol":x["ticker"],"apikey":key},timeout=20).json()
            rows=r.get("data",[])
            if not rows:
                x["options"]="NO_DATA"
                continue
            oi=sum(int(float(i.get("open_interest",0) or 0)) for i in rows[:50])
            volume=sum(int(float(i.get("volume",0) or 0)) for i in rows[:50])
            x["options_open_interest"]=oi
            x["options_volume"]=volume
            x["options"]="PASS" if oi>=500 and volume>0 else "WEAK"
        except Exception as e:
            x["options"]="ERROR"
            print("options",x["ticker"],e)
    return candidates


def alert(a,b):
    url=os.getenv("DISCORD_WEBHOOK_URL")
    if not url: return
    state_path="data/alert_state.json"
    os.makedirs("data",exist_ok=True)
    try:
        state=json.load(open(state_path)) if os.path.exists(state_path) else {}
    except Exception: state={}
    now=time.time(); cooldown=int(os.getenv("ALERT_COOLDOWN_SECONDS","14400"))
    candidates=[("A",x) for x in a if x["score"]>=85]+[("B",x) for x in b if x["score"]>=85]
    fresh=[]
    for kind,x in candidates:
        key=f"{kind}:{x['ticker']}"
        if now-state.get(key,0)>=cooldown:
            fresh.append((kind,x)); state[key]=now
    if not fresh: return
    lines=["**Quant Scanner — new high-confidence research signals**"]
    for kind,x in fresh:
        extra=(f" | P5d={x['probability']:.0%}" if kind=="A" and x.get("probability") is not None else "")
        lines.append(f"{kind} **{x['ticker']}** score={x['score']:.1f}{extra} | RV={x.get('relative_volume',x.get('rel_volume','?'))}")
    lines.append("Research signal only — verify data/options before trading.")
    session.post(url,json={"content":"\n".join(lines)},timeout=15).raise_for_status()
    with open(state_path,"w") as f: json.dump(state,f,indent=2)


def main():
    a=options_check(scanner_a()); b=options_check(scanner_b())
    payload={
        "generated_at":datetime.now(timezone.utc).isoformat(),
        "market_status":"SCANNED",
        "scanner_a":a,
        "scanner_b":b,
        "alerts_enabled":bool(os.getenv("DISCORD_WEBHOOK_URL")),
        "methodology":{
            "A":"Conditional historical 5-session downside frequency; minimum 20 comparable observations; no synthetic probability when sample is sparse.",
            "B":"Short-float + days-to-cover + SI change + relative volume + price momentum; all components normalized before weighting.",
            "options":"Finalist-only and explicitly marked PASS/WEAK/NO_DATA/NOT_CHECKED."
        }
    }
    os.makedirs("frontend/public",exist_ok=True)
    with open("frontend/public/scanner-data.json","w") as f: json.dump(payload,f,indent=2)
    alert(a,b)
    print(f"Scanner complete: A={len(a)} B={len(b)}")

if __name__=="__main__": main()
