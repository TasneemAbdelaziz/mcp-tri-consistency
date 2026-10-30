# C(t) labels for the 40 evaluation tools

Hand labels of what the **code** does, to measure the detector (RQ1). Same 40
tools as `labeling/d_labels_v1/d_eval_40_*.xlsx`; join on `id` (`sample_400:N`).
Made by `scripts/make_c_eval_40.py`.

| File | Who |
|---|---|
| `c_eval_40_tasneem.xlsx` | Tasneem |
| `c_eval_40_menna.xlsx` | Menna |

## Order

1. Finish the **description** sheet (`d_eval_40_*.xlsx`) first.
2. Leave a day or two.
3. Then do this sheet, without going back to the description sheet.

## Blind rules

Label from the code only. Do not look up the tool's annotations, its
description, the detector's output, the key files or the other annotator's
sheet. Each annotator works alone; agreement (kappa) is computed before any
discussion.

## How to label

For each row, open **definition** (where the tool is registered) and
**handler** (the code it runs), and follow the calls as far as you need. The
links point at the exact commit that was analysed. Count an effect when **any
path** of the tool can do it.

Column meanings and rules are in `labeling/sample_v1/README.md` and
`labeling/guide.md` (P1-P3, R1-R6). If the code cannot be followed (generated,
missing, an external package), set `could_not_trace = yes`.
