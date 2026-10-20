"""A(t) for Python: find MCP tool definitions and their annotations statically.

Tool definition styles handled:
  * fastmcp   @mcp.tool(name=..., description=..., annotations=...) on a function
  * add_tool  server.add_tool(fn, name=..., annotations=...) or
              server.add_tool("name", description, schema, handler, annotations=...)
  * lowlevel  Tool(name=..., annotations=...) from mcp.types, returned by
              @server.list_tools(); the handler is the shared @server.call_tool()
              dispatcher, mapped later by the call graph
  * raw       a dict literal {"name": ..., "inputSchema": ..., "annotations": ...}
              (hand-written JSON-RPC servers)

Annotations may be ToolAnnotations(...) or a dict, inline or bound to a name:
module level, inside the enclosing function, or imported from another module
of the same repo. Each hint is "true" / "false" / "omitted" (not written, the
SDK default applies) / "unresolved" (written, but not statically evaluable).

Usage: python annotations.py REPO_DIR [OUT.jsonl]
"""
import ast
import json
import sys
from collections import defaultdict
from pathlib import Path

HINTS = ["readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"]
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "site-packages", "__pycache__", "dist", "build"}
MCP_MODULES = ("mcp", "fastmcp")
AMBIGUOUS = object()  # name bound to different values -> cannot resolve


def call_name(node):
    """'mcp.tool' for mcp.tool(...), 'Tool' for Tool(...)."""
    f = node.func if isinstance(node, ast.Call) else node
    parts = []
    while isinstance(f, ast.Attribute):
        parts.append(f.attr)
        f = f.value
    if isinstance(f, ast.Name):
        parts.append(f.id)
    return ".".join(reversed(parts))


def bind(table, key, value):
    """Record key = value; a second, different value makes the key AMBIGUOUS."""
    old = table.get(key)
    if old is None:
        table[key] = value
    elif old is AMBIGUOUS:
        return
    elif value is AMBIGUOUS or ast.dump(old) != ast.dump(value):
        table[key] = AMBIGUOUS


def collect_bindings(tree):
    """Module-level and function-level simple assignments of a file."""
    module, local = {}, {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            bind(module, node.targets[0].id, node.value)
        elif isinstance(node, ast.ClassDef):  # Enum-style: class Tools(str, Enum): X = "x"
            for item in node.body:
                if isinstance(item, ast.Assign) and isinstance(item.targets[0], ast.Name):
                    bind(module, f"{node.name}.{item.targets[0].id}", item.value)
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    bind(local, node.targets[0].id, node.value)
    return module, local


class Module:
    def __init__(self, tree, repo_consts):
        self.consts, self.local = collect_bindings(tree)
        self.repo = repo_consts  # module-level constants of the whole repo, by name
        self.imported = set()    # names imported from other modules
        self.mcp_names = set()   # names / aliases that come from the MCP SDK
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for a in node.names:
                    self.imported.add(a.asname or a.name)
                    if node.module.split(".")[0] in MCP_MODULES:
                        self.mcp_names.add(a.asname or a.name)
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split(".")[0] in MCP_MODULES:
                        self.mcp_names.add(a.asname or a.name.split(".")[0])

    def lookup(self, key):
        for table in (self.consts, self.local):
            if key in table:
                return table[key]
        if key.split(".")[0] in self.imported and key in self.repo:
            return self.repo[key]
        return None

    def resolve(self, node, depth=0):
        if depth > 5:
            return node
        if isinstance(node, (ast.Name, ast.Attribute)):
            key = call_name(node)
            if key.endswith((".value", ".name")):
                key = key.rsplit(".", 1)[0]
            target = self.lookup(key)
            if target is not None and target is not AMBIGUOUS:
                return self.resolve(target, depth + 1)
        return node

    def literal(self, node):
        try:
            return ast.literal_eval(self.resolve(node))
        except (ValueError, SyntaxError, TypeError):
            return None

    def state(self, node):
        v = self.literal(node)
        return "true" if v is True else "false" if v is False else "unresolved"

    def annotations(self, node):
        """({hint: state}, kind) from ToolAnnotations(...) / dict / None."""
        states = {h: "omitted" for h in HINTS}
        if node is None:
            return states, "none"
        node = self.resolve(node)
        if isinstance(node, ast.Constant) and node.value is None:
            return states, "none"
        if isinstance(node, ast.Call) and call_name(node).endswith("ToolAnnotations"):
            pairs = [(kw.arg, kw.value) for kw in node.keywords if kw.arg]
            kind = "ToolAnnotations"
        elif isinstance(node, ast.Dict):
            pairs = [(self.literal(k), v) for k, v in zip(node.keys, node.values) if k is not None]
            kind = "dict"
        else:
            return {h: "unresolved" for h in HINTS}, "unresolved"
        for key, value in pairs:
            if key in states:
                states[key] = self.state(value)
        return states, kind

    def is_mcp_tool_class(self, call):
        """Tool(...) only counts when Tool comes from the MCP SDK."""
        name = call_name(call)
        parts = name.split(".")
        if parts[-1] != "Tool":
            return False
        return (name in self.mcp_names) or (len(parts) > 1 and parts[0] in self.mcp_names)


def kwargs(call):
    return {kw.arg: kw.value for kw in call.keywords if kw.arg}


def record(rel, node, style, mod, name, desc, ann_node, handler=None, handler_line=None, extra_hints=None):
    states, kind = mod.annotations(ann_node)
    for h, v in (extra_hints or {}).items():  # hints passed as their own kwargs
        if states[h] == "omitted":
            states[h] = mod.state(v)
    return {
        "file": rel, "line": node.lineno, "style": style, "tool": name, "description": desc,
        "annotations": states, "annotations_kind": kind,
        "handler": handler, "handler_line": handler_line,
    }


def parse_file(path, rel, repo_consts=None):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, ValueError):
        return []
    mod = Module(tree, repo_consts or {})
    functions = {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    tools = []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                if not call_name(dec).endswith(".tool"):
                    continue
                kw = kwargs(dec) if isinstance(dec, ast.Call) else {}
                desc = mod.literal(kw["description"]) if "description" in kw else ast.get_docstring(node)
                name = mod.literal(kw["name"]) if "name" in kw else node.name
                tools.append(record(rel, node, "fastmcp", mod, name, desc, kw.get("annotations"),
                                    node.name, node.lineno, {h: kw[h] for h in HINTS if h in kw}))

        elif isinstance(node, ast.Call) and call_name(node).endswith(".add_tool"):
            kw, args = kwargs(node), node.args
            first = mod.literal(args[0]) if args else None
            if isinstance(first, str):  # add_tool("name", description, schema, handler, ...)
                name = first
                desc = mod.literal(args[1]) if len(args) > 1 else mod.literal(kw.get("description"))
                fn = args[3] if len(args) > 3 else kw.get("handler") or kw.get("fn")
            else:                       # add_tool(fn, name=..., description=...)
                fn = args[0] if args else kw.get("fn")
                name = mod.literal(kw["name"]) if "name" in kw else call_name(fn) if fn is not None else None
                desc = mod.literal(kw.get("description")) if "description" in kw else None
            handler = call_name(fn) if fn is not None else None
            if desc is None and handler in functions:
                desc = ast.get_docstring(functions[handler])
            line = functions[handler].lineno if handler in functions else None
            tools.append(record(rel, node, "add_tool", mod, name, desc, kw.get("annotations"), handler, line))

        elif isinstance(node, ast.Call) and mod.is_mcp_tool_class(node):
            kw = kwargs(node)
            if "name" in kw:
                desc = mod.literal(kw["description"]) if "description" in kw else None
                tools.append(record(rel, node, "lowlevel", mod, mod.literal(kw["name"]), desc,
                                    kw.get("annotations")))

        elif isinstance(node, ast.Dict):
            keys = {mod.literal(k): v for k, v in zip(node.keys, node.values) if k is not None}
            if "name" in keys and "inputSchema" in keys:
                desc = mod.literal(keys["description"]) if "description" in keys else None
                tools.append(record(rel, node, "raw", mod, mod.literal(keys["name"]), desc,
                                    keys.get("annotations")))
    return tools


def repo_constants(files):
    """Module-level constants across the repo, keyed by name (ambiguous dropped)."""
    table = {}
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError):
            continue
        module, _ = collect_bindings(tree)
        for k, v in module.items():
            bind(table, k, v)
    return {k: v for k, v in table.items() if v is not AMBIGUOUS}


def is_test(rel):
    """Test code builds fake tool lists; it is not part of the server."""
    return bool({"test", "tests", "testing"} & set(rel.parts[:-1])) or \
        rel.name.startswith("test_") or rel.name.endswith("_test.py") or rel.name == "conftest.py"


def python_files(root):
    files = []
    for p in root.rglob("*.py"):
        rel = p.relative_to(root)
        if not (SKIP_DIRS & set(rel.parts)) and not is_test(rel):
            files.append(p)
    return files


def uses_mcp(files):
    """True if any file imports an MCP library (mcp, fastmcp). Checked per repo:
    tools are often defined in a file that never imports the SDK itself."""
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else []
            if any(n.split(".")[0] in MCP_MODULES for n in names):
                return True
    return False


def parse_repo(root, mcp_only=False):
    """mcp_only: return nothing for repos that never import an MCP library."""
    root = Path(root)
    files = python_files(root)
    if mcp_only and not uses_mcp(files):
        return []
    consts = repo_constants(files)
    tools = []
    for path in files:
        tools.extend(parse_file(path, path.relative_to(root).as_posix(), consts))
    return tools


def main():
    # python annotations.py REPO [OUT.jsonl] [--all]   (--all keeps non-MCP repos)
    args = [a for a in sys.argv[1:] if a != "--all"]
    tools = parse_repo(args[0], mcp_only="--all" not in sys.argv)
    sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    out = open(args[1], "w", encoding="utf-8") if len(args) > 1 else sys.stdout
    for t in tools:
        out.write(json.dumps(t, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
