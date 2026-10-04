"""
Harvest ReliefWeb jobs (incl. expired) into reliefweb_jobs.duckdb.

Setup:
  pip install -r requirements.txt
  Put your approved appname in .env (never committed):
    RELIEFWEB_APPNAME=your-approved-appname

Usage:
  python harvest.py            # full backfill 2011->today
  python harvest.py --update   # only jobs changed since last run
  python harvest.py --start 2020-01-01
  python harvest.py --orgs     # refresh the organisation list only (type and home country); seconds
  python harvest.py --meta     # one-off: fill job type, experience, city and organisation type
                               # for jobs already in the database (no descriptions pulled, so quick)

Pages month by month (avoids deep-offset limits) and upserts, so it is safe to
stop and re-run at any time. API rows replace the body-less Power BI rows.
"""
import argparse
import datetime as dt
import os
import time

import duckdb
import requests
from dotenv import load_dotenv

load_dotenv()
APPNAME = os.environ.get("RELIEFWEB_APPNAME")

API = "https://api.reliefweb.int/v2/jobs"
SOURCES_API = "https://api.reliefweb.int/v2/sources"
DB = "reliefweb_jobs.duckdb"
FIELDS = ["id", "title", "body", "url", "status", "date.created", "date.closing",
          "date.changed", "source.name", "source.shortname", "source.id",
          "country.name", "career_categories.name", "theme.name",
          "source.type.name", "type.name", "experience.name", "city.name"]
# --meta pulls only these (plus source.id to attach the organisation type)
META_FIELDS = ["id", "source.id", "source.type.name", "type.name", "experience.name", "city.name"]


def fetch_window(appname, field, start, end, fields=FIELDS):
    offset = 0
    while True:
        payload = {
            "preset": "analysis",  # includes expired jobs
            "limit": 1000, "offset": offset,
            "fields": {"include": fields},
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
    upsert_meta(con, recs, own_transaction=False)
    con.execute("COMMIT")


def first_name(r, key):
    """ReliefWeb returns these as short lists; keep the first name, or None."""
    v = r.get(key) or []
    return v[0].get("name") if v else None


def upsert_meta(con, recs, own_transaction=True):
    """Job type, experience, city (job_meta) and organisation type (org_types)."""
    if not recs:
        return
    ids = [r["id"] for r in recs]
    org = {}
    for r in recs:
        for s in r.get("source", []):
            t = (s.get("type") or {}).get("name")
            if s.get("id") is not None and t:
                org[s["id"]] = t
    if own_transaction:
        con.execute("BEGIN")
    con.execute("DELETE FROM job_meta WHERE job_id IN (SELECT unnest(?))", [ids])
    con.executemany("INSERT INTO job_meta VALUES (?,?,?,?)", [
        (r["id"], first_name(r, "type"), first_name(r, "experience"), first_name(r, "city"))
        for r in recs])
    if org:
        con.execute("DELETE FROM org_types WHERE org_id IN (SELECT unnest(?))", [list(org)])
        con.executemany("INSERT INTO org_types VALUES (?,?)", list(org.items()))
    if own_transaction:
        con.execute("COMMIT")


def refresh_orgs(con, appname):
    """ReliefWeb's own record of every organisation: type and home country (table: orgs)."""
    recs, offset = [], 0
    while True:
        payload = {"preset": "analysis", "limit": 1000, "offset": offset, "sort": ["id:asc"],
                   "fields": {"include": ["id", "name", "shortname", "status", "type.name",
                                          "country.name", "country.iso3"]}}
        r = requests.post(SOURCES_API, params={"appname": appname}, json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()
        rows = data.get("data", [])
        recs += [row["fields"] for row in rows]
        offset += len(rows)
        if offset >= data.get("totalCount", 0) or not rows:
            break
        time.sleep(1)
    if not recs:
        return
    con.execute("BEGIN")
    con.execute("DELETE FROM orgs")
    con.executemany("INSERT INTO orgs VALUES (?,?,?,?,?,?,?)", [
        (o["id"], o.get("name"), o.get("shortname"), (o.get("type") or {}).get("name"),
         "; ".join(c.get("name") or "" for c in o.get("country", [])) or None,
         ";".join((c.get("iso3") or "").upper() for c in o.get("country", [])) or None,
         o.get("status")) for o in recs])
    con.execute("COMMIT")
    print(f"orgs: {len(recs):,} organisations (type and home country)")


def months(start, end):
    d = start
    while d < end:
        n = (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        yield d, min(n, end) - dt.timedelta(seconds=1)
        d = n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--appname", default=APPNAME,
                    help="Override; defaults to RELIEFWEB_APPNAME from .env")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--start", default="2011-01-01")
    ap.add_argument("--orgs", action="store_true",
                    help="Only refresh the organisation list (type and home country)")
    ap.add_argument("--meta", action="store_true",
                    help="Only fill job type, experience, city and organisation type (no descriptions)")
    a = ap.parse_args()
    if not a.appname:
        ap.error("No appname: add RELIEFWEB_APPNAME=... to .env")

    con = duckdb.connect(DB)
    con.execute(open("schema.sql").read())
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0)

    if a.orgs:
        refresh_orgs(con, a.appname)
        con.close()
        return

    if a.meta:
        # Backfill of the extra fields only. Does not touch jobs, descriptions or topic matches.
        for s, e in months(dt.datetime.fromisoformat(a.start), now):
            recs = list(fetch_window(a.appname, "date.created", s, e, META_FIELDS))
            upsert_meta(con, recs)
            print(f"{s:%Y-%m}: {len(recs):>5} jobs")
        print("job type:  ", con.execute("SELECT job_type, count(*) FROM job_meta GROUP BY 1 ORDER BY 2 DESC").fetchall())
        print("experience:", con.execute("SELECT experience, count(*) FROM job_meta GROUP BY 1 ORDER BY 2 DESC").fetchall())
        print("org type:  ", con.execute("SELECT org_type, count(*) FROM org_types GROUP BY 1 ORDER BY 2 DESC").fetchall())
        refresh_orgs(con, a.appname)
        con.close()
        return

    if a.update:
        last = con.execute("SELECT max(date_changed) FROM jobs WHERE data_source='api_v2'").fetchone()[0]
        field, start = "date.changed", (last or dt.datetime(2011, 1, 1))
    else:
        field, start = "date.created", dt.datetime.fromisoformat(a.start)

    for s, e in months(start, now):
        recs = list(fetch_window(a.appname, field, s, e))
        upsert(con, recs)
        print(f"{s:%Y-%m}: {len(recs):>5} jobs")
    refresh_orgs(con, a.appname)
    print(con.execute("SELECT data_source, count(*) FROM jobs GROUP BY 1").fetchall())
    con.close()


if __name__ == "__main__":
    main()