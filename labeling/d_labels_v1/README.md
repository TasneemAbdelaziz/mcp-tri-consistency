# D(t) labels v1: what each tool's description claims

Made by `scripts/make_d_labeling.py`. Schema: claim-level records from
`docs/Review_D_extraction_for_Menna.docx` (v1.1, section 3), with one fixed
vocabulary for both annotators.

| File | Who | Tools |
|---|---|---|
| `d_calibration_30_tasneem.xlsx` | Tasneem | the 30 tools Menna already labelled (`Menna_Reviewed_Proposals.csv`), blank |
| `d_sample_400_menna.xlsx` | Menna | the 400 tools of `labeling/sample_v1` (they have code, so C↔A, D↔A and C↔D all use one sample) |
| `d_sample_400_tasneem.xlsx` | Tasneem | same 400, for agreement |

`tool_id`: `census_v2:N` = line N (from 1) of `data/raw/census_v2/tools_full.jsonl`;
`sample_400:N` = row N of `labeling/sample_v1/sample_400_key.csv`.

## Blind rules

Label from the **server, tool name and description only**. Do not look at the
tool's annotations, its code, any model output, or the other annotator's file.
16 of the 400 tools have no description in their code: label all five effects
`not_stated` and write `no description` in notes.

## Filling the sheet

There is one row per tool and effect. For a second claim about the same effect
(for example a scoped denial and a global affirmation), copy the row below it
and fill the copy. Leave `not_stated` rows otherwise empty.

| Column | Values |
|---|---|
| `polarity` | not_stated / affirmed / denied / uncertain |
| `scope` | global / filesystem / database / remote_api / credentials / messages / code / user_data / other |
| `actor` | tool / provider / other_tool / user |
| `condition` | free text, or empty |
| `mode` | write only: additive / modifying / overwrite / unknown |
| `world` | network only: open / closed / unknown |
| `evidence` | an exact substring of the description (required unless not_stated) |
| `needs_review` | no / yes |
| `notes` | free text; for `other` scope, say what the resource is |

Changes from Menna's first file, so both files compare directly: `scope` uses
the fixed list above (free text goes in notes); `actor` has no `unknown`
(use the closest value and needs_review = yes); `target` and
`interaction_domain` are merged into `world`.

## Rules (from the review, section 4)

| Rule | Case | Label |
|---|---|---|
| U1 | not_stated vs uncertain | uncertain only with a quote that bears on the effect but leaves it open |
| B1 | "read-only", "no state changes", "no side effects" | denied write and denied delete, scope global; nothing about execute or network |
| S1 | "no filesystem access", "does not execute JavaScript" | denial with that scope only |
| A1 | expiry or cleanup done by a provider | actor = provider |
| A2 | "then call submit_x" | actor = other_tool |
| N1 | "fetches the URL you provide" | network affirmed, world open |
| N2 | a named service | network affirmed if clearly not the server's own, else uncertain; world from the interaction, a name alone = unknown |
| H1 | an HTTP method shown | not write by itself; judge the action (a path like /search can show it) |
| E1 | returns a command or code without running it | not execute |

Open questions from Menna's first round (decide in the calibration meeting,
then add here): an API quota or a relative API route without a host (uncertain
network?); revocation (delete or modifying write?); persistence alone as
evidence of a write.

## Protocol

1. Tasneem labels the 30 calibration tools blind; compute kappa against
   Menna's labels per effect (on the derived status and on polarity); settle
   every disagreement, including Menna's 18 needs_review items; update the rules.
2. Both label the 400 independently with the frozen rules; kappa; adjudicate.
3. The derived status per effect and the D↔A / C↔D comparisons are computed
   by code from these sheets.

Note: 5 descriptions contain U+FFFD (a character lost in the source file's
encoding); they are left as they are.
