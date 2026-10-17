# Data

## external/ (not committed)
`git clone https://github.com/flame-stream/mcp-annotation-census data/external/mcp-annotation-census`
at commit `5c24643`. Its `output_full2/registry_snapshot.json` is the registry
snapshot every run below uses.

## raw/census_v2/
Our re-run of the census (`scripts/census.py`, run 2026-10-12, same snapshot)
that also records each tool's title, description and inputSchema.

- `tools_full.jsonl.gz`: one JSON object per tool (description, input_schema,
  annotation states true/false/omitted, raw_annotations). Decompress with
  `gunzip -k`. The uncompressed file is not committed (125 MB > GitHub limit).
- `registry_snapshot.json` is not committed; it is identical to the one in external/.

## processed/
- `census_joined.csv`: union of census_v2 and the original census
  (`scripts/analyze_census.py data/raw/census_v2 data/external/mcp-annotation-census/output_full2`),
  joined with the GitHub repo of each server. `source` says which run a server came from.
- `repo_meta.jsonl`: GitHub metadata + language bytes per repo (`scripts/detect_languages.py`).
- `candidates.csv`: servers kept for static analysis (`scripts/filter_census.py`).
- `repos_manifest.csv`: cloned repos with the exact commit SHA (`scripts/clone_repos.py`).
