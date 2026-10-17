"""Select candidate servers for static analysis -> data/processed/candidates.csv.

A server is kept when:
  * it has >=1 tool with an explicit annotation (from the census),
  * its GitHub repo is reachable and not archived,
  * the repo is mainly Python or TypeScript/JavaScript (by GitHub language bytes).
"""
import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOINED = ROOT / "data/processed/census_joined.csv"
META = ROOT / "data/processed/repo_meta.jsonl"
OUT = ROOT / "data/processed/candidates.csv"
# share of all code bytes the winning language (Python, or TS+JS) must have
MIN_SHARE = 0.5


def classify(langs):
    py = langs.get("Python", 0)
    ts = langs.get("TypeScript", 0) + langs.get("JavaScript", 0)
    total = sum(langs.values()) or 1
    if py >= ts and py / total >= MIN_SHARE:
        return "python"
    if ts > py and ts / total >= MIN_SHARE:
        return "typescript"
    return "other"


def main():
    meta = {}
    for line in open(META, encoding="utf-8"):
        m = json.loads(line)
        meta[m["repo"]] = m

    rows, reasons = [], Counter()
    with open(JOINED, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if int(r["annotated_tools"]) == 0:
                reasons["no annotated tools"] += 1
                continue
            if not r["github"]:
                reasons["no github repo"] += 1
                continue
            m = meta.get(r["github"].lower())
            if m is None:
                reasons["metadata not fetched yet"] += 1
                continue
            if m["status"] != 200:
                reasons[f"repo http {m['status']}"] += 1
                continue
            if m["archived"]:
                reasons["archived"] += 1
                continue
            lang = classify(m["languages"])
            if lang == "other":
                reasons[f"language: {m['primary_language']}"] += 1
                continue
            reasons[f"kept: {lang}"] += 1
            rows.append({**r, "language": lang, "full_name": m["full_name"],
                         "default_branch": m["default_branch"], "stars": m["stars"],
                         "size_kb": m["size_kb"], "pushed_at": m["pushed_at"]})

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for k, v in reasons.most_common(25):
        print(f"{v:6d}  {k}")
    repos = {r["full_name"].lower() for r in rows}
    print(f"\n{len(rows)} servers, {len(repos)} distinct repos -> {OUT}")


if __name__ == "__main__":
    main()
