# Labeling sample v1 (C↔A ground truth)

Drawn 2026-10-23 by `scripts/make_labeling_sample.py --seed 11` from the scan
results available then (498 repos with annotated tools, 6,882 tools).

| File | For | Contents |
|---|---|---|
| `calibration_30_<name>.xlsx` | each annotator | 30 tools for the calibration round |
| `sample_400_<name>.xlsx` | each annotator | the 400-tool evaluation sample |
| `*_key.csv` | **analysis only, do not open while labeling** | stratum, inclusion probability, annotations, description, detector output |

## How to label (both annotators, independently)

1. Read [`../guide.md`](../guide.md) first: principle P1–P3 and rules R1–R6.
2. For each row, open **definition** (where the tool is registered) and
   **handler** (the code it runs). Follow the calls it makes as far as you need.
   The links point at the exact commit that was analysed.
3. Fill the columns from **what the code does**. Do not look up the tool's
   annotations, its description, or the key file: the inconsistency is computed
   later from your labels and the annotations, so your labels stay independent
   of both the annotations and the detector.

| Column | Values | Meaning |
|---|---|---|
| `writes` | no / yes / unsure | changes state that persists after the call (file, database, remote API, git) |
| `write_mode` | additive / modifying / overwrite / unknown | only if writes = yes: adds new state, changes existing state, or may replace an existing file/object |
| `deletes` | no / yes / unsure | removes data that existed before the call |
| `executes` | no / fixed program / command from input / unsure | runs a process or evaluates code |
| `network` | no / open target / fixed host / unsure | open = the target comes from input or is arbitrary (URLs, web search); fixed = a hard-coded host |
| `special_case` | R1 … R6 / other | the effect falls under a guide rule (say which); "other" + notes for a new case |
| `could_not_trace` | no / yes | the code could not be followed (generated, missing, external package) |
| `notes` | text | anything a second reader needs, especially for unsure / other |

Count an effect when **any path** of the tool can do it, not only the usual one.

## Protocol

1. **Calibration (30):** both label independently, then compare every
   disagreement together and update `guide.md` (bump its version). These 30 are
   not part of the evaluation.
2. **Main sample (400):** label independently with the frozen guide; do not
   discuss items until both are done.
3. **Agreement:** Cohen's κ per column (target ≥ 0.7), plus PABAK for rare effects.
4. **Adjudication:** settle disagreements together; keep both original labels,
   the final one and the reason. A third person settles what remains.

Expected effort: about 3 minutes per tool, about 20 hours per annotator for 400.

## Notes for the analysis

- Strata: flagged 169, clean_risky 168, clean_other 40, review 23. Use
  `inclusion_prob` to re-weight prevalence; precision comes from `flagged`,
  recall from `clean_risky`.
- Languages: 306 TypeScript/JavaScript, 94 Python (proportional to the population).
- At most 2 tools per repo and 3 per owner (template families).
- Blindness is on trust: the key files are in this folder.
