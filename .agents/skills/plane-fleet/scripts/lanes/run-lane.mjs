#!/usr/bin/env node
// run-lane — run one fleet role on a CLI executor (codex, opencode, or Claude Code on another
// provider such as claude-ollama) and write
// <out>/result.json. Launched by the PM with Bash run_in_background, so the PM is
// notified when it exits. Never commits by itself. Never prints secrets.
//
// Usage:
//   run-lane.sh <codex|opencode|claude-ollama> --model <m> --role <role> --ticket <ID> --cwd <dir>
//               --brief <file> --out <dir> [--sandbox restricted|full|read-only]
//               [--timeout <sec>] [--effort <level>] [--dry-run]
//               [--ignore-budget]
//   run-lane.sh models [codex|opencode|claude-ollama]
//   run-lane.sh pick|budget|log|stats|report|apply|seed ...   -> fleetctl.py (selection, pacer, log, report)
//   After a lane: run-lane.sh log add --from-result <out>/result.json --outcome O [--kind K] takes
//   ticket, role, executor, model, durationMs and usage from result.json.
//
// Exit codes: 0 completed · 2 usage error (no result.json) · 75 deferred (no budget; see
// resumeAt) · 124 timeout · 127 executor missing · 130 aborted · otherwise the executor's
// own non-zero exit (or 1).
// Registry: references/executors.json, overridden by
// <repo>/.plane/config.json -> fleet.executors. See executors.md.

import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync, createWriteStream, appendFileSync, rmSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { StringDecoder } from "node:string_decoder";
import { fileURLToPath } from "node:url";
import { realpathSync } from "node:fs";

const HOME = homedir();
// Everything resolves from this file's real location: <fleet root>/scripts/lanes/run-lane.mjs.
const FLEET_ROOT = resolve(dirname(realpathSync(fileURLToPath(import.meta.url))), "../..");
const STATE_HOME = process.env.PLANE_FLEET_HOME || join(HOME, ".config/plane-fleet");
const REGISTRY = join(FLEET_ROOT, "references/executors.json");
const ADAPTER = join(FLEET_ROOT, "references/non-claude-adapter.md");
const STANDING = join(FLEET_ROOT, "references/standing-brief.md");
const FLEETCTL = join(FLEET_ROOT, "scripts/lanes/fleetctl.py");
function fleetctl(args) {
  const r = spawnSync("python3", [FLEETCTL, ...args], { encoding: "utf8", timeout: 30000 });
  return { code: r.status, out: (r.stdout || "").trim(), err: (r.stderr || "").trim() };
}

// ~ and $HOME expand; {fleet_root} is this plugin's skill folder; {state_home} is PLANE_FLEET_HOME.
const expand = (p) => (typeof p === "string"
  ? p.replace(/\{fleet_root\}/g, FLEET_ROOT).replace(/\{state_home\}/g, STATE_HOME)
     .replace(/^~(?=\/|$)/, HOME).replace(/\$HOME/g, HOME)
  : p);
function usage(msg) {
  process.stderr.write(`run-lane: ${msg}\nsee the header of ${process.argv[1]} or executors.md\n`);
  process.exit(2);
}

// ---------- registry ----------
function deepMerge(base, over) {
  if (over === null || typeof over !== "object" || Array.isArray(over)) return over;
  const out = { ...(base && typeof base === "object" && !Array.isArray(base) ? base : {}) };
  for (const [k, v] of Object.entries(over)) out[k] = deepMerge(out[k], v);
  return out;
}
function gitTop(dir) {
  const r = spawnSync("git", ["-C", dir, "rev-parse", "--show-toplevel"], { encoding: "utf8" });
  return r.status === 0 ? r.stdout.trim() : null;
}
function projectOf(cwd) {
  const r = spawnSync("git", ["-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"], { encoding: "utf8" });
  if (r.status === 0 && r.stdout.trim()) return dirname(r.stdout.trim().replace(/\/$/, "")).split("/").pop();
  const top = gitTop(cwd);
  return top ? top.split("/").pop() : null;
}
function loadRegistry(cwd) {
  if (!existsSync(REGISTRY)) return { registry: null, source: "missing" };
  let reg = JSON.parse(readFileSync(REGISTRY, "utf8"));
  let source = REGISTRY;
  // Same layers as fleetctl.py: user override, then its projects.<name>, then the repo's config.
  const userPath = expand(reg.log?.user_override || "{state_home}/executors.json");
  if (existsSync(userPath)) {
    try {
      const user = JSON.parse(readFileSync(userPath, "utf8"));
      const { projects, ...rest } = user;
      reg = deepMerge(reg, rest); source += ` + ${userPath}`;
      const proj = cwd ? projects?.[projectOf(cwd)] : null;
      if (proj) { reg = deepMerge(reg, proj); source += ` projects.${projectOf(cwd)}`; }
    } catch { /* ignore a broken user override */ }
  }
  const top = cwd ? gitTop(cwd) : null;
  // A worktree's top level is the worktree; .plane/config.json is tracked, so it is there too.
  const cfgPath = top ? join(top, ".plane/config.json") : null;
  if (cfgPath && existsSync(cfgPath)) {
    try {
      const over = JSON.parse(readFileSync(cfgPath, "utf8"))?.fleet?.executors;
      if (over && typeof over === "object") { reg = deepMerge(reg, over); source += ` + ${cfgPath} fleet.executors`; }
    } catch { /* a broken project config must not break the shared defaults */ }
  }
  return { registry: reg, source };
}

// ---------- args ----------
function parseArgs(argv) {
  const opts = { positional: [] };
  const flags = new Set(["dry-run", "ignore-budget"]);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith("--")) { opts.positional.push(a); continue; }
    const key = a.slice(2);
    if (flags.has(key)) { opts[key] = true; continue; }
    const v = argv[++i];
    if (v === undefined || v.startsWith("--")) usage(`${a} needs a value`);
    opts[key] = v;
  }
  return opts;
}

// ---------- secrets: load only what the executor needs, never print ----------
function readEnvVar(file, name) {
  if (!existsSync(file)) return null;
  for (const line of readFileSync(file, "utf8").split("\n")) {
    const m = line.match(new RegExp(`^\\s*(?:export\\s+)?${name}\\s*=\\s*(.*)$`));
    if (m) return m[1].trim().replace(/^(['"])(.*)\1$/, "$2");
  }
  return null;
}

// ---------- git helpers (snapshot for result.json) ----------
function git(cwd, args) {
  const r = spawnSync("git", ["-C", cwd, ...args], { encoding: "utf8" });
  return r.status === 0 ? r.stdout : null;
}
const lines = (s) => (s == null ? null : s.split("\n").map((l) => l.trimEnd()).filter(Boolean));
function snapshot(cwd) {
  return {
    status: lines(git(cwd, ["status", "--porcelain"])),
    worktrees: lines(git(cwd, ["worktree", "list", "--porcelain"]))?.filter((l) => l.startsWith("worktree ")).map((l) => l.slice(9)) ?? null,
    branches: lines(git(cwd, ["for-each-ref", "--format=%(refname:short)", "refs/heads"])),
  };
}
// Worktrees and branches are repo-wide (shared git dir), so other live sessions show up too.
// Keep only entries that name this lane's ticket, e.g. PROJ-12 or proj-12.
const added = (before, after, ticket) => {
  if (!before || !after) return null;
  const t = String(ticket || "").toLowerCase();
  return after.filter((x) => !before.includes(x) && (!t || x.toLowerCase().includes(t)));
};

// ---------- prompt ----------
function composePrompt(o, role) {
  const parts = [];
  parts.push(`# Fleet lane: ${o.role} for ${o.ticket}`);
  parts.push(`Executor: ${o.executor} · model: ${o.model} · sandbox: ${o.sandbox} · working dir: ${o.cwd}`);
  parts.push("");
  // A claude-cli lane is Claude Code itself: skills, hooks and CLAUDE.md work natively, no adapter.
  if (o.kind !== "claude-cli") parts.push(`FIRST read ${ADAPTER} and follow it. It explains how to run a skill written for Claude Code from ${o.executor}.`);
  if (role?.skill) {
    parts.push(`Your role skill: read ${resolve(FLEET_ROOT, expand(role.skill))} in full and follow it exactly, as the ${o.role}. Paths like references/... and scripts/... in it are relative to ${FLEET_ROOT}. Where it says to invoke another skill, read that skill's SKILL.md (fleet roles are under ${FLEET_ROOT}/roles/) and follow it.`);
  }
  if (role?.standing_brief) {
    parts.push(`FIRST read ${STANDING} and follow it exactly; it is part of this brief.`);
  }
  if (o.sandbox === "read-only") {
    parts.push("This lane is READ-ONLY. Do not edit files, commit, push, or write to Plane. Report only.");
  }
  parts.push("");
  parts.push("## Brief from the PM");
  parts.push("");
  parts.push(readFileSync(o.brief, "utf8").trim());
  parts.push("");
  parts.push("## Final message");
  parts.push("Your final message is ONLY the report line or block your role skill specifies (or the brief asks for). Nothing before or after it.");
  return parts.join("\n") + "\n";
}

// ---------- argv per executor ----------
function codexArgv(o, exe, finalPath) {
  const argv = ["exec", "--json", "-o", finalPath, "-m", o.model, "-C", o.cwd];
  const prof = exe.sandbox_profiles?.[o.sandbox];
  if (!prof) usage(`codex has no sandbox profile "${o.sandbox}" (have: ${Object.keys(exe.sandbox_profiles || {}).join(", ")})`);
  argv.push(...prof.args);
  if (o.effort) argv.push("-c", `model_reasoning_effort="${o.effort}"`);
  for (const name of exe.disable_mcp || []) argv.push("-c", `mcp_servers.${name}.enabled=false`);
  // codex exec runs with approval_policy=never, and MCP calls need approval unless the
  // server says otherwise: without this every plane call fails ("requires approval").
  for (const name of exe.mcp_approve || []) argv.push("-c", `mcp_servers.${name}.default_tools_approval_mode="approve"`);
  // Non-secret per-lane overrides only (e.g. which binary). Values are JSON, which is valid
  // TOML for strings and string arrays. Never put credentials here: argv is visible in ps.
  for (const [name, fields] of Object.entries(exe.mcp_overrides || {})) {
    for (const [k, v] of Object.entries(fields)) argv.push("-c", `mcp_servers.${name}.${k}=${JSON.stringify(v)}`);
  }
  argv.push("-"); // prompt on stdin
  return argv;
}
function opencodeArgv(o, exe) {
  const model = o.model.includes("/") ? o.model : `${exe.provider}/${o.model}`;
  const agent = o.sandbox === "read-only" ? exe.agents?.["read-only"]?.args : exe.agents?.write?.args;
  if (!agent) usage(`opencode has no agent args for sandbox "${o.sandbox}"`);
  const argv = ["run", "--format", "json", "--model", model, "--dir", o.cwd, ...agent];
  // opencode calls reasoning effort a "variant"; the names are the provider's own.
  if (o.effort) argv.push("--variant", o.effort);
  return argv;
}

// Claude Code against another provider: the prompt goes on stdin, the provider comes from env.
function claudeCliArgv(o, exe, mcpPath) {
  const prof = exe.permission_profiles?.[o.sandbox];
  if (!prof) usage(`${o.executor} has no permission profile "${o.sandbox}" (have: ${Object.keys(exe.permission_profiles || {}).join(", ")})`);
  const argv = ["-p", "--output-format", "stream-json", "--verbose", "--model", o.model,
    "--no-session-persistence", "--add-dir", FLEET_ROOT, ...prof.args, "--strict-mcp-config"];
  if (mcpPath) argv.push("--mcp-config", mcpPath);
  if (o.effort) argv.push("--effort", o.effort);
  return argv;
}
// Copy the named MCP servers out of the user's Claude config into a 0600 file for this lane only.
function writeLaneMcp(exe, out) {
  const names = exe.mcp_servers || [];
  if (!names.length) return null;
  let src = {};
  try { src = JSON.parse(readFileSync(expand(exe.mcp_source || "~/.claude.json"), "utf8")).mcpServers || {}; } catch {}
  const servers = Object.fromEntries(names.filter((n) => src[n]).map((n) => [n, src[n]]));
  const path = join(out, "mcp.json");
  writeFileSync(path, JSON.stringify({ mcpServers: servers }), { mode: 0o600 });
  return { path, missing: names.filter((n) => !src[n]) };
}

// ---------- event parsing (best effort; the raw stream is always kept) ----------
function makeScanner(onEvent) {
  let buf = "";
  return (text) => {
    buf += text;
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (!line.startsWith("{")) continue;
      try { onEvent(JSON.parse(line)); } catch { /* not an event */ }
    }
  };
}

// ---------- run ----------
async function run(opts) {
  const executor = opts.positional[0];
  for (const k of ["model", "role", "ticket", "cwd", "brief", "out"]) if (!opts[k]) usage(`missing --${k}`);
  if (executor === "claude") usage("claude lanes are spawned with the Agent tool, not run-lane (team-pm §3)");
  const cwd = resolve(expand(opts.cwd));
  if (!existsSync(cwd)) usage(`--cwd ${cwd} does not exist`);
  const brief = resolve(expand(opts.brief));
  if (!existsSync(brief) || !readFileSync(brief, "utf8").trim()) usage(`--brief ${brief} is missing or empty`);
  const out = resolve(expand(opts.out));

  const { registry, source } = loadRegistry(cwd);
  if (!registry) usage(`registry ${REGISTRY} is missing: spawn the claude fallback instead`);
  const exe = registry.executors?.[executor];
  if (!exe) usage(`unknown executor "${executor}" (have: ${Object.keys(registry.executors || {}).join(", ")})`);
  if (exe.kind !== executor && !["codex", "opencode", "claude-cli"].includes(exe.kind)) usage(`executor kind ${exe.kind} is not runnable here`);
  const kind = exe.kind;
  const role = registry.roles?.[opts.role];
  if (!role) usage(`unknown role "${opts.role}" (have: ${Object.keys(registry.roles || {}).join(", ")})`);
  if (opts.role === "pm") usage("the PM never runs as a lane");
  const model = opts.model;
  const modelWarning = (exe.models || []).includes(model.replace(/^[^/]+\//, "")) ? null : `model "${model}" is not in the registry list for ${executor}; running it anyway`;
  const sandbox = opts.sandbox || role.sandbox || "read-only";
  const timeoutSec = Number(opts.timeout || role.timeout_sec || 3600);
  if (!Number.isFinite(timeoutSec) || timeoutSec <= 0) usage("--timeout must be a positive number of seconds");

  mkdirSync(out, { recursive: true });
  const o = { executor, kind, model, role: opts.role, ticket: opts.ticket, cwd, brief, sandbox, effort: opts.effort };
  const paths = {
    prompt: join(out, "prompt.md"), events: join(out, "events.jsonl"), stderr: join(out, "stderr.log"),
    final: join(out, "last-message.txt"), result: join(out, "result.json"), started: join(out, "started.json"),
  };
  writeFileSync(paths.prompt, composePrompt(o, role));

  const bin = exe.binary || kind;
  const laneMcp = kind === "claude-cli" ? writeLaneMcp(exe, out) : null;
  const argv = kind === "codex" ? codexArgv(o, exe, paths.final)
    : kind === "claude-cli" ? claudeCliArgv(o, exe, laneMcp?.path) : opencodeArgv(o, exe);
  const env = { ...process.env };
  // Credentials the executor's own config references as env vars ({env:NAME}): taken from the
  // environment, else from the file the registry names. Values never reach argv, logs or stdout.
  if (exe.env_file && Array.isArray(exe.env_names)) {
    for (const name of exe.env_names) {
      if (env[name]) continue;
      const v = readEnvVar(expand(exe.env_file), name);
      if (v) env[name] = v;
    }
  }
  if (kind === "opencode" && exe.config_content) {
    const { $comment, ...cfg } = exe.config_content;
    const json = expand(JSON.stringify(cfg)).replace(/~\//g, `${HOME}/`);
    env.OPENCODE_CONFIG_CONTENT = json;
  }
  if (kind === "claude-cli") {
    // Point this child (and every subagent it spawns) at the provider. Its own key wins over the
    // claude.ai login; no alias may fall through to an Anthropic model id.
    if (!exe.base_url || !exe.auth_env) usage(`${executor} needs base_url and auth_env in the registry`);
    delete env.ANTHROPIC_API_KEY;
    env.ANTHROPIC_BASE_URL = exe.base_url;
    env.ANTHROPIC_AUTH_TOKEN = env[exe.auth_env] || "";
    for (const k of ["ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
      "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_SMALL_FAST_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL"]) env[k] = model;
    env.CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = "1";
  }
  // Fleet hygiene for anything the lane runs (standing brief): no shared Nx daemon.
  env.NX_DAEMON = "false";

  if (opts["dry-run"]) {
    process.stdout.write(JSON.stringify({ bin, argv, cwd, sandbox, timeoutSec, prompt: paths.prompt, registry: source, modelWarning,
      ...(laneMcp ? { mcpServers: (exe.mcp_servers || []).filter((n) => !laneMcp.missing.includes(n)), mcpMissing: laneMcp.missing } : {}),
      ...(kind === "claude-cli" ? { providerKey: env.ANTHROPIC_AUTH_TOKEN ? "set" : "MISSING" } : {}) }, null, 2) + "\n");
    if (laneMcp) rmSync(laneMcp.path, { force: true });
    return 0;
  }

  const version = (() => {
    const r = spawnSync(bin, ["--version"], { encoding: "utf8", env, timeout: 15000 });
    return r.status === 0 ? r.stdout.trim().split("\n").pop() : null;
  })();
  const startedAt = new Date();
  const before = snapshot(cwd);
  const base = {
    schema: "fleet-lane.result.v1", executor, kind, model, role: opts.role, ticket: opts.ticket, cwd, sandbox,
    effort: opts.effort || null, timeoutSec, executorVersion: version, registry: source, modelWarning,
    startedAt: startedAt.toISOString(), promptPath: paths.prompt, logPath: paths.events, stderrPath: paths.stderr,
  };
  const finish = (fields) => {
    if (laneMcp) rmSync(laneMcp.path, { force: true }); // it may hold MCP credentials
    const after = snapshot(cwd);
    const result = {
      ...base, ...fields,
      finishedAt: new Date().toISOString(), durationMs: Date.now() - startedAt.getTime(),
      touchedFiles: after.status, worktreesAdded: added(before.worktrees, after.worktrees, opts.ticket), branchesAdded: added(before.branches, after.branches, opts.ticket),
    };
    writeFileSync(paths.result, JSON.stringify(result, null, 2) + "\n");
    const summary = `lane ${result.status} · ${executor}/${model} · ${opts.role} ${opts.ticket} · exit ${result.exitCode} · ${Math.round(result.durationMs / 1000)}s · ${paths.result}`;
    process.stdout.write(summary + "\n" + (result.lastMessage ? `--- last message ---\n${result.lastMessage}\n` : ""));
    return result;
  };

  // Budget gate (fleetctl budget check): a held executor is not launched. The PM sleeps until
  // resumeAt on a background timer and re-runs, or picks again (selection skips held executors).
  if (!opts["ignore-budget"]) {
    const b = fleetctl(["budget", "check", executor, "--json", "--cwd", cwd]);
    let check = null; try { check = JSON.parse(b.out); } catch {}
    if (check && check.state !== "ok") {
      finish({ status: "deferred", exitCode: 75, signal: null, lastMessage: "", budget: check,
               resumeAt: check.resume_at ? new Date(check.resume_at * 1000).toISOString() : null,
               error: `budget ${check.state} for ${executor}${check.note ? ": " + check.note : ""}` });
      return 75;
    }
  }
  if (kind === "claude-cli" && !env.ANTHROPIC_AUTH_TOKEN) {
    finish({ status: "unavailable", exitCode: 127, signal: null, lastMessage: "", error: `${exe.auth_env} not found in the environment or env_file` });
    return 127;
  }
  if (!version) {
    finish({ status: "unavailable", exitCode: 127, signal: null, lastMessage: "", error: `${bin} not found or --version failed` });
    return 127;
  }
  writeFileSync(paths.started, JSON.stringify({ ...base, pid: process.pid }, null, 2) + "\n");
  fleetctl(["budget", "lane-start", executor, "--cwd", cwd]);

  const child = spawn(bin, argv, { cwd, env, stdio: ["pipe", "pipe", "pipe"], detached: true });
  const errOut = createWriteStream(paths.stderr);
  let threadId = null; let sessionId = null; let tokenUsage = null; let cliResult = null;
  const textParts = new Map(); const order = [];
  const scan = makeScanner((ev) => {
    if (kind === "codex") {
      if (ev.type === "thread.started" && ev.thread_id) threadId = ev.thread_id;
      if (ev.type === "turn.completed" && ev.usage) tokenUsage = ev.usage;
    } else if (kind === "claude-cli") {
      if (ev.session_id) sessionId = ev.session_id;
      if (ev.type === "result") {
        cliResult = ev;
        // Same shape as codex: input counts cache reads too, cached_input_tokens says how many.
        const u = ev.usage || {};
        const cached = u.cache_read_input_tokens || 0;
        tokenUsage = { input_tokens: (u.input_tokens || 0) + cached + (u.cache_creation_input_tokens || 0),
          cached_input_tokens: cached, output_tokens: u.output_tokens || 0, num_turns: ev.num_turns ?? null };
      }
    } else {
      const sid = ev.sessionID || ev.session_id; if (sid) sessionId = sid;
      if (ev.type === "text" && ev.part?.type === "text") {
        const id = ev.part.id || `anon-${order.length}`;
        if (!textParts.has(id)) order.push(id);
        textParts.set(id, ev.part.text ?? "");
      }
    }
  });
  const dec = new StringDecoder("utf8");
  child.stdout.on("data", (c) => { appendFileSync(paths.events, c); scan(dec.write(c)); });
  child.stderr.on("data", (c) => errOut.write(c));
  child.stdin.on("error", () => {});
  child.stdin.end(readFileSync(paths.prompt, "utf8"));

  const killTree = (sig) => { try { process.kill(-child.pid, sig); } catch { try { child.kill(sig); } catch {} } };
  let reason = null;
  const timer = setTimeout(() => { reason = "timeout"; killTree("SIGTERM"); setTimeout(() => killTree("SIGKILL"), 15000).unref(); }, timeoutSec * 1000);
  for (const sig of ["SIGTERM", "SIGINT", "SIGHUP"]) {
    process.on(sig, () => { reason = reason || "aborted"; killTree("SIGTERM"); setTimeout(() => killTree("SIGKILL"), 5000).unref(); });
  }

  const { code, signal } = await new Promise((res) => child.on("close", (code, signal) => res({ code, signal })));
  clearTimeout(timer);
  errOut.end();
  if (reason === "timeout" || reason === "aborted") killTree("SIGKILL"); // sweep stragglers in the group

  let lastMessage = "";
  if (kind === "codex") { try { lastMessage = readFileSync(paths.final, "utf8").trim(); } catch {} }
  else if (kind === "claude-cli") {
    lastMessage = cliResult && !cliResult.is_error && typeof cliResult.result === "string" ? cliResult.result.trim() : "";
    if (lastMessage) writeFileSync(paths.final, lastMessage + "\n");
  }
  else { lastMessage = order.map((id) => textParts.get(id)).join("").trim(); if (lastMessage) writeFileSync(paths.final, lastMessage + "\n"); }

  // Quota or rate limit hit: record a back-off so the pacer holds this executor for a while.
  const RATE_RE = /\b429\b|rate[ _-]?limit|too many requests|usage limit|quota (exceeded|reached)|insufficient_quota/i;
  let rateLimited = false;
  try {
    const tail = (p) => { const t = readFileSync(p, "utf8"); return t.slice(-200000); };
    const errText = existsSync(paths.stderr) ? tail(paths.stderr) : "";
    const evText = existsSync(paths.events) ? tail(paths.events).split("\n").filter((l) => /"type":"(error|turn\.failed|session\.error)"|"error"|"is_error":true/.test(l)).join("\n") : "";
    rateLimited = RATE_RE.test(errText) || RATE_RE.test(evText);
  } catch {}
  if (rateLimited) fleetctl(["budget", "backoff", executor, "--reason", "rate limited in lane", "--cwd", cwd]);
  const ok = reason === null && code === 0 && lastMessage.length > 0;
  const status = reason ?? (ok ? "completed" : "failed");
  const exitCode = status === "timeout" ? 124 : status === "aborted" ? 130 : ok ? 0 : (code && code !== 0 ? code : 1);
  const stderrTail = (() => { try { return readFileSync(paths.stderr, "utf8").split("\n").filter((l) => l.trim()).slice(-15); } catch { return []; } })();
  finish({
    status, exitCode, childExitCode: code, signal: signal || null, lastMessage,
    threadId, sessionId, usage: tokenUsage, rateLimited,
    ...(status !== "completed" ? { stderrTail, error: status === "failed" && !lastMessage ? "no final message from the executor" : undefined } : {}),
  });
  return exitCode;
}

// ---------- main ----------
const opts = parseArgs(process.argv.slice(2));
const cmd = opts.positional[0];
if (!cmd) usage("missing executor or subcommand");
if (["pick", "budget", "log", "stats", "report", "selftest", "apply", "seed", "config"].includes(cmd)) {
  usage(`"${cmd}" is handled by fleetctl.py: call it through run-lane.sh`);
} else if (cmd === "models") {
  const { registry } = loadRegistry(opts.cwd || process.cwd());
  const which = opts.positional[1];
  for (const [name, e] of Object.entries(registry?.executors || {})) {
    if (which && which !== name) continue;
    process.stdout.write(`${name} (default ${e.default_model}): ${(e.models || []).join(", ")}\n`);
  }
  process.exit(0);
} else {
  run(opts).then((c) => process.exit(c), (e) => { process.stderr.write(`run-lane: ${e?.stack || e}\n`); process.exit(1); });
}
