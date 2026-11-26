"""SignalPoint news drafts. Collects recent items from public feeds and asks a model to write each as a SignalPoint brief
grounded ONLY in the fetched source text. Every draft goes through automated checks: the schema gate (tools/quality.cjs), a
check that every number in the summaries appears in the source, and a fact-check review by a second model (the "editor").
Drafts that pass all three are PUBLISHED AUTOMATICALLY to live/briefs-live.json (at most SP_MAX_PUBLISH per run), which the
site reads from the `drafts` branch. No person reviews a brief before it is published; the rest are held or rejected, and
every decision is written to <date>.json and audit-summary.json. A published brief is withdrawn by adding its id to retracted.json."""
import json, os, re, sys, time, html, subprocess, urllib.request, urllib.error, xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
OUT = sys.argv[1] if len(sys.argv) > 1 else "drafts"
KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = os.environ.get("SP_MODEL", "claude-sonnet-5-5")
MAX_ITEMS = int(os.environ.get("SP_MAX_ITEMS", "6"))
REVIEW_MODEL = os.environ.get("SP_REVIEW_MODEL", "claude-opus-5-5")
# SP_MAX_PUBLISH: how many new briefs one run may publish (default 5). Set it to 0 to "draft and hold everything for manual
# approval": the run still drafts, checks and reviews, and still writes <date>.json, seen.json and audit-summary.json, but it adds
# nothing to live/briefs-live.json and writes no new Pro analysis (no backfill either). Held drafts are marked in the audit.
MAX_PUBLISH = max(0, int(os.environ.get("SP_MAX_PUBLISH", "5")))
# Hard spend cap: model calls allowed in ONE run. "draft" = calls to SP_MODEL (writing briefs and Pro analysis),
# "review" = calls to SP_REVIEW_MODEL (editor review of briefs and claim check of analysis). Measured runs used 11 to 19 of each (Nov 24-26, 2026); 24 covers a full run (6 briefs + 9 analyses).
# When a limit is reached the run stops drafting, publishes only what was already fully checked, and records it in the audit.
LIMITS = {"draft": max(0, int(os.environ.get("SP_MAX_DRAFT_CALLS", "24"))), "review": max(0, int(os.environ.get("SP_MAX_REVIEW_CALLS", "24")))}
CALLS = {"draft": 0, "review": 0}
BUDGET_HIT = []
class BudgetExceeded(RuntimeError): pass
def budget_left(kind): return LIMITS[kind] - CALLS[kind]
def budget_note(where):
    msg = "%s: call budget reached (draft %d/%d, review %d/%d)" % (where, CALLS["draft"], LIMITS["draft"], CALLS["review"], LIMITS["review"])
    if not any(m.startswith(where + ":") for m in BUDGET_HIT): BUDGET_HIT.append(msg); print("BUDGET", msg)
KEEP_LIVE = 40
UA = {"User-Agent": "Mozilla/5.0 (SignalPoint news drafts; github.com/martinfgaleano-crypto/signalpoint)"}
FEEDS = [
    ("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml", "A"),
    ("US Bureau of Labor Statistics", "https://www.bls.gov/feed/bls_latest.rss", "A"),
    ("US Energy Information Administration", "https://www.eia.gov/rss/todayinenergy.xml", "A"),
    ("Valora Analitik", "https://www.valoraanalitik.com/feed/", "B"),
    ("Portafolio", "https://www.portafolio.co/rss/economia.xml", "B"),
    ("Federal Reserve (monetary policy)", "https://www.federalreserve.gov/feeds/press_monetary.xml", "A"),
    ("US Bureau of Economic Analysis", "https://apps.bea.gov/rss/rss.xml", "A"),
    ("US Securities and Exchange Commission", "https://www.sec.gov/news/pressreleases.rss", "A"),
    ("US Census Bureau (economic indicators)", "https://www.census.gov/economic-indicators/indicator.xml", "A"),
    ("CNBC Economy", "https://www.cnbc.com/id/20910258/device/rss/rss.html", "B"),
    ("CNBC Finance", "https://www.cnbc.com/id/10000664/device/rss/rss.html", "B"),
]
US_FEEDS = {"Federal Reserve", "US Bureau of Labor Statistics", "US Energy Information Administration", "Federal Reserve (monetary policy)", "US Bureau of Economic Analysis", "US Securities and Exchange Commission", "US Census Bureau (economic indicators)", "CNBC Economy", "CNBC Finance"}
PRIORITY = re.compile(r"\bstocks?\b|\byields?\b|treasur|earnings|inflation|\bjobs\b|payrolls|unemployment|tariffs?|\bdollar\b|\bgdp\b|recession|interest rates?|rate (cut|hike)|nasdaq|s&p|dow\b|oil prices?|consumer spending|retail sales|housing starts|salario m[ií]nimo|econom[ií]a|bolsas?\b|premercado|mercados?\b|aranceles?|d[eé]ficit|deuda|fiscal|desempleo|exportaciones|importaciones|remesas|tasas?\b|recesi[oó]n|crecimiento|banrep|banco de la rep|\bdane\b|\bipc\b|inflaci|\btrm\b|d[oó]lar|peso colombiano|colcap|\bbvc\b|bolsa de valores|acci[oó]n(es)? de|ecopetrol|bancolombia|cibest|grupo argos|grupo sura|\bisa\b|\btes\b|tasa de (inter[eé]s|pol[ií]tica)|\bfed\b|fomc|\bcpi\b|\bppi\b|petr[oó]leo|brent|crude|treasury|bonos?|utilidad(es)?|resultados (trimestrales|financieros)|pib\b|calificaci[oó]n|fitch|moody|s&p", re.I)
SKIP = re.compile(r"entrevista|festival|\bexpo\b|vacantes|navide|concierto|turismo|viajeros", re.I)
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
SCHEMA = """Number format: in English fields use English notation (US$2,540 million, 144.7); in Spanish fields use Colombian notation (US$2.540 millones, 144,7). Never copy Spanish number notation into English text.
Return ONE JSON object, no prose, with exactly these keys:
{"title": English headline of at most 95 characters (count them; Spanish title also at most 105), factual, no hype, attribute claims to who made them (say "some workers", not "workers", when the source says only part of a group),
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
def _call(messages, model=None, kind="draft"):
    if budget_left(kind) <= 0: raise BudgetExceeded(kind + " call budget reached")   # checked before any request is sent
    CALLS[kind] += 1
    body = json.dumps({"model": model or MODEL, "max_tokens": 4000, "messages": messages}).encode()
    return _http(body)
def _http(body):
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={"x-api-key": KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r: j = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError("API %s: %s" % (e.code, e.read()[:300].decode("utf-8", "replace")))
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
def review(b, src, feed_date=""):
    t = _call([{"role": "user", "content": REVIEW + "\n\nDRAFT:\n" + json.dumps(b, ensure_ascii=False) + "\n\nPUBLICATION DATE (from the publisher's feed): " + (feed_date or "unknown") + "\n\nSOURCE TEXT:\n" + src[:9000] + "\n\nOutput only the JSON object."}], model=REVIEW_MODEL, kind="review")
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
    raw_cand = list(cand)
    def score(c): return len(PRIORITY.findall(c["title"] + " " + c["desc"]))
    cand = [c for c in cand if c["link"] not in seen and not SKIP.search(c["title"]) and (c["grade"] == "A" or score(c) >= 1)]
    cand.sort(key=lambda c: (c["grade"], -score(c)))
    cand = [c for c in cand if not (c["feed"].startswith("US Securities") and score(c) < 1)]
    _seen_t = set(); _dedup = []
    for c in cand:   # the same release often comes through two feeds (e.g. both Fed feeds)
        k = re.sub(r"[^a-z0-9]+", "", c["title"].lower())[:60]
        if k in _seen_t: continue
        _seen_t.add(k); _dedup.append(c)
    cand = _dedup
    us_q = [c for c in cand if c["feed"] in US_FEEDS]; co_q = [c for c in cand if c["feed"] not in US_FEEDS]; mixed = []
    while us_q or co_q:   # alternate the two markets so each run covers the US and Colombia
        if us_q: mixed.append(us_q.pop(0))
        if co_q: mixed.append(co_q.pop(0))
    cand = mixed
    report = {"generatedAt": datetime.now(timezone.utc).isoformat(), "model": MODEL, "feeds": feedlog, "briefs": [], "rejected": []}
    report["candidates"] = {"from_feeds": len(raw_cand), "after_filter": len(cand), "sample": [c["title"][:90] for c in cand[:8]], "dropped": {"seen": sum(1 for c in raw_cand if c["link"] in seen), "skip": sum(1 for c in raw_cand if SKIP.search(c["title"])), "no_topic": sum(1 for c in raw_cand if c["grade"] != "A" and score(c) < 1)}, "raw_sample": [[c["grade"], score(c), c["title"][:70]] for c in raw_cand[:6]]}
    if not KEY:
        report["note"] = "ANTHROPIC_API_KEY is not set: candidates listed, no drafts written."
        report["candidates"] = cand[:20]
    for c in (cand[:MAX_ITEMS] if KEY else []):
        # a new draft needs one writing call and one editor call; without both, stop here (the item stays unseen and comes back next run)
        if budget_left("draft") < 1 or budget_left("review") < 1: budget_note("drafting stopped"); break
        try: src = text_of(get(c["link"]))[:9000]
        except Exception as e: src = c["desc"]
        prompt = f"{SCHEMA}\n\nSource: {c['feed']} (evidence grade suggested: {c['grade']})\nURL: {c['link']}\nPublished: {c['date']}\nHeadline: {c['title']}\n\nSOURCE TEXT:\n{src}"
        try:
            b = claude(prompt)
        except BudgetExceeded: budget_note("drafting stopped"); break
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
            try: rv = review(b, src, c["date"])
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
        if budget_left("review") < 1: budget_note("review of older drafts stopped"); break   # unreviewed drafts are never published
        try: src = text_of(get(b["source"]["url"]))[:9000]
        except Exception: continue
        miss = numbers_supported(b, src)
        try: rv = review({k: v for k, v in b.items() if k != "id"}, src)
        except Exception as e: rv = {"pass": False, "relevance": 0, "issues": ["review failed: " + repr(e)[:120]]}
        ok = (not miss) and rv.get("pass") is True and int(rv.get("relevance") or 0) >= 3
        report.setdefault("audit", []).append({"id": b["id"], "title": b["title"], "url": b["source"]["url"], "gate": "pass", "numbers_missing": miss, "review": rv, "decision": "publish" if ok else "hold", "reviewModel": REVIEW_MODEL})
    publish(report, today)
INSIGHT = """You write the SignalPoint Pro analysis of one market news brief. Use only the BRIEF and the SOURCE TEXT plus widely accepted economics.
Return ONE JSON object: {"en": [[heading, paragraph], x4], "es": [[heading, paragraph], x4]} with exactly these headings in this order:
en: "What it means", "Scenarios", "Who feels it first", "What would change the reading"
es: "Qué significa", "Escenarios", "Quién lo siente primero", "Qué cambiaría la lectura"
Rules: each paragraph 35-70 words, plain words; scenarios are conditional (if X, then Y tends to...), never predictions; never recommend buying, selling or holding anything and give no price targets;
use only numbers that appear in the source text; English number notation in en, Colombian in es."""
SB_URL = os.environ.get("SUPABASE_URL", "https://nfygddhczgwdurwuzjya.supabase.co")
SB_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
import insight_ml
HIST = None
INSIGHT_LOG = []
def _verify(an, src, b, ev):
    t = _call([{"role": "user", "content": insight_ml.VERIFY + "\n\nANALYSIS:\n" + json.dumps(an, ensure_ascii=False) + "\n\nBRIEF:\n" + json.dumps(b, ensure_ascii=False)
                + "\n\nHISTORICAL EVIDENCE:\n" + (ev or "(none)") + "\n\nSOURCE TEXT:\n" + src[:9000] + "\n\nOutput only the JSON object."}], model=REVIEW_MODEL, kind="review")
    j = _parse(t); return int(j.get("claims") or 0), [u for u in (j.get("unsupported") or []) if isinstance(u, dict) and u.get("text")]
def _shape_ok(j):
    en, es = j.get("en"), j.get("es")
    return isinstance(en, list) and isinstance(es, list) and len(en) == 4 and len(es) == 4 and all(isinstance(x, list) and len(x) == 2 and all(isinstance(y, str) and y.strip() for y in x) for x in en + es)
def make_insight(b):
    """Pro analysis for a published brief, grounded in SignalPoint's event studies and checked claim by claim.
    Public part (first section free) goes to briefs-live.json; the rest only to Supabase."""
    global HIST
    if not KEY or not SB_KEY: return None
    try: src = text_of(get(b["source"]["url"]))[:9000]
    except Exception: return None
    if HIST is None: HIST = insight_ml.load_history() or {}
    keys = insight_ml.match_events(b); ev, pats = insight_ml.evidence(keys, HIST)
    prompt = INSIGHT + "\n\n" + (insight_ml.GROUND.format(ev=ev) if ev else insight_ml.NOGROUND) + "\n\nBRIEF:\n" + json.dumps(b, ensure_ascii=False) + "\n\nSOURCE TEXT:\n" + src
    log = {"id": b["id"], "events": keys, "rounds": []}; INSIGHT_LOG.append(log)
    feedback = ""
    for rnd in range(2):
        if budget_left("draft") < 1 or budget_left("review") < 1:   # an analysis is only published after its claim check
            budget_note("Pro analysis skipped"); log["result"] = "skipped: call budget reached"; return None
        try: j = claude(prompt + feedback)
        except Exception as e: log["result"] = "model error: " + repr(e)[:200]; print("insight model error", repr(e)[:300]); return None
        if not _shape_ok(j): log["rounds"].append({"shape": False}); feedback = "\n\nYour last answer did not have exactly four [heading, paragraph] pairs per language. Follow the format."; continue
        en, es = j["en"], j["es"]
        miss = numbers_supported({"summary": " ".join(p for _, p in en), "es": {"summary": " ".join(p for _, p in es)}}, src + " " + json.dumps(b, ensure_ascii=False) + " " + ev)
        try: n, bad = _verify({"en": en, "es": es}, src, b, ev)
        except Exception as e: n, bad = 0, [{"text": "(checker unavailable)", "why": repr(e)[:80]}]
        log["rounds"].append({"claims": n, "unsupported": bad, "numbers_missing": miss})
        if not miss and not bad: break
        feedback = ("\n\nA checker reviewed your previous analysis. Rewrite it so that every claim is supported. Remove or fix these:\n"
                    + "\n".join("- " + u["text"] + " (" + u.get("why", "") + ")" for u in bad)
                    + ("\nNumbers not found in the source or evidence: " + ", ".join(map(str, miss)) if miss else ""))
    else:
        log["result"] = "rejected"; return None
    log["result"] = "published"
    body = {"p": [{"h": h, "p": t} for h, t in en], "es": {"p": [{"h": h, "p": t} for h, t in es]}}
    req = urllib.request.Request(SB_URL + "/rest/v1/premium_content?on_conflict=id", data=json.dumps({"id": "insight:" + b["id"], "body": body}).encode(), method="POST",
        headers={"apikey": SB_KEY, "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            if r.status >= 300: return None
    except Exception as e:
        print("insight upload failed", repr(e)[:160]); return None
    basis = [{"event": k, "n": HIST["events"][k]["n"], "en": HIST["events"][k]["en"], "es": HIST["events"][k]["es"]} for k in keys if HIST.get("events", {}).get(k)]
    return {"tease": en[0][1], "first": {"h": en[1][0], "p": en[1][1]}, "parts": [h for h, _ in en[2:]], "basis": basis,
            "checked": log["rounds"][-1].get("claims", 0), "_pats": pats,
            "es": {"tease": es[0][1], "first": {"h": es[1][0], "p": es[1][1]}, "parts": [h for h, _ in es[2:]]}}
def _track_add(track, b, ins):
    for p in ins.pop("_pats", []) or []:
        k = (b["id"], p["asset"], p["h"])
        if any((q["id"], q["asset"], q["h"]) == k for q in track.get("open", []) + track.get("closed", [])): continue
        track.setdefault("open", []).append(dict(p, id=b["id"], date=(b.get("eventDate") or datetime.now(timezone.utc).date().isoformat())[:10]))
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
    tp = os.path.join(OUT, "live", "track.json"); track = json.load(open(tp)) if os.path.exists(tp) else {"open": [], "closed": []}
    for i in ok_ids:
        b = byid.get(i)
        if not b or i in have or b["source"]["url"] in have or i in retracted: continue
        if added >= MAX_PUBLISH:   # passed every check but over the publish limit (always the case when SP_MAX_PUBLISH=0): held, not published
            for a in report["audit"]:
                if a.get("id") == i and not a.get("publishedAt"): a["held"] = "publish limit (SP_MAX_PUBLISH=%d)" % MAX_PUBLISH
            continue
        live["briefs"].insert(0, b); added += 1
        ins = make_insight(b)
        if ins: _track_add(track, b, ins); live.setdefault("insights", {})[i] = ins
        for a in report["audit"]:
            if a.get("id") == i: a["publishedAt"] = datetime.now(timezone.utc).isoformat()
    live["briefs"] = [b for b in live["briefs"] if b["id"] not in retracted][:KEEP_LIVE]
    keep = {b["id"] for b in live["briefs"]}; live["insights"] = {k: v for k, v in live.get("insights", {}).items() if k in keep}
    done_back = 0
    for b in live["briefs"]:   # briefs published before analysis existed get theirs a few per run
        if MAX_PUBLISH <= 0 or done_back >= int(os.environ.get("SP_INSIGHT_BACKFILL", "4")): break
        if b["id"] in live["insights"]: continue
        ins = make_insight(b); done_back += 1
        if ins: _track_add(track, b, ins); live["insights"][b["id"]] = ins
    try: track = insight_ml.score(track)
    except Exception as e: print("track scoring failed", repr(e)[:120])
    json.dump(track, open(tp, "w"), ensure_ascii=False, indent=1)
    live["track"] = dict(track.get("summary", {}), recent=[{k: p[k] for k in ("id", "event", "asset", "h", "dir", "share", "realized", "held", "closedOn")} for p in track.get("closed", [])[-8:]])
    report["insight_checks"] = INSIGHT_LOG
    report["budget"] = {"calls": dict(CALLS), "limits": dict(LIMITS), "max_publish": MAX_PUBLISH, "hit": list(BUDGET_HIT)}
    live["updatedAt"] = datetime.now(timezone.utc).isoformat(); live["retracted"] = sorted(retracted)
    json.dump(live, open(lp, "w"), ensure_ascii=False, indent=1)
    json.dump(report, open(os.path.join(OUT, f"{today}.json"), "w"), ensure_ascii=False, indent=1)
    # running audit summary
    sp = os.path.join(OUT, "audit-summary.json"); summ = json.load(open(sp)) if os.path.exists(sp) else {"days": {}}
    au = report.get("audit", [])
    summ["days"][today] = {"drafted": sum(1 for a in au if a.get("gate") == "pass"), "rejected_by_gate": sum(1 for a in au if a.get("gate") == "fail"),
        "held_by_review": sum(1 for a in au if a.get("decision") == "hold"), "published": sum(1 for a in au if a.get("publishedAt")),
        "held_by_publish_limit": sum(1 for a in au if a.get("held") and not a.get("publishedAt")), "last_run": report["budget"]}
    json.dump(summ, open(sp, "w"), indent=1)
    print("published", added, json.dumps({"feeds": report.get("feeds"), "drafts": len(report["briefs"]), "rejected": len(report["rejected"]), "budget": report["budget"]}))
def selftest():
    """Offline check of the call budget and of SP_MAX_PUBLISH=0. No network, no API key: python3 tools/news_drafts.py --selftest"""
    import tempfile
    g = globals(); day = datetime.now(timezone.utc).date().isoformat(); sent = []
    def fake_http(body):
        sent.append(json.loads(body)["model"]); m = json.loads(body)["messages"][0]["content"]
        if m.startswith(REVIEW): return json.dumps({"pass": True, "relevance": 5, "issues": []})
        n = re.search(r"Headline: T(\d+)", m).group(1)
        return json.dumps({"title": "Test brief " + n, "eventDate": day, "summary": "Nothing with figures.", "source": {"name": "t", "url": ""}, "es": {"summary": "Nada con cifras."}})
    def fake_items(): return [{"feed": "Federal Reserve", "grade": "A", "title": "T%d" % i, "link": "https://example.test/%d" % i, "desc": "", "date": day} for i in range(4)], {}
    g.update(_http=fake_http, items=fake_items, get=lambda url, timeout=40: b"source text", validate=lambda b, today: {"ok": True, "errors": []}, KEY="selftest", SB_KEY="")
    time.sleep = lambda s: None; insight_ml.score = lambda t: t
    def run(draft, rev, pub):
        g["OUT"] = tempfile.mkdtemp(); g["MAX_PUBLISH"] = pub; LIMITS.update(draft=draft, review=rev); CALLS.update(draft=0, review=0); del BUDGET_HIT[:]; del sent[:]
        main()
        rd = lambda f: json.load(open(os.path.join(OUT, f)))
        return rd(day + ".json"), rd("live/briefs-live.json"), rd("audit-summary.json")["days"][day]
    rep, live, summ = run(16, 12, 5)      # normal run: everything fits
    assert len(rep["briefs"]) == 4 and len(live["briefs"]) == 4 and summ["published"] == 4 and not rep["budget"]["hit"], "normal run"
    assert len(sent) == 8 and rep["budget"]["calls"] == {"draft": 4, "review": 4}, "call count"
    rep, live, summ = run(2, 12, 5)       # writing budget of 2: two drafts, both fully checked and published, then a clean stop
    assert len(rep["briefs"]) == 2 and len(live["briefs"]) == 2 and len(sent) == 4 and rep["budget"]["hit"] and summ["last_run"]["hit"], "draft budget"
    rep, live, summ = run(16, 1, 5)       # editor budget of 1: only one draft is written, nothing unreviewed is published
    assert len(rep["briefs"]) == 1 and len(live["briefs"]) == 1 and sent.count(REVIEW_MODEL) == 1 and rep["budget"]["hit"], "review budget"
    rep, live, summ = run(0, 0, 5)        # zero budget: no request at all, files still written
    assert sent == [] and rep["briefs"] == [] and live["briefs"] == [] and rep["budget"]["hit"], "zero budget"
    rep, live, summ = run(16, 12, 0)      # SP_MAX_PUBLISH=0: drafts and audit written, nothing goes live
    assert len(rep["briefs"]) == 4 and live["briefs"] == [] and summ["published"] == 0 and summ["held_by_publish_limit"] == 4, "max publish 0"
    assert all(a.get("held") and not a.get("publishedAt") for a in rep["audit"]), "held marks"
    print("selftest ok")
if __name__ == "__main__":
    if "--selftest" in sys.argv: selftest()
    else: main()
