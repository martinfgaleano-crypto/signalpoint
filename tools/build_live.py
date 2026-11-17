"""Build markets-live.json: the latest daily series for the board's markets, from the files fetch_history.py downloaded.
Only sources that match each market's named source are used. A market is left out (the site keeps its last reviewed data)
if its data is stale, too short, or has an implausible jump."""
import csv, json, sys, os
from datetime import date, timedelta
D = sys.argv[1] if len(sys.argv) > 1 else "out"
N = 12
def fred(name):
    p = os.path.join(D, f"fred_{name}.csv")
    if not os.path.exists(p): return []
    out = []
    for r in csv.DictReader(open(p)):
        k = [c for c in r if c != "observation_date"][0]
        if r[k] not in ("", "."): out.append((r["observation_date"], float(r[k])))
    return out
def trm():
    p = os.path.join(D, "trm.csv")
    if not os.path.exists(p): return []
    rows = {}
    for r in csv.DictReader(open(p)):
        d = r["vigenciadesde"][:10]
        if date.fromisoformat(d).weekday() < 5: rows[d] = float(r["valor"])
    return sorted(rows.items())
SRC = {
  "sp500": (fred("SP500"), 2, 0.12, {"name": "S&P Dow Jones Indices, via FRED (series SP500)", "url": "https://fred.stlouisfed.org/series/SP500"}),
  "nasdaq": (fred("NASDAQCOM"), 2, 0.15, {"name": "Nasdaq, Inc., via FRED (series NASDAQCOM)", "url": "https://fred.stlouisfed.org/series/NASDAQCOM"}),
  "dow": (fred("DJIA"), 2, 0.12, {"name": "S&P Dow Jones Indices, via FRED (series DJIA)", "url": "https://fred.stlouisfed.org/series/DJIA"}),
  "us2y": (fred("DGS2"), 2, 0.6, {"name": "US Treasury constant-maturity yields, via FRED (series DGS2)", "url": "https://fred.stlouisfed.org/series/DGS2"}),
  "us10y": (fred("DGS10"), 2, 0.6, {"name": "US Treasury constant-maturity yields, via FRED (series DGS10)", "url": "https://fred.stlouisfed.org/series/DGS10"}),
  "us30y": (fred("DGS30"), 2, 0.6, {"name": "US Treasury constant-maturity yields, via FRED (series DGS30)", "url": "https://fred.stlouisfed.org/series/DGS30"}),
  "eurusd": (fred("DEXUSEU"), 4, 0.05, {"name": "Federal Reserve H.10 exchange rates, via FRED (series DEXUSEU)", "url": "https://fred.stlouisfed.org/series/DEXUSEU"}),
  "usdcop": (trm(), 2, 0.06, {"name": "Superintendencia Financiera de Colombia, TRM, via datos.gov.co", "url": "https://www.datos.gov.co/Econom-a-y-Finanzas/Tasa-de-Cambio-Representativa-del-Mercado-Historic/mcec-87by"}),
  "brent": (fred("DCOILBRENTEU"), 2, 0.25, {"name": "US Energy Information Administration, Europe Brent spot price, via FRED (series DCOILBRENTEU)", "url": "https://fred.stlouisfed.org/series/DCOILBRENTEU"}),
  "btc": (fred("CBBTCUSD"), 0, 0.35, {"name": "Coinbase, via FRED (series CBBTCUSD)", "url": "https://fred.stlouisfed.org/series/CBBTCUSD"}),
}
today = date.today(); out = {"asOf": today.isoformat(), "markets": {}, "skipped": {}}
for k, (ser, dec, maxjump, src) in SRC.items():
    ser = ser[-N:]
    if len(ser) < 5: out["skipped"][k] = "too short"; continue
    if (today - date.fromisoformat(ser[-1][0])).days > 12: out["skipped"][k] = "stale"; continue
    jumps = [abs(ser[i][1] / ser[i - 1][1] - 1) for i in range(1, len(ser)) if ser[i - 1][1]]
    if k in ("us2y", "us10y", "us30y"): jumps = [abs(ser[i][1] - ser[i - 1][1]) for i in range(1, len(ser))]
    if max(jumps) > maxjump: out["skipped"][k] = "implausible jump"; continue
    out["markets"][k] = {"series": [[d, round(v, dec if dec else 2)] for d, v in ser], "source": src}
json.dump(out, open(os.path.join(D, "markets-live.json"), "w"), indent=1)
print("live:", sorted(out["markets"]), "skipped:", out["skipped"])
