# Description extraction v2

Prepared 20 October 2026. This is a development implementation after Claude's
review, with explicit corrections to its network, conflict, voting and HTTP
examples. v1 outputs and the assisted reference labels are retained unchanged.
No v2 model inference or independent human evaluation has been run.

## What changed

The extractor now produces claims, not one global status per effect. Every
claim preserves polarity, scope, actor, condition and exact evidence. Write
mode distinguishes additive from modifying actions. Network target describes
transport; interaction_domain describes open/closed entities independently.
We keep description-only input; names can be added in a separately logged
ablation, not silently mixed into this baseline.

## Run the development experiment

Upload Run_Prompt_v2_20_Tools.txt to a fresh conversation without v1 labels or
predictions, request execution of the instructions, and return the 20 JSONL
objects. This is an exploratory chat run, not a reproducible API benchmark.
API runs should record exact model ID, settings, date, raw output, hashes and
failures. Do not send reference labels or annotations to the extractor.

To validate and compare actual predictions locally, from the repository root:

```powershell
python description_v2/claims_pipeline.py --inputs description_v2/inputs_20.jsonl --predictions model_v2.jsonl --annotations pilot/tools_20.jsonl --out model_v2_review.json
python -m unittest discover -s description_v2 -p "test_*.py" -v
```

The first command rejects invalid output, unknown/duplicate/missing IDs, extra
keys and invented evidence. It does not repair outputs silently. All review
findings are saved with claim evidence. It does not invoke an LLM or tools.

## Deterministic aggregation

Only actor=tool claims affect derived statuses. Provider/user/other_tool
claims are retained. Unknown actors cause review. Any positive claim can
affirm an effect in its stated scope. A denial is global only if scope=global
and condition=null. Scoped or conditional denials are retained and flagged,
but do not become universal denials.

An affirmed and denied claim with overlapping scope and condition triggers
internal conflict and status=uncertain. Unknown overlap triggers review and
blocks an automatic annotation-inconsistency verdict for that effect. Different
literal condition texts are not treated as proven mutually exclusive. Known
disjoint resource scopes (e.g. database/filesystem) stay separate; language
versus resource scopes require review when their relation is unknown.

## Comparison profile v2

These are candidate declaration inconsistencies, not runtime proof or protocol
violations. MCP specification revision pinned: 2025-06-18, ToolAnnotations.
https://modelcontextprotocol.io/specification/2025-06-18/schema

* Explicit readOnlyHint=true: affirmed tool write/delete is a candidate.
  Affirmed execute alone is review, not an automatic inconsistency. Execution
  and mutation are separate concepts; inspect explicit effects and isolation.
* Explicit destructiveHint=false applies only when effective readOnlyHint=false.
  Tool delete or write mode=modifying/mixed is a candidate under our stated
  interpretation of additive updates. Unknown mode is review. A modifying write
  is not automatically data loss; report the policy and calibrate with the team.
* Explicit openWorldHint=false: require an affirmed tool network claim AND
  interaction_domain=open. A named service or literal host is not enough.
  Non-network interaction-domain assessment remains outside this transport-based
  implementation's coverage; open-world semantics are not defined by TCP alone.
* Uncertain relevant claims => review. Omitted hints never become explicit
  claims; effective readOnly defaults are used only to determine applicability.
* No detected candidate is not proof of consistency, completeness or safety.
* An unsafe readOnly=true declaration can be flagged even if its destructiveHint
  is inapplicable. Keep those two checks separate.

## Two-model agreement

Vote on the derived per-effect status, not exact phrasing of claim strings.
Identical affirmed/denied/not_stated statuses are retained; identical uncertain
is uncertain with review. Any disagreement is uncertain with review. Inherited
scope/actor/internal-conflict review flags are never cleared by agreement.
This status vote is a diagnostic only: do not use it as the contradiction
engine. Produce contradiction candidates from each model's complete claims;
compare/intersect rule-and-evidence findings after human calibration, because
agreeing on affirmed does not mean agreeing on scope, actor or domain.

## Pilot and evaluation boundaries

The 20 real examples remain development data, not human ground truth. The
contrastive fixtures are author-written software tests, not measured model
performance. Original reviewed CSV is not rewritten or migrated to claim-level
gold labels automatically. Next: blind dual-human calibration outside the held-
out evaluation set, freeze guide, and evaluate separate model runs against
adjudicated fresh tools. Repeatedly inspected validation data is development
data; keep the final test set untouched until evaluation.

## Important decisions

1. Broad read-only/no-state-change statements deny write and delete.
2. Scoped denials preserve their resource/language and any condition.
3. Named service references without clear transport are uncertain network;
   explicit remote communication can affirm network with domain unspecified.
4. Fixed-host public web search can be open; allowlisted caller-supplied URLs
   can be closed. Do not decide domain from host syntax alone.
5. Provider expiry is not automatically a tool delete; ambiguous actor or
   removal semantics remain review.
6. POST /api/search alone is uncertain read, not affirmed read/write.
7. Conflicting evidence is preserved and blocks an automatic verdict.
8. A pair of not_stated votes remains not_stated, with its missing-evidence
   limitation. It is not a pair of safety guarantees.

## Running the extracted standalone package

After extracting this ZIP, open a terminal in its folder:

```powershell
python claims_pipeline.py --inputs inputs_20.jsonl --predictions model_v2.jsonl --annotations annotations_20.jsonl --out model_v2_review.json
python -m unittest discover -s . -p "test_*.py" -v
```

Software verification: 29 unit tests passed; all 16 hand-authored expected records passed the strict built-in validator and the CLI aggregation path. These records are not model outputs. JSON Schema is supplied as a structural contract; external Draft 2020-12 meta-schema validation was not run because the optional library was unavailable. Runtime validation uses only the Python standard library. Scope strings must use the guide vocabulary; unrecognized scope relationships are sent for review rather than assumed disjoint.
