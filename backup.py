"""
Back up reliefweb_jobs.duckdb as a zipped Parquet snapshot.

Setup - add one line to .env (no quotes):
  BACKUP_DIR=C:\\path\\to\\your\\SharePoint\\folder

Usage:
  python backup.py      # run after each harvest; keeps the newest 3 backups

Restore:
  1. Unzip the newest backup into an empty folder, e.g. C:\\restore
  2. python -c "import duckdb; duckdb.connect('reliefweb_jobs.duckdb').execute(\"IMPORT DATABASE 'C:/restore'\")"
     (run in a folder with no existing reliefweb_jobs.duckdb)
"""
import datetime as dt
import os
import tempfile
import zipfile
from pathlib import Path

import duckdb
from dotenv import load_dotenv

load_dotenv()
DB = "reliefweb_jobs.duckdb"
KEEP = 3
PREFIX = "reliefweb_jobs_"


def main():
    dest = os.environ.get("BACKUP_DIR")
    if not dest:
        raise SystemExit("No BACKUP_DIR in .env - add BACKUP_DIR=C:\\path\\to\\folder")
    dest = Path(dest)
    if not dest.is_dir():
        raise SystemExit(f"BACKUP_DIR not found: {dest}")

    name = f"{PREFIX}{dt.datetime.now():%Y%m%d_%H%M}.zip"

    with tempfile.TemporaryDirectory() as tmp:
        export = Path(tmp) / "export"

        # 1. Export every table to compressed Parquet (read-only: fails if a harvest is running)
        try:
            con = duckdb.connect(DB, read_only=True)
        except duckdb.IOException as e:
            raise SystemExit(f"Database is in use (is harvest.py still running?)\n{e}")
        n_jobs = con.execute("SELECT count(*) FROM jobs").fetchone()[0]
        print(f"Exporting {n_jobs:,} jobs...")
        con.execute(f"EXPORT DATABASE '{export.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")

        # 2. Sanity check: exported jobs table has the same row count
        pq = export / "jobs.parquet"
        if pq.exists():
            n_pq = con.execute(f"SELECT count(*) FROM read_parquet('{pq.as_posix()}')").fetchone()[0]
            if n_pq != n_jobs:
                raise SystemExit(f"Row count mismatch: db {n_jobs:,} vs export {n_pq:,} - backup aborted")
        con.close()

        # 3. Zip (Parquet is already compressed, so store rather than re-deflate)
        local_zip = Path(tmp) / name
        with zipfile.ZipFile(local_zip, "w", zipfile.ZIP_STORED) as z:
            for f in sorted(export.rglob("*")):
                if f.is_file():
                    z.write(f, f.relative_to(export))

        # 4. Copy under a temporary name, then rename, so SharePoint never syncs a half-written file
        part = dest / (name + ".part")
        with open(local_zip, "rb") as src, open(part, "wb") as out:
            while chunk := src.read(16 * 1024 * 1024):
                out.write(chunk)
        os.replace(part, dest / name)

    size_mb = (dest / name).stat().st_size / 1e6
    print(f"Saved {dest / name} ({size_mb:,.0f} MB)")

    # 5. Prune: keep the newest KEEP backups (only after the new one succeeded)
    backups = sorted(dest.glob(f"{PREFIX}*.zip"))
    for old in backups[:-KEEP]:
        old.unlink()
        print(f"Removed old backup {old.name}")


if __name__ == "__main__":
    main()
