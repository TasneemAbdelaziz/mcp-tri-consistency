# MCP Tri-Consistency

Code, descriptions and annotations of MCP tools: when do they disagree, and
does it matter? Research code for the paper by Tasneem AbdElaziz and Menna Samy (AIU).

- **C(t)** what the code does (static analysis, `detector/`)
- **D(t)** what the description says (LLM extraction)
- **A(t)** what the annotations claim (`readOnlyHint`, `destructiveHint`, `openWorldHint`)

## Setup
```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```
`scripts/detect_languages.py` needs a read-only GitHub token in `GITHUB_TOKEN`.

## Pipeline
| Step | Script | Output |
|---|---|---|
| 1. Census with descriptions | `scripts/census.py` | `data/raw/census_v2/` |
| 2. Join with GitHub repos | `scripts/analyze_census.py` | `data/processed/census_joined.csv` |
| 3. Repo languages | `scripts/detect_languages.py` | `data/processed/repo_meta.jsonl` |
| 4. Filter (Python / TS) | `scripts/filter_census.py` | `data/processed/candidates.csv` |
| 5. Clone (full history) | `scripts/clone_repos.py` | `repos/`, `data/processed/repos_manifest.csv` |

See `data/README.md` for where each data file comes from.

## Layout
```
scripts/     data collection
detector/    sinks catalog, Python and TypeScript analyzers
labeling/    ground-truth guide and labels
data/        raw and processed data
repos/       cloned server repos (not committed)
```
