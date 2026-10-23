"""Draw the C<->A ground-truth sample from the scan results.

Unit: a tool with at least one explicitly written annotation. Strata (by the
detector's output, so precision AND recall can be measured):
  flagged      >= 1 strict inconsistency                        (precision)
  review       no inconsistency, >= 1 review item               (unknown-world cases)
  clean_risky  clean, but has a hint the code could contradict:
               readOnlyHint=true, destructiveHint=false or
               openWorldHint=false                              (recall)
  clean_other  clean, nothing to contradict                     (coverage)

Diversity: at most 2 tools per repo and 3 per owner. A calibration set of 30
is drawn first and kept out of the main sample. Each row records its stratum
and its inclusion probability, so prevalence can be re-weighted later.

Annotators label from the code only: the files they get carry the tool name
and links to the code at the scanned commit, but no annotations, description
or detector output (those are in key.csv, which annotators must not open).

Usage: python make_labeling_sample.py [--seed 11]
"""
import argparse
import csv
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "data/results/scan"
OUT = ROOT / "labeling/sample_v1"
QUOTA = {"flagged": 160, "review": 40, "clean_risky": 160, "clean_other": 40}
CALIBRATION = 30
PER_REPO, PER_OWNER = 2, 3

# what annotators fill in: E(t), from the code only
LABELS = [
    ("writes", ["no", "yes", "unsure"]),
    ("write_mode", ["", "additive", "modifying", "overwrite", "unknown"]),
    ("deletes", ["no", "yes", "unsure"]),
    ("executes", ["no", "fixed program", "command from input", "unsure"]),
    ("network", ["no", "open target", "fixed host", "unsure"]),
    ("special_case", ["", "R1 bookkeeping", "R2 cleanup", "R3 fixed program", "R4 POST read",
                      "R5 debug log", "R6 git", "other (notes)"]),
    ("could_not_trace", ["no", "yes"]),
]


def load_tools():
    tools = []
    for path in sorted(RESULTS.glob("*.jsonl")):
        for line in open(path, encoding="utf-8"):
            t = json.loads(line)
            if t.get("annotations_kind") in ("none", "unresolved") or not t.get("entry"):
                continue
            ann = t["annotations"]
            if not any(v in ("true", "false") for v in ann.values()):
                continue
            t["stratum"] = ("flagged" if t["inconsistencies"] else "review" if t["review"] else
                            "clean_risky" if (ann["readOnlyHint"] == "true" or ann["destructiveHint"] == "false"
                                              or ann["openWorldHint"] == "false") else "clean_other")
            tools.append(t)
    return tools


def draw(pool, n, rng, per_repo, per_owner, exclude=()):
    """Up to n tools from pool, respecting the per-repo / per-owner caps."""
    rng.shuffle(pool)
    out, repo_n, owner_n = [], Counter(), Counter()
    for t in pool:
        key = (t["repo"], t["tool"], t["file"])
        owner = t["repo"].split("/")[0].lower()
        if key in exclude or repo_n[t["repo"]] >= per_repo or owner_n[owner] >= per_owner:
            continue
        out.append(t)
        repo_n[t["repo"]] += 1
        owner_n[owner] += 1
        if len(out) == n:
            break
    return out


def link(t, line):
    return f"https://github.com/{t['repo']}/blob/{t['sha']}/{t['file'] if line == t['line'] else t['entry_file']}#L{line}"


def annotator_row(i, t):
    entry_file, entry_line = t["file"], t.get("handler_line") or t["line"]
    e = str(t.get("entry") or "")
    if ":" in e and e.rsplit(":", 1)[1].isdigit() and not e.startswith("call_tool"):
        f, ln = e.rsplit(":", 1)
        entry_file = f if "/" in f or "." in f else t["file"]
        if t.get("package_root") not in (None, "", ".") and not entry_file.startswith(t["package_root"] + "/"):
            entry_file = f"{t['package_root']}/{entry_file}"
        entry_line = int(ln)
    base = f"https://github.com/{t['repo']}/blob/{t['sha']}"
    return {
        "id": i, "repo": t["repo"], "tool": t["tool"], "language": t["lang"],
        "definition": f"{base}/{t['file']}#L{t['line']}",
        "handler": f"{base}/{entry_file}#L{entry_line}",
        **{name: "" for name, _ in LABELS}, "notes": "",
    }


def write_xlsx(path, rows, title):
    wb = Workbook()
    ws = wb.active
    ws.title = title
    cols = list(rows[0].keys())
    ws.append(cols)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F4E79")
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for r in rows:
        ws.append([r[c] for c in cols])
    for i, (name, options) in enumerate(LABELS):
        col = cols.index(name) + 1
        letter = ws.cell(row=1, column=col).column_letter
        dv = DataValidation(type="list", formula1='"' + ",".join(o for o in options if o) + '"', allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{letter}2:{letter}{len(rows) + 1}")
        ws.column_dimensions[letter].width = 18
    widths = {"id": 5, "repo": 32, "tool": 28, "language": 9, "definition": 14, "handler": 14, "notes": 40}
    for name, w in widths.items():
        ws.column_dimensions[ws.cell(row=1, column=cols.index(name) + 1).column_letter].width = w
    for row in ws.iter_rows(min_row=2):
        for name in ("definition", "handler"):
            cell = row[cols.index(name)]
            cell.hyperlink = cell.value
            cell.style = "Hyperlink"
    ws.freeze_panes = "E2"
    wb.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    OUT.mkdir(parents=True, exist_ok=True)

    tools = load_tools()
    by = defaultdict(list)
    for t in tools:
        by[t["stratum"]].append(t)
    sizes = {s: len(v) for s, v in by.items()}
    print("population:", sizes, "| repos:", len({t["repo"] for t in tools}))

    # calibration: proportional to the main quotas, drawn first and excluded
    calib = []
    for s, q in QUOTA.items():
        calib += draw(list(by[s]), round(CALIBRATION * q / sum(QUOTA.values())), rng, 1, 1)
    taken = {(t["repo"], t["tool"], t["file"]) for t in calib}
    picked = {s: draw(list(by[s]), q, rng, PER_REPO, PER_OWNER, taken) for s, q in QUOTA.items()}
    # a stratum smaller than its quota (review is rare): top up from flagged and
    # clean_risky in turn, still within the caps
    short = sum(QUOTA.values()) - sum(map(len, picked.values()))
    for s in ["flagged", "clean_risky"] * short:
        if short <= 0:
            break
        have = {(t["repo"], t["tool"], t["file"]) for v in picked.values() for t in v} | taken
        more = draw([t for t in by[s] if (t["repo"], t["tool"], t["file"]) not in have], 1, rng, PER_REPO, PER_OWNER)
        if more:
            picked[s] += more
            short -= 1
    main_rows = []
    for s, rows in picked.items():
        for t in rows:
            t["inclusion_prob"] = round(len(rows) / max(sizes.get(s, 1), 1), 6)
        main_rows += rows
    rng.shuffle(main_rows)  # strata mixed, so annotators cannot infer them from order

    for name, rows in (("calibration_30", calib), ("sample_400", main_rows)):
        ann_rows = [annotator_row(i + 1, t) for i, t in enumerate(rows)]
        for who in ("tasneem", "menna"):
            write_xlsx(OUT / f"{name}_{who}.xlsx", ann_rows, name)
        with open(OUT / f"{name}_key.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "repo", "sha", "tool", "language", "stratum", "inclusion_prob", "readOnlyHint",
                        "destructiveHint", "openWorldHint", "detector_strict", "detector_lenient", "detector_review",
                        "description"])
            for i, t in enumerate(rows, 1):
                a = t["annotations"]
                w.writerow([i, t["repo"], t["sha"], t["tool"], t["lang"], t["stratum"], t.get("inclusion_prob", ""),
                            a["readOnlyHint"], a["destructiveHint"], a["openWorldHint"],
                            "; ".join(sorted({v["rule"] for v in t["inconsistencies"]})),
                            "; ".join(sorted({v["rule"] for v in t["inconsistencies_lenient"]})),
                            "; ".join(sorted({v["rule"] for v in t["review"]})),
                            (t.get("description") or "")[:500]])
        print(f"{name}: {len(rows)} tools, {len({t['repo'] for t in rows})} repos, "
              f"strata {dict(Counter(t['stratum'] for t in rows))}, languages {dict(Counter(t['lang'] for t in rows))}")


if __name__ == "__main__":
    main()
