"""Build the pilot sample of job ads for LLM topic classification.

Run from the repo root:  python llm_pilot/build_sample.py
Writes llm_pilot/data/sample.parquet (id, year, lang, title, org, body_clean, why).

Composition (target 5,000, fixed seed so it is repeatable):
  1. every ad behind review/review_labels.csv (the test set)
  2. top-up so each new topic has at least MIN_PER_TOPIC ads with an old regex hit
  3. top-up so French and Spanish ads reach MIN_FR / MIN_ES
  4. the rest: equal numbers per year, at random
"""
import csv
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "llm_pilot" / "data" / "sample.parquet"
TARGET, MIN_PER_TOPIC, MIN_FR, MIN_ES, SEED = 5000, 60, 450, 300, 42
DROP_GROUPS = {"Funding & donors"}

topics = [r for r in csv.DictReader(open(ROOT / "review" / "topics_v2_definitions.csv", encoding="utf-8-sig"))
          if r["group"] not in DROP_GROUPS]
old2new = [(o.strip(), t["topic"]) for t in topics for o in t["replaces"].split(";") if o.strip()]
label_ids = sorted({int(r["job_id"]) for r in csv.DictReader(open(ROOT / "review" / "review_labels.csv", encoding="utf-8-sig"))})

con = duckdb.connect()  # in-memory; the big database is attached read-only
con.execute(f"ATTACH '{(ROOT / 'reliefweb_jobs.duckdb').as_posix()}' AS rw (READ_ONLY)")
con.execute(f"SELECT setseed({SEED / 100})")
con.execute("CREATE TABLE old2new(old VARCHAR, new VARCHAR)")
con.executemany("INSERT INTO old2new VALUES (?, ?)", old2new)
con.execute("CREATE TABLE label_ids(id BIGINT)")
con.executemany("INSERT INTO label_ids VALUES (?)", [(i,) for i in label_ids])

print("reading job metadata and detecting language ...", flush=True)
con.execute(r"""
CREATE TABLE meta AS
WITH t AS (
  SELECT j.id, year(j.date_created) AS year, lower(substr(c.body_clean, 1, 3000)) AS s,
         hash(j.id, 42) AS rnd
  FROM rw.jobs j JOIN rw.jobs_clean c USING (id)
  WHERE j.data_source = 'api_v2' AND year(j.date_created) >= 2011 AND length(c.body_clean) >= 400
), n AS (
  SELECT id, year, rnd,
    len(regexp_extract_all(s, '\b(the|and|of|with|for|will)\b')) AS en,
    len(regexp_extract_all(s, '\b(le|les|des|et|du|pour|dans|une)\b')) AS fr,
    len(regexp_extract_all(s, '\b(el|los|las|y|para|con|del|una)\b')) AS es
  FROM t)
SELECT id, year, rnd,
  CASE WHEN fr > en AND fr >= es THEN 'fr' WHEN es > en AND es > fr THEN 'es' ELSE 'en' END AS lang
FROM n
""")
print(con.sql("SELECT lang, count(*) FROM meta GROUP BY 1 ORDER BY 2 DESC").fetchall(), flush=True)

con.execute("CREATE TABLE pick(id BIGINT PRIMARY KEY, why VARCHAR)")
con.execute("INSERT INTO pick SELECT id, 'review_labels' FROM label_ids WHERE id IN (SELECT id FROM meta)")

print("topping up thin topics ...", flush=True)
con.execute("""
CREATE TABLE hits AS
SELECT h.job_id AS id, m.new AS topic, bool_or(h.in_title) AS in_title, any_value(x.rnd) AS rnd
FROM rw.concept_hits h JOIN old2new m ON m.old = h.concept JOIN meta x ON x.id = h.job_id
GROUP BY 1, 2
""")
unmatched = con.sql("SELECT old FROM old2new WHERE old NOT IN (SELECT DISTINCT concept FROM rw.concept_hits)").fetchall()
if unmatched:
    print("  old topic names with no regex hits (check spelling):", [u[0] for u in unmatched])
for (topic,) in con.sql("SELECT DISTINCT new FROM old2new ORDER BY 1").fetchall():
    have = con.execute("SELECT count(*) FROM hits WHERE topic = ? AND id IN (SELECT id FROM pick)", [topic]).fetchone()[0]
    need = MIN_PER_TOPIC - have
    if need > 0:
        # half from title matches (likely genuine), half from description-only matches (the hard cases)
        for cond, k in (("in_title", need // 2), ("NOT in_title", need - need // 2)):
            con.execute(f"""INSERT OR IGNORE INTO pick
                SELECT id, 'thin_topic' FROM hits WHERE topic = ? AND {cond} AND id NOT IN (SELECT id FROM pick)
                ORDER BY rnd LIMIT {k}""", [topic])

print("topping up French and Spanish ...", flush=True)
for lang, minimum in (("fr", MIN_FR), ("es", MIN_ES)):
    have = con.execute("SELECT count(*) FROM pick JOIN meta USING (id) WHERE lang = ?", [lang]).fetchone()[0]
    if minimum > have:
        con.execute(f"""INSERT OR IGNORE INTO pick SELECT id, 'language' FROM meta
            WHERE lang = ? AND id NOT IN (SELECT id FROM pick) ORDER BY rnd LIMIT {minimum - have}""", [lang])

n = con.sql("SELECT count(*) FROM pick").fetchone()[0]
years = con.sql("SELECT count(DISTINCT year) FROM meta").fetchone()[0]
per_year = max(0, (TARGET - n)) // years + 1
print(f"{n} picked so far; adding about {per_year} random ads per year ...", flush=True)
con.execute(f"""INSERT OR IGNORE INTO pick
    SELECT id, 'random_by_year' FROM (
      SELECT id, row_number() OVER (PARTITION BY year ORDER BY rnd) AS k
      FROM meta WHERE id NOT IN (SELECT id FROM pick))
    WHERE k <= {per_year}""")
con.execute(f"""DELETE FROM pick WHERE why = 'random_by_year' AND id IN (
    SELECT p.id FROM pick p JOIN meta m USING (id) WHERE p.why = 'random_by_year'
    ORDER BY m.rnd DESC LIMIT greatest(0, (SELECT count(*) FROM pick) - {TARGET}))""")

print("writing sample ...", flush=True)
con.execute(f"""
COPY (
  SELECT p.id, m.year, m.lang, j.title,
         (SELECT string_agg(DISTINCT coalesce(nullif(o.org_shortname, ''), o.org_name), '; ')
            FROM rw.job_orgs o WHERE o.job_id = p.id) AS org,
         c.body_clean, p.why
  FROM pick p JOIN meta m USING (id) JOIN rw.jobs j USING (id) JOIN rw.jobs_clean c USING (id)
  ORDER BY m.rnd
) TO '{OUT.as_posix()}' (FORMAT parquet)
""")
s = f"read_parquet('{OUT.as_posix()}')"
print("sample size:", con.sql(f"SELECT count(*) FROM {s}").fetchone()[0])
print("by reason:", con.sql(f"SELECT why, count(*) FROM {s} GROUP BY 1 ORDER BY 2 DESC").fetchall())
print("by language:", con.sql(f"SELECT lang, count(*) FROM {s} GROUP BY 1 ORDER BY 2 DESC").fetchall())
print("by year:", con.sql(f"SELECT year, count(*) FROM {s} GROUP BY 1 ORDER BY 1").fetchall())
print("thinnest topics (ads with an old regex hit):",
      con.sql(f"SELECT topic, count(*) FROM hits WHERE id IN (SELECT id FROM {s}) GROUP BY 1 ORDER BY 2 LIMIT 8").fetchall())
