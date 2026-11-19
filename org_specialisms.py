"""
What does each organisation hire for, far more than the sector does? Every organisation, every year.

Run from the repo folder (the one holding reliefweb_jobs.duckdb):
    python org_specialisms.py

Reads the database read-only and writes two files to "Claude outputs/" (git-ignored):
    org_specialisms_all.csv        every organisation x topic pair with at least MIN_TOPIC_POSTS core ads
    org_specialisms_shortlist.csv  the pairs that clear the screen below, with example job titles

Same rules as export.py: API rows only, June 2011 to the last full month, GPT-6 Luna tags, core tags only
(the job is the topic), a job with several organisations counts once for each.

concentration = the organisation's core ads for the topic / the number expected if it hired like the sector.
"Expected" is worked out year by year (its ads that year x the sector's share for the topic that year), so
an organisation active only in, say, 2013-2016 is compared with the sector in those years, not with all 15.
conc_low is the same ratio using the bottom of a 95% interval on the organisation's count: rank on that,
it stops 5 ads out of 20 beating 150 out of 2,000.
"""
import csv
import datetime as dt
import math
from pathlib import Path

import duckdb

DB = "reliefweb_jobs.duckdb"
TOPICS_FILE = Path("review/topics_v2_definitions.csv")
CLASS_FILE = Path("docs/data/org_classification.csv")
OUT = Path("Claude outputs")
LLM_MODEL = "gpt-6-luna"
MIN_ORG_POSTS = 20      # organisations with fewer ads in all are left out
MIN_TOPIC_POSTS = 5     # pairs with fewer core ads are left out
SHORTLIST_LOW = 3.0     # shortlist: conc_low at least this ...
SHORTLIST_SHARE = 0.03  # ... and the topic is at least this share of the organisation's ads
N_TITLES = 3            # example job titles per shortlisted pair


def wilson_low(k, n, z=1.96):
    p = k / n
    return (p + z * z / (2 * n) - z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / (1 + z * z / n)


def main():
    OUT.mkdir(exist_ok=True)
    try:
        con = duckdb.connect(DB, read_only=True)
    except duckdb.IOException as e:
        raise SystemExit(f"Database is in use (is harvest.py, strip.py or classify.py running?)\n{e}")

    con.execute("CREATE TEMP TABLE tc (concept VARCHAR, raw VARCHAR)")
    con.executemany("INSERT INTO tc VALUES (?, ?)", [
        ((r.get("dashboard_name") or "").strip() or r["topic"], r["topic"])
        for r in csv.DictReader(open(TOPICS_FILE, encoding="utf-8-sig"))])
    con.execute("""CREATE TEMP TABLE hits AS
        SELECT DISTINCT l.job_id, t.concept
        FROM llm_topics l JOIN tc t ON t.raw = l.topic
        WHERE l.model = ? AND l.level = 'core'""", [LLM_MODEL])
    cutoff = dt.date.today().replace(day=1)
    con.execute(f"""CREATE TEMP TABLE j AS
        SELECT id, year(date_created) AS y, date_created, title FROM jobs
        WHERE data_source = 'api_v2' AND date_created IS NOT NULL
          AND date_created >= DATE '2011-06-01' AND date_created < DATE '{cutoff.isoformat()}'""")
    con.execute("""CREATE TEMP TABLE jo AS
        SELECT DISTINCT o.job_id, o.org_id, j.y
        FROM job_orgs o JOIN j ON j.id = o.job_id WHERE o.org_id IS NOT NULL""")
    con.execute("""CREATE TEMP TABLE onames AS
        SELECT o.org_id, arg_max(o.org_name, j.date_created) AS name
        FROM job_orgs o JOIN j ON j.id = o.job_id WHERE o.org_id IS NOT NULL GROUP BY 1""")

    rows = con.execute("""
        WITH tot AS (SELECT y, count(*) AS n FROM j GROUP BY 1),
        sec AS (SELECT j.y, h.concept, count(*) AS k FROM hits h JOIN j ON j.id = h.job_id GROUP BY 1, 2),
        rate AS (SELECT sec.y, sec.concept, sec.k / tot.n AS r FROM sec JOIN tot USING (y)),
        oy AS (SELECT org_id, y, count(*) AS n FROM jo GROUP BY 1, 2),
        ot AS (SELECT org_id, sum(n) AS n, min(y) AS y0, max(y) AS y1 FROM oy GROUP BY 1),
        ex AS (SELECT oy.org_id, rate.concept, sum(oy.n * rate.r) AS expected
               FROM oy JOIN rate USING (y) GROUP BY 1, 2),
        ok AS (SELECT jo.org_id, h.concept, count(*) AS k, min(jo.y) AS ty0, max(jo.y) AS ty1,
                      count(DISTINCT jo.y) AS years_with_ads
               FROM jo JOIN hits h ON h.job_id = jo.job_id GROUP BY 1, 2)
        SELECT ok.org_id, onames.name, ok.concept, ot.n, ok.k, ex.expected, ot.y0, ot.y1,
               ok.ty0, ok.ty1, ok.years_with_ads
        FROM ok JOIN ot USING (org_id) JOIN ex USING (org_id, concept) JOIN onames USING (org_id)
        WHERE ot.n >= ? AND ok.k >= ?""", [MIN_ORG_POSTS, MIN_TOPIC_POSTS]).fetchall()

    cls = {}
    if CLASS_FILE.exists():
        for r in csv.DictReader(open(CLASS_FILE, encoding="utf-8-sig")):
            cls[int(r["org_id"])] = (r["class"], r["reliefweb_type"], r["home_country"])

    out = []
    for oid, name, topic, n, k, exp, y0, y1, ty0, ty1, yrs in rows:
        n, k = int(n), int(k)
        c = cls.get(oid, ("", "", ""))
        out.append({
            "org_id": oid, "org": name, "class": c[0], "reliefweb_type": c[1], "home_country": c[2],
            "topic": topic, "org_posts": n, "org_first_year": y0, "org_last_year": y1,
            "topic_posts": k, "topic_share": round(k / n, 4), "expected_posts": round(exp, 2),
            "concentration": round(k / exp, 1), "conc_low": round(wilson_low(k, n) * n / exp, 1),
            "topic_first_year": ty0, "topic_last_year": ty1, "years_with_topic_ads": yrs})
    out.sort(key=lambda r: -r["conc_low"])
    cols = list(out[0].keys()) if out else []
    with open(OUT / "org_specialisms_all.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, cols)
        w.writeheader()
        w.writerows(out)

    short = [r for r in out if r["conc_low"] >= SHORTLIST_LOW and r["topic_share"] >= SHORTLIST_SHARE]
    for r in short:
        titles = con.execute("""
            SELECT j.title FROM jo JOIN hits h ON h.job_id = jo.job_id JOIN j ON j.id = jo.job_id
            WHERE jo.org_id = ? AND h.concept = ? ORDER BY hash(j.id) LIMIT ?""",
            [r["org_id"], r["topic"], N_TITLES]).fetchall()
        r["example_titles"] = " | ".join((t[0] or "").strip() for t in titles)
    with open(OUT / "org_specialisms_shortlist.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, cols + ["example_titles"])
        w.writeheader()
        w.writerows(short)

    n_orgs = con.execute("SELECT count(*) FROM (SELECT org_id FROM jo GROUP BY 1 HAVING count(*) >= ?)",
                         [MIN_ORG_POSTS]).fetchone()[0]
    print(f"Organisations with {MIN_ORG_POSTS}+ ads: {n_orgs:,}")
    print(f"Pairs written: {len(out):,} (all), {len(short):,} (shortlist) -> {OUT}/")


if __name__ == "__main__":
    main()
