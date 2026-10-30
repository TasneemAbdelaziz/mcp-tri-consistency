"""Claude's D(t) proposals for the 30 calibration tools (model output, not a
human label). Made from the description only, with the rules in README.md,
without seeing Menna's labels, the annotations or the code.

v3 (2026-10-29): read and conditional-denial claims revised to rules RD and CD
(README); 8566 and 52440 network claims dropped (N2 v2: a name alone).
v2 (2026-10-29): network and write claims revised to the rules agreed after
Menna's review: a service name alone is not network; an operation-linked
quota or a bare API method/route is uncertain; deleting a field is not also a
write; persistence alone does not establish a write.

Each claim: (effect, polarity, scope, actor, condition, mode, world, evidence,
needs_review, notes). Effects without a claim are written as not_stated.
Run: python claude_proposals_30.py  ->  d_calibration_30_claude_proposals.xlsx
"""
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from make_d_labeling import COLUMNS, EFFECTS, write_sheet  # noqa: E402

HERE = Path(__file__).resolve().parent
A, D, U = "affirmed", "denied", "uncertain"


def c(effect, polarity, scope, evidence, actor="tool", condition="", mode="", world="", review="no", notes=""):
    return dict(effect=effect, polarity=polarity, scope=scope, actor=actor, condition=condition, mode=mode,
                world=world, evidence=evidence, needs_review=review, notes=notes)


P = {
    "census_v2:13401": [
        c("write", A, "database", "Add a single YouTuber to the database", mode="additive"),
        c("network", U, "remote_api", "cost an extra YouTube API quota point per call to resolve",
          condition="handle or URL passed instead of a channel ID", world="unknown",
          notes="N2 v2: operation-linked API quota, no connection described -> uncertain"),
    ],
    "census_v2:18830": [
        c("read", U, "database", "Margins and institutional flows come from different datasets",
          notes="RD: rows may arrive pre-fetched (rows_by_ticker)"),
    ],
    "census_v2:25575": [
        c("read", A, "database", "List every product category with its item count and sample products"),
    ],
    "census_v2:74402": [
        c("write", A, "database", "Change a calendar: its name, or whether it shows Saturdays and Sundays (weekends)",
          mode="modifying"),
        c("write", A, "database", "`add_data_sources` adds sources of events", mode="additive",
          condition="add_data_sources passed"),
        c("delete", A, "database", "`remove_data_source_ids` removes sources by the ids list_calendars shows",
          condition="remove_data_source_ids passed"),
    ],
    "census_v2:39392": [
        c("read", A, "remote_api", "Get order history for the active Schwab account."),
    ],
    "census_v2:21540": [
        c("network", A, "other", "Broadcast a signed TRON transaction", world="open",
          notes="other = public blockchain"),
        c("write", A, "other", "Broadcast a signed TRON transaction", mode="additive", notes="other = TRON ledger"),
        c("write", A, "other", "MERX purchases the deficit at the best\nmarket price before broadcasting",
          condition="target address lacks sufficient energy", mode="additive", review="yes",
          notes="purchase of energy; MERX is the server's own service, so actor = tool"),
    ],
    "census_v2:10422": [
        c("write", A, "database", "Append a new content block to a link-in-bio page.", mode="additive"),
        c("write", A, "database", "this saves an unpublished latest revision only", mode="additive",
          condition="page already published"),
    ],
    "census_v2:12866": [
        c("read", D, "database", "Does not read or change company records."),
        c("write", D, "database", "Does not read or change company records."),
        c("delete", D, "database", "Does not read or change company records.", notes="B1-style: 'change' covers delete"),
    ],
    "census_v2:8566": [],  # RD: a computed score; N2 v2: USAspending.gov is only named
    "census_v2:12702": [
        c("execute", A, "code", "An outside check on code, executed in a sealed sandbox.",
          notes="runs caller-supplied code"),
        c("write", A, "other", "Every delivered verdict is charged", actor="provider", condition="a verdict is delivered",
          mode="additive", review="yes", notes="payment charge; other = payment ledger"),
    ],
    "census_v2:60988": [
        c("read", A, "code", "statically check structured RevoGrid imports, configuration, dependencies, versions, and optional bounded source"),
        c("execute", D, "global", "Never executes code."),
    ],
    "census_v2:39151": [
        c("delete", A, "credentials", "Deletes one key from the operator's encrypted credential blob"),
        c("write", D, "credentials", "without rewriting\nthe vault", condition="field already absent",
          notes="CD: conditional denial, not a general one"),
    ],
    "census_v2:55458": [
        c("read", A, "remote_api", "List kata authored by a Codewars username"),
    ],
    "census_v2:26770": [
        c("read", A, "database", "return the most relevant patterns grouped by suite"),
    ],
    "census_v2:36678": [
        c("read", A, "database", "Returns the latest version/status info for a vault."),
    ],
    "census_v2:54045": [
        c("network", A, "remote_api", "Fetches the page", world="open", notes="N1: any URL"),
        c("read", A, "remote_api", "Fetches the page, extracts title/description/key links"),
    ],
    "census_v2:25993": [
        c("read", A, "credentials", "Returns the email's existing active key"),
        c("write", A, "credentials", "Idempotently issue a user's API key", mode="additive"),
        c("write", A, "credentials", "revokes\nthe existing keys and mints a fresh one", condition="rotate=true",
          mode="modifying"),
        c("delete", U, "credentials", "revokes\nthe existing keys", condition="rotate=true", review="yes",
          notes="open question: revocation as delete or modifying write"),
    ],
    "census_v2:56462": [
        c("write", A, "user_data", "Save data the agent will need to reuse later", mode="unknown",
          notes="key-value store: a reused key may overwrite"),
        c("delete", A, "user_data", "anonymous sessions retain memory for 24 hours", actor="provider",
          condition="anonymous session", notes="A1: expiry by the service"),
        c("delete", A, "user_data", "forget to delete", actor="other_tool"),
    ],
    "census_v2:52440": [
        c("read", A, "remote_api", "runs resolution_audit on both sides and compares source, settle time, precision, and evidence standard"),

    ],
    "census_v2:36107": [],
    "census_v2:69446": [
        c("read", A, "remote_api", "List expected payments (READ ONLY)."),
        c("write", D, "global", "READ ONLY", notes="B1"),
        c("delete", D, "global", "READ ONLY", notes="B1"),
        c("network", U, "remote_api", "API: GET /expected_payments", world="unknown", review="yes",
          notes="open question: relative API route without a host"),
    ],
    "census_v2:69614": [
        c("write", A, "remote_api", "updates a fundraising profile's goal/name/story", mode="modifying"),
        c("write", A, "remote_api", "Set overwriteCustomFields:true to overwrite", condition="overwriteCustomFields:true",
          mode="overwrite"),
        c("network", U, "remote_api", "Raisely API: PATCH /profiles/{path}", world="unknown",
          notes="N2 v2: method + route without a described call -> uncertain"),
    ],
    "census_v2:35417": [
        c("read", U, "remote_api", "Build a generic MCP Apps chart from one or more FXMacroData endpoint families",
          notes="RD: the description does not say whether the tool or the app fetches"),
        c("network", D, "other", "The tool does not fetch arbitrary URLs", notes="S1: arbitrary URLs only"),
        c("network", U, "remote_api", "it only composes approved FXMacroData API surfaces", world="closed",
          notes="bounded to approved surfaces"),
        c("execute", D, "code", "or run custom chart code"),
    ],
    "census_v2:60950": [
        c("read", A, "user_data", "Shows whether the account is connected, setup progress, verified wallets"),
        c("write", D, "global", "Read-only.", notes="B1"),
        c("delete", D, "global", "Read-only.", notes="B1"),
    ],
    "census_v2:71489": [
        c("write", A, "database", "Register a watch condition", mode="additive"),
        c("network", A, "remote_api", "real-time monitoring of prices, gas, weather, wallet balances/txs, or custom API endpoints",
          actor="provider", world="open", review="yes", notes="monitoring runs later on the service; custom endpoints = open"),
        c("write", A, "other", "$0.01 USDC per call via x402 on Base", actor="provider", mode="additive",
          notes="payment"),
    ],
    "census_v2:2573": [
        c("read", A, "other", "Validates ids, semver, descriptions, strict input/output schemas",
          notes="other = the supplied manifest"),
        c("execute", D, "code", "It never executes plugin code"),
        c("read", D, "credentials", "or loads provider secrets"),
    ],
    "census_v2:31007": [
        c("read", A, "database", "Get one self-hosted FEMA NFHL inventory unit by exact DFIRM ID."),
        c("read", D, "other", "It does not fetch or inspect the geodatabase", notes="S1: the geodatabase only"),
    ],
    "census_v2:59913": [
        c("read", A, "other", "Semantic search INSIDE a fetched record.", notes="other = text passed in"),
    ],
    "census_v2:9322": [
        c("execute", A, "code", "Run real code"),
        c("write", U, "filesystem", "get a persistent per-agent development environment at /workspace",
          condition="use_workspace=true", mode="unknown", notes="persistence alone does not establish a write"),
        c("network", U, "remote_api", "scraping + processing", world="unknown", review="yes",
          notes="scraping implies network but the description does not say the sandbox has it"),
    ],
    "census_v2:42102": [
        c("write", A, "remote_api", "Corrects the category of one or more transactions (PATCH /transactions/:id)",
          mode="modifying"),
        c("write", A, "remote_api", "recategorizing a transaction automatically creates a Category Rule for this client",
          mode="additive"),
        c("network", U, "remote_api", "This overrides Pluggy's automatic categorization", world="unknown",
          notes="names the Pluggy service; transport not stated"),
    ],
}


def main():
    blank = openpyxl.load_workbook(HERE / "d_calibration_30_tasneem.xlsx").active
    tools, descs = [], {}
    for r in blank.iter_rows(min_row=2, values_only=True):
        if r[1] not in descs:
            descs[r[1]] = r[4]
            tools.append(r[1:5])
    rows, bad = [], []
    for tool_id, server, tool, desc in tools:
        claims = P[tool_id]
        for e in EFFECTS:
            mine = [x for x in claims if x["effect"] == e]
            for x in mine or [dict(effect=e, polarity="not_stated")]:
                if x["polarity"] != "not_stated" and x["evidence"] not in desc:
                    bad.append((tool_id, e, x["evidence"]))
                rows.append([tool_id, server, tool, desc, e] + [x.get(k, "") for k in COLUMNS[6:]])
    if bad:
        raise SystemExit(f"evidence not in description: {bad}")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "claude_proposals"
    ws.append(COLUMNS)
    for i, r in enumerate(rows, 1):
        ws.append([i] + r)
    wb.save(HERE / "d_calibration_30_claude_proposals.xlsx")
    claims = sum(len(v) for v in P.values())
    print(f"{len(tools)} tools, {claims} claims, {len(rows)} rows; all evidence found in the descriptions")


if __name__ == "__main__":
    main()
