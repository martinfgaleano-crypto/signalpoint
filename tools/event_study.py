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
# Multiple testing: many event x market x horizon tests. Control the false discovery rate (Benjamini-Hochberg, q=0.05).
import math
def pval(z): return math.erfc(abs(z)/math.sqrt(2))
tests=[]
for k,b in res["events"].items():
    for ak,a in b["assets"].items():
        for h,v in a["h"].items():
            p=v["base"]/100;n=v["n"];z=(v["up"]-n*p)/math.sqrt(n*p*(1-p)) if 0<p<1 else 0
            v["p"]=pval(z);tests.append(v)
tests.sort(key=lambda v:v["p"]);m=len(tests);cut=0
for i,v in enumerate(tests,1):
    if v["p"]<=0.10*i/m: cut=i
for i,v in enumerate(tests,1):
    v["sig"]=i<=cut and v["n"]>=10; v["hint"]=(not v["sig"]) and v["p"]<0.05 and v["n"]>=10; v["p"]=round(v["p"],4)
res["tests"]=m;res["discoveries"]=sum(1 for v in tests if v["sig"]);res["hints"]=sum(1 for v in tests if v["hint"])
# Similar days: describe each market day by its recent context and find the closest past days (k-nearest neighbours).
def asof_map(series):
    return dict(series)
def ret(series,i,n): return (series[i][1]/series[i-n][1]-1)*100 if i-n>=0 and series[i-n][1] else None
spx=A["sp500"][2];trs=A["usdcop"][2];brs=A["brent"][2];cos=A["colo"][2];brl=bis()
d2=sorted(dgs2.items());d10=dgs10
def idx_on(series,dd):
    lo,hi=0,len(series)-1;best=None
    while lo<=hi:
        mid=(lo+hi)//2
        if series[mid][0]<=dd: best=mid;lo=mid+1
        else: hi=mid-1
    return best
def feats(dd):
    out=[]
    for ser,n in ((trs,20),(trs,5),(spx,20),(brs,20)):
        i=idx_on(ser,dd)
        if i is None: return None
        r=ret(ser,i,n)
        if r is None: return None
        out.append(r)
    i=idx_on(spx,dd)
    if i is None or i<21: return None
    rs=[(spx[j][1]/spx[j-1][1]-1)*100 for j in range(i-19,i+1)];out.append(st.pstdev(rs)*math.sqrt(252))
    i=idx_on(d2,dd)
    if i is None or i<60: return None
    out.append(d2[i][1]-d2[i-60][1])
    i=idx_on(d10,dd)
    if i is None or i<20: return None
    out.append(d10[i][1]-d10[i-20][1])
    i=idx_on(cos,dd)
    if i is None: return None
    r=ret(cos,i,20)
    if r is None: return None
    out.append(r)
    i=idx_on(brl,dd)
    if i is None: return None
    j=idx_on(brl,dd-timedelta(days=91))
    if j is None: return None
    out.append(brl[i][1]-brl[j][1])
    return out
FN=[("Dólar en pesos, últimas 4 semanas","Dollar in pesos, last 4 weeks","%"),("Dólar en pesos, última semana","Dollar in pesos, last week","%"),("S&P 500, últimas 4 semanas","S&P 500, last 4 weeks","%"),("Brent, últimas 4 semanas","Brent, last 4 weeks","%"),("Volatilidad del S&P 500 (anualizada)","S&P 500 volatility (annualised)","%"),("Bono a 2 años de EE. UU., últimos 3 meses","US 2-year yield, last 3 months","pts"),("Bono a 10 años de EE. UU., últimas 4 semanas","US 10-year yield, last 4 weeks","pts"),("Acciones colombianas (COLO), últimas 4 semanas","Colombian stocks (COLO), last 4 weeks","%"),("Tasa del Banco de la República, últimos 3 meses","Banco de la República rate, last 3 months","pts")]
days=[x[0] for x in spx if x[0]>=date(2001,1,1)]
rows=[(dd,feats(dd)) for dd in days]; rows=[(dd,f) for dd,f in rows if f]
today_d,today_f=rows[-1]
mu=[st.mean(f[j] for _,f in rows) for j in range(len(FN))];sd=[st.pstdev(f[j] for _,f in rows) or 1 for j in range(len(FN))]
zf=lambda f:[(f[j]-mu[j])/sd[j] for j in range(len(FN))]
tz=zf(today_f)
cands=sorted(((sum((a-b)**2 for a,b in zip(zf(f),tz))**0.5,dd) for dd,f in rows if (today_d-dd).days>90))
K=20;pick=[]
for dist,dd in cands:
    if all(abs((dd-p).days)>=20 for _,p in pick): pick.append((dist,dd))
    if len(pick)>=K: break
sim={"date":str(today_d),"k":len(pick),"features":[{"es":FN[j][0],"en":FN[j][1],"unit":FN[j][2],"today":round(today_f[j],2),"typical":round(mu[j],2)} for j in range(len(FN))],"days":[str(dd) for _,dd in sorted(pick,key=lambda x:x[1])],"assets":{}}
for ak,(aes,aen,ser) in A.items():
    out={}
    for h in [5,20,60]:
        xs=[]
        for _,dd in pick:
            i=idx_on(ser,dd)
            if i is not None and i+h<len(ser): xs.append((ser[i+h][1]/ser[i][1]-1)*100)
        if len(xs)<10: continue
        bl=baseline(ser,h) if str(h) not in res["baseline"].get(ak,{}) else res["baseline"][ak][str(h)]
        p=bl["up"]/100;n=len(xs);up=sum(1 for x in xs if x>0);z=(up-n*p)/math.sqrt(n*p*(1-p))
        out[str(h)]={"n":n,"up":up,"med":round(st.median(xs),2),"base":bl["up"],"sig":abs(z)>=1.96}
    if out: sim["assets"][ak]={"es":aes,"en":aen,"h":out}
# Out-of-sample check (walk-forward): for test days since 2008, neighbours come only from days at least 90 days earlier,
# and the baseline is the up-share known before that day. Brier score: lower is better; skill > 0 means the method beats the baseline.
def knn_val(ak,ser,h=20,step=10,k=20):
    rr=[(dd,zf(f)) for dd,f in rows]; out=[]
    for t in range(0,len(rr),step):
        dd,tzz=rr[t]
        if dd<date(2008,1,1): continue
        i0=idx_on(ser,dd)
        if i0 is None or i0+h>=len(ser) or ser[i0][0]>dd: continue
        real=1 if ser[i0+h][1]>ser[i0][1] else 0
        past=[(sum((a-b)**2 for a,b in zip(z,tzz)),d2_) for d2_,z in rr if (dd-d2_).days>90]
        past.sort();pk=[];
        for _,d2_ in past:
            if all(abs((d2_-q).days)>=20 for q in pk): pk.append(d2_)
            if len(pk)>=k: break
        ups=[];
        for d2_ in pk:
            j=idx_on(ser,d2_)
            if j is not None and j+h<len(ser) and ser[j+h][0]<dd: ups.append(1 if ser[j+h][1]>ser[j][1] else 0)
        if len(ups)<10: continue
        pre=[x for x in ser if x[0]<dd and x[0]>=START]
        if len(pre)<300: continue
        base=sum(1 for q in range(len(pre)-h) if pre[q+h][1]>pre[q][1])/(len(pre)-h)
        pk_=sum(ups)/len(ups); out.append((pk_,base,real))
    if len(out)<30: return None
    bk=sum((p-r)**2 for p,_,r in out)/len(out); bb=sum((b-r)**2 for _,b,r in out)/len(out)
    return {"tests":len(out),"brier_knn":round(bk,4),"brier_base":round(bb,4),"skill":round(1-bk/bb,3),"hit_knn":round(sum(1 for p,_,r in out if (p>0.5)==(r==1))/len(out)*100),"hit_base":round(sum(1 for _,b,r in out if (b>0.5)==(r==1))/len(out)*100)}
sim["validation"]={}
for ak,(aes,aen,ser) in A.items():
    try:
        v=knn_val(ak,ser)
        if v: sim["validation"][ak]=v
    except Exception as e: print("validation failed",ak,repr(e)[:80])
res["similar"]=sim
json.dump(res,open('history.json','w'),ensure_ascii=False,indent=1)
print('validation',json.dumps(sim.get('validation')))
for k,b in res["events"].items():
    print(f"\n{b['es']}  n={b['n']}  ({b['first']} → {b['last']})")
    for ak,a in b["assets"].items():
        print("  ",a["es"][:34].ljust(34)," | ".join(f"t+{h}: {v['up']}/{v['n']} ({round(v['up']/v['n']*100)}% vs {res['baseline'][ak][h]['up']}%), med {v['med']:+.2f}%" for h,v in a["h"].items()))
