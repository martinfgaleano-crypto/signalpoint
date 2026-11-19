"""Build stocks-live.json: one year of daily closes for a list of US and Colombian stocks, from Yahoo Finance's public chart data.
A stock is left out if its data is missing, stale (more than 7 days old) or has an implausible one-day jump. Usage: build_stocks.py <out_dir>."""
import json, os, sys, time, urllib.request
from datetime import date, datetime, timezone
D = sys.argv[1] if len(sys.argv) > 1 else "out"
UA = {"User-Agent": "Mozilla/5.0 (SignalPoint nightly data; github.com/martinfgaleano-crypto/signalpoint)"}
# id, Yahoo symbol, name, region, currency, sector (en, es), extra words that identify the company in the news
STOCKS = [
    ("aapl", "AAPL", "Apple", "us", "USD", ("Technology", "Tecnología"), ["apple", "iphone"]),
    ("msft", "MSFT", "Microsoft", "us", "USD", ("Technology", "Tecnología"), ["microsoft"]),
    ("nvda", "NVDA", "Nvidia", "us", "USD", ("Semiconductors", "Semiconductores"), ["nvidia", "chip"]),
    ("amzn", "AMZN", "Amazon", "us", "USD", ("Retail and cloud", "Comercio y nube"), ["amazon"]),
    ("googl", "GOOGL", "Alphabet (Google)", "us", "USD", ("Technology", "Tecnología"), ["alphabet", "google"]),
    ("meta", "META", "Meta", "us", "USD", ("Technology", "Tecnología"), ["meta platforms", "facebook", "instagram"]),
    ("tsla", "TSLA", "Tesla", "us", "USD", ("Autos", "Automotriz"), ["tesla"]),
    ("jpm", "JPM", "JPMorgan Chase", "us", "USD", ("Banks", "Bancos"), ["jpmorgan"]),
    ("v", "V", "Visa", "us", "USD", ("Payments", "Pagos"), ["visa inc"]),
    ("ko", "KO", "Coca-Cola", "us", "USD", ("Consumer", "Consumo"), ["coca-cola"]),
    ("wmt", "WMT", "Walmart", "us", "USD", ("Retail", "Comercio"), ["walmart"]),
    ("nflx", "NFLX", "Netflix", "us", "USD", ("Media", "Medios"), ["netflix"]),
    ("meli", "MELI", "MercadoLibre", "us", "USD", ("E-commerce in Latin America", "Comercio electrónico en América Latina"), ["mercadolibre", "mercado libre"]),
    ("brkb", "BRK-B", "Berkshire Hathaway", "us", "USD", ("Conglomerate", "Conglomerado"), ["berkshire"]),
    ("ecopetrol", "ECOPETROL.CL", "Ecopetrol", "co", "COP", ("Oil and gas", "Petróleo y gas"), ["ecopetrol"]),
    ("cibest", "PFCIBEST.CL", "Grupo Cibest (Bancolombia)", "co", "COP", ("Banks", "Bancos"), ["cibest", "bancolombia"]),
    ("isa", "ISA.CL", "ISA", "co", "COP", ("Energy transmission", "Transmisión de energía"), ["interconexión eléctrica", " isa "]),
    ("geb", "GEB.CL", "Grupo Energía Bogotá", "co", "COP", ("Energy", "Energía"), ["grupo energía bogotá", "geb"]),
    ("grupoargos", "GRUPOARGOS.CL", "Grupo Argos", "co", "COP", ("Holding company", "Holding"), ["grupo argos"]),
    ("celsia", "CELSIA.CL", "Celsia", "co", "COP", ("Energy", "Energía"), ["celsia"]),
    ("aval", "PFAVAL.CL", "Grupo Aval", "co", "COP", ("Banks", "Bancos"), ["grupo aval", "banco de bogotá"]),
    ("ec", "EC", "Ecopetrol ADR (NYSE)", "co", "USD", ("Oil and gas", "Petróleo y gas"), ["ecopetrol"]),
]
def fetch(sym):
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(sym)}?range=1y&interval=1d"
    for _ in range(2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r: j = json.load(r)
            res = j["chart"]["result"][0]; rows = {}
            for t, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]):
                if c is not None: rows[datetime.fromtimestamp(t, timezone.utc).date().isoformat()] = float(c)
            return sorted(rows.items()), res.get("meta", {})
        except Exception as e:
            err = repr(e)[:120]; time.sleep(2)
    return [], {"error": err}
def calendar(sym):
    """Next earnings date and dividend dates, when Yahoo publishes them. Missing is fine."""
    url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.request.quote(sym)}?modules=calendarEvents"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r: j = json.load(r)
        ce = j["quoteSummary"]["result"][0].get("calendarEvents", {})
        f = lambda v: datetime.fromtimestamp(v["raw"], timezone.utc).date().isoformat() if isinstance(v, dict) and v.get("raw") else None
        ed = [f(x) for x in (ce.get("earnings", {}).get("earningsDate") or [])]
        return {k: v for k, v in {"earnings": next((d for d in ed if d), None), "exDividend": f(ce.get("exDividendDate")), "dividend": f(ce.get("dividendDate"))}.items() if v}
    except Exception as e:
        return {"error": repr(e)[:80]}
today = date.today(); out = {"asOf": today.isoformat(), "stocks": {}, "skipped": {}}
for sid, sym, name, region, cur, sector, words in STOCKS:
    ser, meta = fetch(sym); time.sleep(0.6)
    if len(ser) < 30: out["skipped"][sid] = "missing " + str(meta.get("error", "")); continue
    if (today - date.fromisoformat(ser[-1][0])).days > 7: out["skipped"][sid] = "stale"; continue
    if max(abs(ser[i][1] / ser[i - 1][1] - 1) for i in range(max(1, len(ser) - 30), len(ser))) > 0.4: out["skipped"][sid] = "implausible jump"; continue
    dec = 0 if cur == "COP" else 2
    out["stocks"][sid] = {"ticker": sym.replace(".CL", ""), "name": name, "region": region, "currency": cur, "sector": sector[0], "sector_es": sector[1], "words": words,
                          "prefix": "$" if cur == "COP" else "US$", "decimals": dec,
                          "series": [[d, round(v, dec) if dec else round(v)] for d, v in ser],
                          "source": {"name": f"Yahoo Finance ({sym}), daily close", "url": f"https://finance.yahoo.com/quote/{sym}/"}}

# Upcoming earnings and dividend dates for the US stocks, from Nasdaq's public calendars (next 45 days, weekdays).
from datetime import timedelta
want = {v["ticker"].replace("-", "."): k for k, v in out["stocks"].items() if v["region"] == "us"}
want.update({v["ticker"]: k for k, v in out["stocks"].items() if v["region"] == "us"})
NH = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36", "Accept": "application/json"}
cal_err = 0
for n in range(0, 46):
    d = today + timedelta(days=n)
    if d.weekday() > 4: continue
    for kind, key in (("earnings", "earnings"), ("dividends", "exDividend")):
        try:
            with urllib.request.urlopen(urllib.request.Request(f"https://api.nasdaq.com/api/calendar/{kind}?date={d.isoformat()}", headers=NH), timeout=20) as r: j = json.load(r)
            rows = ((j.get("data") or {}).get("rows") or ((j.get("data") or {}).get("calendar") or {}).get("rows") or [])
            for row in rows:
                sid = want.get(str(row.get("symbol", "")).upper())
                if sid and key not in out["stocks"][sid].setdefault("calendar", {}): out["stocks"][sid]["calendar"][key] = d.isoformat()
        except Exception as e:
            cal_err += 1; out.setdefault("calendarErrors", []).append(f"{kind} {d}: {repr(e)[:60]}") if cal_err < 4 else None
        time.sleep(0.25)
json.dump(out, open(os.path.join(D, "stocks-live.json"), "w"), separators=(",", ":"))
print("stocks:", sorted(out["stocks"]), "skipped:", out["skipped"])
