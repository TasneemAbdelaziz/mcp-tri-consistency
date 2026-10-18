# Open questions for the labeling guide

Cases the detector reports that need a labeling decision before the pilot.
Each one comes from a real repo; decide together, then write the rule into the guide.

| # | Case | Example | Detector says | Question |
|---|---|---|---|---|
| 1 | Deleting internal bookkeeping | official `git` server, `git_commit` deletes `.git/MERGE_HEAD` after a merge commit (`server.py:223`) | `destructiveHint=false` + delete | Does removing the tool's own internal state count as destructive? |
| 2 | Cleanup of partial outputs | `guihousun/NTL-GPT-Clone`, `clip_raster` etc. unlink their own failed output file | `destructiveHint=false` + delete | Same as 1, but on files the tool itself just created. |
| 3 | Running a process that changes nothing | `CLEURNOC/ciscolive-potpourri`, `generate_password` runs `hankify-pw` | `readOnlyHint=true` + execute | Is a side-effect-free subprocess a readOnly violation? The plan's rule says yes (execute). |
| 4 | POST used for reading | same repo, `get_client_details` POSTs to get an auth token | `readOnlyHint=true` + write (HTTP POST) | Auth/search endpoints use POST without changing state. Label as consistent? |
| 5 | Append-only logs / journals | `ryanfrigo/kalshi-ai-trading-bot`, `settle` appends to a settlements file | `readOnlyHint=true` + write | Looks like a true inconsistency; confirm. |
| 6 | `git checkout` marked non-destructive | official `git` server, `git_checkout` (`destructiveHint=false`) | write only (checkout is in the write list) | A checkout can overwrite local changes. Should checkout be a delete/overwrite sink? |
