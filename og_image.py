"""Build the link-preview card for the dashboard and keep its meta tags in step.

Run after export.py:  python og_image.py

Reads docs/data/data.js and docs/data/meta.json, then
  1. draws docs/og-image.png (1200x627): headline, post count, job posts per
     full calendar year with the peak and the latest full year highlighted;
  2. updates the description, og:description, og:image:alt and og:image
     version tag in docs/index.html, so the text matches the new numbers and
     LinkedIn fetches the new image rather than its cached copy.

Use --no-html to draw the image only.
"""
import argparse
import hashlib
import io
import json
import re
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from PIL import Image

ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
FONTS = ROOT / "assets" / "fonts"
URL = "https://trendlines.curinta.com/"

W, H = 1200, 627
BG, INK, MUTED, ACCENT, SOFT, LINE = "#F5F7FA", "#1E242C", "#6F7885", "#408ADE", "#B9D3F1", "#E2E7EE"


def load_data():
    s = (DOCS / "data" / "data.js").read_text(encoding="utf-8")
    d = json.loads(s[s.index("{"): s.rindex("}") + 1])
    meta = json.loads((DOCS / "data" / "meta.json").read_text(encoding="utf-8"))
    per_year, months_in_year = defaultdict(int), defaultdict(int)
    for m, n in zip(d["totals"]["months"], d["totals"]["jobs"]):
        per_year[int(m[:4])] += n
        months_in_year[int(m[:4])] += 1
    # Full calendar years only, so a partial first or last year doesn't read as a drop.
    years = sorted(y for y, k in months_in_year.items() if k == 12)
    return {
        "years": years,
        "posts": [per_year[y] for y in years],
        "total": meta["total_jobs"],
        "first_year": int(meta["first_month"][:4]),
        "n_topics": len(d["topics"]["topics"]),
        "generated": meta.get("generated", ""),
        "gaps": meta.get("possible_gaps", []),
    }


def fmt_k(n):
    return f"{round(n / 1000):,}k"


def draw(v, out):
    for f in FONTS.glob("Poppins-*.ttf"):
        font_manager.fontManager.addfont(str(f))
    plt.rcParams["font.family"] = "Poppins"

    years, posts = v["years"], v["posts"]
    peak = years[posts.index(max(posts))]
    latest = years[-1]
    marked = {peak, latest}

    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor(BG)
    t = lambda x, y, s, **kw: fig.text(x / W, 1 - y / H, s, va="baseline", **kw)
    t(64, 150, "A lens on the", fontsize=40, weight="bold", color=INK)
    t(64, 205, "humanitarian sector", fontsize=40, weight="bold", color=ACCENT)
    t(64, 252, f"{v['total']:,} ReliefWeb job posts since {v['first_year']}, "
               f"tagged against {v['n_topics']} topics", fontsize=17, color=MUTED)
    t(64, 300, f"Job posts per year, {years[0]}–{latest}", fontsize=13, color=MUTED, weight="medium")

    ax = fig.add_axes([64 / W, 70 / H, (W - 128) / W, 250 / H])
    ax.set_facecolor(BG)
    x = range(len(years))
    ax.bar(x, posts, width=0.72, color=[ACCENT if y in marked else SOFT for y in years])
    for y in marked:
        k = years.index(y)
        ax.text(k, posts[k] + max(posts) * 0.03, fmt_k(posts[k]), ha="center", va="bottom",
                fontsize=15, weight="bold", color=INK)
    # Label every other year plus the latest, skipping the one that would crowd it.
    labels = [str(y) if y == latest or ((latest - y) % 2 == 0 and latest - y > 1) else "" for y in years]
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, fontsize=13, color=MUTED)
    ax.tick_params(length=0)
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.axhline(0, color=LINE, lw=1.5)
    ax.set_ylim(0, max(posts) * 1.18)
    fig.text((W - 64) / W, 24 / H, URL.split("//")[1].rstrip("/"), fontsize=14, color=INK,
             ha="right", weight="medium")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, facecolor=BG)
    plt.close(fig)
    buf.seek(0)
    im = Image.open(buf).convert("RGB")
    logo = Image.open(DOCS / "curinta-logo.png").convert("RGBA")
    lw = 170
    logo = logo.resize((lw, round(logo.height * lw / logo.width)), Image.LANCZOS)
    im.paste(logo, (W - 64 - lw, 40), logo)
    im.save(out, optimize=True)
    return peak, latest


def update_html(v, peak, latest):
    path = DOCS / "index.html"
    with open(path, encoding="utf-8", newline="") as f:
        html = f.read()
    posts = dict(zip(v["years"], v["posts"]))
    total_floor = f"{v['total'] // 1000:,},000+"
    desc = (f"A lens on the humanitarian sector: how its priorities shift over time, read from {total_floor} "
            f"ReliefWeb job posts since {v['first_year']}, tagged against {v['n_topics']} topics and tracked by organisation.")
    alt = (f"Bar chart of ReliefWeb job posts per year, {v['years'][0]} to {latest}, "
           f"peaking at {round(posts[peak], -3):,} in {peak}"
           + (f", with {round(posts[latest], -3):,} in {latest}" if latest != peak else ""))
    image = f"{URL}og-image.png?v={v['generated'].replace('-', '')}-{hashlib.sha1((DOCS / 'og-image.png').read_bytes()).hexdigest()[:6]}"
    swaps = [
        (r'(<meta name="description" content=")[^"]*', desc),
        (r'(<meta property="og:description" content=")[^"]*', desc),
        (r'(<meta property="og:image:alt" content=")[^"]*', alt),
        (r'(<meta property="og:image" content=")[^"]*', image),
    ]
    for pattern, value in swaps:
        html, n = re.subn(pattern, lambda m: m.group(1) + value, html, count=1)
        if not n:
            raise SystemExit(f"index.html: no tag matching {pattern!r}; add the link-preview tags first.")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(html)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-html", action="store_true", help="draw the image only")
    args = ap.parse_args()

    v = load_data()
    out = DOCS / "og-image.png"
    peak, latest = draw(v, out)
    print(f"Wrote {out.relative_to(ROOT)}: {v['years'][0]}–{latest}, peak {peak}")
    for g in v["gaps"]:
        if int(g["month"][:4]) in v["years"]:
            print(f"  Caution: {g['month']} looks low ({g['jobs']:,} posts vs a typical "
                  f"{g['neighbour_median']:,}), so {g['month'][:4]} may be undercounted.")
    if not args.no_html:
        update_html(v, peak, latest)
        print("Updated link-preview tags in docs/index.html")
    print(f"After pushing, refresh LinkedIn's copy: https://www.linkedin.com/post-inspector/ ({URL})")


if __name__ == "__main__":
    main()
