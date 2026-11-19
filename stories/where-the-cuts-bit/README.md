# Story one: Where the cuts bit

The files that build `docs/where-the-cuts-bit.html`, live at
https://trendlines.curinta.com/where-the-cuts-bit since 16 Nov 2026.

The page is a **fixed snapshot** of the data to end Oct 2026 (export of 3 Nov 2026).
`pages.py` does not generate it and the monthly refresh does not change it.
Nothing here runs as part of the routine in the main README.

## Files

| File | What it is |
|---|---|
| `template.html` | The page: text, styles and chart code. Numbers in the text are `{{placeholders}}`. |
| `data.py` | Reads the dashboard export and the funding data; writes `snapshot.json` and `facts.json`. |
| `build.py` | Fills the template and writes the page. |
| `snapshot.json` | The series the charts draw, as built on 16 Nov 2026. |
| `facts.json` | Every number quoted in the text, as built on 16 Nov 2026. |
| `inputs/iha_2019_2025.json` | Public and private funding figures used for the 2019 and 2020 estimate. |

## To change the wording only

Edit `template.html`, then from the repo folder:

    python stories\where-the-cuts-bit\build.py stories\where-the-cuts-bit docs\about.html docs\where-the-cuts-bit.html

This reuses the saved `snapshot.json` and `facts.json`, so no figure changes.
The banner, favicon, signup box and menu script are lifted from `docs/about.html`.

## To rebuild the figures

Only do this on purpose: it re-reads the current export, so every number on the page
moves to the latest data and the story stops being the snapshot that was published.

    git clone https://github.com/ALNAP-Comms/gha_2026 ..\gha_2026
    python stories\where-the-cuts-bit\data.py docs ..\gha_2026\analyses stories\where-the-cuts-bit\snapshot.json stories\where-the-cuts-bit\inputs\iha_2019_2025.json

Then run `build.py` as above. `data.py` prints the figures it computed.

## Sources

- **Job adverts:** the dashboard export in `docs/data` (totals.json, roles.json,
  country_year.csv, topic_year.csv, meta.json).
- **Funding, 2021 to 2025:** ALNAP, Global Humanitarian Assistance Report 2026, published
  chart data (`fig-1.1-total_iha.csv`), constant 2024 prices. 2025 is preliminary.
- **Funding, 2019 and 2020:** an estimate. ALNAP publishes no constant-price total before
  2021. The estimate is public donors in constant 2024 prices, plus private funding in
  current prices scaled by the public donors' own deflator (constant divided by current).
  Run on 2021 to 2025, the method lands within 0.6% of the published totals. The inputs
  come from ALNAP's analysis workbook, not its public chart data, so check before putting
  `inputs/` in any public copy of this repo.
- **2026 funding scenarios and recipient changes:** the same ALNAP chart data
  (`fig-1.2-scenarios.csv`, `fig-2.1-recipients.csv`).

## Numbers typed by hand in the template

Everything else is computed. These are not, so check them if the data changes:

- Palestine up 15% and Myanmar up 11% in 2025, and "18 of the 20 largest recipients" (ALNAP fig 2.1).
- "Nineteen fell by half or more" in the first countries step.
- "a third fewer in one month" (January to February 2025).
- The US pause on foreign assistance, 20 January 2025, and the fall of the Assad government, December 2024.
- The 30% and 64% on the dashboard's Latest story card in `docs/index.html`.

## Rules the page follows

- Topics are counted as core tags. The big-topics chart takes topics with 300 or more adverts
  in 2022; the smaller-topics chart takes those under 300 with at least 50 in 2022 or 2025.
- Countries are the 20 with the most adverts in 2022. Organisation types need 500 or more in 2022.
- No organisation is named, only organisation types.
- Evidence and interpretation are kept apart: "My reading" boxes are inference,
  "Treat with care" boxes are caveats.

## Still open (16 Nov 2026)

- Syria: how many organisations account for the rise has not been checked.
- The page names two cash figures (CVA down 78%, multi-purpose cash down 80%). The rollout
  notes say to hold CVA findings until the Curinta and CALP separation is settled.
- A stories index page, when there is a second story.
