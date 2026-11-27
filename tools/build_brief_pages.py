"""One static, indexable page per published brief (Spanish and English), the two brief indexes and sitemap.xml.

Input is the robot's data (branch `drafts`): live/briefs-live.json, optionally retracted.json and the dated run files
(<date>.json, which keep every brief that was ever published, with its publishedAt). Output goes into a copy of the site:
  brief/<id>/index.html        Spanish page        en/brief/<id>/index.html   English page
  brief/index.html             Spanish index       en/brief/index.html        English index
  brief/brief.css              shared stylesheet   sitemap.xml                static entries kept + every brief page
Retracted briefs that were published get a short "this brief was withdrawn" page (noindex, no brief text, not in the sitemap).
The brief text is AI-written from RSS sources: everything from the JSON is treated as untrusted and HTML-escaped.
Python 3 standard library only; no network, no model calls.

  python3 tools/build_brief_pages.py --live briefs-live.json [--retracted retracted.json] [--archive DIR] --site _site
"""
import argparse, glob, html, json, os, re, sys
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

BASE = "https://martinfgaleano-crypto.github.io/signalpoint/"   # the ONE place to change when the domain changes
SITE = "SignalPoint"
ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]{0,90}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SM_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"

MONTHS_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# Labels as the home page words them (index.html: paper(), UI_ES, footer).
CAT_ES = {"Macro data": "Datos macro", "Central banks": "Bancos centrales", "Corporate": "Empresas", "Other": "Otros",
          "Earnings": "Resultados", "Geopolitics": "Geopolítica", "Regulation": "Regulación", "Commodities": "Materias primas",
          "Markets": "Mercados", "M&A": "Fusiones y adquisiciones"}
REGION_ES = {"US": "EE. UU.", "US / Global": "EE. UU. / Global", "US / China": "EE. UU. / China", "UK": "Reino Unido",
             "Global": "Global", "Colombia": "Colombia"}
GRADE = {"en": {"A": "A · primary document", "B": "B · reported by press", "C": "C · single unconfirmed report"},
         "es": {"A": "A · documento primario", "B": "B · reportado por prensa", "C": "C · un solo reporte sin confirmar"}}
IMP = {"favorable": ("fav", "▲", "Favorable", "Favorable"), "adverse": ("adv", "▼", "Adverse", "Desfavorable"),
       "mixed": ("mix", "◆", "Mixed", "Mixto"), "undetermined": ("und", "○", "Undetermined", "Indeterminado")}
STATUS = {"observed": ("✓ Observed", "✓ Observado"), "not_observed": ("✕ Not observed", "✕ No observado"),
          "inconclusive": ("Inconclusive", "No concluyente")}
L = {
 "en": dict(home="Home", all="All briefs", glossary="Glossary (Spanish)", other="Leer en español", event="Event date",
            published="Published", impact="Impact by actor", watch="What to watch · observable follow-ups",
            unknown="What we do not know", source="Source:", evidence="Evidence", none_actor="No actor could be assessed from the source.",
            none_watch="None stated.", none_unk="Nothing flagged.", by="by",
            legend="▲ favorable · ▼ adverse · ◆ mixed · ○ undetermined: the effect on that actor through the channel described, not a call on its share price.",
            grades="A: the primary document was read. B: press reporting with attribution. C: a single unconfirmed report.",
            ai="Written with AI from the cited source and checked by an automatic editor; audited afterwards.",
            disclaimer="SignalPoint reads market events and states who is affected, what would confirm or refute the reading, and what is still unknown. Briefs are generated with AI from the cited sources and can be wrong. Nothing here is investment advice or a recommendation to buy or sell any security.",
            idx_title="All briefs", idx_lead="Every brief SignalPoint has published, newest first. Each one says what happened, who is exposed, what to watch and what is not known, with the source one click away.",
            idx_desc="Every SignalPoint brief, newest first: market and economic events in plain words, with the source and an evidence grade.",
            retracted_h="This brief was withdrawn", retracted_p="SignalPoint withdrew this brief after publishing it, and its text is no longer shown.",
            retracted_when="Withdrawn", not_recorded="date not recorded", reason="Reason", retracted_list="Withdrawn briefs",
            retracted_item="Brief of {d}, withdrawn", read="Read the brief", latest="Latest briefs on the home page"),
 "es": dict(home="Inicio", all="Todas las notas", glossary="Glosario", other="Read in English", event="Fecha del evento",
            published="Publicada", impact="Impacto por actor", watch="Qué vigilar · seguimientos observables",
            unknown="Lo que no sabemos", source="Fuente:", evidence="Evidencia", none_actor="No se pudo evaluar ningún actor a partir de la fuente.",
            none_watch="Nada indicado.", none_unk="Nada señalado.", by="hasta el",
            legend="▲ favorable · ▼ desfavorable · ◆ mixto · ○ indeterminado: el efecto sobre ese actor por el canal descrito, no una predicción del precio de su acción.",
            grades="A: se leyó el documento original. B: prensa que cita su fuente. C: un solo reporte sin confirmar.",
            ai="Redactada con IA a partir de la fuente citada y revisada por un editor automático; se audita después.",
            disclaimer="SignalPoint lee los eventos de mercado y dice a quién afectan, qué confirmaría o refutaría la lectura y qué no se sabe todavía. Las noticias se generan con IA a partir de las fuentes citadas y pueden tener errores. Nada aquí es asesoría de inversión ni una recomendación de comprar o vender ningún valor.",
            idx_title="Todas las notas", idx_lead="Cada nota que SignalPoint ha publicado, de la más reciente a la más antigua. Cada una dice qué pasó, quién está expuesto, qué vigilar y qué no se sabe, con la fuente a un clic.",
            idx_desc="Todas las notas de SignalPoint, de la más reciente a la más antigua: eventos del mercado y la economía en palabras simples, con la fuente y un nivel de evidencia.",
            retracted_h="Esta nota fue retirada", retracted_p="SignalPoint retiró esta nota después de publicarla y ya no muestra su texto.",
            retracted_when="Retirada", not_recorded="fecha no registrada", reason="Motivo", retracted_list="Notas retiradas",
            retracted_item="Nota del {d}, retirada", read="Leer la nota", latest="Últimas notas en la página principal"),
}

def e(s): return html.escape("" if s is None else str(s), quote=True)
def txt(v, n=2000):
    """Plain text from an untrusted value: str only, control characters removed, length-capped."""
    if not isinstance(v, str): return ""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", v).strip()[:n]
def safe_url(u):
    u = txt(u, 600)
    return u if re.match(r"^https?://[^\s\"'<>]+$", u) else ""
def day(iso):
    d = txt(iso, 40)[:10]
    return d if DATE_RE.match(d) else ""
def fmt(iso, lang):
    d = day(iso)
    if not d: return ""
    y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10])
    return "%d %s %d" % (dd, MONTHS_ES[m - 1], y) if lang == "es" else "%s %d, %d" % (MONTHS_EN[m - 1], dd, y)
def clip(s, n):
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) <= n: return s
    cut = s[:n - 1].rsplit(" ", 1)[0].rstrip(",.;:")
    return cut + "…"
def jsonld(obj):
    # json.dumps, then neutralise characters that could close the <script> element.
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
def path_for(lang, bid=None):
    p = ("en/" if lang == "en" else "") + "brief/"
    return p + (bid + "/" if bid else "")

def load_json(p, default):
    if not p or not os.path.exists(p): return default
    try:
        with open(p, encoding="utf-8") as f: return json.load(f)
    except Exception as ex:
        print("warning: cannot read %s: %r" % (p, ex), file=sys.stderr); return default

def retracted_map(raw):
    """retracted.json is a list of ids today; also accept [{id, date, reason}] or {id: {date, reason}} for later."""
    out = {}
    items = raw.items() if isinstance(raw, dict) else ((x, None) for x in raw) if isinstance(raw, list) else []
    for k, v in items:
        if isinstance(k, dict): k, v = k.get("id"), k
        if isinstance(k, str) and ID_RE.match(k):
            v = v if isinstance(v, dict) else {}
            out[k] = {"date": day(v.get("date")), "reason": txt(v.get("reason"), 400)}
    return out

def valid_brief(b):
    if not isinstance(b, dict) or not isinstance(b.get("id"), str) or not ID_RE.match(b["id"]): return False
    return bool(txt(b.get("title")) and txt(b.get("summary")) and isinstance(b.get("source"), dict))

def collect(live, archive_dir, retracted):
    """Published briefs: the live list first, then any brief the dated run files show as published (publishedAt) that
    has since left the live window, so its address keeps working. Retracted ids are split out."""
    pub_at, arch = {}, {}
    for p in sorted(glob.glob(os.path.join(archive_dir, "*.json"))) if archive_dir else []:
        if not re.match(r"^\d{4}-\d{2}-\d{2}\.json$", os.path.basename(p)): continue
        d = load_json(p, {})
        if not isinstance(d, dict): continue
        for a in d.get("audit") or []:
            if isinstance(a, dict) and isinstance(a.get("id"), str) and txt(a.get("publishedAt"), 40):
                pub_at.setdefault(a["id"], txt(a.get("publishedAt"), 40))
        for b in d.get("briefs") or []:
            if valid_brief(b): arch[b["id"]] = b   # files are read oldest first, so the newest copy of a brief wins
    briefs, seen = [], set()
    for b in (live.get("briefs") or []) if isinstance(live, dict) else []:
        if valid_brief(b) and b["id"] not in seen and b["id"] not in retracted:
            seen.add(b["id"]); briefs.append(b)
    for i, b in arch.items():
        if i in pub_at and i not in seen and i not in retracted:
            seen.add(i); briefs.append(b)
    for b in briefs:
        b["_pub"] = pub_at.get(b["id"]) or b["id"][:10]
    gone = []
    for i, r in retracted.items():
        b = next((x for x in (live.get("briefs") or []) if isinstance(x, dict) and x.get("id") == i), None) if isinstance(live, dict) else None
        if b is None and i in arch and i in pub_at: b = arch[i]
        if b is None: continue                       # never published or no data: no page
        gone.append({"id": i, "pub": pub_at.get(i) or i[:10], "event": day(b.get("eventDate")), "date": r["date"], "reason": r["reason"]})
    briefs.sort(key=lambda b: (b["_pub"][:10], day(b.get("eventDate")), b["id"]), reverse=True)
    gone.sort(key=lambda g: g["pub"], reverse=True)
    return briefs, gone

def view(b, lang):
    """The language-specific public fields of a brief (never the Pro `insights`)."""
    es = b.get("es") if isinstance(b.get("es"), dict) else {}
    loc = es if lang == "es" else {}
    def pick(k, n=4000): return txt(loc.get(k), n) or txt(b.get(k), n)
    actors = []
    base_a = b.get("actors") if isinstance(b.get("actors"), list) else []
    loc_a = loc.get("actors") if isinstance(loc.get("actors"), list) else []
    for i, a in enumerate(base_a[:12]):
        if not isinstance(a, dict): continue
        la = loc_a[i] if i < len(loc_a) and isinstance(loc_a[i], dict) else {}
        actors.append({"name": txt(la.get("name"), 200) or txt(a.get("name"), 200), "ticker": txt(a.get("ticker"), 20),
                       "impact": a.get("impact") if a.get("impact") in IMP else "undetermined",
                       "reason": txt(la.get("reason"), 1000) or txt(a.get("reason"), 1000)})
    watch = []
    base_w = b.get("watch") if isinstance(b.get("watch"), list) else []
    loc_w = loc.get("watch") if isinstance(loc.get("watch"), list) else []
    for i, w in enumerate(base_w[:12]):
        if not isinstance(w, dict): continue
        lw = loc_w[i] if i < len(loc_w) and isinstance(loc_w[i], dict) else {}
        st = w.get("status"); st = "observed" if st == "confirmed" else "not_observed" if st == "refuted" else st
        watch.append({"text": txt(lw.get("text"), 600) or txt(w.get("text"), 600),
                      "note": txt(lw.get("outcome") or lw.get("note"), 600) or txt(w.get("outcome") or w.get("note"), 600),
                      "due": day(w.get("due")), "status": st if st in STATUS else "open"})
    unk_src = loc.get("unknowns") if isinstance(loc.get("unknowns"), list) and loc.get("unknowns") else b.get("unknowns")
    unknowns = [txt(u, 600) for u in (unk_src if isinstance(unk_src, list) else [])[:12] if txt(u, 600)]
    src = b.get("source") if isinstance(b.get("source"), dict) else {}
    cat, reg = txt(b.get("category"), 60), txt(b.get("region"), 60)
    return {"title": pick("title", 300), "summary": pick("summary"), "actors": actors, "watch": watch, "unknowns": unknowns,
            "cat": CAT_ES.get(cat, cat) if lang == "es" else cat, "region": REGION_ES.get(reg, reg) if lang == "es" else reg,
            "grade": b.get("evidence") if b.get("evidence") in ("A", "B", "C") else "",
            "src_name": txt(src.get("name"), 120), "src_url": safe_url(src.get("url")), "event": day(b.get("eventDate"))}

def head(lang, title, desc, canon, alt, css, noindex=False, og_type="website", extra=""):
    h = ['<!DOCTYPE html><html lang="%s"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' % lang,
         "<title>%s</title>" % e(title), '<meta name="description" content="%s">' % e(desc)]
    if noindex: h.append('<meta name="robots" content="noindex">')
    else:
        h.append('<link rel="canonical" href="%s">' % e(canon))
        if alt:
            h.append('<link rel="alternate" hreflang="es" href="%s"><link rel="alternate" hreflang="en" href="%s"><link rel="alternate" hreflang="x-default" href="%s">' % (e(alt["es"]), e(alt["en"]), e(alt["es"])))
        h.append('<meta property="og:type" content="%s"><meta property="og:site_name" content="%s"><meta property="og:title" content="%s"><meta property="og:description" content="%s"><meta property="og:url" content="%s"><meta property="og:image" content="%s"><meta property="og:locale" content="%s">' % (
            og_type, SITE, e(title), e(desc), e(canon), e(BASE + "og.png"), "es_CO" if lang == "es" else "en_US"))
        h.append('<meta name="twitter:card" content="summary_large_image">')
    h.append('<link rel="icon" href="%sicon-192.png"><meta name="theme-color" content="#2F5BFF"><link rel="stylesheet" href="%sbrief/brief.css">' % (css, css))
    return "".join(h) + extra + "</head><body>"

def topbar(lang, root, other_href):
    o = '<a class="lang" href="%s" hreflang="%s">%s</a>' % (e(other_href), "es" if lang == "en" else "en", e(L[lang]["other"])) if other_href else ""
    return '<header><a class="brand" href="%s">SignalPoint</a>%s</header><main>' % (e(root + ("?lang=en" if lang == "en" else "")), o)

def foot(lang, root):
    t = L[lang]
    return ('</main><footer><p class="flinks"><a href="%s">%s</a> · <a href="%s">%s</a> · <a href="%sglosario/">%s</a></p>%s</footer></body></html>'
            % (e(root + ("?lang=en" if lang == "en" else "")), t["home"], e(root + path_for(lang)), t["all"], root, t["glossary"], e(t["disclaimer"])))

def brief_page(b, lang):
    t, v, bid = L[lang], view(b, lang), b["id"]
    root = "../../../" if lang == "en" else "../../"
    url = BASE + path_for(lang, bid)
    alt = {"es": BASE + path_for("es", bid), "en": BASE + path_for("en", bid)}
    other = root + path_for("es" if lang == "en" else "en", bid)
    desc = clip(v["summary"], 155)
    pub = b["_pub"]
    ld = {"@context": "https://schema.org", "@type": "NewsArticle", "headline": clip(v["title"], 110), "description": desc,
          "datePublished": pub, "dateModified": pub, "inLanguage": lang, "url": url, "mainEntityOfPage": url,
          "image": [BASE + "og.png"], "isAccessibleForFree": True,
          "author": {"@type": "Organization", "name": SITE, "url": BASE},
          "publisher": {"@type": "Organization", "name": SITE, "url": BASE, "logo": {"@type": "ImageObject", "url": BASE + "icon-512.png"}}}
    if v["src_url"]: ld["citation"] = {"@type": "CreativeWork", "name": v["src_name"] or v["src_url"], "url": v["src_url"]}
    extra = ('<meta property="article:published_time" content="%s">' % e(pub)) + '<script type="application/ld+json">' + jsonld(ld) + "</script>"
    out = [head(lang, v["title"] + " | " + SITE, desc, url, alt, root, og_type="article", extra=extra), topbar(lang, root, other)]
    meta = [x for x in (v["cat"], v["region"]) if x]
    out.append('<article><p class="k">%s</p><h1>%s</h1>' % (" · ".join(e(x) for x in meta), e(v["title"])))
    dates = []
    if v["event"]: dates.append('%s: <time datetime="%s">%s</time>' % (t["event"], v["event"], fmt(v["event"], lang)))
    dates.append('%s: <time datetime="%s">%s</time>' % (t["published"], e(pub[:10]), fmt(pub, lang)))
    out.append('<p class="dates">%s</p>' % " · ".join(dates))
    if v["grade"]: out.append('<p class="grade"><b>%s %s</b><span>%s</span></p>' % (t["evidence"], e(GRADE[lang][v["grade"]]), e(t["grades"])))
    out.append('<p class="lede">%s</p>' % e(v["summary"]))
    out.append('<section><h2>%s</h2><p class="note">%s</p>' % (t["impact"], e(t["legend"])))
    if v["actors"]:
        out.append('<ul class="actors">')
        for a in v["actors"]:
            i = IMP[a["impact"]]
            out.append('<li><p class="who">%s%s <span class="imp %s">%s %s</span></p><p>%s</p></li>' % (
                e(a["name"]), (' <span class="tk">%s</span>' % e(a["ticker"])) if a["ticker"] else "", i[0], i[1], i[3] if lang == "es" else i[2], e(a["reason"])))
        out.append("</ul>")
    else: out.append('<p class="note">%s</p>' % t["none_actor"])
    out.append('</section><section><h2>%s</h2><ul class="watch">' % t["watch"])
    for w in v["watch"]:
        st = ('<span class="st">%s</span> ' % STATUS[w["status"]][1 if lang == "es" else 0]) if w["status"] != "open" else ""
        due = (' <span class="due">%s %s</span>' % (t["by"], fmt(w["due"], lang))) if w["due"] else ""
        out.append("<li>%s%s%s%s</li>" % (st, e(w["text"]), due, ('<br><span class="note">%s</span>' % e(w["note"])) if w["note"] else ""))
    if not v["watch"]: out.append('<li class="note">%s</li>' % t["none_watch"])
    out.append('</ul></section><section><h2>%s</h2><ul class="unk">' % t["unknown"])
    out.append("".join("<li>%s</li>" % e(u) for u in v["unknowns"]) or '<li class="note">%s</li>' % t["none_unk"])
    out.append("</ul></section>")
    src = ('<a href="%s" rel="noopener noreferrer" target="_blank">%s</a>' % (e(v["src_url"]), e(v["src_name"] or v["src_url"]))) if v["src_url"] else e(v["src_name"])
    out.append('<p class="src">%s %s</p><p class="note">%s</p></article>' % (t["source"], src, e(t["ai"])))
    out.append('<p class="more"><a href="%s">%s</a> · <a href="%s">%s</a></p>' % (e(root + path_for(lang)), t["all"], e(root + ("?lang=en" if lang == "en" else "") + "#briefing"), t["latest"]))
    out.append(foot(lang, root))
    return "".join(out)

def retracted_page(g, lang):
    t = L[lang]
    root = "../../../" if lang == "en" else "../../"
    other = root + path_for("es" if lang == "en" else "en", g["id"])
    out = [head(lang, t["retracted_h"] + " | " + SITE, t["retracted_p"], "", None, root, noindex=True), topbar(lang, root, other)]
    out.append('<article class="gone"><p class="k">%s</p><h1>%s</h1><p class="lede">%s</p><p class="dates">' % (t["retracted_when"].upper(), t["retracted_h"], t["retracted_p"]))
    bits = ["%s: %s" % (t["published"], fmt(g["pub"], lang))]
    bits.append("%s: %s" % (t["retracted_when"], fmt(g["date"], lang) if g["date"] else t["not_recorded"]))
    out.append(" · ".join(bits) + "</p>")
    if g["reason"]: out.append('<p><b>%s:</b> %s</p>' % (t["reason"], e(g["reason"])))
    out.append("</article>" + foot(lang, root))
    return "".join(out)

def index_page(briefs, gone, lang):
    t = L[lang]
    root = "../../" if lang == "en" else "../"
    url = BASE + path_for(lang)
    alt = {"es": BASE + path_for("es"), "en": BASE + path_for("en")}
    ld = {"@context": "https://schema.org", "@type": "CollectionPage", "name": t["idx_title"], "url": url, "inLanguage": lang,
          "publisher": {"@type": "Organization", "name": SITE, "url": BASE}}
    out = [head(lang, t["idx_title"] + " | " + SITE, t["idx_desc"], url, alt, root, extra='<script type="application/ld+json">' + jsonld(ld) + "</script>"),
           topbar(lang, root, root + path_for("es" if lang == "en" else "en"))]
    out.append('<p class="k">SIGNALPOINT</p><h1>%s</h1><p class="lede">%s</p><ol class="list">' % (t["idx_title"], e(t["idx_lead"])))
    for b in briefs:
        v = view(b, lang)
        href = b["id"] + "/"
        out.append('<li><p class="dates"><time datetime="%s">%s</time>%s</p><h2><a href="%s">%s</a></h2><p>%s</p></li>' % (
            e(b["_pub"][:10]), fmt(b["_pub"], lang), (" · " + e(v["cat"])) if v["cat"] else "", e(href), e(v["title"]), e(clip(v["summary"], 120))))
    out.append("</ol>")
    if gone:
        out.append('<h2 class="sub">%s</h2><ul class="gonelist">' % t["retracted_list"])
        for g in gone:
            out.append('<li><a href="%s" rel="nofollow">%s</a></li>' % (e(g["id"] + "/"), e(t["retracted_item"].format(d=fmt(g["pub"], lang)))))
        out.append("</ul>")
    out.append(foot(lang, root))
    return "".join(out)

CSS = """:root{--ink:#111;--muted:#5B6478;--line:#E3E7F0;--accent:#2F5BFF;--bg:#FAFAFA;--card:#fff;--fav:#1F9D55;--adv:#D93025;--mix:#B7791F;--und:#6E6E73}
body{font:17px/1.65 Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;color:var(--ink);background:var(--bg)}
header{background:#000;color:#fff;padding:14px 20px;display:flex;justify-content:space-between;align-items:center;gap:12px}
header a{color:#fff;text-decoration:none}.brand{font-weight:700}.lang{font-size:.85rem;opacity:.85}
main{max-width:720px;margin:0 auto;padding:28px 20px 48px}h1{font-size:1.9rem;line-height:1.18;margin:.25em 0 .4em;overflow-wrap:anywhere}
h2{font-size:1.15rem;margin:1.8em 0 .5em}.k{font-size:.8rem;font-weight:700;color:var(--accent);letter-spacing:.02em;margin:0}
.dates,.note{font-size:.85rem;color:var(--muted)}.lede{font-size:1.12rem}
.grade{background:var(--card);border:2px solid var(--line);border-radius:14px;padding:10px 14px;font-size:.9rem;display:flex;flex-direction:column;gap:2px}
.grade span{color:var(--muted);font-size:.82rem}
ul.actors,ul.watch,ul.unk,ol.list,ul.gonelist{padding:0;list-style:none;margin:0}
ul.actors li,ul.watch li,ol.list li{background:var(--card);border:2px solid var(--line);border-bottom-width:4px;border-radius:14px;padding:12px 16px;margin:10px 0}
ul.actors p{margin:.2em 0}.who{font-weight:700}.tk{font-size:.8rem;color:var(--muted);font-weight:600}
.imp{font-size:.8rem;font-weight:700;white-space:nowrap;margin-left:4px}.imp.fav{color:var(--fav)}.imp.adv{color:var(--adv)}.imp.mix{color:var(--mix)}.imp.und{color:var(--und)}
.due{font-size:.82rem;color:var(--muted);white-space:nowrap}.st{font-weight:700}
ul.unk li{padding-left:1.1em;position:relative;margin:.4em 0}ul.unk li:before{content:"?";position:absolute;left:0;color:var(--accent);font-weight:700}
.src{margin-top:2em;padding-top:1em;border-top:2px solid var(--line);overflow-wrap:anywhere}
ol.list h2{font-size:1.05rem;margin:.1em 0 .3em;line-height:1.3}ol.list p{margin:.2em 0}ol.list li>p:last-child{font-size:.95rem}
h2.sub{font-size:1rem;color:var(--muted)}ul.gonelist li{margin:.3em 0;font-size:.9rem}
a{color:var(--accent)}ol.list h2 a{color:var(--ink);text-decoration:none}ol.list h2 a:hover{color:var(--accent);text-decoration:underline}
.more{margin-top:1.6em}footer{font-size:.8rem;color:var(--muted);max-width:720px;margin:0 auto;padding:0 20px 40px}
@media (prefers-color-scheme:dark){:root{--ink:#F2F2F5;--muted:#A1A1AA;--line:#2C2C33;--bg:#111114;--card:#1A1A1F;--accent:#7C9BFF}ol.list h2 a{color:var(--ink)}}
"""

def write(p, s):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f: f.write(s)

def sitemap(site, briefs):
    p = os.path.join(site, "sitemap.xml")
    keep = []
    if os.path.exists(p):
        try:
            root = ET.parse(p).getroot()
            for u in root.findall("{%s}url" % SM_NS):
                loc = (u.findtext("{%s}loc" % SM_NS) or "").strip()
                if not loc or loc.startswith(BASE + "brief/") or loc.startswith(BASE + "en/brief/"): continue   # regenerated below
                keep.append((loc, (u.findtext("{%s}lastmod" % SM_NS) or "").strip()))
        except ET.ParseError as ex:
            print("warning: existing sitemap.xml unreadable (%r); writing brief entries only" % ex, file=sys.stderr)
    newest = briefs[0]["_pub"][:10] if briefs else ""
    entries = keep + [(BASE + path_for(l), newest) for l in ("es", "en")]
    for b in briefs:
        for l in ("es", "en"): entries.append((BASE + path_for(l, b["id"]), b["_pub"][:10]))
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="%s">' % SM_NS]
    for loc, lm in entries:
        lines.append("<url><loc>%s</loc>%s</url>" % (html.escape(loc, quote=False), ("<lastmod>%s</lastmod>" % lm) if DATE_RE.match(lm or "") else ""))
    lines.append("</urlset>")
    write(p, "\n".join(lines) + "\n")
    return len(entries)

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", required=True, help="path to live/briefs-live.json")
    ap.add_argument("--retracted", help="path to retracted.json (list of ids)")
    ap.add_argument("--archive", help="directory with the dated run files <date>.json (keeps briefs that left the live list)")
    ap.add_argument("--site", required=True, help="site directory to write into (a copy of main)")
    a = ap.parse_args(argv)
    live = load_json(a.live, None)
    if not isinstance(live, dict) or not isinstance(live.get("briefs"), list):
        print("error: %s is not a briefs-live.json" % a.live, file=sys.stderr); return 2
    ret = retracted_map(load_json(a.retracted, []))
    ret.update({k: v for k, v in retracted_map(live.get("retracted") or []).items() if k not in ret})
    briefs, gone = collect(live, a.archive, ret)
    write(os.path.join(a.site, "brief", "brief.css"), CSS)
    for b in briefs:
        for l in ("es", "en"): write(os.path.join(a.site, path_for(l, b["id"]), "index.html"), brief_page(b, l))
    for g in gone:
        for l in ("es", "en"): write(os.path.join(a.site, path_for(l, g["id"]), "index.html"), retracted_page(g, l))
    for l in ("es", "en"): write(os.path.join(a.site, path_for(l), "index.html"), index_page(briefs, gone, l))
    n = sitemap(a.site, briefs)
    print("brief pages: %d es + %d en; retracted pages: %d es + %d en; sitemap URLs: %d" % (len(briefs), len(briefs), len(gone), len(gone), n))
    return 0

if __name__ == "__main__":
    sys.exit(main())
