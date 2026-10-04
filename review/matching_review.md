# Topic matching review, October 2026

Seven reviewer agents read 2,985 sampled matches across all 94 topics: up to 12 title matches and 20 description-only matches per topic. They judged each one genuine or not, proposed fixes to `topics.csv`, and tested each fix against the sample. Seven challenger agents then re-tested every fix and rejected or corrected the weak ones.

## Headline

| Counting rule | Genuine in sample | Weighted by real volume |
|---|---|---|
| Title matches | 1,012 / 1,105 (92%) | **≈ 97%** |
| Description-only matches | 973 / 1,880 (52%) | **≈ 39%** |
| Title or description (the dashboard's "any") | | **≈ 43%** |

"Weighted" applies each topic's sample precision to its real number of matches, so the big, noisy topics count for more.

**Evidence:** title matching works for almost every topic. Description-only matches are wrong more often than right, and they make up 85–97% of most topics' "any" totals.

**Inference:** "Title or description" mostly measures how often organisations paste sector lists, mission blurbs and policy statements into ads, not what the job involves. Keep **Title** as the dashboard default. Don't present description counts as "demand for X" until the strip fixes below are in.

**Caveat:** each estimate rests on 12 title and 20 description samples per topic, so a single topic's precision has a margin of roughly ±20 points. The tests also ran on the ~440 characters around each match, not the full ad, so "false matches removed" counts are upper bounds.

## Where description matches fail

| Cause | Topics hit hardest |
|---|---|
| Organisation sector lists ("we work in health, nutrition, WASH, education, shelter…") that `strip.py` misses because wording drifts between ads | Education 0/20, Protection 1/20, Shelter 1/20, Health/Nutrition/WASH 4/20, CCCM, Agriculture, Livelihoods |
| Mission blurbs (IRC, UNHCR, HelpAge, HI, PIN, ACTED, RI) | Refugees, IDPs, Statelessness, Older people, Disability, Resilience |
| Recruitment and code-of-conduct wording ("regardless of age, disability…", "must sign the safeguarding policy") | Disability, Gender, LGBTQI+, Older people, Safeguarding, DEI, Compliance |
| Incidental mentions ("report to the security focal point", "capacity building" as a skill) | Partnerships & capacity strengthening 2/20, Security management 6/20, Audit & risk 9/20 |
| Funder lists ("our donors include…") | the donor topics, mildly |

## Bugs to fix whatever else happens

These are clear regex errors. Each fix was tested and lost no genuine matches, or one at most.

| Topic | Problem | Fix |
|---|---|---|
| Digital payments | `e[- ]?payments?` has no word boundary, so it matches "th**e payment**", "R**epayment**" (17/20 description matches false) | `\be[- ]?payments?\b` |
| MHPSS | "mental health" matches "environ**mental health**" | `\bmental health` |
| Child protection | "unaccompanied" mostly means an unaccompanied *duty station* | narrow to unaccompanied children/minors (see change list) |
| Biometrics | FBI fingerprint checks, statistics "biometry" | extended exclude (15 false removed, 0 lost) |
| Digital identity | "legal identity" turns it into civil-documentation (ICLA) work | delete that row |
| Digital public infrastructure | `\bDPI\b` / `\bDPG\b` match French *déplacés internes* and other things (23 false) | delete both acronym rows |
| Stablecoins & digital assets | "digital assets" = photos and video in comms jobs (30 false) | delete that row |
| AI & machine learning | Spanish/French "IA", "ST/AI/" UN document codes | narrower `l'IA` / `la IA` forms plus extra excludes |
| Localisation | "localisation du poste" (job location) | `\blocali[sz]ation` plus exclude |
| Conflict sensitivity | "do no harm" as a stock principle | scope=title |
| Environmental sustainability | French "environnement" (= any environment, e.g. "environnement Windows") | scope=title |
| Education | "education:" CV-requirements headings | already excluded; extend the exclude |
| Emergency telecoms | "connectivity" is generic; only 5/12 titles genuine | narrow to emergency/humanitarian connectivity or the cluster |
| Gender | the exclude misses the French plural "violences basées sur le genre" | extend the exclude |
| Financial inclusion | "SLA" = service level agreement | `\bVS&?LAs?\b` |

## The biggest single improvement: strip stock phrases for every organisation

`strip.py` removes sentences an organisation repeats *exactly*. The leaks above are near-duplicates and cross-organisation stock wording. The reviewers wrote 47 regexes for this (`strip_phrases.csv`). The highest-value one is the **sector-list** pattern, which on its own explains 45 false description matches across Health, Nutrition, WASH, Education, Shelter, Protection and Livelihoods.

Two ways forward, best first:

1. **Make `strip.py` fuzzy.** Match a sentence that is near-identical to one the same organisation has used before (normalised text, or the first ~12 words), not only exact repeats. This fixes mission blurbs and sector lists across all topics at once.
2. **Add a global stock-phrase list** to `strip.py`: the regexes in `strip_phrases.csv`, applied to every organisation before matching.

Either one needs a full re-run of `strip.py` and `match.py` (about 16 minutes for the match).

## Structural points

- **Supersets, so don't stack these in one chart:** CVA ⊃ MPCA; USAID ⊃ USAID BHA/OFDA/FFP; Health ⊃ SRHR, HIV/TB/malaria, Nutrition, Epidemics; AI ⊃ Generative AI.
- **Merges suggested:** Stablecoins → Blockchain & crypto (almost no signal of its own after the fix); Digital identity + Registration + Interoperability → one "ID & registration systems" topic; Emergency telecoms → a broader topic (84 title matches in 15 years).
- **Misplaced:** "Cash Coordinator" job titles at NGOs are internal CVA leads, not inter-agency coordination. "Shift the power" and "decolonisation" fit Localisation better than DEI.
- **Thin topics:** chart annually or as totals only. These include Area-based approaches (14 titles), Interoperability (25), Blockchain (19), Older people, LGBTQI+, Cash coordination, Digital payments, MPCA, the smaller donors, Humanitarian reset and DPI.
- **Organisation-driven topics:** Migration descriptions lean on IOM's name and mission text, Older people on HelpAge's, Disability on HI's. These counts show *who is hiring* rather than *what the role is*.
- **Muddled:** Philanthropy & private sector mixes major gifts, foundations, corporate partnerships and impact investing. A suggested rename is "Private & philanthropic fundraising".

## Files

- `precision_by_topic.csv`: every topic's sample counts, verdict and main false-match causes.
- `proposed_changes.csv`: 94 proposed `topics.csv` changes, sorted by recommendation.
  - **apply (47):** passed the challenger.
  - **apply corrected (check first) (42):** the challenger found a problem and wrote a fixed version. Check these quickly before using them.
  - **skip (5).**
  - `use_this` holds the regex to paste. Sample effect is shown as false matches removed and genuine matches lost.
- `strip_phrases.csv`: 47 stock-phrase regexes for `strip.py`, with examples and the topics they inflate.

## Suggested order

1. Apply the bug fixes in the table above (about 15 rows).
2. Make `strip.py` fuzzy, or add the stock-phrase list, then re-run strip and match.
3. Re-sample with the same script and check description precision again. A sensible bar before showing "Title or description" more prominently is ≥70% for the topics you headline.
4. Then work through the rest of `proposed_changes.csv`, merges and regrouping.
