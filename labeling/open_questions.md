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

(none yet)
