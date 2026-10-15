# Changelog

Latest: https://agent-toolkit.itqanlab.com/s/plane-fleet/CHANGELOG.md

What changed in `plane-fleet`, newest version first. To see if a newer version exists, open the address above and compare its top version with the one installed.

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
