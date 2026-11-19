# ReliefWeb hiring trends

What the humanitarian sector hires for, year by year: every job post on ReliefWeb since June 2011, tagged against 65 topics in 9 groups, plus hiring by organisation and country. A Curinta project.

**Dashboard:** https://trendlines.curinta.com/

## How it works

1. `harvest.py` pulls job posts from the ReliefWeb API v2 into a local DuckDB database (`reliefweb_jobs.duckdb`, not in Git).
2. `strip.py` removes template text organisations repeat across their ads (equal-opportunity statements, benefits, legal clauses).
3. `llm_pilot/` has a language model (GPT-6 Luna) read each ad and tag it against the topic list in `review/topics_v2_definitions.csv` (see `llm_pilot/README.md`).
4. `export.py` writes small summary files to `docs/data/`, which the dashboard (`docs/index.html`) reads; `pages.py` rebuilds the Methodology, Glossary and About pages.

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
python harvest.py --update                 # monthly top-up
python strip.py --update                   # clean new and changed ads
python llm_pilot/build_all.py              # write all ads for tagging (a few minutes)
python llm_pilot/classify.py run --model gpt-6-luna --source all --workers 20 --max-usd 5   # tags only ads not yet done
python llm_pilot/classify.py load --model gpt-6-luna --source all
python export.py                           # refresh dashboard data
python pages.py                            # refresh Methodology, Glossary and About
python og_image.py                         # rebuild the LinkedIn preview card to match
python backup.py                           # after each harvest
```

Then commit and push; Cloudflare republishes the dashboard from `docs/` at https://trendlines.curinta.com/. If `og_image.py` changed the card, paste the URL into https://www.linkedin.com/post-inspector/ so LinkedIn drops its cached copy.

## Topics

The topic list, with definitions, is `review/topics_v2_definitions.csv`; the model is given it word for word. Changing a definition puts earlier tags out of date. The older regex matching (`match.py`, `topics.csv`) is retired and kept in `legacy/`.

## Caveats

Counts are advertised posts on ReliefWeb, not hires, and not all humanitarian hiring. Some organisations stopped posting to ReliefWeb (UNICEF almost entirely from mid-2020), which affects topic mix. Use shares, not counts, for trends.

Source: ReliefWeb (reliefweb.int), used under ReliefWeb's terms.

## Stories

Scrolling stories are hand-built pages in `docs/`, one per story, linked from the Stories item in the nav and the Latest story card on the dashboard. Each is a fixed snapshot of the data on the day it was built: `pages.py` does not generate them and the routine above does not change them.

- **Where the cuts bit** (16 Nov 2026): `docs/where-the-cuts-bit.html`, live at trendlines.curinta.com/where-the-cuts-bit. Build files, sources and rules are in [`stories/where-the-cuts-bit`](stories/where-the-cuts-bit/README.md).

The Stories nav link is set in `pages.py` (sub-pages) and by hand in `docs/index.html` (dashboard). When a second story is added, build a stories index page and point the link there.

## One-off analyses

- **Organisation specialisms** (18 Nov 2026): `python org_specialisms.py` finds what each organisation hires for far more than the sector does, for every organisation with 20 or more ads and across all years (the dashboard's topic concentration covers only the 150 largest and two four-year windows). It reads the database read-only and writes `org_specialisms_all.csv` and `org_specialisms_shortlist.csv` to `Claude outputs/` (git-ignored). Method and thresholds are in the docstring at the top of the script. First used for the LinkedIn post "We didn't know they hired for that!"; the animation for it and the script that draws it are also in `Claude outputs/`.
