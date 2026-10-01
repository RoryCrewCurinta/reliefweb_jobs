# ReliefWeb hiring trends

What the humanitarian sector hires for, year by year: every job post on ReliefWeb since June 2011, matched against 94 topics in 9 groups, plus hiring by organisation. A Curinta project.

**Dashboard:** https://rorycrewcurinta.github.io/reliefweb_jobs/

## How it works

1. `harvest.py` pulls job posts from the ReliefWeb API v2 into a local DuckDB database (`reliefweb_jobs.duckdb`, not in Git).
2. `strip.py` removes template text organisations repeat across their ads (equal-opportunity statements, benefits, legal clauses).
3. `match.py` applies the topic list in `topics.csv` to job titles and descriptions.
4. `export.py` writes small summary files to `docs/data/`, which the dashboard (`docs/index.html`) reads.

Data files, counting rules and display cautions: [`docs/data/README.md`](docs/data/README.md).

## Setup (Windows, VS Code)

```
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Put your ReliefWeb appname in `.env` as `RELIEFWEB_APPNAME=...`. It is git-ignored; never commit it.

## Routine

```
python harvest.py --update    # monthly top-up
python match.py               # after harvesting or editing topics.csv
python check.py "Biometrics"  # 20 random matches; aim for 16+ genuine
python export.py              # refresh dashboard data
python backup.py              # after each harvest
```

Then commit and push; GitHub Pages republishes the dashboard from `docs/`.

## Topics

`topics.csv` has one row per pattern: `topic, group, pattern, case_sensitive, scope, exclude, note`. A job counts for a topic if any of its patterns match. Patterns are regular expressions; `exclude` phrases are removed before matching. Renamed terms are merged (CTP→CVA, OFDA/FFP→BHA, DFID→FCDO).

## Caveats

Counts are advertised posts on ReliefWeb, not hires, and not all humanitarian hiring. Some organisations stopped posting to ReliefWeb (UNICEF almost entirely from mid-2020), which affects topic mix. Use shares, not counts, for trends.

Source: ReliefWeb (reliefweb.int), used under ReliefWeb's terms.
