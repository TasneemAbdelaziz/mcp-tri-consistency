"""Source 2: GitHub Code Search for files that use MCP tool annotations.

Follows the collection idea of Hasan et al. ("MCP at First Glance", TOSEM),
but searches for the annotations themselves instead of SDK imports, so every
hit is a repo that already has annotations to compare against.

The search API returns at most 1,000 results per query, so each
(term, language) query is split into file-size ranges until every range
holds <= 1,000 hits. Code search allows ~10 requests/minute.

Hits go to data/raw/code_search/hits.jsonl; finished ranges are recorded in
done.txt so an interrupted run resumes where it stopped. Ranges whose pages
kept failing go to failed.txt and are retried at the start of the next run.
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
FAILED = RAW / "failed.txt"
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
        failures = 0
        while True:
            wait = MIN_INTERVAL - (time.time() - self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            try:
                r = self.client.get(API, params={"q": q, "page": page, "per_page": per_page})
            except httpx.HTTPError as e:
                r, error = None, repr(e)
            if r is not None and r.status_code in (403, 429):
                reset = int(r.headers.get("x-ratelimit-reset", time.time() + 60))
                wait = max(reset - time.time(), int(r.headers.get("retry-after", 0)), 30)
                print(f"rate limited, sleeping {wait:.0f}s", file=sys.stderr)
                time.sleep(wait)
                continue
            if r is not None and r.status_code == 422:  # past the 1,000-result window
                return {"total_count": 0, "items": []}
            if r is not None and r.status_code == 200:
                return r.json()
            # transient: network errors, 408 and 5xx are common on code search
            failures += 1
            error = error if r is None else f"HTTP {r.status_code}"
            if failures >= 5:
                print(f"giving up on {q!r} page {page}: {error}", file=sys.stderr)
                return {"total_count": 0, "items": [], "failed": True}
            print(f"{error}, retry {failures}/5", file=sys.stderr)
            time.sleep(30 * failures)


def ranges(searcher, base, lo, hi):
    """Yield (lo, hi, count) size ranges, each with <= LIMIT hits.
    count is None when the count query itself failed."""
    res = searcher.search(f"{base} size:{lo}..{hi}", per_page=1)
    if res.get("failed"):
        yield lo, hi, None
        return
    count = res["total_count"]
    if count <= LIMIT or lo == hi:
        if count > LIMIT:
            print(f"warning: {base} size:{lo} has {count} hits, only {LIMIT} reachable", file=sys.stderr)
        yield lo, hi, count
        return
    mid = (lo + hi) // 2
    yield from ranges(searcher, base, lo, mid)
    yield from ranges(searcher, base, mid + 1, hi)


def fetch_range(s, hits, key, count, lang, term):
    """Download all pages of one size range; False if a page failed."""
    for page in range(1, min(count, LIMIT) // PAGE + 2):
        res = s.search(key, page=page)
        if res.get("failed"):
            return False
        for it in res["items"]:
            hits.write(json.dumps({
                "repo": it["repository"]["full_name"],
                "fork": it["repository"]["fork"],
                "path": it["path"],
                "language": lang,
                "term": term,
            }) + "\n")
        if len(res["items"]) < PAGE:
            break
    hits.flush()
    return True


def collect(token):
    RAW.mkdir(parents=True, exist_ok=True)
    done = DONE.read_text(encoding="utf-8").split("\n") if DONE.exists() else []
    failed = FAILED.read_text(encoding="utf-8").split("\n") if FAILED.exists() else []
    s = Searcher(token)
    with open(HITS, "a", encoding="utf-8") as hits, open(DONE, "a", encoding="utf-8") as log:
        # retry ranges that failed in an earlier run
        still_failed = []
        for key in filter(None, failed):
            term, lang = key.split()[0], key.split("language:")[1].split()[0]
            if fetch_range(s, hits, key, LIMIT, lang, term):
                log.write(key + "\n")
                log.flush()
            else:
                still_failed.append(key)
        FAILED.write_text("\n".join(still_failed) + "\n", encoding="utf-8")

        for term in TERMS:
            for lang in LANGUAGES:
                base = f"{term} language:{lang}"
                if base in done:
                    continue
                # ranges are done in increasing size order: resume after the last one
                start = max((int(k.split("..")[1]) + 1 for k in done if k.startswith(base + " size:")),
                            default=0)
                for lo, hi, count in ranges(s, base, start, MAX_SIZE):
                    key = f"{base} size:{lo}..{hi}"
                    if count == 0:
                        continue
                    if count is None or not fetch_range(s, hits, key, count, lang, term):
                        with open(FAILED, "a", encoding="utf-8") as f:
                            f.write(key + "\n")
                        print(f"{key}: FAILED, will retry next run", file=sys.stderr)
                        continue
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
