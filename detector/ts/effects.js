// E(t) for TypeScript / JavaScript and the C<->A check: the TS counterpart of
// detector/python/effects.py, with the same output, rules and effect kinds.
//
// From each tool's handler, walk the code it can reach (calls into the repo's
// own functions are followed across files, up to depth k) and collect sinks:
// read / write / delete / execute / network. Calls are resolved through
// imports (ESM and require), local functions, class methods (this.x), local
// variable initializers (new X(), factories) and wrapper-call bindings. When a
// receiver cannot be resolved, distinctive method names (unlink, deleteMany,
// prisma.user.delete, client.post) still match with confidence "low".
//
// Usage: node effects.js REPO_DIR [--k 3] [--out OUT.jsonl] [--all]
const fs = require("fs");
const path = require("path");
const ts = require("typescript");
const yaml = require("js-yaml");
const A = require("./annotations");
const { unwrap, dotted, line, AMBIGUOUS } = A;

const CATEGORIES = ["read", "write", "delete", "execute", "network"];
const CATALOG = yaml.load(fs.readFileSync(path.join(__dirname, "../sinks/typescript.yaml"), "utf8"));
// "fs.unlink*" = one name segment (unlink, unlinkSync), not fs.unlink(x).catch;
// a trailing ".*" covers a whole namespace (openai.chat.completions.create)
const glob = p => new RegExp("^" + p.replace(/[.+^${}()|[\]\\]/g, "\\$&")
  .replace(/\\\.\*$/, "\\..+").replace(/\*/g, "[^.]*") + "$");
const PROMISE_METHODS = new Set(["then", "catch", "finally"]);
const MATCHERS = CATEGORIES.flatMap(c => (CATALOG[c] || []).map(p => [glob(p), c]));
const WRITE_MODE = {};
for (const [mode, names] of Object.entries(CATALOG.write_modes)) for (const n of names) WRITE_MODE[n.toLowerCase()] = mode;
const HTTP = Object.fromEntries(Object.entries(CATALOG.http_method_effects).map(([k, v]) => [k.toLowerCase(), v]));
const SQL = { select: "read", with: "read", insert: "write", update: "write", create: "write", alter: "write",
  replace: "write", upsert: "write", merge: "write", delete: "delete", drop: "delete", truncate: "delete" };
const SQL_MODE = { insert: "additive", create: "additive", update: "modifying", alter: "modifying", replace: "modifying", upsert: "modifying", merge: "modifying" };
const GLOBALS = { fetch: "fetch", eval: "eval", Function: "Function", WebSocket: "ws" };
const FS_ALIASES = new Set(["fs", "fs/promises", "fs-extra", "fs-extra/esm", "graceful-fs"]);

// distinctive method names on receivers we cannot type
const UNTYPED = {
  unlink: "delete", unlinkSync: "delete", rm: "delete", rmSync: "delete", rmdir: "delete", rmdirSync: "delete",
  deleteOne: "delete", deleteMany: "delete", findByIdAndDelete: "delete", findOneAndDelete: "delete",
  dropCollection: "delete", dropDatabase: "delete",
  writeFile: "write", writeFileSync: "write", appendFile: "write", appendFileSync: "write", mkdirSync: "write",
  insertOne: "write", insertMany: "write", updateOne: "write", updateMany: "write", replaceOne: "write",
  findOneAndUpdate: "write", findByIdAndUpdate: "write", bulkWrite: "write",
};
// ORM-style chains: prisma.user.delete(), db.insert(t), supabase.from("t").update()
const ORM_ROOT = /^(prisma|db|database|drizzle|knex|supabase|orm|repo|repository|model|em|tx|trx|sql|client)/i;
const ORM = { create: ["write", "additive"], createMany: ["write", "additive"], insert: ["write", "additive"],
  update: ["write", "modifying"], updateMany: ["write", "modifying"], upsert: ["write", "modifying"],
  delete: ["delete"], deleteMany: ["delete"], remove: ["delete"], destroy: ["delete"], truncate: ["delete"],
  findMany: ["read"], findUnique: ["read"], findFirst: ["read"], select: ["read"], count: ["read"] };
const HTTP_RECEIVER = /client|http|api|session|axios|request|fetcher/i;
// name-based call resolution: skip names too common to identify one function
const MAX_BY_NAME = 3;
const GENERIC_NAMES = new Set(["then", "catch", "finally", "call", "apply", "bind", "toString", "valueOf", "toJSON",
  "push", "pop", "shift", "slice", "splice", "concat", "join", "split", "replace", "map", "filter", "reduce", "forEach",
  "find", "some", "every", "includes", "indexOf", "keys", "values", "entries", "assign", "freeze", "parse", "stringify",
  "send", "emit", "handle", "execute", "process", "init", "start", "stop", "close", "open", "next", "done", "write",
  "read", "load", "save", "create", "update", "delete", "remove", "list", "get", "set", "has", "add", "clear", "run",
  "invoke", "request", "fetch", "query", "search", "render", "format", "validate", "build", "make", "reset", "log",
  "info", "warn", "error", "debug", "trace", "json", "text", "test", "match", "exec", "resolve", "reject", "connect"]);

// effect kinds for the labeling rules (labeling/guide.md), as in effects.py
const BOOKKEEPING = ["merge_head", "orig_head", "autostash", "git_dir", ".git/", ".lock", "lockfile", "lockpath", "lock_path", ".pid"];
const WRITE_BOOKKEEPING = ["manifest", "cache", "_state", "state.json", "registry.json", "checkpoint"];
const TEMP = ["tmp", "temp", "partial", ".part", "scratch"];
const CLEANUP_FUNCS = ["cleanup", "clean_up", "cleanUp", "removePartial", "rollback", "discard"];
const LOG = [".log", "/log", "logs/", "debug", "trace", "telemetry", "observability"];
const READ_ENDPOINT = ["search", "query", "token", "oauth", "login", "auth", "lookup"];
const LENIENT_DROP = new Set(["bookkeeping", "cleanup", "temp", "execute_fixed", "post_read_like", "log"]);

// own keys only: UNTYPED.toString etc. would find inherited Object methods
const own = (m, k) => (k != null && Object.prototype.hasOwnProperty.call(m, k) ? m[k] : undefined);
const normModule = spec => { spec = spec.replace(/^node:/, ""); return FS_ALIASES.has(spec) ? "fs" : spec; };
const isFn = n => n && (ts.isFunctionDeclaration(n) || ts.isArrowFunction(n) || ts.isFunctionExpression(n) || ts.isMethodDeclaration(n));
const lower = s => s.toLowerCase();

class Repo {
  constructor(root) {
    this.root = root;
    this.parsed = A.parseSources(root);
    this.consts = A.repoConstants(this.parsed);
    this.files = new Map();
    for (const f of this.parsed) this.files.set(f.rel, { rel: f.rel, sf: f.sf });
    this.bySf = new Map([...this.files.values()].map(info => [info.sf, info]));
    for (const info of this.files.values()) this.index(info);
    this.byName = this.indexByName();
  }

  // every named function-like node in the repo, by its short name, for calls on
  // receivers we cannot type (objects passed in by dependency injection):
  // functions, class methods, and object-literal methods / function properties
  indexByName() {
    const by = new Map();
    const add = (name, info, node) => { if (!by.has(name)) by.set(name, []); by.get(name).push({ info, node }); };
    for (const info of this.files.values()) {
      const visit = n => {
        if ((ts.isFunctionDeclaration(n) || ts.isMethodDeclaration(n)) && n.name && ts.isIdentifier(n.name) && n.body) add(n.name.text, info, n);
        else if ((ts.isPropertyAssignment(n) || ts.isVariableDeclaration(n) || ts.isPropertyDeclaration(n)) && n.name && ts.isIdentifier(n.name) &&
          n.initializer && (ts.isArrowFunction(unwrap(n.initializer)) || ts.isFunctionExpression(unwrap(n.initializer)))) add(n.name.text, info, unwrap(n.initializer));
        ts.forEachChild(n, visit);
      };
      visit(info.sf);
    }
    return by;
  }

  ctx(info) { return info.ctx || (info.ctx = new A.FileCtx(info.sf, this.consts)); }

  resolveModule(fromRel, spec) {
    if (!spec.startsWith(".")) return null;
    const base = path.posix.normalize(path.posix.join(path.posix.dirname(fromRel), spec)).replace(/\.(m|c)?js$/, "");
    for (const cand of [base, ...[".ts", ".tsx", ".mts", ".cts", ".js", ".mjs", ".cjs", ".jsx"].flatMap(e => [base + e, `${base}/index${e}`])])
      if (this.files.has(cand)) return cand;
    return null;
  }

  index(info) {
    const imports = new Map(), functions = new Map(), classes = new Set();
    const addImport = (local, spec, name) => {
      const rel = this.resolveModule(info.rel, spec);
      imports.set(local, rel ? { rel, name } : { mod: normModule(spec), name });
    };
    const visit = (node, cls) => {
      if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier) && node.importClause) {
        const spec = node.moduleSpecifier.text, c = node.importClause;
        if (c.name) addImport(c.name.text, spec, "default");
        if (c.namedBindings && ts.isNamespaceImport(c.namedBindings)) addImport(c.namedBindings.name.text, spec, "*");
        if (c.namedBindings && ts.isNamedImports(c.namedBindings))
          for (const e of c.namedBindings.elements) addImport(e.name.text, spec, (e.propertyName || e.name).text);
      } else if (ts.isVariableDeclaration(node) && node.initializer) {
        const init = unwrap(node.initializer.kind === ts.SyntaxKind.AwaitExpression ? node.initializer.expression : node.initializer);
        const req = init && ts.isCallExpression(init) && init.arguments.length === 1 && ts.isStringLiteral(init.arguments[0]) &&
          ((ts.isIdentifier(init.expression) && init.expression.text === "require") || init.expression.kind === ts.SyntaxKind.ImportKeyword);
        if (req && ts.isIdentifier(node.name)) addImport(node.name.text, init.arguments[0].text, "*");
        else if (req && ts.isObjectBindingPattern(node.name))
          for (const e of node.name.elements) addImport(e.name.getText(info.sf), init.arguments[0].text, (e.propertyName || e.name).getText(info.sf));
        else if (ts.isIdentifier(node.name) && (ts.isArrowFunction(init) || ts.isFunctionExpression(init)) && !functions.has(node.name.text))
          functions.set(node.name.text, init);
      } else if (ts.isFunctionDeclaration(node) && node.name && !functions.has(node.name.text)) {
        functions.set(node.name.text, node);
      } else if (ts.isClassDeclaration(node) && node.name) {
        classes.add(node.name.text);
        for (const m of node.members)
          if (ts.isMethodDeclaration(m) && m.name && ts.isIdentifier(m.name)) functions.set(`${node.name.text}.${m.name.text}`, m);
          else if (ts.isPropertyDeclaration(m) && m.name && ts.isIdentifier(m.name) && m.initializer && isFn(unwrap(m.initializer)))
            functions.set(`${node.name.text}.${m.name.text}`, unwrap(m.initializer));
      }
      ts.forEachChild(node, c => visit(c, cls));
    };
    visit(info.sf);
    info.imports = imports;
    info.functions = functions;
    info.classes = classes;
  }
}

function enclosingClass(node) {
  for (let n = node.parent; n; n = n.parent) if (ts.isClassDeclaration(n) && n.name) return n.name.text;
  return null;
}
function enclosingName(node) {
  for (let n = node.parent; n; n = n.parent) {
    if ((ts.isFunctionDeclaration(n) || ts.isMethodDeclaration(n)) && n.name) return n.name.getText();
    if ((ts.isArrowFunction(n) || ts.isFunctionExpression(n)) && ts.isVariableDeclaration(n.parent)) return n.parent.name.getText();
  }
  return "";
}

// what the names visible in a function were assigned from (flow-insensitive):
// the module's top level, then each enclosing function, then the function itself,
// inner bindings overriding outer ones (a handler often uses a manager created
// in the surrounding main())
function localVars(fn, sf) {
  const vars = new Map();
  const collect = (root, deep) => {
    const visit = n => {
      if (ts.isVariableDeclaration(n) && ts.isIdentifier(n.name) && n.initializer) vars.set(n.name.text, n.initializer);
      if (ts.isParameter(n) && ts.isIdentifier(n.name) && n.type && ts.isTypeReferenceNode(n.type)) vars.set(n.name.text, { typeName: n.type.typeName });
      if (deep || !isFn(n)) ts.forEachChild(n, visit);  // outer scopes: skip into other functions
    };
    ts.forEachChild(root, visit);
  };
  if (sf) collect(sf, false);
  const chain = [];
  for (let n = fn && fn.parent; n; n = n.parent) if (isFn(n)) chain.unshift(n);
  for (const outer of chain) collect(outer.body || outer, false);
  if (fn) collect(fn, true);
  return vars;
}

class Scope {
  constructor(repo, info, fn, params) {
    this.repo = repo; this.info = info; this.fn = fn; this.params = params || null;
    this.vars = localVars(fn, info.sf);
    this.cls = fn ? enclosingClass(fn) : null;
    this.ctx = repo.ctx(info);
  }

  // qualified name of an expression: a sink string ("fs.unlink", "axios.post"),
  // or {rel, name} for a repo function, or {relModule} for a namespace import
  qualify(expr, depth = 0) {
    expr = unwrap(expr);
    if (!expr || depth > 6) return null;
    if (expr.kind === ts.SyntaxKind.AwaitExpression) return this.qualify(expr.expression, depth + 1);
    if (ts.isIdentifier(expr)) {
      const n = expr.text;
      if (this.params && this.params.has(n)) return this.qualify(this.params.get(n), depth + 1);
      if (this.vars.has(n)) {
        const v = this.vars.get(n);
        if (v.typeName) return this.qualify(v.typeName, depth + 1);
        const t = this.typeOf(v, depth + 1);
        if (t) return t;
      }
      if (this.info.classes.has(n)) return { rel: this.info.rel, cls: n };
      const imp = this.info.imports.get(n);
      if (imp) {
        if (imp.rel && imp.name !== "*" && this.repo.files.get(imp.rel).classes.has(imp.name)) return { rel: imp.rel, cls: imp.name };
        if (imp.rel) return imp.name === "*" ? { relModule: imp.rel } : { rel: imp.rel, name: imp.name === "default" ? "default" : imp.name };
        if (imp.mod === "fs" && imp.name === "promises") return "fs";  // import { promises as fs } from "fs"
        return imp.name === "*" || imp.name === "default" ? imp.mod : `${imp.mod}.${imp.name}`;
      }
      if (this.info.functions.has(n)) return { rel: this.info.rel, name: n };
      if (own(GLOBALS, n)) return GLOBALS[n];
      return null;
    }
    if (ts.isQualifiedName(expr)) {  // type annotations: pg.Client
      const b = this.qualify(expr.left, depth + 1);
      return typeof b === "string" ? `${b}.${expr.right.text}` : null;
    }
    if (ts.isPropertyAccessExpression(expr)) {
      const prop = expr.name.text;
      if (expr.expression.kind === ts.SyntaxKind.ThisKeyword && this.cls) return { rel: this.info.rel, name: `${this.cls}.${prop}` };
      const b = this.qualify(expr.expression, depth + 1);
      if (typeof b === "string") return `${b}.${prop}`;
      if (b && b.relModule) return { rel: b.relModule, name: prop };
      if (b && b.cls) return { rel: b.rel, name: `${b.cls}.${prop}` };  // instance or static method
      return null;
    }
    if (ts.isCallExpression(expr) || ts.isNewExpression(expr)) return this.typeOf(expr, depth + 1);
    return null;
  }

  // the "type" a value has, as a sink namespace: new Pool() -> "pg.Pool", axios.create() -> "axios"
  typeOf(init, depth = 0) {
    init = unwrap(init);
    if (!init) return null;
    if (init.kind === ts.SyntaxKind.AwaitExpression) return this.typeOf(init.expression, depth + 1);
    if (ts.isCallExpression(init) && ts.isIdentifier(init.expression) && init.expression.text === "require" &&
      init.arguments.length === 1 && ts.isStringLiteral(init.arguments[0])) return normModule(init.arguments[0].text);
    if (ts.isNewExpression(init)) {
      const q = this.qualify(init.expression, depth + 1);
      return typeof q === "string" || (q && q.cls) ? q : null;  // new KnowledgeGraphManager() -> its class
    }
    if (ts.isCallExpression(init)) {
      const q = this.qualify(init.expression, depth + 1);
      if (typeof q === "string") return q.replace(/\.(create|default|createClient|connect|getClient|Client|Pool)$/, "");
    }
    if (ts.isIdentifier(init) || ts.isPropertyAccessExpression(init)) { const q = this.qualify(init, depth + 1); return typeof q === "string" ? q : null; }
    return null;
  }

  literal(node) {
    node = unwrap(node);
    if (node && ts.isIdentifier(node)) {
      if (this.params && this.params.has(node.text)) return this.literal(this.params.get(node.text));
      if (this.vars.has(node.text) && !this.vars.get(node.text).typeName) return this.literal(this.vars.get(node.text));
    }
    return this.ctx.literal(node);
  }

  // the call's text plus what its variables were assigned from, lower-cased
  text(node) {
    const parts = [node.getText(this.info.sf)], seen = new Set();
    let frontier = [node];
    for (let d = 0; d < 2; d++) {
      const next = [];
      for (const f of frontier) {
        const visit = n => {
          if (ts.isIdentifier(n) && !seen.has(n.text)) {
            seen.add(n.text);
            const v = (this.params && this.params.get(n.text)) || this.vars.get(n.text);
            if (v && !v.typeName && v.getText) { parts.push(v.getText()); next.push(v); }
          }
          ts.forEachChild(n, visit);
        };
        visit(f);
      }
      frontier = next;
    }
    return parts.join(" ").toLowerCase();
  }
}

// root identifier of a chain: supabase.from("t").delete -> "supabase"
function chainRoot(expr) {
  let n = unwrap(expr), len = 0;
  while (n && (ts.isPropertyAccessExpression(n) || ts.isCallExpression(n) || ts.isElementAccessExpression(n))) {
    if (ts.isPropertyAccessExpression(n)) len++;
    n = unwrap(n.expression);
  }
  return [n && (ts.isIdentifier(n) ? n.text : n.kind === ts.SyntaxKind.ThisKeyword ? "this" : null), len];
}

function sqlCategory(text) {
  const w = (text || "").trim().split(/\s+/)[0];
  return w ? [own(SQL, lower(w)), own(SQL_MODE, lower(w))] : [null, null];
}

function httpVerbOf(call, scope, q) {
  const last = typeof q === "string" ? q.split(".").pop() : null;
  if (last && own(HTTP, lower(last)) !== undefined && last !== "request") return lower(last);
  const opts = call.arguments.find(a => { const o = scope.ctx.resolve(a); return o && ts.isObjectLiteralExpression(o); });
  const o = opts && scope.ctx.resolve(opts);
  const m = o && scope.literal(scope.ctx.prop(o, "method"));
  if (typeof m === "string") return lower(m);
  if (last === "request" && call.arguments.length) { const v = scope.literal(call.arguments[0]); if (typeof v === "string" && own(HTTP, lower(v))) return lower(v); }
  return "get";
}

// [category, sink, confidence, mode?] for one call / new / tagged template
function classify(node, scope) {
  const out = [];
  if (ts.isTaggedTemplateExpression(node)) {
    const tag = unwrap(node.tag).getText(scope.info.sf);
    if (/sql/i.test(tag)) {
      const head = ts.isNoSubstitutionTemplateLiteral(node.template) ? node.template.text : node.template.head.text;
      const [cat, mode] = sqlCategory(head);
      if (cat) out.push([cat, `${tag}\`\``, "high", mode]);
    }
    return out;
  }
  const q = scope.qualify(node.expression);
  const method = ts.isPropertyAccessExpression(unwrap(node.expression)) ? unwrap(node.expression).name.text : null;
  if (PROMISE_METHODS.has(method)) return out;  // x(...).catch(): x itself is classified
  const args = node.arguments || [];

  if (method && ["query", "execute", "run", "exec", "all", "prepare", "unsafe", "raw"].includes(method) && args.length) {
    const sql = scope.literal(args[0]);
    const [cat, mode] = typeof sql === "string" ? sqlCategory(sql) : [null, null];
    if (cat) return [[cat, typeof q === "string" ? q : `?.${method}`, "high", mode]];
  }
  if (typeof q === "string") {
    const hits = new Set();
    for (const [re, cat] of MATCHERS) if (re.test(q) && !hits.has(cat)) { hits.add(cat); out.push([cat, q, "high"]); }
    if (hits.has("network")) {
      const effect = own(HTTP, httpVerbOf(node, scope, q));
      if (effect && effect !== "read") out.push([effect, q, "high"]);
    }
    if (out.length) return out;
  }
  const untyped = method && own(UNTYPED, method);
  if (untyped && !(typeof q === "string" && /^(Map|Set|WeakMap|URLSearchParams|Headers|FormData)\b/.test(q)))
    return [[untyped, `?.${method}`, "low"]];
  const [root, len] = chainRoot(node.expression);
  // ORM chains; .delete also needs an ORM-like root, since Map.delete(key) is common
  const orm = method && own(ORM, method);
  if (orm && root && (method === "delete" ? ORM_ROOT.test(root) && len >= 2 : ORM_ROOT.test(root) || len >= 3)) {
    const [cat, mode] = orm;
    return [[cat, `${root}.….${method}`, "low", mode]];
  }
  // untyped client.post(url): every verb needs a URL-like first argument
  // (clients.delete(sessionId) on a Map is not an HTTP DELETE)
  const verb = method ? own(HTTP, lower(method)) : undefined;  // request[m](...) has no static name
  if (verb !== undefined && root && HTTP_RECEIVER.test(root)) {
    const first = args[0] && unwrap(args[0]);
    const urlLike = first && (ts.isTemplateExpression(first) || ts.isNoSubstitutionTemplateLiteral(first) ||
      (ts.isStringLiteral(first) && /^(https?:|\/)/.test(first.text)) || (ts.isIdentifier(first) && /url|endpoint|path/i.test(first.text)));
    if (urlLike) {
      out.push(["network", `${root}.${method}`, "low"]);
      if (verb !== "read") out.push([verb, `${root}.${method}`, "low"]);
    }
  }
  return out;
}

function fixedProgram(node, scope) {
  let a = node.arguments && node.arguments[0] && unwrap(node.arguments[0]);
  if (a && ts.isIdentifier(a)) { const v = (scope.params && scope.params.get(a.text)) || scope.vars.get(a.text); if (v && !v.typeName) a = unwrap(v); }
  if (!a) return false;
  if (ts.isStringLiteral(a) || ts.isNoSubstitutionTemplateLiteral(a)) return !!a.text.trim();
  if (ts.isTemplateExpression(a)) return !!a.head.text.trim();
  if (ts.isArrayLiteralExpression(a)) return a.elements.length > 0 && ts.isStringLiteral(a.elements[0]);
  return false;
}

function inHandler(node) {
  for (let n = node.parent; n && !isFn(n); n = n.parent) if (ts.isCatchClause(n) || (n.parent && ts.isTryStatement(n.parent) && n.parent.finallyBlock === n)) return true;
  return false;
}

function effectKind(cat, sink, node, scope) {
  const text = scope.text(node);
  const fname = enclosingName(node);
  if (cat === "delete") {
    if (BOOKKEEPING.some(w => text.includes(w))) return "bookkeeping";
    if (inHandler(node) || CLEANUP_FUNCS.some(w => fname.toLowerCase().includes(w.toLowerCase())) || TEMP.some(w => text.includes(w)) || text.includes("tmpdir")) return "cleanup";
  }
  if (cat === "execute") return /^(eval|Function|vm\.)/.test(sink) ? "execute_dynamic" : fixedProgram(node, scope) ? "execute_fixed" : "execute_dynamic";
  if (cat === "write") {
    if ([...BOOKKEEPING, ...WRITE_BOOKKEEPING].some(w => text.includes(w))) return "bookkeeping";
    if (/post|request|fetch|axios/i.test(sink) && (READ_ENDPOINT.some(w => text.includes(w)) || (text.includes("graphql") && !text.includes("mutation")))) return "post_read_like";
    if (LOG.some(w => text.includes(w))) return "log";
    if (TEMP.some(w => text.includes(w)) || text.includes("tmpdir")) return "temp";
  }
  return "plain";
}

function writeMode(sink, node, scope, given) {
  if (given) return given;
  const last = sink.split(".").pop().replace(/Sync$/, "");
  if (/^(fetch|axios|got|ky|node-fetch|undici)/.test(sink) || /client|http|api|request/i.test(sink)) {
    const v = httpVerbOf(node, scope, sink);
    return v === "post" ? "additive" : v === "put" || v === "patch" ? "modifying" : "unknown";
  }
  return own(WRITE_MODE, lower(last)) || "unknown";
}

function networkWorld(node, scope) {
  let url = node.arguments && node.arguments[0];
  if (!url) return "unknown";
  let u = unwrap(url);
  if (ts.isObjectLiteralExpression(u)) { const p = scope.ctx.prop(u, "url"); if (!p) return "unknown"; u = unwrap(p); }
  if (typeof scope.literal(u) === "string" && !ts.isTemplateExpression(u)) return "unknown";
  if (ts.isTemplateExpression(u)) {
    const head = u.head.text;
    if (/:\/\/[^/]/.test(head)) return "unknown";
    const first = u.templateSpans[0] && scope.literal(u.templateSpans[0].expression);
    if (!head && typeof first === "string" && /:\/\//.test(first)) return "unknown";  // `${BASE}/x`
  }
  if (ts.isIdentifier(u)) { const v = scope.vars.get(u.text); if (v && !v.typeName && typeof scope.literal(v) === "string") return "unknown"; }
  return "open";
}

class Analyzer {
  constructor(repo, k = 3) { this.repo = repo; this.k = k; this.cache = new Map(); }

  functionEffects(rel, name, depth) {
    const key = `${rel}::${name}::${depth}`;
    if (this.cache.has(key)) return this.cache.get(key);
    this.cache.set(key, []);
    const info = this.repo.files.get(rel);
    const fn = info && info.functions.get(name);
    const effects = fn ? this.bodyEffects(fn, new Scope(this.repo, info, fn), depth) : [];
    this.cache.set(key, effects);
    return effects;
  }

  bodyEffects(fn, scope, depth) {
    const root = isFn(fn) ? fn.body : fn;
    const effects = [];
    if (!root) return effects;
    const visit = n => {
      if (ts.isCallExpression(n) || ts.isNewExpression(n) || ts.isTaggedTemplateExpression(n)) {
        for (const [cat, sink, confidence, mode] of classify(n, scope)) {
          const e = { category: cat, sink, confidence, kind: effectKind(cat, sink, n, scope),
            file: scope.info.rel, line: line(scope.info.sf, n), path: [] };
          if (cat === "write") e.mode = writeMode(sink, n, scope, mode);
          if (cat === "network") e.world = networkWorld(n, scope);
          effects.push(e);
        }
        if (!ts.isTaggedTemplateExpression(n) && depth < this.k) {
          const q = scope.qualify(n.expression);
          if (q && typeof q === "object" && q.rel) {
            const target = q.name === "default" ? this.defaultExport(q.rel) : q.name;
            if (target) for (const e of this.functionEffects(q.rel, target, depth + 1))
              effects.push({ ...e, path: [`${q.rel}:${target}:${line(scope.info.sf, n)}`, ...e.path] });
          }
          // fn(i) where fn is a function value: a wrapper's parameter bound to an
          // inline function at its call site, or a local const holding one
          // name-based fallback (class hierarchy analysis): an untyped call whose name
          // is defined in at most MAX_BY_NAME places in the repo follows all of them
          if (!q && !(ts.isNewExpression(n))) {
            const callee = unwrap(n.expression);
            const name = ts.isPropertyAccessExpression(callee) ? callee.name.text : null;
            const cands = name && !GENERIC_NAMES.has(name) && name.length >= 4 && this.repo.byName.get(name);
            if (cands && cands.length <= MAX_BY_NAME) {
              for (const c of cands) for (const e of this.bodyEffects(c.node, new Scope(this.repo, c.info, c.node), depth + 1))
                effects.push({ ...e, via_name: true, path: [`${c.info.rel}:~${name}:${line(scope.info.sf, n)}`, ...e.path] });
            }
          }
          const inline = this.inlineFunction(n.expression, scope);
          if (inline) {
            const info = this.repo.bySf.get(inline.getSourceFile());
            if (info) for (const e of this.bodyEffects(inline, new Scope(this.repo, info, inline), depth + 1))
              effects.push({ ...e, path: [`${info.rel}:<fn>:${line(scope.info.sf, n)}`, ...e.path] });
          }
          // an inline callback passed to a repo function is analysed where it is written
        }
      }
      ts.forEachChild(n, visit);
    };
    visit(root);
    return effects;
  }

  // a raw (low-level) tool's code: its branch in a dispatcher, or in a function the
  // dispatcher hands the tool name to; otherwise the whole dispatcher, marked shared
  // (every tool it serves gets all its effects: an over-approximation)
  rawEntry(t, dispatchers) {
    const fx = (stmts, scope) => stmts.flatMap(s => this.bodyEffects(s, scope, 0));
    const withBranch = dispatchers.find(d => d.map.has(t.tool));
    if (withBranch) {
      const scope = new Scope(this.repo, withBranch.info, withBranch.fn);
      return { entry: `call_tool[${t.tool}]`, shared: false, effects: fx([...withBranch.prelude, ...withBranch.map.get(t.tool)], scope) };
    }
    const sameFile = dispatchers.filter(d => d.info.rel === t.file);
    const d = sameFile.length === 1 ? sameFile[0] : dispatchers.length === 1 ? dispatchers[0] : null;
    if (!d) return null;
    const scope = new Scope(this.repo, d.info, d.fn);
    // delegation: workspaceTool(root, mode, request.params.name, args) with a switch inside
    for (const st of d.prelude) {
      let found = null;
      const visit = n => {
        if (!found && ts.isCallExpression(n) && n.arguments.some(a => /(^|\.)(name|toolName)$/.test(unwrap(a).getText(d.info.sf)))) {
          const q = scope.qualify(n.expression);
          const info = q && q.rel && this.repo.files.get(q.rel);
          const fn = info && info.functions.get(q.name);
          if (fn) { const b = this.branches(fn, info); if (b.map.has(t.tool)) found = { info, fn, b }; }
        }
        ts.forEachChild(n, visit);
      };
      visit(st);
      if (found) return { entry: `${found.info.rel}:${t.tool}`, shared: false,
        effects: fx(found.b.map.get(t.tool), new Scope(this.repo, found.info, found.fn)) };
    }
    return { entry: "call_tool[*]", shared: true, effects: fx(d.prelude, scope) };
  }

  inlineFunction(expr, scope) {
    const e = unwrap(expr);
    if (!e || !ts.isIdentifier(e)) return null;
    const v = (scope.params && scope.params.get(e.text)) || null;
    const target = v && unwrap(v);
    return target && (ts.isArrowFunction(target) || ts.isFunctionExpression(target)) ? target : null;
  }

  defaultExport(rel) {
    const info = this.repo.files.get(rel);
    for (const st of info.sf.statements) {
      if (ts.isFunctionDeclaration(st) && st.name && st.modifiers && st.modifiers.some(m => m.kind === ts.SyntaxKind.DefaultKeyword)) return st.name.text;
      if (ts.isExportAssignment(st) && ts.isIdentifier(st.expression)) return st.expression.text;
    }
    return null;
  }

  // low-level servers: setRequestHandler(CallToolRequestSchema, async (req) => { switch (name) { case "x": ... } })
  dispatchers() {
    const out = [];
    for (const info of this.repo.files.values()) {
      const visit = n => {
        if (ts.isCallExpression(n) && A.calleeName(n) === "setRequestHandler" && n.arguments.length >= 2 &&
          /CallTool/.test(n.arguments[0].getText(info.sf))) {
          let fn = unwrap(n.arguments[1]), fnInfo = info;
          if (ts.isIdentifier(fn)) {  // setRequestHandler(CallToolRequestSchema, handleCall)
            const q = new Scope(this.repo, info, null).qualify(fn);
            const target = q && q.rel && this.repo.files.get(q.rel).functions.get(q.name);
            if (target) { fn = target; fnInfo = this.repo.files.get(q.rel); }
          }
          if (isFn(fn) && fn.body) out.push({ info: fnInfo, fn, ...this.branches(fn, fnInfo) });
        }
        // hand-written JSON-RPC: switch (request.method) { case "tools/call": ... }
        if (ts.isCaseClause(n) && this.repo.ctx(info).literal(n.expression) === "tools/call") {
          let fn = n; while (fn && !isFn(fn)) fn = fn.parent;
          out.push({ info, fn, map: new Map(), prelude: [...n.statements] });
        }
        ts.forEachChild(n, visit);
      };
      visit(info.sf);
    }
    return out;
  }

  branches(fn, info) {
    const ctx = this.repo.ctx(info), map = new Map(), prelude = [];
    const isName = e => /(^|\.)(name|toolName|tool)$/.test(unwrap(e).getText(info.sf));
    const walk = stmts => {
      for (const st of stmts) {
        if (ts.isSwitchStatement(st) && isName(st.expression)) {
          let pending = [];
          for (const c of st.caseBlock.clauses) {
            if (ts.isCaseClause(c)) { const v = ctx.literal(c.expression); if (typeof v === "string") pending.push(v); }
            if (c.statements.length) { for (const name of pending) map.set(name, c.statements); pending = []; }
          }
        } else if (ts.isIfStatement(st) && ts.isBinaryExpression(st.expression) &&
          [ts.SyntaxKind.EqualsEqualsEqualsToken, ts.SyntaxKind.EqualsEqualsToken].includes(st.expression.operatorToken.kind) && isName(st.expression.left)) {
          const v = ctx.literal(st.expression.right);
          if (typeof v === "string") map.set(v, [st.thenStatement]);
          if (st.elseStatement) walk([st.elseStatement]);
        } else if (ts.isTryStatement(st)) { walk(st.tryBlock.statements); }
        else if (ts.isBlock(st)) { walk(st.statements); }
        else prelude.push(st);
      }
    };
    walk(ts.isBlock(fn.body) ? fn.body.statements : [fn.body]);
    return { map, prelude };
  }

  analyze({ mcpOnly = false } = {}) {
    if (mcpOnly && !A.usesMcp(this.repo.parsed)) return [];
    const tools = A.parseRepo(this.repo.root, { parsed: this.repo.parsed });
    let dispatchers = null;
    for (const t of tools) {
      const { handler, ctx, params } = t._ast;
      const info = this.repo.files.get(t.file);
      let effects = [], entry = null;
      const h = handler && unwrap(handler);
      if (h && isFn(h)) {
        entry = `${t.file}:${line(info.sf, h)}`;
        effects = this.bodyEffects(h, new Scope(this.repo, info, h, params), 0);
      } else if (h && ts.isCallExpression(h)) {
        // higher-order handler: safe((input) => search(site, input)) -- the wrapper
        // function and the inline function passed to it are both reachable
        entry = `${t.file}:${line(info.sf, h)}`;
        const outer = (() => { for (let n = h.parent; n; n = n.parent) if (isFn(n)) return n; return null; })();
        effects = this.bodyEffects(h, new Scope(this.repo, info, outer, params), 0);
      } else if (h && (ts.isIdentifier(h) || ts.isPropertyAccessExpression(h))) {
        const q = new Scope(this.repo, info, null, params).qualify(h);
        if (q && typeof q === "object" && q.rel) {
          entry = `${q.rel}:${q.name}`;
          effects = this.functionEffects(q.rel, q.name, 0);
        } else if (q && typeof q === "object" && q.relModule) entry = null;
      } else if (t.style === "raw") {
        dispatchers = dispatchers || this.dispatchers();
        const r = this.rawEntry(t, dispatchers);
        if (r) { entry = r.entry; effects = r.effects; t.entry_shared = r.shared; }
      }
      t.entry = entry;
      t.effects = effects;
      [t.inconsistencies, t.review] = inconsistencies(t.annotations, effects);
      if (t.entry_shared) {
        // the whole dispatcher was taken for this tool: its effects may belong to
        // other tools, so findings are only candidates for review
        t.review.push(...t.inconsistencies.map(v => ({ ...v, rule: `shared_entry:${v.rule}` })));
        t.inconsistencies = [];
      }
      t.inconsistencies_lenient = t.inconsistencies.filter(v => !LENIENT_DROP.has(v.witness.kind));
    }
    return tools;
  }
}

// same rules as detector/python/effects.py (MCP 2025-06-18; review v1.1)
function inconsistencies(ann, effects) {
  const by = c => effects.filter(e => e.category === c);
  const found = [], review = [];
  if (ann.readOnlyHint === "true")
    for (const c of ["delete", "execute", "write"]) for (const e of by(c)) found.push({ rule: `readOnly_but_${c}`, witness: e });
  if (ann.destructiveHint === "false" && ann.readOnlyHint !== "true") {
    for (const e of by("delete")) found.push({ rule: "nondestructive_but_delete", witness: e });
    for (const e of by("write")) if (["modifying", "overwrite"].includes(e.mode)) found.push({ rule: `nondestructive_but_${e.mode}`, witness: e });
  }
  if (ann.openWorldHint === "false")
    for (const e of by("network")) (e.world === "open" ? found : review).push({ rule: e.world === "open" ? "closedworld_but_open_network" : "closedworld_network_unknown_world", witness: e });
  return [found, review];
}

module.exports = { Repo, Analyzer, inconsistencies };

if (require.main === module) {
  const argv = process.argv.slice(2);
  const opt = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };
  const repoDir = argv.find((a, i) => !a.startsWith("--") && !["--k", "--out"].includes(argv[i - 1]));
  const tools = new Analyzer(new Repo(repoDir), Number(opt("--k", 3))).analyze({ mcpOnly: !argv.includes("--all") });
  const outFile = opt("--out");
  const out = outFile ? fs.createWriteStream(outFile) : process.stdout;
  for (const t of tools) out.write(JSON.stringify(t) + "\n");
  if (outFile) out.end();
}
