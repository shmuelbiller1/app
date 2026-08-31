"""Quant Scanner research engine.

Scanner A: leveraged/inverse ETF overextension + historical downside frequency.
Scanner B: optional FINRA CSV short-interest data + Finnhub price/volume momentum.
Options are finalist-only so API usage stays small.
"""
import json, math, os, time
from datetime import datetime, timezone
import requests
import pandas as pd

FINNHUB = "https://finnhub.io/api/v1"
EXCLUDED = {"Technology", "Biotechnology", "Software", "Semiconductors"}
# Starter universe; replace/extend with your maintained issuer-derived universe.
LEVERAGED = ["YANG","YINN","NUGT","DUST","ERX","ERY","FAS","FAZ","LABU","LABD","UCO","SCO","BOIL","KOLD","GUSH","DRIP","TNA","TZA","SOXL","SOXS","TMF","TMV"]

session = requests.Session()
session.headers.update({"User-Agent":"QuantScanner/1.0 research"})

def fh(endpoint, params):
    key=os.getenv("FINNHUB_API_KEY")
    if not key: return {}
    p=dict(params); p["token"]=key
    r=session.get(f"{FINNHUB}/{endpoint}", params=p, timeout=20)
    r.raise_for_status(); return r.json()

def candles(symbol, days=400):
    end=int(time.time()); start=end-days*86400
    d=fh("stock/candle", {"symbol":symbol,"resolution":"D","from":start,"to":end})
    if d.get("s") not in ("ok", None) or not d.get("c"): return None
    return pd.DataFrame({"date":pd.to_datetime(d["t"],unit="s",utc=True),"close":d["c"],"volume":d.get("v",[0]*len(d["c"]))})

def profile_ok(symbol):
    p=fh("stock/profile2", {"symbol":symbol})
    industry=p.get("finnhubIndustry","Unknown")
    return industry not in EXCLUDED, industry

def features(df):
    c=df.close
    sma20=c.rolling(20).mean(); sd20=c.rolling(20).std()
    z=float((c.iloc[-1]-sma20.iloc[-1])/sd20.iloc[-1]) if sd20.iloc[-1] else 0
    hi=float(c.tail(252).max()); px=float(c.iloc[-1])
    dist=max(0,(hi-px)/hi*100) if hi else 0
    rsi_delta=c.diff(); gain=rsi_delta.clip(lower=0).rolling(14).mean(); loss=(-rsi_delta.clip(upper=0)).rolling(14).mean()
    rs=gain.iloc[-1]/loss.iloc[-1] if loss.iloc[-1] else 99
    rsi=100-(100/(1+rs))
    relvol=float(df.volume.iloc[-1]/df.volume.tail(20).mean()) if df.volume.tail(20).mean() else 0
    return z,dist,rsi,relvol

def downside_probability(df, z_now, horizon=5):
    c=df.close; sma=c.rolling(20).mean(); sd=c.rolling(20).std()
    z=(c-sma)/sd
    valid=z.notna()
    # Use a neighborhood around today's z-state, not future information.
    matches=(z[valid] >= z_now-0.35) & (z[valid] <= z_now+0.35)
    idx=list(z[valid][matches].index)
    outcomes=[]
    for i in idx:
        pos=df.index.get_loc(i)
        if pos+horizon < len(df):
            outcomes.append((c.iloc[pos+horizon]/c.iloc[pos]-1)<0)
    if len(outcomes)<10: return None, len(outcomes)
    return sum(outcomes)/len(outcomes), len(outcomes)

def scanner_a():
    out=[]
    for symbol in LEVERAGED:
        try:
            ok,industry=profile_ok(symbol)
            if not ok: continue
            df=candles(symbol)
            if df is None or len(df)<80: continue
            z,dist,rsi,relvol=features(df)
            prob,n=downside_probability(df,z)
            if prob is None: prob=0.5
            # Components are normalized to a transparent 0-100 score.
            z_component=min(max(z/3.0,0),1)*40
            high_component=max(0,min(1,1-dist/10))*25
            rsi_component=max(0,min(1,(rsi-55)/25))*15
            volume_component=max(0,min(1,(relvol-1)/3))*5
            score=z_component+high_component+rsi_component+volume_component+prob*15
            if score>=55:
                out.append({"ticker":symbol,"score":round(score,1),"probability":round(prob,4),"z_score":round(z,2),"high_distance":round(dist,2),"rsi":round(rsi,1),"relative_volume":round(relvol,2),"liquidity":"HIGH" if df.volume.tail(20).mean()>100000 else "MED","options":None,"sample_size":n,"industry":industry})
        except Exception as e: print("A",symbol,e)
    return sorted(out,key=lambda x:x["score"],reverse=True)[:20]

def load_finra():
    path=os.getenv("FINRA_SHORT_CSV","data/finra_short_interest.csv")
    if not os.path.exists(path): return pd.DataFrame()
    return pd.read_csv(path)

def scanner_b():
    finra=load_finra()
    if finra.empty: return []
    required={"ticker","short_float","days_to_cover"}
    if not required.issubset(finra.columns): return []
    out=[]
    for _,row in finra.iterrows():
        symbol=str(row.ticker).upper().strip()
        try:
            ok,industry=profile_ok(symbol)
            if not ok: continue
            df=candles(symbol,90)
            if df is None or len(df)<25: continue
            px=float(df.close.iloc[-1]); prev=float(df.close.iloc[-2]); price_change=(px/prev-1)*100
            avg=float(df.volume.tail(20).mean()); relvol=float(df.volume.iloc[-1]/avg) if avg else 0
            # Momentum gates keep high-SI names from becoming automatic squeeze calls.
            if price_change<3 or relvol<1.5: continue
            sf=float(row.short_float); dtc=float(row.days_to_cover)
            si_change=float(row.si_change_pct) if "si_change_pct" in row and pd.notna(row.si_change_pct) else 0
            raw=.32*min(sf/30,1)+.23*min(dtc/10,1)+.20*min(max(si_change,0)/50,1)+.15*min(relvol/5,1)+.10*min(max(price_change,0)/15,1)
            out.append({"ticker":symbol,"score":round(raw*100,1),"short_float":round(sf,2),"days_to_cover":round(dtc,2),"rel_volume":round(relvol,2),"price_change":round(price_change,2),"si_change_pct":round(si_change,2),"options":None,"industry":industry})
        except Exception as e: print("B",symbol,e)
    return sorted(out,key=lambda x:x["score"],reverse=True)[:20]

def options_check(candidates):
    # Alpha Vantage is intentionally optional. We only ask about the finalists.
    key=os.getenv("ALPHA_VANTAGE_API_KEY")
    if not key: return candidates
    for x in candidates[:20]:
        try:
            r=session.get("https://www.alphavantage.co/query",params={"function":"HISTORICAL_OPTIONS","symbol":x["ticker"],"apikey":key},timeout=20).json()
            rows=r.get("data",[])
            oi=sum(int(float(i.get("open_interest",0) or 0)) for i in rows[:50])
            x["options"]=oi>=500
            x["options_open_interest"]=oi
        except Exception as e: print("options",x["ticker"],e)
    return candidates

def alert(a,b):
    url=os.getenv("DISCORD_WEBHOOK_URL")
    if not url: return
    high_a=[x for x in a if x["score"]>=85]; high_b=[x for x in b if x["score"]>=85]
    if not high_a and not high_b: return
    lines=["**Quant Scanner — high-score alert**"]
    if high_a: lines.append("**A / Leveraged Reversal:** " + ", ".join(f'{x["ticker"]} {x["score"]:.1f}' for x in high_a[:8]))
    if high_b: lines.append("**B / Short Squeeze:** " + ", ".join(f'{x["ticker"]} {x["score"]:.1f}' for x in high_b[:8]))
    lines.append("Research signal only — no auto-trading.")
    session.post(url,json={"content":"\n".join(lines)},timeout=15).raise_for_status()

def main():
    a=options_check(scanner_a()); b=options_check(scanner_b())
    payload={"generated_at":datetime.now(timezone.utc).isoformat(),"market_status":"SCANNED","scanner_a":a,"scanner_b":b,"alerts_enabled":bool(os.getenv("DISCORD_WEBHOOK_URL"))}
    os.makedirs("frontend/public",exist_ok=True)
    with open("frontend/public/scanner-data.json","w") as f: json.dump(payload,f,indent=2)
    alert(a,b)
    print(f"Scanner complete: A={len(a)} B={len(b)}")

if __name__=="__main__": main()
