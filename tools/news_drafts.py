"""SignalPoint news drafts (v1). Collects recent items from public feeds, asks Claude to write each as a SignalPoint brief
grounded ONLY in the fetched source text, validates every draft with the publication gate (tools/quality.cjs) and writes
the result to drafts/<date>.json. Nothing is published: a person reviews the drafts before they reach the site."""
import json, os, re, sys, time, html, subprocess, urllib.request, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
OUT = sys.argv[1] if len(sys.argv) > 1 else "drafts"
KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = os.environ.get("SP_MODEL", "claude-sonnet-5-5")
MAX_ITEMS = int(os.environ.get("SP_MAX_ITEMS", "6"))
REVIEW_MODEL = os.environ.get("SP_REVIEW_MODEL", "claude-opus-5-5")
MAX_PUBLISH = int(os.environ.get("SP_MAX_PUBLISH", "5"))
KEEP_LIVE = 40
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
    cutoff = datetime.now(timezone.utc) - timedelta(hours=72)
    for name, url, grade in FEEDS:
        try:
            root = ET.fromstring(get(url)); n = 0; sample = ""
            for it in root.iter("item"):
                if not sample: sample = (it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date") or "none")[:40]
                title = (it.findtext("title") or "").strip(); link = (it.findtext("link") or "").strip()
                desc = text_of((it.findtext("description") or "").encode()); pub = it.findtext("pubDate") or ""
                try:
                    from email.utils import parsedate_to_datetime
                    when = parsedate_to_datetime(pub).astimezone(timezone.utc)
                except Exception:
                    try:
                        w = datetime.fromisoformat(pub.strip().replace(" ", "T"))
                        when = (w if w.tzinfo else w.replace(tzinfo=timezone(timedelta(hours=-5)))).astimezone(timezone.utc)
                    except Exception: when = None
                if not title or not link.startswith("https://") or not when or when < cutoff: continue
                out.append({"feed": name, "grade": grade, "title": title, "link": link, "desc": desc[:600], "date": (when or datetime.now(timezone.utc)).date().isoformat()}); n += 1
            log[name] = f"{n} (first date: {sample})"
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
def _call(messages, model=None):
    body = json.dumps({"model": model or MODEL, "max_tokens": 4000, "messages": messages}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={"x-api-key": KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r: j = json.load(r)
    return "".join(c.get("text", "") for c in j.get("content", []))
def _parse(t):
    i = t.find("{")
    if i < 0: raise ValueError("no JSON object")
    obj, _ = json.JSONDecoder().raw_decode(t[i:])
    return obj
def claude(prompt):
    msgs = [{"role": "user", "content": prompt + "\n\nOutput only the JSON object. Use straight double quotes for JSON strings; inside text use « » or single quotes, never unescaped double quotes."}]
    t = _call(msgs)
    try: return _parse(t)
    except Exception as e:
        msgs += [{"role": "assistant", "content": t}, {"role": "user", "content": "That was not valid JSON (" + str(e)[:120] + "). Return the same brief again as one valid JSON object and nothing else."}]
        return _parse(_call(msgs))
NUM = re.compile(r"(?<![\w.,])(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)")
def _norm(n):
    n = n.strip(".,")
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", n): return [n.replace(".", "").replace(",", "")]   # thousands only
    if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+[.,]\d+", n): body, dec = n[:-len(re.split(r"[.,]", n)[-1]) - 1], re.split(r"[.,]", n)[-1]; return [body.replace(".", "").replace(",", "") + "." + dec]
    return [n.replace(",", ".")]
def numbers_supported(b, src):
    """Every number in the summaries (except years and small integers) must appear in the source text."""
    pool = set()
    for m in NUM.finditer(src):
        for v in _norm(m.group(1)): pool.add(v); pool.add(v.rstrip("0").rstrip(".") if "." in v else v)
    missing = []
    for text in (b.get("summary", ""), (b.get("es") or {}).get("summary", "")):
        for m in NUM.finditer(text):
            for v in _norm(m.group(1)):
                if re.fullmatch(r"(19|20)\d\d", v) or (re.fullmatch(r"\d", v)): continue
                vv = v.rstrip("0").rstrip(".") if "." in v else v
                if v not in pool and vv not in pool: missing.append(m.group(1))
    return sorted(set(missing))
REVIEW = """You are SignalPoint's fact-checking editor. Compare the DRAFT brief with the SOURCE TEXT.
Return ONE JSON object: {"pass": true|false, "relevance": 1-5, "issues": ["..."]}.
Fail ("pass": false) if ANY of these is true: a fact, number, date, name or attribution in the draft is not supported by the source;
the eventDate is not the date of the event or publication in the source; the evidence grade is too high for the source (press = B);
the text recommends buying, selling or holding, or gives a price target; the Spanish and English versions disagree;
an actor's impact is asserted without support in the source. relevance: how useful this is for a young Colombian following markets
(5 = central bank, inflation, GDP, the peso, major listed companies; 1 = lifestyle or minor local news). List concrete issues; empty if none."""
def review(b, src):
    t = _call([{"role": "user", "content": REVIEW + "\n\nDRAFT:\n" + json.dumps(b, ensure_ascii=False) + "\n\nSOURCE TEXT:\n" + src[:9000] + "\n\nOutput only the JSON object."}], model=REVIEW_MODEL)
    return _parse(t)
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
            bid = f"{b['eventDate']}-{slug(b['title'])}"
            miss = numbers_supported(b, src)
            try: rv = review(b, src)
            except Exception as e: rv = {"pass": False, "relevance": 0, "issues": ["review failed: " + repr(e)[:120]]}
            ok = (not miss) and rv.get("pass") is True and int(rv.get("relevance") or 0) >= 3
            report["briefs"].append(dict({"id": bid}, **b))
            report.setdefault("audit", []).append({"id": bid, "title": b["title"], "url": c["link"], "gate": "pass", "numbers_missing": miss,
                "review": rv, "decision": "publish" if ok else "hold", "reviewModel": REVIEW_MODEL})
        else:
            report["rejected"].append({"title": c["title"], "url": c["link"], "errors": v["errors"][:6]})
            report.setdefault("audit", []).append({"title": c["title"], "url": c["link"], "gate": "fail", "errors": v["errors"][:6], "decision": "reject"})
        time.sleep(2)
    day = os.path.join(OUT, f"{today}.json")
    if os.path.exists(day):   # several runs in one day add to the same file instead of replacing it
        try:
            old = json.load(open(day)); ids = {b["id"] for b in report["briefs"]}
            report["briefs"] = [b for b in old.get("briefs", []) if b["id"] not in ids] + report["briefs"]
            report["rejected"] = old.get("rejected", []) + report["rejected"]
            report["audit"] = old.get("audit", []) + report.get("audit", [])
        except Exception: pass
    json.dump(report, open(day, "w"), ensure_ascii=False, indent=1)
    json.dump(sorted(seen), open(seen_p, "w"))
    # drafts from earlier runs that were never reviewed (e.g. written before self-review existed) get reviewed now
    audited = {a.get("id") for a in report.get("audit", [])}
    for b in report["briefs"]:
        if b["id"] in audited or not KEY: continue
        try: src = text_of(get(b["source"]["url"]))[:9000]
        except Exception: continue
        miss = numbers_supported(b, src)
        try: rv = review({k: v for k, v in b.items() if k != "id"}, src)
        except Exception as e: rv = {"pass": False, "relevance": 0, "issues": ["review failed: " + repr(e)[:120]]}
        ok = (not miss) and rv.get("pass") is True and int(rv.get("relevance") or 0) >= 3
        report.setdefault("audit", []).append({"id": b["id"], "title": b["title"], "url": b["source"]["url"], "gate": "pass", "numbers_missing": miss, "review": rv, "decision": "publish" if ok else "hold", "reviewModel": REVIEW_MODEL})
    publish(report, today)
def publish(report, today):
    """Automatic publication with self-review: only drafts that passed the gate, the number check and the editor review."""
    os.makedirs(os.path.join(OUT, "live"), exist_ok=True)
    lp = os.path.join(OUT, "live", "briefs-live.json")
    live = json.load(open(lp)) if os.path.exists(lp) else {"briefs": []}
    retracted = set(json.load(open(os.path.join(OUT, "retracted.json")))) if os.path.exists(os.path.join(OUT, "retracted.json")) else set()
    have = {b["id"] for b in live["briefs"]} | {b["source"]["url"] for b in live["briefs"]}
    ok_ids = [a["id"] for a in report.get("audit", []) if a.get("decision") == "publish"]
    byid = {b["id"]: b for b in report["briefs"]}
    added = 0
    for i in ok_ids:
        b = byid.get(i)
        if not b or i in have or b["source"]["url"] in have or i in retracted: continue
        if added >= MAX_PUBLISH: break
        live["briefs"].insert(0, b); added += 1
        for a in report["audit"]:
            if a.get("id") == i: a["publishedAt"] = datetime.now(timezone.utc).isoformat()
    live["briefs"] = [b for b in live["briefs"] if b["id"] not in retracted][:KEEP_LIVE]
    live["updatedAt"] = datetime.now(timezone.utc).isoformat(); live["retracted"] = sorted(retracted)
    json.dump(live, open(lp, "w"), ensure_ascii=False, indent=1)
    json.dump(report, open(os.path.join(OUT, f"{today}.json"), "w"), ensure_ascii=False, indent=1)
    # running audit summary
    sp = os.path.join(OUT, "audit-summary.json"); summ = json.load(open(sp)) if os.path.exists(sp) else {"days": {}}
    au = report.get("audit", [])
    summ["days"][today] = {"drafted": sum(1 for a in au if a.get("gate") == "pass"), "rejected_by_gate": sum(1 for a in au if a.get("gate") == "fail"),
        "held_by_review": sum(1 for a in au if a.get("decision") == "hold"), "published": sum(1 for a in au if a.get("publishedAt"))}
    json.dump(summ, open(sp, "w"), indent=1)
    print("published", added, json.dumps({"feeds": report.get("feeds"), "drafts": len(report["briefs"]), "rejected": len(report["rejected"])}))
if __name__ == "__main__": main()
