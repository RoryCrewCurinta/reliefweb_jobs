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
