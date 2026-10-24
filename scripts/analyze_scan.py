"""First RQ2 numbers from the scan: how often code and annotations disagree.

Reads data/results/scan_manifest.csv and data/results/scan/*.jsonl and writes
data/results/rq2_preliminary.md. Units are tools with at least one explicit
annotation. Detector output only: these are candidate inconsistencies until the
labeled sample gives precision and recall.

Template families (owners with many generated repos) are reported both as
they are and with each owner capped at 5 repos, so one generator cannot drive
the prevalence.
"""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "data/results"
OWNER_CAP = 5
HINTS = ["readOnlyHint", "destructiveHint", "openWorldHint"]


def load():
    tools = []
    for path in sorted((RES / "scan").glob("*.jsonl")):
        for line in open(path, encoding="utf-8"):
            t = json.loads(line)
            if t.get("annotations_kind") in ("none", "unresolved"):
                continue
            if any(t["annotations"][h] in ("true", "false") for h in t["annotations"]):
                tools.append(t)
    return tools


def cap_owners(tools):
    repos_by_owner = defaultdict(list)
    for r in sorted({t["repo"] for t in tools}):
        repos_by_owner[r.split("/")[0].lower()].append(r)
    keep = {r for rs in repos_by_owner.values() for r in rs[:OWNER_CAP]}
    return [t for t in tools if t["repo"] in keep]


def pct(a, b):
    return f"{a:,} ({100 * a / b:.1f}%)" if b else "0"


def table(tools):
    """rows: per rule, tools with the rule among tools where the rule can apply."""
    rules = [
        ("readOnlyHint=true, code writes", "readOnlyHint", "true", "readOnly_but_write"),
        ("readOnlyHint=true, code deletes", "readOnlyHint", "true", "readOnly_but_delete"),
        ("readOnlyHint=true, code executes", "readOnlyHint", "true", "readOnly_but_execute"),
        ("destructiveHint=false, code deletes", "destructiveHint", "false", "nondestructive_but_delete"),
        ("destructiveHint=false, code modifies/overwrites", "destructiveHint", "false", "nondestructive_but_m"),
        ("openWorldHint=false, request to an open target", "openWorldHint", "false", "closedworld_but_open_network"),
    ]
    out = []
    for label, hint, value, prefix in rules:
        base = [t for t in tools if t["annotations"][hint] == value and
                not (hint == "destructiveHint" and t["annotations"]["readOnlyHint"] == "true")]
        hit = lambda key: sum(any(v["rule"].startswith(prefix) or (prefix == "nondestructive_but_m" and
                                  v["rule"] in ("nondestructive_but_modifying", "nondestructive_but_overwrite"))
                                  for v in t[key]) for t in base)
        out.append((label, len(base), hit("inconsistencies"), hit("inconsistencies_lenient")))
    return out


def main():
    rows = list(csv.DictReader(open(RES / "scan_manifest.csv", encoding="utf-8")))
    status = Counter(r["status"] for r in rows)
    tools = load()
    capped = cap_owners(tools)
    lines = ["# RQ2 preliminary: detector output on the 5,000-repo random sample", "",
             f"Repos scanned: {len(rows):,}. Status: " + ", ".join(f"{k} {v:,}" for k, v in status.most_common()) + ".", "",
             "Candidate inconsistencies from the static detector, before validation against the labeled sample.", ""]
    for name, ts in (("All repos", tools), (f"Owners capped at {OWNER_CAP} repos", capped)):
        n = len(ts)
        repos = {t["repo"] for t in ts}
        s = sum(bool(t["inconsistencies"]) for t in ts)
        l = sum(bool(t["inconsistencies_lenient"]) for t in ts)
        rv = sum(bool(t["review"]) for t in ts)
        rs = len({t["repo"] for t in ts if t["inconsistencies_lenient"]})
        lines += [f"## {name}", "",
                  f"- Tools with explicit annotations: {n:,} in {len(repos):,} repos "
                  f"(TS/JS {sum(t['lang'] == 'ts' for t in ts):,}, Python {sum(t['lang'] == 'python' for t in ts):,})",
                  f"- Inconsistent, strict: {pct(s, n)}",
                  f"- Inconsistent, lenient (guide rules R1-R5 dropped): {pct(l, n)}",
                  f"- Repos with at least one lenient inconsistency: {pct(rs, len(repos))}",
                  f"- Only for review (fixed host, shared dispatcher): {pct(rv, n)}", "",
                  "| Rule | Tools where it applies | Strict | Lenient |", "|---|---|---|---|"]
        for label, base, st, le in table(ts):
            lines.append(f"| {label} | {base:,} | {pct(st, base)} | {pct(le, base)} |")
        by_lang = defaultdict(lambda: [0, 0])
        for t in ts:
            by_lang[t["lang"]][0] += 1
            by_lang[t["lang"]][1] += bool(t["inconsistencies_lenient"])
        lines += ["", "| Language | Tools | Lenient inconsistent |", "|---|---|---|"]
        for lang, (a, b) in sorted(by_lang.items()):
            lines.append(f"| {lang} | {a:,} | {pct(b, a)} |")
        kinds = Counter(v["witness"]["kind"] for t in ts for v in t["inconsistencies"])
        lines += ["", "Effect kinds behind strict findings: " + ", ".join(f"{k} {v:,}" for k, v in kinds.most_common()), ""]
    explicit = Counter()
    for t in tools:
        for h in HINTS:
            explicit[(h, t["annotations"][h])] += 1
    lines += ["## Explicit vs omitted hints (all tools with any explicit hint)", "", "| Hint | true | false | omitted |", "|---|---|---|---|"]
    for h in HINTS:
        lines.append(f"| {h} | {explicit[(h, 'true')]:,} | {explicit[(h, 'false')]:,} | {explicit[(h, 'omitted')]:,} |")
    (RES / "rq2_preliminary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
