// Tests for TS/JS E(t) and the C<->A rules: node --test detector/ts
const test = require("node:test");
const assert = require("node:assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { Repo, Analyzer } = require("./effects");

function analyze(files, k = 3) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mcp-eff-"));
  for (const [name, text] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(path.join(dir, name)), { recursive: true });
    fs.writeFileSync(path.join(dir, name), text);
  }
  return Object.fromEntries(new Analyzer(new Repo(dir), k).analyze().map(t => [t.tool, t]));
}
const cats = t => new Set(t.effects.map(e => e.category));
const rules = t => new Set(t.inconsistencies.map(v => v.rule));
const kinds = t => new Set(t.inconsistencies.map(v => v.witness.kind));

test("fs through an imported helper, two files deep", () => {
  const t = analyze({
    "store.ts": `import { promises as fs } from "fs";
      export async function save(p: string, s: string) { await fs.writeFile(p, s); }
      export async function drop(p: string) { await fs.rm(p, { recursive: true }); }`,
    "server.ts": `import { save, drop } from "./store.js";
      server.registerTool("note", { annotations: { readOnlyHint: true } }, async ({ p }) => { await save(p, "x"); });
      server.registerTool("wipe", { annotations: { readOnlyHint: false, destructiveHint: false } }, async ({ p }) => drop(p));`,
  });
  assert.deepEqual(rules(t.note), new Set(["readOnly_but_write"]));
  assert.deepEqual(rules(t.wipe), new Set(["nondestructive_but_delete"]));
  assert.ok(t.note.inconsistencies[0].witness.path[0].startsWith("store.ts:save"));
});

test("depth limit k", () => {
  const files = { "s.ts": `import fs from "node:fs";
    function a(p) { b(p); } function b(p) { fs.unlinkSync(p); }
    server.registerTool("x", { annotations: { destructiveHint: false } }, async ({ p }) => a(p));` };
  assert.ok(cats(analyze(files, 2).x).has("delete"));
  assert.ok(!cats(analyze(files, 1).x).has("delete"));
});

test("class instance created in the enclosing function", () => {
  const t = analyze({ "s.ts": `
    import { writeFileSync } from "fs";
    class Store { save(s) { writeFileSync("data.json", s, { flag: "a" }); } }
    function main() {
      const store = new Store();
      server.registerTool("add", { annotations: { readOnlyHint: true } }, async () => store.save("x"));
    }` });
  assert.deepEqual(rules(t.add), new Set(["readOnly_but_write"]));
});

test("fetch: method decides the effect; URL from input = open world", () => {
  const t = analyze({ "s.ts": `
    server.registerTool("get", { annotations: { readOnlyHint: true, openWorldHint: false } },
      async ({ url }) => fetch(url));
    server.registerTool("del", { annotations: { readOnlyHint: true, openWorldHint: false } },
      async ({ id }) => fetch(\`https://api.x.com/items/\${id}\`, { method: "DELETE" }));` });
  assert.deepEqual(rules(t.get), new Set(["closedworld_but_open_network"]));
  assert.deepEqual(rules(t.del), new Set(["readOnly_but_delete"]));
  assert.equal(t.del.review.length, 1);  // fixed host: review, not inconsistency
});

test("axios verbs and child_process", () => {
  const t = analyze({ "s.ts": `
    import axios from "axios";
    import { execSync, exec } from "child_process";
    server.registerTool("a", { annotations: { readOnlyHint: true } }, async ({ cmd }) => {
      await axios.post("https://api.x.com/orders", {});
      execSync("git status");
      exec(cmd);
    });` });
  assert.deepEqual(rules(t.a), new Set(["readOnly_but_write", "readOnly_but_execute"]));
  const ex = t.a.inconsistencies.filter(v => v.rule === "readOnly_but_execute").map(v => v.witness.kind).sort();
  assert.deepEqual(ex, ["execute_dynamic", "execute_fixed"]);
});

test("SQL and ORM chains", () => {
  const t = analyze({ "s.ts": `
    server.registerTool("q", { annotations: { readOnlyHint: true } }, async () => {
      await pool.query("SELECT * FROM t");
      await prisma.user.delete({ where: { id: 1 } });
      await sql\`UPDATE t SET a = 1\`;
    });` });
  assert.deepEqual(rules(t.q), new Set(["readOnly_but_delete", "readOnly_but_write"]));
});

test("no false positives: Map.delete, promise .catch, dict-like get", () => {
  const t = analyze({ "s.ts": `
    import { promises as fs } from "fs";
    const clients = new Map();
    server.registerTool("x", { annotations: { readOnlyHint: true, openWorldHint: false } }, async ({ id, headers }) => {
      clients.delete(id);
      headers.get("authorization");
      await fs.readFile("a.txt").catch(() => {});
    });` });
  assert.deepEqual([...cats(t.x)], ["read"]);
  assert.equal(t.x.effects.length, 1);
});

test("labeling kinds: atomic save, lock file, cleanup in catch", () => {
  const t = analyze({ "s.ts": `
    import { promises as fs } from "fs";
    async function persist(file, s) {
      const tmp = file + ".tmp";
      try { await fs.writeFile(tmp, s); await fs.rename(tmp, file); }
      catch (e) { await fs.unlink(tmp); throw e; }
    }
    server.registerTool("add", { annotations: { readOnlyHint: false, destructiveHint: false } }, async ({ s }) => persist("db.json", s));` });
  assert.ok(t.add.inconsistencies.length > 0);
  assert.deepEqual(t.add.inconsistencies_lenient, []);
  for (const k of kinds(t.add)) assert.ok(["temp", "cleanup"].includes(k), k);
});

test("low-level switch dispatcher maps branches to raw tools", () => {
  const t = analyze({ "s.ts": `
    import { unlinkSync, readFileSync } from "fs";
    const tools = [
      { name: "read_it", inputSchema: {}, annotations: { readOnlyHint: true } },
      { name: "drop_it", inputSchema: {}, annotations: { readOnlyHint: true } }];
    server.setRequestHandler(CallToolRequestSchema, async (request) => {
      const args = request.params.arguments;
      switch (request.params.name) {
        case "read_it": return readFileSync(args.p);
        case "drop_it": unlinkSync(args.p); return {};
      }
    });` });
  assert.equal(t.read_it.entry, "call_tool[read_it]");
  assert.deepEqual(t.read_it.inconsistencies, []);
  assert.deepEqual(rules(t.drop_it), new Set(["readOnly_but_delete"]));
});
