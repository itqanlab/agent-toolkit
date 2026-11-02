# Changelog

Latest: https://agent-toolkit.itqanlab.com/s/plane-fleet/CHANGELOG.md

What changed in `plane-fleet`, newest version first. To see if a newer version exists, open the address above and compare its top version with the one installed.

## [2.9.1] - 2026-11-02

### Fixed

- `fleet gate-stamp check` read a stale re-run. `gh pr checks` keeps one row per check name. After a PR title edit it kept a re-run attempt of the old workflow run, which still carried the old title and failed, over the newer run that passed. The check said NOT READY while GitHub showed the PR as clean. It now also reads the PR's `statusCheckRollup` and, for each check name, uses the run with the highest workflow run id. An older passing run never hides a newer failure.

## [2.9.0] - 2026-11-01

Two waits that bought nothing. On one project every engineer or tester session built its slot from zero (worktree, install, database, migrate, seed, servers): 8 to 10 minutes of a 20 to 45 minute session. Then each group PR waited about 15 minutes for a CI job that re-ran the lint, typecheck, test and build the PM's own pre-push gate had just passed on the same commit.

### Added

- `fleet slot-template build|clone|status`: one migrated, seeded Postgres template per schema state. `build` makes `<prefix>_<key12>` from `origin/<trunk>` in a throwaway worktree with the configured commands. The key hashes the migration and seed files and the build commands, not the commit, so a template is reused until they change. A lock stops two builds at once, and only `keep` templates stay. `clone <slot> [--test]` drops the slot's DB (and its test DB) and copies the template in seconds. It touches only slot DBs named in `fleet.slots`, never the shared row's, and exits 3 when no ready template matches so the session runs its recipe. Off unless `fleet.slot_db_template.enabled`.
- `fleet gate-stamp post|check`: `post` puts a `local-gate` commit status on a SHA, only when HEAD is that SHA, the tracked tree is clean and the gate log shows success for it. `check --pr N` exits 0 when the PR head has the stamp and every check outside `ci.covered_by_local_gate` passed or skipped. A skip after a covered job was cancelled does not count as passed. Off while that list is empty.

### Changed

- Engineers and testers clone their slot DB with `fleet slot-template clone` and skip migrate and seed when it works. Otherwise they run the recipe.
- Before any migrate, seed, reset or e2e command, echo `DATABASE_URL` and every test URL, check each names your slot DB, and export each in its own statement. On one project a combined export left the test URL on its old value, and the test harness migrated the owner's shared DB.
- The PM rebuilds the template in the background after a group that changed migrations or seed.
- A group PR into the trunk may merge when `fleet gate-stamp check` passes, even while a covered job still runs. Never the release PR to production, and never when the head moved after the stamp. Trunk CI still runs everything and stays the deploy gate.

## [2.8.0] - 2026-11-01

Engineers and testers were paying for the same checks over and over. In one run a rework engineer pushed 4 times and ran the server e2e set 4 times, another engineer ran it 5 times, and three agents pushing at once held a 12-core machine at load 60 to 78.

### Added

- `fleet cache-server start|stop|status|env`: a small Nx remote cache on 127.0.0.1 (Nx 20.8+ self-hosted cache API), one per project, so every engineer, tester and group worktree reuses the others' lint, typecheck, unit-test and build results. Off unless `fleet.nx_cache_server.enabled`. `eval "$(fleet cache-server env --cwd <repo>)"` starts it and exports the two Nx variables. Oldest entries go past `max_gb` (default 20). Checked with two worktrees: the second got `[remote cache]`.

### Changed

- Push once per session, after the last clean review pass. Review fixes stay local commits. Every push runs the whole pre-push gate and starts PR CI.
- While working, run only the spec files you touched, never a whole project or suite, and nothing by hand right before a push.
- Never run the same tests twice on one commit. While fixing a failure, re-run only the failing spec; run the full needed set once, after the last change. A rework or tester round re-runs only what its new commits touch.
- Reports carry the push count and the number of full server or browser spec-set runs.
- Testers push their test commits once, together.
- Sharing one Nx cache folder across worktrees does not help on Nx 22 (each worktree's database ignores entries it did not write), which is why the cache server exists.
- `--skipNxCache` is for a result that looks wrong for the change, not for every green: cached lint, unit tests and build are real results.
- If the cache server is down, Nx runs the task and still exits 1 (`Failed to send request ... /v1/cache`). The brief says to restart the server and run again, never to skip the hook.

## [2.7.0] - 2026-11-01

The fleet now checks itself while it runs. In one night's run the PM spent more than every agent together, mostly by carrying big outputs in its context. One engineer ran 576 tool calls on one UI ticket, a finished agent kept sending its report, and two tickets went to rework because of the ticket text.

### Added

- `fleet retro [--since ISO | --hours N] [--cwd repo] [--json]`: per ticket rounds, spend, tool calls, time and outcome, totals, the PM's share and context per call, rework and its causes, lanes and the Codex burn rate, then numbered findings, each with a cause, a fix and who owns it (pm, toolkit, owner). Exit 3 on an alert. A finding seen in the previous window is marked REPEAT. Thresholds and levels are set under `fleet.retro` in config.
- The PM's `retro` skill: one watcher runs the retro every 30 minutes, and again after each group merge and at the end of a run. The PM says each finding to the owner in one line, applies `pm` fixes at once and logs them as `retro_fix`, and proposes the rest with evidence.
- `fleet findings <file>`: the final findings block of a `codex review` or `codex exec` transcript, deduplicated, with one count line. Exit 3 on an open P1 or P2, 4 when the review did not finish.
- `fleet watch --stop-prefix <prefix>` stops every live watcher whose name starts with it.

### Changed

- The PM runs with auto-compact near 150k. Its state lives in Plane, the resume note and `fleet status`.
- Every review transcript (the engineer's passes, the PM's focused review, the group review) goes to a file and is read only through `fleet findings`.
- Engineers stop at a soft cap, 3 self-review passes or about 300 tool calls, and report `CAP` with what is done, what is open and the findings left. Testers stop at about 300 tool calls. The PM decides the next step.
- Engineers and testers stop every background job they started before the final report. Watch names start with the ticket id.
- An out-of-scope P1 is never pushed silently: the engineer comments the P1 and its scope argument and reports `In Review · needs PM scope call`. The PM decides before a tester starts.
- Tickets with screenshots, visual baselines or e2e checks on counts and dates must say how each shot gets fresh data, a test clock and no leftovers, and ask for N unchanged reruns green.
- Pre-pick triage: a missing cited path, or a named file, setting, preset or config that does not exist, sends the ticket to the planner to fix the text before anyone claims it. The planner checks each named thing exists before filing.
- Merge groups stay small (about 5) when they carry a shared UI or dependency change, since per-PR CI skips most jobs on drafts.

### Fixed

- `fleet log add` refuses a row that repeats one already in the log (same agent id and outcome, or same project, ticket, role, executor and outcome within 10 minutes). `--force` logs a real second session.
- Backfilled usage rows keep the failure cause and task kind of the row they copy, so a test failure no longer looks like a second failure without a cause.

## [2.6.0] - 2026-11-01

Two fixes from one night's run: the machine gate held every spawn for 3 hours on a Mac that had plenty of free memory, and one engineer left 28 copies of the same wait running.

### Added

- `fleet watch <name> --until '<test>'` and `fleet watch <name> -- <command>` run a background wait under a name. A second start under a name that is still running starts nothing and exits 75, with the holder's pid and output file. `--show`, `--list` and `--stop` read and end them. Engineers and testers wait only through it (standing brief), and the PM waits for CI with `fleet watch <TICKET>-ci -- gh run watch <id>`.
- The sweep flags duplicate waits: the same `until` or `while ... sleep` loop running more than once from the repo. `--kill` keeps the newest copy.

### Fixed

- On macOS the gate no longer reads "swap nearly full" as critical. macOS adds 1 GB swap files as it needs them, so less than 1 GB left is normal once any swap is in use, and pages from apps open for days sit there at no cost. Swap in use now counts as tight at most. The kernel's memory-pressure level (warn closes, critical is critical) and the swap-out rate since the last probe (`fleet.resources.swapout_mb_s`, default 5, 25 and 100 MB/s) decide. Linux, Windows and a Mac that gives no pressure reading keep the old rule.

## [2.5.0] - 2026-10-30

Fewer rework rounds. In one run, three tickets took 2 to 4 test rounds each. Every round fixed only the one case the tester named, a tester approval was overturned by the group review, and the bugs it found were already in the engineer's own notes.

### Added

- `fleet.tool_caches` config: a short `tmpdir` for Jest, Nx and temp files, so a repo on an external disk stops filling the internal one. Lanes and gates get `TMPDIR` from it, `fleet status` names a Jest cache over its limit, and `fleet-sweep.sh --caches` (or the launchd job from `fleet-cache-sweep.plist.template`) clears old caches, temp folders and Docker's build cache. A Jest cache had reached 26 GB.

### Changed

- High-risk PRs (money, schema, API, auth, privacy, audit): a tester APPROVED does not count until the PM's focused review is back clean. That review runs on a different executor from the engineer's. The PM reads the engineer's open notes first, and any note touching totals, balances, permissions or written data is a must-fix before the tester starts.
- Rework briefs ask for the whole class: every path, state and call site with the same shape, listed in the handoff as `class checked:`. Testers name the class with each finding, and the retest tries each one.
- A rework that misses the same class twice moves to a different, stronger executor.
- Two reworks is the cap, and hitting it counts as a fleet defect. Before a third round, the PM finds which step let it through (ticket, build, test, review or the PM's own briefs), logs it with a change to that step, and puts round 3 to the owner. Round 3 fixes the design, on a stronger executor.
- A tester finding the ticket never asked for is a PM scope decision with a rule for the whole class, never a one-case Rework.
- Rework and retest briefs point at one written case list on the ticket.
- When group PRs skip the full suites, the group builder runs every test file that covers changed code, not only the specs the tickets name.
- No release waits on one ticket by default. The PM tells the owner what holding costs, and a ticket with no user-visible change doesn't hold a release unless the owner says so.

## [2.4.1] - 2026-10-29

### Fixed

- 2.4.0 wrote the worktree folders into an untracked `.watchmanconfig` `ignore_dirs` at the repo root. watchman then treats the repo root as the project for every worktree, so Jest inside a worktree found no tests and a pre-push hook passed green with three failing tests. `fleet status` and `run-lane` no longer write any watcher config. The warning now says to drop the watch and turn watchman off for Jest, and the PM docs forbid the `ignore_dirs` fix. If 2.4.0 wrote the file in a repo, delete `<repo>/.watchmanconfig` and the `/.watchmanconfig` line in `.git/info/exclude`.

## [2.4.0] - 2026-10-29

A machine gate that works on any OS and is enforced in code. On 2026-10-29 a 12-core, 32 GB Mac reached a load of 72 with 900 MB of swap left, running only a terminal, Docker and four fleet sessions. The biggest process wasn't a fleet session. watchman, the file watcher Jest uses, held 11 GB: its watch on the repo root covered every worktree's node_modules, and lane churn made it re-crawl the tree 5,863 times. The old gate read one macOS number, ignored swap, and was prose the PM skipped: four sessions were spawned at load 26.

### Added

- `fleet resources` (`core/scripts/fleetres.py`, standard library only). It measures memory the OS can still hand out, swap against RAM, load per core (CPU busy on Windows) and free disk on macOS, Linux (cgroup limits included) and Windows. Limits scale to the machine and can be set in `fleet.resources`. Levels: ok, tight, closed, critical (exit 0 to 3). It names the biggest processes, marks the fleet's own, and says what each usually is and whether its fix is safe (watchman, Nx daemons, headless browsers, VMs, browser tabs, indexers). It warns when a file watcher is rooted over the worktrees.
- "Room for N heavy": how many more engineers or testers with a server, Jest or a browser the machine can take, from free memory less a reserve, capped by cores and `max_heavy`.
- `fleet resources --wait`: blocks until the gate opens, at most 4 minutes. Briefs use it before Jest, Playwright or a server, in place of `uptime` arithmetic.
- `--gate heavy|light` for scripts.
- Briefs run Jest with `--no-watchman`.

### Changed

- `run-lane` defers a lane while the gate won't admit it (exit 75, `resources <level>` in the error). `--ignore-resources` skips the check.
- The usage-pacer hook holds an engineer or tester Claude spawn on the same rule, and any fleet spawn at critical. The owner can switch it off with `resources-off` in `PLANE_FLEET_HOME`.
- `fleet status` opens with a `machine:` line, the reasons, safe fixes for machine hogs, and watcher warnings.
- `fleet-sweep.sh` prints the machine gate instead of the macOS-only check. `--min-free-mem-pct` and `--min-disk-gb` still override it for one run.
- PM: a new hard rule, "never spawn past the machine gate", and a critical-level procedure: sweep, apply the safe fixes, tell the owner what is left, and only then stop the newest session's test run or server.
- Standing brief: "Share the machine" uses `fleet resources --wait`, and no session starts a file watcher in a worktree.

## [2.3.0] - 2026-10-28

Fewer rework rounds, and a machine that doesn't choke. Measured on one project from 2026-10-26 to 28 (34 tickets): only 12 shipped in one round and 14 took three or more. Rework took at least 15 of 25 engineer hours.

### Changed

- The engineer's self-review now loops on P2s as well as P1s. When the brief carries the PM's focused review prompt, the engineer runs that one too, until one full pass reports neither. A P2 the engineer thinks doesn't apply goes to the PM before the push; on money, privacy, auth and audit tickets it blocks (`engineering/engineer/skills/open-pr.md` §3b).
- For every finding, the engineer fixes the whole class: every writer of the field, every booking path, every caller, found by searching the whole repo. The sites checked go in the handoff, and the report line shows the focused pass count (`engineering/engineer/role.md` §6).
- The PM writes the focused review prompt into every engineer brief: the ticket's invariants, the findings deferred to other tickets, and the failure kinds that matter (`core/pm/skills/spawn.md`).
- The PM runs that review on every money, schema, API, privacy, auth and audit PR while the tester works, sends any finding to the running tester, and routes one Rework with everything instead of two (`core/pm/skills/spawn-tester.md` §4). On one project it found a P1 or P2 the tester's blind pass had missed on four PRs in a row.
- After a third round, a ticket isn't patched again. A fresh `opus` engineer rebuilds it against three to five written invariants, or the planner splits it (`core/pm/skills/pick.md` §2).
- A timed-out lane's commits are judged by the fallback engineer (keep, squash or rewrite) before anything is built on them (`core/pm/skills/spawn.md` §3, step 5).
- A failed group PR fixed in place: easy fixes push first, each investigation gets its own lane, every lane gets a check at 30 minutes, and at most one other heavy session runs meanwhile (`core/pm/skills/merge-queue.md` §5).
- The PM never sums up open findings as "nothing serious". Each one is named, with where it went (`core/pm/role.md` §7).

### Added

- A CPU load gate. No heavy spawn while the 1-minute load is over twice the core count, and at most 4 heavy sessions at once. Every session runs Jest at `--maxWorkers=2` and waits out a high load before starting Jest, Playwright or a server (`core/pm/skills/spawn-tester.md`, `engineering/references/standing-brief.md`). Four heavy lanes plus two pre-push hooks had taken a 12-core Mac to a load of 108.
- Ticket section §3c, invariants and every path they cover, required on money, concurrency and audit tickets. Rules the owner has to decide get decided there, not in review (`core/planner/skills/write-ticket.md` §3).

## [2.2.0] - 2026-10-26

### Changed

- Schema tickets build in parallel when the models they touch don't overlap. Before, one schema ticket held every other schema ticket from build to deploy, about 1.5 to 2 hours each. Only the merge is still serial: one schema PR per train, and the next one rebases and re-stamps its migration folder before it merges (`core/pm/skills/pick.md` §2, `merge-queue.md` §5).
- Engineer briefs on a schema ticket name the other schema tickets' models as off-limits and ask for an additive-only migration in its own folder. A migration that drops, renames or rewrites data still builds alone (`engineering/engineer/skills/investigate.md`).
- Testers take the client screenshot and attach it through the Plane MCP only. When the MCP refuses a local file, they save it to `~/.cache/plane-fleet/shots/<IDENTIFIER>-<n>.png` and name that path in the verdict comment. They never open Plane in a browser, never guess its web address, and never open a tunnel or upload host to get a public URL (`engineering/tester/skills/verdict.md`, `engineering/tester/role.md`, `core/references/non-claude-adapter.md`).

### Added

- `fleet.parallel_schema` in the project config: how many schema tickets may build at once. Default 2.

## [2.1.0] - 2026-10-26

### Added

- Antigravity as a lane executor (`fleet antigravity ...`, the `agy` CLI on a Google AI plan). Models: `gemini-4-argon`, `gemini-3.8-flash`, `claude-opus-5-5`, `claude-sonnet-5-5`, `gpt-oss-120b`, with `--effort`. Opt-in: no candidates list names it by default.
- A live meter for it: `agy -p /usage`, cached 5 minutes. Its three pools (Gemini, Claude and GPT, Argon) are judged apart, so `pick` and the lane gate look at the pool of the model being picked. `fleet budget check antigravity --model <m>` does the same by hand.
- `fleet antigravity-setup`, run once: registers Plane with agy through `fleet mcp-exec plane`, which reads the server entry from `~/.claude.json` at start so no key is copied, and links the lane guard plugin into agy.
- The lane guard, an agy `PreToolUse` hook that acts only in fleet lanes. agy cannot set tools per run and its own denials end a headless run, so every lane runs with skip-permissions and the guard denies browser tools, other MCP servers and, in read-only lanes, writes, unlisted commands and Plane writes. A denial reaches the model and the lane still ends on its report. `result.json` says whether the guard ran and what it denied.
- The adapter page covers Antigravity.

## [2.0.0] - 2026-10-25

### Breaking

- The plugin and its skill are renamed `plane-fleet` → `fleet`. Reinstall it under the new name. A linked install relinks `skills/plane-fleet` and each agent card.
- The fleet is organized in sections: `core/` (PM, planner, board specialist, scanner, solo mode, the `fleet` command, shared references), `engineering/` (engineer, tester, their references and scripts) and `social/` (planned). Every role is a folder with `role.md` and `skills/`, one file per thing it does, read only when that step comes.
- The role skills `team-pm`, `team-engineer`, `team-tester`, `team-ticket-writer` and `solo-ship` are gone as separate skills. Start the PM with `/plane-fleet run`; the others are role files reached through `fleet` (table in `SKILL.md`). The ticket writer is now the planner's `skills/write-ticket.md`.
- `scripts/lanes/run-lane.sh` is now the `fleet` command in `core/scripts/`, with `scripts/fleet` as its short path. The old path still forwards to it for this version.
- Agent cards sit in `agents/<section>/`. `fleet-plane` is renamed `fleet-board`. A plugin install names them `plane-fleet:<section>:<agent>`.

### Added

- `fleet-scanner`, a read-only agent for counting, triage and log reading on behalf of the PM and planner.
- A README per section.

### Changed

- Agent cards are short pointers; each role's procedure lives in its `role.md`.
- The engineer's, tester's and PM's long role files are split into skill files by their existing sections, text unchanged. Section numbers (`§3`) stay, and references between files name the file.
- The state folder keeps its name, `~/.config/plane-fleet` (`PLANE_FLEET_HOME`), so the log, cost cache and overrides carry over. Hooks and `cost` still recognize sessions and log rows from before the rename.

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
- Shape rules in `engineering/references/ticket-rules.md` §2: one outcome per ticket, end to end; never split by layer while under the ceiling; siblings on the same screen or component ship together.
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

- `engineering/scripts/fleet-sweep.sh` finds what finished or dead sessions left running (servers on free slots' ports, processes in removed worktrees, Nx daemons, old headless Chromium, wait loops that can never end) and stops it with `--kill`. It also prints a spawn gate on free memory and disk. The PM runs it before every spawn.
- `run-lane.sh report --project <p> --since <iso>`: tokens per Done ticket, first-pass approval, rework rounds and the share of Done work the client can see, for one run.
- `run-lane.sh log add --from-result <result.json>` takes a lane's tokens and duration from its own file. `selftest` checks the log round trip.
- Rework rounds by ticket kind in `engineering/references/ticket-rules.md`.

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
