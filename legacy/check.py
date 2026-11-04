"""
Spot-check a topic: print random matching jobs and WHY they matched.

  python check.py Biometrics                 # 20 random matches
  python check.py "Gender" 40                # 40 matches
  python check.py "Gender" 30 --body         # only jobs matched in the description, not the title
  python check.py                            # list topic names

T = matched in the title (the title is shown); B = description only (the matching text is shown).
Count how many are genuinely about the topic. Aim for 16+ out of 20; if lower, tighten
patterns or add an exclude in topics.csv, then re-run match.py.
"""
import csv
import re
import sys

import duckdb

args = [a for a in sys.argv[1:] if not a.startswith("--")]
body_only = "--body" in sys.argv
topic = args[0] if args else None
n = int(args[1]) if len(args) > 1 else 20

con = duckdb.connect("reliefweb_jobs.duckdb", read_only=True)
if not topic:
    print("Topics:\n" + "\n".join(r[0] for r in con.execute("SELECT concept FROM concepts ORDER BY 1").fetchall()))
    sys.exit()

# Rebuild the topic's patterns exactly as match.py uses them
rows = [r for r in csv.DictReader(open("topics.csv", encoding="utf-8-sig")) if r["topic"].lower() == topic.lower()]
if not rows:
    sys.exit(f"No topic called {topic!r} in topics.csv - run 'python check.py' to list them")
rules = []
for r in rows:
    try:
        pat = re.compile(r["pattern"], 0 if r["case_sensitive"].strip() == "1" else re.I)
        exc = re.compile(r["exclude"], re.I) if r.get("exclude") else None
        if (r.get("scope") or "").strip().lower() != "title":   # title-only patterns can't explain a description match
            rules.append((pat, exc))
    except re.error:
        pass  # pattern uses syntax Python can't read; the match still counts, we just can't show why

has_clean = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'jobs_clean'").fetchone()[0]
body_sql = "coalesce(c.body_clean, j.body, '')" if has_clean else "coalesce(j.body, '')"
join = "LEFT JOIN jobs_clean c ON c.id = j.id" if has_clean else ""
where = "AND NOT h.in_title" if body_only else ""

total, n_title = con.execute(f"""SELECT count(*), sum(in_title::INT) FROM concept_hits
                                 WHERE lower(concept) = lower(?)""", [topic]).fetchone()
picked = con.execute(f"""
    SELECT year(j.date_created), h.in_title, j.title, {body_sql}
    FROM concept_hits h JOIN jobs j ON j.id = h.job_id {join}
    WHERE lower(h.concept) = lower(?) {where}
    ORDER BY random() LIMIT ?""", [topic, n]).fetchall()

print(f"{rows[0]['topic']}: {total:,} jobs matched ({n_title or 0:,} in the title).")
print(f"Random {len(picked)}{' description-only' if body_only else ''} matches:\n")
for year, in_title, title, body in picked:
    if in_title:
        print(f"{year}  T  {title[:110]}")
        continue
    text = re.sub(r"<[^>]+>", " ", body)
    snippet = "(can't show the match)"
    for pat, exc in rules:
        t = exc.sub(" ", text) if exc else text
        m = pat.search(t)
        if m:
            a, b = max(0, m.start() - 70), min(len(t), m.end() + 70)
            snippet = ("…" if a else "") + t[a:m.start()] + "[" + m.group(0) + "]" + t[m.end():b] + ("…" if b < len(t) else "")
            snippet = re.sub(r"\s+", " ", snippet)
            break
    print(f"{year}  B  {title[:110]}")
    print(f"         {snippet}\n")