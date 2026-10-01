"""
Spot-check precision: print 20 random matching job titles for a topic.
  python check.py Biometrics
  python check.py "Anticipatory action" 40
Count how many of the printed jobs are genuinely about the topic. Aim for 16+/20;
if lower, tighten patterns or add an exclude in topics.csv, then re-run match.py.
"""
import sys, duckdb
topic = sys.argv[1] if len(sys.argv) > 1 else None
n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
con = duckdb.connect("reliefweb_jobs.duckdb", read_only=True)
if not topic:
    print("Topics:\n" + "\n".join(r[0] for r in con.execute("SELECT concept FROM concepts ORDER BY 1").fetchall())); sys.exit()
rows = con.execute("""SELECT year(j.date_created), CASE WHEN h.in_title THEN 'T' ELSE 'B' END, j.title, j.url
                      FROM concept_hits h JOIN jobs j ON j.id = h.job_id
                      WHERE lower(h.concept) = lower(?) ORDER BY random() LIMIT ?""", [topic, n]).fetchall()
total = con.execute("SELECT count(*) FROM concept_hits WHERE lower(concept)=lower(?)", [topic]).fetchone()[0]
print(f"{topic}: {total} jobs matched. Random {len(rows)} (T = matched in title, B = body only):\n")
for y, where, title, url in rows:
    print(f"{y}  {where}  {title[:90]}")
