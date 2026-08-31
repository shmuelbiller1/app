import json, math, os, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "public"
OUT.mkdir(exist_ok=True)

EXCLUDED = {"Technology", "Biotechnology", "Software", "Semiconductors", "Internet"}


def rsi(s, n=14):
    d=s.diff(); up=d.clip(lower=0); down=-d.clip(upper=0)
    rs=up.ewm(alpha=1/n, adjust=False).mean() / down.ewm(alpha=1/n, adjust=False).mean().replace(0,np.nan)
    return 100-(100/(1+rs))


def metrics(df):
    c=df["Close"].astype(float); v=df["Volume"].astype(float)
    sma20=c.rolling(20).mean(); sd20=c.rolling(20).std()
    z=(c.iloc[-1]-sma20.iloc[-1])/sd20.iloc[-1] if sd20.iloc[-1] else 0
    r=float(rsi(c).iloc[-1]); hi=float(c.tail(252).max()); px=float(c.iloc[-1])
    dist=(hi-px)/hi if hi else 1
    rv=float(v.iloc[-1]/v.tail(20).mean()) if v.tail(20).mean() else 0
    mom5=float(c.iloc[-1]/c.iloc[-6]-1) if len(c)>6 else 0
    bb=(px-(sma20.iloc[-1]+2*sd20.iloc[-1]))/(2*sd20.iloc[-1]) if sd20.iloc[-1] else 0
    return {"price":round(px,4),"z20":round(float(z),3),"rsi14":round(r,2),"distance_52w":round(dist*100,2),"relative_volume":round(rv,2),"momentum_5d":round(mom5*100,2),"bb_excursion":round(float(bb),3)}


def historical_probability(df, threshold_z=2.0, horizon=5):
    c=df["Close"].astype(float); sma=c.rolling(20).mean(); sd=c.rolling(20).std(); z=(c-sma)/sd
    hits=[]
    for i in range(20, len(c)-horizon):
        if np.isfinite(z.iloc[i]) and z.iloc[i] >= threshold_z:
            hits.append(float(c.iloc[i+horizon]/c.iloc[i]-1))
    if not hits: return None, 0
    return round(sum(x<0 for x in hits)/len(hits)*100,1), len(hits)


def reversal_score(m, prob):
    z=max(0,min(3,m["z20"])) / 3 * 35
    near=(1-min(1,max(0,m["distance_52w"])/10))*20
    r=max(0,min(1,(m["rsi14"]-55)/25))*15
    rv=max(0,min(1,(m["relative_volume"]-1)/3))*10
    p=(prob or 50)/100*20
    return round(z+near+r+rv+p,1)


def scan_etfs():
    universe=json.loads((ROOT/"leveraged_etfs.json").read_text())
    out=[]
    for item in universe:
        s=item["symbol"]
        try:
            df=yf.download(s, period="2y", interval="1d", auto_adjust=False, progress=False)
            if df.empty: continue
            if isinstance(df.columns,pd.MultiIndex): df=df.xs(s,axis=1,level=1)
            df=df.dropna(subset=["Close","Volume"])
            if len(df)<260: continue
            m=metrics(df); prob,n=historical_probability(df)
            # Candidate gate: near high or statistically extended, plus meaningful liquidity.
            if m["distance_52w"] <= 8 or m["z20"] >= 1.75:
                score=reversal_score(m,prob)
                out.append({**item,**m,"downside_probability_5d":prob,"historical_samples":n,"reversal_score":score,"options_check":"pending"})
        except Exception as e:
            print("ETF",s,e)
    return sorted(out,key=lambda x:x["reversal_score"],reverse=True)


def scan_squeeze():
    # FINRA file adapter. Set FINRA_SHORT_INTEREST_CSV to a downloaded/current FINRA file.
    path=os.getenv("FINRA_SHORT_INTEREST_CSV")
    if not path or not Path(path).exists(): return []
    si=pd.read_csv(path)
    cols={c.lower().replace(" ","_"):c for c in si.columns}
    def col(*names):
        for n in names:
            if n in cols:return cols[n]
        return None
    tc=col("symbol","ticker","issue_symbol"); sic=col("short_interest","current_short_position","current_short_interest"); dc=col("days_to_cover","days_to_cover_ratio"); fl=col("float","public_float")
    if not tc or not sic:return []
    out=[]
    for _,row in si.iterrows():
        s=str(row[tc]).strip().upper()
        try:
            short=float(row[sic]); days=float(row[dc]) if dc else np.nan; flt=float(row[fl]) if fl else np.nan
            if short<=0: continue
            df=yf.download(s,period="6mo",interval="1d",auto_adjust=False,progress=False)
            if df.empty:continue
            if isinstance(df.columns,pd.MultiIndex):df=df.xs(s,axis=1,level=1)
            df=df.dropna(subset=["Close","Volume"])
            if len(df)<30:continue
            m=metrics(df)
            # short interest is usually shares; if float is available derive short-float %. Otherwise omit.
            sf=short/flt*100 if flt and flt>0 else None
            squeeze=0
            if sf is not None:squeeze += min(40,max(0,sf))*0.8
            if np.isfinite(days):squeeze += min(25,max(0,days))*1.0
            squeeze += min(20,max(0,m["relative_volume"]-1)*8)
            squeeze += min(15,max(0,m["momentum_5d"]))*0.5
            if m["relative_volume"]>=2 and m["momentum_5d"]>3:
                out.append({"ticker":s,"short_interest":short,"short_float_pct":round(sf,2) if sf else None,"days_to_cover":round(days,2) if np.isfinite(days) else None,**m,"squeeze_score":round(squeeze,1),"options_check":"pending"})
        except Exception as e: print("SQ",s,e)
    return sorted(out,key=lambda x:x["squeeze_score"],reverse=True)


def main():
    result={"generated_at":datetime.now(timezone.utc).isoformat(),"status":"live_scan","scanner_a":scan_etfs(),"scanner_b":scan_squeeze(),"notes":["Prices/volume are pulled at run time.","FINRA short-interest candidates require FINRA_SHORT_INTEREST_CSV.","Options validation is intentionally a separate finalist stage.","Scores are research signals, not guarantees or trade instructions."]}
    (OUT/"scanner-data.json").write_text(json.dumps(result,indent=2))
    print(json.dumps({"A":len(result["scanner_a"]),"B":len(result["scanner_b"])}))

if __name__=="__main__":main()
