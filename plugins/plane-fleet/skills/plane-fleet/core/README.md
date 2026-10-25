# core

Runs the fleet, whatever kind of work it does. Every other section relies on it.

| Folder | Holds |
| --- | --- |
| `pm/` | the PM: your main session, which picks, spawns, merges and reports. `role.md` + `skills/` |
| `planner/` | turns requests and the board into right-sized tickets; `skills/write-ticket.md` writes their bodies |
| `board/` | the board specialist: files, merges, relates and reports tickets on Plane |
| `scanner/` | read-only counting, triage and log reading, so the PM's large context does not carry it |
| `solo/` | one session doing the whole loop, for agents that cannot start sub-sessions |
| `references/` | config schema, Plane calls, usage budget, executor registry and prices, the non-Claude adapter |
| `scripts/` | the `fleet` command and its Python and Node modules |

The PM's merge, deploy and tester-spawn skills are steps of the engineering pipeline. They stay
in `pm/skills/` until the PM becomes a step runner (design doc, phase 1); then they move into
`engineering/`.
