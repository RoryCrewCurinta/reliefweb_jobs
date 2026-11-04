"""
Score jobs against topics.csv and (re)build concept_hits.

Usage:
  python match.py            # full rescore: after editing topics.csv or a full strip.py
  python match.py --update   # only new/changed jobs: monthly, after harvest --update and strip --update

Matches titles, and descriptions with boilerplate removed (jobs_clean, from strip.py).
--update refuses to run if topics.csv or the template list changed since the last full run,
because old and new jobs would then be scored by different rules.

topics.csv columns:
  topic, group     - what appears on the dashboard
  pattern          - regular expression (one synonym per row)
  case_sensitive   - 1 for acronyms (CVA, AI, GIS...), else 0
  scope            - blank = title and description; 'title' = job titles only (for words too generic
                     in descriptions, e.g. 'compliance')
  exclude          - phrases blanked out before matching (e.g. 'handicap international'), case-insensitive
  note             - free text
"""
import argparse
import csv
import hashlib
import io
import sys
import time

import duckdb

DB = "reliefweb_jobs.duckdb"


def get_state(con, key):
    r = con.execute("SELECT value FROM pipeline_state WHERE key = ?", [key]).fetchone()
    return r[0] if r else None


def set_state(con, key, value):
    con.execute("DELETE FROM pipeline_state WHERE key = ?", [key])
    con.execute("INSERT INTO pipeline_state VALUES (?, ?)", [key, value])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true", help="score only new/changed jobs")
    a = ap.parse_args()
    t0 = time.time()
    try:
        con = duckdb.connect(DB)
    except duckdb.IOException as e:
        raise SystemExit(f"Database is in use (is another script running?)\n{e}")
    con.execute(open("schema.sql").read())
    con.execute("CREATE TABLE IF NOT EXISTS pipeline_state (key VARCHAR, value VARCHAR)")
    con.execute("CREATE TABLE IF NOT EXISTS matched_jobs (id BIGINT, date_changed TIMESTAMP)")

    raw = open("topics.csv", "rb").read()
    topics_hash = hashlib.sha256(raw).hexdigest()[:16]
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))

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
        sys.exit("Fix these patterns in topics.csv first:\n" + "\n".join(bad))

    has_clean = con.execute("SELECT count(*) FROM information_schema.tables "
                            "WHERE table_name = 'jobs_clean'").fetchone()[0] > 0
    strip_version = get_state(con, "strip_version")

    if a.update:
        if get_state(con, "topics_hash") != topics_hash:
            sys.exit("topics.csv has changed since the last full run - run 'python match.py' (full)")
        if get_state(con, "match_strip_version") != strip_version:
            sys.exit("strip.py was fully re-run since the last full match - run 'python match.py' (full)")
        con.execute("""CREATE OR REPLACE TEMP TABLE todo AS
            SELECT j.id FROM jobs j LEFT JOIN matched_jobs m ON m.id = j.id
            WHERE m.id IS NULL OR m.date_changed IS DISTINCT FROM j.date_changed""")
        if has_clean:
            missing = con.execute("""SELECT count(*) FROM todo t JOIN jobs j ON j.id = t.id
                                     LEFT JOIN jobs_clean c ON c.id = t.id
                                     WHERE j.body IS NOT NULL
                                       AND (c.id IS NULL OR c.date_changed IS DISTINCT FROM j.date_changed)""").fetchone()[0]
            if missing:
                sys.exit(f"{missing:,} new jobs have no cleaned description - run 'python strip.py --update' first")
    else:
        con.execute("CREATE OR REPLACE TEMP TABLE todo AS SELECT id FROM jobs")
        if not has_clean:
            print("WARNING: no cleaned descriptions (run strip.py first) - matching raw text incl. boilerplate")

    n_todo = con.execute("SELECT count(*) FROM todo").fetchone()[0]
    print(f"{'Update' if a.update else 'Full rescore'}: {n_todo:,} jobs, {len(rows)} patterns")
    if n_todo == 0:
        print("Nothing new to score.")
        return

    body = "regexp_replace(j.body, '<[^>]+>', ' ', 'g')"
    if has_clean:
        body = f"coalesce(c.body_clean, {body})"
        join = "LEFT JOIN jobs_clean c ON c.id = j.id"
    else:
        join = ""
    con.execute(f"""CREATE OR REPLACE TEMP TABLE txt AS
        SELECT j.id, coalesce(j.title, '') AS title, coalesce({body}, '') AS body
        FROM todo t JOIN jobs j ON j.id = t.id {join}""")
    con.execute("CREATE OR REPLACE TEMP TABLE raw_hits (job_id BIGINT, concept VARCHAR, in_title BOOLEAN, in_body BOOLEAN)")

    for n, r in enumerate(rows, 1):
        pat = r["pattern"] if r["case_sensitive"].strip() == "1" else "(?i)" + r["pattern"]
        if r.get("exclude"):
            excl = "(?i)" + r["exclude"]
            T, B, params = "regexp_replace(title, ?, ' ', 'g')", "regexp_replace(body, ?, ' ', 'g')", [excl]
        else:
            T, B, params = "title", "body", []
        if (r.get("scope") or "").strip().lower() == "title":
            # Pattern too generic for descriptions: count it in job titles only
            con.execute(f"""INSERT INTO raw_hits
                SELECT id, ?, regexp_matches({T}, ?), false
                FROM txt WHERE regexp_matches(title, ?)""",
                        [r["topic"]] + params + [pat, pat])
        else:
            con.execute(f"""INSERT INTO raw_hits
                SELECT id, ?, regexp_matches({T}, ?), regexp_matches({B}, ?)
                FROM txt WHERE regexp_matches(title, ?) OR regexp_matches(body, ?)""",
                        [r["topic"]] + params + [pat] + params + [pat, pat, pat])
        if n % 100 == 0:
            print(f"  {n}/{len(rows)} patterns")

    con.execute("BEGIN")
    if a.update:
        con.execute("DELETE FROM concept_hits WHERE job_id IN (SELECT id FROM todo)")
        con.execute("DELETE FROM matched_jobs WHERE id IN (SELECT id FROM todo)")
    else:
        con.execute("DELETE FROM concepts; DELETE FROM concept_patterns; DELETE FROM concept_hits; DELETE FROM matched_jobs;")
        for t, g in sorted({(r["topic"], r["group"]) for r in rows}):
            con.execute("INSERT INTO concepts VALUES (?, ?, NULL)", [t, g])
        con.executemany("INSERT INTO concept_patterns VALUES (?, ?)", [(r["topic"], r["pattern"]) for r in rows])
        set_state(con, "topics_hash", topics_hash)
        set_state(con, "match_strip_version", strip_version)
    con.execute("""INSERT INTO concept_hits
        SELECT job_id, concept, bool_or(in_title), bool_or(in_body) FROM raw_hits
        GROUP BY 1, 2 HAVING bool_or(in_title) OR bool_or(in_body)""")
    con.execute("INSERT INTO matched_jobs SELECT j.id, j.date_changed FROM todo t JOIN jobs j ON j.id = t.id")
    con.execute("COMMIT")

    if a.update:
        n_hits = con.execute("SELECT count(*) FROM raw_hits").fetchone()[0]
        print(f"Scored {n_todo:,} jobs ({n_hits:,} pattern hits).")
    else:
        print(con.sql("""SELECT c.grp AS "group", h.concept AS topic, count(*) AS jobs,
                                sum(in_title::INT) AS in_title, sum(in_body::INT) AS in_body
                         FROM concept_hits h JOIN concepts c USING (concept)
                         GROUP BY 1, 2 ORDER BY 1, jobs DESC""").df().to_string(index=False))
    con.close()
    print(f"\nDone in {(time.time() - t0) / 60:.1f} min. Next: python export.py")


if __name__ == "__main__":
    main()