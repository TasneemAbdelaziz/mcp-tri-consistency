# Labeling guide: C<->A ground truth

Draft v0.1 (2026-10-19), agreed by Tasneem; **pending Menna's review** before the
30-tool calibration round. Changes after calibration go in the changelog at the end.

## What a label is

For each tool, each annotator reads the tool's code (handler + everything it calls)
and answers, independently, one question per hint that is **explicitly set**:

| Hint (explicit) | Label `inconsistent` when the code can... |
|---|---|
| `readOnlyHint: true` | change the environment (rule P2 below) |
| `destructiveHint: false` | lose or overwrite data that existed before the call (P1) |
| `openWorldHint: false` | reach an external system over the network |

Omitted hints get no label: the SDK default (`readOnly=false`, `destructive=true`,
`openWorld=true`) can never contradict the code. `destructiveHint` is only labeled
when `readOnlyHint` is not `true` (the spec says it is meaningless otherwise).

## The principle

Judge the environment **as the user sees it after the call has finished**:

- **P1 destructive:** data that existed before the call is deleted or overwritten.
- **P2 not read-only:** any change that persists after the call and affects later calls or the user.
- **P3 does not count:** temporary state the tool creates and removes within the same call.

This follows the MCP spec: `readOnlyHint` = "does not modify its environment",
`destructiveHint=false` = "performs only additive updates".

## Rules for the cases we have already met

| # | Case | Label | Why | Real example |
|---|---|---|---|---|
| R1 | Deleting internal bookkeeping that the operation itself ends (e.g. `.git/MERGE_HEAD` after a merge commit) | consistent with `destructive=false` | Part of completing the operation, as the underlying tool does it; no user data is lost (P1 not met) | official `git` server, `git_commit` |
| R2 | Cleaning up an output file the tool created in the same call (failed or partial output) | consistent, **unless** the path comes from the user and may pre-exist: then writing it is an overwrite → `destructive` | P3; but overwriting an existing user file meets P1 | `NTL-GPT-Clone`, `clip_raster` |
| R3 | Running an external program | judge by **what the program does**: a fixed program with no lasting effect is consistent; a command built from user input (a shell tool) is `inconsistent` with `readOnly=true` | Running a process is not itself a change; an arbitrary command can do anything | `ciscolive-potpourri`, `generate_password` (consistent) |
| R4 | HTTP POST | judge by **what the endpoint does**, not the verb: search, token, GraphQL `query` = read; GraphQL `mutation` and create/update endpoints = write | Many APIs read through POST | `ciscolive-potpourri`, `get_client_details` (token POST = read) |
| R5 | Writing logs / journals | diagnostic logs (`logging`, debug files) = consistent; persisting state that later calls or the user read (records, journals, caches the user sees) = `inconsistent` with `readOnly=true` | Every server logs; P2 is about lasting, meaningful state | `kalshi-ai-trading-bot`, `settle` (inconsistent) |
| R6 | `git checkout` | switching to an existing ref = write (non-destructive; git refuses to drop local changes without `--force`); checking out **paths** or `--force` = destructive | Branch switch is protected by git; path checkout discards edits | official `git` server, `git_checkout` (consistent: validates the ref, rejects `-` flags) |

## How the detector supports this

Every effect the detector reports carries a `kind`. Kinds R1–R5 mark the cases
above, so the paper can report results **strict** (every sink counts) and
**lenient** (these kinds dropped): see `detector/python/effects.py`.

| `kind` | Rule | Dropped in lenient |
|---|---|---|
| `bookkeeping` | R1 | yes |
| `cleanup` | R2 | yes |
| `execute_fixed` | R3, fixed program | yes |
| `execute_dynamic` | R3, command from input | no |
| `post_read_like` | R4 | yes |
| `log` | R5, diagnostic | yes |
| `plain` | anything else | no |

When the label and the detector disagree, the label wins; note the case here.

## Open for calibration

- R2 needs the annotator to check whether the output path is user-controlled and may pre-exist.
- R5 boundary: a cache file the user never sees. Proposed: consistent (not "meaningful state").

## Changelog

- v0.1 (2026-10-19): P1–P3 and R1–R6 from the first 14 sampled repos.
