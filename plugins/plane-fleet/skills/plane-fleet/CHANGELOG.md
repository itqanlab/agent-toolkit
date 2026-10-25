# Changelog

Latest: https://agent-toolkit.itqanlab.com/s/plane-fleet/CHANGELOG.md

What changed in `plane-fleet`, newest version first. To see if a newer version exists, open the address above and compare its top version with the one installed.

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
