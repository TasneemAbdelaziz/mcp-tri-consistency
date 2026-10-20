"""Tests for E(t) and the C<->A rules: python -m pytest detector/python"""
import textwrap

from effects import Analyzer, Repo


def analyze(tmp_path, code, k=3):
    (tmp_path / "server.py").write_text(textwrap.dedent(code), encoding="utf-8")
    return {t["tool"]: t for t in Analyzer(Repo(tmp_path), k).analyze()}


def cats(t):
    return {e["category"] for e in t["effects"]}


def rules(t):
    return {v["rule"] for v in t["inconsistencies"]}


def test_open_mode_decides_read_or_write(tmp_path):
    tools = analyze(tmp_path, '''
        @mcp.tool(annotations={"readOnlyHint": True})
        def show(p):
            return open(p).read()
        @mcp.tool(annotations={"readOnlyHint": True})
        def save(p):
            with open(p, "a") as f:
                f.write("x")
    ''')
    assert cats(tools["show"]) == {"read"} and not tools["show"]["inconsistencies"]
    assert rules(tools["save"]) == {"readOnly_but_write"}


def test_interprocedural_depth(tmp_path):
    code = '''
        import shutil
        def a(p): b(p)
        def b(p): shutil.rmtree(p)
        @mcp.tool(annotations={"destructiveHint": False})
        def clean(p): a(p)
    '''
    assert rules(analyze(tmp_path, code)["clean"]) == {"nondestructive_but_delete"}
    assert analyze(tmp_path, code, k=1)["clean"]["effects"] == []  # rmtree is 2 calls deep


def test_typed_path_and_import_alias(tmp_path):
    tools = analyze(tmp_path, '''
        from pathlib import Path
        import subprocess as sp
        @mcp.tool(annotations={"readOnlyHint": True})
        def t(p: str):
            Path(p).unlink()
            sp.run(["ls"])
    ''')
    assert {e["sink"] for e in tools["t"]["effects"]} == {"pathlib.Path.unlink", "subprocess.run"}
    assert rules(tools["t"]) == {"readOnly_but_delete", "readOnly_but_execute"}


def test_http_verbs_and_closed_world(tmp_path):
    tools = analyze(tmp_path, '''
        import requests
        @mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
        def remove_user(uid):
            requests.delete(f"https://api.x.com/users/{uid}")
    ''')
    assert cats(tools["remove_user"]) == {"network", "delete"}
    # a fixed host is not proof of a closed or an open world: review, not inconsistency
    assert rules(tools["remove_user"]) == {"readOnly_but_delete"}
    assert {r["rule"] for r in tools["remove_user"]["review"]} == {"closedworld_network_unknown_world"}


def test_open_world_when_url_comes_from_input(tmp_path):
    tools = analyze(tmp_path, '''
        import httpx
        BASE = "https://api.internal.x.com"
        @mcp.tool(annotations={"openWorldHint": False})
        def fetch_page(url):
            return httpx.get(url)
        @mcp.tool(annotations={"openWorldHint": False})
        def status():
            return httpx.get(f"{BASE}/status")
    ''')
    assert rules(tools["fetch_page"]) == {"closedworld_but_open_network"}
    assert rules(tools["status"]) == set() and tools["status"]["review"]


def test_destructive_false_means_additive_only(tmp_path):
    tools = analyze(tmp_path, '''
        @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
        def append_note(t):
            with open("notes.md", "a") as f: f.write(t)
        @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False})
        def save(p, t):
            with open(p, "w") as f: f.write(t)
        @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
        def ro(p, t):
            with open(p, "w") as f: f.write(t)
    ''')
    assert rules(tools["append_note"]) == set()
    assert rules(tools["save"]) == {"nondestructive_but_overwrite"}
    # destructiveHint is meaningless when readOnlyHint is true: only the readOnly rule fires
    assert rules(tools["ro"]) == {"readOnly_but_write"}


def test_dict_get_is_not_http(tmp_path):
    tools = analyze(tmp_path, '''
        @mcp.tool(annotations={"openWorldHint": False})
        def t(http_headers):
            return http_headers.get("authorization")
    ''')
    assert tools["t"]["effects"] == []


def test_omitted_hints_never_violate(tmp_path):
    tools = analyze(tmp_path, '''
        import os
        @mcp.tool()
        def rm(p): os.remove(p)
    ''')
    assert cats(tools["rm"]) == {"delete"} and tools["rm"]["inconsistencies"] == []


def test_lowlevel_match_dispatcher(tmp_path):
    tools = analyze(tmp_path, '''
        import os
        from mcp.types import Tool, ToolAnnotations
        class T(str, Enum):
            READ = "read_it"
            DROP = "drop_it"
        def tools():
            return [Tool(name=T.READ.value, inputSchema={}, annotations=ToolAnnotations(readOnlyHint=True)),
                    Tool(name=T.DROP.value, inputSchema={}, annotations=ToolAnnotations(readOnlyHint=True))]
        @server.call_tool()
        async def call_tool(name, arguments):
            match name:
                case T.READ:
                    return os.listdir(".")
                case T.DROP:
                    os.remove(arguments["p"])
    ''')
    assert tools["read_it"]["entry"] == "call_tool[read_it]" and not tools["read_it"]["inconsistencies"]
    assert rules(tools["drop_it"]) == {"readOnly_but_delete"}


# --- labeling rules R1-R6 (labeling/guide.md): kinds and strict vs lenient ---

def kinds(t):
    return {v["witness"]["kind"] for v in t["inconsistencies"]}


def test_r1_bookkeeping_delete_is_lenient(tmp_path):
    tools = analyze(tmp_path, '''
        from pathlib import Path
        @mcp.tool(annotations={"destructiveHint": False})
        def commit(repo):
            git_dir = Path(repo.git_dir)
            for name in ("MERGE_HEAD", "MERGE_MSG"):
                (git_dir / name).unlink(missing_ok=True)
    ''')
    assert kinds(tools["commit"]) == {"bookkeeping"}
    assert tools["commit"]["inconsistencies_lenient"] == []


def test_r2_cleanup_in_except_handler(tmp_path):
    tools = analyze(tmp_path, '''
        import os
        @mcp.tool(annotations={"destructiveHint": False})
        def convert(out):
            try:
                build(out)
            except Exception:
                os.remove(out)
                raise
    ''')
    assert kinds(tools["convert"]) == {"cleanup"} and tools["convert"]["inconsistencies_lenient"] == []


def test_r2_deleting_user_file_stays_strict(tmp_path):
    tools = analyze(tmp_path, '''
        import os
        @mcp.tool(annotations={"destructiveHint": False})
        def remove(path):
            os.remove(path)
    ''')
    assert kinds(tools["remove"]) == {"plain"} and len(tools["remove"]["inconsistencies_lenient"]) == 1


def test_r3_fixed_vs_dynamic_command(tmp_path):
    tools = analyze(tmp_path, '''
        import subprocess
        from shlex import split
        @mcp.tool(annotations={"readOnlyHint": True})
        def pw(n):
            subprocess.run(split(f"hankify-pw --num-words {n}"))
        @mcp.tool(annotations={"readOnlyHint": True})
        def shell(cmd):
            subprocess.run(cmd, shell=True)
    ''')
    assert kinds(tools["pw"]) == {"execute_fixed"} and tools["pw"]["inconsistencies_lenient"] == []
    assert kinds(tools["shell"]) == {"execute_dynamic"} and tools["shell"]["inconsistencies_lenient"]


def test_r4_post_to_search_or_graphql_query(tmp_path):
    tools = analyze(tmp_path, '''
        import requests
        @mcp.tool(annotations={"readOnlyHint": True})
        def find(q):
            requests.post("https://api.x.com/search", json={"q": q})
        @mcp.tool(annotations={"readOnlyHint": True})
        def gql(q):
            requests.post("https://api.x.com/graphql", json={"query": "query { me { id } }"})
        @mcp.tool(annotations={"readOnlyHint": True})
        def create(name):
            requests.post("https://api.x.com/users", json={"name": name})
    ''')
    assert tools["find"]["inconsistencies_lenient"] == [] and tools["gql"]["inconsistencies_lenient"] == []
    assert kinds(tools["create"]) == {"plain"}


def test_r5_debug_log_vs_state_journal(tmp_path):
    tools = analyze(tmp_path, '''
        @mcp.tool(annotations={"readOnlyHint": True})
        def status():
            with open("server.log", "a") as f:
                f.write("called")
        @mcp.tool(annotations={"readOnlyHint": True})
        def settle(rows):
            with open("settlements.jsonl", "a") as f:
                f.write(rows)
    ''')
    assert kinds(tools["status"]) == {"log"} and tools["status"]["inconsistencies_lenient"] == []
    assert kinds(tools["settle"]) == {"plain"} and tools["settle"]["inconsistencies_lenient"]


def test_r6_checkout_branch_vs_force(tmp_path):
    tools = analyze(tmp_path, '''
        import git
        @mcp.tool(annotations={"destructiveHint": False})
        def switch(repo: git.Repo, b):
            repo.git.checkout(b)
        @mcp.tool(annotations={"destructiveHint": False})
        def restore(repo: git.Repo, path):
            repo.git.checkout("--", path)
    ''')
    assert tools["switch"]["inconsistencies"] == []
    assert {v["rule"] for v in tools["restore"]["inconsistencies"]} == {"nondestructive_but_delete"}
