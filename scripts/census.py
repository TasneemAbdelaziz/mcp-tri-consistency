#!/usr/bin/env python3
"""MCP Registry Tool Annotation Census.

Adapted from flame-stream/mcp-annotation-census (MIT, see CENSUS_LICENSE).
Change for the MCP tri-consistency paper: each tool's title, description,
inputSchema and raw annotations dict are also saved to tools_full.jsonl,
so the description channel D(t) can be compared with the annotations A(t).

Measures how often the four standard MCP tool annotations
(readOnlyHint, destructiveHint, idempotentHint, openWorldHint) are used by
servers listed in the Official MCP Registry.

The script:
  1. Downloads all server entries from the Official MCP Registry public API.
  2. Keeps the latest version of each server.
  3. Probes every server exposing a remote endpoint (streamable-http / sse)
     ANONYMOUSLY -- including servers that declare an auth header -- and calls
     tools/list. It NEVER calls or executes any tool. A server is recorded as
     'authentication required' only if it actually returns HTTP 401/403.
  4. Records, per tool, whether each annotation is explicitly true, explicitly
     false, or omitted -- preserving that three-way distinction.
  5. Writes a raw registry snapshot, per-server / per-tool / failure CSVs, a
     per-field value breakdown, and a summary table (CSV + Markdown).

Usage:
    python census.py
    python census.py --limit 20
    python census.py --concurrency 10 --timeout 15
    python census.py --resume
    python census.py --snapshot output/registry_snapshot.json

See README.md for how each metric is defined and computed.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import httpx

# The four standard MCP tool annotations, in the order used throughout output.
STANDARD_ANNOTATIONS = (
    "readOnlyHint",
    "destructiveHint",
    "idempotentHint",
    "openWorldHint",
)

REGISTRY_BASE_URL = "https://registry.modelcontextprotocol.io"
LIST_ENDPOINT = "/v0.1/servers"
PAGE_LIMIT = 100  # Registry max page size.

# Sentinels for the three-way annotation state.
TRUE = "true"
FALSE = "false"
OMITTED = "omitted"

# MCP spec default value for each hint (used for the default-aware value view).
# A value equal to its default carries no author-chosen information.
SPEC_DEFAULTS = {
    "readOnlyHint": FALSE,
    "destructiveHint": TRUE,
    "idempotentHint": FALSE,
    "openWorldHint": TRUE,
}

DEFAULT_OUTPUT = Path("output")
DEFAULT_CONCURRENCY = 5
DEFAULT_TIMEOUT = 30.0  # seconds per MCP connection attempt


# --------------------------------------------------------------------------- #
# Side-effect classification (name heuristic)
# --------------------------------------------------------------------------- #
# IMPORTANT: This is a NAME-BASED HEURISTIC, deliberately independent of the
# annotations we measure, so that annotation statistics computed on the
# side-effecting subset are not circular. It does NOT read readOnlyHint/etc.
# It is a rough guess -- it looks at the verb tokens in the tool name and does
# not verify actual behaviour. Treat the side-effect numbers as indicative.
#
# Classification rules (in order):
#   1. If the FIRST token is a read verb (get/list/search/...), the tool is a
#      read -- regardless of any later token. The leading verb defines what the
#      tool does. This is the key fix for names like "get_start_path" or
#      "get_features_export", where an object noun happens to look like a verb.
#   2. Otherwise, if the first token is a "compute" verb (generate/analyze/...),
#      the tool computes and returns a result -> treat as a read. This removes a
#      systematic false-positive cluster seen in the registry ("generate_diagram",
#      "build_source_pack", "start_demand_report" all declared readOnlyHint=true).
#   3. Otherwise, if any token is a mutating verb, the tool is side-effecting.
#   4. Otherwise (no verb at all -> just nouns), default to NOT side-effecting.
# Verb lists were tuned against a ~1300-tool registry sample (see audit_heuristic.py).
SIDE_EFFECT_VERBS = frozenset({
    "create", "update", "delete", "remove", "write", "set", "put", "patch",
    "post", "send", "publish", "unpublish", "add", "insert", "append", "upsert",
    "edit", "modify", "rename", "move", "copy", "upload", "save", "store",
    "register", "unregister", "deregister", "enable", "disable", "start", "stop",
    "restart", "invoke", "trigger", "deploy", "provision",
    "cancel", "revoke", "grant", "approve", "reject", "merge", "commit", "push",
    "sync", "import", "install", "uninstall", "reset", "clear", "purge", "drop",
    "truncate", "flush", "schedule", "assign", "unassign", "attach", "detach",
    "link", "unlink", "activate", "deactivate", "archive", "restore", "submit",
    "apply", "increment", "decrement", "vote", "like", "follow", "unfollow",
    "subscribe", "unsubscribe", "pay", "charge", "refund", "transfer", "mint",
    "burn",
    # cache/state mutators (servers mark these destructive=false but they write)
    "refresh", "invalidate",
    # write verbs found missing in the registry audit
    "request", "initiate", "report", "rotate", "launch", "book", "claim",
    "toggle", "terminate", "rollback", "hide", "unhide", "reply", "ack",
    "acknowledge", "kill", "abort", "pause", "resume", "order", "buy", "sell",
    "redeem", "withdraw", "deposit", "stake", "unstake", "swap", "bridge",
    "sign", "spawn", "enqueue", "dispatch", "emit", "log", "record", "track",
    "seed", "reindex", "rebuild",
})

# Read verbs. If the FIRST name token is one of these, the tool is a read even
# if a later token collides with a mutating verb ("export" as a noun, etc.).
# "export"/"download" live here as leading verbs (export_data == read-only dump)
# but are intentionally NOT in SIDE_EFFECT_VERBS.
READ_VERBS = frozenset({
    "get", "list", "search", "read", "query", "fetch", "check", "show",
    "describe", "find", "count", "view", "resolve", "lookup", "browse",
    "inspect", "export", "download", "summarize", "explain",
})

# "Compute" verbs: produce and RETURN a derived result rather than persist it.
# As a LEADING token these read; as a later token they don't force side effects.
# (Registry servers annotate generate_*/analyze_* etc. with readOnlyHint=true.)
COMPUTE_VERBS = frozenset({
    "generate", "analyze", "analyse", "predict", "compute", "calculate",
    "simulate", "estimate", "forecast", "draft", "compare", "evaluate",
    "score", "rank", "detect", "classify", "extract", "parse", "render",
    "preview", "suggest", "recommend", "plan", "validate", "verify",
})

# Ambiguous "do something" verbs: side-effecting by default, but a read when
# they wrap a read/compute verb (execute_read_portfolio, run_analysis_report).
ACTION_VERBS = frozenset({"run", "execute", "exec"})

_TOKEN_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


def _name_tokens(name: str) -> list[str]:
    """Split a tool name into lowercase word tokens (snake/kebab/camel-aware)."""
    tokens: list[str] = []
    for part in re.split(r"[^A-Za-z0-9]+", name):
        if not part:
            continue
        # Split camelCase / PascalCase into words.
        tokens.extend(_TOKEN_RE.findall(part) or [part])
    return [t.lower() for t in tokens]


def is_side_effecting(tool_name: str) -> bool:
    """Heuristic: does this tool name suggest a write / side effect?"""
    tokens = _name_tokens(tool_name)
    if not tokens:
        return False
    first = tokens[0]
    # Rule 1: a leading read verb wins (get_start_path is a read).
    if first in READ_VERBS:
        return False
    # Rule 2: a leading compute verb returns a derived result -> read.
    # (generate_diagram / analyze_x / build a report: registry marks these
    # readOnlyHint=true.) But "execute"/"run" that wrap a read/compute verb
    # (execute_read_portfolio, run_analysis) are reads too.
    if first in COMPUTE_VERBS:
        return False
    # Rule 3: ambiguous action verbs (run/execute/exec) mean "do something" ->
    # side-effecting, UNLESS they wrap a read/compute verb (execute_read_x).
    if first in ACTION_VERBS:
        if len(tokens) > 1 and (tokens[1] in READ_VERBS
                                or tokens[1] in COMPUTE_VERBS):
            return False
        return True
    # Rule 4: any mutating verb token.
    return any(tok in SIDE_EFFECT_VERBS for tok in tokens)


# --------------------------------------------------------------------------- #
# Progress reporting
# --------------------------------------------------------------------------- #
def _progress(msg: str, *, done: bool = False) -> None:
    """Write a single self-overwriting progress line to stderr.

    Uses a carriage return so successive updates rewrite the same line on a
    TTY. When stderr is not a TTY (redirected to a file), fall back to plain
    newline-terminated lines so logs stay readable.
    """
    if sys.stderr.isatty():
        sys.stderr.write("\r\033[K" + msg)
        if done:
            sys.stderr.write("\n")
        sys.stderr.flush()
    else:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()


def _bar(fraction: float, width: int = 24) -> str:
    fraction = max(0.0, min(1.0, fraction))
    filled = int(round(fraction * width))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


# --------------------------------------------------------------------------- #
# Registry download
# --------------------------------------------------------------------------- #
def _get_page_with_retry(client: httpx.Client, params: dict[str, Any],
                         retries: int = 4) -> dict[str, Any]:
    """GET one page, retrying transient network errors with linear backoff.

    Backoff is deterministic (no sleep-jitter) so runs stay reproducible.
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.get(LIST_ENDPOINT, params=params)
            resp.raise_for_status()
            return resp.json()
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            if attempt < retries - 1:
                wait = 2.0 * (attempt + 1)
                _progress(f"  page fetch failed ({type(exc).__name__}); "
                          f"retry {attempt + 1}/{retries - 1} in {wait:.0f}s")
                time.sleep(wait)
    raise RuntimeError(f"page fetch failed after {retries} attempts") from last_exc


def fetch_registry_snapshot(limit_pages: int | None = None,
                            checkpoint_path: Path | None = None
                            ) -> list[dict[str, Any]]:
    """Download all server entries via cursor pagination.

    Returns the list of raw ServerResponse objects (each has "server" and
    "_meta"). `limit_pages` caps the number of pages for quick testing.
    If `checkpoint_path` is given, the growing snapshot is flushed to that file
    every few pages so a mid-download crash leaves a reusable partial snapshot.
    """
    entries: list[dict[str, Any]] = []
    cursor: str | None = None
    pages = 0
    # Generous read timeout: the registry list endpoint can be slow per page.
    timeout = httpx.Timeout(connect=15.0, read=90.0, write=15.0, pool=15.0)
    with httpx.Client(base_url=REGISTRY_BASE_URL, timeout=timeout) as client:
        while True:
            params: dict[str, Any] = {"limit": PAGE_LIMIT}
            if cursor:
                params["cursor"] = cursor
            body = _get_page_with_retry(client, params)
            page = body.get("servers", [])
            entries.extend(page)
            pages += 1
            cursor = (body.get("metadata") or {}).get("nextCursor") or (
                body.get("metadata") or {}
            ).get("next_cursor")
            # Total count is unknown up front, so show a running spinner.
            spin = "|/-\\"[pages % 4]
            _progress(f"Downloading registry {spin} page {pages}, "
                      f"{len(entries)} entries")
            # Periodic checkpoint so a crash leaves a reusable snapshot.
            if checkpoint_path is not None and pages % 10 == 0:
                checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
                checkpoint_path.write_text(json.dumps(entries), encoding="utf-8")
            if not cursor:
                break
            if limit_pages is not None and pages >= limit_pages:
                break
    _progress(f"Downloaded {len(entries)} entries in {pages} pages", done=True)
    return entries


def latest_per_server(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the latest version of each distinct server name.

    Prefers the entry flagged isLatest; otherwise falls back to the last-seen
    entry for that name (registry returns them in a stable order).
    """
    chosen: dict[str, dict[str, Any]] = {}
    for entry in entries:
        server = entry.get("server", {})
        name = server.get("name")
        if not name:
            continue
        official = _official_meta(entry)
        is_latest = official.get("isLatest", False)
        if name not in chosen or is_latest:
            chosen[name] = entry
    return list(chosen.values())


def _official_meta(entry: dict[str, Any]) -> dict[str, Any]:
    return (entry.get("_meta") or {}).get(
        "io.modelcontextprotocol.registry/official", {}
    ) or {}


# --------------------------------------------------------------------------- #
# Server selection / transport
# --------------------------------------------------------------------------- #
@dataclass
class Target:
    """A remote server we will attempt to inspect."""

    name: str
    version: str
    transport: str  # "streamable-http" or "sse"
    url: str
    requires_auth: bool  # heuristic: remote declares header/variable inputs


def select_targets(entries: list[dict[str, Any]]) -> tuple[list[Target], list[dict]]:
    """Split latest entries into inspectable remote targets and pre-known failures.

    Remote scope: any streamable-http / sse remote is a target, INCLUDING
    servers whose registry entry declares a required auth header/variable. Such
    a declaration means the server advertises wanting a credential, but it does
    NOT mean tools/list itself is gated -- many servers allow anonymous
    discovery and only require auth to CALL a tool. We therefore probe them
    anonymously anyway and only record 'authentication required' if the
    connection actually returns 401/403 (handled by _classify_error). The
    Target.requires_auth flag records the declaration for reference.

    Only servers with no usable remote (package/stdio-only) are pre-failed
    without a network attempt, as 'unsupported transport'.
    """
    targets: list[Target] = []
    prefailures: list[dict] = []

    for entry in entries:
        server = entry.get("server", {})
        name = server.get("name", "<unknown>")
        version = server.get("version", "")
        remotes = server.get("remotes") or []

        if not remotes:
            prefailures.append(_failure_row(name, version, "unsupported transport",
                                             "no remotes (package/local only)"))
            continue

        # Prefer streamable-http, then sse. Ignore stdio (local).
        remote = _pick_remote(remotes)
        if remote is None:
            prefailures.append(_failure_row(name, version, "unsupported transport",
                                             "only stdio/unknown transports"))
            continue

        targets.append(Target(
            name=name,
            version=version,
            transport=remote["type"],
            url=remote["url"],
            # Declaration only; we still probe anonymously. Actual auth
            # enforcement is detected at connection time (401/403).
            requires_auth=_remote_requires_auth(remote),
        ))

    return targets, prefailures


def _pick_remote(remotes: list[dict]) -> dict | None:
    for wanted in ("streamable-http", "sse"):
        for remote in remotes:
            if remote.get("type") == wanted and remote.get("url"):
                return remote
    return None


def _remote_requires_auth(remote: dict) -> bool:
    """Heuristic: treat a remote as auth-required if it declares required
    header inputs or required variables (the server needs a value from us)."""
    for header in remote.get("headers") or []:
        if header.get("isRequired") or header.get("required"):
            return True
    for _, var in (remote.get("variables") or {}).items():
        if isinstance(var, dict) and (var.get("isRequired") or var.get("required")):
            return True
    return False


# --------------------------------------------------------------------------- #
# MCP inspection
# --------------------------------------------------------------------------- #
@dataclass
class ToolRecord:
    server_name: str
    server_version: str
    tool_name: str
    # Each is "true" / "false" / "omitted".
    annotations: dict[str, str] = field(default_factory=dict)
    # Name-heuristic guess only (see is_side_effecting); not from annotations.
    side_effecting: bool = False
    # Full tools/list payload for D(t) extraction (saved to tools_full.jsonl).
    title: str | None = None
    description: str | None = None
    input_schema: dict[str, Any] | None = None
    raw_annotations: dict[str, Any] | None = None


@dataclass
class InspectResult:
    target: Target
    ok: bool
    tools: list[ToolRecord] = field(default_factory=list)
    failure_reason: str = ""
    detail: str = ""


def annotation_state(raw_annotations: dict[str, Any] | None, key: str) -> str:
    """Three-way state of a single annotation from the RAW JSON dict.

    Using the raw JSON (not the parsed pydantic model, whose fields all default
    to None) is what lets us distinguish explicit false from omitted.
    """
    if not raw_annotations or key not in raw_annotations:
        return OMITTED
    value = raw_annotations[key]
    if value is True:
        return TRUE
    if value is False:
        return FALSE
    # Non-boolean value present -> treat as present-but-not-a-bool == omitted-ish.
    # We keep it simple: present truthy/falsey coerced.
    return TRUE if value else FALSE


async def _connect_and_list(target: Target, timeout: float) -> Any:
    """Open the transport, initialize, and return the tools/list result.

    Every step -- including entering the transport context manager, which is
    where a silent/hung SSE endpoint can otherwise block forever -- runs inside
    the single overall deadline applied by the caller via wait_for().
    """
    from mcp import ClientSession

    if target.transport == "streamable-http":
        from mcp.client.streamable_http import streamablehttp_client
        ctx = streamablehttp_client(target.url, timeout=timeout)
    elif target.transport == "sse":
        from mcp.client.sse import sse_client
        ctx = sse_client(target.url, timeout=timeout)
    else:
        raise ValueError(f"unsupported transport: {target.transport}")

    async with ctx as streams:
        # streamable-http yields a 3-tuple; sse yields a 2-tuple.
        read_stream, write_stream = streams[0], streams[1]
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await session.list_tools()


async def inspect_target(target: Target, timeout: float) -> InspectResult:
    """Connect to one remote server and run tools/list. Never calls a tool.

    A single overall deadline (2x the per-step timeout, to allow connect +
    initialize + list) bounds the whole attempt, so a hung connection can never
    stall the run.
    """
    if target.transport not in ("streamable-http", "sse"):
        return InspectResult(target, False, failure_reason="unsupported transport",
                             detail=target.transport)
    overall = max(timeout * 2, timeout + 10.0)
    try:
        result = await asyncio.wait_for(
            _connect_and_list(target, timeout), timeout=overall)
    except (asyncio.TimeoutError, TimeoutError):
        return InspectResult(target, False, failure_reason="timeout")
    except Exception as exc:  # noqa: BLE001 - map everything to a reason.
        return InspectResult(target, False,
                             failure_reason=_classify_error(exc),
                             detail=f"{type(exc).__name__}: {exc}"[:300])

    tools = _extract_tool_records(target, result)
    if not tools:
        return InspectResult(target, False, failure_reason="no tools",
                             detail="server returned an empty tool list")
    return InspectResult(target, True, tools=tools)


def _extract_tool_records(target: Target, result: Any) -> list[ToolRecord]:
    records: list[ToolRecord] = []
    for tool in getattr(result, "tools", []) or []:
        raw_ann = _raw_annotations(tool)
        states = {k: annotation_state(raw_ann, k) for k in STANDARD_ANNOTATIONS}
        tool_name = getattr(tool, "name", "<unknown>")
        records.append(ToolRecord(
            server_name=target.name,
            server_version=target.version,
            tool_name=tool_name,
            annotations=states,
            side_effecting=is_side_effecting(tool_name),
            title=getattr(tool, "title", None),
            description=getattr(tool, "description", None),
            input_schema=getattr(tool, "inputSchema", None),
            raw_annotations=raw_ann,
        ))
    return records


def _raw_annotations(tool: Any) -> dict[str, Any] | None:
    """Get annotations as a raw dict, preserving explicit false vs omitted.

    Dumps the pydantic model with by_alias and exclude_unset so that fields the
    server never sent are absent (not defaulted to None).
    """
    ann = getattr(tool, "annotations", None)
    if ann is None:
        return None
    if hasattr(ann, "model_dump"):
        try:
            return ann.model_dump(by_alias=True, exclude_unset=True)
        except Exception:  # noqa: BLE001
            return ann.model_dump(by_alias=True)
    if isinstance(ann, dict):
        return ann
    return None


def _classify_error(exc: Exception) -> str:
    text = f"{type(exc).__name__} {exc}".lower()
    if any(s in text for s in ("401", "403", "unauthorized", "forbidden", "auth")):
        return "authentication required"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if any(s in text for s in ("404", "405", "not found", "method not allowed",
                               "invalid content type", "text/event-stream")):
        return "unsupported transport"
    return "connection failed"


async def inspect_all(targets: list[Target], concurrency: int,
                      timeout: float, on_done) -> list[InspectResult]:
    """Inspect targets with bounded concurrency; on_done(result) after each."""
    sem = asyncio.Semaphore(concurrency)
    results: list[InspectResult] = []

    async def worker(t: Target) -> None:
        async with sem:
            res = await inspect_target(t, timeout)
            results.append(res)
            on_done(res)

    await asyncio.gather(*(worker(t) for t in targets))
    return results


# --------------------------------------------------------------------------- #
# Aggregation / summary
# --------------------------------------------------------------------------- #
def _tool_has_any(rec: ToolRecord) -> bool:
    return any(v != OMITTED for v in rec.annotations.values())


def _tool_has_all(rec: ToolRecord) -> bool:
    return all(v != OMITTED for v in rec.annotations.values())


def _tool_has(rec: ToolRecord, key: str) -> bool:
    return rec.annotations.get(key, OMITTED) != OMITTED


def _v(rec: ToolRecord, key: str) -> str:
    """The value of a hint on a tool: TRUE / FALSE / OMITTED."""
    return rec.annotations.get(key, OMITTED)


def build_value_stats(server_results: list[InspectResult],
                      tool_filter=None) -> dict[str, Any]:
    """Per-field true / false / omitted breakdown across tools.

    This is the primary *semantic* result: it reports the actual asserted value
    of each hint, not merely whether the field was serialized. With tool_filter
    it restricts to a subset (e.g. the heuristic side-effecting tools).

    Also reports three applicability-aware destructiveness metrics and the
    readOnly x destructive contradiction count (all verifiable against the
    cross-tab):
      - classified_destructiveness: destructiveHint present AND readOnlyHint != true
      - explicitly_destructive:     destructiveHint == true AND readOnlyHint != true
      - explicit_nondestructive_write: readOnlyHint == false AND destructiveHint == false
    """
    keep = tool_filter or (lambda _t: True)
    tools = [t for r in server_results if r.ok for t in r.tools if keep(t)]
    n = len(tools)
    rows = []
    for k in STANDARD_ANNOTATIONS:
        rows.append({
            "annotation": k,
            "true": sum(1 for x in tools if _v(x, k) == TRUE),
            "false": sum(1 for x in tools if _v(x, k) == FALSE),
            "omitted": sum(1 for x in tools if _v(x, k) == OMITTED),
        })
    classified = sum(1 for x in tools
                     if _v(x, "destructiveHint") != OMITTED
                     and _v(x, "readOnlyHint") != TRUE)
    destructive = sum(1 for x in tools
                      if _v(x, "destructiveHint") == TRUE
                      and _v(x, "readOnlyHint") != TRUE)
    nondestr_write = sum(1 for x in tools
                         if _v(x, "readOnlyHint") == FALSE
                         and _v(x, "destructiveHint") == FALSE)
    contradiction = sum(1 for x in tools
                        if _v(x, "readOnlyHint") == TRUE
                        and _v(x, "destructiveHint") == TRUE)
    return {
        "n_tools": n,
        "rows": rows,
        "classified_destructiveness": classified,
        "explicitly_destructive": destructive,
        "explicit_nondestructive_write": nondestr_write,
        "contradiction": contradiction,
    }


def _tool_signature(rec: ToolRecord) -> tuple[str, ...]:
    return tuple(rec.annotations.get(k, OMITTED) for k in STANDARD_ANNOTATIONS)


def build_differentiation_stats(server_results: list[InspectResult]) -> dict[str, Any]:
    """Server-level annotation-value differentiation.

    Distinguishes servers that emit no fields, servers that stamp one identical
    annotation-value signature on every tool, and servers that vary signatures
    across tools -- the evidence for (vs against) deliberate per-tool annotation.
    """
    servers = [r for r in server_results if r.ok and r.tools]
    n = len(servers)
    empty_sig = (OMITTED,) * len(STANDARD_ANNOTATIONS)

    no_fields = one_sig = multi_sig = 0
    dom_shares: list[float] = []      # dominant-signature share, emitting servers
    distinct_counts: list[int] = []   # distinct signatures, emitting servers
    diff_eligible = diff_yes = 0      # >=2 tools AND annotated

    for r in servers:
        sigs = [_tool_signature(t) for t in r.tools]
        distinct = set(sigs)
        emits = any(s != empty_sig for s in sigs)
        if not emits:
            no_fields += 1
        elif len(distinct) == 1:
            one_sig += 1
        else:
            multi_sig += 1
        if emits:
            distinct_counts.append(len(distinct))
            counts = {s: sigs.count(s) for s in distinct}
            dom_shares.append(max(counts.values()) / len(sigs))
        if len(r.tools) >= 2 and emits:
            diff_eligible += 1
            if len(distinct) > 1:
                diff_yes += 1

    def _stats(xs: list[float]) -> dict[str, float]:
        if not xs:
            return {"mean": 0, "median": 0, "p90": 0, "max": 0}
        s = sorted(xs)
        return {
            "mean": sum(s) / len(s),
            "median": s[len(s) // 2],
            "p90": s[min(len(s) - 1, int(0.9 * (len(s) - 1)))],
            "max": s[-1],
        }

    return {
        "n_servers": n,
        "no_fields": no_fields,
        "one_signature": one_sig,
        "multi_signature": multi_sig,
        "diff_eligible": diff_eligible,
        "diff_differentiated": diff_yes,
        "distinct_per_server": _stats([float(x) for x in distinct_counts]),
        "dominant_share": _stats(dom_shares),
    }


def build_summary(server_results: list[InspectResult],
                  tool_filter=None) -> dict[str, Any]:
    """Compute the summary metrics, optionally over a subset of tools.

    Without a filter (the default), this is the whole-registry census:
      Server denominator: inspected servers that returned at least one tool.
      Tool denominator: all extracted tools.

    With `tool_filter` (a predicate over ToolRecord), only matching tools are
    counted, and a server qualifies only if it has at least one matching tool:
      Server denominator: servers with >=1 matching tool.
      Tool denominator: matching tools only.
    All server-level metrics (any / all-four / per-key) are computed over each
    qualifying server's *matching* tools. This is what powers the
    "side-effecting servers, side-effecting tools only" table.
    """
    keep = tool_filter or (lambda _t: True)

    # Per server, the tools that pass the filter.
    per_server: list[tuple[InspectResult, list[ToolRecord]]] = []
    for r in server_results:
        if not (r.ok and r.tools):
            continue
        matching = [t for t in r.tools if keep(t)]
        if matching:  # server qualifies only if it has >=1 matching tool
            per_server.append((r, matching))

    all_tools = [t for _, tools in per_server for t in tools]

    n_servers = len(per_server)
    n_tools = len(all_tools)

    # Tool-level counts (over matching tools only).
    tool_any = sum(1 for t in all_tools if _tool_has_any(t))
    tool_all = sum(1 for t in all_tools if _tool_has_all(t))
    tool_none = sum(1 for t in all_tools if not _tool_has_any(t))
    tool_per_key = {k: sum(1 for t in all_tools if _tool_has(t, k))
                    for k in STANDARD_ANNOTATIONS}

    # Server-level counts (over each server's matching tools).
    srv_any = 0        # >=1 matching tool has >=1 annotation
    srv_all_some = 0   # >=1 matching tool has all four
    srv_all_every = 0  # every matching tool has all four
    srv_none = 0       # no matching tool has any annotation
    srv_per_key = {k: 0 for k in STANDARD_ANNOTATIONS}
    for _, tools in per_server:
        if any(_tool_has_any(t) for t in tools):
            srv_any += 1
        else:
            srv_none += 1
        if any(_tool_has_all(t) for t in tools):
            srv_all_some += 1
        if all(_tool_has_all(t) for t in tools):  # non-empty by construction
            srv_all_every += 1
        for k in STANDARD_ANNOTATIONS:
            if any(_tool_has(t, k) for t in tools):
                srv_per_key[k] += 1

    def pct(n: int, d: int) -> str:
        return f"{(100 * n / d):.1f}%" if d else "n/a"

    rows: list[dict[str, str]] = []

    def add(metric: str, s: int, t: int, with_pct: bool = True) -> None:
        if with_pct:
            rows.append({
                "metric": metric,
                "servers": f"{s} ({pct(s, n_servers)})",
                "tools": f"{t} ({pct(t, n_tools)})",
            })
        else:
            rows.append({"metric": metric, "servers": str(s), "tools": str(t)})

    add("Successfully inspected", n_servers, n_tools, with_pct=False)
    add("Any field present (schema coverage)", srv_any, tool_any)
    # "All four" is a schema/framework fact, not semantic completeness.
    rows.append({
        "metric": "All four fields present (complete field emission)",
        "servers": f"{srv_all_some} ({pct(srv_all_some, n_servers)}) >=1 tool; "
                   f"{srv_all_every} ({pct(srv_all_every, n_servers)}) every tool",
        "tools": f"{tool_all} ({pct(tool_all, n_tools)})",
    })
    add("No fields present", srv_none, tool_none)
    for k in STANDARD_ANNOTATIONS:
        add(f"{k} field present", srv_per_key[k], tool_per_key[k])

    return {
        "rows": rows,
        "n_servers": n_servers,
        "n_tools": n_tools,
    }


# --------------------------------------------------------------------------- #
# Output writers
# --------------------------------------------------------------------------- #
def _failure_row(name: str, version: str, reason: str, detail: str = "") -> dict:
    return {"server_name": name, "server_version": version,
            "failure_reason": reason, "detail": detail}


def write_outputs(outdir: Path, snapshot: list[dict], server_results: list[InspectResult],
                  prefailures: list[dict], summary: dict[str, Any],
                  side_summary: dict[str, Any] | None = None,
                  value_stats: dict[str, Any] | None = None,
                  side_value_stats: dict[str, Any] | None = None,
                  diff_stats: dict[str, Any] | None = None) -> None:
    outdir.mkdir(parents=True, exist_ok=True)

    (outdir / "registry_snapshot.json").write_text(
        json.dumps(snapshot, indent=2), encoding="utf-8")

    # servers.csv -- one row per inspected server (ok or failed connection).
    # declares_auth = registry entry declared a required header/variable (a
    # credential *request*, not proof that tools/list is gated).
    with (outdir / "servers.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["server_name", "server_version", "transport", "url",
                    "declares_auth", "status", "tool_count",
                    "failure_reason", "detail"])
        for r in server_results:
            w.writerow([
                r.target.name, r.target.version, r.target.transport, r.target.url,
                "true" if r.target.requires_auth else "false",
                "ok" if r.ok else "failed",
                len(r.tools), r.failure_reason, r.detail,
            ])

    # tools.csv -- one row per discovered tool.
    with (outdir / "tools.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["server_name", "server_version", "tool_name",
                    *STANDARD_ANNOTATIONS, "side_effecting"])
        for r in server_results:
            for t in r.tools:
                w.writerow([t.server_name, t.server_version, t.tool_name,
                            *(t.annotations[k] for k in STANDARD_ANNOTATIONS),
                            "true" if t.side_effecting else "false"])

    # tools_full.jsonl -- one JSON object per tool with description/schema.
    with (outdir / "tools_full.jsonl").open("w", encoding="utf-8") as f:
        for r in server_results:
            for t in r.tools:
                f.write(json.dumps({
                    "server_name": t.server_name,
                    "server_version": t.server_version,
                    "tool_name": t.tool_name,
                    "title": t.title,
                    "description": t.description,
                    "input_schema": t.input_schema,
                    "annotations": t.annotations,
                    "raw_annotations": t.raw_annotations,
                }, ensure_ascii=False, default=str) + "\n")

    # failures.csv -- pre-known + connection failures.
    with (outdir / "failures.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["server_name", "server_version", "failure_reason", "detail"])
        for pf in prefailures:
            w.writerow([pf["server_name"], pf["server_version"],
                        pf["failure_reason"], pf["detail"]])
        for r in server_results:
            if not r.ok:
                w.writerow([r.target.name, r.target.version,
                            r.failure_reason, r.detail])

    # summary.csv -- both tables, tagged by a "scope" column.
    with (outdir / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["scope", "metric", "servers", "tools"])
        w.writeheader()
        for row in summary["rows"]:
            w.writerow({"scope": "all", **row})
        if side_summary is not None:
            for row in side_summary["rows"]:
                w.writerow({"scope": "side_effecting", **row})

    # values.csv -- per-field true/false/omitted for all tools and (if given)
    # the side-effecting subset, tagged by scope.
    if value_stats is not None:
        with (outdir / "values.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "scope", "annotation", "true", "false", "omitted"])
            w.writeheader()
            for row in value_stats["rows"]:
                w.writerow({"scope": "all", **row})
            if side_value_stats is not None:
                for row in side_value_stats["rows"]:
                    w.writerow({"scope": "side_effecting", **row})

    # summary.md -- all sections.
    md = _summary_markdown(summary, side_summary, value_stats,
                           side_value_stats, diff_stats)
    (outdir / "summary.md").write_text(md, encoding="utf-8")


def _one_table(summary: dict[str, Any], heading: str, caption: str) -> list[str]:
    lines = [heading, "",
             f"Servers (denominator): **{summary['n_servers']}**  ",
             f"Tools (denominator): **{summary['n_tools']}**  ",
             caption, "",
             "| Metric | Servers | Tools |", "| --- | --- | --- |"]
    for row in summary["rows"]:
        lines.append(f"| {row['metric']} | {row['servers']} | {row['tools']} |")
    lines.append("")
    return lines


def _value_table(vs: dict[str, Any], heading: str, note: str) -> list[str]:
    n = vs["n_tools"]

    def p(x: int) -> str:
        return f"{x} ({100 * x / n:.1f}%)" if n else str(x)

    lines = [heading, "", note, "",
             "| Annotation | true | false | omitted |",
             "| --- | --- | --- | --- |"]
    for r in vs["rows"]:
        lines.append(f"| {r['annotation']} | {p(r['true'])} | {p(r['false'])} | "
                     f"{p(r['omitted'])} |")
    lines += ["",
              "Applicability-aware destructiveness "
              "(verifiable against the readOnly x destructive cross-tab):", "",
              "| Metric | Tools |", "| --- | --- |",
              f"| Classified for destructiveness (DE present, RO!=true) "
              f"| {p(vs['classified_destructiveness'])} |",
              f"| Explicitly destructive (DE=true, RO!=true) "
              f"| {p(vs['explicitly_destructive'])} |",
              f"| Explicit non-destructive write (RO=false, DE=false) "
              f"| {p(vs['explicit_nondestructive_write'])} |",
              f"| Contradiction (RO=true & DE=true) "
              f"| {p(vs['contradiction'])} |",
              ""]
    return lines


def _diff_table(d: dict[str, Any]) -> list[str]:
    n = d["n_servers"]

    def p(x: int) -> str:
        return f"{x} ({100 * x / n:.1f}%)" if n else str(x)

    diff_pct = (f"{100 * d['diff_differentiated'] / d['diff_eligible']:.1f}%"
                if d["diff_eligible"] else "n/a")
    dps, dom = d["distinct_per_server"], d["dominant_share"]
    return [
        "## Server-level differentiation", "",
        f"Across {n} inspected servers with >=1 tool. A *signature* is a tool's "
        "(readOnly, destructive, idempotent, openWorld) value tuple.", "",
        "| Metric | Servers |", "| --- | --- |",
        f"| Emit no annotation fields | {p(d['no_fields'])} |",
        f"| One identical signature for every tool | {p(d['one_signature'])} |",
        f"| Multiple signatures across tools | {p(d['multi_signature'])} |",
        "",
        f"Of the {d['diff_eligible']} servers with >=2 tools *and* some "
        f"annotation, **{diff_pct}** differentiate values between tools "
        f"({d['diff_differentiated']} servers).",
        "",
        "Among servers emitting any field: distinct signatures per server "
        f"mean={dps['mean']:.2f}, median={dps['median']:.0f}, p90={dps['p90']:.0f}, "
        f"max={dps['max']:.0f}; each server's dominant signature covers "
        f"mean={100 * dom['mean']:.1f}%, median={100 * dom['median']:.1f}%, "
        f"p90={100 * dom['p90']:.1f}%, max={100 * dom['max']:.1f}% of its tools.",
        "",
    ]


def _summary_markdown(summary: dict[str, Any],
                      side_summary: dict[str, Any] | None = None,
                      value_stats: dict[str, Any] | None = None,
                      side_value_stats: dict[str, Any] | None = None,
                      diff_stats: dict[str, Any] | None = None) -> str:
    lines = ["# MCP Registry Tool Annotation Census", "",
             "> Field presence measures wire-level emission, not semantic "
             "annotation. See the value tables below.", ""]
    lines += _one_table(
        summary, "## Field presence / schema coverage (all servers, all tools)",
        "Presence = the field was serialized (true OR false). Denominators: "
        "inspected servers with >=1 tool; all extracted tools.")
    if value_stats is not None:
        lines += _value_table(
            value_stats, "## Field values (primary semantic result)",
            "Actual asserted value of each hint across all tools.")
    if diff_stats is not None:
        lines += _diff_table(diff_stats)
    if side_summary is not None:
        lines += _one_table(
            side_summary,
            "## Side-effecting subset -- field presence (EXPLORATORY)",
            "A server qualifies if >=1 tool looks side-effecting by a NAME "
            "HEURISTIC (see README); tool denominator = side-effecting tools "
            "only. Exploratory, not ground truth.")
    if side_value_stats is not None:
        lines += _value_table(
            side_value_stats,
            "## Side-effecting subset -- field values (EXPLORATORY)",
            "Value breakdown for the heuristic side-effecting tools only. "
            "Exploratory, not ground truth.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Resume support
# --------------------------------------------------------------------------- #
def load_completed(outdir: Path) -> set[tuple[str, str]]:
    """Return {(name, version)} of servers already recorded in servers.csv."""
    path = outdir / "servers.csv"
    done: set[tuple[str, str]] = set()
    if not path.exists():
        return done
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            done.add((row["server_name"], row["server_version"]))
    return done


def load_existing_results(outdir: Path) -> list[InspectResult]:
    """Reconstruct prior InspectResults from servers.csv + tools.csv (for resume)."""
    servers_path = outdir / "servers.csv"
    tools_path = outdir / "tools.csv"
    if not servers_path.exists():
        return []

    full: dict[tuple[str, str, str], dict[str, Any]] = {}
    full_path = outdir / "tools_full.jsonl"
    if full_path.exists():
        with full_path.open(encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                full[(d["server_name"], d["server_version"], d["tool_name"])] = d

    tools_by_server: dict[tuple[str, str], list[ToolRecord]] = {}
    if tools_path.exists():
        with tools_path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = (row["server_name"], row["server_version"])
                rec = ToolRecord(
                    server_name=row["server_name"],
                    server_version=row["server_version"],
                    tool_name=row["tool_name"],
                    annotations={k: row[k] for k in STANDARD_ANNOTATIONS},
                    side_effecting=(row.get("side_effecting", "") == "true"),
                )
                d = full.get((rec.server_name, rec.server_version, rec.tool_name), {})
                rec.title = d.get("title")
                rec.description = d.get("description")
                rec.input_schema = d.get("input_schema")
                rec.raw_annotations = d.get("raw_annotations")
                tools_by_server.setdefault(key, []).append(rec)

    results: list[InspectResult] = []
    with servers_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["server_name"], row["server_version"])
            target = Target(name=row["server_name"], version=row["server_version"],
                            transport=row["transport"], url=row["url"],
                            requires_auth=(row.get("declares_auth") == "true"))
            results.append(InspectResult(
                target=target,
                ok=(row["status"] == "ok"),
                tools=tools_by_server.get(key, []),
                failure_reason=row["failure_reason"],
                detail=row["detail"],
            ))
    return results


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--limit", type=int, default=None,
                   help="Only inspect the first N latest servers (quick test).")
    p.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                   help=f"Concurrent MCP connections (default {DEFAULT_CONCURRENCY}).")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                   help=f"Per-server timeout in seconds (default {DEFAULT_TIMEOUT}).")
    p.add_argument("--resume", action="store_true",
                   help="Skip servers already present in output/servers.csv.")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                   help="Output directory (default ./output).")
    p.add_argument("--snapshot", type=Path, default=None,
                   help="Reuse an existing registry_snapshot.json instead of downloading.")
    p.add_argument("--max-pages", type=int, default=None,
                   help="Stop downloading after N registry pages "
                        "(100 servers/page). Useful for a quick partial snapshot.")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    outdir: Path = args.output

    # 1. Registry snapshot. Reuse an existing one when --snapshot/--resume is
    # given; otherwise download and save it to disk immediately (so a long
    # download is not lost if inspection later fails, and so repeat runs with
    # --limit can reuse it via --resume/--snapshot).
    snap_path = args.snapshot or (outdir / "registry_snapshot.json")
    if (args.snapshot or args.resume) and snap_path.exists():
        print(f"Loading registry snapshot from {snap_path}", file=sys.stderr)
        snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
    else:
        print("Downloading registry snapshot...", file=sys.stderr)
        outdir.mkdir(parents=True, exist_ok=True)
        final_snap = outdir / "registry_snapshot.json"
        snapshot = fetch_registry_snapshot(
            limit_pages=args.max_pages, checkpoint_path=final_snap)
        final_snap.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        print(f"Saved snapshot ({len(snapshot)} entries) to {final_snap}",
              file=sys.stderr)

    latest = latest_per_server(snapshot)
    print(f"{len(snapshot)} entries -> {len(latest)} distinct latest servers",
          file=sys.stderr)

    targets, prefailures = select_targets(latest)
    print(f"{len(targets)} anonymous remote targets; "
          f"{len(prefailures)} pre-known failures", file=sys.stderr)

    if args.limit is not None:
        targets = targets[:args.limit]
        print(f"--limit: inspecting first {len(targets)} targets", file=sys.stderr)

    # 2. Resume: reuse prior results, skip already-done targets.
    prior_results: list[InspectResult] = []
    if args.resume:
        done = load_completed(outdir)
        prior_results = load_existing_results(outdir)
        before = len(targets)
        targets = [t for t in targets if (t.name, t.version) not in done]
        print(f"--resume: {before - len(targets)} already done, "
              f"{len(targets)} remaining", file=sys.stderr)

    # 3. Inspect, showing a live progress bar. Break failures out by auth vs
    # other, since this run probes declared-auth servers anonymously and the
    # interesting question is how many actually reject anonymous tools/list.
    total = len(targets)
    declared_auth = sum(1 for t in targets if t.requires_auth)
    stats = {"i": 0, "ok": 0, "auth": 0, "other": 0}

    def on_done(res: InspectResult) -> None:
        stats["i"] += 1
        if res.ok:
            stats["ok"] += 1
        elif res.failure_reason == "authentication required":
            stats["auth"] += 1
        else:
            stats["other"] += 1
        frac = stats["i"] / total if total else 1.0
        _progress(
            f"Inspecting {_bar(frac)} {stats['i']}/{total} "
            f"({stats['ok']} ok, {stats['auth']} auth-blocked, "
            f"{stats['other']} other-fail) last: {res.target.name[:36]}",
            done=(stats["i"] == total),
        )

    new_results: list[InspectResult] = []
    if targets:
        print(f"Inspecting {total} remote servers "
              f"({declared_auth} declare an auth requirement; probing all "
              f"anonymously). concurrency {args.concurrency}, "
              f"timeout {args.timeout}s...", file=sys.stderr)
        new_results = asyncio.run(
            inspect_all(targets, args.concurrency, args.timeout, on_done))

    server_results = prior_results + new_results

    # 4. Summarize + write.
    #  - field presence (schema coverage), all + side-effecting subset;
    #  - field values (primary semantic result), all + side-effecting subset;
    #  - server-level value differentiation.
    summary = build_summary(server_results)
    side_summary = build_summary(server_results,
                                 tool_filter=lambda t: t.side_effecting)
    value_stats = build_value_stats(server_results)
    side_value_stats = build_value_stats(server_results,
                                         tool_filter=lambda t: t.side_effecting)
    diff_stats = build_differentiation_stats(server_results)
    write_outputs(outdir, snapshot, server_results, prefailures,
                  summary, side_summary, value_stats, side_value_stats, diff_stats)

    # Print all sections.
    print("\n" + _summary_markdown(summary, side_summary, value_stats,
                                   side_value_stats, diff_stats))
    print(f"Outputs written to {outdir}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
