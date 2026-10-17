"""Join the annotation census (tools.csv) with the registry snapshot to see
how many annotated remote servers point to a GitHub repo, and in which language
(inferred from the registry's package entries: npm -> TS/JS, pypi -> Python)."""
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# census output dirs, newest first (default: the published run only), e.g.
#   analyze_census.py data/raw/census_v2 data/external/mcp-annotation-census/output_full2
CENSUS = [Path(p) for p in sys.argv[1:]] or [ROOT / "data/external/mcp-annotation-census/output_full2"]
OUT = ROOT / "data/processed"
ANNOTATIONS = ["readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"]
GH = re.compile(r"github\.com[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/.*)?$", re.I)


def latest_entries(snapshot):
    """Keep one entry per server name, preferring isLatest (same rule as census.py)."""
    best = {}
    for e in snapshot:
        s = e["server"]
        latest = e.get("_meta", {}).get("io.modelcontextprotocol.registry/official", {}).get("isLatest", False)
        if s["name"] not in best or latest:
            best[s["name"]] = s
    return best


def repo_info(s):
    url = (s.get("repository") or {}).get("url") or ""
    m = GH.search(url)
    kinds = {p.get("registryType") for p in s.get("packages") or []}
    lang = "python" if "pypi" in kinds else "ts/js" if "npm" in kinds else "unknown"
    return (f"{m.group(1)}/{m.group(2)}" if m else None), url, lang, (s.get("repository") or {}).get("subfolder", "")


def main():
    snapshot = json.load(open(CENSUS[0] / "registry_snapshot.json", encoding="utf-8"))
    servers = latest_entries(snapshot)

    # Union of census runs: a server is taken from the first run (in argv order)
    # that has it, so pass the newest run first. `source` records which run.
    tools_by_server = {}
    for census in CENSUS:
        run = {}
        with open(census / "tools.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["server_name"] in tools_by_server:
                    continue
                t = run.setdefault(r["server_name"], {"tools": 0, "annotated": 0, "explicit_fields": 0,
                                                      "source": census.name})
                t["tools"] += 1
                n = sum(r[a] != "omitted" for a in ANNOTATIONS)
                t["annotated"] += n > 0
                t["explicit_fields"] += n
        tools_by_server.update(run)

    rows, c = [], Counter()
    for name, t in tools_by_server.items():
        s = servers.get(name, {})
        gh, url, lang, sub = repo_info(s)
        c["servers_with_tools"] += 1
        c["tools"] += t["tools"]
        if t["annotated"]:
            c["servers_annotated"] += 1
        if gh:
            c["servers_github"] += 1
        if gh and t["annotated"]:
            c["servers_github_annotated"] += 1
            c["tools_github_annotated_servers"] += t["tools"]
            c[f"lang:{lang}"] += 1
        rows.append({"server_name": name, "github": gh or "", "repo_url": url, "subfolder": sub,
                     "lang_hint": lang, "tools": t["tools"], "annotated_tools": t["annotated"],
                     "source": t["source"]})
        c[f"source:{t['source']}"] += 1

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "census_joined.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    # how many distinct repos (several registry names can share one repo)
    repos = {r["github"].lower() for r in rows if r["github"] and r["annotated_tools"]}
    c["distinct_github_repos_annotated"] = len(repos)
    # whole-registry view: all latest servers with a GitHub repo, regardless of remote/census
    c["registry_latest_servers"] = len(servers)
    c["registry_with_github"] = sum(1 for s in servers.values() if repo_info(s)[0])
    for s in servers.values():
        if repo_info(s)[0]:
            c[f"registry_github_lang:{repo_info(s)[2]}"] += 1
    for k, v in c.items():
        print(f"{k:40s} {v}")


if __name__ == "__main__":
    sys.exit(main())
