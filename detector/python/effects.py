"""E(t) for Python and the C<->A check.

For every tool found by annotations.py, walk the code reachable from its
handler (interprocedural, up to depth k) and collect the sinks it can reach:
read / write / delete / execute / network. Then compare with the annotations:

    readOnlyHint=true     => no write, delete or execute
    destructiveHint=false => no delete
    openWorldHint=false   => no network

Only explicit hints can be violated; an omitted hint means the SDK default
(readOnly=false, destructive=true, openWorld=true), which never contradicts.

Calls are resolved with a light, flow-insensitive analysis: imports (absolute
and relative), module functions, self-methods, and local variable types from
constructors, `with ... as x` and parameter annotations. When the receiver of
a method call cannot be typed, a few distinctive method names (unlink,
rmtree, delete_many, ...) still match, with confidence "low".

Usage: python effects.py REPO_DIR [--k 3] [--out OUT.jsonl]
"""
import argparse
import ast
import fnmatch
import json
import sys
from pathlib import Path

import yaml

from annotations import HINTS, Module, call_name, is_test, parse_file, python_files, repo_constants, uses_mcp

SINKS_FILE = Path(__file__).resolve().parents[1] / "sinks/python.yaml"
CATEGORIES = ["read", "write", "delete", "execute", "network"]
OPENERS = {"builtins.open", "io.open", "codecs.open", "pathlib.Path.open", "aiofiles.open"}
HTTP_VERBS = {"get": "read", "head": "read", "options": "read",
              "post": "write", "put": "write", "patch": "write", "delete": "delete"}
SQL = {"select": "read", "with": "read", "insert": "write", "update": "write", "create": "write",
       "alter": "write", "replace": "write", "upsert": "write", "merge": "write",
       "delete": "delete", "drop": "delete", "truncate": "delete"}
# method names distinctive enough to match on an untyped receiver
UNTYPED_METHODS = {
    "unlink": "delete", "rmtree": "delete", "rmdir": "delete", "delete_one": "delete",
    "delete_many": "delete", "drop_collection": "delete", "delete_object": "delete",
    "write_text": "write", "write_bytes": "write", "mkdir": "write", "makedirs": "write",
    "insert_one": "write", "insert_many": "write", "update_one": "write", "update_many": "write",
    "replace_one": "write", "put_object": "write",
}
HTTP_RECEIVERS = ("client", "session", "http", "api")
# what a call returns, for typing variables (x = sqlite3.connect(...) -> Connection)
RETURNS = {
    "sqlite3.connect": "sqlite3.Connection", "sqlite3.Connection.cursor": "sqlite3.Cursor",
    "requests.session": "requests.Session", "git.Repo.init": "git.Repo", "git.Repo.clone_from": "git.Repo",
    "pathlib.Path.resolve": "pathlib.Path", "pathlib.Path.expanduser": "pathlib.Path",
    "pathlib.Path.absolute": "pathlib.Path", "pathlib.Path.joinpath": "pathlib.Path",
    "pathlib.Path.with_suffix": "pathlib.Path", "pathlib.Path.with_name": "pathlib.Path",
}
BUILTINS = {"open", "eval", "exec", "compile", "__import__"}

# Effect kinds for the labeling rules (labeling/guide.md). They are heuristics on
# the call's text and the expressions its variables were assigned from; every
# effect keeps its kind so results can be reported strict (all) and lenient
# (LENIENT_DROP kinds removed).
BOOKKEEPING_WORDS = ("merge_head", "orig_head", "cherry_pick_head", "autostash", "git_dir", ".git/",
                     ".lock", "lockfile", ".pid")
WRITE_BOOKKEEPING_WORDS = ("manifest", "cache", "_state", "state.json", "registry.json", "checkpoint")
TEMP_WORDS = ("tmp", "temp", "partial", ".part", "scratch")
CLEANUP_FUNCS = ("cleanup", "clean_up", "remove_partial", "rollback", "discard")
LOG_WORDS = (".log", "/log", "logs/", "debug")
READ_ENDPOINT_WORDS = ("search", "query", "token", "oauth", "login", "auth", "lookup")
LENIENT_DROP = {"bookkeeping", "cleanup", "temp", "execute_fixed", "post_read_like", "log"}


def load_sinks(path=SINKS_FILE):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    generic = [(p, c) for c in CATEGORIES for p in data.get(c) or []]
    libs = [(p, c) for c, pats in (data.get("libraries") or {}).items() for p in pats]
    return libs, generic


def module_name(rel):
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


class Repo:
    """All modules of a repo, their functions, classes and imports."""

    def __init__(self, root):
        self.root = Path(root)
        files = python_files(self.root)
        self.consts = repo_constants(files)
        self.modules = {}    # module name -> info dict
        self.functions = {}  # qualified name -> (FunctionDef, module name, class name)
        self.by_suffix = {}  # dotted suffix -> module name (for absolute imports in src/ layouts)
        for path in files:
            rel = path.relative_to(self.root)
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
            except (SyntaxError, ValueError):
                continue
            name = module_name(rel)
            self.modules[name] = {"tree": tree, "rel": rel.as_posix(), "path": path,
                                  "mod": Module(tree, self.consts), "imports": {}}
            parts = name.split(".")
            for i in range(len(parts)):
                suffix = ".".join(parts[i:])
                self.by_suffix[suffix] = name if suffix not in self.by_suffix else None
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.functions[f"{name}.{node.name}"] = (node, name, None)
                elif isinstance(node, ast.ClassDef):
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            self.functions[f"{name}.{node.name}.{item.name}"] = (item, name, node.name)
            # nested functions (handlers defined inside a serve() function, for example)
            for outer in ast.walk(tree):
                if isinstance(outer, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for inner in ast.walk(outer):
                        if inner is not outer and isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            self.functions.setdefault(f"{name}.{inner.name}", (inner, name, None))
        for name, info in self.modules.items():
            info["imports"] = self.imports_of(name, info["tree"])

    def local_module(self, dotted):
        """Map an imported module path to a repo module, if it is one."""
        if dotted in self.modules:
            return dotted
        return self.by_suffix.get(dotted)

    def imports_of(self, name, tree):
        table = {}
        package = name.split(".")[:-1] if not self.modules[name]["rel"].endswith("__init__.py") else name.split(".")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    target = self.local_module(a.name) or a.name
                    table[a.asname or a.name.split(".")[0]] = target if a.asname else a.name.split(".")[0]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package[: len(package) - node.level + 1] if node.level > 1 else package
                    src = ".".join(base + ([node.module] if node.module else []))
                else:
                    src = node.module or ""
                src = self.local_module(src) or src
                for a in node.names:
                    full = f"{src}.{a.name}" if src else a.name
                    # `from pkg import module` imports a module, not a name
                    table[a.asname or a.name] = self.local_module(full) or full
        return table


class Context:
    """Where a statement is being analysed: module, class, typed local variables."""

    def __init__(self, repo, module, cls=None, func=None):
        self.repo, self.module, self.cls = repo, module, cls
        self.info = repo.modules[module]
        self.types = {}
        self.assigned = {}  # local name -> the expression it was last assigned from
        if func is not None:
            self.type_function(func)

    def type_function(self, func):
        args = func.args.args + func.args.kwonlyargs + func.args.posonlyargs
        for a in args:
            if a.annotation is not None:
                t = self.resolve(a.annotation)
                if t:
                    self.types[a.arg] = t
        for node in ast.walk(func):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                names = [target] if isinstance(target, ast.Name) else \
                    [e for e in getattr(target, "elts", []) if isinstance(e, ast.Name)]  # fd, path = mkstemp()
                for n in names:
                    self.assigned[n.id] = node.value
            elif isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(node.target, ast.Name):
                self.assigned[node.target.id] = node.iter  # for name in ("MERGE_HEAD", ...)
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                t = self.value_type(node.value)
                if t:
                    self.types[node.targets[0].id] = t
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for item in node.items:
                    if isinstance(item.optional_vars, ast.Name):
                        t = self.value_type(item.context_expr)
                        if t:
                            self.types[item.optional_vars.id] = t

    def value_type(self, node):
        if isinstance(node, ast.Await):
            node = node.value
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):  # Path(x) / "y"
            left = self.value_type(node.left) or (self.resolve(node.left) if isinstance(node.left, ast.Name) else None)
            return left if left == "pathlib.Path" else None
        if isinstance(node, ast.Call):
            q = self.resolve(node.func)
            if q is None:
                return None
            if q in RETURNS:
                return RETURNS[q]
            last = q.split(".")[-1]
            if last[:1].isupper():  # a constructor: Foo(...) -> Foo
                return q
        return None

    def resolve(self, node):
        """Qualified name of an expression, e.g. 'shutil.rmtree' or 'pathlib.Path.unlink'."""
        if isinstance(node, ast.Name):
            n = node.id
            if n in self.types:
                return self.types[n]
            if n == "self" and self.cls:
                return f"{self.module}.{self.cls}"
            if f"{self.module}.{n}" in self.repo.functions:
                return f"{self.module}.{n}"
            if n in self.info["imports"]:
                return self.info["imports"][n]
            if n in BUILTINS:
                return f"builtins.{n}"
            return None
        if isinstance(node, ast.Attribute):
            base = self.resolve(node.value)
            return f"{base}.{node.attr}" if base else None
        if isinstance(node, ast.Call):  # chained: Path(x).unlink(), requests.Session().get()
            return self.value_type(node)
        if isinstance(node, ast.Subscript):  # Optional[Path], list[Path] -> annotation's inner type
            return self.resolve(node.slice) if isinstance(node.slice, (ast.Name, ast.Attribute)) else None
        return None


def literal_str(mod, node):
    v = mod.literal(node) if node is not None else None
    return v if isinstance(v, str) else None


def classify_call(call, ctx, libs, generic):
    """[(category, sink, confidence)] for one call expression."""
    q = ctx.resolve(call.func)
    mod = ctx.info["mod"]
    method = call.func.attr if isinstance(call.func, ast.Attribute) else None
    out = []
    if q:
        # file opens: the mode decides read vs write
        if q in OPENERS or q.endswith(".open") and q.startswith("pathlib.Path"):
            pos = 0 if q.startswith("pathlib.Path") else 1
            mode_node = call.args[pos] if len(call.args) > pos else next(
                (k.value for k in call.keywords if k.arg == "mode"), None)
            mode = literal_str(mod, mode_node) if mode_node is not None else "r"
            if mode is None:
                return [("write", q, "low")]
            return [("write" if set(mode) & set("wax+") else "read", q, "high")]
        # SQL: the statement decides
        if method in ("execute", "executemany", "executescript") and call.args:
            sql = literal_str(mod, call.args[0])
            if sql and sql.split():
                cat = SQL.get(sql.split()[0].lower())
                if cat:
                    return [(cat, q, "high")]
        # R6: a branch switch is protected by git; --force or `-- <paths>` drops local edits
        if q == "git.Repo.git.checkout":
            flags = {mod.literal(a) for a in call.args} | {k.arg for k in call.keywords}
            if flags & {"-f", "--force", "--", "force"}:
                return [("delete", q, "high")]
        for pattern, cat in libs:
            if fnmatch.fnmatchcase(q, pattern):
                return [(cat, q, "high")]
        constructor = q.split(".")[-1][:1].isupper()
        for pattern, cat in generic:
            # `httpx.*` means its calls, not building a client object
            if constructor and pattern.endswith("*") and q != pattern.rstrip(".*"):
                continue
            if fnmatch.fnmatchcase(q, pattern):
                out.append((cat, q, "high"))
        if out and any(c == "network" for c, _, _ in out):
            verb = method.lower() if method else None
            if verb == "request" and call.args:
                verb = (literal_str(mod, call.args[0]) or "").lower()
            if verb in HTTP_VERBS and HTTP_VERBS[verb] != "read":
                out.append((HTTP_VERBS[verb], q, "high"))
        if out:
            return out
    # untyped receivers: fall back to distinctive method names
    if method in UNTYPED_METHODS and not (q and q.split(".")[0] in ("os", "shutil")):
        return [(UNTYPED_METHODS[method], f"?.{method}", "low")]
    # untyped `client.post(url)`: the receiver must be a plain variable named like a
    # client, and .get also needs a URL-looking first argument (dict.get is common)
    if method and method.lower() in HTTP_VERBS and isinstance(call.func.value, (ast.Name, ast.Attribute)):
        receiver = call_name(call.func.value).lower()
        first = call.args[0] if call.args else None
        url_like = isinstance(first, ast.JoinedStr) or \
            (isinstance(first, ast.Constant) and str(first.value).startswith(("http", "/"))) or \
            (isinstance(first, ast.Name) and any(w in first.id.lower() for w in ("url", "endpoint", "path")))
        if any(r in receiver for r in HTTP_RECEIVERS) and (method.lower() != "get" or url_like):
            out = [("network", f"{receiver}.{method}", "low")]
            if HTTP_VERBS[method.lower()] != "read":
                out.append((HTTP_VERBS[method.lower()], f"{receiver}.{method}", "low"))
            return out
    return []


def call_text(call, ctx, depth=2):
    """The call's source plus, for each variable it uses, what that variable was
    assigned from (two levels), lower-cased: `p.unlink()` + `p = Path(tmpdir) / x`."""
    parts, seen, frontier = [ast.unparse(call)], set(), [call]
    for _ in range(depth):
        nxt = []
        for node in frontier:
            for n in ast.walk(node):
                if isinstance(n, ast.Name) and n.id in ctx.assigned and n.id not in seen:
                    seen.add(n.id)
                    parts.append(ast.unparse(ctx.assigned[n.id]))
                    nxt.append(ctx.assigned[n.id])
        frontier = nxt
    return " ".join(parts).lower()


def fixed_program(call, ctx):
    """True when the program a subprocess call runs is a literal (its arguments may vary)."""
    if not call.args:
        return False
    arg = call.args[0]
    for _ in range(2):  # follow `cmd = [...]` once, and split(f"prog ...")
        if isinstance(arg, ast.Name) and arg.id in ctx.assigned:
            arg = ctx.assigned[arg.id]
        if isinstance(arg, ast.Call) and call_name(arg).split(".")[-1] == "split" and arg.args:
            arg = arg.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return bool(arg.value.strip())
    if isinstance(arg, (ast.List, ast.Tuple)) and arg.elts:
        return isinstance(arg.elts[0], ast.Constant)
    if isinstance(arg, ast.JoinedStr) and arg.values:
        first = arg.values[0]
        return isinstance(first, ast.Constant) and bool(str(first.value).split())
    return False


def effect_kind(cat, sink, call, ctx, fname, in_handler):
    """Which labeling rule (if any) this effect falls under; 'plain' otherwise."""
    text = call_text(call, ctx)
    if cat == "delete":
        if any(w in text for w in BOOKKEEPING_WORDS):
            return "bookkeeping"                                       # R1
        if in_handler or any(w in (fname or "").lower() for w in CLEANUP_FUNCS) \
                or any(w in text for w in TEMP_WORDS) or "tempfile." in text:
            return "cleanup"                                           # R2
    if cat == "execute" and not sink.startswith("builtins."):
        return "execute_fixed" if fixed_program(call, ctx) else "execute_dynamic"  # R3
    if cat == "write":
        if any(w in text for w in BOOKKEEPING_WORDS + WRITE_BOOKKEEPING_WORDS):
            return "bookkeeping"                                       # R1: the tool's own state files
        verb = call.func.attr.lower() if isinstance(call.func, ast.Attribute) else ""
        if verb in ("post", "request") and (any(w in text for w in READ_ENDPOINT_WORDS)
                                            or ("graphql" in text and "mutation" not in text)):
            return "post_read_like"                                    # R4
        if any(w in text for w in LOG_WORDS):
            return "log"                                               # R5
        if "tempfile." in text or any(w in text for w in TEMP_WORDS):
            return "temp"                                              # P3
    return "plain"


# write mode, for destructiveHint=false ("performs only additive updates"):
# additive = creates/appends; modifying = changes existing state; overwrite = may
# replace an existing file or object; unknown otherwise
WRITE_MODES = {
    "mkdir": "additive", "makedirs": "additive", "touch": "additive", "insert_one": "additive",
    "insert_many": "additive", "add": "additive", "create_head": "additive", "commit": "additive",
    "tag": "additive", "stash": "additive", "clone_from": "additive", "post": "additive",
    "write_text": "overwrite", "write_bytes": "overwrite", "put_object": "overwrite", "copy": "overwrite",
    "copy2": "overwrite", "copyfile": "overwrite", "copytree": "overwrite", "dump": "unknown",
    "update_one": "modifying", "update_many": "modifying", "replace_one": "modifying", "set": "modifying",
    "rename": "modifying", "replace": "modifying", "move": "modifying", "chmod": "modifying",
    "put": "modifying", "patch": "modifying",
    # git refuses to drop local changes on a branch switch, merge or pull (guide R6);
    # checkout --force / -- <paths> is classified as delete in classify_call
    "checkout": "additive", "merge": "additive", "pull": "additive",
}
SQL_MODES = {"insert": "additive", "create": "additive", "update": "modifying", "alter": "modifying",
             "replace": "modifying", "upsert": "modifying", "merge": "modifying"}


def write_mode(sink, call, ctx):
    method = sink.split(".")[-1].lower()
    mod = ctx.info["mod"]
    if sink in OPENERS or sink.endswith(".open"):
        pos = 0 if sink.startswith("pathlib.Path") else 1
        node = call.args[pos] if len(call.args) > pos else next((k.value for k in call.keywords if k.arg == "mode"), None)
        mode = literal_str(mod, node) if node is not None else None
        if mode is None:
            return "unknown"
        return "overwrite" if set(mode) & set("w+") else "additive"  # a, x: append / create new
    if method in ("execute", "executemany", "executescript") and call.args:
        sql = literal_str(mod, call.args[0]) or ""
        return SQL_MODES.get(sql.split()[0].lower(), "unknown") if sql.split() else "unknown"
    return WRITE_MODES.get(method, "unknown")


def network_world(call, ctx):
    """open = the target comes from data (likely tool input); unknown = a fixed host.
    A fixed host is not proof of a closed world: one service can expose an open world
    (review v1.1), so it goes to review rather than counting as consistent."""
    mod = ctx.info["mod"]
    url = call.args[0] if call.args else next((k.value for k in call.keywords if k.arg in ("url", "uri")), None)
    if isinstance(call.func, ast.Attribute) and call.func.attr == "request" and len(call.args) > 1:
        url = call.args[1]  # request(method, url)
    if url is None:
        return "unknown"
    if literal_str(mod, url) is not None:
        return "unknown"
    if isinstance(url, ast.JoinedStr) and url.values:
        first = url.values[0]
        head = first.value if isinstance(first, ast.Constant) else \
            literal_str(mod, first.value) if isinstance(first, ast.FormattedValue) else None
        if isinstance(head, str) and "://" in head and head.split("://", 1)[1]:
            return "unknown"  # f"https://api.x.com/{id}": fixed host
    return "open"


def handler_calls(stmts):
    """ids of nodes inside except / finally blocks (cleanup paths)."""
    ids = set()
    for stmt in stmts:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Try):
                for block in [h.body for h in node.handlers] + [node.finalbody]:
                    for s in block:
                        ids.update(id(n) for n in ast.walk(s))
    return ids


class Analyzer:
    def __init__(self, repo, k=3):
        self.repo, self.k = repo, k
        self.libs, self.generic = load_sinks()
        self.cache = {}

    def function_effects(self, qname, depth):
        """Effects reachable from a repo function, with call paths."""
        key = (qname, depth)
        if key in self.cache:
            return self.cache[key]
        self.cache[key] = []  # breaks recursion cycles
        node, module, cls = self.repo.functions[qname]
        ctx = Context(self.repo, module, cls, node)
        self.cache[key] = self.statements_effects(node.body, ctx, depth, node.name)
        return self.cache[key]

    def statements_effects(self, stmts, ctx, depth, fname=None):
        effects = []
        rel = ctx.info["rel"]
        in_handler = handler_calls(stmts)
        for stmt in stmts:
            for node in ast.walk(stmt):
                if not isinstance(node, ast.Call):
                    continue
                for cat, sink, conf in classify_call(node, ctx, self.libs, self.generic):
                    kind = effect_kind(cat, sink, node, ctx, fname, id(node) in in_handler)
                    effect = {"category": cat, "sink": sink, "confidence": conf, "kind": kind,
                              "file": rel, "line": node.lineno, "path": []}
                    if cat == "write":
                        effect["mode"] = write_mode(sink, node, ctx)
                    elif cat == "network":
                        effect["world"] = network_world(node, ctx)
                    effects.append(effect)
                q = ctx.resolve(node.func)
                if q in self.repo.functions and depth < self.k:
                    for e in self.function_effects(q, depth + 1):
                        effects.append({**e, "path": [f"{q}:{node.lineno}"] + e["path"]})
        return effects

    def dispatch_branches(self, func, ctx):
        """For a low-level call_tool(name, args) dispatcher: tool name -> statements.
        Statements outside the per-tool branches run for every tool (prelude)."""
        if not func.args.args:
            return [], {}
        var = func.args.args[0].arg
        mod = ctx.info["mod"]
        branches, prelude = {}, []

        def names_of(test):
            if isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and test.left.id == var:
                if isinstance(test.ops[0], ast.Eq):
                    return [mod.literal(test.comparators[0])]
                if isinstance(test.ops[0], ast.In):
                    v = mod.literal(test.comparators[0])
                    return list(v) if isinstance(v, (list, tuple, set)) else []
            if isinstance(test, ast.BoolOp):
                return [n for v in test.values for n in names_of(v)]
            return []

        def visit(stmts):
            for stmt in stmts:
                if isinstance(stmt, ast.If) and names_of(stmt.test):
                    for n in names_of(stmt.test):
                        branches.setdefault(n, []).extend(stmt.body)
                    visit(stmt.orelse)
                elif isinstance(stmt, ast.Match) and isinstance(stmt.subject, ast.Name) and stmt.subject.id == var:
                    for case in stmt.cases:
                        pats = case.pattern.patterns if isinstance(case.pattern, ast.MatchOr) else [case.pattern]
                        for p in pats:
                            if isinstance(p, ast.MatchValue):
                                branches.setdefault(mod.literal(p.value), []).extend(case.body)
                elif isinstance(stmt, (ast.Try, ast.With, ast.AsyncWith)):
                    visit(stmt.body)
                    for h in getattr(stmt, "handlers", []):
                        visit(h.body)
                else:
                    prelude.append(stmt)
        visit(func.body)
        return prelude, {k: v for k, v in branches.items() if isinstance(k, str)}

    def analyze(self):
        results = []
        dispatchers = []
        for qname, (node, module, cls) in self.repo.functions.items():
            if any(call_name(d).endswith(".call_tool") for d in node.decorator_list):
                ctx = Context(self.repo, module, cls, node)
                dispatchers.append((ctx, *self.dispatch_branches(node, ctx)))

        for name, info in self.repo.modules.items():
            for tool in parse_file(info["path"], info["rel"], self.repo.consts):
                effects, entry = [], None
                if tool["handler"]:
                    q = f"{name}.{tool['handler']}"
                    if q not in self.repo.functions:  # handler imported from elsewhere
                        q = info["imports"].get(tool["handler"], q)
                    if q in self.repo.functions:
                        entry = q
                        effects = self.function_effects(q, 0)
                else:  # low-level: find its branch in a call_tool dispatcher
                    for ctx, prelude, branches in dispatchers:
                        if tool["tool"] in branches:
                            entry = f"call_tool[{tool['tool']}]"
                            effects = self.statements_effects(prelude + branches[tool["tool"]], ctx, 0)
                            break
                    else:
                        # single-tool servers guard with `if name != "x": raise` and
                        # have no branches: the whole dispatcher is that tool
                        for ctx, prelude, branches in dispatchers:
                            if not branches and ctx.module == name:
                                entry = "call_tool[*]"
                                effects = self.statements_effects(prelude, ctx, 0)
                                break
                tool["entry"] = entry
                tool["effects"] = effects
                tool["inconsistencies"], tool["review"] = inconsistencies(tool["annotations"], effects)
                tool["inconsistencies_lenient"] = [v for v in tool["inconsistencies"]
                                                   if v["witness"]["kind"] not in LENIENT_DROP]
                results.append(tool)
        return results


def inconsistencies(ann, effects):
    """C<->A inconsistencies, and cases that need review, from explicit hints only.
    Rules follow the MCP 2025-06-18 definitions (docs/Review_D_extraction_for_Menna.docx, s.5):
      readOnlyHint=true      "does not modify its environment": no write, delete, execute
      destructiveHint=false  "only additive updates", meaningful only when readOnlyHint is
                             not true: no delete, no modifying or overwriting write
      openWorldHint=false    "domain of interaction is closed": no request to an open
                             target; a fixed host is unknown -> review
    Returns (inconsistencies, review)."""
    cats = {}
    for e in effects:
        cats.setdefault(e["category"], []).append(e)
    found, review = [], []
    if ann["readOnlyHint"] == "true":
        for c in ("delete", "execute", "write"):
            for e in cats.get(c, []):
                found.append({"rule": "readOnly_but_" + c, "witness": e})
    if ann["destructiveHint"] == "false" and ann["readOnlyHint"] != "true":
        for e in cats.get("delete", []):
            found.append({"rule": "nondestructive_but_delete", "witness": e})
        for e in cats.get("write", []):
            if e.get("mode") in ("modifying", "overwrite"):
                found.append({"rule": "nondestructive_but_" + e["mode"], "witness": e})
    if ann["openWorldHint"] == "false":
        for e in cats.get("network", []):
            if e.get("world") == "open":
                found.append({"rule": "closedworld_but_open_network", "witness": e})
            else:
                review.append({"rule": "closedworld_network_unknown_world", "witness": e})
    return found, review


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--out")
    ap.add_argument("--all", action="store_true", help="also analyze repos that never import an MCP library")
    args = ap.parse_args()
    repo = Repo(args.repo)
    mcp = args.all or uses_mcp([repo.root / info["rel"] for info in repo.modules.values()])
    results = Analyzer(repo, args.k).analyze() if mcp else []
    sys.stdout.reconfigure(encoding="utf-8")
    out = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    for r in results:
        out.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
