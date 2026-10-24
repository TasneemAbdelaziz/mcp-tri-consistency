# RQ2 preliminary: detector output on the 5,000-repo random sample

Repos scanned: 5,000. Status: ok 3,815, no_hints 868, unreachable 225, error 83, partial 7, timeout 2.

Candidate inconsistencies from the static detector, before validation against the labeled sample.

## All repos

- Tools with explicit annotations: 32,887 in 2,196 repos (TS/JS 24,250, Python 8,637)
- Inconsistent, strict: 4,584 (13.9%)
- Inconsistent, lenient (guide rules R1-R5 dropped): 3,698 (11.2%)
- Repos with at least one lenient inconsistency: 540 (24.6%)
- Only for review (fixed host, shared dispatcher): 1,164 (3.5%)

| Rule | Tools where it applies | Strict | Lenient |
|---|---|---|---|
| readOnlyHint=true, code writes | 19,421 | 1,666 (8.6%) | 1,083 (5.6%) |
| readOnlyHint=true, code deletes | 19,421 | 284 (1.5%) | 172 (0.9%) |
| readOnlyHint=true, code executes | 19,421 | 663 (3.4%) | 462 (2.4%) |
| destructiveHint=false, code deletes | 7,451 | 432 (5.8%) | 274 (3.7%) |
| destructiveHint=false, code modifies/overwrites | 7,451 | 1,025 (13.8%) | 859 (11.5%) |
| openWorldHint=false, request to an open target | 14,483 | 1,389 (9.6%) | 1,389 (9.6%) |

| Language | Tools | Lenient inconsistent |
|---|---|---|
| python | 8,637 | 911 (10.5%) |
| ts | 24,250 | 2,787 (11.5%) |

Effect kinds behind strict findings: plain 10,671, execute_fixed 2,464, execute_dynamic 1,600, bookkeeping 1,237, cleanup 1,104, temp 1,025, post_read_like 708, log 360

## Owners capped at 5 repos

- Tools with explicit annotations: 32,865 in 2,192 repos (TS/JS 24,250, Python 8,615)
- Inconsistent, strict: 4,583 (13.9%)
- Inconsistent, lenient (guide rules R1-R5 dropped): 3,697 (11.2%)
- Repos with at least one lenient inconsistency: 539 (24.6%)
- Only for review (fixed host, shared dispatcher): 1,164 (3.5%)

| Rule | Tools where it applies | Strict | Lenient |
|---|---|---|---|
| readOnlyHint=true, code writes | 19,412 | 1,666 (8.6%) | 1,083 (5.6%) |
| readOnlyHint=true, code deletes | 19,412 | 284 (1.5%) | 172 (0.9%) |
| readOnlyHint=true, code executes | 19,412 | 663 (3.4%) | 462 (2.4%) |
| destructiveHint=false, code deletes | 7,443 | 432 (5.8%) | 274 (3.7%) |
| destructiveHint=false, code modifies/overwrites | 7,443 | 1,024 (13.8%) | 858 (11.5%) |
| openWorldHint=false, request to an open target | 14,475 | 1,389 (9.6%) | 1,389 (9.6%) |

| Language | Tools | Lenient inconsistent |
|---|---|---|
| python | 8,615 | 910 (10.6%) |
| ts | 24,250 | 2,787 (11.5%) |

Effect kinds behind strict findings: plain 10,668, execute_fixed 2,464, execute_dynamic 1,600, bookkeeping 1,237, cleanup 1,104, temp 1,025, post_read_like 708, log 360

## Explicit vs omitted hints (all tools with any explicit hint)

| Hint | true | false | omitted |
|---|---|---|---|
| readOnlyHint | 19,421 | 11,087 | 1,960 |
| destructiveHint | 4,280 | 17,974 | 10,305 |
| openWorldHint | 9,568 | 14,483 | 8,756 |
