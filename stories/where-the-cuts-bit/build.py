"""Assembles the story page: template + data snapshot + computed figures + the shared
banner, favicon, signup block and scripts lifted from an existing generated page.

Usage: python build.py <this folder> <docs/about.html> <docs/where-the-cuts-bit.html>
Reads template.html, snapshot.json and facts.json from this folder. Every {{name}} in the
template is filled from facts.json or from the pieces lifted out of about.html."""
import json, re, sys, datetime
S, about_path, out = sys.argv[1], sys.argv[2], sys.argv[3]
about = open(about_path, encoding="utf-8").read()
tpl = open(f"{S}/template.html", encoding="utf-8").read()
facts = json.load(open(f"{S}/facts.json", encoding="utf-8"))
snap = open(f"{S}/snapshot.json", encoding="utf-8").read()
D = json.loads(snap)
def grab(pat, flags=re.S):
    m = re.search(pat, about, flags); assert m, pat; return m
last = D["last_month"]; mon = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][int(last[5:]) - 1]
parts = {
 "FAVICON": grab(r'<link rel="icon"[^>]*>').group(0),
 "OG_IMAGE": grab(r'<meta property="og:image" content="([^"]+)"').group(1),
 "BANNER": grab(r'<header class="site" id="site">.*?</header>').group(0),
 "SIGNUP": grab(r'<aside class="signup" aria-labelledby="suTitle2">.*?</aside>').group(0),
 "MENU_JS": grab(r'<script>\s*\(function\(\)\{\s*var site=document.getElementById\("site"\).*?</script>').group(0),
 "SIGNUP_JS": grab(r'<script>\s*\(function\(\)\{\s*var URL="https://assets\.mailerlite\.com.*?</script>').group(0),
 "LOGO_SRC": grab(r'<footer class="colophon">\s*<span><img src="([^"]+)"').group(1),
 "DATA": snap, "GENERATED": D["generated"], "BUILT": datetime.date.today().isoformat(), "LAST": f"{mon} {last[:4]}",
}
missing = set()
def sub(m):
    k = m.group(1)
    if k in parts: return parts[k]
    if k in facts: return facts[k]
    missing.add(k); return m.group(0)
html = re.sub(r"\{\{(\w+)\}\}", sub, tpl)
assert not missing, missing
open(out, "w", encoding="utf-8", newline="\n").write(html)
print("built", out, len(html), "bytes; facts used:", len({k for k in re.findall(r"\{\{(\w+)\}\}", tpl) if k in facts}), "of", len(facts))
