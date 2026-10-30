"""The 40-tool D(t) evaluation set, enriched for rare effects.

Random samples hold few delete / execute / network tools (in the 100-tool set:
9 delete, 6 execute), too few to measure agreement or accuracy on the
effects that drive the inconsistency rules. This set takes 10 tools per
stratum, using the CODE detector's effects (not anything about the
description, so annotators stay blind):
  execute  the detector found an execute effect
  delete   the detector found a delete effect (and no execute)
  network  the detector found a network effect (and neither of the above)
  other    none of the three
Tools come from the 100-tool set first (no description proposals exist for
them); a stratum short of 10 is topped up from the other 300 of the
400-tool sample. One tool per owner, a description required. Each tool's
inclusion probability within its stratum is recorded: the set is for
measuring agreement and accuracy, not prevalence.

Usage: python make_d_eval_40.py [--seed 40]
"""
import argparse
import csv
import glob
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_d_labeling import write_sheet  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "labeling/d_labels_v1"
STRATA = ["execute", "delete", "network", "other"]
PER = 10


def stratum(cats):
    for s in ("execute", "delete", "network"):
        if s in cats:
            return s
    return "other"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=40)
    rng = random.Random(ap.parse_args().seed)

    key = {f"sample_400:{r['id']}": r for r in csv.DictReader(open(ROOT / "labeling/sample_v1/sample_400_key.csv", encoding="utf-8"))}
    ev = set((D / "d_eval_100_ids.txt").read_text(encoding="utf-8").split())
    ws = openpyxl.load_workbook(D / "d_sample_400_menna.xlsx").active
    desc = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        desc.setdefault(r[1], (r[2], r[3], r[4] or ""))
    want = {(k["repo"], k["tool"]): tid for tid, k in key.items()}
    cats = defaultdict(set)
    for p in glob.glob(str(ROOT / "data/results/scan/*.jsonl")):
        for line in open(p, encoding="utf-8"):
            t = json.loads(line)
            tid = want.get((t["repo"], t["tool"]))
            if tid:
                cats[tid] |= {e["category"] for e in t.get("effects", [])}

    usable = [t for t in key if desc[t][2] and not desc[t][2].startswith("(no description")]
    pools = defaultdict(lambda: {"eval": [], "rest": []})
    for t in usable:
        pools[stratum(cats[t])]["eval" if t in ev else "rest"].append(t)

    picked, owners, meta = [], set(), {}
    for s in STRATA:
        got = []
        for src in ("eval", "rest"):
            pool = pools[s][src][:]
            rng.shuffle(pool)
            for t in pool:
                o = key[t]["repo"].split("/")[0].lower()
                if len(got) == PER or o in owners:
                    continue
                got.append(t)
                owners.add(o)
                meta[t] = (s, src)
        size = len(pools[s]["eval"]) + len(pools[s]["rest"])
        for t in got:
            meta[t] += (round(len(got) / size, 4),)
        picked += got
    rng.shuffle(picked)  # strata mixed, so the order reveals nothing

    tools = [(t, *desc[t]) for t in picked]
    for who in ("tasneem", "menna"):
        write_sheet(D / f"d_eval_40_{who}.xlsx", tools)
    (D / "d_eval_40_ids.txt").write_text("\n".join(picked) + "\n", encoding="utf-8")
    with open(D / "d_eval_40_key.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tool_id", "repo", "tool", "stratum", "drawn_from", "inclusion_prob_in_stratum"])
        for t in picked:
            s, src, prob = meta[t]
            w.writerow([t, key[t]["repo"], key[t]["tool"], s, "eval_100" if src == "eval" else "other_300", prob])
    print(f"{len(picked)} tools, {len({key[t]['repo'] for t in picked})} repos")
    print("strata:", dict(Counter(meta[t][0] for t in picked)))
    print("drawn from:", dict(Counter(meta[t][1] for t in picked)))
    print("languages:", dict(Counter(key[t]["language"] for t in picked)))


if __name__ == "__main__":
    main()
