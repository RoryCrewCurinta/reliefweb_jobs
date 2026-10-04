# LLM topic tagging

A cheap model (OpenAI GPT-6 Luna) reads job ads and tags each with topics from
`review/topics_v2_definitions.csv` at a level: core, duty, skill or mention. Core is the headline measure.

| File | What it does |
|---|---|
| `prompt.md` | The instructions sent to the model. The topic list is filled in from the CSV. |
| `classify.py` | `dry-run`, `models`, `run`, `show`, `batch-submit`, `batch-fetch`, `load`, `spend` |
| `score.py` | Agreement with `review/review_labels.csv`, or with a second model (`--compare`) |
| `build_sample.py` | Picks the 5,000-ad pilot sample into `data/sample.parquet` |
| `build_all.py` | Writes every ad to `data/all_ads.parquet`, in random order, for the full run |

Fixed rules applied in code to every result (`apply_rules` in `classify.py`): four topics are core-only
(Partnerships, Needs assessment, Safety & security, Compliance); a specialist topic adds its parent
(Health, CVA).

Full run:

    python llm_pilot/build_all.py
    python llm_pilot/classify.py run --model gpt-6-luna --source all --workers 20 --max-usd 20

Needs `OPENAI_API_KEY=...` in `.env`. `data/` is git-ignored. If the topic CSV or the prompt changes,
results made before the change are out of date.
