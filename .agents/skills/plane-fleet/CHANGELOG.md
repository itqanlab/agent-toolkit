# Changelog

Latest: https://agent-toolkit.itqanlab.com/s/plane-fleet/CHANGELOG.md

What changed in `plane-fleet`, newest version first. To see if a newer version exists, open the address above and compare its top version with the one installed.

## [1.6.0] - 2026-10-25

### Added

- `hooks/pm-recompact.py`, a `SessionStart` hook on `compact`: in a PM session it adds the live `run-lane.sh status` and the PM's hard rules to the compacted context, so the PM continues from facts, not from the summary.

### Changed

- The PM runs with `claude --autocompact 300k`. Its context grew about 1.3k tokens a call, to 650k by call 400, and calls over 400k were 48% of PM spend; the default window on a 1M model compacts near 967k.

## [1.5.0] - 2026-10-25

### Added

- `hooks/cache-keeper.py`: in fleet agents, refuses a foreground Bash timeout over 270000 ms and a Monitor deadline over 270000 ms (or none), and tells the agent to run the job in the background and check it every 4 minutes. An agent's prompt cache lives 5 minutes; waits past it made the next call rewrite the whole context, 12% of agent spend over a month and 24% in its last week. Refusals are logged; `cache-keeper-off` turns it off. `cost` shows the refusals next to the rewrite cost.
- `run-lane.sh status`: budget, slots and who holds them, lanes running and just ended (a dead lane is flagged), open PRs with required checks, labels and mergeability, trunk CI, and worktrees with no open PR, in one call. The PM used about 2,000 separate calls a month for these.

### Changed

- The standing brief limits every wait to 4 minutes and says how to wait longer.
- The PM never reads product code, runs builds or tests, or queries a database itself: 37% of its spend went there, on a context of 300k tokens and more. It reads the fleet with `status` and waits for CI with `gh run watch` in the background.
- On a linked install, register `cache-keeper.py` in user settings like the pacer (README).

## [1.4.0] - 2026-10-25

### Added

- `run-lane.sh free-models refresh` discovers the free models opencode serves today: no cost, tool calls, and at least `min_context`. It keeps each model's first and last day seen in `{state_home}/free-models.json`. `run-lane.sh free-models` lists them. New free models appear almost daily, some only for a short trial; 2 of the 6 listed on 2026-10-22 were gone three days later.
- `free_model_policy` in the registry: the roles that may use free models (default `scan`; a free tier may keep the prompt), the providers to ask, and how old a list may be.

### Changed

- `pick` adds every live free model as a challenger for the allowed roles, and an experiment tries the newest untried one first. A model that is no longer served drops out. Every other role loses free models, whatever a list says.
- `run-lane` refuses a free model outside the allowed roles or outside a read-only sandbox.
- The registry's static `free_models` list is only a fallback when no discovery is fresh.
- The PM runs `free-models refresh` in preflight.

## [1.3.0] - 2026-10-25

### Added

- `run-lane.sh cost`: what tickets really cost and how long they took, read from the Claude Code session files of the PM and its agents, the lanes' usage and GitHub merge times. Per merged ticket: cost, agent + PM share, first spawn to merge, hours agents worked; cost by role and by rework rounds; where the money goes (cache reads and writes, cache rewrites after a wait, first-call context, the PM's calls and context). `--ticket` prints one ticket's sessions in order, `--json` gives the data.
- `cost --backfill [--dry-run]` writes the real usage onto Claude spawn rows, so the scoreboard compares Claude and lanes on the same tokens.
- A `prices` block in the executor registry: API list prices per model, used only by `cost`. A model without a price shows tokens only.
- `log add --cause missed|ticket|spec_changed|environment`, required on every `verify_fail`. Of 114 test failures logged before this, none had a cause.
- `fleet.cost.claude_project_dirs` in the project config, for a repo whose old sessions sit under another folder name.

### Changed

- The PM logs a Claude spawn's `agent_id` and duration, not its `tokens`, names every spawn `<role> <TICKET>`, and runs `cost --backfill` and `cost` in preflight.

### Fixed

- The `tokens` a Claude spawn row carried is the size of the agent's last call, not its spend: measured 2026-10-25, a median engineer session processed 9.8M tokens and a tester 14.3M, 44 and 56 times the logged figure. The docs that built cost claims on it are corrected: the agent types' start is about 17k tokens of context against 72k for `general-purpose` (1.2.0 said 23k against 40k), and the fixed cost of a ticket is now given in measured dollars.
- `cost` keeps a summary of each session it reads, so a session still counts after Claude Code deletes its file (30 days by default).
- A repo that moved had its old run-log rows counted twice: the copy under the new Claude projects folder got a new `source_key`. On one project that was 459 of 1,442 rows, so the scoreboard, reports and promotions worked on doubled samples, and `seed` would copy the rows in again. A legacy row's identity no longer includes the folder.

## [1.2.0] - 2026-10-25

### Added

- Four agent types in `agents/`: `fleet-planner` plans right-sized tickets, `fleet-plane` files and reshapes them on Plane, `fleet-engineer` and `fleet-tester` run the existing roles. Each carries only the tools its role uses. Measured on one project: a spawn starts at about 23k tokens, against about 40k for `general-purpose`.
- Shape rules in `references/ticket-rules.md` §2: one outcome per ticket, end to end; never split by layer while under the ceiling; siblings on the same screen or component ship together.
- opencode lanes can use opencode's free models and the Z.ai coding plan as `provider/model`. Free models cost 0 in the cost units. Model families ignore the provider prefix.
- `disable_plugins` in the executor registry turns off Codex plugins in a lane. The browser and computer-use plugins bring `cua_repl`, which drives the owner's real Chrome and desktop.
- Every lane writes a small status file under `{state_home}/lanes/`, so a status view can list live and finished lanes without knowing each lane's `--out`.

### Changed

- The PM spawns `fleet-engineer` and `fleet-tester` by `subagent_type`, and sends new work through the planner and the Plane specialist instead of writing tickets itself.
- The ticket floor is about 150 changed lines, up from 50.
- The usage pacer also gates spawns of the four agent types.
- `fleet-sweep.sh` finds slot scratch dirs by `fleet.slot_scratch_prefix` (default `/tmp/<identifier>-slot-`), not one hard-coded project name.
- Examples in the rules and roles name no project.
- Effort is part of a candidate: `executor:model@effort` is scored, explored and promoted on its own. `pick` returns it, `log add --effort` and lane results record it, and opencode lanes pass it as `--variant`.
- Roles on another coding CLI never open Plane in a browser, never control the owner's desktop or browser, and never upload a file to an outside host to get a link. An attachment the MCP refuses stays local.

### Fixed

- opencode lanes logged no tokens: the runner now sums opencode's per-step token counts, so their cost and size show on the scoreboard.
- A row logged with kind `*` was counted twice on the scoreboard.

## [1.1.0] - 2026-10-15

### Added

- `scripts/fleet-sweep.sh` finds what finished or dead sessions left running (servers on free slots' ports, processes in removed worktrees, Nx daemons, old headless Chromium, wait loops that can never end) and stops it with `--kill`. It also prints a spawn gate on free memory and disk. The PM runs it before every spawn.
- `run-lane.sh report --project <p> --since <iso>`: tokens per Done ticket, first-pass approval, rework rounds and the share of Done work the client can see, for one run.
- `run-lane.sh log add --from-result <result.json>` takes a lane's tokens and duration from its own file. `selftest` checks the log round trip.
- Rework rounds by ticket kind in `references/ticket-rules.md`.

### Changed

- Testers run targeted specs only. The PM's group PR runs the full server and browser suites, opened as a draft, labelled, then marked ready, so CI sees the label.
- The standing brief asks every session to leave nothing running: one browser per session, closed in a finally, no Nx daemon, and a teardown that checks ports, processes and daemons.

### Fixed

- `log add --set` dropped its values on spawn rows, so the outcomes log had outcomes but no tokens or durations.

## [1.0.0] - 2026-10-09

### Added

- Five roles that work a Plane board together: a PM that claims tickets oldest first and runs the merge queue, engineers that each take one ticket to a draft PR in their own worktree and environment slot, testers that check a PR blind in the browser and then add tests, a ticket writer, and a solo mode for one session.
- Project config in `.plane/config.json`, with a private per-user override for client contacts, server names and timezone, and `run-lane.sh config` to print the merged result.
- Executors: any role can run as a sub-session or as a background lane on another coding CLI, picked per spawn by role, task kind and remaining budget. Lanes write a `result.json` with status, report line, duration and token use, and never commit on their own.
- One budget pacer for every executor: a hard stop and a pace rule on each meter, `pacer-off` and `pace-off` switches, and a lane that has no budget exits as deferred with a resume time.
- One outcomes log for all projects, a scoreboard per role, task kind and executor, and automatic promotion or demotion of executors, written to a decisions file the owner can veto.
- A hook that holds new fleet sub-sessions when the usage window is ahead of pace.
- A Plane MCP server declared by the plugin, run from source with `uvx`.
