"""Write the bold-home preview to site/nuevo/index.html: same app, with a base href so data paths resolve, and noindex."""
import os
src = open("site/index.html", encoding="utf-8").read()
src = src.replace("<head>", '<head>\n<base href="/signalpoint/">\n<meta name="robots" content="noindex">', 1)
os.makedirs("site/nuevo", exist_ok=True)
open("site/nuevo/index.html", "w", encoding="utf-8").write(src)
print("site/nuevo/index.html", len(src))
