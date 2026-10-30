"""C(t) sheets for the 40 evaluation tools: what the CODE does, labelled by hand
to measure the detector (RQ1). Same tools as labeling/d_labels_v1/d_eval_40_*.

Annotators get the tool name and links to the code at the scanned commit, with
no annotations, description or detector output. Columns and values come from
make_labeling_sample.py (the same labels as labeling/sample_v1).

Usage: python make_c_eval_40.py
"""
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_labeling_sample import RESULTS, annotator_row, write_xlsx  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "labeling/d_labels_v1"
OUT = ROOT / "labeling/c_labels_v1"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    key = {f"sample_400:{r['id']}": r for r in csv.DictReader(open(ROOT / "labeling/sample_v1/sample_400_key.csv", encoding="utf-8"))}
    ids = (D / "d_eval_40_ids.txt").read_text(encoding="utf-8").split()

    rows, missing = [], []
    for n, tid in enumerate(ids, 1):
        k = key[tid]
        path = RESULTS / f"{k['repo'].replace('/', '__')}.jsonl"
        match = None
        for line in open(path, encoding="utf-8"):
            t = json.loads(line)
            if (t["tool"] or "") == k["tool"] and t.get("entry") and t.get("annotations_kind") not in ("none", "unresolved"):
                match = t
                break
        if match is None:
            missing.append(tid)
            continue
        row = annotator_row(n, match)
        row["id"] = tid
        rows.append(row)
    if missing:
        raise SystemExit(f"no scan record for: {missing}")
    for who in ("tasneem", "menna"):
        write_xlsx(OUT / f"c_eval_40_{who}.xlsx", rows, "c_eval_40")
    print(f"{len(rows)} tools -> {OUT}")


if __name__ == "__main__":
    main()
