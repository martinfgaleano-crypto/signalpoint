"""Precision layer for SignalPoint Pro analysis.

1. Grounding: match a brief to the event studies in history.json and hand the model only those statistics.
2. Pattern record: when an event's past behaviour is statistically reliable, log what the pattern points to,
   then score it once the horizon has passed (did the historical pattern hold this time?).
Nothing here forecasts; it measures how often past patterns held.
"""
import csv, io, json, re, urllib.request
from datetime import date, datetime, timezone

DATA = "https://raw.githubusercontent.com/martinfgaleano-crypto/signalpoint/data/"
UA = {"User-Agent": "SignalPoint insight precision (github.com/martinfgaleano-crypto/signalpoint)"}

def _get(name, timeout=40):
    with urllib.request.urlopen(urllib.request.Request(DATA + name, headers=UA), timeout=timeout) as r:
        return r.read()

def load_history():
    try: return json.loads(_get("history.json"))
    except Exception as e:
        print("history unavailable", repr(e)[:100]); return None

# Conservative keyword rules: a brief maps to an event only when its text clearly describes it.
UP = r"(rais|hike|increas|sube|subi|aument|alza|eleva|jump|surg|climb|rise|rose|dispar)"
DOWN = r"(cut|lower|reduc|baj|recort|ca[ei]|descend|drop|fall|fell|slid|retroce)"
RULES = [
    ("banrep_hike", r"(banco de la rep|banrep|emisor)", UP + r"[^.]{0,60}(tasa|rate)|(tasa|rate)[^.]{0,40}" + UP),
    ("banrep_cut", r"(banco de la rep|banrep|emisor)", DOWN + r"[^.]{0,60}(tasa|rate)|(tasa|rate)[^.]{0,40}" + DOWN),
    ("fed_hike", r"(federal reserve|\bfed\b|fomc|reserva federal)", UP + r"[^.]{0,60}(rate|tasa)|(rate|tasa)[^.]{0,40}" + UP),
    ("fed_cut", r"(federal reserve|\bfed\b|fomc|reserva federal)", DOWN + r"[^.]{0,60}(rate|tasa)|(rate|tasa)[^.]{0,40}" + DOWN),
    ("fed_meeting", r"(fomc|federal open market|reuni[oó]n de la fed|fed (decision|meeting|minutes)|minutas de la fed|actas de la fed)", r"."),
    ("us10y_jump", r"(10-year|10 años|treasury yield|rendimiento del (bono|tesoro))", UP),
    ("brent_up", r"(brent|crude|petr[oó]leo|oil price)", UP),
    ("trm_up", r"(\btrm\b|d[oó]lar en colombia|peso colombiano|d[oó]lar.{0,20}pesos)", r"(d[oó]lar|trm)[^.]{0,40}" + UP + r"|peso[^.]{0,30}" + DOWN),
    ("trm_down", r"(\btrm\b|d[oó]lar en colombia|peso colombiano|d[oó]lar.{0,20}pesos)", r"(d[oó]lar|trm)[^.]{0,40}" + DOWN + r"|peso[^.]{0,30}" + UP),
    ("colo_jump", r"(colcap|bolsa de colombia|bvc|acciones colombianas)", UP),
]

def match_events(b):
    t = " ".join([b.get("title", ""), b.get("summary", ""), (b.get("es") or {}).get("title", ""), (b.get("es") or {}).get("summary", "")]).lower()
    out = []
    for key, subj, verb in RULES:
        if re.search(subj, t) and re.search(verb, t): out.append(key)
    if "fed_hike" in out or "fed_cut" in out:
        out = [k for k in out if k != "fed_meeting"]
    if "trm_up" in out and "trm_down" in out:
        out = [k for k in out if k not in ("trm_up", "trm_down")]
    return out[:3]

def evidence(keys, hist):
    """Plain-text block of the event-study statistics the model may cite, plus the reliable patterns."""
    if not hist or not keys: return "", []
    lines, pats = [], []
    base = hist.get("baseline", {})
    for k in keys:
        e = hist["events"].get(k)
        if not e: continue
        lines.append(f"EVENT {k}: {e['en']} / {e['es']}. Past cases: {e['n']} ({e['first']} to {e['last']}).")
        for ak, a in e.get("assets", {}).items():
            for h in ("5", "20"):
                v = a["h"].get(h)
                if not v: continue
                rel = "statistically reliable" if v.get("sig") else ("suggestive but not confirmed (may be chance)" if v.get("hint") else "NOT reliable (could be chance)")
                lines.append(f"  {a['en']} / {a['es']}, {h} trading days later: up in {v['up']} of {v['n']} cases "
                             f"({round(v['up'] / v['n'] * 100)}%; any period: {v['base']}%), median {v['med']:+.2f}%; {rel}.")
                if (v.get("sig") or v.get("hint")) and v["n"] >= 10:
                    share = v["up"] / v["n"] * 100
                    pats.append({"event": k, "asset": ak, "h": int(h), "dir": "up" if share > v["base"] else "down",
                                 "share": round(share), "base": v["base"], "n": v["n"], "level": "reliable" if v.get("sig") else "suggestive"})
    return "\n".join(lines), pats

GROUND = """HISTORICAL EVIDENCE (SignalPoint event studies on daily data since 2000; the only historical statistics you may cite):
{ev}
Rules for the evidence: in "Scenarios" cite at least one of these statistics with its number of cases (for example "in 23 of 61 past hikes").
Only call a pattern reliable when it is marked statistically reliable; call a suggestive one a tendency that may be chance; otherwise say the past is mixed. Do not invent any other historical statistic.
Copy the numbers exactly; in Spanish use Colombian notation."""
NOGROUND = "No historical evidence matched this brief: do not cite historical statistics or past frequencies."

VERIFY = """You are SignalPoint's claim checker. Split the ANALYSIS (English and Spanish) into its factual claims and check each one.
A claim is SUPPORTED if it is stated in the SOURCE TEXT or the BRIEF, if it copies a statistic from the HISTORICAL EVIDENCE exactly,
or if it is a conditional description of a widely accepted economic mechanism ("if rates rise, borrowing tends to cost more").
A claim is UNSUPPORTED if it states a fact, number, date, name, cause or outcome that none of those back, if it predicts what will happen,
if it recommends buying, selling or holding, or if the Spanish says something the English does not.
Return ONE JSON object: {"claims": <number of claims checked>, "unsupported": [{"text": "<the claim>", "why": "<short reason>"}]}"""

# ----- pattern record -----
SERIES = {"sp500": ("yahoo", "yahoo_GSPC.json"), "colo": ("yahoo", "yahoo_COLO.json"), "ec": ("yahoo", "yahoo_EC.json"),
          "brent": ("fred", "fred_DCOILBRENTEU.csv"), "usdcop": ("trm", "trm.csv")}

def _series(ak):
    kind, name = SERIES[ak]; raw = _get(name, 60)
    if kind == "yahoo":
        j = json.loads(raw)["chart"]["result"][0]; out = {}
        for t, c in zip(j["timestamp"], j["indicators"]["quote"][0]["close"]):
            if c is not None: out[datetime.fromtimestamp(t, timezone.utc).date().isoformat()] = c
        return sorted(out.items())
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if kind == "fred":
        k = [c for c in rows[0] if c != "observation_date"][0]
        return [(r["observation_date"][:10], float(r[k])) for r in rows if r[k] not in ("", ".")]
    return sorted((r["vigenciadesde"][:10], float(r["valor"])) for r in rows if r.get("valor"))

def score(track):
    """Close every open pattern whose horizon has passed. Base is the last close on or before the event date."""
    cache = {}
    still = []
    for p in track.get("open", []):
        try:
            ser = cache.get(p["asset"]) or cache.setdefault(p["asset"], _series(p["asset"]))
        except Exception as e:
            print("series unavailable", p["asset"], repr(e)[:80]); still.append(p); continue
        i0 = max((i for i, (d, _) in enumerate(ser) if d <= p["date"]), default=None)
        if i0 is None or i0 + p["h"] >= len(ser): still.append(p); continue
        chg = (ser[i0 + p["h"]][1] / ser[i0][1] - 1) * 100
        q = dict(p, closedOn=ser[i0 + p["h"]][0], realized=round(chg, 2), held=(chg > 0) == (p["dir"] == "up"))
        track.setdefault("closed", []).append(q)
    track["open"] = still
    cl = track.get("closed", [])
    exp = [(p["share"] if p["dir"] == "up" else 100 - p["share"]) for p in cl]
    track["summary"] = {"open": len(still), "closed": len(cl), "held": sum(1 for p in cl if p["held"]),
                        "expected": round(sum(exp) / len(exp)) if exp else None, "updatedAt": date.today().isoformat()}
    return track
