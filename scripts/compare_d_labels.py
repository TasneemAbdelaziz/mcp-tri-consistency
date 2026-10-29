"""Agreement between two D(t) label files in the claim-level schema.

Claims are not reduced to one status per effect (scopes are partly free text
and a tool can hold several claims with different actors and scopes). Instead
each tool x effect is compared on separate binary questions:

  affirmed_by_tool  is there an affirmed claim with actor = tool?  (what D<->A uses)
  uncertain_tool    is there an uncertain claim with actor = tool (and no affirmed)?
  denied_any_scope  is there a denied claim, at any scope?

For each: agreement, Cohen's kappa, and the disagreeing pairs.
Input files: CSV (Menna's export) or XLSX (the d_labels_v1 sheets).

Usage: python compare_d_labels.py A.csv|xlsx B.csv|xlsx
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

EFFECTS = ["read", "write", "delete", "execute", "network"]


def load(path):
    path = Path(path)
    if path.suffix == ".csv":
        rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    else:
        ws = openpyxl.load_workbook(path).active
        cols = [c.value for c in ws[1]]
        rows = [{k: ("" if v is None else str(v)) for k, v in zip(cols, r)} for r in ws.iter_rows(min_row=2, values_only=True)]
    by = defaultdict(list)
    for r in rows:
        if r.get("tool_id"):
            by[(r["tool_id"], r["effect"])].append(r)
    return by


QUESTIONS = {
    "affirmed_by_tool": lambda cl: any(c["polarity"] == "affirmed" and c["actor"] == "tool" for c in cl),
    "uncertain_tool": lambda cl: (not any(c["polarity"] == "affirmed" and c["actor"] == "tool" for c in cl)
                                  and any(c["polarity"] == "uncertain" and c["actor"] in ("tool", "") for c in cl)),
    "denied_any_scope": lambda cl: any(c["polarity"] == "denied" for c in cl),
}


def kappa(pairs):
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    pa, pb = sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return po, (po - pe) / (1 - pe) if pe < 1 else 1.0


def main():
    a, b = load(sys.argv[1]), load(sys.argv[2])
    keys = sorted(set(a) | set(b))
    print(f"{len(keys)} tool x effect pairs ({Path(sys.argv[1]).name} vs {Path(sys.argv[2]).name})")
    for q, f in QUESTIONS.items():
        pairs = [(f(a.get(k, [])), f(b.get(k, []))) for k in keys]
        po, k = kappa(pairs)
        print(f"\n{q}: agreement {po:.2f}, kappa {k:.2f}")
        for e in EFFECTS:
            pe = [p for key, p in zip(keys, pairs) if key[1] == e]
            print(f"   {e:8} {sum(x == y for x, y in pe)}/{len(pe)}")
        for key, (x, y) in zip(keys, pairs):
            if x != y:
                print(f"   differs: {key[0]} {key[1]}  A={x} B={y}")


if __name__ == "__main__":
    main()
