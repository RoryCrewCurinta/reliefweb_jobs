"""
Strip boilerplate from job descriptions before topic matching.

Idea: within each organisation, a sentence that appears across many DIFFERENT job
titles is template text (equal-opportunity statements, benefits, fraud/safeguarding
clauses, "Education:" headings), not content about the role. Re-posts of the same
role share text too, but under the same title, so they are NOT counted as templates.

Usage:
  python strip.py --update     # monthly, after harvest.py --update: cleans new/changed jobs
                               # with the existing template list (fast)
  python strip.py              # full run: re-learn templates from the whole archive and
                               # re-clean everything (slow; do quarterly). Then run a FULL match.py.
  python strip.py --min-titles 15 --min-share 0.05    # full run, removing less

Writes:
  jobs_clean   (id, date_changed, body_clean) - what match.py reads
  boilerplate  (org_key, sentence, n_jobs, n_titles) - everything treated as template, for inspection

Trade-offs: an org that adds the same topical sentence to most of its posts loses it;
new orgs/templates leak until the next full run. Check the boilerplate table for your
key topics before trusting a trend.
"""
import argparse
import datetime as dt
import time

import duckdb

DB = "reliefweb_jobs.duckdb"
BATCH = 20000   # jobs cleaned per batch; lower it if memory is still tight
AUDIT = ["gender", "women", "disabilit", "sexual orientation", "fraud", "safeguard",
         "exploitation", "health insurance", "education", "data protection", "cash"]


def table_exists(con, name):
    return con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
                       [name]).fetchone()[0] > 0


def set_state(con, key, value):
    con.execute("CREATE TABLE IF NOT EXISTS pipeline_state (key VARCHAR, value VARCHAR)")
    con.execute("DELETE FROM pipeline_state WHERE key = ?", [key])
    con.execute("INSERT INTO pipeline_state VALUES (?, ?)", [key, value])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update", action="store_true", help="clean only new/changed jobs")
    ap.add_argument("--min-titles", type=int, default=10,
                    help="boilerplate if one org uses the sentence across this many distinct job titles")
    ap.add_argument("--min-share", type=float, default=0.01,
                    help="...AND in at least this share of that org's posts")
    a = ap.parse_args()
    t0 = time.time()
    try:
        con = duckdb.connect(DB)
    except duckdb.IOException as e:
        raise SystemExit(f"Database is in use (is another script running?)\n{e}")

    # Which jobs to process
    if a.update:
        if not (table_exists(con, "boilerplate") and table_exists(con, "jobs_clean")):
            raise SystemExit("No template list yet - run a full 'python strip.py' first")
        con.execute("""CREATE OR REPLACE TEMP TABLE todo AS
            SELECT j.id FROM jobs j LEFT JOIN jobs_clean c ON c.id = j.id
            WHERE j.body IS NOT NULL
              AND (c.id IS NULL OR c.date_changed IS DISTINCT FROM j.date_changed)""")
    else:
        con.execute("CREATE OR REPLACE TEMP TABLE todo AS SELECT id FROM jobs WHERE body IS NOT NULL")
    n_todo = con.execute("SELECT count(*) FROM todo").fetchone()[0]
    print(f"{'Update' if a.update else 'Full run'}: {n_todo:,} jobs to clean")
    if n_todo == 0:
        print("Nothing new. Next: python match.py --update")
        return

    con.execute("SET preserve_insertion_order = false")   # lets DuckDB use less memory

    def split(where):
        """Sentences for the jobs selected by `where` (a SQL condition on todo t)."""
        con.execute(f"""CREATE OR REPLACE TEMP TABLE jk AS
            SELECT j.id,
                   coalesce(min(o.org_id)::VARCHAR, 'none') AS org_key,
                   trim(regexp_replace(lower(coalesce(j.title, '')), '[^a-z]+', ' ', 'g')) AS ntitle
            FROM todo t JOIN jobs j ON j.id = t.id LEFT JOIN job_orgs o ON o.job_id = j.id
            WHERE {where}
            GROUP BY j.id, j.title""")
        con.execute(r"""CREATE OR REPLACE TEMP TABLE sent AS
            WITH parts AS (
                SELECT j.id, regexp_split_to_array(
                           regexp_replace(j.body, '<[^>]+>', ' ', 'g'),
                           '[\r\n]+|[.!?;]\s+|\s[•·▪]\s') AS arr
                FROM jk JOIN jobs j ON j.id = jk.id),
            raw AS (SELECT id, unnest(range(1, len(arr) + 1)) AS pos, unnest(arr) AS s FROM parts)
            SELECT id, pos, s,
                   trim(regexp_replace(regexp_replace(lower(s), '[0-9]+', '#', 'g'),
                                       '[^a-z#àâçéèêëîïôûùüÿñáíóú]+', ' ', 'g')) AS ns
            FROM raw WHERE trim(s) <> ''""")

    if not a.update:
        print("Splitting all descriptions into sentences...")
        split("true")
        print(f"    {con.execute('SELECT count(*) FROM sent').fetchone()[0]:,} sentences")
        print(f"Learning templates (>= {a.min_titles} job titles and >= {a.min_share:.0%} of an org's posts)...")
        con.execute(f"""CREATE OR REPLACE TABLE boilerplate AS
            WITH org_n AS (SELECT org_key, count(*) AS n FROM jk GROUP BY 1)
            SELECT k.org_key, s.ns AS sentence,
                   count(DISTINCT s.id) AS n_jobs, count(DISTINCT k.ntitle) AS n_titles
            FROM sent s JOIN jk k USING (id) JOIN org_n o USING (org_key)
            WHERE s.ns <> ''
            GROUP BY 1, 2, o.n
            HAVING count(DISTINCT k.ntitle) >= {a.min_titles}
               AND count(DISTINCT s.id) >= {a.min_share} * o.n""")
        print(f"    {con.execute('SELECT count(*) FROM boilerplate').fetchone()[0]:,} template sentences")
        con.execute("DROP TABLE sent")
        con.execute("CREATE OR REPLACE TABLE jobs_clean (id BIGINT, date_changed TIMESTAMP, body_clean VARCHAR)")
        set_state(con, "strip_version", dt.datetime.now().isoformat(timespec="seconds"))
    else:
        con.execute("DELETE FROM jobs_clean WHERE id IN (SELECT id FROM todo)")

    # Clean in batches, committing each one: memory stays flat, and if it stops part-way,
    # 'python strip.py --update' carries on from where it got to.
    con.execute(f"""CREATE OR REPLACE TEMP TABLE todo AS
        SELECT id, (row_number() OVER (ORDER BY id) - 1) // {BATCH} AS batch FROM todo""")
    n_batches = con.execute("SELECT max(batch) + 1 FROM todo").fetchone()[0]
    before = after = 0
    print(f"Writing cleaned descriptions in {n_batches} batches...")
    for b in range(n_batches):
        split(f"t.batch = {b}")
        con.execute("""CREATE OR REPLACE TEMP TABLE kept AS
            SELECT s.id, s.pos, s.s, b.sentence IS NULL AS keep
            FROM sent s JOIN jk k USING (id)
            LEFT JOIN boilerplate b ON b.org_key = k.org_key AND b.sentence = s.ns""")
        x, y = con.execute("SELECT sum(length(s)), sum(length(s)) FILTER (WHERE keep) FROM kept").fetchone()
        before += x or 0
        after += y or 0
        con.execute("BEGIN")
        con.execute("""INSERT INTO jobs_clean
            SELECT jk.id, j.date_changed, coalesce(agg.body_clean, '')
            FROM jk JOIN jobs j ON j.id = jk.id
            LEFT JOIN (SELECT id, string_agg(s, '. ' ORDER BY pos) AS body_clean
                       FROM kept WHERE keep GROUP BY id) agg ON agg.id = jk.id""")
        con.execute("COMMIT")
        print(f"    batch {b + 1}/{n_batches} done")
    print(f"    description text kept: {after / before:.0%}" if before else "    (no text)")

    if not a.update:
        print("\nMost widespread template sentences:")
        for sentence, n in con.execute("""SELECT sentence, sum(n_jobs) AS n FROM boilerplate
                                          GROUP BY 1 ORDER BY n DESC LIMIT 15""").fetchall():
            print(f"  {n:>8,}  {sentence[:100]}")
        print("\nTopic words inside removed text (job-sentence occurrences stripped):")
        for w in AUDIT:
            n = con.execute("SELECT coalesce(sum(n_jobs), 0) FROM boilerplate WHERE sentence LIKE ?",
                            [f"%{w}%"]).fetchone()[0]
            print(f"  {w:<20} {n:>10,}")

    con.close()
    nxt = "python match.py --update" if a.update else "python match.py   (full rescore needed)"
    print(f"\nDone in {(time.time() - t0) / 60:.1f} min. Next: {nxt}")


if __name__ == "__main__":
    main()