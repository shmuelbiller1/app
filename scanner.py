"""Quant Scanner live research engine.

Scanner A: leveraged/inverse ETF overextension/reversal.
Scanner B: short-interest squeeze candidates.
Signal Laboratory: every emitted candidate is recorded as a time-stamped
research event and later joined to realized +1/+3/+5/+10/+20 session outcomes.

Research-first rules:
- no fake probabilities when historical samples are sparse;
- signal features use only information available at signal time;
- FINRA short interest and Reg SHO are separate evidence;
- options are finalist-only and missing options data stays explicit;
- headline score is not presented as a calibrated probability.
"""
import json, os, time
from datetime import datetime, timezone
import requests
import pandas as pd
import numpy as np
import yfinance as yf

from scanner.research_stats import bootstrap_ci
from scanner.signal_lab import record_signals, write_lab_report

FINNHUB = "https://finnhub.io/api/v1"
EXCLUDED = {"Technology", "Biotechnology", "Software", "Semiconductors", "Internet"}
LEVERAGED = [
    "YANG","YINN","NUGT","DUST","ERX","ERY","FAS","FAZ","UCO","SCO",
    "BOIL","KOLD","GUSH","DRIP","TNA","TZA","TMF","TMV","DFEN","DUG","DIG","SAA","SDD","UDOW","SDOW"
]

session = requests.Session()
session.headers.update({"User-Agent": "QuantScanner/4.0 research"})


def fh(endpoint, params):
    key = os.getenv("FINNHUB_API_KEY")
    if not key:
        return {}
    p = dict(params); p["token"] = key
    r = session.get(f"{FINNHUB}/{endpoint}", params=p, timeout=20)
    r.raise_for_status()
    return r.json()


def candles(symbol, days=400):
    try:
        df = yf.download(symbol, period=f"{max(days,60)}d", interval="1d", auto_adjust=False, progress=False, threads=False)
        if df is None or df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns=df.columns.get_level_values(0)
        if not {"Close","Volume"}.issubset(df.columns): return None
        out=df[["Close","Volume"]].copy().rename(columns={"Close":"close","Volume":"volume"}).dropna()
        out.index=pd.to_datetime(out.index,utc=True)
        return out.reset_index(names="date")
    except Exception as e:
        print("history",symbol,e); return None


def profile_ok(symbol):
    try:
        p=fh("stock/profile2",{"symbol":symbol}); industry=p.get("finnhubIndustry","Unknown")
        if industry=="Unknown" and os.getenv("ALLOW_UNKNOWN_INDUSTRY","0")!="1": return False,industry
        return industry not in EXCLUDED,industry
    except Exception: return False,"Unknown"


def rsi(series,n=14):
    d=series.diff(); gain=d.clip(lower=0); loss=-d.clip(upper=0)
    avg_gain=gain.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    avg_loss=loss.ewm(alpha=1/n,adjust=False,min_periods=n).mean()
    rs=avg_gain/avg_loss.replace(0,np.nan)
    return 100-(100/(1+rs))


def feature_row(df):
    c,v=df.close,df.volume
    sma20=c.rolling(20).mean(); sd20=c.rolling(20).std()
    sma50=c.rolling(50).mean(); sd50=c.rolling(50).std()
    px=c.iloc[-1]
    z20=(px-sma20.iloc[-1])/sd20.iloc[-1] if sd20.iloc[-1] else np.nan
    z50=(px-sma50.iloc[-1])/sd50.iloc[-1] if sd50.iloc[-1] else np.nan
    hi=c.tail(252).max(); dist=(hi-px)/hi*100 if hi else np.nan
    rv=v.iloc[-1]/v.tail(20).mean() if v.tail(20).mean() else np.nan
    ret1=px/c.iloc[-2]-1
    ret5=px/c.iloc[-6]-1 if len(c)>=6 else np.nan
    ret20=px/c.iloc[-21]-1 if len(c)>=21 else np.nan
    atr_like=(c.diff().abs().rolling(14).mean().iloc[-1] / px) if len(c)>=15 else np.nan
    return {"price":float(px),"z_score":float(z20),"z50":float(z50),"high_distance":float(dist),
            "rsi":float(rsi(c).iloc[-1]),"relative_volume":float(rv),"return_1d":float(ret1*100),
            "return_5d":float(ret5*100) if np.isfinite(ret5) else None,"return_20d":float(ret20*100) if np.isfinite(ret20) else None,
            "atr_fraction":float(atr_like),"avg_volume_20":float(v.tail(20).mean())}


def state_signature(df, pos, horizon=5):
    c=df.close; v=df.volume
    sma=c.rolling(20).mean(); sd=c.rolling(20).std(); z=(c-sma)/sd
    rs=rsi(c)
    hi=c.rolling(252,min_periods=20).max(); dist=(hi-c)/hi
    rv=v/v.rolling(20).mean()
    if pos>=len(df): return None
    return np.array([z.iloc[pos], rs.iloc[pos], dist.iloc[pos], rv.iloc[pos]], dtype=float)


def historical_probability(df, current_signature, horizon=5, tolerances=(0.45,10.0,0.035,0.90), min_samples=20):
    c=df.close
    outcomes=[]
    current=np.asarray(current_signature,dtype=float)
    for pos in range(20, len(df)-horizon):
        sig=state_signature(df,pos)
        if sig is None or not np.all(np.isfinite(sig)): continue
        if np.all(np.abs(sig-current) <= np.asarray(tolerances)):
            outcomes.append(float(c.iloc[pos+horizon]/c.iloc[pos]-1))
    if len(outcomes)<min_samples: return None,len(outcomes),outcomes
    return float(np.mean(np.asarray(outcomes)<0)),len(outcomes),outcomes


def scanner_a():
    out=[]
    for symbol in LEVERAGED:
        try:
            ok,industry=profile_ok(symbol)
            if not ok: continue
            df=candles(symbol,420)
            if df is None or len(df)<260: continue
            f=feature_row(df)
            sig=state_signature(df,len(df)-1)
            prob,n,outcomes=historical_probability(df,sig)
            quality="INSUFFICIENT" if prob is None else ("STRONG" if n>=80 else "GOOD" if n>=40 else "LIMITED")
            extension=min(max(f["z_score"]/3.0,0),1)
            high=max(0,min(1,1-f["high_distance"]/8.0))
            rsi_factor=max(0,min(1,(f["rsi"]-55)/25.0))
            volume_factor=max(0,min(1,(f["relative_volume"]-1)/3.0))
            probability_factor=(max(0,min(1,(prob-0.5)/0.3)) if prob is not None else 0)
            score=100*(0.30*extension+0.25*high+0.15*rsi_factor+0.10*volume_factor+0.20*probability_factor)
            ci=None
            if outcomes and len(outcomes)>=20:
                binary=np.asarray([1.0 if x<0 else 0.0 for x in outcomes])
                lo,hi=bootstrap_ci(binary,np.mean,n_resamples=500,mean_block=min(7,len(binary)))
                ci=[round(float(lo),4),round(float(hi),4)]
            if score>=50:
                out.append({"ticker":symbol,"score":round(score,1),"probability":round(prob,4) if prob is not None else None,
                    "probability_ci":ci,"probability_horizon_days":5,"probability_sample":n,"data_quality":quality,
                    "price":round(f["price"],4),"z_score":round(f["z_score"],2),"z50":round(f["z50"],2),
                    "high_distance":round(f["high_distance"],2),"rsi":round(f["rsi"],1),"relative_volume":round(f["relative_volume"],2),
                    "return_1d":round(f["return_1d"],2),"return_5d":f["return_5d"],"return_20d":f["return_20d"],
                    "avg_volume_20":round(f["avg_volume_20"]),"industry":industry,"options":"NOT_CHECKED",
                    "signal_time":datetime.now(timezone.utc).isoformat()})
        except Exception as e: print("A",symbol,e)
    return sorted(out,key=lambda x:x["score"],reverse=True)[:20]


def load_finra():
    path=os.getenv("FINRA_SHORT_CSV","data/finra_short_interest.csv")
    return pd.read_csv(path) if os.path.exists(path) else pd.DataFrame()


def load_reg_sho():
    path="data/finra_reg_sho_daily.csv"
    return pd.read_csv(path) if os.path.exists(path) else pd.DataFrame()


def scanner_b():
    finra=load_finra(); reg=load_reg_sho()
    if finra.empty: return []
    required={"ticker","short_interest","days_to_cover"}
    if not required.issubset(finra.columns): return []
    reg_map={}
    if not reg.empty and {"ticker","short_volume_ratio"}.issubset(reg.columns):
        reg_map=reg.groupby("ticker")["short_volume_ratio"].mean().to_dict()
    out=[]
    for _,row in finra.iterrows():
        symbol=str(row.ticker).upper().strip()
        try:
            ok,industry=profile_ok(symbol)
            if not ok: continue
            df=candles(symbol,90)
            if df is None or len(df)<30: continue
            f=feature_row(df)
            if f["return_1d"]<3 or f["relative_volume"]<1.5: continue
            sf=float(row.short_float) if "short_float" in row and pd.notna(row.short_float) else np.nan
            dtc=float(row.days_to_cover) if pd.notna(row.days_to_cover) else np.nan
            sic=float(row.si_change_pct) if "si_change_pct" in row and pd.notna(row.si_change_pct) else 0
            sv=float(reg_map.get(symbol,np.nan))
            sf_score=min(max(sf,0)/30,1) if np.isfinite(sf) else 0
            dtc_score=min(max(dtc,0)/10,1) if np.isfinite(dtc) else 0
            change_score=min(max(sic,0)/50,1)
            vol_score=min(max(f["relative_volume"],0)/5,1)
            mom_score=min(max(f["return_1d"],0)/15,1)
            raw=.28*sf_score+.18*dtc_score+.18*change_score+.20*vol_score+.16*mom_score
            out.append({"ticker":symbol,"score":round(raw*100,1),"short_float":round(sf,2) if np.isfinite(sf) else None,
                "days_to_cover":round(dtc,2) if np.isfinite(dtc) else None,"rel_volume":round(f["relative_volume"],2),
                "price":round(f["price"],4),"price_change":round(f["return_1d"],2),"return_5d":f["return_5d"],
                "si_change_pct":round(sic,2),"reg_sho_short_volume_ratio":round(sv,4) if np.isfinite(sv) else None,
                "industry":industry,"options":"NOT_CHECKED","signal_time":datetime.now(timezone.utc).isoformat()})
        except Exception as e: print("B",symbol,e)
    return sorted(out,key=lambda x:x["score"],reverse=True)[:20]


def options_check(candidates):
    key=os.getenv("ALPHA_VANTAGE_API_KEY")
    if not key: return candidates
    for x in candidates[:10]:
        try:
            r=session.get("https://www.alphavantage.co/query",params={"function":"HISTORICAL_OPTIONS","symbol":x["ticker"],"apikey":key},timeout=20).json()
            rows=r.get("data",[])
            if not rows: x["options"]="NO_DATA"; continue
            oi=sum(int(float(i.get("open_interest",0) or 0)) for i in rows[:50]); volume=sum(int(float(i.get("volume",0) or 0)) for i in rows[:50])
            x["options_open_interest"]=oi; x["options_volume"]=volume
            x["options"]="PASS" if oi>=500 and volume>0 else "WEAK"
        except Exception: x["options"]="ERROR"
    return candidates


def alert(a,b):
    url=os.getenv("DISCORD_WEBHOOK_URL")
    if not url:return
    state_path="data/alert_state.json"; os.makedirs("data",exist_ok=True)
    try: state=json.load(open(state_path)) if os.path.exists(state_path) else {}
    except Exception: state={}
    now=time.time(); cooldown=int(os.getenv("ALERT_COOLDOWN_SECONDS","14400")); fresh=[]
    for kind,x in [("A",x) for x in a if x["score"]>=85]+[("B",x) for x in b if x["score"]>=85]:
        k=f"{kind}:{x['ticker']}"
        if now-state.get(k,0)>=cooldown: fresh.append((kind,x)); state[k]=now
    if not fresh:return
    lines=["**Quant Scanner — new high-confidence research signals**"]
    for kind,x in fresh:
        p=f" | P5d={x['probability']:.0%}" if kind=="A" and x.get("probability") is not None else ""
        lines.append(f"{kind} **{x['ticker']}** score={x['score']:.1f}{p} | RV={x.get('relative_volume',x.get('rel_volume','?'))}")
    lines.append("Research signal only — verify data/options before trading.")
    session.post(url,json={"content":"\n".join(lines)},timeout=15).raise_for_status()
    with open(state_path,"w") as f:json.dump(state,f,indent=2)


def main():
    a=options_check(scanner_a()); b=options_check(scanner_b())
    payload={"generated_at":datetime.now(timezone.utc).isoformat(),"market_status":"SCANNED","scanner_a":a,"scanner_b":b,
      "alerts_enabled":bool(os.getenv("DISCORD_WEBHOOK_URL")),
      "signal_lab":"ACTIVE",
      "methodology":{"A":"Historical analog matching on signal-time Z20/RSI/52W-distance/relative-volume; minimum 20 observations; bootstrap CI when available.",
      "B":"Short float + DTC + SI change + relative volume + price momentum; Reg SHO short-volume ratio shown separately as context.",
      "validation":"Every emitted candidate is recorded in the Signal Laboratory and joined to future +1/+3/+5/+10/+20 session outcomes.",
      "options":"Finalist-only; PASS/WEAK/NO_DATA/ERROR/NOT_CHECKED are explicit."}}
    # Record this scan before outcome backfill. The event timestamp is signal time.
    record_signals(payload)
    lab=write_lab_report()
    payload["signal_lab_summary"]={"signals":lab.get("signals",0),"cutoff":lab.get("cutoff"),"outcomes_filled_this_run":lab.get("outcomes_filled_this_run",0),
      "scanner_a":lab.get("A",{}),"scanner_b":lab.get("B",{})}
    os.makedirs("frontend/public",exist_ok=True)
    with open("frontend/public/scanner-data.json","w") as f:json.dump(payload,f,indent=2)
    print(f"Scanner complete: A={len(a)} B={len(b)} | lab signals={lab.get('signals',0)}")

if __name__=="__main__":main()
