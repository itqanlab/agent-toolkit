# plane-fleet

Run a [Plane](https://plane.so) board with a team of agent roles. A PM picks tickets oldest
first and fires engineers in parallel, each in its own git worktree and environment slot. The
moment a PR opens, a tester checks it blind in the browser against the ticket, then reviews the
code and adds tests. The PM merges approved PRs in groups, confirms CI and the deploy, moves
tickets to Done and tells the client. Nobody waits for anybody.

## Roles

| Role | File | Ends at |
| --- | --- | --- |
| PM | `roles/team-pm/SKILL.md` | merged, deployed, CI/CD green, `Done`, client told |
| engineer | `roles/team-engineer/SKILL.md` | draft PR open, browser-reviewed, ticket `In Review` |
| tester | `roles/team-tester/SKILL.md` | `Approved` (label `qa-approved`) or `Rework` |
| ticket writer | `roles/team-ticket-writer/SKILL.md` | new ticket in `Todo` with an investigate gate |
| solo | `roles/solo-ship/SKILL.md` | the whole loop in one session, ticket by ticket |

The entry point is `SKILL.md`, which routes a request to the right role. The roles are full
skills in their own right: you can link `roles/team-pm` into your skills folder as `team-pm` and
call it directly. Each role finds the shared files by resolving the plugin folder physically, so
a symlinked install works.

## Requirements

- **A Plane MCP server named `plane`** with the resource tools `workitem`, `workitem_comment`,
  `workitem_relation`, `workitem_attachment`, `state` and `label`, each taking an `action`. The
  plugin declares one in `.mcp.json`: the
  [itqanlab/plane-mcp-server](https://github.com/itqanlab/plane-mcp-server) fork, run from source
  with `uvx`, pinned to a commit until the fork has a release tag. It reads three environment
  variables:
  - `PLANE_API_KEY`: Workspace Settings → API tokens
  - `PLANE_WORKSPACE_SLUG`
  - `PLANE_BASE_URL`: only for a self-hosted Plane (default `https://api.plane.so`)
- `git`, the GitHub CLI `gh` (signed in), `python3`, and `node` 18 or newer.
- An agent that can start sub-sessions for the PM role. Without one, use the solo role, or run
  one engineer or tester role by hand.
- `uv` for the MCP server (`uvx`).

## Setup

1. Install the plugin, or link `skills/plane-fleet` (and, if you like, each `roles/<name>`) into
   your agent's skills folder. On a linked install, also link each file in the plugin's
   `agents/` folder into `~/.claude/agents/`, so the PM can spawn `fleet-engineer`,
   `fleet-tester`, `fleet-planner` and `fleet-plane`. New agent types show up in the next session.
2. Set the three Plane variables in the environment your agent starts from.
3. In each repo, let the PM or solo role write `.plane/config.json` on first run, or write it
   from `references/config-schema.md`. Keep private values (client contact, server names,
   timezone) in `~/.config/plane-fleet/projects/<repo-name>.json` instead of the repo.
4. Optional: give engineers and testers environment slots (`fleet.slots` and
   `fleet.slot_recipe`) so they can run the app and check their work in a browser.

## Executors, budget and the outcomes log

Every role runs as a sub-session by default. A role can also run on another coding CLI as a
background lane:

```bash
scripts/lanes/run-lane.sh pick --role engineer --kind api --cwd <repo>
scripts/lanes/run-lane.sh codex --model <model> --role engineer --ticket PROJ-12 \
  --cwd <repo> --brief brief.md --out /tmp/PROJ-12-engineer
scripts/lanes/run-lane.sh budget          # one line: Claude 46% (5h) · Codex 20% (wk) · Ollama ok
scripts/lanes/run-lane.sh stats           # first-pass rate per role, task kind and executor
scripts/lanes/run-lane.sh apply           # promote or demote executors, logged for veto
```

`references/executors.md` has the whole design. In short:

- **Registry.** `references/executors.json` lists executors, models, roles, task kinds and
  ranked candidates (champion first). It ships Claude-only. Opt in to other CLIs in
  `~/.config/plane-fleet/executors.json`.
- **Selection.** Mostly the champion, about one pick in five a challenger, never an experiment
  for schema, money, concurrency, urgent work or a second attempt.
- **Budget.** One pacer for every executor: a hard stop and a pace rule on each meter. The
  Claude meter is a statusline relay file you point it at. Codex reads its own session logs.
  Services with no usage API get a lane counter and back-off on 429.
- **Outcomes.** One log for all projects at `~/.config/plane-fleet/executor-outcomes.jsonl`,
  tagged by project, back-filled as tickets move.

User-level state lives in `~/.config/plane-fleet/`, or wherever `PLANE_FLEET_HOME` points.

### Other coding CLIs

| CLI | Needs |
| --- | --- |
| Codex | the `codex` CLI, signed in, and the two profiles from `references/codex-profiles/` copied into `$CODEX_HOME` |
| opencode | the `opencode` CLI and a provider in its config, for example an OpenAI-compatible `ollama-cloud` provider with `baseURL` `https://ollama.com/v1` and `apiKey` `{env:OLLAMA_API_KEY}` |

Engineer and tester lanes on Codex run with full access, because Codex's sandbox keeps every
`.git` path read-only and a lane must commit. opencode has no OS sandbox; give it read-only
roles.

## The usage pacer hook

`hooks/usage-pacer.py` runs before every sub-session spawn, through the plugin's
`hooks/hooks.json`. It holds new fleet sessions when the Claude window is ahead of pace or past
the hard stop. Without a meter configured it judges nothing. Turn it off with
`touch ~/.config/plane-fleet/pacer-off`, or keep only the hard stop with `pace-off`.

## The cache keeper hook

`hooks/cache-keeper.py` runs before every `Bash` and `Monitor` call and acts only inside the
fleet agents (`fleet-engineer`, `fleet-tester`, `fleet-planner`, `fleet-plane`). An agent's
prompt cache lives 5 minutes, and a call that waits longer makes the next call write the whole
context again. So it refuses a foreground Bash timeout over 270000 ms and a Monitor deadline
over 270000 ms, and tells the agent to run the job in the background and check it every 4
minutes. Refusals are logged to `~/.config/plane-fleet/cache-keeper.jsonl`. Turn it off with
`touch ~/.config/plane-fleet/cache-keeper-off`.

On a linked install (agents linked into your agents folder instead of a plugin install), the
plugin's `hooks/hooks.json` does not run. Register both hooks in your user settings the same
way: a `PreToolUse` entry with matcher `Agent` for `usage-pacer.py`, and one with matcher
`Bash|Monitor` for `cache-keeper.py`.

## Example

> run the board

The PM reads `.plane/config.json`, checks the board, claims the three oldest workable tickets,
gives each engineer a slot, and spawns a tester the moment a PR opens. It merges approved PRs
in a group, waits for trunk CI and the deploy, moves the tickets to `Done`, and keeps going
until the queue is empty or a real blocker stops it.

## Changelog

See `CHANGELOG.md`.
