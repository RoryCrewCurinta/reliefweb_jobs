"""
Load topics.csv and (re)build concept_hits.   Run after editing topics.csv:  python match.py
Matches job titles now, and full descriptions once the API harvest has filled them in.

topics.csv columns:
  topic, group     - what appears on the dashboard
  pattern          - regular expression (one synonym per row)
  case_sensitive   - 1 for acronyms (CVA, AI, GIS...), else 0
  exclude          - phrases blanked out before matching (e.g. 'handicap international'), case-insensitive
  note             - free text
"""
import csv, sys, duckdb

DB = "reliefweb_jobs.duckdb"
con = duckdb.connect(DB)
con.execute(open("schema.sql").read())
rows = list(csv.DictReader(open("topics.csv", encoding="utf-8-sig")))

# Validate every regex first, so one typo doesn't kill a long run
bad = []
for i, r in enumerate(rows, start=2):
    for field in ("pattern", "exclude"):
        if r.get(field):
            try:
                con.execute("SELECT regexp_matches('x', ?)", [r[field]])
            except Exception as e:
                bad.append(f"line {i} {field}: {r[field]!r} -> {e}")
if bad:
    print("Fix these patterns in topics.csv first:\n" + "\n".join(bad)); sys.exit(1)

con.execute("DELETE FROM concepts; DELETE FROM concept_patterns; DELETE FROM concept_hits;")
for t, g in sorted({(r["topic"], r["group"]) for r in rows}):
    con.execute("INSERT INTO concepts VALUES (?,?,NULL)", [t, g])
con.executemany("INSERT INTO concept_patterns VALUES (?,?)", [(r["topic"], r["pattern"]) for r in rows])

con.execute("""CREATE OR REPLACE TEMP TABLE txt AS
  SELECT id, coalesce(title,'') AS title,
         coalesce(regexp_replace(body, '<[^>]+>', ' ', 'g'), '') AS body
  FROM jobs""")
con.execute("CREATE OR REPLACE TEMP TABLE raw_hits (job_id BIGINT, concept VARCHAR, in_title BOOLEAN, in_body BOOLEAN)")

for n, r in enumerate(rows, 1):
    pat = r["pattern"] if r["case_sensitive"].strip() == "1" else "(?i)" + r["pattern"]
    if r.get("exclude"):
        excl = "(?i)" + r["exclude"]
        T, B, params = "regexp_replace(title, ?, ' ', 'g')", "regexp_replace(body, ?, ' ', 'g')", [excl]
    else:
        T, B, params = "title", "body", []
    con.execute(f"""INSERT INTO raw_hits
        SELECT id, ?, regexp_matches({T}, ?), regexp_matches({B}, ?)
        FROM txt WHERE regexp_matches(title, ?) OR regexp_matches(body, ?)""",
        [r["topic"]] + params + [pat] + params + [pat, pat, pat])
    if n % 100 == 0:
        print(f"  {n}/{len(rows)} patterns")

con.execute("""INSERT INTO concept_hits
  SELECT job_id, concept, bool_or(in_title), bool_or(in_body) FROM raw_hits
  GROUP BY 1,2 HAVING bool_or(in_title) OR bool_or(in_body)""")

print(con.sql("""SELECT c.grp AS "group", h.concept AS topic, count(*) AS jobs,
                        sum(in_title::INT) AS in_title, sum(in_body::INT) AS in_body
                 FROM concept_hits h JOIN concepts c USING (concept)
                 GROUP BY 1,2 ORDER BY 1, jobs DESC""").df().to_string(index=False))
con.close()
