"""Tests for E(t) and the C<->A rules: python -m pytest detector/python"""
import textwrap

from effects import Analyzer, Repo


def analyze(tmp_path, code, k=3):
    (tmp_path / "server.py").write_text(textwrap.dedent(code), encoding="utf-8")
    return {t["tool"]: t for t in Analyzer(Repo(tmp_path), k).analyze()}


def cats(t):
    return {e["category"] for e in t["effects"]}


def rules(t):
    return {v["rule"] for v in t["violations"]}


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
    assert cats(tools["show"]) == {"read"} and not tools["show"]["violations"]
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
    assert rules(tools["remove_user"]) == {"readOnly_but_delete", "closedworld_but_network"}


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
    assert cats(tools["rm"]) == {"delete"} and tools["rm"]["violations"] == []


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
    assert tools["read_it"]["entry"] == "call_tool[read_it]" and not tools["read_it"]["violations"]
    assert rules(tools["drop_it"]) == {"readOnly_but_delete"}
