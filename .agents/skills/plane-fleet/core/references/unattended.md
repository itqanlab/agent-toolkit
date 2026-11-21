# Unattended runs

> Read by the owner when setting a project up, and by the PM whenever `FLEET_UNATTENDED=1` is set.
> The tools are `core/scripts/fleet schedule` (`fleetschedule.py`) and the `unattended-guard` hook.

Tickets wait while no fleet session is open. On one project that was 30 to 46 percent of each
ticket's cycle time. A schedule starts the PM on a timer, so the queue keeps moving at night and
between sessions.

Production is never touched unattended. Everything else the owner allows is listed in the config,
and a hook enforces the list, so it doesn't rest on the PM remembering a rule.

## Setup

```jsonc
"fleet": {
  "unattended": {
    "command": "claude -p \"/plane-fleet run\" --permission-mode bypassPermissions",  // what one run starts, from the repo root
    "allow": ["merge", "client_message"],   // see below; [] = build and test only
    "max_hours": 3,                         // a run is stopped after this
    "attended_grace_minutes": 30            // skip a run while an attended PM wrote its heartbeat this recently
  },
  "alert_command": "notify-me \"$FLEET_ALERT\""   // called when an unattended run fails or times out
}
```

Then `fleet schedule install --every 2h` from the repo. On macOS it writes a launchd agent to
`~/Library/LaunchAgents/`, and on Linux a crontab line. `fleet schedule status` shows whether it
is installed, whether it is paused, and the last runs. `pause` and `resume` skip runs without
uninstalling. `remove` takes it out. The command must be able to run with nobody to answer a
permission prompt. How that's done depends on the agent CLI and the machine. Decide it
deliberately, because the guard below is the only gate left.

## What may run

| Step | Unattended |
|---|---|
| claim tickets, build, open PRs into the trunk, test, rework | always |
| intake (`fleet intake`), executor re-ranking (`fleet apply`) | always |
| group-merge into the trunk, and the dev deploy that follows | only with `"merge"` in `allow` |
| client messages (`client.channel`) | only with `"client_message"` in `allow` |
| a push, merge, PR or release tag on a production branch, a production deploy command | **never** |

A production branch is the `branch` of any `deploy.environments` entry named `prod` or
`production`, plus `git.prod_branch`. A production deploy command is that entry's
`deploy_command` or `command`.

## The guard

`hooks/unattended-guard.py` runs before every Bash, Skill and MCP call, and does nothing unless
`FLEET_UNATTENDED=1`, which `run-once` sets. It denies:

- `git push` to a production branch, including `HEAD:<branch>`, and a pushed release tag
- `gh pr create --base <production branch>`
- `gh pr merge` when `"merge"` is not allowed, when the PR's base is a production branch, or when
  the base can't be read
- a production deploy command
- the client channel's skill or tool when `"client_message"` is not allowed

A denial reaches the model as a reason, so the run goes on and records the blocked step.

## The PM in an unattended run

The normal role holds, with these changes:

- **No one to ask.** An owner question goes in with `fleet questions add`, and the ticket waits
  in its state. Pick other work. Never guess an owner decision.
- **A blocked step is not a failure.** Write it into the FLEET RESUME NOTE as owed (for example
  "group PR #N green, merge waits for the owner"), and go on with what is allowed.
- **Finish inside `max_hours`.** Stop claiming new tickets in the last 30 minutes. Leave
  everything in a state the next run or an attended session can pick up, and write the resume
  note before the end.
- **Heartbeat:** an attended PM runs `fleet schedule heartbeat` at each loop, so a scheduled run
  doesn't start beside it. Inside an unattended run the command does nothing.
