"""Score model results against the regex review labels, and against a second model.

Run from the repo root:
  python llm_pilot/score.py                               Luna against review/review_labels.csv
  python llm_pilot/score.py --compare gpt-5.6-terra       Luna against a stronger model on the ads both have read

Reading the first table: each review label says whether an old regex match for a topic was genuine
or false. The model "agrees" when it tags that topic core, duty or skill for a genuine match, and
mention or nothing for a false one. The review labels were made by reviewer agents reading about
440 characters round the match, so this is agreement between two imperfect judges, not accuracy.
"""
import argparse
import collections
import csv
import json
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "llm_pilot"))
from classify import apply_rules  # the same fixed rules (core-only, parent topics) for every model
DATA = ROOT / "llm_pilot" / "data"
ap = argparse.ArgumentParser()
ap.add_argument("--model", default="gpt-5.6-luna")
ap.add_argument("--compare", default="")
ap.add_argument("--positive", default="core,duty,skill", help="levels that count as 'the job involves this'")
a = ap.parse_args()
POS = set(a.positive.split(","))


def load(model):
    out = {}
    for line in open(DATA / f"results_{model}.jsonl", encoding="utf-8"):
        r = json.loads(line)
        out[r["id"]] = {t["topic"]: t["level"] for t in apply_rules(r["topics"])}
    return out


def pct(n, d):
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "0/0"


res = load(a.model)
print(f"{a.model}: {len(res)} ads classified\n")

if a.compare:
    other = load(a.compare)
    both = sorted(set(res) & set(other))
    strong = {"core", "duty"}
    mine = {(i, t) for i in both for t, l in res[i].items() if l in strong}
    theirs = {(i, t) for i in both for t, l in other[i].items() if l in strong}
    same_level = sum(1 for i, t in mine & theirs if res[i][t] == other[i][t])
    print(f"Ads read by both models: {len(both)}. Counting core and duty tags only.")
    print(f"  {a.compare} tags that {a.model} also has: {pct(len(mine & theirs), len(theirs))}")
    print(f"  {a.model} tags that {a.compare} also has: {pct(len(mine & theirs), len(mine))}")
    print(f"  of the shared tags, same level (core vs duty): {pct(same_level, len(mine & theirs))}")
    miss = collections.Counter(t for _, t in theirs - mine).most_common(8)
    extra = collections.Counter(t for _, t in mine - theirs).most_common(8)
    print(f"  topics {a.model} misses most: {miss}\n  topics {a.model} adds most: {extra}")
    raise SystemExit

topics = list(csv.DictReader(open(ROOT / "review" / "topics_v2_definitions.csv", encoding="utf-8-sig")))
old2new = collections.defaultdict(list)
for t in topics:
    for o in t["replaces"].split(";"):
        if o.strip():
            old2new[o.strip()].append(t["topic"])

cells = collections.Counter()   # (hit, label, level)
per_topic = collections.defaultdict(collections.Counter)
skipped = collections.Counter()
for r in csv.DictReader(open(ROOT / "review" / "review_labels.csv", encoding="utf-8-sig")):
    jid = int(r["job_id"])
    if r["label"] not in ("genuine", "false"):
        skipped["ambiguous label"] += 1
    elif r["old_topic"] not in old2new:
        skipped["old topic not in new list"] += 1
    elif jid not in res:
        skipped["ad not classified yet"] += 1
    else:
        for new in old2new[r["old_topic"]]:
            level = res[jid].get(new, "none")
            cells[(r["hit"], r["label"], level)] += 1
            agree = (level in POS) == (r["label"] == "genuine")
            per_topic[new][(r["label"], agree)] += 1

print("Left out:", dict(skipped), "\n")
levels = ["core", "duty", "skill", "mention", "none"]
print(f"{'match type':<11}{'review said':<13}" + "".join(f"{l:>9}" for l in levels) + "   model agrees")
tot_ok = tot = 0
for hit in ("title", "body_only"):
    for label in ("genuine", "false"):
        row = [cells[(hit, label, l)] for l in levels]
        ok = sum(row[:3]) if label == "genuine" else sum(row[3:])
        ok = sum(n for l, n in zip(levels, row) if (l in POS) == (label == "genuine"))
        tot_ok, tot = tot_ok + ok, tot + sum(row)
        print(f"{hit:<11}{label:<13}" + "".join(f"{n:>9}" for n in row) + f"   {pct(ok, sum(row))}")
print(f"\nOverall agreement: {pct(tot_ok, tot)} (levels counted as positive: {sorted(POS)})")

out = DATA / f"score_by_topic_{a.model}.csv"
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["topic", "genuine_n", "genuine_model_agrees", "false_n", "false_model_agrees"])
    for t in sorted(per_topic):
        c = per_topic[t]
        w.writerow([t, c[("genuine", True)] + c[("genuine", False)], c[("genuine", True)],
                    c[("false", True)] + c[("false", False)], c[("false", True)]])
print(f"Per-topic counts written to {out.relative_to(ROOT)} (small numbers per topic: read with care)")
