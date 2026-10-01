# ReliefWeb hiring trends: data for the dashboard

Produced by `export.py` from a local DuckDB of every ReliefWeb job post since 2011 (ReliefWeb API v2, expired posts included). Curinta product; no CALP or Power BI branding or references.

Regenerate with `python export.py`. Never hand-edit these files.

## Rules baked into every file

- **API rows only.** The legacy Power BI snapshot is not used. The "2023 snapshot vs API harvest" coverage strip in the design doc is obsolete: the harvest is complete.
- **Series start in June 2011.** Earlier months are the ReliefWeb jobs archive starting up (a few dozen posts a month), not hiring.
- **The current month is dropped**, so series never end in a false cliff. The latest **year** is usually partial: check `months_covered` in `totals_by_year.csv` or `last_year_partial` in `meta.json`, and show it as partial (dashed or labelled).
- **Two counting rules for topics.** Keep them separate and label them:
  - `title`: the topic is in the job title. The role *is* the topic. Cleaner; the default.
  - `any`: in the title or the description. The role *mentions* the topic. Broader and noisier.
  - `n_body_hits` = matched in the description. A job can be a title hit and a body hit.
- **Shares, not counts, for trends.** Divide topic hits by `n_posts` for the same period, otherwise falls in total posting (for example the 2025 USAID cuts) look like topic declines.
- **Template text is stripped before matching.** Sentences an organisation repeats across many different job titles (equal-opportunity statements, benefits, legal clauses) are removed first.
- **Multi-organisation posts** count once for each organisation.
- **Missing rows mean zero.** A topic, organisation or year with no hits has no row.

## Files

| File | One row per | Columns |
|---|---|---|
| `totals_by_year.csv` | year | `year, n_posts, months_covered` |
| `topic_year.csv` | topic × year | `topic, group, year, n_title_hits, n_body_hits, n_any_hits` |
| `org_year.csv` | organisation × year (150 largest posters) | `org, org_id, year, n_posts` |
| `org_topic_tilt.csv` | organisation × topic × period × metric | `org, topic, period, metric, n_org_posts, n_org_topic_posts, org_share, all_share, tilt` |
| `meta.json` | – | generated date, first/last month, total jobs, `possible_gaps`, rules |
| `totals.json`, `topics.json`, `orgs.json`, `org_topics.json` | monthly versions | month axis in `months`; series aligned to it |
| `data.js` | – | all JSON files in one `window.RW_DATA` object, for pages opened from disk |

**Tilt:** `org_share / all_share` for the same period and metric. 2 means the organisation hires for the topic twice as often as the sector. Periods are `2019-2022` and the last four complete years. Only organisations with at least 50 posts in the period are included. Filter on `n_org_topic_posts` too (suggest 10 or more) before showing a tilt: small counts give extreme ratios.

## Display cautions

- **Unusual months** are listed in `meta.json` → `possible_gaps`. December 2025 (726 posts, about half the usual) has been checked against the API and is complete: ReliefWeb really did carry that few. The cause (a hiring freeze, or organisations posting elsewhere) can't be told from this data, so show it without explaining it. Shares are less affected than counts.
- **Minimum volume.** Don't rank or headline a topic on fewer than about 20 posts per period. Watchlist topics (group `Watchlist (emerging)`) are small: show counts, label them as signals.
- **Topics still under review** for description-matching precision: Health, Partnerships & capacity strengthening, Protection (general), Resilience. Prefer `title` for these until checked. Compliance and Education descriptions now count only specific terms; Gender `any` measures how often gender is mainstreamed into job ads, not gender roles.
- **Renames are already merged** within topics (CTP→CVA, OFDA/FFP→BHA, DFID→FCDO), so they won't show up as trends.
- Counts are **advertised posts on ReliefWeb**, not hires, and not all humanitarian hiring. Some organisations moved recruitment to their own portals; a collapse in one organisation's volume may mean that rather than a hiring freeze.

## Dashboard design (Curinta brand)

- Colours: blue `#408ADE` (dark mode `#4C95E6`), grey `#4D4D4D`. Fonts: Space Grotesk (headings, numbers), IBM Plex Sans (body).
- Chart series order, checked for colour-blind safety in light and dark: blue `#408ADE`, orange `#eb6834`, aqua `#1baf7a`, yellow `#eda100`, magenta `#e87ba4`, violet `#4a3aa7`. Six series per chart at most.
- Part-years (first and last) are drawn dashed. Topic charts default to share of posts and title matches.
- Current build: https://claude.ai/artifact/AiCisY6vBrRpMc65RxLznq (posts per year, topic trends by group, rising/falling 2015–18 vs 2022–25, organisation explorer with topic tilt, method and cautions).

Source attribution: ReliefWeb (reliefweb.int), used under ReliefWeb's terms.