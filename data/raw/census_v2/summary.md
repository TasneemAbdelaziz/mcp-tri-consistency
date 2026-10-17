# MCP Registry Tool Annotation Census

> Field presence measures wire-level emission, not semantic annotation. See the value tables below.

## Field presence / schema coverage (all servers, all tools)

Servers (denominator): **3718**  
Tools (denominator): **77084**  
Presence = the field was serialized (true OR false). Denominators: inspected servers with >=1 tool; all extracted tools.

| Metric | Servers | Tools |
| --- | --- | --- |
| Successfully inspected | 3718 | 77084 |
| Any field present (schema coverage) | 2218 (59.7%) | 53832 (69.8%) |
| All four fields present (complete field emission) | 1470 (39.5%) >=1 tool; 1276 (34.3%) every tool | 37809 (49.0%) |
| No fields present | 1500 (40.3%) | 23252 (30.2%) |
| readOnlyHint field present | 2213 (59.5%) | 53065 (68.8%) |
| destructiveHint field present | 1863 (50.1%) | 45219 (58.7%) |
| idempotentHint field present | 1651 (44.4%) | 40278 (52.3%) |
| openWorldHint field present | 1950 (52.4%) | 47164 (61.2%) |

## Field values (primary semantic result)

Actual asserted value of each hint across all tools.

| Annotation | true | false | omitted |
| --- | --- | --- | --- |
| readOnlyHint | 43309 (56.2%) | 9756 (12.7%) | 24019 (31.2%) |
| destructiveHint | 2874 (3.7%) | 42345 (54.9%) | 31865 (41.3%) |
| idempotentHint | 35052 (45.5%) | 5226 (6.8%) | 36806 (47.7%) |
| openWorldHint | 27880 (36.2%) | 19284 (25.0%) | 29920 (38.8%) |

Applicability-aware destructiveness (verifiable against the readOnly x destructive cross-tab):

| Metric | Tools |
| --- | --- |
| Classified for destructiveness (DE present, RO!=true) | 10218 (13.3%) |
| Explicitly destructive (DE=true, RO!=true) | 2842 (3.7%) |
| Explicit non-destructive write (RO=false, DE=false) | 7134 (9.3%) |
| Contradiction (RO=true & DE=true) | 32 (0.0%) |

## Server-level differentiation

Across 3718 inspected servers with >=1 tool. A *signature* is a tool's (readOnly, destructive, idempotent, openWorld) value tuple.

| Metric | Servers |
| --- | --- |
| Emit no annotation fields | 1500 (40.3%) |
| One identical signature for every tool | 726 (19.5%) |
| Multiple signatures across tools | 1492 (40.1%) |

Of the 2173 servers with >=2 tools *and* some annotation, **68.7%** differentiate values between tools (1492 servers).

Among servers emitting any field: distinct signatures per server mean=3.04, median=2, p90=6, max=15; each server's dominant signature covers mean=80.0%, median=83.7%, p90=100.0%, max=100.0% of its tools.

## Side-effecting subset -- field presence (EXPLORATORY)

Servers (denominator): **1942**  
Tools (denominator): **11786**  
A server qualifies if >=1 tool looks side-effecting by a NAME HEURISTIC (see README); tool denominator = side-effecting tools only. Exploratory, not ground truth.

| Metric | Servers | Tools |
| --- | --- | --- |
| Successfully inspected | 1942 | 11786 |
| Any field present (schema coverage) | 1299 (66.9%) | 8169 (69.3%) |
| All four fields present (complete field emission) | 988 (50.9%) >=1 tool; 927 (47.7%) every tool | 5909 (50.1%) |
| No fields present | 643 (33.1%) | 3617 (30.7%) |
| readOnlyHint field present | 1231 (63.4%) | 7650 (64.9%) |
| destructiveHint field present | 1243 (64.0%) | 7769 (65.9%) |
| idempotentHint field present | 1052 (54.2%) | 6344 (53.8%) |
| openWorldHint field present | 1134 (58.4%) | 6909 (58.6%) |

## Side-effecting subset -- field values (EXPLORATORY)

Value breakdown for the heuristic side-effecting tools only. Exploratory, not ground truth.

| Annotation | true | false | omitted |
| --- | --- | --- | --- |
| readOnlyHint | 1644 (13.9%) | 6006 (51.0%) | 4136 (35.1%) |
| destructiveHint | 1865 (15.8%) | 5904 (50.1%) | 4017 (34.1%) |
| idempotentHint | 3504 (29.7%) | 2840 (24.1%) | 5442 (46.2%) |
| openWorldHint | 3468 (29.4%) | 3441 (29.2%) | 4877 (41.4%) |

Applicability-aware destructiveness (verifiable against the readOnly x destructive cross-tab):

| Metric | Tools |
| --- | --- |
| Classified for destructiveness (DE present, RO!=true) | 6373 (54.1%) |
| Explicitly destructive (DE=true, RO!=true) | 1863 (15.8%) |
| Explicit non-destructive write (RO=false, DE=false) | 4376 (37.1%) |
| Contradiction (RO=true & DE=true) | 2 (0.0%) |
