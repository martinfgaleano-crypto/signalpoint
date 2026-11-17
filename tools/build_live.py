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
    rows = sorted({r["vigenciadesde"][:10]: float(r["valor"]) for r in csv.DictReader(open(p))}.items())
    out = []
    for d, v in rows:   # weekday rates always; a weekend date only when it carries a new rate (as on the board)
        if date.fromisoformat(d).weekday() < 5 or not out or out[-1][1] != v: out.append((d, v))
    return out
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
def yahoo(sym):
    p = os.path.join(D, f"yahoo_{sym}.json")
    if not os.path.exists(p): return []
    from datetime import datetime, timezone
    try:
        j = json.load(open(p))["chart"]["result"][0]
        rows = {}
        for t, c in zip(j["timestamp"], j["indicators"]["quote"][0]["close"]):
            if c is not None: rows[datetime.fromtimestamp(t, timezone.utc).date().isoformat()] = float(c)
        return sorted(rows.items())
    except Exception:
        return []
# Colombian stocks: the iShares MSCI COLCAP ETF traded on the Bolsa de Valores de Colombia (no free feed of the index itself).
SRC["colcap"] = (yahoo("ICOLCAP.CL"), 0, 0.12, {"name": "iShares MSCI COLCAP ETF (ICOLCAP) on the Bolsa de Valores de Colombia, via Yahoo Finance", "url": "https://finance.yahoo.com/quote/ICOLCAP.CL/"})
OVERRIDE = {"colcap": {"name": "Colombian stocks (MSCI Colcap ETF)", "prefix": "$", "decimals": 0, "note": "Price of one unit of the iShares MSCI COLCAP ETF, in pesos. It follows the MSCI Colcap index; it is not the index level.",
                        "es": {"name": "Acciones colombianas (ETF del MSCI Colcap)", "note": "Precio de una unidad del ETF iShares MSCI COLCAP, en pesos. Sigue al índice MSCI Colcap; no es el nivel del índice."}}}
today = date.today(); out = {"asOf": today.isoformat(), "markets": {}, "skipped": {}}
for k, (ser, dec, maxjump, src) in SRC.items():
    ser = ser[-N:]
    if len(ser) < 5: out["skipped"][k] = "too short"; continue
    if (today - date.fromisoformat(ser[-1][0])).days > 12: out["skipped"][k] = "stale"; continue
    jumps = [abs(ser[i][1] / ser[i - 1][1] - 1) for i in range(1, len(ser)) if ser[i - 1][1]]
    if k in ("us2y", "us10y", "us30y"): jumps = [abs(ser[i][1] - ser[i - 1][1]) for i in range(1, len(ser))]
    if max(jumps) > maxjump: out["skipped"][k] = "implausible jump"; continue
    out["markets"][k] = dict({"series": [[d, round(v, dec) if dec else round(v)] for d, v in ser], "source": src}, **OVERRIDE.get(k, {}))
json.dump(out, open(os.path.join(D, "markets-live.json"), "w"), indent=1)
print("live:", sorted(out["markets"]), "skipped:", out["skipped"])
