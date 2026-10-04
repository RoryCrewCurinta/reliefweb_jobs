# Handover: classify ReliefWeb job ads with a language model (Luna pilot)

Written 3 Oct 2026 for a new thread. Owner: Rory Crew (Curinta). Paste this in, or point the new thread at this file.

## Goal of the new thread

Set up and run a pilot that has a cheap language model (OpenAI GPT-5.6 Luna) read job ads and tag each with topics from the new 62-topic list, at a level: **core** (the job is this), **duty**, **skill** or **mention**. Then score it against existing labels and decide whether to run it on all ads.

## The project in five lines

- Dashboard of ReliefWeb job posts: what the humanitarian sector hires for. Curinta-branded. No CALP or Power BI references.
- Folder: `C:\Users\rcrew\reliefweb_jobs` (Windows, VS Code, `.venv`). GitHub: `RoryCrewCurinta/reliefweb_jobs`. Dashboard: `docs/index.html`, reads `docs/data/data.js`.
- Database: `reliefweb_jobs.duckdb` (about 8 GB, local only). 516,428 jobs, Jun 2011 – Sep 2026, with full descriptions.
- Pipeline: `harvest.py` (ReliefWeb API v2) → `strip.py` (removes repeated boilerplate into `jobs_clean.body_clean`) → `match.py` (regex topics from `topics.csv` into `concept_hits`) → `export.py` (writes `docs/data/`).
- Secrets live in `.env` (git-ignored): `RELIEFWEB_APPNAME`. Add `OPENAI_API_KEY` there for the pilot. Never commit `.env`.

## Why we are doing this

A review of 2,985 sampled regex matches found:

- Title matches are about 97% genuine. Description-only matches are about 39% genuine (weighted by volume).
- Description noise is mostly organisation sector lists, mission blurbs, equal-opportunity and safeguarding-policy wording, funder lines and passing mentions.
- Many topics (interoperability, MPCA, cash coordination, anticipatory action) rarely appear in titles, so titles alone miss them.

So regex on full descriptions is not good enough, and titles alone are too narrow.

## Decisions already made

- Audience: sector analysts.
- New topic list: 62 topics in 9 groups with definitions (`review/topics_v2_definitions.csv`). Not yet wired into the pipeline; search patterns not yet written for it.
- Functions come from ReliefWeb's own career category field (complete from 2018). Funding & donors group dropped.
- Dashboard default stays on title matches until description matching is trustworthy.
- API costs go on a personal account, separate from the work Claude subscription.

## Plan for the pilot

1. **Account:** personal OpenAI account, prepaid credit (about $5 is plenty), key in `.env` as `OPENAI_API_KEY`.
2. **Sample:** 5,000 ads spread across years, languages (EN/FR/ES) and topics, with extra thin topics. Include the ads behind `review/review_labels.csv` so results can be scored.
3. **Input text:** ideally only the Responsibilities and Requirements sections. A section splitter (headings in EN/FR/ES) does not exist yet. For a first look, send `jobs_clean.body_clean`.
4. **Prompt:** the 62 topics with definitions, includes and excludes; a fixed JSON answer: for each relevant topic, the level and the sentence that justifies it.
5. **Test** on 20–50 ads and read the answers before the full run.
6. **Run:** live calls (about $3, finishes in the session; new accounts have low rate limits) or Batch API (about $1.50, up to 24 hours).
7. **Score** against `review_labels.csv`, and against a stronger model (Claude Sonnet 5.5 or GPT-5.6 Terra) on the same 300 ads (about $2).
8. **Decide:** if Luna agrees about 90% on core and duty labels, run it on every ad (roughly $150 by batch). If not, label 5,000 with the stronger model (about $15–20) and train a local embedding classifier instead.

Prices checked 2 Oct 2026 (per million tokens, batch): Luna $0.10 in / $0.60 out; Terra $1 / $6; Claude Sonnet 5.5 $1 / $5; Haiku 4.5 $0.50 / $2.50. Re-check before spending. Cost figures above are estimates.

## Files to use (all in `C:\Users\rcrew\reliefweb_jobs\review\`)

| File | What it is |
|---|---|
| `topics_v2_definitions.csv` | The new 62-topic list: group, topic, definition, includes, excludes, standard, old topics replaced, old match counts |
| `review_labels.csv` | 2,985 regex matches judged genuine / false / ambiguous by review agents, with job id, old topic, matched text and context. The test set. |
| `matching_review.md` | Findings of the regex review |
| `proposed_changes.csv`, `strip_phrases.csv` | Regex fixes and stock phrases (not yet applied) |
| `precision_by_topic.csv` | Sample accuracy per old topic |
| `reliefweb_fields.csv` | ReliefWeb fields that need no matching (career category, job type, etc.) and their status |

`review_labels.csv` uses the **old** 94 topic names; `topics_v2_definitions.csv` has a `replaces` column that maps old to new.

## Database tables that matter

- `jobs` (id, title, body, date_created, url, data_source; use `data_source = 'api_v2'`)
- `jobs_clean` (id, body_clean): description with repeated boilerplate removed
- `job_orgs`, `job_countries`, `job_categories` (career category), `job_themes`
- `concept_hits` (job_id, concept, in_title, in_body): current regex results
- Suggested new table for model output: `llm_topics` (job_id, topic, level, evidence, model, run_date)

## Not done yet

- Section splitter (Responsibilities / Requirements).
- Search patterns for the 62-topic list; regex bug fixes from the review.
- `harvest.py` does not pull job type, experience or organisation type (available in the API).
- UNICEF stopped posting to ReliefWeb in mid-2020; an "exclude UNICEF" view was proposed, not built.

## Practical gotchas

- A Claude session can reach the folder only while the laptop is awake and linked. It runs commands in a Linux workspace on the laptop, where `duckdb` had to be pip-installed; the Windows `.venv` is not usable from there. Long jobs must be split into steps under about 3 minutes.
- Keep Windows line endings when editing the `.py` files, or Git shows every line as changed.
- If a Claude session runs `git status` on the repo it can leave `.git/index.lock`; delete it if Git complains.
- Paste git commands one at a time in VS Code.
