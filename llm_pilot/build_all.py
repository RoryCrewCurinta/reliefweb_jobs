"""Write every job ad to llm_pilot/data/all_ads.parquet for the full classification run.

Run from the repo root:  python llm_pilot/build_all.py
Ads are stored in a fixed random order, so if the full run stops part-way the finished part is still a
fair sample of all ads. Ads with almost no text (under 200 characters) are left out.
"""
import os
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
TEST = "--test" in sys.argv  # one ad in a hundred, to check the script quickly
OUT = ROOT / "llm_pilot" / "data" / ("all_ads_test.parquet" if TEST else "all_ads.parquet")
con = duckdb.connect()
con.execute(f"ATTACH '{(ROOT / 'reliefweb_jobs.duckdb').as_posix()}' AS rw (READ_ONLY)")
con.execute("SET preserve_insertion_order = false")
if os.environ.get("DUCKDB_TMP"):
    con.execute(f"SET temp_directory = '{os.environ['DUCKDB_TMP']}'")
    con.execute("SET memory_limit = '2GB'")
print("writing all ads (this takes a few minutes) ...", flush=True)
con.execute(f"""
COPY (
  WITH orgs AS (
    SELECT job_id, string_agg(DISTINCT coalesce(nullif(org_shortname, ''), org_name), '; ') AS org
    FROM rw.job_orgs GROUP BY 1)
  SELECT j.id, year(j.date_created) AS year, j.title, o.org, c.body_clean
  FROM rw.jobs j JOIN rw.jobs_clean c USING (id) LEFT JOIN orgs o ON o.job_id = j.id
  WHERE j.data_source = 'api_v2' AND length(c.body_clean) >= 200 {'AND j.id % 100 = 0' if TEST else ''}
  ORDER BY hash(j.id, 42)
) TO '{OUT.as_posix()}' (FORMAT parquet, ROW_GROUP_SIZE 20000)
""")
n, chars = con.sql(f"SELECT count(*), avg(least(length(body_clean), 12000)) FROM read_parquet('{OUT.as_posix()}')").fetchone()
print(f"{n:,} ads written, about {chars / 4:,.0f} tokens of text each; file {OUT.stat().st_size / 1e6:,.0f} MB")
