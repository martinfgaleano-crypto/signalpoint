"""SignalPoint news drafts. Collects recent items from public feeds, asks Claude to write each as a SignalPoint brief
grounded ONLY in the fetched source text, validates every draft with the publication gate (tools/quality.cjs) and writes
the result to drafts/<date>.json. Nothing is published: a person reviews the drafts before they reach the site."""
import json, os, re, sys, time, html, subprocess, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
OUT = sys.argv[1] if len(sys.argv) > 1 else "drafts"
KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = os.environ.get("SP_MODEL", "claude-sonnet-5-5")
MAX_ITEMS = int(os.environ.get("SP_MAX_ITEMS", "6"))
UA = {"User-Agent": "Mozilla/5.0 (SignalPoint news drafts; github.com/martinfgaleano-crypto/signalpoint)"}
FEEDS = [
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml", "A"),
    ("US Bureau of Labor Statistics", "https://www.bls.gov/feed/bls_latest.rss", "A"),
    ("US Energy Information Administration", "https://www.eia.gov/rss/todayinenergy.xml", "A"),
    ("Valora Analitik", "https://www.valoraanalitik.com/feed/", "B"),
    ("Portafolio", "https://www.portafolio.co/rss/economia.xml", "B"),
    ("Federal Reserve (monetary policy)", "https://www.federalreserve.gov/feeds/press_monetary.xml", "A"),
]
PRIORITY = re.compile(r"banrep|banco de la rep|\bdane\b|\bipc\b|inflaci|\btrm\b|d[oó]lar|peso colombiano|colcap|\bbvc\b|bolsa de valores|acci[oó]n(es)? de|ecopetrol|bancolombia|cibest|grupo argos|grupo sura|\bisa\b|\btes\b|tasa de (inter[eé]s|pol[ií]tica)|\bfed\b|fomc|\bcpi\b|\bppi\b|petr[oó]leo|brent|crude|treasury|bonos?|utilidad(es)?|resultados (trimestrales|financieros)|pib\b|calificaci[oó]n|fitch|moody|s&p", re.I)
SKIP = re.compile(r"entrevista|festival|expo|vacantes|navide|concierto|turismo|viajeros", re.I)
def get(url, timeout=40):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r: return r.read()
def text_of(raw):
    s = raw.decode("utf-8", "replace")
    s = re.sub(r"(?is)<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s); s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()
def items():
    out, log = [], {}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=40)
    for name, url, grade in FEEDS:
        try:
            root = ET.fromstring(get(url)); n = 0
            for it in root.iter("item"):
                title = (it.findtext("title") or "").strip(); link = (it.findtext("link") or "").strip()
                desc = text_of((it.findtext("description") or "").encode()); pub = it.findtext("pubDate") or ""
                try: when = datetime.strptime(pub[:25].strip(), "%a, %d %b %Y %H:%M:%S").replace(tzinfo=timezone.utc)
                except Exception: when = None
                if not title or not link.startswith("https://") or (when and when < cutoff): continue
                out.append({"feed": name, "grade": grade, "title": title, "link": link, "desc": desc[:600], "date": (when or datetime.now(timezone.utc)).date().isoformat()}); n += 1
            log[name] = n
        except Exception as e:
            log[name] = "error: " + repr(e)[:120]
    return out, log
SCHEMA = """Return ONE JSON object, no prose, with exactly these keys:
{"title": English headline <= 110 chars, factual, no hype,
 "category": one of "Central banks","Macro data","Earnings","M&A","Corporate","Regulation","Commodities","Geopolitics","Other",
 "region": e.g. "Colombia", "US", "US / Global",
 "eventDate": "YYYY-MM-DD" (the day the event happened, not in the future),
 "evidence": "A" if the source is the primary document (central bank, statistics office, company filing), "B" if attributed press reporting, "C" if a single unconfirmed report,
 "source": {"name": who published it, "url": the exact source URL given},
 "summary": 2-4 English sentences with only figures that appear in the source text,
 "actors": 2-4 items {"name": who is affected, "ticker": "" or a real ticker, "impact": "favorable"|"adverse"|"mixed"|"undetermined", "reason": one sentence on the channel},
 "watch": 2-3 items {"text": an observable follow-up, "due": "YYYY-MM-DD" or "", "status": "open", "kind": "observation", "note": how it will be checked},
 "unknowns": 2-3 short open questions the source leaves unanswered,
 "tags": up to 6 short tags,
 "es": {"title": Spanish title, "summary": Spanish summary, "actors": [{"name","reason"} same order], "watch": [{"text","note"} same order], "unknowns": [same order]}}
Rules: use ONLY the source text provided; never invent numbers, quotes or dates; if the text does not support a field, be conservative ("undetermined").
Never recommend buying, selling or holding anything, never give price targets or confidence scores. Spanish must be neutral Colombian Spanish (no voseo)."""
def claude(prompt):
    body = json.dumps({"model": MODEL, "max_tokens": 2500, "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={"x-api-key": KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r: j = json.load(r)
    t = "".join(c.get("text", "") for c in j.get("content", []))
    m = re.search(r"\{.*\}", t, re.S)
    return json.loads(m.group(0)) if m else None
def validate(b, today):
    js = "const q=require('./tools/quality.cjs');const b=JSON.parse(require('fs').readFileSync(0,'utf8'));console.log(JSON.stringify(q.validateBrief(b,{today:process.argv[1],maxAgeDays:4})))"
    r = subprocess.run(["node", "-e", js, today], input=json.dumps(b), capture_output=True, text=True)
    try: return json.loads(r.stdout)
    except Exception: return {"ok": False, "errors": ["validator failed: " + r.stderr[:200]]}
def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48]
def main():
    os.makedirs(OUT, exist_ok=True)
    today = datetime.now(timezone.utc).date().isoformat()
    seen_p = os.path.join(OUT, "seen.json"); seen = set(json.load(open(seen_p))) if os.path.exists(seen_p) else set()
    cand, feedlog = items()
    def score(c): return len(PRIORITY.findall(c["title"] + " " + c["desc"]))
    cand = [c for c in cand if c["link"] not in seen and not SKIP.search(c["title"]) and (c["grade"] == "A" or score(c) >= 1)]
    cand.sort(key=lambda c: (c["grade"], -score(c)))
    report = {"generatedAt": datetime.now(timezone.utc).isoformat(), "model": MODEL, "feeds": feedlog, "briefs": [], "rejected": []}
    if not KEY:
        report["note"] = "ANTHROPIC_API_KEY is not set: candidates listed, no drafts written."
        report["candidates"] = cand[:20]
    for c in (cand[:MAX_ITEMS] if KEY else []):
        try: src = text_of(get(c["link"]))[:9000]
        except Exception as e: src = c["desc"]
        prompt = f"{SCHEMA}\n\nSource: {c['feed']} (evidence grade suggested: {c['grade']})\nURL: {c['link']}\nPublished: {c['date']}\nHeadline: {c['title']}\n\nSOURCE TEXT:\n{src}"
        try:
            b = claude(prompt)
        except Exception as e:
            report["rejected"].append({"title": c["title"], "url": c["link"], "errors": ["model call failed: " + repr(e)[:160]]}); continue
        if not isinstance(b, dict):
            report["rejected"].append({"title": c["title"], "url": c["link"], "errors": ["no JSON"]}); continue
        b.pop("id", None)
        if isinstance(b.get("source"), dict): b["source"]["url"] = c["link"]
        v = validate(b, today)
        seen.add(c["link"])
        if v["ok"]:
            report["briefs"].append(dict({"id": f"{b['eventDate']}-{slug(b['title'])}"}, **b))
        else:
            report["rejected"].append({"title": c["title"], "url": c["link"], "errors": v["errors"][:6]})
        time.sleep(2)
    json.dump(report, open(os.path.join(OUT, f"{today}.json"), "w"), ensure_ascii=False, indent=1)
    json.dump(sorted(seen), open(seen_p, "w"))
    print(json.dumps({"feeds": feedlog, "drafts": len(report["briefs"]), "rejected": len(report["rejected"])}))
if __name__ == "__main__": main()
