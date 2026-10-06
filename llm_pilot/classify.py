"""Classify job ads against the topic list with an OpenAI model (GPT-5.6 Luna pilot).

Run from the repo root. Needs OPENAI_API_KEY in .env. Uses only the standard library and duckdb.

  python llm_pilot/classify.py dry-run             show the prompt, one request and a cost estimate (no API call)
  python llm_pilot/classify.py models              list model names your key can use
  python llm_pilot/classify.py run --limit 30      classify the first 30 sample ads live
  python llm_pilot/classify.py show --limit 30     print results in readable form
  python llm_pilot/classify.py run                 classify the whole sample live (resumes where it stopped)
  python llm_pilot/classify.py batch-submit        send what is left through the Batch API (half price, up to 24 h)
  python llm_pilot/classify.py batch-fetch         collect finished batches
  python llm_pilot/classify.py load                copy results into the llm_topics table in the database
  python llm_pilot/classify.py spend --credit 10   estimated spend so far and what is left of your prepaid credit

Full run on every ad (after python llm_pilot/build_all.py):
  python llm_pilot/classify.py run --source all --workers 16 --max-usd 20

Options: --model gpt-5.6-luna  --effort low  --workers 4  --limit N  --max-chars 12000  --tag NAME  --source sample|all  --max-usd X
Results go to llm_pilot/data/results_<model>.jsonl, one line per ad.
"""
import argparse
import csv
import datetime
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / "llm_pilot"
DATA = HERE / "data"
API = "https://api.openai.com/v1"
DROP_GROUPS = {"Funding & donors"}
LEVELS = ["core", "duty", "skill", "mention"]
# Topics kept only at core level; any other level the model gives them is dropped.
CORE_ONLY = {"Partnerships & partner capacity", "Needs assessment & analysis",
             "Safety & security management", "Compliance, audit & risk"}
# A specialist topic always counts under its parent too, at the same level or higher.
PARENTS = {"Sexual & reproductive health": "Health", "Epidemics & disease control": "Health",
           "Mental health & psychosocial support (MHPSS)": "Health",
           "Multi-purpose cash (MPCA)": "Cash & voucher assistance (CVA)",
           "Cash coordination": "Cash & voucher assistance (CVA)",
           "Group cash transfers": "Cash & voucher assistance (CVA)"}


def apply_rules(topics):
    """Fixed rules applied to every answer, whatever the model did: core-only topics and parent topics."""
    out = [dict(t) for t in topics if t["topic"] not in CORE_ONLY or t["level"] == "core"]
    for t in list(out):
        parent = PARENTS.get(t["topic"])
        if not parent:
            continue
        have = next((x for x in out if x["topic"] == parent), None)
        if have is None:
            out.append({"topic": parent, "level": t["level"], "evidence": t["evidence"]})
        elif LEVELS.index(t["level"]) < LEVELS.index(have["level"]):
            have["level"], have["evidence"] = t["level"], t["evidence"]
    return out
# USD per million tokens: (input, cached input, output). Checked 3 Oct 2026; re-check before a big run.
PRICES = {"gpt-5.6-luna": (0.20, 0.02, 1.20), "gpt-6-luna": (0.10, 0.01, 0.50),
          "gpt-5.6-terra": (2.00, 0.20, 12.00), "gpt-6.1-sol": (2.00, 0.10, 10.00),
          "gpt-6-astra": (10.00, 1.00, 50.00)}
BATCH_DISCOUNT = 0.5


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def api_key():
    key = os.environ.get("OPENAI_API_KEY", "")
    if not key:
        sys.exit("No OPENAI_API_KEY found. Add a line OPENAI_API_KEY=sk-... to .env in the repo root.")
    return key


def load_topics():
    rows = csv.DictReader(open(ROOT / "review" / "topics_v2_definitions.csv", encoding="utf-8-sig"))
    return [r for r in rows if r["group"] not in DROP_GROUPS]


def system_prompt(topics):
    lines, group = [], None
    for t in topics:
        if t["group"] != group:
            group = t["group"]
            lines.append(f"\n## {group}")
        s = f"- **{t['topic']}**: {t['definition']}"
        if t["includes"].strip():
            s += f" Includes: {t['includes'].strip()}."
        if t["emerging"].strip():
            s += f" Also: {t['emerging'].strip()}."
        if t["excludes"].strip():
            s += f" Excludes: {t['excludes'].strip()}."
        lines.append(s)
    return (HERE / "prompt.md").read_text(encoding="utf-8").replace("{{TOPICS}}", "\n".join(lines).strip())


def schema(topics):
    return {"type": "json_schema", "json_schema": {"name": "job_topics", "strict": True, "schema": {
        "type": "object", "additionalProperties": False, "required": ["topics"],
        "properties": {"topics": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["topic", "level", "evidence"],
            "properties": {"topic": {"type": "string", "enum": [t["topic"] for t in topics]},
                           "level": {"type": "string", "enum": LEVELS},
                           "evidence": {"type": "string"}}}}}}}}


def source_path(a):
    return DATA / ("all_ads.parquet" if a.source == "all" else "sample.parquet")


def suffix(a):
    return ("_all" if a.source == "all" else "") + ("_" + a.tag if a.tag else "")


def count_ads(a):
    n = duckdb.sql(f"SELECT count(*) FROM read_parquet('{source_path(a).as_posix()}')").fetchone()[0]
    return min(n, a.limit) if a.limit else n


def iter_ads(a, skip=()):
    """Ads from the source file in its stored order, a few thousand at a time, leaving out ids in skip."""
    if not source_path(a).exists():
        sys.exit(f"{source_path(a).name} not found. Run python llm_pilot/build_all.py first.")
    cur = duckdb.connect().execute(f"SELECT id, title, org, body_clean FROM read_parquet('{source_path(a).as_posix()}')"
                                   + (f" LIMIT {a.limit}" if a.limit else ""))
    while rows := cur.fetchmany(2000):
        for r in rows:
            if r[0] not in skip:
                yield dict(zip(("id", "title", "org", "text"), r))


def ads_by_id(a, ids):
    cur = duckdb.sql(f"SELECT id, title, org, body_clean FROM read_parquet('{source_path(a).as_posix()}') "
                     f"WHERE id IN ({','.join(str(int(i)) for i in ids) or 'NULL'})")
    return {r[0]: dict(zip(("id", "title", "org", "text"), r)) for r in cur.fetchall()}


def request_body(ad, sysmsg, fmt, a):
    text = ad["text"] if len(ad["text"]) <= a.max_chars else ad["text"][:a.max_chars] + "\n[text cut]"
    user = f"Job title: {ad['title']}\nOrganisation: {ad['org'] or 'unknown'}\n\nAdvertisement:\n{text}"
    body = {"model": a.model, "response_format": fmt, "max_completion_tokens": 4000,
            "messages": [{"role": "system", "content": sysmsg}, {"role": "user", "content": user}]}
    if a.effort != "default":
        body["reasoning_effort"] = a.effort
    return body


def http(method, path, payload=None, raw=None, headers=None, timeout=180):
    h = {"Authorization": f"Bearer {api_key()}"}
    data = raw
    if payload is not None:
        data, h["Content-Type"] = json.dumps(payload).encode(), "application/json"
    h.update(headers or {})
    req = urllib.request.Request(API + path, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


PACE = {"gap": 0.0, "next": 0.0, "ok": 0, "lock": threading.Lock()}  # shared by all workers


def wait_turn():
    """Space out request starts so all workers together stay under the account's rate limit."""
    with PACE["lock"]:
        now = time.time()
        start = max(now, PACE["next"])
        PACE["next"] = start + PACE["gap"]
    if start > now:
        time.sleep(start - now)


def slow_down(msg):
    """After a rate-limit reply, widen the gap between requests by a third. speed_up() narrows it again,
    so the pace settles just under whatever limit OpenAI is really applying."""
    with PACE["lock"]:
        PACE["ok"] = 0
        first = PACE["gap"] == 0
        PACE["gap"] = min(5.0, max(0.1, PACE["gap"] * 1.3))
        if first or time.time() - PACE.get("told", 0) > 300:
            PACE["told"] = time.time()
            print(f"  rate limit reached: now one request every {PACE['gap']:.2f}s (about {3600 / PACE['gap']:,.0f} "
                  f"ads an hour); the pace adjusts itself. OpenAI said: {' '.join(msg.split())[:200]}", flush=True)


def speed_up():
    """After 50 replies in a row with no rate-limit message, close the gap by 15%."""
    with PACE["lock"]:
        PACE["ok"] += 1
        if PACE["ok"] >= 50 and PACE["gap"] > 0:
            PACE["ok"] = 0
            PACE["gap"] = PACE["gap"] * 0.85 if PACE["gap"] > 0.05 else 0.0


def call(body, tries=12):
    for i in range(tries):
        wait_turn()
        try:
            reply = json.loads(http("POST", "/chat/completions", body))
            speed_up()
            return reply
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "replace")[:500]
            if e.code in (429, 500, 502, 503, 504) and "insufficient_quota" not in msg and i < tries - 1:
                if e.code == 429:
                    slow_down(msg)
                asked = float(e.headers.get("retry-after") or 0)
                time.sleep(min(90, max(asked, 2 ** i)) + random.random() * 2)
                continue
            raise RuntimeError(f"HTTP {e.code}: {msg}")
        except (urllib.error.URLError, TimeoutError) as e:
            if i == tries - 1:
                raise RuntimeError(str(e))
            wait = min(90, 2 ** i)
            print(f"  no reply ({e}); trying again in {wait}s", flush=True)
            time.sleep(wait)


def results_path(a):
    return DATA / f"results_{a.model}{suffix(a)}.jsonl"


def done_ids(a):
    p = results_path(a)
    ids = set()
    if p.exists():
        for line in open(p, encoding="utf-8"):
            try:
                ids.add(json.loads(line)["id"])
            except Exception:
                pass  # a half-written last line, if a run was cut off mid-save
    return ids


def to_record(ad_id, resp, a, via):
    ch = resp["choices"][0]
    u = resp.get("usage", {})
    rec = {"id": ad_id, "model": a.model, "effort": a.effort, "via": via,
           "run_date": datetime.date.today().isoformat(), "topics": None,
           "in": u.get("prompt_tokens", 0),
           "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
           "cache_write": (u.get("prompt_tokens_details") or {}).get("cache_write_tokens", 0),
           "out": u.get("completion_tokens", 0),
           "reasoning": (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)}
    try:
        rec["topics"] = apply_rules(json.loads(ch["message"]["content"])["topics"])
    except Exception:
        rec["error"] = f"unreadable answer (finish_reason={ch.get('finish_reason')}, refusal={ch['message'].get('refusal')})"
    return rec


def cost(recs, model):
    p_in, p_cached, p_out = PRICES.get(model, (0, 0, 0))
    usd = 0.0
    for r in recs:
        f = BATCH_DISCOUNT if r.get("via") == "batch" else 1.0
        write = r.get("cache_write", 0)  # tokens stored in the cache are billed at 1.25 times the input rate
        usd += f * ((r["in"] - r["cached"] + 0.25 * write) * p_in + r["cached"] * p_cached + r["out"] * p_out) / 1e6
    return usd


def cmd_dry_run(a):
    topics = load_topics()
    sysmsg, n = system_prompt(topics), count_ads(a)
    a2 = argparse.Namespace(**{**vars(a), "limit": min(n, 2000)})
    ads = list(iter_ads(a2))
    print(sysmsg)
    print("\n" + "=" * 70 + "\nFIRST REQUEST (user message):\n")
    print(request_body(ads[0], sysmsg, schema(topics), a)["messages"][1]["content"][:1500], "...")
    sys_tok = len(sysmsg) / 4
    ad_tok = sum(min(len(x["text"]), a.max_chars) + 80 for x in ads) / 4 / len(ads)
    p_in, p_cached, p_out = PRICES.get(a.model, (0, 0, 0))
    live = n * (sys_tok * p_cached + ad_tok * p_in + 350 * p_out) / 1e6
    worst = n * ((sys_tok + ad_tok) * p_in + 350 * p_out) / 1e6
    print("\n" + "=" * 70)
    print(f"{len(topics)} topics; {n:,} ads; model {a.model}; effort {a.effort}")
    print(f"prompt about {sys_tok:,.0f} tokens; ads about {ad_tok:,.0f} tokens each (rough: characters / 4)")
    print(f"estimated cost for all of them: ${live:,.2f} live with prompt caching, ${worst:,.2f} without, "
          f"about ${worst * BATCH_DISCOUNT:,.2f} by batch without caching. Output assumed at 350 tokens an ad.")


def cmd_models(a):
    ids = sorted(m["id"] for m in json.loads(http("GET", "/models"))["data"])
    print("\n".join(i for i in ids if "gpt-5" in i or "gpt-6" in i) or "\n".join(ids))


def cmd_run(a):
    topics = load_topics()
    sysmsg, fmt = system_prompt(topics), schema(topics)
    done, total = done_ids(a), count_ads(a)
    left = total - len(done)
    print(f"{len(done):,} already done, {left:,} to do, model {a.model}, effort {a.effort}, {a.workers} workers"
          + (f", stops at ${a.max_usd:g}" if a.max_usd < 1e9 else ""), flush=True)
    lock, errors, t0 = threading.Lock(), [], time.time()
    s = {"n": 0, "usd": 0.0, "in": 0, "cached": 0, "out": 0, "reasoning": 0}
    every = 100 if left <= 20000 else 1000
    out = open(results_path(a), "a", encoding="utf-8")

    def stop():
        return len(errors) >= 5 or time.time() - t0 > a.minutes * 60 or s["usd"] >= a.max_usd

    def work(ad):
        if stop():
            return
        try:
            rec = to_record(ad["id"], call(request_body(ad, sysmsg, fmt, a)), a, "live")
        except Exception as e:
            with lock:
                errors.append(str(e))
                print("  error:", str(e)[:300], flush=True)
            return
        with lock:
            if rec["topics"] is None:
                errors.append(rec["error"])
                print("  ad", ad["id"], rec["error"], flush=True)
                return
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out.flush()
            s["n"] += 1
            s["usd"] += cost([rec], a.model)
            for k in ("in", "cached", "out", "reasoning"):
                s[k] += rec[k]
            if s["n"] % every == 0:
                secs = time.time() - t0
                print(f"  {s['n']:,} done, ${s['usd']:.2f} so far, {secs:,.0f}s, "
                      f"about {(left - s['n']) * secs / s['n'] / 3600:,.1f} hours and "
                      f"${(left - s['n']) * s['usd'] / s['n']:,.2f} to go", flush=True)

    gate = threading.BoundedSemaphore(a.workers * 2)  # reads ads only as fast as the workers use them
    with ThreadPoolExecutor(a.workers) as ex:
        for ad in iter_ads(a, done):
            if stop():
                break
            gate.acquire()
            ex.submit(work, ad).add_done_callback(lambda f: gate.release())
    out.close()
    n = s["n"]
    if n:
        print(f"{n:,} classified in {time.time() - t0:,.0f}s. Cost ${s['usd']:.3f} "
              f"(${s['usd'] / n * 5000:.2f} per 5,000 at this rate).")
        print(f"Per ad: {s['in'] / n:,.0f} tokens in ({s['cached'] / n:,.0f} cached), "
              f"{s['out'] / n:,.0f} out ({s['reasoning'] / n:,.0f} reasoning).")
    if len(errors) >= 5:
        print("Stopped after 5 errors. Fix the cause and run again; finished ads are kept.")
    elif s["usd"] >= a.max_usd:
        print(f"Stopped at the ${a.max_usd:g} spending cap. Run again with a new --max-usd to continue.")
    elif n < left:
        print(f"{left - n:,} left. Run the same command again to continue.")


def cmd_show(a):
    recs = [json.loads(l) for l in open(results_path(a), encoding="utf-8")][:a.limit or None]
    ads = ads_by_id(a, [r["id"] for r in recs])
    bad = total = 0
    norm = lambda s: " ".join(s.lower().split())
    for r in recs:
        ad = ads[r["id"]]
        hay = norm(ad["title"] + " " + ad["text"])
        print(f"\n[{r['id']}] {ad['title']}  ({ad['org']})  https://reliefweb.int/node/{r['id']}")
        for t in sorted(r["topics"], key=lambda t: LEVELS.index(t["level"])):
            ev = norm(t["evidence"]).removeprefix("job title:").replace("…", "...")
            found = all(part.strip(' ."“”') in hay for part in ev.split("..."))
            total += 1
            bad += not found
            print(f"   {t['level']:<8}{t['topic']}\n           {'' if found else '(NOT IN AD) '}\"{t['evidence'][:220]}\"")
        if not r["topics"]:
            print("   (no topics)")
    print(f"\n{len(recs)} ads, {total} tags, {total / max(1, len(recs)):.1f} per ad; "
          f"{bad} evidence quotes not found word for word in the ad.")


def batches_file(a):
    return DATA / f"batches_{a.model}{suffix(a)}.json"


def cmd_batch_submit(a):
    topics = load_topics()
    sysmsg, fmt = system_prompt(topics), schema(topics)
    state = json.loads(batches_file(a).read_text()) if batches_file(a).exists() else []
    skip = done_ids(a) | {i for b in state if not b.get("fetched") for i in b["ids"]}
    ads = iter_ads(a, skip)
    for _ in range(a.chunks):
        part = [ad for _, ad in zip(range(a.chunk), ads)]
        if not part:
            print("nothing left to submit")
            break
        jsonl = "\n".join(json.dumps({"custom_id": str(ad["id"]), "method": "POST", "url": "/v1/chat/completions",
                                      "body": request_body(ad, sysmsg, fmt, a)}) for ad in part).encode()
        bnd = uuid.uuid4().hex
        form = (f'--{bnd}\r\nContent-Disposition: form-data; name="purpose"\r\n\r\nbatch\r\n'
                f'--{bnd}\r\nContent-Disposition: form-data; name="file"; filename="chunk.jsonl"\r\n'
                f'Content-Type: application/jsonl\r\n\r\n').encode() + jsonl + f"\r\n--{bnd}--\r\n".encode()
        try:
            fid = json.loads(http("POST", "/files", raw=form, timeout=600,
                                  headers={"Content-Type": f"multipart/form-data; boundary={bnd}"}))["id"]
            b = json.loads(http("POST", "/batches", {"input_file_id": fid, "endpoint": "/v1/chat/completions",
                                                     "completion_window": "24h"}))
        except urllib.error.HTTPError as e:
            print("  stopped:", e.code, e.read().decode("utf-8", "replace")[:400])
            print("  If this is the batch queue limit, wait for earlier chunks to finish, then run batch-submit again.")
            break
        state.append({"batch": b["id"], "ids": [ad["id"] for ad in part], "effort": a.effort,
                      "submitted": datetime.datetime.now().isoformat(timespec="seconds")})
        batches_file(a).write_text(json.dumps(state))
        print(f"  submitted {b['id']} ({len(part)} ads, {len(jsonl) / 1e6:.1f} MB)")


def cmd_batch_fetch(a):
    state = json.loads(batches_file(a).read_text()) if batches_file(a).exists() else []
    waiting = 0
    for b in state:
        if b.get("fetched"):
            continue
        info = json.loads(http("GET", f"/batches/{b['batch']}"))
        print(b["batch"], info["status"], info.get("request_counts"), "submitted", b.get("submitted", "?"))
        if info["status"] in ("failed", "expired", "cancelled"):
            print("  ", info.get("errors"))
            b["fetched"] = True  # frees these ads to be submitted again
        if info["status"] != "completed":
            waiting += info["status"] not in ("failed", "expired", "cancelled")
            continue
        a.effort, recs, failed = b.get("effort", a.effort), [], 0
        if info.get("output_file_id"):
            with open(results_path(a), "a", encoding="utf-8") as out:
                for line in http("GET", f"/files/{info['output_file_id']}/content", timeout=600).decode().splitlines():
                    row = json.loads(line)
                    if row.get("error") or row["response"]["status_code"] != 200:
                        failed += 1
                        continue
                    rec = to_record(int(row["custom_id"]), row["response"]["body"], a, "batch")
                    if rec["topics"] is not None:
                        out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        recs.append(rec)
        if info.get("error_file_id"):
            first = http("GET", f"/files/{info['error_file_id']}/content", timeout=600).decode().splitlines()[:1]
            print("   some requests failed, for example:", first[0][:400] if first else "")
        b["fetched"] = True
        if recs:
            n = len(recs)
            tin, tc = sum(r["in"] for r in recs), sum(r["cached"] for r in recs)
            print(f"   saved {n} of {len(b['ids'])} ({failed} failed), estimated cost ${cost(recs, a.model):.3f}")
            print(f"   per ad: {tin / n:,.0f} tokens in, {tc / n:,.0f} cached ({100 * tc / tin:.0f}% of input), "
                  f"{sum(r['out'] for r in recs) / n:,.0f} out; ads with no cached tokens: {sum(r['cached'] == 0 for r in recs)}")
    batches_file(a).write_text(json.dumps(state))
    print(f"{waiting} batch(es) still in progress." if waiting else "No batches waiting.")
    print("Ads that failed inside a batch are picked up by the next batch-submit or run.")


def cmd_spend(a):
    total, rows = 0.0, []
    for p in sorted(DATA.glob("results_*.jsonl")):
        groups = {}
        for line in open(p, encoding="utf-8"):
            r = json.loads(line)
            groups.setdefault((r["model"], r.get("via", "live")), []).append(r)
        for (model, via), recs in sorted(groups.items()):
            if model not in PRICES:
                rows.append(f"  {model:<16}{via:<7}{len(recs):>6} ads   no price known, not counted")
                continue
            usd = cost(recs, model)
            total += usd
            rows.append(f"  {model:<16}{via:<7}{len(recs):>6} ads   ${usd:8.3f}   "
                        f"{sum(r['in'] for r in recs) / 1e6:6.2f}M tokens in, {sum(r['out'] for r in recs) / 1e6:5.2f}M out")
    print("Estimated spend from the saved results (all runs):")
    print("\n".join(rows) or "  nothing yet")
    print(f"  total ${total:.3f}; starting credit ${a.credit:.2f}; estimated balance ${a.credit - total:.2f}")
    print("Estimate from token counts at list prices. It leaves out failed calls, results files you deleted")
    print("and batches not yet fetched. The real balance is on the billing page of the OpenAI platform site.")


def cmd_load(a):
    recs = [json.loads(l) for l in open(results_path(a), encoding="utf-8")]
    rows = [(r["id"], t["topic"], t["level"], t["evidence"], r["model"], r["run_date"])
            for r in recs for t in apply_rules(r["topics"])]
    con = duckdb.connect(str(ROOT / "reliefweb_jobs.duckdb"))
    con.execute("""CREATE TABLE IF NOT EXISTS llm_topics
        (job_id BIGINT, topic VARCHAR, level VARCHAR, evidence VARCHAR, model VARCHAR, run_date DATE)""")
    con.execute("CREATE TEMP TABLE new_rows AS SELECT * FROM llm_topics LIMIT 0")
    con.executemany("INSERT INTO new_rows VALUES (?, ?, ?, ?, ?, ?)", rows)
    con.execute("DELETE FROM llm_topics WHERE model = ? AND job_id IN (SELECT job_id FROM new_rows)", [a.model])
    con.execute("INSERT INTO llm_topics SELECT * FROM new_rows")
    print(f"llm_topics now holds {con.sql('SELECT count(*) FROM llm_topics').fetchone()[0]} rows "
          f"({len(rows)} from {len(recs)} ads by {a.model}). Ads with no topics have no rows.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["dry-run", "models", "run", "show", "batch-submit", "batch-fetch", "load", "spend"])
    ap.add_argument("--model", default="gpt-5.6-luna")
    ap.add_argument("--effort", default="low", help="reasoning effort: none, low, medium, high, or default")
    ap.add_argument("--limit", type=int, default=0, help="only the first N ads of the sample")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--minutes", type=float, default=1e9, help="stop a live run after this many minutes")
    ap.add_argument("--max-chars", type=int, default=12000, help="cut longer ads to this length")
    ap.add_argument("--tag", default="", help="suffix for the results file, to keep a test run apart")
    ap.add_argument("--credit", type=float, default=10.0, help="prepaid credit you started with, in USD")
    ap.add_argument("--chunk", type=int, default=600, help="ads per batch file")
    ap.add_argument("--chunks", type=int, default=1, help="how many batch files to submit in one go")
    ap.add_argument("--source", choices=["sample", "all"], default="sample",
                    help="sample = the 5,000-ad pilot sample; all = every ad (run build_all.py first)")
    ap.add_argument("--max-usd", type=float, default=1e9, help="stop a live run once it has spent this much")
    a = ap.parse_args()
    load_env()
    {"dry-run": cmd_dry_run, "models": cmd_models, "run": cmd_run, "show": cmd_show,
     "batch-submit": cmd_batch_submit, "batch-fetch": cmd_batch_fetch, "load": cmd_load,
     "spend": cmd_spend}[a.cmd](a)
