# Running a fleet role from Codex, opencode or Antigravity

You are a fleet session (engineer, tester, scan, ...) started by the PM through `fleet`.
The role skills were written for Claude Code. This page says how to follow them from Codex,
opencode or the Antigravity CLI (agy). Everything else in your role skill and the standing brief applies to you unchanged.

## Plane: MCP only

- Every Plane read and write goes through your `plane` MCP server. It exposes the same
  actions the skills call `mcp__plane__workitem`, `mcp__plane__workitem_comment`,
  `mcp__plane__state`, `mcp__plane__label` and so on. In your tool list they may be named
  `plane.workitem`, `plane__workitem` or similar. Same server, same arguments.
- Never call the Plane REST API. No curl, no scripts, no Python against it, even if you find a
  key in a config file.
- If the `plane` tools are missing or fail to start, stop. Report `BLOCKED · plane MCP
  unavailable` as your final message. Do not work around it.
- Never open Plane in a browser, and never guess its web address. You don't need the web UI:
  the MCP does everything. The project's Plane is self-hosted, so `app.plane.so` is someone
  else's site. (2026-10-24: a tester lane opened `app.plane.so/<workspace>/browse/<ticket>` in
  the owner's Chrome to attach a screenshot.)
- An attachment the MCP refuses stays local. Name its path in your comment and move on. Never
  upload a screenshot, log or file to an outside host (catbox, imgur, pastebins, file drops)
  to get a URL: that publishes the app's screens to anyone with the link. (Same run: a lane
  uploaded a slot screenshot to catbox.moe.)
- The rules in `core/references/plane-api.md` apply to you: raw HTML in
  `description_html` and `comment_html`, send `priority` with every state change, read each
  write back.

## No Agent or Skill tools

- Where a skill says "invoke skill X" or "use the planner's `write-ticket` skill", read
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

Never control the owner's desktop or browser: no computer use, no `cua_repl`, no browser or
Chrome plugin tools, even if they show up in your tool list. On Antigravity that means none of
`browser_*`, `open_browser_url`, `click_browser_pixel`, `capture_browser_screenshot`,
`execute_browser_javascript`, `read_browser_page`, the browser subagent or `chrome-devtools`
MCP tools; agy loads them in every session and the runner cannot turn them off. The runner turns those plugins off
(`disable_plugins` in the executor registry); if one is still there, the registry missed it.
Don't use it, and say so in your final message.

## Hooks and gates

- Never bypass a hook: no `--no-verify`, no `HUSKY=0`, no `-n`. In a fresh worktree run
  `npx husky` first, as the standing brief says.
- Claude Code's own PreToolUse hooks (the Plane API blocker, the usage pacer) do not run in
  your session. Their rules still bind you. Follow them by hand.
- Never raise a budget, threshold or timeout to get green. Report it.

## Antigravity only

- Your shell tool is `run_command`. Background commands report through `command_status`.
- A fleet hook checks each tool call. When it refuses one, you get the reason as the tool's
  error. Do not retry it or work around it: carry on and say in your report what you could not do.
- In a read-only lane, use only the commands the lane prompt lists, one per call, no pipes. Read
  and search with `view_file`, `grep_search`, `find_by_name` and `list_dir`.
- Do not use subagents, scheduling, messaging, image generation or the marketplace. Do the work
  yourself, in this session.

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
