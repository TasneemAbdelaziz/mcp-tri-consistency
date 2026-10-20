"""Run both detectors over every repo in data/processed/dataset_repos.csv.

Per repo, in a worker process:
  1. `git ls-remote` gives the HEAD commit (recorded, so results are traceable)
  2. the source archive of that commit is downloaded from codeload.github.com
     and only code files are extracted (.py .ts .js ...; no node_modules,
     dist, tests are skipped later by the detectors); names Windows cannot
     hold are sanitized
  3. detector/python/effects.py and detector/ts/effects.js run on it (MCP-only)
  4. tool records go to data/results/scan/<owner>__<repo>.jsonl and the
     extracted files are deleted

A summary row per repo is appended to data/results/scan_manifest.csv; repos
already in it are skipped, so the scan resumes after an interruption.
The full git history is fetched later, only for repos with inconsistencies (RQ3).

Usage: python scan_repos.py [--limit N] [--workers 8] [--seed 7]
"""
import argparse
import csv
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tarfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data/processed/dataset_repos.csv"
RESULTS = ROOT / "data/results/scan"
MANIFEST = ROOT / "data/results/scan_manifest.csv"
WORK = ROOT / "data/tmp/scan"
PYTHON = str(ROOT / ".venv/Scripts/python.exe") if os.name == "nt" else str(ROOT / ".venv/bin/python")
CODE_EXTS = {".py", ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}
SKIP_DIRS = {"node_modules", ".git", "dist", "build", "out", "coverage", ".next", "vendor", "site-packages",
             ".venv", "venv", "__pycache__"}
MAX_ARCHIVE = 300 * 1024 * 1024
MAX_FILE = 2 * 1024 * 1024
TIMEOUT = 300
FIELDS = ["repo", "sha", "status", "py_files", "ts_files", "tools", "annotated", "inconsistent_strict",
          "inconsistent_lenient", "review", "seconds", "error"]
BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
PACKAGE_MARKERS = ("package.json", "pyproject.toml", "setup.py", "setup.cfg")
HINT_RE = re.compile(r"readOnlyHint|destructiveHint|openWorldHint|idempotentHint")


def head_sha(repo):
    r = subprocess.run(["git", "ls-remote", f"https://github.com/{repo}", "HEAD"], capture_output=True,
                       text=True, timeout=60, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    return r.stdout.split()[0] if r.returncode == 0 and r.stdout.strip() else None


def download(repo, sha, dest, attempts=3):
    """codeload sometimes drops long transfers: retry with a growing pause."""
    for i in range(attempts):
        try:
            return download_once(repo, sha, dest)
        except (httpx.TransportError, httpx.TimeoutException):
            if i == attempts - 1:
                raise
            time.sleep(10 * (i + 1))


def download_once(repo, sha, dest):
    with httpx.stream("GET", f"https://codeload.github.com/{repo}/tar.gz/{sha}", timeout=120,
                      follow_redirects=True) as r:
        if r.status_code != 200:
            raise RuntimeError(f"archive http {r.status_code}")
        size = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(1 << 16):
                size += len(chunk)
                if size > MAX_ARCHIVE:
                    raise RuntimeError("archive too large")
                f.write(chunk)


def extract(archive, dest):
    """Code files (and package markers) only; returns (py_files, ts_files)."""
    py = tsn = 0
    with tarfile.open(archive, "r:gz") as tar:
        for m in tar:
            if not m.isfile() or m.size > MAX_FILE:
                continue
            parts = m.name.split("/")[1:]  # drop the <repo>-<sha>/ prefix
            if not parts or SKIP_DIRS & set(parts[:-1]):
                continue
            ext = os.path.splitext(parts[-1])[1].lower()
            if ext not in CODE_EXTS and parts[-1] not in PACKAGE_MARKERS:
                continue
            safe = [BAD_CHARS.sub("_", p).rstrip(". ")[:80] or "_" for p in parts]
            target = dest.joinpath(*safe)
            if len(str(target)) > 240:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(m)
            if src is None:
                continue
            with open(target, "wb") as f:
                shutil.copyfileobj(src, f)
            if ext == ".py":
                py += 1
            elif ext in CODE_EXTS:
                tsn += 1
    return py, tsn


def analysis_roots(src):
    """Package directories that hold annotations: for each file mentioning a hint
    name, its nearest ancestor with a package marker (else the repo root).
    Keeps monorepos tractable; imports across sibling packages are not followed.
    Returns [] when no file mentions a hint (no annotated tools to check)."""
    roots = set()
    for path in src.rglob("*"):
        if path.suffix.lower() not in CODE_EXTS or not path.is_file():
            continue
        try:
            if not HINT_RE.search(path.read_text(encoding="utf-8", errors="ignore")):
                continue
        except OSError:
            continue
        d = path.parent
        while d != src and not any((d / m).exists() for m in PACKAGE_MARKERS):
            d = d.parent
        roots.add(d)
    # a root inside another root is analysed with it
    return sorted(r for r in roots if not any(o != r and o in r.parents for o in roots))


def run_detector(cmd, out_file):
    r = subprocess.run(cmd + ["--out", str(out_file)], capture_output=True, text=True, timeout=TIMEOUT,
                       encoding="utf-8", errors="replace", cwd=ROOT)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip().splitlines()[-1][:200] if r.stderr.strip() else f"exit {r.returncode}")
    if not out_file.exists():
        return []
    return [json.loads(line) for line in open(out_file, encoding="utf-8") if line.strip()]


def scan(repo):
    t0 = time.time()
    key = repo.replace("/", "__")
    row = {f: "" for f in FIELDS} | {"repo": repo}
    work = WORK / key
    try:
        sha = head_sha(repo)
        if not sha:
            return row | {"status": "unreachable", "seconds": round(time.time() - t0, 1)}
        row["sha"] = sha
        shutil.rmtree(work, ignore_errors=True)
        src = work / "src"
        src.mkdir(parents=True)
        archive = work / "a.tar.gz"
        download(repo, sha, archive)
        py, tsn = extract(archive, src)
        archive.unlink()
        row |= {"py_files": py, "ts_files": tsn}
        roots = analysis_roots(src)
        if not roots:
            return row | {"status": "no_hints", "tools": 0, "annotated": 0, "seconds": round(time.time() - t0, 1)}
        tools = []
        for i, root in enumerate(roots):
            prefix = root.relative_to(src).as_posix()
            has_py = any(root.rglob("*.py"))
            has_ts = any(p.suffix in CODE_EXTS - {".py"} for p in root.rglob("*.*"))
            runs = ([("python", [PYTHON, "detector/python/effects.py", str(root)])] if has_py else []) + \
                   ([("ts", ["node", "detector/ts/effects.js", str(root)])] if has_ts else [])
            for lang, cmd in runs:
                for t in run_detector(cmd, work / f"{lang}{i}.jsonl"):
                    if prefix != ".":  # paths relative to the repo root
                        t["file"] = f"{prefix}/{t['file']}"
                    tools.append(t | {"lang": lang, "package_root": prefix})
        if tools:
            with open(RESULTS / f"{key}.jsonl", "w", encoding="utf-8") as f:
                for t in tools:
                    f.write(json.dumps(t | {"repo": repo, "sha": sha}, ensure_ascii=False) + "\n")
        ann = [t for t in tools if t.get("annotations_kind") != "none"]
        row |= {"status": "ok", "tools": len(tools), "annotated": len(ann),
                "inconsistent_strict": sum(bool(t.get("inconsistencies")) for t in ann),
                "inconsistent_lenient": sum(bool(t.get("inconsistencies_lenient")) for t in ann),
                "review": sum(bool(t.get("review")) for t in ann)}
    except subprocess.TimeoutExpired:
        row |= {"status": "timeout"}
    except Exception as e:  # noqa: BLE001 - one bad repo must not stop the scan
        row |= {"status": "error", "error": f"{type(e).__name__}: {e}"[:200]}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    row["seconds"] = round(time.time() - t0, 1)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    with open(DATASET, encoding="utf-8") as f:
        repos = [r["github"] for r in csv.DictReader(f)]
    random.Random(args.seed).shuffle(repos)  # partial scans stay representative
    done = set()
    if MANIFEST.exists():
        with open(MANIFEST, encoding="utf-8") as f:
            done = {r["repo"] for r in csv.DictReader(f)}
    todo = [r for r in repos if r not in done][: args.limit]
    print(f"{len(repos)} repos, {len(done)} done, scanning {len(todo)} with {args.workers} workers", file=sys.stderr)

    new = not MANIFEST.exists()
    with open(MANIFEST, "a", newline="", encoding="utf-8") as f, ProcessPoolExecutor(args.workers) as pool:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        t0 = time.time()
        futures = [pool.submit(scan, r) for r in todo]
        for i, fut in enumerate(as_completed(futures), 1):
            w.writerow(fut.result())
            f.flush()
            if i % 25 == 0 or i == len(todo):
                rate = i / (time.time() - t0)
                print(f"{i}/{len(todo)}  {rate * 3600:.0f} repos/h  eta {(len(todo) - i) / rate / 3600:.1f} h",
                      file=sys.stderr)


if __name__ == "__main__":
    main()
