"""Tests for the Python annotation parser: python -m pytest detector/python"""
import textwrap

from annotations import parse_file


def parse(tmp_path, code):
    f = tmp_path / "server.py"
    f.write_text(textwrap.dedent(code), encoding="utf-8")
    return {t["tool"]: t for t in parse_file(f, "server.py")}


def hints(t):
    a = t["annotations"]
    return a["readOnlyHint"], a["destructiveHint"], a["openWorldHint"]


def test_fastmcp_toolannotations(tmp_path):
    tools = parse(tmp_path, '''
        from mcp.server.fastmcp import FastMCP
        from mcp.types import ToolAnnotations
        mcp = FastMCP("x")

        @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
        def list_notes() -> str:
            """List all notes."""
            return ""
    ''')
    t = tools["list_notes"]
    assert t["style"] == "fastmcp" and t["handler"] == "list_notes"
    assert hints(t) == ("true", "omitted", "false")
    assert t["description"] == "List all notes."


def test_fastmcp_dict_name_and_description(tmp_path):
    tools = parse(tmp_path, '''
        @mcp.tool(name="rm", description="Delete a note", annotations={"destructiveHint": True})
        async def delete_note(id: str): ...
    ''')
    t = tools["rm"]
    assert t["handler"] == "delete_note" and t["description"] == "Delete a note"
    assert hints(t) == ("omitted", "true", "omitted")


def test_bare_decorator_has_no_annotations(tmp_path):
    tools = parse(tmp_path, '''
        @mcp.tool
        def ping(): ...
        @mcp.tool()
        def pong(): ...
    ''')
    assert tools["ping"]["annotations_kind"] == "none"
    assert hints(tools["pong"]) == ("omitted", "omitted", "omitted")


def test_module_level_constant(tmp_path):
    tools = parse(tmp_path, '''
        READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False)
        @mcp.tool(annotations=READ_ONLY)
        def get(): ...
    ''')
    assert hints(tools["get"]) == ("true", "false", "omitted")


def test_unresolved_values(tmp_path):
    tools = parse(tmp_path, '''
        @mcp.tool(annotations=make_annotations())
        def a(): ...
        @mcp.tool(annotations=ToolAnnotations(readOnlyHint=settings.ro))
        def b(): ...
    ''')
    assert tools["a"]["annotations_kind"] == "unresolved"
    assert hints(tools["b"]) == ("unresolved", "omitted", "omitted")


def test_variable_in_enclosing_function(tmp_path):
    tools = parse(tmp_path, '''
        def register(mcp):
            read = ToolAnnotations(readOnlyHint=True)
            @mcp.tool(annotations=read)
            async def status(): ...
    ''')
    assert hints(tools["status"]) == ("true", "omitted", "omitted")


def test_constant_imported_from_other_module(tmp_path):
    (tmp_path / "consts.py").write_text("RO = {'readOnlyHint': True}\n", encoding="utf-8")
    (tmp_path / "server.py").write_text(
        "from consts import RO\n@mcp.tool(annotations=RO)\ndef get(): ...\n", encoding="utf-8")
    from annotations import parse_repo
    tools = {t["tool"]: t for t in parse_repo(tmp_path)}
    assert hints(tools["get"]) == ("true", "omitted", "omitted")


def test_add_tool_both_signatures(tmp_path):
    tools = parse(tmp_path, '''
        def handle(args): """Run it."""
        server.add_tool("run", "Run a task", {}, handle, annotations={"openWorldHint": True})
        mcp.add_tool(handle, name="run2", annotations=ToolAnnotations(readOnlyHint=False))
    ''')
    assert tools["run"]["handler"] == "handle" and tools["run"]["description"] == "Run a task"
    assert hints(tools["run"]) == ("omitted", "omitted", "true")
    assert tools["run2"]["description"] == "Run it."
    assert hints(tools["run2"]) == ("false", "omitted", "omitted")


def test_non_mcp_tool_class_ignored(tmp_path):
    tools = parse(tmp_path, '''
        from app.agent.tools import Tool
        Tool(name="add_todo", description="x", parameters={})
    ''')
    assert tools == {}


def test_mcp_tool_class_via_types_alias(tmp_path):
    tools = parse(tmp_path, '''
        import mcp.types as types
        types.Tool(name="t", inputSchema={}, annotations=types.ToolAnnotations(destructiveHint=True))
    ''')
    assert hints(tools["t"]) == ("omitted", "true", "omitted")


def test_raw_dict_tool(tmp_path):
    tools = parse(tmp_path, '''
        READ_ONLY = {"readOnlyHint": True, "openWorldHint": False}
        TOOLS = [{"name": "list", "description": "List", "inputSchema": {}, "annotations": READ_ONLY}]
    ''')
    assert tools["list"]["style"] == "raw"
    assert hints(tools["list"]) == ("true", "omitted", "false")


def test_ambiguous_name_is_unresolved(tmp_path):
    tools = parse(tmp_path, '''
        def a(mcp):
            ann = ToolAnnotations(readOnlyHint=True)
        def b(mcp):
            ann = ToolAnnotations(readOnlyHint=False)
            @mcp.tool(annotations=ann)
            def x(): ...
    ''')
    assert tools["x"]["annotations_kind"] == "unresolved"


def test_repo_constants_with_name_ambiguous_in_one_file(tmp_path):
    (tmp_path / "a.py").write_text("X = 1\nX = 2\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("X = 3\n", encoding="utf-8")
    from annotations import parse_repo
    assert parse_repo(tmp_path) == []


def test_lowlevel_enum_name(tmp_path):
    tools = parse(tmp_path, '''
        from mcp.types import Tool, ToolAnnotations
        class Tools(str, Enum):
            NOW = "get_time"
        @server.list_tools()
        async def list_tools():
            return [Tool(name=Tools.NOW.value, description="Now",
                         annotations=ToolAnnotations(readOnlyHint=True))]
    ''')
    t = tools["get_time"]
    assert t["style"] == "lowlevel" and t["handler"] is None
    assert hints(t) == ("true", "omitted", "omitted")
