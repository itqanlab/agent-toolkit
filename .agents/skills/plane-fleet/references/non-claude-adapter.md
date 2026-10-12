# Running a fleet role from Codex or opencode

You are a fleet session (engineer, tester, scan, ...) started by the PM through `run-lane.sh`.
The role skills were written for Claude Code. This page says how to follow them from Codex or
opencode. Everything else in your role skill and the standing brief applies to you unchanged.

## Plane: MCP only

- Every Plane read and write goes through your `plane` MCP server. It exposes the same
  actions the skills call `mcp__plane__workitem`, `mcp__plane__workitem_comment`,
  `mcp__plane__state`, `mcp__plane__label` and so on. In your tool list they may be named
  `plane.workitem`, `plane__workitem` or similar. Same server, same arguments.
- Never call the Plane REST API. No curl, no scripts, no Python against it, even if you find a
  key in a config file.
- If the `plane` tools are missing or fail to start, stop. Report `BLOCKED · plane MCP
  unavailable` as your final message. Do not work around it.
- The rules in `references/plane-api.md` apply to you: raw HTML in
  `description_html` and `comment_html`, send `priority` with every state change, read each
  write back.

## No Agent or Skill tools

- Where a skill says "invoke skill X" or "use `/team-ticket-writer`", read
  that skill's `SKILL.md` (the fleet roles are under `roles/` in the fleet folder) and follow it
  yourself, in this session.
- Where a skill says to spawn a subagent, do that part yourself, in order.
- `ToolSearch`, `Agent`, `SendMessage`, `Monitor` and `Skill` do not exist for you. Skip
  steps that only load tools.

## Claude-only tools: use the shell

| The skill says | You do |
|---|---|
| `Read`, `Grep`, `Glob`, `ptah_search_files`, `ptah_*` analysis | `cat`/`sed -n`, `rg`/`grep`, `find`/`ls` |
| `Edit`, `Write` | your own file edit tool, or a careful shell edit |
| `ptah_get_diagnostics` | the repo's own commands: `NX_DAEMON=false npx nx run <project>:typecheck` / `lint` |
| `Bash run_in_background`, `Monitor` | run it in the foreground with a timeout, or background it and poll with `sleep` loops |
| browser review via Claude's browser tools | your own Playwright: `npx playwright` from the worktree, headless Chromium. Never the owner's Chrome |
| `mcp__nx-mcp__*` | `npx nx show project <name> --json`, `npx nx graph --file=...` |

## Hooks and gates

- Never bypass a hook: no `--no-verify`, no `HUSKY=0`, no `-n`. In a fresh worktree run
  `npx husky` first, as the standing brief says.
- Claude Code's own PreToolUse hooks (the Plane API blocker, the usage pacer) do not run in
  your session. Their rules still bind you. Follow them by hand.
- Never raise a budget, threshold or timeout to get green. Report it.

## Slots, ports and git

- Same slot rules as everyone: only your assigned slot's ports, DB and Nx cache. `NX_DAEMON=false`
  is already set in your environment. Check `lsof -iTCP:<port> -sTCP:LISTEN` before you start
  anything, and tear the slot down before you report.
- Never touch the shared row's ports (`fleet.slots.shared`) or another slot's.
- Your sandbox: the engineer and tester lanes run with full access because the restricted Codex
  sandbox cannot write `.git`. Full access is not permission to go outside your worktree, slot
  and the repo's git metadata.
- `run-lane` never commits for you. Commits, pushes and the PR are yours, exactly as the role
  skill says. Never push to the trunk.

## Secrets

- Never print, log or paste a token, key or password, including into Plane comments, PR bodies
  or your final message. If a command would echo one, mask it.

## Final message

Your last message is the role skill's report line or block, nothing else. The PM reads it from
`result.json` and acts on it. Examples:

- engineer: `PROJ-134 → In Review · PR #212 · gate green · browser: 3/3 criteria walked as sales · slot A torn down`
- engineer blocked: `PROJ-134 BLOCKED → Todo · waiting on <what>`
- tester: the `test — …` block from the tester skill
- scan: whatever the brief's report contract asks for

If you stop early for any reason, the final message still says what state you left the ticket
in. A lane that exits without a report line is treated as a dead session.
