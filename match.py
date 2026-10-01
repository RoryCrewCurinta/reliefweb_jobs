"""
Load topics.csv into the database and (re)build concept_hits.
Run after editing topics.csv:   python match.py
Matches titles now; also matches job descriptions once the API harvest has filled them.
Patterns are regular expressions; case_sensitive=1 for acronyms (CVA, AI, GIS...).
"""
import csv, duckdb

con = duckdb.connect("reliefweb_jobs.duckdb")
con.execute(open("schema.sql").read())
rows = list(csv.DictReader(open("topics.csv", encoding="utf-8")))

con.execute("DELETE FROM concepts; DELETE FROM concept_patterns; DELETE FROM concept_hits;")
for c, g in sorted({(r["concept"], r["group"]) for r in rows}):
    con.execute("INSERT INTO concepts VALUES (?,?,NULL)", [c, g])
con.executemany("INSERT INTO concept_patterns VALUES (?,?)", [(r["concept"], r["pattern"]) for r in rows])

# Strip HTML/markdown noise from bodies once, into a temp table
con.execute("""CREATE OR REPLACE TEMP TABLE txt AS
  SELECT id, coalesce(title,'') AS title,
         coalesce(regexp_replace(body, '<[^>]+>', ' ', 'g'), '') AS body
  FROM jobs""")

con.execute("CREATE OR REPLACE TEMP TABLE raw_hits (job_id BIGINT, concept VARCHAR, in_title BOOLEAN, in_body BOOLEAN)")
for r in rows:
    pat = r["pattern"] if r["case_sensitive"] == "1" else "(?i)" + r["pattern"]
    con.execute("""INSERT INTO raw_hits
        SELECT id, ?, regexp_matches(title, ?), regexp_matches(body, ?)
        FROM txt WHERE regexp_matches(title, ?) OR regexp_matches(body, ?)""",
        [r["concept"], pat, pat, pat, pat])

con.execute("""INSERT INTO concept_hits
  SELECT job_id, concept, bool_or(in_title), bool_or(in_body) FROM raw_hits GROUP BY 1,2""")

print(con.sql("""SELECT concept, count(*) AS jobs, sum(in_title::INT) AS in_title, sum(in_body::INT) AS in_body
                 FROM concept_hits GROUP BY 1 ORDER BY jobs DESC"""))
con.close()
