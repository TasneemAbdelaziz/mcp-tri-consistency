"""Source 1: servers published to the MCP Registry as npm / PyPI packages.

Unlike remote servers, a package is built from its repo, so the repo holds
the server code itself. Output: data/processed/registry_packages.csv.

Usage:
    python registry_packages.py            # download a fresh registry snapshot
    python registry_packages.py SNAPSHOT   # reuse a saved snapshot
"""
import csv
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from census import fetch_registry_snapshot, latest_per_server  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/processed/registry_packages.csv"
GH = re.compile(r"github\.com[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/.*)?$", re.I)
LANG = {"npm": "typescript", "pypi": "python"}


def main():
    if len(sys.argv) > 1:
        snap_path = Path(sys.argv[1])
        snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
    else:
        snap_path = ROOT / f"data/raw/registry_snapshot_{date.today()}.json"
        snapshot = fetch_registry_snapshot(checkpoint_path=snap_path)
        snap_path.write_text(json.dumps(snapshot), encoding="utf-8")
    print(f"snapshot: {snap_path} ({len(snapshot)} entries)", file=sys.stderr)

    rows, c = [], Counter()
    for s in latest_per_server(snapshot):
        s = s.get("server", s)
        c["latest servers"] += 1
        pkgs = [p for p in s.get("packages") or [] if p.get("registryType") in LANG]
        if not pkgs:
            c["no npm/pypi package"] += 1
            continue
        repo = s.get("repository") or {}
        m = GH.search(repo.get("url") or "")
        if not m:
            c["package but no github repo"] += 1
            continue
        types = sorted({p["registryType"] for p in pkgs})
        c[f"kept: {'+'.join(types)}"] += 1
        rows.append({
            "server_name": s["name"],
            "server_version": s.get("version", ""),
            "github": f"{m.group(1)}/{m.group(2)}",
            "subfolder": repo.get("subfolder", ""),
            "registry_type": "+".join(types),
            "package": pkgs[0].get("identifier", ""),
            "lang_hint": LANG[pkgs[0]["registryType"]],
            "has_remote": bool(s.get("remotes")),
            "description": s.get("description", ""),
        })

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for k, v in c.most_common():
        print(f"{v:6d}  {k}")
    print(f"\n{len(rows)} servers, {len({r['github'].lower() for r in rows})} distinct repos -> {OUT}")


if __name__ == "__main__":
    main()
