"""Parse FOMC decision dates (last day of each meeting) from the Federal Reserve calendar pages fetched by fetch_history.py."""
import re, json, sys, os
from datetime import date
D = sys.argv[1] if len(sys.argv) > 1 else "fomc"
names = "January February March April May June July August September October November December".split()
M = {m: i + 1 for i, m in enumerate(names)}; M.update({m[:3]: i + 1 for i, m in enumerate(names)}); M["Sept"] = 9
out = set()
def add(y, mo, d):
    mo = mo.strip().split('/')[-1].strip(); d = d.replace('*', '').strip().split('-')[-1].strip()
    if mo in M and d.isdigit(): out.add(date(y, M[mo], int(d)))
for y in range(2000, 2021):
    p = os.path.join(D, f"{y}.html")
    if not os.path.exists(p): continue
    for h in re.findall(r'<h5[^>]*>(.*?)</h5>', open(p).read(), re.S):
        h = re.sub(r'<[^>]+>|\s+', ' ', h).strip()
        if 'Meeting' not in h or 'Conference' in h: continue
        h = h.split(' Meeting')[0].strip()
        m = re.match(r'([A-Za-z/]+)\s+\d+\s*-\s*([A-Za-z]+)\s+(\d+)$', h)
        if m: add(y, m.group(2), m.group(3)); continue
        m = re.match(r'([A-Za-z/]+)\s+([\d\-]+)', h)
        if m: add(y, m.group(1), m.group(2))
t = open(os.path.join(D, "current.html")).read()
for blk in re.split(r'<h4[^>]*>', t)[1:]:
    ym = re.search(r'(\d{4}) FOMC Meetings', blk)
    if not ym: continue
    y = int(ym.group(1))
    for mo, dd in re.findall(r'fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?fomc-meeting__date[^>]*>([^<]+)<', blk, re.S):
        if '(' in dd or 'notation' in dd.lower() or 'unscheduled' in dd.lower(): continue
        add(y, mo, dd)
ds = sorted(str(x) for x in out if x <= date.today())
json.dump(ds, open("fomc_dates.json", "w")); print(len(ds), "FOMC decisions")
