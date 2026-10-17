"""Clone every distinct repo in candidates.csv into repos/<owner>__<name>.

Uses --filter=blob:none (partial clone): the full commit history is kept for
RQ3 (code drift), but old file contents are only downloaded on demand.
The HEAD commit of each clone is recorded in data/processed/repos_manifest.csv
so every result can be traced to an exact code version.

Usage: python clone_repos.py [N]   # N = test sample: first N repos per language
"""
import csv
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = ROOT / "data/processed/candidates.csv"
MANIFEST = ROOT / "data/processed/repos_manifest.csv"
REPOS = ROOT / "repos"
WORKERS = 4
TIMEOUT = 600


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                          timeout=TIMEOUT, encoding="utf-8", errors="replace")


def clone(full_name, language):
    dest = REPOS / full_name.replace("/", "__")
    row = {"repo": full_name, "language": language, "path": "", "sha": "", "status": "failed", "error": ""}
    try:
        if not (dest / ".git").exists():
            r = git("-c", "core.longpaths=true", "clone", "--filter=blob:none", "--quiet",
                    f"https://github.com/{full_name}.git", str(dest))
            if r.returncode != 0:
                return {**row, "error": r.stderr.strip()[:200]}
        sha = git("rev-parse", "HEAD", cwd=dest).stdout.strip()
    except subprocess.TimeoutExpired:
        return {**row, "error": "timeout"}
    return {**row, "path": str(dest.relative_to(ROOT)), "sha": sha, "status": "ok"}


def main():
    REPOS.mkdir(exist_ok=True)
    repos = {}
    with open(CANDIDATES, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            repos.setdefault(r["full_name"], r)
    items = [(name, r["language"]) for name, r in repos.items()]
    if len(sys.argv) > 1:
        # test sample: first N repos per language, skipping template families
        n = int(sys.argv[1])
        items = [(name, r["language"]) for name, r in repos.items() if int(r["owner_repos"]) <= 10]
        items = [x for x in items if x[1] == "python"][:n] + [x for x in items if x[1] == "typescript"][:n]

    results = []
    with ThreadPoolExecutor(WORKERS) as pool:
        futures = [pool.submit(clone, name, lang) for name, lang in items]
        for i, fut in enumerate(as_completed(futures), 1):
            results.append(fut.result())
            if i % 25 == 0:
                print(f"{i}/{len(items)}", file=sys.stderr)

    with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["repo", "language", "path", "sha", "status", "error"])
        w.writeheader()
        w.writerows(sorted(results, key=lambda r: r["repo"].lower()))
    ok = sum(r["status"] == "ok" for r in results)
    print(f"{ok}/{len(results)} cloned -> {MANIFEST}")


if __name__ == "__main__":
    main()
