"""Render shareable 1080x1350 images (Instagram, TikTok, X) for recently published briefs, in English and Spanish.
Usage: python3 tools/social_cards.py <drafts_dir>. Writes <drafts_dir>/social/<date>/<id>-<lang>.png and captions.md."""
import json, os, sys, textwrap
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont

OUT = sys.argv[1] if len(sys.argv) > 1 else "d"
HERE = os.path.dirname(os.path.abspath(__file__))
F = lambda w, s: ImageFont.truetype(os.path.join(HERE, "fonts", f"Inter-{w}.otf"), s)
W, H, M = 1080, 1350, 84
BG, INK, DIM, MUTE, BLUE, UP, DOWN = (5, 6, 8), (255, 255, 255), (200, 204, 214), (130, 136, 150), (77, 116, 255), (61, 220, 132), (255, 107, 94)
L = {"en": {"src": "Source: ", "not": "Not investment advice", "who": "Who it affects", "imp": {"favorable": "▲", "adverse": "▼", "mixed": "◆", "undetermined": "○"}},
     "es": {"src": "Fuente: ", "not": "No es asesoría de inversión", "who": "A quién afecta", "imp": {"favorable": "▲", "adverse": "▼", "mixed": "◆", "undetermined": "○"}}}
MON = {"en": ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], "es": ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"]}

def wrap(draw, text, font, width, max_lines):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= width: cur = t
        else:
            lines.append(cur); cur = w
            if len(lines) == max_lines: break
    if len(lines) < max_lines and cur: lines.append(cur)
    if len(lines) == max_lines and " ".join(lines) != text.strip():
        while draw.textlength(lines[-1] + "…", font=font) > width: lines[-1] = lines[-1].rsplit(" ", 1)[0]
        lines[-1] += "…"
    return lines

def first_sentence(s):
    for sep in (". ", "; "):
        if sep in s: return s.split(sep)[0].rstrip(".") + "."
    return s

def card(b, lang):
    v = b if lang == "en" else {**b, **(b.get("es") or {})}
    im = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(im)
    # line motif: a thin rising line in the accent colour along the top band
    d.rectangle([M, 236, M + 120, 242], fill=BLUE)   # accent bar; no chart line, so the card never implies a direction the news does not state
    d.ellipse([M - 2, 72, M + 22, 96], outline=INK, width=3); d.ellipse([M + 6, 80, M + 14, 88], fill=BLUE)
    d.text((M + 36, 66), "SignalPoint", font=F("SemiBold", 34), fill=INK)
    dt = datetime.strptime(b["eventDate"], "%Y-%m-%d"); ds = f"{dt.day} {MON[lang][dt.month-1]} {dt.year}" if lang == "es" else f"{MON[lang][dt.month-1]} {dt.day}, {dt.year}"
    d.text((W - M - d.textlength(ds, font=F("Regular", 28)), 72), ds, font=F("Regular", 28), fill=MUTE)
    y = 300
    tf = F("Bold", 66)
    for ln in wrap(d, v["title"], tf, W - 2 * M, 5): d.text((M, y), ln, font=tf, fill=INK); y += 78
    y += 26
    sf = F("Regular", 34)
    for ln in wrap(d, first_sentence(v.get("summary", "")), sf, W - 2 * M, 4): d.text((M, y), ln, font=sf, fill=DIM); y += 48
    acts = (v.get("actors") or [])[:3]; base = b.get("actors") or []
    if acts and y < H - 380:
        y += 34; d.text((M, y), L[lang]["who"], font=F("SemiBold", 30), fill=MUTE); y += 52
        for i, a in enumerate(acts):
            imp = (base[i].get("impact") if i < len(base) else a.get("impact")) or "undetermined"
            col = UP if imp == "favorable" else DOWN if imp == "adverse" else MUTE
            d.text((M, y), L[lang]["imp"].get(imp, "○"), font=F("Bold", 32), fill=col)
            name = wrap(d, a.get("name", ""), F("SemiBold", 34), W - 2 * M - 52, 1)
            d.text((M + 52, y - 2), name[0] if name else "", font=F("SemiBold", 34), fill=INK); y += 56
            if y > H - 260: break
    d.line([(M, H - 170), (W - M, H - 170)], fill=(40, 44, 54), width=2)
    src = L[lang]["src"] + (b.get("source") or {}).get("name", "")
    d.text((M, H - 140), src, font=F("Regular", 28), fill=MUTE)
    d.text((M, H - 98), L[lang]["not"] + " · signalpoint", font=F("Regular", 26), fill=MUTE)
    return im

def caption(b, lang):
    v = b if lang == "en" else {**b, **(b.get("es") or {})}
    tags = "#markets #investing #economy" if lang == "en" else "#mercados #inversión #economía #Colombia"
    note = "Not investment advice." if lang == "en" else "No es asesoría de inversión."
    return f"{v['title']}\n\n{first_sentence(v.get('summary',''))}\n\n{note} {tags}"

def main():
    live = json.load(open(os.path.join(OUT, "live", "briefs-live.json")))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()
    done = 0
    sk = os.path.join(OUT, "social", "skip.json"); skip = set(json.load(open(sk))) if os.path.exists(sk) else set()
    for b in live.get("briefs", []):
        if b.get("eventDate", "") < cutoff or b["id"] in set(live.get("retracted") or []) or b["id"] in skip: continue
        folder = os.path.join(OUT, "social", b["eventDate"]); os.makedirs(folder, exist_ok=True)
        caps = os.path.join(folder, "captions.md")
        for lang in ("es", "en"):
            p = os.path.join(folder, f"{b['id'][:60]}-{lang}.png")
            if os.path.exists(p): continue
            card(b, lang).save(p, optimize=True); done += 1
            with open(caps, "a", encoding="utf-8") as f: f.write(f"## {os.path.basename(p)}\n\n{caption(b, lang)}\n\n")
    print("cards", done)

if __name__ == "__main__": main()
