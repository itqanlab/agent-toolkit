# Executors — who runs each fleet role

The fleet has **roles** (engineer, tester, scan, ticket writer, PM) and **executors** (the
program that runs a role: a Claude subagent, the Codex CLI, opencode on Ollama Cloud, Claude Code
on Ollama Cloud). Any role
can in principle run on any executor. The PM picks one per spawn.

The role skills don't change. An engineer is an engineer whether Claude or Codex runs it: same
skill, same standing brief, same slot rules, same report line. Only the program underneath
differs.

- Registry (machine-readable): `references/executors.json`
- Selection, budget, log, scoreboard, config: `scripts/lanes/fleetctl.py` (through `run-lane.sh pick|budget|log|stats|report|apply|seed|config|selftest`)
- User-level state: `{state_home}` = `PLANE_FLEET_HOME`, default `{state_home}/` (outcomes log, decisions, user override, budget override, back-off state, per-project config overrides)
- Runner for non-Claude executors: `scripts/lanes/run-lane.sh`
- What a non-Claude session must know: `references/non-claude-adapter.md`

## Task kinds

Every spawn is tagged with a role and a **task kind** before the pick. The PM derives the kind
from triage (paths, keywords, schema words) and the ticket text:

| kind | means |
|---|---|
| `api` | server endpoints, services, DTOs, guards; no schema change |
| `ui` | client components, templates, styling, client data access |
| `schema` | schema or migration change (never an experiment, never auto-promoted) |
| `money-concurrency` | money movement, balances, locks, ordering, timing (same) |
| `copy-i18n` | labels, translations, static text only |
| `tests-only` | adds or fixes tests, no product code |
| `infra-deps` | CI, build config, dependencies, tooling |
| `retest` | a tester re-checking a reworked PR |
| `rework` | a second engineer attempt after Rework (never an experiment) |

Add kinds under `task_kinds` in the registry when a new shape of work keeps showing up.

## Champion and challengers

`candidates` in the registry holds, per role and per kind (`*` = any kind without its own
list), a ranked list of `executor:model`. The first is the **champion**; the rest are
**challengers**. Shipped defaults are Claude only, so the fleet works with nothing else
installed:

| role / kind | champion | challengers |
|---|---|---|
| engineer / `*` | claude `sonnet` | claude `opus` |
| engineer / `schema`, `money-concurrency`, `rework` | claude `opus` | — |
| tester / `*` | claude `opus` | — |
| tester / `copy-i18n` | claude `sonnet` | claude `opus` |
| scan / `*` | claude `haiku` | — |
| ticket-writer / `*` | claude `sonnet` | — |

**Opting in to Codex or opencode** is a user-override edit, for example:

```json
{ "candidates": {
    "engineer": { "*": [ {"executor":"codex","model":"gpt-5.6-sol"}, {"executor":"claude","model":"sonnet"} ] },
    "scan":     { "*": [ {"executor":"opencode","model":"kimi-k2.7-code"}, {"executor":"claude","model":"haiku"} ] } } }
```

**Effort is part of a candidate.** A candidate may carry `"effort"`, and then it is its own
entry everywhere: `codex:gpt-5.6-sol@low` and `codex:gpt-5.6-sol@high` are scored, explored and
promoted separately. `pick` returns the effort; pass it to the lane with `--effort`, or to a
Claude spawn as the `Agent` call's `effort`. A candidate without `"effort"` runs at the
executor's default and keeps the plain `executor:model` key, so older rows still count for it.
To compare efforts, list the same model twice with different efforts:

```json
"tests-only": [ {"executor":"codex","model":"gpt-5.6-sol","effort":"medium"},
                {"executor":"codex","model":"gpt-5.6-sol","effort":"low"} ]
```

**opencode serves three providers.** A bare model id uses the executor's `provider`
(`ollama-cloud`). Name the others as `provider/model`:

| provider | models | cost |
|---|---|---|
| `ollama-cloud` | `kimi-k2.7-code`, `glm-5.3`, `deepseek-v4-pro:0813`, … (`models` in the registry) | Ollama Cloud plan, shared with `claude-ollama` |
| `opencode` | `opencode/nemotron-3-ultra-free`, `opencode/big-pickle`, … (`free_models`) | free, no key; free tiers may keep prompts |
| `zai-coding-plan` | `zai-coding-plan/glm-5.3`, … | Z.ai GLM coding plan (`opencode auth login`) |

opencode takes effort as `--variant`; the runner passes `--effort` through. Variant names are
the provider's own. Ollama Cloud models are also reachable through Claude Code
(`claude-ollama`), which keeps Claude Code's permission profiles; opencode's write agent runs
with `--auto` and no OS sandbox. Run both routes as separate candidates and let the scoreboard
decide.

Escalation triggers still pin the engineer to claude `opus`: `schema`, `concurrency`,
`unknown_root_cause`, `rework_once`, `architecture`, `disprove_gate`.

**Experiments.** About 1 pick in 5 (`selection.explore_rate`) goes to a challenger, the one with
the fewest logged runs for that role and kind. The pick line says `EXPERIMENT`. Never an
experiment for: an urgent or trunk-red fix (`--urgent`), a kind with `allow_explore: false`, a
second attempt after Rework (`--attempt 1`), or an escalation. When the engineer is an
experiment, its tester stays proven (champion, or n ≥ 5 at ≥ 70%) and, where one exists, from
another model family than the engineer (`--pair-with codex:gpt-5.6-sol --pair-experiment`).

## How the PM picks

```bash
L=scripts/lanes/run-lane.sh
$L pick --role engineer --kind api --cwd <repo>                   # champion or experiment
$L pick --role engineer --kind api --triggers concurrency         # escalation
$L pick --role tester --kind ui --pair-with codex:gpt-5.6-sol --pair-experiment
$L models                                                         # every selectable model
```

`pick` prints JSON with `decision` (`spawn` or `wait`), `executor`, `model`, `sandbox`,
`experiment`, `reason`, `budget` and a ready `pick_line`. Layers, later wins:

1. the shared registry `executors.json`
2. the **user override** `{state_home}/executors.json` (promotions write here)
3. its `projects.<repo-name>` block (project champions write here)
4. the repo's `.plane/config.json` → `fleet.executors`

Objects merge key by key; lists and plain values replace. **No registry, or the executor is
missing on this machine** → a Claude subagent with the team-pm §3 model defaults. A broken lane
never stops the fleet. Any listed model can also be forced by hand with `run-lane.sh <exe>
--model`; an unlisted one runs with a warning in `result.json`.

## Budget: one pacer for every executor

Same rules for each executor: **hard stop** at `hard_stop_pct` (95), and **pace**: no faster
than the window elapses plus `pace_allowance_pct` (20). Override per user in
`{state_home}/budget.json` (same shape as `budget` in the registry).

| executor | meter | window |
|---|---|---|
| claude | the file in `budget.executors.claude.status_file`: a statusline relay that writes the harness's `rate_limits.five_hour` block. None set = no meter | 5 h |
| codex | newest `~/.codex/sessions/YYYY/MM/DD/*.jsonl` `token_count` event `rate_limits` (`primary`/`secondary` `used_percent`, `window_minutes`, `resets_at`) | as reported (weekly on the current plan) |
| opencode, claude-ollama / Ollama Cloud | no usage API: a local lane counter per window, plus a back-off after any 429 or quota error. Both draw on one plan, so `state_as: opencode` makes them share the counter and the back-off | 5 h |

Each source answers `ok`, `hold` (pace or back-off) or `stop` (hard stop), with `resume_at`. An
unknown meter is `ok` (no judgement), as before. After a lane, `run-lane` scans its output for
429 / rate-limit / quota text and records a back-off (`backoff_minutes`, 30) for that executor.

Switch files in `{state_home}`: `pacer-off` (no gate) and `pace-off` (hard stop only), for all
executors, or `pacer-off-<executor>` / `pace-off-<executor>` for one. `legacy_switch_dir` on an
executor's budget block adds one more folder to look in.

Gates:
- **Claude spawns:** the `usage-pacer.py` PreToolUse hook on `Agent`, now calling the same
  `fleetctl` check.
- **Codex, opencode and claude-ollama lanes:** `run-lane.sh` checks before launching. Held → `result.json` status
  `deferred`, exit 75, `resumeAt`. The PM starts a background `sleep` until then and re-picks.
  It never hands back to the owner.
- **Routing:** `pick` only chooses executors whose budget is `ok`. When the champion is held,
  portable work (engineer, scan) moves to the next candidate with budget; pinned work (testers,
  escalations) returns `decision: wait` with `resume_at`.

One line for preflight and status updates: `run-lane.sh budget` →
`Claude 58% (5h) · Codex 9% (wk) · Ollama ok (2 lanes) · Claude Code/Ollama ok (2 lanes)`.

## Running a lane

Claude executor: the `Agent` tool, exactly as team-pm §3 shows. Nothing changes.

Codex, opencode or claude-ollama: write the per-spawn brief to a file, then start the lane with **Bash
`run_in_background: true`** so you are told when it exits:

```bash
scripts/lanes/run-lane.sh codex --model gpt-5.6-sol \
  --role engineer --ticket PROJ-134 --cwd /path/to/repo \
  --brief /tmp/PROJ-134-engineer/brief.md --out /tmp/PROJ-134-engineer/lane
```

The runner builds the real prompt: the adapter note (not for claude-ollama, which is Claude Code), "read and follow <role SKILL.md>", the
standing-brief line (for engineer and tester), then your brief. It feeds it on stdin, enforces
the timeout (role default, or `--timeout <sec>`), and writes `<out>/result.json`:

| field | meaning |
|---|---|
| `status` | `completed` · `failed` · `timeout` · `aborted` · `unavailable` |
| `exitCode` | 0 completed, 124 timeout, 127 binary missing, 130 aborted, else the executor's |
| `lastMessage` | the session's final message, which is its report line |
| `touchedFiles` | `git status --porcelain` in `--cwd` |
| `worktreesAdded`, `branchesAdded` | new worktrees and branches whose name has the ticket id |
| `durationMs`, `usage`, `threadId`/`sessionId`, `executorVersion`, `logPath`, `stderrPath` | for the run log and debugging |

`--dry-run` prints the command and writes the prompt without running anything. The runner
never commits and never prints secrets. Credentials an executor's own config references as env vars (`env_names`, e.g. `OLLAMA_API_KEY`)
come from the environment, or from the `env_file` your user override names, and go into the
child's environment only.

### Sandbox

| `--sandbox` | Codex | opencode | claude-ollama |
|---|---|---|---|
| `full` | profile `fleet-engineer-full` + `--dangerously-bypass-approvals-and-sandbox` | `build` agent + `--auto` | `--dangerously-skip-permissions` |
| `restricted` | profile `fleet-engineer` (workspace write, network on, caches, pnpm store, /tmp) | — | — |
| `read-only` | `-s read-only` | `plan` agent, no `--auto` | allow Read, Grep, Glob, Bash, `mcp__plane__*`; deny Edit, Write, NotebookEdit |

**Why engineers and testers run `full` on Codex.** Tested 2026-10-09 on codex-cli 0.161.0. The
restricted profile passed network, `gh api user`, `git ls-remote` (keychain), a local Postgres,
the npm registry, `pnpm install --frozen-lockfile` and an nx typecheck. It failed every git
write: `Unable to create .../.git/worktrees/<wt>/HEAD.lock: Operation not permitted`. Codex
keeps every `.git` path read-only in workspace-write, even when the profile grants it `write`.
There is no documented way to lift that. Engineers and testers must commit, so they get full
access. The restricted profile stays for a future role that edits but never commits.

Profiles live in `~/.codex/fleet-engineer.config.toml` and `~/.codex/fleet-engineer-full.config.toml`.
Codex 0.161 loads `-p <name>` from `$CODEX_HOME/<name>.config.toml`. A `[profiles.<name>]`
table in config.toml is not how this version does it.

opencode has no OS sandbox. `plan` is a permission policy: it refuses edits but still ran a
read-only `ls` in the smoke test. Only give opencode read-only roles until that changes.

### Lane-specific settings the runner applies

- Codex: MCP calls need approval and `exec` runs with approval `never`, so every plane call
  failed until the runner passed `mcp_servers.plane.default_tools_approval_mode="approve"`.
  `mcp_overrides` can point the lane's `plane` server at the same server build Claude uses, so
  both see the same tools (only non-secret fields such as `command`; argv is visible in `ps`).
  `disable_mcp` switches off MCP servers a lane never needs. `disable_plugins` does the same
  for Codex plugins (`"browser@openai-bundled"` and so on), which bring tools of their own:
  the computer-use and browser plugins give a lane `cua_repl`, which drives the owner's real
  Chrome and desktop. Turning off the MCP server of the same name does not remove it.
- opencode: a headless run auto-rejects reads outside the working dir, and one rejection ends
  the run. The runner allows the fleet folder (`{fleet_root}/**`, and nothing else outside)
  through `OPENCODE_CONFIG_CONTENT`.
- claude-ollama: runs `claude -p` with the child's env pointed at the provider
  (`ANTHROPIC_BASE_URL` = `base_url`, `ANTHROPIC_AUTH_TOKEN` = the `auth_env` key,
  `ANTHROPIC_API_KEY` removed). Every model alias (opus, sonnet, haiku, the small fast model,
  subagents) is set to the lane's model, so no call falls through to Anthropic and the Claude
  quota is untouched. MCP is `--strict-mcp-config` with only `mcp_servers` (plane), copied from
  `~/.claude.json` into a 0600 `mcp.json` in the out dir and deleted when the lane ends.
  `--add-dir` gives it the fleet folder. Read-only is a tool list, not plan mode: tested
  2026-10-16, plan mode blocks MCP calls even with an allow rule. `--effort` passes through.
  Smoke tested 2026-10-16 on kimi-k2.7-code and glm-5.3: Bash, Plane reads, a denied Write in
  read-only, and an edit + test run + commit in full mode. No commit trailer is added.
- All: `NX_DAEMON=false` in the child environment.

## Outcomes log, scoreboard, promotion

**One log for all projects:** `{state_home}/executor-outcomes.jsonl`, append-only, every row
tagged `project` (the repo name). Older per-project run logs can be folded in with
`log.legacy_glob` in the user override and `run-lane.sh seed` (idempotent). They stay read live,
so rows still written there are not lost.

```bash
# a Claude spawn: numbers from the Agent result, as --set (or bare k=v words, same thing)
$L log add --ticket PROJ-134 --role engineer --kind api --executor claude --model sonnet \
   --outcome pr_opened --reason "champion" --set duration_ms=1234000 tokens=230000 rework_count=0
# a lane: ticket, role, executor, model, duration and tokens come from its result.json
$L log add --from-result /tmp/PROJ-134-engineer/lane/result.json --kind api --outcome pr_opened --reason "PR 212"
$L log add ... --experiment                                   # an experiment pick
$L log add ... --effort high                                  # a Claude spawn given an effort (lanes: from result.json)
# the PM, when a ticket reaches Done (a marker row, not a session)
$L log add --ticket PROJ-134 --role pm --executor claude --model opus --outcome done --set client_visible=true
$L log backfill --ticket PROJ-134 --role engineer --set verify_first_pass=true ci_first_pass=true
$L log backfill --ticket PROJ-134 --role tester --set reverted=false bug_filed='"PROJ-171"'
$L selftest                                                   # log add round trip in a temp log
```

`--set` values are typed: `duration_ms`, `tokens`, `input_tokens`, `output_tokens`,
`cached_input_tokens` (and `reasoning_output_tokens`, `rework_count`) are stored as numbers
(`1,234` is fine), `true`/`false` as booleans, anything else as a string. Numbers typed on the
line win over `--from-result`. Before 2026-10-15 `log add` dropped `--set` values and refused
bare `k=v` words after an option, so older spawn rows have no tokens or duration.

Row fields: `ts, project, ticket, role, task_kind, executor, model, experiment, reason,
duration_ms, tokens` (Claude: the session total), or for a lane `input_tokens,
cached_input_tokens, output_tokens, reasoning_output_tokens`, `tokens` = input + output,
`result_path` and `lane_status` when it did not complete. Then `claude_meter_delta_pct` when
known, `outcome` (`pr_opened`, `blocked`, `verify_pass`, `verify_fail`, `done`, `lane_failed`,
`deferred`), `verify_first_pass, rework_count, ci_first_pass`, and later `reverted`,
`bug_filed`. `log add` needs `--executor` on every row, the PM's own Done rows included (use the PM's executor and model). A Done row (`--role pm --outcome done`) carries `client_visible`: `true` when the
client can see the change (UI, copy, a report they read), `false` for tests, infra, refactors
and internal tooling. Back-fills are separate rows and apply to the latest matching spawn. A
row with `"usage_only": true` and `for_ts` adds tokens/duration to the spawn row with that ts
(used to back-fill a run logged without numbers); without a match it counts as its own session.

**Report:** `$L report --project <repo> --since <iso> [--until <iso>]` prints, for that window:
tickets Done (`outcome=done` rows) and approved (`verify_pass`), sessions by
role/executor/model with tokens and hours, tokens per Done and per approved ticket (Claude
total; Codex output and input apart, input being ~99% cache reads), first-pass approval (the
first tester verdict per ticket), rework rounds per ticket (tester `verify_fail` count, top 5)
and the share of Done tickets with `client_visible=true`. `$L report -h` defines each line.

**Real cost:** `$L cost [--since <iso>] [--until <iso>]` reads what was actually spent, from the
sessions themselves:

- every Claude call in the repo's Claude Code session files, the PM's own and each agent's,
  deduplicated by message id and priced with the registry's `prices` block (API list prices, to
  compare options; plans bill differently; a model without a price shows tokens only)
- each lane's usage from its log row, and merge times from GitHub (`gh`)
- per merged ticket: agent cost and agent + PM share, first spawn → merge, hours agents worked;
  cost by role; cost and cycle time by rework rounds; test failures by `fail_cause`
- where the money goes: cache reads, cache writes and output; whole-context cache rewrites after
  a wait of 5 minutes or more (the default cache lifetime); each agent type's first-call context;
  the PM's calls per merged ticket, average context per call and cost by activity

`$L cost --ticket PROJ-134` prints that ticket's sessions in order with cost, calls and outcome.
`--json` gives the same as data. An agent belongs to the tickets in its spawn `description`
(`<role> <TICKET>`, team-pm §3), else to those in the first lines of its brief. Repo sessions
are found by folder name under `$CLAUDE_CONFIG_DIR/projects` (default `~/.claude/projects`),
worktrees included. A repo that moved keeps its old sessions under the old folder name: list
it in `.plane/config.json` `fleet.cost.claude_project_dirs`.

Claude Code deletes session files after `cleanupPeriodDays` (30 by default). `cost` keeps a
summary of every session it has read in `{state_home}/cost-cache` and keeps counting a session
after its file is gone, so run it at least every few weeks, or raise `cleanupPeriodDays`.

`$L cost --backfill [--dry-run]` adds the real usage to each Claude spawn row that has none,
matched by `agent_id`, else by the agent of the same ticket and role that ended within 30
minutes before the row. The scoreboard then compares Claude and lanes on the same tokens.

**What a row is scored on.** Engineer: `verify_first_pass`, or else the first tester verdict
after it on the same ticket. Old rows put the engineer's flag on the tester row. Tester: the
verdict held (not `reverted`, no `bug_filed`), only once those are back-filled. Until then
testers show `—`.

**Scoreboard:** `$L stats [--role R] [--kind K] [--project P]` gives, per (role, kind,
executor:model), n, first-pass rate ("not enough data" under 5), rework rate, mean minutes and
mean cost. Cost is in relative units (`cost_weights`, per million tokens of uncached input,
cache writes and output) and is only for comparing candidates. Until `cost --backfill` gives a
Claude row real usage, its cost comes from `tokens`, the last call's size, and reads far too low.
Scoring is global; `--project` filters.

**Promotion and demotion:** `$L apply` (`--dry-run` to preview), at every PM preflight:
- a challenger with n ≥ 5, first-pass ≥ the champion's and lower mean cost becomes champion
- a champion below 70% over its last 5 scored runs swaps with the next candidate
- a project gets its own champion only when its own runs (≥ 5 for both) disagree with the
  global order; that goes under `projects.<repo>` in the user override
- kinds with `auto_promote: false` (`schema`, `money-concurrency`) are never changed, only
  written as `PROPOSED` for the owner

Each change is a line in `{state_home}/executor-decisions.md` (date, role/kind, old →
new, the numbers), and the new order goes into the user override. The owner vetoes by editing
either file. The PM says every line in its report.

## Limits

- **Meters differ in quality.** Claude's is live. Codex's is only as fresh as the last Codex
  session that logged it. Ollama has no meter at all, only a lane count and back-off after a 429.
  A lane can still hit a quota mid-ticket; `run-lane` records the back-off and marks it
  `rateLimited`, and the PM treats it as a lane failure.
- **No Agent or Skill tools in a Codex or opencode lane.** It reads skill files and follows
  them itself, and cannot spawn helpers. A claude-ollama lane has both, and its subagents run on
  the lane's model.
- **Claude Code hooks do not run in a Codex or opencode lane.** The Plane-API blocker and the
  usage pacer are Claude hooks. The adapter repeats their rules, but nothing enforces them there.
  A claude-ollama lane runs them all, which also means the usage pacer can hold its `Agent`
  calls on the Claude meter even though those subagents run on Ollama. Git hooks (husky) run
  everywhere.
- **claude-ollama is not proven.** No candidates list names it by default. It gets real work
  only as a challenger in a user override, and earns champion through the scoreboard like any
  other executor.
- **Cost of context.** A Codex smoke lane used ~650k input tokens, mostly cached, for a 1-minute
  task. Expect real engineer lanes to be large.
- **A lane holds a slot** like any session, and tears it down like any session.

## Adding a role

1. Write its skill (or decide it has none: then the brief is the whole task, like `scan`).
2. Add it under `roles` in `executors.json`: skill path, whether it gets the standing brief,
   what it writes, its default sandbox and timeout.
3. Add a `role_defaults` row (executor, model, fallback) and, if needed, an `escalation` entry.
4. Say in team-pm when the PM spawns it.

## Adding an executor

1. Install it and add it under `executors` in `executors.json`: `kind`, binary, models, how
   it maps `full` / `read-only` / `restricted`.
2. Teach `run-lane.mjs` its argv, how to pass the prompt (stdin is best), and how to get the
   final message out of its output. Keep the `result.json` shape.
3. Check `non-claude-adapter.md` still holds for it (MCP access to plane, file reads outside
   the working dir, hooks).
4. Smoke it read-only first, then on a throwaway worktree, before giving it a role default.
