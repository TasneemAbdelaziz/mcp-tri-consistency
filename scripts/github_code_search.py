"""Source 2: GitHub Code Search for files that use MCP tool annotations.

Follows the collection idea of Hasan et al. ("MCP at First Glance", TOSEM),
but searches for the annotations themselves instead of SDK imports, so every
hit is a repo that already has annotations to compare against.

The search API returns at most 1,000 results per query, so each
(term, language) query is split into file-size ranges until every range
holds <= 1,000 hits. Code search allows ~10 requests/minute.

Hits go to data/raw/code_search/hits.jsonl; finished ranges are recorded in
done.txt so an interrupted run resumes where it stopped.
Run aggregate_code_search() (python github_code_search.py --aggregate) to
build data/processed/code_search_repos.csv from the hits.
"""
import csv
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/code_search"
HITS = RAW / "hits.jsonl"
DONE = RAW / "done.txt"
OUT = ROOT / "data/processed/code_search_repos.csv"
API = "https://api.github.com/search/code"

TERMS = ["readOnlyHint", "destructiveHint"]
LANGUAGES = ["Python", "TypeScript", "JavaScript"]
MAX_SIZE = 400_000  # GitHub only indexes files < 384 KB
PAGE = 100
LIMIT = 1000
MIN_INTERVAL = 6.5  # seconds between requests (10/min limit)
# vendored / generated copies of the SDK, not server code
SKIP_PATHS = ("node_modules/", "/dist/", "/build/", ".d.ts", "site-packages/", "/vendor/")


class Searcher:
    def __init__(self, token):
        self.client = httpx.Client(timeout=60, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        self.last = 0.0

    def search(self, q, page=1, per_page=PAGE):
        while True:
            wait = MIN_INTERVAL - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            try:
                r = self.client.get(API, params={"q": q, "page": page, "per_page": per_page})
            except httpx.HTTPError as e:
                print(f"network error {e!r}, retrying", file=sys.stderr)
                time.sleep(30)
                continue
            if r.status_code in (403, 429):
                reset = int(r.headers.get("x-ratelimit-reset", time.time() + 60))
                wait = max(reset - time.time(), int(r.headers.get("retry-after", 0)), 30)
                print(f"rate limited, sleeping {wait:.0f}s", file=sys.stderr)
                time.sleep(wait)
                continue
            if r.status_code == 422:  # past the 1,000-result window
                return {"total_count": 0, "items": []}
            if r.status_code >= 500:  # transient GitHub errors (search 503s often)
                print(f"server error {r.status_code}, retrying", file=sys.stderr)
                time.sleep(30)
                continue
            r.raise_for_status()
            return r.json()


def ranges(searcher, base, lo, hi):
    """Yield (lo, hi, count) size ranges, each with <= LIMIT hits."""
    count = searcher.search(f"{base} size:{lo}..{hi}", per_page=1)["total_count"]
    if count <= LIMIT or lo == hi:
        if count > LIMIT:
            print(f"warning: {base} size:{lo} has {count} hits, only {LIMIT} reachable", file=sys.stderr)
        yield lo, hi, count
        return
    mid = (lo + hi) // 2
    yield from ranges(searcher, base, lo, mid)
    yield from ranges(searcher, base, mid + 1, hi)


def collect(token):
    RAW.mkdir(parents=True, exist_ok=True)
    done = set(DONE.read_text(encoding="utf-8").split("\n")) if DONE.exists() else set()
    s = Searcher(token)
    with open(HITS, "a", encoding="utf-8") as hits, open(DONE, "a", encoding="utf-8") as log:
        for term in TERMS:
            for lang in LANGUAGES:
                base = f"{term} language:{lang}"
                if base in done:
                    continue
                for lo, hi, count in ranges(s, base, 0, MAX_SIZE):
                    key = f"{base} size:{lo}..{hi}"
                    if key in done or count == 0:
                        continue
                    for page in range(1, min(count, LIMIT) // PAGE + 2):
                        items = s.search(key, page=page)["items"]
                        for it in items:
                            hits.write(json.dumps({
                                "repo": it["repository"]["full_name"],
                                "fork": it["repository"]["fork"],
                                "path": it["path"],
                                "language": lang,
                                "term": term,
                            }) + "\n")
                        if len(items) < PAGE:
                            break
                    hits.flush()
                    log.write(key + "\n")
                    log.flush()
                    print(f"{key}: {count}", file=sys.stderr)
                log.write(base + "\n")
                log.flush()


def aggregate():
    repos = defaultdict(lambda: {"files": set(), "languages": set(), "terms": set(), "fork": False})
    for line in open(HITS, encoding="utf-8"):
        h = json.loads(line)
        if any(p in "/" + h["path"] for p in SKIP_PATHS):
            continue
        r = repos[h["repo"]]
        r["files"].add(h["path"])
        r["languages"].add(h["language"])
        r["terms"].add(h["term"])
        r["fork"] |= h["fork"]
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["github", "fork", "files", "languages", "terms"])
        for name, r in sorted(repos.items(), key=lambda x: x[0].lower()):
            w.writerow([name, r["fork"], len(r["files"]), "+".join(sorted(r["languages"])),
                        "+".join(sorted(r["terms"]))])
    forks = sum(r["fork"] for r in repos.values())
    print(f"{len(repos)} repos ({forks} forks) -> {OUT}")


if __name__ == "__main__":
    if "--aggregate" in sys.argv:
        aggregate()
    else:
        token = os.environ.get("GITHUB_TOKEN") or sys.exit("GITHUB_TOKEN is required for code search")
        collect(token)
