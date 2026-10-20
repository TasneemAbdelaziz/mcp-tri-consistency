"""Merge the four repo sources into one de-duplicated list:
data/processed/dataset_repos.csv (one row per GitHub repo).

Sources (a repo may come from several; `sources` lists them all):
  registry     npm / PyPI packages in the MCP Registry   (registry_packages.csv)
  code_search  GitHub code search for annotation names   (code_search_repos.csv)
  census       remote servers with annotations           (census_joined.csv)
  official     modelcontextprotocol/servers

Forks are dropped. `owner_repos` counts an owner's repos in the list, so
template families (one owner, hundreds of generated repos) can be capped or
grouped in the analysis.
"""
import csv
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "data/processed"
OUT = P / "dataset_repos.csv"


def main():
    repos = defaultdict(lambda: {"sources": set(), "lang_hints": set(), "servers": set(), "packages": set()})

    def add(github, source, lang=None, server=None, package=None):
        key = github.strip().lower().removesuffix(".git")
        if key.count("/") != 1:
            return
        r = repos[key]
        r.setdefault("github", github.strip().removesuffix(".git"))
        r["sources"].add(source)
        if lang:
            r["lang_hints"].add(lang)
        if server:
            r["servers"].add(server)
        if package:
            r["packages"].add(package)

    with open(P / "registry_packages.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            add(row["github"], "registry", row["lang_hint"], row["server_name"], row["package"])
    with open(P / "code_search_repos.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["fork"] != "True":
                for lang in row["languages"].split("+"):
                    add(row["github"], "code_search", lang.lower())
    with open(P / "census_joined.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["github"] and int(row["annotated_tools"]) > 0:
                add(row["github"], "census", None, row["server_name"])
    add("modelcontextprotocol/servers", "official")

    owners = Counter(k.split("/")[0] for k in repos)
    rows = [{
        "github": r["github"],
        "sources": "+".join(sorted(r["sources"])),
        "lang_hints": "+".join(sorted(r["lang_hints"])),
        "registry_servers": len(r["servers"]),
        "packages": "+".join(sorted(r["packages"]))[:200],
        "owner_repos": owners[k.split("/")[0]],
    } for k, r in sorted(repos.items())]

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    by_sources = Counter(r["sources"] for r in rows)
    print(f"{len(rows)} repos -> {OUT}")
    for k, v in by_sources.most_common():
        print(f"  {v:6d}  {k}")
    big = [(o, n) for o, n in owners.most_common(8) if n > 50]
    print("  owners with > 50 repos:", big)


if __name__ == "__main__":
    main()
