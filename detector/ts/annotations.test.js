// Tests for the TS/JS annotation parser: node --test detector/ts
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { parseRepo } = require("./annotations");

function repo(files) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mcp-ts-"));
  for (const [name, text] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(dir, name)), { recursive: true });
    fs.writeFileSync(path.join(dir, name), text);
  }
  return Object.fromEntries(parseRepo(dir).map(t => [t.tool, t]));
}
const hints = t => [t.annotations.readOnlyHint, t.annotations.destructiveHint, t.annotations.openWorldHint];

test("registerTool with inline config", () => {
  const t = repo({ "s.ts": `server.registerTool("list", {description: "List all", annotations: {readOnlyHint: true}}, async () => ({}));` });
  assert.equal(t.list.style, "registerTool");
  assert.equal(t.list.description, "List all");
  assert.deepEqual(hints(t.list), ["true", "omitted", "omitted"]);
  assert.equal(t.list.handler, "<inline>");
});

test("name and config held in consts, handler by name", () => {
  const t = repo({ "s.ts": `
    const name = "echo";
    const config = { description: "Echo", annotations: { readOnlyHint: true, openWorldHint: false } as const };
    function handle() {}
    export const reg = (server) => { server.registerTool(name, config, handle); };` });
  assert.deepEqual(hints(t.echo), ["true", "omitted", "false"]);
  assert.equal(t.echo.handler, "handle");
});

test("annotations imported from another file and spread", () => {
  const t = repo({
    "consts.ts": `export const READ_ONLY = { readOnlyHint: true, destructiveHint: false };`,
    "s.ts": `import { READ_ONLY } from "./consts";
      server.registerTool("get", { annotations: { ...READ_ONLY, openWorldHint: true } }, h);`,
  });
  assert.deepEqual(hints(t.get), ["true", "false", "true"]);
});

test("older server.tool(name, desc, schema, annotations, cb) API", () => {
  const t = repo({ "s.js": `
    server.tool("rm", "Delete a file", { path: z.string() }, { destructiveHint: true }, async ({ path }) => {});
    server.tool("ping", async () => {});` });
  assert.equal(t.rm.description, "Delete a file");
  assert.deepEqual(hints(t.rm), ["omitted", "true", "omitted"]);
  assert.equal(t.ping.annotations_kind, "none");
});

test("FastMCP addTool with execute", () => {
  const t = repo({ "s.ts": `server.addTool({ name: "add", description: "Add", annotations: { readOnlyHint: false }, execute: async () => "x" });` });
  assert.equal(t.add.style, "addTool");
  assert.equal(t.add.handler, "<inline>");
  assert.deepEqual(hints(t.add), ["false", "omitted", "omitted"]);
});

test("raw tool objects for low-level ListTools, enum names", () => {
  const t = repo({ "s.ts": `
    enum Tools { Search = "search_docs" }
    const tools = [{ name: Tools.Search, description: "Search", inputSchema: {}, annotations: { readOnlyHint: true } }];
    server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools }));` });
  assert.equal(t.search_docs.style, "raw");
  assert.deepEqual(hints(t.search_docs), ["true", "omitted", "omitted"]);
});

test("unresolved values and test files", () => {
  const t = repo({
    "s.ts": `server.registerTool("a", { annotations: makeAnnotations() }, h);
             server.registerTool("b", { annotations: { readOnlyHint: process.env.RO === "1" } }, h);`,
    "__tests__/s.test.ts": `server.registerTool("fake", { annotations: { readOnlyHint: true } }, h);`,
  });
  assert.equal(t.a.annotations_kind, "unresolved");
  assert.deepEqual(hints(t.b), ["unresolved", "omitted", "omitted"]);
  assert.equal(t.fake, undefined);
});

test("a config object is not counted twice as a raw tool", () => {
  const t = repo({ "s.ts": `server.registerTool("x", { name: "x", inputSchema: {}, annotations: {} }, h);` });
  assert.equal(Object.keys(t).length, 1);
  assert.equal(t.x.style, "registerTool");
});

test("wrapper function: each call site is a tool", () => {
  const t = repo({ "s.ts": `
    import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
    const add = (name: string, description: string, read: boolean, fn: any) =>
      server.registerTool(name, { description, annotations: { readOnlyHint: read, destructiveHint: false } }, async (i) => fn(i));
    add("list_purchases", "List purchases.", true, () => 1);
    add("create_claim", "Create a claim.", false, () => 2);` });
  assert.equal(t.list_purchases.style, "registerTool_via_wrapper");
  assert.equal(t.list_purchases.description, "List purchases.");
  assert.deepEqual(hints(t.list_purchases), ["true", "false", "omitted"]);
  assert.deepEqual(hints(t.create_claim), ["false", "false", "omitted"]);
  assert.equal(Object.keys(t).length, 2);
});

test("registerAppTool(server, name, config, handler)", () => {
  const t = repo({ "s.ts": `
    const TOOL_HINTS = { readOnlyHint: false, destructiveHint: false, openWorldHint: false };
    registerAppTool(server, "create_game", { description: "New game", annotations: TOOL_HINTS }, handleCreateGame);` });
  assert.equal(t.create_game.style, "registerAppTool");
  assert.equal(t.create_game.handler, "handleCreateGame");
  assert.deepEqual(hints(t.create_game), ["false", "false", "false"]);
});

test("NestJS-style @McpTool decorator on a method", () => {
  const t = repo({ "s.ts": `
    import { McpTool } from "@onivoro/server-mcp";
    class Tools {
      @McpTool({ name: "echo", description: "Echo", annotations: { readOnlyHint: true } })
      async echo(args) { return args; }
    }` });
  assert.equal(t.echo.style, "decorator");
  assert.equal(t.echo.handler, "echo");
  assert.deepEqual(hints(t.echo), ["true", "omitted", "omitted"]);
  assert.deepEqual(t.echo.mcp_imports, ["@onivoro/server-mcp"]);
});

test("non-MCP agent tools are kept but have no MCP imports", () => {
  const t = repo({ "s.ts": `
    import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
    pi.registerTool({ name: "probe", description: "Probe", annotations: { readOnlyHint: false }, async execute() {} });` });
  assert.equal(t.probe.handler, "execute");
  assert.deepEqual(t.probe.mcp_imports, []);
});

test("mcpOnly drops repos that never import an MCP library", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mcp-ts-"));
  fs.writeFileSync(path.join(dir, "s.ts"), `pi.registerTool({ name: "probe", annotations: { readOnlyHint: false }, async execute() {} });`);
  assert.equal(parseRepo(dir, { mcpOnly: true }).length, 0);
  fs.writeFileSync(path.join(dir, "server.ts"), `import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";`);
  assert.equal(parseRepo(dir, { mcpOnly: true }).length, 1);  // the SDK import is in another file
});
