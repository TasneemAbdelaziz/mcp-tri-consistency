# Open questions for the labeling guide

The first six questions were decided on 2026-10-19 and are now rules R1-R6 in
[guide.md](guide.md) (pending Menna's review). New questions go below.

| # | Case | Decision | Rule |
|---|---|---|---|
| 1 | Deleting internal bookkeeping (`.git/MERGE_HEAD`) | consistent | R1 |
| 2 | Cleanup of the tool's own partial output | consistent, unless the path is user-controlled and may pre-exist | R2 |
| 3 | Running a process that changes nothing | judge by the program; a command from user input is inconsistent | R3 |
| 4 | POST used for reading | judge by the endpoint; GraphQL query = read | R4 |
| 5 | Logs / journals | debug logs consistent; persisted state inconsistent | R5 |
| 6 | `git checkout` | branch switch = write; `--force` / paths = destructive. The official tool validates the ref: consistent | R6 |

## New questions

| # | Case | Example | Status | Question |
|---|---|---|---|---|
| 7 | Deletion gated by configuration, and really a move | `BlockRunAI/blockrun-mcp`: with `BLOCKRUN_KEYCHAIN=strict`, loading the wallet moves the key into the OS keychain and `rmSync`s the plaintext file; reached from 5 tools marked `destructiveHint=false` | open | Is a deletion that only runs under an opt-in setting, and preserves the data elsewhere, destructive? |
| 8 | POST as a probe | same repo, `blockrun_polymarket_read` (`readOnlyHint=true`) POSTs an empty body to `/order` only to read the 403 geoblock status | R4 suggests consistent | Confirms R4: judge by what the request does, not the verb. |
