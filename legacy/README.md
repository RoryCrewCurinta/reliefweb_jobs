# Legacy keyword matching (retired November 2026)

`match.py` matched job ads against regular expressions in `topics.csv` and wrote the `concept_hits` table. `check.py` sampled its matches for review.

Retired because a review of 2,985 sampled matches (`review/matching_review.md`) found keyword matching on full descriptions too noisy. Topics now come from the language-model tagging in `llm_pilot/` (table `llm_topics`).

Kept for the record and because `llm_pilot/build_sample.py` and `review/` refer to `concept_hits`. Nothing in the routine runs these files. The `concept_hits` table stays in the database but is no longer updated.
