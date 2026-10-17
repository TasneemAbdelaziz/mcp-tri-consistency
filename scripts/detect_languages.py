"""Fetch GitHub metadata + language breakdown for every repo in census_joined.csv
that has at least one annotated tool. Results are cached in repo_meta.jsonl, so
re-running only fetches repos not seen yet.

Needs a GitHub token in the GITHUB_TOKEN environment variable (read-only,
public repos is enough). Without it GitHub allows only 60 requests/hour.
"""
import csv
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
JOINED = ROOT / "data/processed/census_joined.csv"
META = ROOT / "data/processed/repo_meta.jsonl"
API = "https://api.github.com"


def get(client, url):
    """GET with rate-limit handling; returns (status, json or None)."""
    while True:
        r = client.get(url)
        if r.status_code in (403, 429) and r.headers.get("x-ratelimit-remaining") == "0":
            wait = max(int(r.headers.get("x-ratelimit-reset", time.time() + 60)) - time.time(), 1) + 2
            print(f"rate limited, sleeping {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)
            continue
        return r.status_code, (r.json() if r.status_code == 200 else None)


def fetch(client, repo):
    status, info = get(client, f"{API}/repos/{repo}")
    if info is None:
        return {"repo": repo, "status": status}
    _, langs = get(client, f"{API}/repos/{repo}/languages")
    return {
        "repo": repo,
        "status": status,
        "full_name": info["full_name"],  # differs from repo if it was renamed
        "default_branch": info["default_branch"],
        "archived": info["archived"],
        "fork": info["fork"],
        "stars": info["stargazers_count"],
        "size_kb": info["size"],
        "pushed_at": info["pushed_at"],
        "primary_language": info["language"],
        "languages": langs or {},
    }


def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("warning: GITHUB_TOKEN not set, limited to 60 requests/hour", file=sys.stderr)
    with open(JOINED, encoding="utf-8") as f:
        repos = sorted({r["github"].lower() for r in csv.DictReader(f)
                        if r["github"] and int(r["annotated_tools"]) > 0})
    done = set()
    if META.exists():
        done = {json.loads(line)["repo"] for line in open(META, encoding="utf-8")}
    todo = [r for r in repos if r not in done]
    print(f"{len(repos)} repos, {len(done)} cached, {len(todo)} to fetch", file=sys.stderr)

    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client, \
            open(META, "a", encoding="utf-8") as out:
        for i, repo in enumerate(todo, 1):
            out.write(json.dumps(fetch(client, repo)) + "\n")
            out.flush()
            if i % 50 == 0:
                print(f"{i}/{len(todo)}", file=sys.stderr)


if __name__ == "__main__":
    main()
