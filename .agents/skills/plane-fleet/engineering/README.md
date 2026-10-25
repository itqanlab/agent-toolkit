# engineering

Ships code: one ticket becomes one reviewed, tested PR, merged in a group and deployed.

| Folder | Holds |
| --- | --- |
| `engineer/` | one ticket to a draft PR, in its own worktree and environment slot. `role.md` + `skills/` |
| `tester/` | one PR checked blind in the browser, then its diff reviewed and tests written. `role.md` + `skills/` |
| `references/` | the standing brief every engineer and tester keeps, ticket size and filing rules, client notes |
| `scripts/` | board drift against git, pre-pick triage, git tidy, the sweep for leftover servers and browsers |

Pipeline today: plan, build (engineer), verify (tester), ship (the PM's merge queue and deploy),
notify. It is still written into the PM's skills; phase 1 moves it into a pipeline file here.
