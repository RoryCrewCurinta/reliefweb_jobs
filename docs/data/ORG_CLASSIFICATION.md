# How organisations are classified

ReliefWeb gives every organisation one type: Non-governmental Organization, International Organization, Government, Red Cross/Red Crescent Movement, Academic and Research Institution, Media or Other. It does not say whether an NGO is international or national.

The dashboard keeps ReliefWeb's types and splits the NGOs into three classes, using each NGO's home country (as ReliefWeb records it) and where its jobs are.

The full mapping, one row per organisation, is in [`org_classification.csv`](org_classification.csv). It is rebuilt every time `export.py` runs.

## The rule

| Class | Rule |
|---|---|
| **International NGO** | Home country is high-income (World Bank), or the home is not a country in the World Bank list (for example "World"). |
| **Locally based NGO** | Home country is low- or middle-income, **and** at least 80% of the NGO's posts that carry a country are in that home country. |
| **Regional NGO (global South base)** | Home country is low- or middle-income, but fewer than 80% of its located posts are there: it works across several countries. |
| NGO (home country unknown) | ReliefWeb lists no home country. A handful of small organisations. |

Two adjustments:

- **NGOs based in Türkiye or Syria are always locally based.** The Syria response is run largely by Syrian and Turkish NGOs registered in Türkiye that work across the border and sometimes post for neighbouring countries. They are local to that response, so the 80% test is not applied to them. (For the share shown in the mapping, Türkiye and Syria are counted as one home.)
- **Manual corrections** for well-known misfits, each with a reason, in [`ref/org_class_overrides.csv`](../../ref/org_class_overrides.csv). Examples: Oxfam and ActionAid (global confederations whose secretariats are in Nairobi and Johannesburg), country offices of international NGOs, and CGIAR research centres that ReliefWeb types as NGOs.

## Why "locally based" and not "national"

The rule is a proxy. It finds NGOs that are based in a low- or middle-income country and hire almost entirely there. Most are national NGOs, but the class also includes:

- country chapters and affiliates of international networks that are registered locally;
- international NGOs that happen to be headquartered in the country where they work;
- Syrian NGOs registered in Türkiye.

And it misses national NGOs in high-income countries (for example a Greek or Polish NGO responding at home), which fall under International NGO.

## Inputs

| Input | Source | File |
|---|---|---|
| Organisation type and home country | ReliefWeb API, `sources` endpoint | database table `orgs`, refreshed by `harvest.py` |
| Country of each job | ReliefWeb API, `jobs` endpoint | database table `job_countries` |
| Income group of each country | World Bank country classification (API, fetched 4 Oct 2026) | [`ref/wb_income_levels.csv`](../../ref/wb_income_levels.csv) |
| Manual corrections | Reviewed by hand | [`ref/org_class_overrides.csv`](../../ref/org_class_overrides.csv) |

Settings are at the top of `export.py`: `HOME_SHARE` (0.8), `HOME_PAIRS` and `ALWAYS_LOCAL_HOMES` (Türkiye and Syria).

## Columns in `org_classification.csv`

`org_id`, `organisation`, `reliefweb_type`, `home_country`, `home_income_level`, `posts`, `posts_with_country`, `share_of_posts_in_home_country`, `class`, `basis` (ReliefWeb type, rule, or manual override) and `reason` (the rule that fired, or the reason for the override).

## Result on 4 October 2026

| Class | Organisations | Posts |
|---|---|---|
| International NGO | 2,448 | 323,650 |
| Locally based NGO | 849 | 14,194 |
| Regional NGO (global South base) | 222 | 7,517 |
| NGO (home country unknown) | 7 | 107 |

Locally based NGOs were 1.4% of all ReliefWeb posts in 2012, 2.3% in 2019 and about 5% in 2025 and 2026.

## Limits

- **ReliefWeb is mainly where international organisations advertise.** A small locally based share here does not show that national NGOs hire little; most of their recruitment happens elsewhere.
- **Only the largest misfits have been checked by hand:** roughly the 45 biggest organisations in the locally based and regional classes. Smaller ones are classified by the rule alone.
- **Home country is ReliefWeb's record**, usually the headquarters. It can be out of date or reflect a secretariat rather than where the organisation started.
- **Income groups change.** The World Bank list is a snapshot; re-fetch it occasionally.
- **Small organisations with one or two posts** pass or fail the 80% test on very little evidence.

To change a classification, add a row to `ref/org_class_overrides.csv` (organisation id, name, class, reason) and re-run `export.py`.
