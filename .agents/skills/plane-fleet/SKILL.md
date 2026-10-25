---
name: plane-fleet
description: "Run a Plane board with a team of agent roles: a PM, parallel engineers, blind testers and a ticket writer. Triggers: 'run the board', 'work the tickets', 'work PROJ-12', 'test PR 212', 'write a ticket for this', 'ship the queue on my own', 'plane fleet'. Each engineer takes one ticket into its own git worktree and environment slot and opens a PR; a tester checks it blind in the browser, then reviews the code and adds tests; the PM claims tickets oldest first, merges approved PRs in groups, confirms CI and deploy, and moves tickets to Done. Roles can run on other coding CLIs too, picked per spawn by task kind and remaining budget, with an outcomes log that promotes the executor that does best. Needs a Plane MCP server and the GitHub CLI."
license: MIT
compatibility: "Needs git, the GitHub CLI (gh) signed in, python3 and node 18 or newer, and a Plane MCP server named plane (see README.md). Optional: other coding CLIs for non-default executors. Network access to Plane and GitHub."
metadata:
  author: itqanlab
  version: 1.5.0
  category: devops
  short: "Run a Plane board with PM, engineer and tester agents"
  starter: "run the board until the queue is empty"
---

# plane-fleet

A team of agent roles that works a Plane board the way a small engineering team does. Nobody
waits for anybody: engineers open PRs and move on, testers pick up any open PR at once, and the
PM lands what is approved and green.

## Pick the role, then read its file

Every role is a full skill under `roles/`. Read the one that matches the request and follow it
exactly. All paths in those files (`references/…`, `scripts/…`, `roles/…`) are relative to this
folder, the one that holds this file.

| The user asks | Role | File |
| --- | --- | --- |
| run the board, work the tickets, keep the fleet going | PM | `roles/team-pm/SKILL.md` |
| work one ticket to a PR | engineer | `roles/team-engineer/SKILL.md` |
| test one open PR | tester | `roles/team-tester/SKILL.md` |
| write or split tickets, turn notes into tickets | ticket writer | `roles/team-ticket-writer/SKILL.md` |
| ship the queue alone, one ticket at a time, no team | solo | `roles/solo-ship/SKILL.md` |

## Agents

Four agent types ship in the plugin's `agents/` folder. Each carries only the tools its role
uses, so its first call carries about 17k tokens of context instead of about 72k for
`general-purpose`, and so does every later call (measured 2026-10-25). On a linked install, link them into your agent's agents folder too
(`README.md`, Setup).

| Agent | Role | Writes |
| --- | --- | --- |
| `fleet-planner` | turns a request or the open board into right-sized tickets, one outcome each | a plan file, never Plane |
| `fleet-plane` | files the plan, merges siblings, sets relations, reports board health | Plane only |
| `fleet-engineer` | one ticket to an open PR (`roles/team-engineer`) | code, its own ticket |
| `fleet-tester` | one PR, blind check then unit and e2e tests (`roles/team-tester`) | tests, its own ticket |

The PM spawns engineers and testers as sub-sessions, one per ticket or PR. If you cannot start
sub-sessions, run `roles/solo-ship/SKILL.md` instead, or run one engineer or tester role by hand.

## What every role reads

- `references/standing-brief.md` — the boundaries every engineer and tester session keeps
- `references/ticket-rules.md` — when to file a ticket, and how big one may be
- `references/plane-api.md` — the Plane MCP calls and what a board read costs
- `references/config-schema.md` — the project config, and the private per-user override
- `references/usage-budget.md` — spending a usage window on purpose and stopping safely
- `references/notify.md` — telling the client, with a screenshot
- `references/executors.md` and `references/executors.json` — which program runs which role
- `references/non-claude-adapter.md` — what a role running on another coding CLI must know

## Project config

Each repo carries `.plane/config.json` (Plane project, trunk, quality gate, CI, deploy, slots).
Private values (client contact, server names, timezone) go in a per-user override outside the
repo. Print the merged result with:

```bash
scripts/lanes/run-lane.sh config --cwd <repo>
```

When the repo has no config yet, the PM and solo roles build it from the board and the repo.

## Executors, budget and the outcomes log

A role can run on another coding CLI as well as in a sub-session. `scripts/lanes/run-lane.sh`
picks the executor per spawn from the registry, by role, task kind and remaining budget; runs
non-default executors as background lanes with a timeout; logs every outcome to one user-level
log; and promotes a challenger that does better for less. Everything works with the shipped
defaults and no other CLI installed.

```bash
scripts/lanes/run-lane.sh pick --role engineer --kind api --cwd <repo>
scripts/lanes/run-lane.sh budget
scripts/lanes/run-lane.sh stats --role engineer
scripts/lanes/run-lane.sh cost --since 2026-10-01      # real spend and time per merged ticket
scripts/lanes/run-lane.sh cost --ticket PROJ-12        # one ticket's sessions in order
scripts/lanes/run-lane.sh free-models refresh          # today's free models, for read-only scans
```

The token counts the log keeps for Claude spawns are the size of each agent's last call, not
its spend. `cost` reads the spend from the session files themselves.

## Board tools

- `scripts/lanes/run-lane.sh status` — budget, slots, lanes, open PRs with required checks, trunk CI and leftover worktrees, in one call
- `scripts/board-drift.sh` — find tickets whose board state disagrees with git and GitHub
- `scripts/repo-scan.sh` — the repo half of the PM's pre-pick triage
- `scripts/git-tidy.sh` — clear merged local branches and stale worktrees
- `scripts/fleet-sweep.sh` — find and stop what finished sessions left running (servers, Chromium, Nx daemons) and check the memory and disk gate before a spawn

## Updates

This skill is versioned. Its version is `metadata.version` in the header of this file. `CHANGELOG.md` in this folder lists what changed in each version, newest first.

To check for a newer version, open the address on the `Latest:` line of `CHANGELOG.md` and compare its top version with the installed one. If the newer one is ahead, read every entry between the two and tell the user what changed before anything is updated. A `Breaking` section means the user has to do something. To update, reinstall the skill from its source repository, the same way it was installed.
