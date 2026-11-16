"""Download public historical series for SignalPoint's "what happened the other times" studies.
Runs on GitHub Actions (open internet). Writes raw files + a log; never fails the job."""
import json, sys, os, time, urllib.request, urllib.parse
OUT = sys.argv[1] if len(sys.argv) > 1 else "out"
os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (SignalPoint research; github.com/martinfgaleano-crypto/signalpoint)"}
log = {}
def get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()
def save(name, url):
    try:
        b = get(url); open(os.path.join(OUT, name), "wb").write(b)
        log[name] = {"ok": True, "bytes": len(b), "url": url, "head": b[:160].decode("utf-8", "replace")}
    except Exception as e:
        log[name] = {"ok": False, "url": url, "error": repr(e)[:300]}
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="
for sid in ["DFEDTARU", "DFEDTAR", "SP500", "DCOILBRENTEU", "DEXUSAL", "DGS10", "DGS2", "DTB3", "CPIAUCSL"]:
    save(f"fred_{sid}.csv", FRED + sid)
# TRM (Superfinanciera via datos.gov.co, Socrata)
save("trm.csv", "https://www.datos.gov.co/resource/32sa-8pi3.csv?$limit=20000&$order=vigenciadesde")
if not log["trm.csv"]["ok"]:
    time.sleep(5); save("trm.csv", "https://www.datos.gov.co/api/views/32sa-8pi3/rows.csv?accessType=DOWNLOAD")
# Banco de la República pages that link to the policy-rate series (to discover the export URLs)
save("banrep_tpm_page.html", "https://www.banrep.gov.co/es/estadisticas/tasas-de-interes-de-politica-monetaria")
save("banrep_node50426.html", "https://www.banrep.gov.co/es/node/50426")
save("uba_tasas.html", "https://uba.banrep.gov.co/htmlcommons/SeriesHistoricas/tasas-interes.html")
# Yahoo daily history (long range)
now = int(time.time())
for sym in ["^GSPC", "COP=X", "COLO", "EC", "CIB", "BZ=F", "^TNX"]:
    q = urllib.parse.quote(sym)
    save(f"yahoo_{sym.replace('^','').replace('=','_')}.json", f"https://query2.finance.yahoo.com/v8/finance/chart/{q}?period1=946684800&period2={now}&interval=1d")
    time.sleep(1)
# Central bank policy rates (BIS), daily: Colombia and US
save("bis_cbpol_CO.csv", "https://stats.bis.org/api/v2/data/dataflow/BIS/WS_CBPOL/1.0/D.CO?format=csv")
if not log["bis_cbpol_CO.csv"]["ok"]:
    save("bis_cbpol_CO.csv", "https://stats.bis.org/api/v1/data/WS_CBPOL/D.CO/all?format=csv")
save("fred_COLCPIALLMINMEI.csv", FRED + "COLCPIALLMINMEI")
# Look for Banco de la República policy-rate datasets on datos.gov.co
save("catalog_banrep.json", "https://api.us.socrata.com/api/catalog/v1?domains=www.datos.gov.co&q=" + urllib.parse.quote("tasa de intervención política monetaria") + "&limit=20")
save("catalog_ipc.json", "https://api.us.socrata.com/api/catalog/v1?domains=www.datos.gov.co&q=" + urllib.parse.quote("IPC variación mensual") + "&limit=20")
json.dump(log, open(os.path.join(OUT, "log.json"), "w"), indent=1, ensure_ascii=False)
print(json.dumps({k: v.get("ok") for k, v in log.items()}))
