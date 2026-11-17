"""Add reviewed drafts to briefs.json. Usage: python3 tools/accept_drafts.py drafts.json ID [ID ...]
Each brief is validated again with quality.cjs; duplicates (same id or source URL) are skipped."""
import json, subprocess, sys
src, ids = sys.argv[1], sys.argv[2:]
drafts = {b["id"]: b for b in json.load(open(src))["briefs"]}
doc = json.load(open("briefs.json")); have = {b["id"] for b in doc["briefs"]}; urls = {b["source"]["url"] for b in doc["briefs"]}
for i in ids:
    b = drafts[i]
    if i in have or b["source"]["url"] in urls: print("skip duplicate", i); continue
    body = {k: v for k, v in b.items() if k != "id"}
    r = subprocess.run(["node", "-e", "const q=require('./quality.cjs');console.log(JSON.stringify(q.validateBrief(JSON.parse(require('fs').readFileSync(0,'utf8')))))"], input=json.dumps(body), capture_output=True, text=True)
    v = json.loads(r.stdout)
    if not v["ok"]: print("REJECTED", i, v["errors"]); continue
    doc["briefs"].insert(0, b); print("added", i)
json.dump(doc, open("briefs.json", "w"), ensure_ascii=False, indent=1)
