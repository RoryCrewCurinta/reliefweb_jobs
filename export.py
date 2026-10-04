"""
Export small summary JSON files for the dashboard from reliefweb_jobs.duckdb.

Usage:
  python export.py      # run after match.py; writes docs/data/*.json and docs/data/data.js

Rules (also written into meta.json so the dashboard can state them):
- API rows only (data_source = 'api_v2'); the legacy Power BI rows are excluded.
- The current, incomplete month is always dropped, so charts never end in a false cliff.
- Topic counts: 'title' = matched in the job title (the role IS the topic);
  'any' = matched in title or description (the role touches it).
- A job with several organisations counts once for each of them.
- Months far below their neighbours are flagged as possible data gaps.
"""
import csv
import datetime as dt
import json
import statistics
from pathlib import Path

import duckdb

DB = "reliefweb_jobs.duckdb"
OUT = Path("docs/data")
TOP_ORGS = 150          # orgs that get their own monthly series
TOP_ORGS_TOPICS = 100   # orgs in the org x topic x year table
MIN_ORG_POSTS = 50      # tilt rows need this many org posts in the period
GAP_RATIO = 0.6         # month flagged if below 60% of the median of the 12 months around it
RECENT_MONTHS = 24      # months of org x topic x month detail (who is hiring for what, recently)
# NGO classification (see docs/data/ORG_CLASSIFICATION.md)
INCOME_FILE = Path("ref/wb_income_levels.csv")          # World Bank income groups
OVERRIDES_FILE = Path("ref/org_class_overrides.csv")    # manual corrections, with reasons
HOME_SHARE = 0.8        # "locally based" = at least this share of an NGO's located posts are in its home country
MIN_LOCATED_POSTS = 1   # posts with a country needed to apply the test
# Countries treated as one home for the test (cross-border responses run from next door)
HOME_PAIRS = [{"Türkiye", "Syrian Arab Republic"}]
# NGOs based in these countries are always "locally based", whatever the share: the Syria response is run
# largely by Syrian and Turkish NGOs registered in Türkiye, which also post for neighbouring countries
ALWAYS_LOCAL_HOMES = {"Türkiye", "Syrian Arab Republic"}
NGO = "Non-governmental Organization"
CLS_INTL, CLS_LOCAL, CLS_REGIONAL, CLS_UNKNOWN = ("International NGO", "Locally based NGO",
                                                  "Regional NGO (global South base)", "NGO (home country unknown)")


BUNDLE = {}


def write(name, obj):
    BUNDLE[name.removesuffix(".json")] = obj
    p = OUT / name
    p.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(f"  {name:<18} {p.stat().st_size / 1024:>8,.0f} KB")


def write_csv(name, header, rows):
    p = OUT / name
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  {name:<18} {p.stat().st_size / 1024:>8,.0f} KB")


def next_month(d):
    return (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def classify_orgs(con):
    """Split ReliefWeb's single 'NGO' type by where each NGO is based. Returns {org_id: class} for every
    organisation with posts, and writes the full mapping to docs/data/org_classification.csv."""
    income = {r["iso3"]: r["income_level"] for r in csv.DictReader(open(INCOME_FILE, encoding="utf-8"))}
    over = {int(r["org_id"]): r for r in csv.DictReader(open(OVERRIDES_FILE, encoding="utf-8"))} \
        if OVERRIDES_FILE.exists() else {}
    located = {}
    for oid, country, n in con.execute("""
            SELECT jo.org_id, c.country, count(DISTINCT jo.job_id)
            FROM jo JOIN job_countries c ON c.job_id = jo.job_id GROUP BY 1, 2""").fetchall():
        located.setdefault(oid, {})[country] = int(n)
    rows, cls = [], {}
    for oid, name, otype, home, iso3, n in con.execute("""
            SELECT jo.org_id, coalesce(g.org_name, any_value(o.org_name)), coalesce(g.org_type, any_value(t.org_type)),
                   g.home_country, g.home_iso3, count(DISTINCT jo.job_id)
            FROM jo LEFT JOIN orgs g ON g.org_id = jo.org_id
                    LEFT JOIN org_types t ON t.org_id = jo.org_id
                    LEFT JOIN job_orgs o ON o.org_id = jo.org_id AND o.job_id = jo.job_id
            GROUP BY jo.org_id, g.org_name, g.org_type, g.home_country, g.home_iso3""").fetchall():
        isos = [x for x in (iso3 or "").split(";") if x]
        homes = {x.strip() for x in (home or "").split(";") if x.strip()}
        for pair in HOME_PAIRS:
            if homes & pair:
                homes |= pair
        levels = sorted({income.get(i, "Not classified") for i in isos})
        loc = located.get(oid, {})
        n_loc = sum(loc.values())
        share = (sum(v for k, v in loc.items() if k in homes) / n_loc) if n_loc else None
        basis, reason = "rule", ""
        if otype != NGO:
            c, basis = otype or "Other", "ReliefWeb type"
        elif oid in over:
            c, basis, reason = over[oid]["class"], "manual override", over[oid]["reason"]
        elif not isos:
            c, reason = CLS_UNKNOWN, "ReliefWeb lists no home country"
        elif any(income.get(i) == "High income" for i in isos) or any(i not in income for i in isos):
            c, reason = CLS_INTL, "home country is high-income (or not a country in the World Bank list)"
        elif homes & ALWAYS_LOCAL_HOMES:
            c, reason = CLS_LOCAL, "based in Türkiye or Syria: treated as locally based (Syria response)"
        elif share is not None and n_loc >= MIN_LOCATED_POSTS and share >= HOME_SHARE:
            c, reason = CLS_LOCAL, f"home country is low/middle-income and {share:.0%} of located posts are there"
        else:
            c, reason = CLS_REGIONAL, ("home country is low/middle-income but only "
                                       f"{share:.0%} of located posts are there" if share is not None
                                       else "home country is low/middle-income; no posts carry a country")
        cls[oid] = c
        rows.append((oid, name, otype, home, "; ".join(levels), int(n), n_loc,
                     "" if share is None else round(share, 3), c, basis, reason))
    rows.sort(key=lambda r: (-r[5], r[1] or ""))
    write_csv("org_classification.csv", ["org_id", "organisation", "reliefweb_type", "home_country",
              "home_income_level", "posts", "posts_with_country", "share_of_posts_in_home_country",
              "class", "basis", "reason"], rows)
    return cls


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        con = duckdb.connect(DB, read_only=True)
    except duckdb.IOException as e:
        raise SystemExit(f"Database is in use (is match.py or harvest.py running?)\n{e}")
    if con.execute("SELECT count(*) FROM concept_hits").fetchone()[0] == 0:
        raise SystemExit("concept_hits is empty - run match.py first")

    cutoff = dt.date.today().replace(day=1)   # start of current month: excluded
    con.execute(f"""CREATE TEMP TABLE j AS
        SELECT id, date_trunc('month', date_created)::DATE AS m
        FROM jobs
        WHERE data_source = 'api_v2' AND date_created IS NOT NULL
         AND date_created >= DATE '2011-06-01' 
          AND date_created < DATE '{cutoff.isoformat()}'""")

    # Month axis shared by every file
    first = con.execute("SELECT min(m) FROM j").fetchone()[0]
    months, d = [], first
    while d < cutoff:
        months.append(d.strftime("%Y-%m"))
        d = next_month(d)
    idx = {m: i for i, m in enumerate(months)}

    def series(pairs):
        s = [0] * len(months)
        for m, v in pairs:
            s[idx[m]] = int(v)
        return s

    print("Writing docs/data/:")

    # 1. Total jobs per month (the denominator for every share)
    totals = series(con.execute("SELECT strftime(m, '%Y-%m'), count(*) FROM j GROUP BY 1").fetchall())
    write("totals.json", {"months": months, "jobs": totals})

    # Coverage check: months far below their neighbours
    gaps = []
    for i, n in enumerate(totals):
        window = [totals[k] for k in range(max(0, i - 6), min(len(totals), i + 7)) if k != i]
        med = statistics.median(window) if window else 0
        if med and n < GAP_RATIO * med:
            gaps.append({"month": months[i], "jobs": n, "neighbour_median": int(med)})

    # 2. Topics per month
    topics = con.execute("SELECT concept, grp FROM concepts ORDER BY grp, concept").fetchall()
    tdata = {c: {"title": [0] * len(months), "any": [0] * len(months)} for c, _ in topics}
    for c, m, t, a in con.execute("""
            SELECT h.concept, strftime(j.m, '%Y-%m'), sum(h.in_title::INT), count(*)
            FROM concept_hits h JOIN j ON j.id = h.job_id GROUP BY 1, 2""").fetchall():
        if c in tdata:
            tdata[c]["title"][idx[m]] = int(t)
            tdata[c]["any"][idx[m]] = int(a)
    write("topics.json", {"months": months,
                          "topics": [{"topic": c, "group": g, **tdata[c]} for c, g in topics]})

    # 3. Organisations per month (top N by total jobs; latest name used for renamed orgs)
    con.execute("""CREATE TEMP TABLE jo AS
        SELECT DISTINCT o.job_id, o.org_id, j.m
        FROM job_orgs o JOIN j ON j.id = o.job_id WHERE o.org_id IS NOT NULL""")
    top = con.execute(f"""
        SELECT o.org_id, arg_max(o.org_name, j.m), arg_max(o.org_shortname, j.m), count(DISTINCT o.job_id) AS n
        FROM job_orgs o JOIN j ON j.id = o.job_id WHERE o.org_id IS NOT NULL
        GROUP BY 1 ORDER BY n DESC LIMIT {TOP_ORGS}""").fetchall()
    ids = [t[0] for t in top]
    oseries = {i: [0] * len(months) for i in ids}
    for oid, m, n in con.execute("""
            SELECT org_id, strftime(m, '%Y-%m'), count(*) FROM jo
            WHERE org_id IN (SELECT unnest(?)) GROUP BY 1, 2""", [ids]).fetchall():
        oseries[oid][idx[m]] = int(n)
    orgs = [{"id": oid, "name": name, "short": short, "total": int(n), "jobs": oseries[oid]}
            for oid, name, short, n in top]
    write("orgs.json", {"months": months, "orgs": orgs})

    # 4. Org x topic x year (compact rows: [org_index, topic_index, year, title, any])
    top2 = ids[:TOP_ORGS_TOPICS]
    oi = {oid: k for k, oid in enumerate(top2)}
    ti = {c: k for k, (c, _) in enumerate(topics)}
    rows = [[oi[o], ti[c], int(y), int(t), int(a)] for o, c, y, t, a in con.execute("""
            SELECT jo.org_id, h.concept, year(jo.m), sum(h.in_title::INT), count(*)
            FROM jo JOIN concept_hits h ON h.job_id = jo.job_id
            WHERE jo.org_id IN (SELECT unnest(?)) GROUP BY 1, 2, 3""", [top2]).fetchall() if c in ti]
    org_years = [[oi[o], int(y), int(n)] for o, y, n in con.execute("""
            SELECT org_id, year(m), count(*) FROM jo
            WHERE org_id IN (SELECT unnest(?)) GROUP BY 1, 2""", [top2]).fetchall()]
    write("org_topics.json", {"orgs": [o["name"] for o in orgs[:TOP_ORGS_TOPICS]],
                              "topics": [c for c, _ in topics],
                              "columns": ["org", "topic", "year", "title", "any"],
                              "rows": rows,
                              "org_year_totals": org_years})

    # 4b. Org x topic x month for the most recent months, all top orgs (for "who is hiring for what" cards)
    #     rows: [org_index into orgs.json, topic_index, month_index into "months" below, title, any]; title > 0 only
    recent = months[-RECENT_MONTHS:]
    ridx = {m: k for k, m in enumerate(recent)}
    ai = {oid: k for k, oid in enumerate(ids)}
    rrows = [[ai[o], ti[c], ridx[m], int(t), int(a)] for o, c, m, t, a in con.execute("""
            SELECT jo.org_id, h.concept, strftime(jo.m, '%Y-%m'), sum(h.in_title::INT), count(*)
            FROM jo JOIN concept_hits h ON h.job_id = jo.job_id
            WHERE jo.org_id IN (SELECT unnest(?)) AND strftime(jo.m, '%Y-%m') >= ?
            GROUP BY 1, 2, 3 HAVING sum(h.in_title::INT) > 0""", [ids, recent[0]]).fetchall() if c in ti and m in ridx]
    write("org_topics_recent.json", {"months": recent,
                                     "columns": ["org", "topic", "month", "title", "any"],
                                     "rows": rrows})

    # 4c. Role dimensions straight from ReliefWeb fields (no text matching): jobs per month by
    #     experience band, job type, organisation type and career category.
    #     job_meta / org_types are filled by harvest.py (backfill once with: python harvest.py --meta).
    have = {t for (t,) in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    dims = {}

    def dim(name, sql):
        d = {}
        for v, m, n in con.execute(sql).fetchall():
            if v is not None and m in idx:
                d.setdefault(v, [0] * len(months))[idx[m]] = int(n)
        dims[name] = [{"name": k, "jobs": d[k]} for k in sorted(d, key=lambda k: -sum(d[k]))]

    if "job_meta" in have:
        dim("experience", """SELECT x.experience, strftime(j.m, '%Y-%m'), count(*)
                             FROM job_meta x JOIN j ON j.id = x.job_id GROUP BY 1, 2""")
        dim("job_type", """SELECT x.job_type, strftime(j.m, '%Y-%m'), count(*)
                           FROM job_meta x JOIN j ON j.id = x.job_id GROUP BY 1, 2""")
    if "orgs" in have and INCOME_FILE.exists():
        # ReliefWeb's types, with NGOs split by where they are based (docs/data/ORG_CLASSIFICATION.md).
        # A job posted by organisations of two classes counts once for each.
        con.execute("CREATE TEMP TABLE org_class (org_id BIGINT, cls VARCHAR)")
        con.executemany("INSERT INTO org_class VALUES (?, ?)", list(classify_orgs(con).items()))
        dim("org_type", """SELECT k.cls, strftime(jo.m, '%Y-%m'), count(DISTINCT jo.job_id)
                           FROM jo JOIN org_class k ON k.org_id = jo.org_id GROUP BY 1, 2""")
    elif "org_types" in have:
        dim("org_type", """SELECT t.org_type, strftime(jo.m, '%Y-%m'), count(DISTINCT jo.job_id)
                           FROM jo JOIN org_types t ON t.org_id = jo.org_id GROUP BY 1, 2""")
    dim("career_category", """SELECT c.category, strftime(j.m, '%Y-%m'), count(DISTINCT c.job_id)
                              FROM job_categories c JOIN j ON j.id = c.job_id GROUP BY 1, 2""")
    tagged = series(con.execute("""SELECT strftime(j.m, '%Y-%m'), count(DISTINCT c.job_id)
                                   FROM job_categories c JOIN j ON j.id = c.job_id GROUP BY 1""").fetchall())
    write("roles.json", {"months": months, "dims": dims, "career_category_tagged": tagged})

    # 5. Flat yearly tables matching the design doc's data contract (CSV, one row per record)
    last_year = int(months[-1][:4])
    last_full = last_year if months[-1].endswith("-12") else last_year - 1
    write_csv("totals_by_year.csv", ["year", "n_posts", "months_covered"], con.execute("""
        SELECT year(m), count(*), count(DISTINCT m) FROM j GROUP BY 1 ORDER BY 1""").fetchall())
    write_csv("topic_year.csv", ["topic", "group", "year", "n_title_hits", "n_body_hits", "n_any_hits"], con.execute("""
        SELECT h.concept, c.grp, year(j.m), sum(h.in_title::INT), sum(h.in_body::INT), count(*)
        FROM concept_hits h JOIN j ON j.id = h.job_id JOIN concepts c USING (concept)
        GROUP BY 1, 2, 3 ORDER BY 1, 3""").fetchall())
    names = {oid: name for oid, name, _, _ in top}
    write_csv("org_year.csv", ["org", "org_id", "year", "n_posts"], [
        (names[o], o, int(y), int(n)) for o, y, n in con.execute("""
            SELECT org_id, year(m), count(DISTINCT job_id) FROM jo
            WHERE org_id IN (SELECT unnest(?)) GROUP BY 1, 2 ORDER BY 1, 2""", [ids]).fetchall()])
    tilt = []
    for p0, p1 in sorted({(2019, 2022), (last_full - 3, last_full)}):
        for o, c, n_org, t, a, at, aa, n_all in con.execute("""
                WITH jp AS (SELECT id FROM j WHERE year(m) BETWEEN ? AND ?),
                tot AS (SELECT count(*) AS n FROM jp),
                allh AS (SELECT concept, sum(in_title::INT) AS t, count(*) AS a
                         FROM concept_hits h JOIN jp ON jp.id = h.job_id GROUP BY 1),
                op AS (SELECT org_id, count(DISTINCT job_id) AS n FROM jo
                       WHERE year(m) BETWEEN ? AND ? AND org_id IN (SELECT unnest(?)) GROUP BY 1),
                oh AS (SELECT jo.org_id, h.concept, sum(h.in_title::INT) AS t, count(*) AS a
                       FROM jo JOIN concept_hits h ON h.job_id = jo.job_id
                       WHERE year(jo.m) BETWEEN ? AND ? AND jo.org_id IN (SELECT unnest(?)) GROUP BY 1, 2)
                SELECT oh.org_id, oh.concept, op.n, oh.t, oh.a, allh.t, allh.a, tot.n
                FROM oh JOIN op USING (org_id) JOIN allh USING (concept), tot
                WHERE op.n >= ?""", [p0, p1, p0, p1, ids, p0, p1, ids, MIN_ORG_POSTS]).fetchall():
            for metric, k, K in (("title", t, at), ("any", a, aa)):
                if k and K:
                    os_, as_ = k / n_org, K / n_all
                    tilt.append((names[o], c, f"{p0}-{p1}", metric, int(n_org), int(k),
                                 round(os_, 6), round(as_, 6), round(os_ / as_, 3)))
    write_csv("org_topic_tilt.csv", ["org", "topic", "period", "metric", "n_org_posts", "n_org_topic_posts",
                                     "org_share", "all_share", "tilt"], tilt)

    # 6. Metadata
    write("meta.json", {
        "generated": dt.date.today().isoformat(),
        "first_month": months[0], "last_month": months[-1],
        "total_jobs": sum(totals),
        "last_year_partial": not months[-1].endswith("-12"),
        "possible_gaps": gaps,
        "rules": [
            "ReliefWeb API jobs only; current incomplete month excluded.",
            "title = topic matched in the job title; any = matched in title or description.",
            "Jobs with several organisations count once for each.",
        ]})
    con.close()

    # 7. Everything in one script file, so the page also works opened straight from disk
    p = OUT / "data.js"
    p.write_text("window.RW_DATA = " + json.dumps(BUNDLE, separators=(",", ":"), ensure_ascii=False) + ";\n",
                 encoding="utf-8")
    print(f"  {'data.js':<18} {p.stat().st_size / 1024:>8,.0f} KB  (what index.html loads)")

    print(f"\n{sum(totals):,} jobs, {months[0]} to {months[-1]}, {len(topics)} topics, {len(orgs)} orgs")
    if gaps:
        print("\nPossible data gaps (check before trusting trends):")
        for g in gaps:
            print(f"  {g['month']}: {g['jobs']:,} jobs vs ~{g['neighbour_median']:,} in neighbouring months")


if __name__ == "__main__":
    main()