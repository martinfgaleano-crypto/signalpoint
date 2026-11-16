"""SignalPoint event studies: what happened the other times. Pure statistics on public daily series."""
import csv, json, statistics as st, sys
from datetime import date, timedelta
def d(s): return date.fromisoformat(s[:10])
def fred(path):
    out=[]
    for r in csv.DictReader(open(path)):
        k=[c for c in r if c!='observation_date'][0]
        if r[k] not in ('','.'): out.append((d(r['observation_date']),float(r[k])))
    return out
def yahoo(path):
    j=json.load(open(path))['chart']['result'][0]
    ts=j['timestamp'];cl=j['indicators']['quote'][0]['close']
    from datetime import datetime,timezone
    out={}
    for t,c in zip(ts,cl):
        if c is not None: out[datetime.fromtimestamp(t,timezone.utc).date()]=c
    return sorted(out.items())
def prevwd(x):
    x-=timedelta(days=1)
    while x.weekday()>4: x-=timedelta(days=1)
    return x
def trm():
    # The TRM in force on day D is computed from trading on the previous business day: re-date it to that market day.
    raw={d(r['vigenciadesde']):float(r['valor']) for r in csv.DictReader(open('trm.csv'))}
    return sorted((prevwd(k),v) for k,v in raw.items() if k.weekday()<5)
def bis():
    rows=[(d(r['TIME_PERIOD']),float(r['OBS_VALUE'])) for r in csv.DictReader(open('bis_cbpol_CO.csv')) if r['OBS_VALUE'] not in ('','NaN')]
    return sorted(rows)
START=date(2000,1,1)
A={ # reaction series
 "usdcop":("Dólar en pesos (TRM)","Dollar in pesos (TRM)",trm()),
 "colo":("Acciones colombianas (ETF COLO, en USD)","Colombian stocks (COLO ETF, USD)",yahoo('yahoo_COLO.json')),
 "ec":("Ecopetrol (ADR)","Ecopetrol (ADR)",yahoo('yahoo_EC.json')),
 "sp500":("S&P 500","S&P 500",yahoo('yahoo_GSPC.json')),
 "brent":("Petróleo Brent","Brent crude",fred('fred_DCOILBRENTEU.csv')),
}
def changes(series):  # day-over-day % changes keyed by date
    return [(series[i][0],(series[i][1]/series[i-1][1]-1)*100) for i in range(1,len(series)) if series[i-1][1]]
def steps(series):  # dates when a rate level changes, with delta
    return [(series[i][0],round(series[i][1]-series[i-1][1],4)) for i in range(1,len(series)) if abs(series[i][1]-series[i-1][1])>1e-9]
def cluster(evs,gap=10):  # keep first event of a cluster (avoid counting the same episode many times)
    out=[];last=None
    for e in evs:
        if last is None or (e[0]-last).days>gap: out.append(e)
        last=e[0]
    return out
fed=steps(fred('fred_DFEDTAR.csv'))+steps(fred('fred_DFEDTARU.csv'))
fed=[e for e in fed if e[0]>=START and not (e[0]==date(2008,12,16))]  # target -> range switch
br=[e for e in steps(bis()) if e[0]>=START]
trmc=[e for e in changes(trm()) if e[0]>=START]
brc=[e for e in changes(fred('fred_DCOILBRENTEU.csv')) if e[0]>=START]
coloc=[e for e in changes(yahoo('yahoo_COLO.json')) if e[0]>=START]
dgs2=dict(fred('fred_DGS2.csv'));dgs10=fred('fred_DGS10.csv')
def ychg(series,dd):  # change in a yield (pp) on market day dd vs previous obs
    ks=sorted(series)
    for i,k in enumerate(ks):
        if k>=dd: return None if i==0 or k!=dd else series[k]-series[ks[i-1]]
    return None
def nextbd(x):
    x+=timedelta(days=1)
    while x.weekday()>4: x+=timedelta(days=1)
    return x
def prevbd(x):
    x-=timedelta(days=1)
    while x.weekday()>4: x-=timedelta(days=1)
    return x
fed_surp=[]
for e in fed:
    dd=prevbd(e[0]); c=ychg(dgs2,dd)
    if c is not None: fed_surp.append((e[0],e[1],c))
def turns(st_):
    out=[]
    for i in range(1,len(st_)):
        if (st_[i][1]>0)!=(st_[i-1][1]>0): out.append(st_[i])
    return out
brt=turns(br)
y10=[(dgs10[i][0],dgs10[i][1]-dgs10[i-1][1]) for i in range(1,len(dgs10)) if dgs10[i][0]>=START]
# All scheduled (and emergency) FOMC decisions, including holds. Surprise proxy: 2-year Treasury yield change on decision day.
fomc=[date.fromisoformat(x) for x in json.load(open('fomc_dates.json')) if x>='2000']
def sgn(x): return 1 if x>0 else -1 if x<0 else 0
fed_all=[]
for dd in fomc:
    c=ychg(dgs2,dd)
    if c is not None: fed_all.append((dd,c))
EV={
 "fed_hike":("La Fed sube su tasa","The Fed raises rates",[e for e in fed if e[1]>0]),
 "fed_cut":("La Fed baja su tasa","The Fed cuts rates",[e for e in fed if e[1]<0]),
 "banrep_hike":("El Banco de la República sube su tasa","Banco de la República raises its rate",[e for e in br if e[1]>0]),
 "banrep_cut":("El Banco de la República baja su tasa","Banco de la República cuts its rate",[e for e in br if e[1]<0]),
 "trm_up":("El dólar sube 1,5% o más en un día frente al peso","The dollar jumps 1.5% or more against the peso in a day",cluster([e for e in trmc if e[1]>=1.5])),
 "trm_down":("El dólar cae 1,5% o más en un día frente al peso","The dollar drops 1.5% or more against the peso in a day",cluster([e for e in trmc if e[1]<=-1.5])),
 "brent_up":("El Brent sube 2,5% o más en un día","Brent rises 2.5% or more in a day",cluster([e for e in brc if e[1]>=2.5])),
 "fed_hawk":("Decisión de la Fed más dura de lo esperado (el bono a 2 años sube 0,07 puntos o más ese día)","Fed decision more hawkish than expected (2-year yield up 0.07 points or more that day)",[(nextbd(d0),c) for d0,c in fed_all if c>=0.07]),
 "fed_dove":("Decisión de la Fed más suave de lo esperado (el bono a 2 años cae 0,07 puntos o más ese día)","Fed decision more dovish than expected (2-year yield down 0.07 points or more that day)",[(nextbd(d0),c) for d0,c in fed_all if c<=-0.07]),
 "fed_meeting":("Reunión de la Fed, cualquiera que sea la decisión","Any Fed meeting, whatever the decision",[(nextbd(d0),c) for d0,c in fed_all]),
 "banrep_turn_hike":("El Banco de la República vuelve a subir después de un ciclo de bajadas","Banco de la República hikes again after a cutting cycle",[e for e in brt if e[1]>0]),
 "banrep_turn_cut":("El Banco de la República empieza a bajar después de un ciclo de subidas","Banco de la República starts cutting after a hiking cycle",[e for e in brt if e[1]<0]),
 "us10y_jump":("El bono del Tesoro a 10 años sube 0,12 puntos o más en un día","The 10-year Treasury yield rises 0.12 points or more in a day",cluster([e for e in y10 if e[1]>=0.12])),
 "colo_jump":("Las acciones colombianas suben 3% o más en un día","Colombian stocks jump 3% or more in a day",cluster([e for e in coloc if e[1]>=3])),
}
H=[1,5,20]
def reaction(series,evdate,h,kind):
    idx=next((i for i,(dd,_) in enumerate(series) if dd>=evdate),None)
    if idx is None: return None
    if kind=="decision":   # evdate = effective date; decision announced the business day before. Base: close before the decision day.
        b0=idx-2; t0=idx-1
    else:                  # shock: base is the close of the shock day; we measure what came after.
        if series[idx][0]!=evdate: return None
        b0=idx; t0=idx+1
    if b0<0 or t0+h-1>=len(series): return None
    return (series[t0+h-1][1]/series[b0][1]-1)*100
def baseline(ser,h):
    s2=[x for x in ser if x[0]>=START]
    xs=[(s2[i+h][1]/s2[i][1]-1)*100 for i in range(len(s2)-h)]
    return {"up":round(sum(1 for x in xs if x>0)/len(xs)*100),"med":round(st.median(xs),2)}
res={"baseline":{ak:{str(h):baseline(ser,h) for h in H} for ak,(_,_,ser) in A.items()},"note":"Event studies on public daily series (FRED, BIS, Superfinanciera TRM via datos.gov.co, Yahoo Finance). Base: last close before the event day. Horizons in trading days of each series. Past behaviour, not a forecast.","asOf":str(max(s[-1][0] for _,_,s in A.values())),"events":{}}
for k,(es,en,evs) in EV.items():
    blk={"es":es,"en":en,"n":len(evs),"first":str(evs[0][0]) if evs else None,"last":str(evs[-1][0]) if evs else None,"dates":[str(e[0]) for e in evs][-40:],"assets":{}}
    for ak,(aes,aen,ser) in A.items():
        if (k=="brent_up" and ak=="brent") or (k=="trm_up" and ak=="usdcop" ) or (k=="trm_down" and ak=="usdcop") or (k=="colo_jump" and ak=="colo"):
            pass  # keep: shows follow-through after the shock day
        out={}
        for h in H:
            xs=[r for r in (reaction(ser,e[0],h,'decision' if k.startswith(('fed','banrep')) else 'shock') for e in evs) if r is not None]
            if len(xs)<5: continue
            xs.sort()
            q=st.quantiles(xs,n=4) if len(xs)>=4 else [xs[0],st.median(xs),xs[-1]]
            out[str(h)]={"n":len(xs),"up":sum(1 for x in xs if x>0),"med":round(st.median(xs),2),"p25":round(q[0],2),"p75":round(q[2],2)}
        if out: blk["assets"][ak]={"es":aes,"en":aen,"h":out}
    for ak,a in blk["assets"].items():
        for h,v in a["h"].items():
            p=res["baseline"][ak][h]["up"]/100;n=v["n"];z=(v["up"]-n*p)/((n*p*(1-p))**0.5) if 0<p<1 else 0
            v["base"]=res["baseline"][ak][h]["up"];v["sig"]=abs(z)>=1.96
    res["events"][k]=blk
json.dump(res,open('history.json','w'),ensure_ascii=False,indent=1)
for k,b in res["events"].items():
    print(f"\n{b['es']}  n={b['n']}  ({b['first']} → {b['last']})")
    for ak,a in b["assets"].items():
        print("  ",a["es"][:34].ljust(34)," | ".join(f"t+{h}: {v['up']}/{v['n']} ({round(v['up']/v['n']*100)}% vs {res['baseline'][ak][h]['up']}%), med {v['med']:+.2f}%" for h,v in a["h"].items()))
