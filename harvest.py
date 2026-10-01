"""
Harvest ReliefWeb jobs (incl. expired) into reliefweb_jobs.duckdb.

Usage:
  pip install duckdb requests
  python harvest.py --appname YOUR-APPROVED-APPNAME            # full backfill 2011->today
  python harvest.py --appname YOUR-APPROVED-APPNAME --update   # only jobs changed since last run

Pages month by month (avoids deep-offset limits) and upserts, so it is safe to
stop and re-run at any time. API rows replace the body-less Power BI rows.
"""
import argparse, time, datetime as dt
import duckdb, requests

API = "https://api.reliefweb.int/v2/jobs"
DB = "reliefweb_jobs.duckdb"
FIELDS = ["id", "title", "body", "url", "status", "date.created", "date.closing",
          "date.changed", "source.name", "source.shortname", "source.id",
          "country.name", "career_categories.name", "theme.name"]


def fetch_window(appname, field, start, end):
    offset = 0
    while True:
        payload = {
            "preset": "analysis",  # includes expired jobs
            "limit": 1000, "offset": offset,
            "fields": {"include": FIELDS},
            "filter": {"field": field, "value": {"from": start.isoformat() + "+00:00",
                                                  "to": end.isoformat() + "+00:00"}},
            "sort": [f"{field}:asc", "id:asc"],
        }
        for attempt in range(5):
            r = requests.post(API, params={"appname": appname}, json=payload, timeout=120)
            if r.status_code == 200:
                break
            print(f"  HTTP {r.status_code}: {r.text[:200]} (retry {attempt+1})")
            time.sleep(10 * (attempt + 1))
        r.raise_for_status()
        data = r.json()
        rows = data.get("data", [])
        yield from (row["fields"] for row in rows)
        offset += len(rows)
        if offset >= data.get("totalCount", 0) or not rows:
            return
        time.sleep(1)  # be polite


def upsert(con, recs):
    if not recs:
        return
    ids = [r["id"] for r in recs]
    con.execute("BEGIN")
    for t, c in [("jobs", "id"), ("job_orgs", "job_id"), ("job_countries", "job_id"),
                 ("job_categories", "job_id"), ("job_themes", "job_id")]:
        con.execute(f"DELETE FROM {t} WHERE {c} IN (SELECT unnest(?))", [ids])
    con.executemany("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?, 'api_v2')", [
        (r["id"], r.get("title"), r.get("body"), r.get("date", {}).get("created"),
         r.get("date", {}).get("closing"), r.get("date", {}).get("changed"),
         r.get("status"), r.get("url")) for r in recs])
    con.executemany("INSERT INTO job_orgs VALUES (?,?,?,?)",
                    [(r["id"], s.get("name"), s.get("shortname"), s.get("id"))
                     for r in recs for s in r.get("source", [])])
    for t, key in [("job_countries", "country"), ("job_categories", "career_categories"),
                   ("job_themes", "theme")]:
        con.executemany(f"INSERT INTO {t} VALUES (?,?)",
                        [(r["id"], x.get("name")) for r in recs for x in r.get(key, [])])
    con.execute("COMMIT")


def months(start, end):
    d = start
    while d < end:
        n = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        yield d, min(n, end) - dt.timedelta(seconds=1)
        d = n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--appname", required=True)
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--start", default="2011-01-01")
    a = ap.parse_args()
    con = duckdb.connect(DB)
    con.execute(open("schema.sql").read())
    now = dt.datetime.utcnow().replace(microsecond=0)

    if a.update:
        last = con.execute("SELECT max(date_changed) FROM jobs WHERE data_source='api_v2'").fetchone()[0]
        field, start = "date.changed", (last or dt.datetime(2011, 1, 1))
    else:
        field, start = "date.created", dt.datetime.fromisoformat(a.start)

    for s, e in months(start, now):
        recs = list(fetch_window(a.appname, field, s, e))
        upsert(con, recs)
        print(f"{s:%Y-%m}: {len(recs):>5} jobs")
    print(con.execute("SELECT data_source, count(*) FROM jobs GROUP BY 1").fetchall())
    con.close()


if __name__ == "__main__":
    main()
