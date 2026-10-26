// Antigravity hook for fleet lanes. run-lane sets FLEET_LANE_POLICY to a policy file in the
// lane's out dir; without it the hook prints nothing (hooks.json checks first), so the owner's own
// agy sessions are untouched. agy has no per-run tool list, so this is where a lane's limits live.
// Measured on agy 1.3.1: empty output is neutral, but "{}" DENIES the tool. A hook denial reaches
// the model as an error and the run goes on; agy's own permission denial ends a headless run.
// A hook cannot grant: "allow", "ask" and permissionOverrides never passed agy's check headless.
// So every lane runs with --dangerously-skip-permissions and this hook is the only gate.
import { readFileSync, writeFileSync, appendFileSync, existsSync } from "node:fs";

const say = (o) => { if (o) process.stdout.write(JSON.stringify(o)); process.exit(0); };
let input = {}; let policy = {};
try { input = JSON.parse(readFileSync(0, "utf8") || "{}"); } catch {}
try { policy = JSON.parse(readFileSync(process.env.FLEET_LANE_POLICY, "utf8")); } catch { say(null); }
try { if (policy.seen) writeFileSync(policy.seen, ""); } catch {} // proof for result.json that the guard ran
const log = (line) => { try { appendFileSync(policy.denied_log, JSON.stringify(line) + "\n"); } catch {} };
const deny = (tool, reason) => {
  log({ tool, reason });
  say({ decision: "deny", reason: `${reason} This is a fleet rule, not an error: carry on without it and finish with your report line.` });
};

const name = input.toolCall?.name || "";
const args = input.toolCall?.args || {};
if ((policy.deny_tools || []).some((p) => new RegExp(`^(${p})$`).test(name))) {
  deny(name, `${name} is off in fleet lanes (never drive a browser or spawn helpers).`);
}
if (name === "call_mcp_tool") {
  const server = args.ServerName || "";
  if (!(policy.mcp_servers || []).includes(server)) deny(name, `MCP server ${server} is off in fleet lanes; only ${(policy.mcp_servers || []).join(", ")} is on.`);
  if (policy.sandbox === "read-only") {
    const action = String(args.Arguments?.action || "");
    if (!new RegExp(policy.mcp_read_actions || "^$").test(action)) deny(name, `Plane action ${action || "(none)"} is not a read; this lane is read-only.`);
  }
  say(null);
}
if (name === "run_command" && policy.sandbox !== "read-only") {
  // Full lanes run what they need, except what reaches past the lane: the owner's browser or
  // desktop, or a tunnel. A guard rail, not a sandbox: `sh -c` gets around it.
  const cmd = String(args.CommandLine || "").trim();
  const bad = (policy.full_deny_commands || []).find((p) => new RegExp(p).test(cmd));
  if (bad) deny(name, `Not in a fleet lane: this opens the owner's browser or desktop, or a tunnel. Got: ${cmd}`);
}
if (policy.sandbox !== "read-only") say(null);

// read-only lane
if ((policy.write_tools || []).includes(name)) deny(name, `${name} writes; this lane is read-only.`);
if (name === "run_command") {
  const cmd = String(args.CommandLine || "").trim();
  if (/[;&|<>`$\n]/.test(cmd)) deny(name, `One plain command per call in a read-only lane: no pipes, redirects, && or $(...). Got: ${cmd}`);
  // listed commands that can still write or run something else through a flag
  if (/(^|\s)(--pre(-glob)?|--output|--ext-diff|--web|--exec|--open-files-in-pager)(=|\s|$)/.test(cmd)) deny(name, `That flag writes or runs another program; this lane is read-only. Got: ${cmd}`);
  const ok = (policy.allow_commands || []).some((p) => cmd === p || cmd.startsWith(p + " "));
  if (!ok) deny(name, `Not on this lane's read-only command list (${(policy.allow_commands || []).join(", ")}). Got: ${cmd}`);
  say(null);
}
// Any other tool that changes something, named or not, stays out of a read-only lane.
if (!new RegExp(`^(${(policy.read_tools || []).join("|")})$`).test(name)) deny(name, `${name} is not a read tool; this lane is read-only.`);
say(null);
