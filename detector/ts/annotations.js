// A(t) for TypeScript / JavaScript: find MCP tool definitions and their
// annotations statically, with the TypeScript compiler's parser.
//
// Tool definition styles handled (output matches detector/python/annotations.py):
//   registerTool  server.registerTool(name, {description, annotations, ...}, handler)
//   tool          server.tool(name, [description], [schema], [annotations], handler)  (older SDK API)
//   addTool       server.addTool({name, description, annotations, execute})           (FastMCP for TS)
//   raw           an object literal {name, inputSchema, annotations, ...}             (low-level ListTools)
//
// Names are resolved through consts (module level, inside functions, and
// exported from other files of the repo), enum members, `as const`, spreads and
// shorthand properties. Each hint is "true" / "false" / "omitted" / "unresolved".
//
// Usage: node annotations.js REPO_DIR [OUT.jsonl]
const fs = require("fs");
const path = require("path");
const ts = require("typescript");

const HINTS = ["readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"];
const SKIP_DIRS = new Set([".git", "node_modules", "dist", "build", "out", "coverage", ".next", "vendor"]);
const EXTS = new Set([".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"]);
const AMBIGUOUS = Symbol("ambiguous");

function isTest(rel) {
  const parts = rel.split("/");
  const name = parts[parts.length - 1];
  return parts.slice(0, -1).some(p => ["test", "tests", "__tests__", "__mocks__", "e2e"].includes(p)) ||
    /\.(test|spec)\.[cm]?[jt]sx?$/.test(name) || name.endsWith(".d.ts");
}

function sourceFiles(root) {
  const out = [];
  const walk = dir => {
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) { if (!SKIP_DIRS.has(e.name)) walk(full); }
      else if (EXTS.has(path.extname(e.name))) {
        const rel = path.relative(root, full).split(path.sep).join("/");
        if (!isTest(rel)) out.push({ full, rel });
      }
    }
  };
  walk(root);
  return out;
}

function parse(full) {
  let text;
  try {
    const st = fs.statSync(full);
    if (st.size > 2_000_000) return null;  // generated bundles
    text = fs.readFileSync(full, "utf8");
  } catch { return null; }
  const kind = /\.[cm]?jsx?$/.test(full) ? ts.ScriptKind.JSX : full.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  return ts.createSourceFile(full, text, ts.ScriptTarget.Latest, true, kind);
}

function bind(table, key, value) {
  if (!table.has(key)) table.set(key, value);
  else if (table.get(key) !== AMBIGUOUS && table.get(key) !== value) table.set(key, AMBIGUOUS);
}

// const / let / var bindings and enum members of one file: [module level, anywhere]
function bindings(sf) {
  const top = new Map(), all = new Map();
  const visit = (node, depth) => {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
      bind(all, node.name.text, node.initializer);
      if (depth === 0) bind(top, node.name.text, node.initializer);
    } else if (ts.isEnumDeclaration(node)) {
      for (const m of node.members) {
        if (m.initializer && (ts.isIdentifier(m.name) || ts.isStringLiteral(m.name))) {
          bind(top, `${node.name.text}.${m.name.text}`, m.initializer);
          bind(all, `${node.name.text}.${m.name.text}`, m.initializer);
        }
      }
    }
    const fn = ts.isFunctionLike(node);
    ts.forEachChild(node, c => visit(c, fn ? depth + 1 : depth));
  };
  ts.forEachChild(sf, c => visit(c, 0));
  return { top, all };
}

function unwrap(node) {
  while (node && (ts.isAsExpression(node) || ts.isParenthesizedExpression(node) || ts.isSatisfiesExpression?.(node)
    || ts.isTypeAssertionExpression(node) || ts.isNonNullExpression(node))) node = node.expression;
  return node;
}

function dotted(node) {
  node = unwrap(node);
  if (ts.isIdentifier(node)) return node.text;
  if (ts.isPropertyAccessExpression(node)) { const b = dotted(node.expression); return b ? `${b}.${node.name.text}` : null; }
  return null;
}

class FileCtx {
  constructor(sf, repoConsts) {
    this.sf = sf;
    const { top, all } = bindings(sf);
    this.top = top; this.all = all; this.repo = repoConsts;
    this.imported = new Set();
    for (const st of sf.statements) {
      if (ts.isImportDeclaration(st) && st.importClause) {
        const c = st.importClause;
        if (c.name) this.imported.add(c.name.text);
        if (c.namedBindings && ts.isNamedImports(c.namedBindings)) c.namedBindings.elements.forEach(e => this.imported.add(e.name.text));
      }
    }
  }

  lookup(key) {
    if (this.params && this.params.has(key)) return this.params.get(key);  // wrapper call being evaluated
    for (const t of [this.top, this.all]) if (t.has(key)) return t.get(key);
    if (this.repo.has(key)) return this.repo.get(key);  // exported from another file
    return null;
  }

  // follow names to the expression they stand for; a.b on an object literal reads property b
  resolve(node, depth = 0) {
    node = unwrap(node);
    if (!node || depth > 6) return node;
    if (ts.isIdentifier(node) || ts.isPropertyAccessExpression(node)) {
      const key = dotted(node);
      if (key) {
        const t = this.lookup(key);
        if (t && t !== AMBIGUOUS) return this.resolve(t, depth + 1);
      }
      if (ts.isPropertyAccessExpression(node)) {
        const base = this.resolve(node.expression, depth + 1);
        if (base && ts.isObjectLiteralExpression(base)) {
          const v = this.prop(base, node.name.text);
          if (v) return this.resolve(v, depth + 1);
        }
      }
    }
    return node;
  }

  literal(node) {
    node = this.resolve(node);
    if (!node) return undefined;
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
    if (node.kind === ts.SyntaxKind.TrueKeyword) return true;
    if (node.kind === ts.SyntaxKind.FalseKeyword) return false;
    if (ts.isNumericLiteral(node)) return Number(node.text);
    if (ts.isTemplateExpression(node)) return node.getText(this.sf).slice(1, -1);  // keeps ${...} visible
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
      const l = this.literal(node.left), r = this.literal(node.right);
      if (typeof l === "string" && typeof r === "string") return l + r;
    }
    return undefined;
  }

  // properties of an object literal, with spreads and shorthands followed: Map name -> node
  props(obj, depth = 0) {
    const out = new Map();
    if (!obj || !ts.isObjectLiteralExpression(obj) || depth > 4) return out;
    for (const p of obj.properties) {
      if (ts.isSpreadAssignment(p)) {
        for (const [k, v] of this.props(this.resolve(p.expression), depth + 1)) out.set(k, v);
      } else if (ts.isPropertyAssignment(p)) {
        const k = ts.isIdentifier(p.name) || ts.isStringLiteral(p.name) ? p.name.text : null;
        if (k) out.set(k, p.initializer);
      } else if (ts.isShorthandPropertyAssignment(p)) {
        out.set(p.name.text, p.name);
      } else if (ts.isMethodDeclaration(p) && ts.isIdentifier(p.name)) {
        out.set(p.name.text, p);
      }
    }
    return out;
  }

  prop(obj, name) { return this.props(obj).get(name); }

  annotations(node) {
    const states = Object.fromEntries(HINTS.map(h => [h, "omitted"]));
    if (!node) return [states, "none"];
    const obj = this.resolve(node);
    if (!obj || obj.kind === ts.SyntaxKind.UndefinedKeyword || (ts.isIdentifier(obj) && obj.text === "undefined")) return [states, "none"];
    if (!ts.isObjectLiteralExpression(obj)) return [Object.fromEntries(HINTS.map(h => [h, "unresolved"])), "unresolved"];
    for (const [k, v] of this.props(obj)) {
      if (k in states) {
        const val = this.literal(v);
        states[k] = val === true ? "true" : val === false ? "false" : "unresolved";
      }
    }
    return [states, "object"];
  }

  hasHints(node) {
    const obj = this.resolve(node);
    return !!obj && ts.isObjectLiteralExpression(obj) && [...this.props(obj).keys()].some(k => HINTS.includes(k));
  }
}

function line(sf, node) { return sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1; }

function handlerInfo(ctx, node) {
  if (!node) return [null, null];
  node = unwrap(node);
  const sf = ctx.sf;
  if (ts.isIdentifier(node) || ts.isPropertyAccessExpression(node)) {
    const name = dotted(node);
    const target = ctx.lookup(name);
    return [name, target && target !== AMBIGUOUS ? line(target.getSourceFile(), target) : null];
  }
  if (ts.isMethodDeclaration(node) && node.name && ts.isIdentifier(node.name)) return [node.name.text, line(sf, node)];
  if (ts.isArrowFunction(node) || ts.isFunctionExpression(node) || ts.isMethodDeclaration(node)) return ["<inline>", line(sf, node)];
  return [null, null];
}

function calleeName(call) {
  const e = unwrap(call.expression);
  return ts.isPropertyAccessExpression(e) ? e.name.text : ts.isIdentifier(e) ? e.text : null;
}

// import / require specifiers of a file that look like an MCP library
const MCP_SPEC = /modelcontextprotocol|(^|[/@-])mcp([/-]|$)|fastmcp|xmcp|mcp-nest|mcp-framework|mcp-use/i;
function mcpImports(sf) {
  const found = new Set();
  const visit = node => {
    let spec = null;
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) spec = node.moduleSpecifier.text;
    else if (ts.isCallExpression(node) && node.arguments.length === 1 && ts.isStringLiteral(node.arguments[0]) &&
      (node.expression.kind === ts.SyntaxKind.ImportKeyword || (ts.isIdentifier(node.expression) && node.expression.text === "require"))) spec = node.arguments[0].text;
    if (spec && MCP_SPEC.test(spec)) found.add(spec);
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return [...found];
}

// the function a node sits in, and the name it can be called by
function enclosingFunction(node) {
  for (let n = node.parent; n; n = n.parent) {
    if (ts.isFunctionDeclaration(n) && n.name) return { fn: n, name: n.name.text };
    if ((ts.isArrowFunction(n) || ts.isFunctionExpression(n)) && ts.isVariableDeclaration(n.parent) && ts.isIdentifier(n.parent.name))
      return { fn: n, name: n.parent.name.text };
    if (ts.isFunctionLike(n)) return null;  // an anonymous callback: stop
  }
  return null;
}

function isParamOf(fn, expr) {
  expr = unwrap(expr);
  return ts.isIdentifier(expr) && fn.parameters.some(p => ts.isIdentifier(p.name) && p.name.text === expr.text);
}

function parseFile(sf, rel, repoConsts) {
  const ctx = new FileCtx(sf, repoConsts);
  const imports = mcpImports(sf);
  const tools = [], used = new Set();
  const rec = (node, style, name, desc, ann, handler) => {
    const [states, kind] = ctx.annotations(ann);
    const [h, hl] = handlerInfo(ctx, handler);
    const record = { file: rel, line: line(sf, node), style, tool: name ?? null, description: desc ?? null,
      annotations: states, annotations_kind: kind, handler: h, handler_line: hl, mcp_imports: imports };
    // for effects.js, not serialized: the handler node, its file context, and a
    // wrapper call's parameter bindings
    Object.defineProperty(record, "_ast", { value: { handler: handler && unwrap(handler), ctx, params: ctx.params && new Map(ctx.params), node } });
    tools.push(record);
  };

  // one registration call -> [style, nameNode, descNode, annotationsNode, handlerNode] or null
  const registration = node => {
    const callee = calleeName(node), args = node.arguments;
    const isMember = ts.isPropertyAccessExpression(unwrap(node.expression));
    const fromConfig = (style, nameNode, configNode, handlerNode) => {
      const config = ctx.resolve(configNode);
      const obj = config && ts.isObjectLiteralExpression(config) ? config : null;
      if (obj) used.add(obj);
      return [style, nameNode, obj && ctx.prop(obj, "description"), obj && ctx.prop(obj, "annotations"), handlerNode];
    };
    const fromObject = (style, objNode) => {
      const obj = ctx.resolve(objNode);
      if (!obj || !ts.isObjectLiteralExpression(obj) || !ctx.prop(obj, "name")) return null;
      used.add(obj);
      return [style, ctx.prop(obj, "name"), ctx.prop(obj, "description"), ctx.prop(obj, "annotations"),
        ctx.prop(obj, "execute") || ctx.prop(obj, "handler")];
    };
    if (callee === "registerTool" && isMember && args.length >= 2) return fromConfig("registerTool", args[0], args[1], args[2]);
    if (callee === "registerTool" && isMember && args.length === 1) return fromObject("registerTool", args[0]);
    if (callee === "registerAppTool" && args.length >= 3) return fromConfig("registerAppTool", args[1], args[2], args[3]);
    if (callee === "tool" && isMember && args.length >= 2) {
      const rest = args.slice(1, -1);
      return ["tool", args[0], rest.find(a => typeof ctx.literal(a) === "string"), rest.find(a => ctx.hasHints(a)), args[args.length - 1]];
    }
    if (callee === "addTool" && isMember && args.length >= 1) return fromObject("addTool", args[0]);
    return null;
  };

  const emit = (node, r) => rec(node, r[0], ctx.literal(r[1]), ctx.literal(r[2]), r[3], r[4]);

  // wrappers: `const add = (name, desc, schema, read, fn) => server.registerTool(name, ...)`
  // each call add("x", ...) is a tool; evaluate the registration with the wrapper's
  // parameters bound to that call's arguments
  const wrapperCalls = (node, r) => {
    const enc = enclosingFunction(node);
    if (!enc || !isParamOf(enc.fn, r[1])) return false;
    const calls = [];
    const find = n => {
      if (ts.isCallExpression(n) && ts.isIdentifier(unwrap(n.expression)) && unwrap(n.expression).text === enc.name) calls.push(n);
      ts.forEachChild(n, find);
    };
    find(sf);
    if (!calls.length) return false;
    for (const call of calls) {
      ctx.params = new Map();
      enc.fn.parameters.forEach((p, i) => { if (ts.isIdentifier(p.name) && call.arguments[i]) ctx.params.set(p.name.text, call.arguments[i]); });
      const rr = registration(node);
      emit(call, [rr[0] + "_via_wrapper", ...rr.slice(1)]);
      ctx.params = null;
    }
    return true;
  };

  const visit = node => {
    if (ts.isCallExpression(node)) {
      const r = registration(node);
      if (r) {
        if (typeof ctx.literal(r[1]) === "string") emit(node, r);
        // name not a literal: a wrapper's parameter, or unknown (kept, except for
        // the generic `.tool(...)` which other libraries also use)
        else if (!wrapperCalls(node, r) && r[0] !== "tool") emit(node, r);
      }
    }
    // decorators: @McpTool({...}) / @Tool({...}) on a class method
    if ((ts.isMethodDeclaration(node) || ts.isPropertyDeclaration(node)) && ts.canHaveDecorators(node)) {
      for (const d of ts.getDecorators(node) || []) {
        const call = d.expression;
        if (ts.isCallExpression(call) && /tool$/i.test(calleeName(call) || "") && call.arguments.length) {
          const obj = ctx.resolve(call.arguments[0]);
          if (obj && ts.isObjectLiteralExpression(obj) && ctx.prop(obj, "name")) {
            used.add(obj);
            rec(node, "decorator", ctx.literal(ctx.prop(obj, "name")), ctx.literal(ctx.prop(obj, "description")),
              ctx.prop(obj, "annotations"), node);
          }
        }
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);

  // raw tool objects: {name, inputSchema, ...} not already part of a call above
  const raw = node => {
    if (ts.isObjectLiteralExpression(node) && !used.has(node)) {
      const p = ctx.props(node);
      if (p.has("name") && p.has("inputSchema")) {
        rec(node, "raw", ctx.literal(p.get("name")), ctx.literal(p.get("description")), p.get("annotations"),
          p.get("handler") || p.get("execute"));
      }
    }
    ts.forEachChild(node, raw);
  };
  raw(sf);
  return tools;
}

// module-level consts across the repo, so imported names resolve (ambiguous names dropped)
function repoConstants(parsed) {
  const table = new Map();
  for (const { sf } of parsed) for (const [k, v] of bindings(sf).top) bind(table, k, v);
  for (const [k, v] of table) if (v === AMBIGUOUS) table.delete(k);
  return table;
}

// mcpOnly: return nothing for repos where no file imports an MCP library (the
// same annotation names are used by non-MCP agent frameworks). Checked per repo,
// not per file: tools are often defined in a file that never imports the SDK.
function parseRepo(root, { mcpOnly = false, parsed = null } = {}) {
  parsed = parsed || parseSources(root);
  if (mcpOnly && !usesMcp(parsed)) return [];
  const consts = repoConstants(parsed);
  return parsed.flatMap(f => parseFile(f.sf, f.rel, consts));
}

const parseSources = root => sourceFiles(root).map(f => ({ ...f, sf: parse(f.full) })).filter(f => f.sf);

// Large repos: parse only the files that define tools (or name an annotation)
// and the repo files they import, transitively up to maxDepth. Effects reached
// only through files nothing imports from there are missed; small repos are
// parsed whole (effects.js decides the threshold).
const SEED_RE = /readOnlyHint|destructiveHint|openWorldHint|idempotentHint|registerTool|setRequestHandler|addTool|registerAppTool|McpTool/;
function parseSourcesLazy(root, maxDepth = 6) {
  const files = sourceFiles(root);
  const byRel = new Map(files.map(f => [f.rel, f]));
  const resolve = (fromRel, spec) => {
    if (!spec.startsWith(".")) return null;
    const base = path.posix.normalize(path.posix.join(path.posix.dirname(fromRel), spec)).replace(/\.(m|c)?js$/, "");
    for (const c of [base, ...[".ts", ".tsx", ".mts", ".cts", ".js", ".mjs", ".cjs", ".jsx"].flatMap(e => [base + e, `${base}/index${e}`])])
      if (byRel.has(c)) return c;
    return null;
  };
  const seen = new Map();
  let frontier = files.filter(f => { try { return SEED_RE.test(fs.readFileSync(f.full, "utf8")); } catch { return false; } });
  for (let depth = 0; depth <= maxDepth && frontier.length; depth++) {
    const next = [];
    for (const f of frontier) {
      if (seen.has(f.rel)) continue;
      const sf = parse(f.full);
      seen.set(f.rel, sf);
      if (!sf) continue;
      const visit = n => {
        let spec = null;
        if ((ts.isImportDeclaration(n) || ts.isExportDeclaration(n)) && n.moduleSpecifier && ts.isStringLiteral(n.moduleSpecifier)) spec = n.moduleSpecifier.text;
        else if (ts.isCallExpression(n) && n.arguments.length === 1 && ts.isStringLiteral(n.arguments[0]) &&
          (n.expression.kind === ts.SyntaxKind.ImportKeyword || (ts.isIdentifier(n.expression) && n.expression.text === "require"))) spec = n.arguments[0].text;
        const rel = spec && resolve(f.rel, spec);
        if (rel && !seen.has(rel)) next.push(byRel.get(rel));
        ts.forEachChild(n, visit);
      };
      visit(sf);
    }
    frontier = next;
  }
  return files.filter(f => seen.get(f.rel)).map(f => ({ ...f, sf: seen.get(f.rel) }));
}
const usesMcp = parsed => parsed.some(f => mcpImports(f.sf).length);

module.exports = { parseRepo, parseSources, parseSourcesLazy, sourceFiles, usesMcp, repoConstants, HINTS, FileCtx, unwrap, dotted, calleeName, line, AMBIGUOUS };

// CLI: node annotations.js REPO [OUT.jsonl] [--all]   (--all keeps non-MCP repos)
if (require.main === module) {
  const keepAll = process.argv.includes("--all");
  const [repoDir, outFile] = process.argv.slice(2).filter(a => a !== "--all");
  const tools = parseRepo(repoDir, { mcpOnly: !keepAll });
  const out = outFile ? fs.createWriteStream(outFile) : process.stdout;
  for (const t of tools) out.write(JSON.stringify(t) + "\n");
  if (outFile) out.end();
}
